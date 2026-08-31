"""Block-3 Package-1 M-B: composition-root ownership of durable execution paths.

Block-2 left three durable execution stores — the idempotency store, the audit
event store, and the transaction journal — constructing themselves inside
ExecutionManager from CWD-relative defaults under ``memory_data/``. The
composition root already owned the durable *financial* state directory, so one
configured ``state_directory`` produced two different persistence roots, and
the same configuration behaved differently depending on where the process
happened to be started: duplicate-request detection, unresolved-journal
detection, and the audit chain all followed the CWD instead of the
configuration.

These tests prove the corrected ownership: every durable path Atlas execution
depends on is derived by ``core.application`` from one configured root, the
canonical runtime never falls back to the ExecutionManager defaults, and
restart behaviour depends on configuration alone.

Stored formats and file names are unchanged; only who chooses the location is.
"""

from __future__ import annotations

import json
import os
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

import pytest

from core.application import (
    CAPITAL_RESERVATION_STATE_FILE,
    EXECUTION_AUDIT_EVENT_FILE,
    EXECUTION_FINANCIAL_STATE_FILE,
    EXECUTION_IDEMPOTENCY_STATE_FILE,
    EXECUTION_TRANSACTION_JOURNAL_FILE,
    PAPER_TRADE_BOOK_FILE,
    RISK_ACCOUNTING_STATE_FILE,
    AtlasApplication,
)
from core.audit_event_store import AuditEventStore
from core.execution_idempotency_store import ExecutionIdempotencyStore
from core.execution_manager import ExecutionManager
from core.execution_models import ExecutionRequest
from core.execution_transaction_journal import (
    CommitOutcome,
    ExecutionTransactionJournal,
)
from core.risk_engine import RiskState

from tests.test_block2_risk_service_composition_wiring import (
    POLICY_VERSION,
    high_bucket_allocation,
    seed_valid_state,
)


D = Decimal


# --------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------


def application(state_dir) -> AtlasApplication:
    return AtlasApplication(state_directory=state_dir)


@pytest.fixture
def state_dir(tmp_path):
    directory = tmp_path / "state"
    seed_valid_state(directory)
    return directory


def risk_state() -> RiskState:
    return RiskState(
        (),
        D("0"),
        D("0"),
        D("10000"),
        D("10000"),
        True,
        datetime.now(UTC).date().isoformat(),
        POLICY_VERSION,
    )


def buy_decision(app: AtlasApplication, *, request_id: str = "r1") -> dict:
    return ExecutionRequest(
        "BTCUSDT",
        "BUY",
        10,
        str(high_bucket_allocation(app)),
        confidence=90,
        risk="HIGH",
        request_id=request_id,
    ).to_dict()


def execute(app: AtlasApplication, *, request_id: str = "r1") -> dict:
    app.execution.start()
    return app.execution.execute(buy_decision(app, request_id=request_id), risk_state())


def durable_paths(app: AtlasApplication) -> dict[str, object]:
    return {
        "risk_accounting": app.risk_state_store.path,
        "capital_reservations": app.reservation_ledger.store.path,
        "execution_financial": app.portfolio_foundation.store.path,
        "idempotency": app.execution.idempotency_store.file_path,
        "transaction_journal": app.execution.transaction_journal.file_path,
        "audit": app.execution.audit_store.file_path,
        "paper_book": Path(app.paper_trader.filename),
    }


# --------------------------------------------------------------------------
# T7 — every durable path is derived from the configured root
# --------------------------------------------------------------------------


def test_all_durable_execution_paths_resolve_under_the_configured_root(state_dir):
    app = application(state_dir)

    assert durable_paths(app) == {
        "risk_accounting": state_dir / RISK_ACCOUNTING_STATE_FILE,
        "capital_reservations": state_dir / CAPITAL_RESERVATION_STATE_FILE,
        "execution_financial": state_dir / EXECUTION_FINANCIAL_STATE_FILE,
        "idempotency": state_dir / EXECUTION_IDEMPOTENCY_STATE_FILE,
        "transaction_journal": state_dir / EXECUTION_TRANSACTION_JOURNAL_FILE,
        "audit": state_dir / EXECUTION_AUDIT_EVENT_FILE,
        "paper_book": state_dir / PAPER_TRADE_BOOK_FILE,
    }


def test_no_durable_execution_file_is_written_outside_the_configured_root(state_dir):
    app = application(state_dir)

    execute(app)

    for path in durable_paths(app).values():
        assert state_dir in path.parents or path.parent == state_dir


def test_the_default_state_root_is_absolute_and_not_cwd_relative():
    from core.application import DEFAULT_STATE_DIRECTORY

    assert DEFAULT_STATE_DIRECTORY.is_absolute()


# --------------------------------------------------------------------------
# T8 — CWD cannot change durable behaviour
# --------------------------------------------------------------------------


def test_durable_paths_are_identical_from_different_working_directories(
    state_dir, tmp_path, monkeypatch
):
    first_cwd = tmp_path / "cwd_a"
    second_cwd = tmp_path / "cwd_b"
    first_cwd.mkdir()
    second_cwd.mkdir()

    monkeypatch.chdir(first_cwd)
    first = durable_paths(application(state_dir))

    monkeypatch.chdir(second_cwd)
    second = durable_paths(application(state_dir))

    assert first == second


def test_execution_from_one_cwd_is_visible_from_another(
    state_dir, tmp_path, monkeypatch
):
    first_cwd = tmp_path / "cwd_a"
    second_cwd = tmp_path / "cwd_b"
    first_cwd.mkdir()
    second_cwd.mkdir()

    monkeypatch.chdir(first_cwd)
    first = application(state_dir)
    assert execute(first)["status"] == "PAPER_EXECUTED"

    monkeypatch.chdir(second_cwd)
    second = application(state_dir)

    assert "r1" in second.execution.completed_request_results
    assert second.execution.transaction_journal.entries["r1"]["state"] == (
        CommitOutcome.COMMITTED.value
    )


def test_no_durable_state_leaks_into_the_working_directory(
    state_dir, tmp_path, monkeypatch
):
    """Nothing durable — including the paper book — appears beside the process."""
    workdir = tmp_path / "cwd_a"
    workdir.mkdir()
    monkeypatch.chdir(workdir)

    execute(application(state_dir))

    assert list(workdir.rglob("*")) == []


# --------------------------------------------------------------------------
# T9 — duplicate-request semantics survive a restart
# --------------------------------------------------------------------------


def test_completed_request_is_still_a_duplicate_after_restart(state_dir):
    first = application(state_dir)
    original = execute(first)
    assert original["status"] == "PAPER_EXECUTED"

    restarted = application(state_dir)
    duplicate = execute(restarted)

    assert duplicate["duplicate_reason"] == "DUPLICATE_REQUEST_COMPLETED"
    assert duplicate["idempotency"]["cache_hit"] is True
    assert duplicate["execution_id"] == original["execution_id"]


def test_restart_loads_the_persisted_idempotency_record(state_dir):
    execute(application(state_dir))

    restarted = application(state_dir)

    assert restarted.execution.stats["persistent_records_loaded"] == 1
    assert "r1" in restarted.execution.completed_request_results


# --------------------------------------------------------------------------
# T10 — unresolved journal survives a restart
# --------------------------------------------------------------------------


def seed_unresolved_journal(state_dir, request_id: str = "stuck") -> None:
    """Leave a PREPARED entry behind using the journal's own contract."""
    journal = ExecutionTransactionJournal(
        state_dir / EXECUTION_TRANSACTION_JOURNAL_FILE
    )
    assert journal.prepare(request_id, {"symbol": "BTCUSDT", "action": "BUY"}) is True


def test_unresolved_journal_blocks_a_restarted_runtime(state_dir):
    seed_unresolved_journal(state_dir)

    restarted = application(state_dir)
    result = execute(restarted)

    assert result["status"] == "RECOVERY_REQUIRED"
    assert restarted.execution.execution_halted is True
    assert restarted.execution.recovery_required is True
    assert restarted.execution.reservation_ledger.get("r1") is None
    assert restarted.execution._risk_admissions == {}


def test_unresolved_journal_detection_does_not_depend_on_cwd(
    state_dir, tmp_path, monkeypatch
):
    seed_unresolved_journal(state_dir)

    for name in ("cwd_a", "cwd_b"):
        workdir = tmp_path / name
        workdir.mkdir()
        monkeypatch.chdir(workdir)

        app = application(state_dir)

        assert app.transaction_journal.has_unresolved() is True
        assert execute(app)["status"] == "RECOVERY_REQUIRED"


def test_an_interrupted_execution_still_blocks_after_restart(state_dir):
    app = application(state_dir)
    app.execution.start()

    # Scoped to the durable read that follows the paper side effect: Block-5A
    # also reads the snapshot during risk_check to derive the canonical
    # RiskState, and failing there would refuse admission rather than
    # interrupt an execution that has already crossed the boundary.
    durable_snapshot = app.execution.portfolio_foundation.snapshot

    def failing_snapshot(*args, **kwargs):
        if app.execution._execution_side_effect_ids:
            raise RuntimeError("durable snapshot read failed")
        return durable_snapshot(*args, **kwargs)

    app.execution.portfolio_foundation.snapshot = failing_snapshot
    app.execution.execute(buy_decision(app), risk_state())

    restarted = application(state_dir)

    assert restarted.transaction_journal.has_unresolved() is True
    assert execute(restarted, request_id="r2")["status"] == "RECOVERY_REQUIRED"


# --------------------------------------------------------------------------
# T11 — the canonical root never relies on the ExecutionManager defaults
# --------------------------------------------------------------------------


def test_composition_root_injects_every_durable_execution_store(state_dir):
    app = application(state_dir)

    assert app.execution.idempotency_store is app.idempotency_store
    assert app.execution.transaction_journal is app.transaction_journal
    assert app.execution.audit_store is app.audit_store


def test_canonical_runtime_uses_no_cwd_relative_store_default(state_dir):
    app = application(state_dir)

    defaults = {
        app.execution.idempotency_store.file_path: (
            ExecutionIdempotencyStore.DEFAULT_FILE
        ),
        app.execution.transaction_journal.file_path: (
            ExecutionTransactionJournal.DEFAULT_FILE
        ),
        app.execution.audit_store.file_path: AuditEventStore.DEFAULT_FILE,
    }

    for resolved, default in defaults.items():
        assert resolved.is_absolute()
        assert resolved != type(resolved)(default)


def test_durable_execution_stores_are_registered_once_in_the_container(state_dir):
    app = application(state_dir)

    assert app.container.get(ExecutionIdempotencyStore) is app.idempotency_store
    assert app.container.get(ExecutionTransactionJournal) is app.transaction_journal
    assert app.container.get(AuditEventStore) is app.audit_store


def test_stores_are_not_recreated_per_request(state_dir):
    app = application(state_dir)
    before = (
        app.execution.idempotency_store,
        app.execution.transaction_journal,
        app.execution.audit_store,
    )

    execute(app, request_id="r1")
    app.execution.execute(buy_decision(app, request_id="r2"), risk_state())

    assert (
        app.execution.idempotency_store,
        app.execution.transaction_journal,
        app.execution.audit_store,
    ) == before


# --------------------------------------------------------------------------
# T12 — corrupt durable execution state fails closed
# --------------------------------------------------------------------------


def test_corrupt_transaction_journal_denies_execution(state_dir):
    (state_dir / EXECUTION_TRANSACTION_JOURNAL_FILE).write_text(
        "{ not json", encoding="utf-8"
    )

    app = application(state_dir)
    result = execute(app)

    assert app.transaction_journal.load_failed is True
    assert app.transaction_journal.has_unresolved() is True
    assert result["success"] is False
    assert result["status"] == "RECOVERY_REQUIRED"
    assert app.execution.reservation_ledger.get("r1") is None
    assert app.execution._risk_admissions == {}


def test_corrupt_idempotency_store_denies_execution(state_dir):
    """A present-but-unreadable record file is never treated as a clean one."""
    (state_dir / EXECUTION_IDEMPOTENCY_STATE_FILE).write_text(
        "{ not json", encoding="utf-8"
    )

    app = application(state_dir)
    result = execute(app)

    assert app.execution.completed_request_results == {}
    assert result["success"] is False
    assert result["status"] == "RECOVERY_REQUIRED"
    assert app.execution.reservation_ledger.get("r1") is None
    assert app.execution._risk_admissions == {}


def test_a_corrupt_journal_grants_no_buy_authority(state_dir):
    (state_dir / EXECUTION_TRANSACTION_JOURNAL_FILE).write_text(
        json.dumps({"entries": "not-a-mapping"}), encoding="utf-8"
    )

    app = application(state_dir)
    result = execute(app)

    assert result["success"] is False
    assert app.execution.execution_halted is True
    assert app.portfolio_foundation.snapshot()["positions"] == {}


# --------------------------------------------------------------------------
# H-2 — the paper book follows the same configured root
# --------------------------------------------------------------------------


def test_paper_book_resolves_under_the_configured_root(state_dir):
    app = application(state_dir)

    assert Path(app.paper_trader.filename) == state_dir / PAPER_TRADE_BOOK_FILE
    assert Path(app.paper_trader.filename).is_absolute()


def test_paper_book_is_written_under_the_configured_root(state_dir):
    app = application(state_dir)

    assert execute(app)["status"] == "PAPER_EXECUTED"

    book = state_dir / PAPER_TRADE_BOOK_FILE
    assert book.exists()
    assert json.loads(book.read_text(encoding="utf-8"))["positions"]


def test_paper_book_location_is_identical_from_different_cwds(
    state_dir, tmp_path, monkeypatch
):
    locations = []

    for name in ("cwd_a", "cwd_b"):
        workdir = tmp_path / name
        workdir.mkdir()
        monkeypatch.chdir(workdir)
        locations.append(Path(application(state_dir).paper_trader.filename))

    assert locations[0] == locations[1]


def test_paper_positions_survive_a_restart_against_the_same_root(state_dir):
    first = application(state_dir)
    assert execute(first)["status"] == "PAPER_EXECUTED"
    opened = dict(first.paper_trader.positions)
    assert opened

    restarted = application(state_dir)

    assert restarted.paper_trader.positions == opened
    assert restarted.paper_trader.history == first.paper_trader.history


def test_no_second_paper_book_is_created_beside_the_process(
    state_dir, tmp_path, monkeypatch
):
    workdir = tmp_path / "cwd_a"
    workdir.mkdir()
    monkeypatch.chdir(workdir)

    execute(application(state_dir))

    assert not (workdir / PAPER_TRADE_BOOK_FILE).exists()
    assert (state_dir / PAPER_TRADE_BOOK_FILE).exists()


def test_paper_book_directory_is_created_when_missing(tmp_path):
    """The composition root may name a root that does not exist yet."""
    absent = tmp_path / "absent"
    app = AtlasApplication(state_directory=absent)

    app.paper_trader.save()

    assert (absent / PAPER_TRADE_BOOK_FILE).exists()


# --------------------------------------------------------------------------
# PAPER / LIVE
# --------------------------------------------------------------------------


def test_path_ownership_does_not_activate_live(state_dir):
    app = application(state_dir)

    assert app.execution_mode == ExecutionManager.MODE_PAPER
    assert app.execution.mode == ExecutionManager.MODE_PAPER
    assert app.execution.live_execution_enabled is False
    assert os.environ.get("ATLAS_LIVE_TRADING") in (None, "", "0", "false", "False")
