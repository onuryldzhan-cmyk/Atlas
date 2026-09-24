"""Execution-authority crash recovery - audit findings F-1, F-2, F-3, F-5, F-6.

The 2026-09-24 reconciliation audit
(checkpoints/20260924T195526Z_execution-financial-state-reconciliation-audit.md)
killed a real PAPER runtime at every commit boundary of one BUY (K0-K6) and
replayed a transient-failure retry (E1) as disposable scripts. This module is
those probes made permanent.

A crash is simulated in-process by raising ``SimulatedCrash`` - a
``BaseException`` - at the boundary. Every ``except Exception`` handler in the
execution path lets it through, exactly as ``os._exit`` would; the only
``finally`` blocks it runs release in-memory claims, never durable state. The
restart is a fresh ``AtlasApplication`` on the same state directory.

Every test runs against its own ``tmp_path`` state directory; nothing here can
reach the repository's real runtime state.
"""

from __future__ import annotations

import json
import subprocess
import sys
from decimal import Decimal
from pathlib import Path

import pytest

from core.application import (
    CAPITAL_RESERVATION_STATE_FILE,
    EXECUTION_APPLIED_EXECUTIONS_FILE,
    EXECUTION_CLOSED_POSITIONS_FILE,
    EXECUTION_FINANCIAL_STATE_FILE,
    EXECUTION_IDEMPOTENCY_STATE_FILE,
    EXECUTION_TRANSACTION_JOURNAL_FILE,
    AtlasApplication,
)
from core.capital_reservation import (
    CapitalReservationLedger,
    JsonReservationStore,
    ReservationStatus,
)
from core.execution_models import ExecutionRequest
from core.execution_portfolio_foundation import (
    AppliedExecutionArchiveStore,
    ClosedPositionArchiveStore,
    ExecutionPortfolioFoundation,
    FinancialStateStore,
)
from core.execution_transaction_journal import CommitOutcome, ExecutionTransactionJournal
from core.instrument_rules import InstrumentRules, InstrumentRuleset
from core.risk_engine import PositionExposure, RiskState

import tools.reconcile_execution_authorities as reconcile_module
from tools.reconcile_execution_authorities import (
    ReconciliationOutcome,
    RecoveryClass,
    reconcile,
)

from tests.test_block2_risk_service_composition_wiring import (
    POLICY_VERSION,
    high_bucket_allocation,
    seed_valid_state,
)

D = Decimal

REPOSITORY_ROOT = Path(__file__).resolve().parent.parent
RECONCILE_CLI_PATH = REPOSITORY_ROOT / "tools" / "reconcile_execution_authorities.py"

# Every durable file a recovery may touch; "nothing moved" compares all of them.
RECOVERY_FILES = (
    EXECUTION_TRANSACTION_JOURNAL_FILE,
    EXECUTION_IDEMPOTENCY_STATE_FILE,
    EXECUTION_FINANCIAL_STATE_FILE,
    EXECUTION_APPLIED_EXECUTIONS_FILE,
    EXECUTION_CLOSED_POSITIONS_FILE,
    CAPITAL_RESERVATION_STATE_FILE,
)


class SimulatedCrash(BaseException):
    """A process kill at a commit boundary: no ``except Exception`` sees it."""


# --------------------------------------------------------------------------
# runtime helpers
# --------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _isolated_roots(monkeypatch):
    # No telemetry/log root may leak in from the operator's environment.
    monkeypatch.delenv("ATLAS_LOG_DIRECTORY", raising=False)


def _app(state_dir: Path) -> AtlasApplication:
    app = AtlasApplication(
        state_directory=state_dir, evidence_directory=state_dir.parent / "evidence",
    )
    app.execution.start()
    return app


def _fresh_state(tmp_path: Path, *, held=None) -> Path:
    state_dir = tmp_path / "state"
    seed_valid_state(state_dir, held=held)
    return state_dir


def _risk_state(*positions) -> RiskState:
    from datetime import UTC, datetime

    return RiskState(
        tuple(positions), sum((p.quote_exposure for p in positions), D("0")),
        D("0"), D("10000"), D("10000"), True,
        datetime.now(UTC).date().isoformat(), POLICY_VERSION,
    )


def _buy(app: AtlasApplication, request_id: str = "r1") -> dict:
    decision = ExecutionRequest(
        "BTCUSDT", "BUY", 10, str(high_bucket_allocation(app)),
        confidence=90, risk="HIGH", request_id=request_id,
    ).to_dict()
    return app.execution.execute(decision, _risk_state())


def _full_exit_sell(app: AtlasApplication, request_id: str = "s1") -> dict:
    position = app.portfolio_foundation.snapshot()["positions"]["BTCUSDT"]
    exposure = D(position["base_quantity"]) * D(position["mark_price"])
    decision = ExecutionRequest(
        "BTCUSDT", "SELL", 10, format(exposure, "f"), confidence=90, risk="HIGH",
        request_id=request_id, reduce_only=True,
    ).to_dict()
    return app.execution.execute(
        decision,
        _risk_state(PositionExposure("BTCUSDT", D(position["base_quantity"]),
                                     D(position["mark_price"]), exposure)),
    )


def _crash_on(monkeypatch, target, name: str, *, after: bool = False) -> None:
    """Kill the process when ``target.name`` is called (or right after it returns)."""
    original = getattr(target, name)

    def crashing(*args, **kwargs):
        if after:
            original(*args, **kwargs)
        raise SimulatedCrash(name)

    monkeypatch.setattr(target, name, crashing)


def _run_until_crash(app: AtlasApplication, action) -> None:
    with pytest.raises(SimulatedCrash):
        action(app)


def _journal_state(state_dir: Path, request_id: str) -> str | None:
    entry = ExecutionTransactionJournal(state_dir / EXECUTION_TRANSACTION_JOURNAL_FILE).entries.get(request_id)
    return None if entry is None else entry["state"]


def _reservation(state_dir: Path, request_id: str):
    store = JsonReservationStore(state_dir / CAPITAL_RESERVATION_STATE_FILE)
    return {item.request_id: item for item in store.load()}.get(request_id)


def _foundation(state_dir: Path) -> ExecutionPortfolioFoundation:
    return ExecutionPortfolioFoundation(
        FinancialStateStore(state_dir / EXECUTION_FINANCIAL_STATE_FILE),
        applied_archive=AppliedExecutionArchiveStore(state_dir / EXECUTION_APPLIED_EXECUTIONS_FILE),
        closed_archive=ClosedPositionArchiveStore(state_dir / EXECUTION_CLOSED_POSITIONS_FILE),
    )


def _idempotency_record(state_dir: Path, request_id: str):
    from core.execution_idempotency_store import ExecutionIdempotencyStore

    return ExecutionIdempotencyStore(
        state_dir / EXECUTION_IDEMPOTENCY_STATE_FILE
    ).completed_requests.get(request_id)


def _snapshot(state_dir: Path) -> dict[str, bytes | None]:
    return {
        name: (state_dir / name).read_bytes() if (state_dir / name).exists() else None
        for name in RECOVERY_FILES
    }


def _recover(state_dir: Path, **kwargs):
    return reconcile(state_dir, apply=True, execution_mode="PAPER", **kwargs)


def _assert_restart_healthy(state_dir: Path) -> AtlasApplication:
    restarted = _app(state_dir)
    assert restarted.execution.execution_halted is False
    assert restarted.execution.recovery_required is False
    assert restarted.transaction_journal.has_unresolved() is False
    return restarted


def _baseline_position(tmp_path: Path) -> dict:
    """The durable position one uninterrupted BUY produces."""
    state_dir = tmp_path / "baseline" / "state"
    seed_valid_state(state_dir)
    app = _app(state_dir)
    assert _buy(app)["status"] == "PAPER_EXECUTED"
    return app.portfolio_foundation.snapshot()


# ==========================================================================
# K-matrix - the audit's crash windows, each proven halted then recovered
# ==========================================================================


def _crash_k1(app, monkeypatch):
    # After PREPARE, before anything else durable.
    _crash_on(monkeypatch, app.execution, "paper_execute")


def _crash_k3(app, monkeypatch):
    # apply_confirmed landed; the reservation commit never ran.
    _crash_on(monkeypatch, app.execution.reservation_ledger, "commit")


def _crash_k4(app, monkeypatch):
    # Reservation committed; the paper mirror never ran.
    _crash_on(monkeypatch, app.execution, "_mirror_paper_book")


def _crash_k5(app, monkeypatch):
    # Mirror projected; the idempotency record never landed.
    _crash_on(monkeypatch, app.execution, "_complete_request")


def _crash_k6(app, monkeypatch):
    # Idempotency recorded; the journal COMMITTED event never landed.
    _crash_on(monkeypatch, app.execution.transaction_journal, "mark_committed")


def test_k0_crash_before_prepare_leaves_no_journal_entry_and_startup_releases_the_orphan(
    tmp_path, monkeypatch,
):
    """K0 / F-2. Pre-fix: restart healthy but r1 stayed RESERVED forever."""
    state_dir = _fresh_state(tmp_path)
    app = _app(state_dir)
    _crash_on(monkeypatch, app.execution.transaction_journal, "prepare")
    _run_until_crash(app, _buy)

    assert _journal_state(state_dir, "r1") is None
    assert _reservation(state_dir, "r1").status is ReservationStatus.RESERVED

    restarted = _app(state_dir)

    assert restarted.execution.execution_halted is False
    assert _reservation(state_dir, "r1").status is ReservationStatus.RELEASED
    assert restarted.reservation_ledger.active_reserved_capital() == D("0")


def test_k0_then_same_request_retry_executes_once_on_a_fresh_reservation(tmp_path, monkeypatch):
    """F-2 + F-3: the released orphan is re-armed, not reused, by the retry."""
    state_dir = _fresh_state(tmp_path)
    app = _app(state_dir)
    _crash_on(monkeypatch, app.execution.transaction_journal, "prepare")
    _run_until_crash(app, _buy)

    restarted = _app(state_dir)
    result = _buy(restarted)

    assert result["status"] == "PAPER_EXECUTED"
    reservation = _reservation(state_dir, "r1")
    assert reservation.status is ReservationStatus.COMMITTED
    assert restarted.execution.execution_halted is False
    assert _journal_state(state_dir, "r1") == CommitOutcome.COMMITTED.value


def test_k1_crash_after_prepare_recovers_as_a_clean_abort(tmp_path, monkeypatch):
    """K1 / F-1: provably nothing happened -> NOT_COMMITTED, capital released."""
    state_dir = _fresh_state(tmp_path)
    app = _app(state_dir)
    _crash_k1(app, monkeypatch)
    _run_until_crash(app, _buy)

    halted = _app(state_dir)
    assert halted.execution.execution_halted is True
    # F-2 must never take a reservation with a PREPARE record for an orphan.
    assert _reservation(state_dir, "r1").status is ReservationStatus.RESERVED

    outcome = _recover(state_dir)

    assert outcome.outcome is ReconciliationOutcome.RECOVERED
    assert outcome.recovery_class == RecoveryClass.ABORT_NOT_APPLIED.value
    assert _journal_state(state_dir, "r1") == CommitOutcome.NOT_COMMITTED.value
    assert _reservation(state_dir, "r1").status is ReservationStatus.RELEASED
    assert _idempotency_record(state_dir, "r1") is None

    restarted = _assert_restart_healthy(state_dir)
    assert restarted.portfolio_foundation.snapshot()["positions"] == {}
    # NOT_COMMITTED stays retryable, and the retry gets a fresh reservation.
    assert _buy(restarted)["status"] == "PAPER_EXECUTED"
    assert _reservation(state_dir, "r1").status is ReservationStatus.COMMITTED


@pytest.mark.parametrize("crash", [_crash_k3, _crash_k4, _crash_k5],
                         ids=["K3", "K4", "K5"])
def test_k3_to_k5_recover_committed_from_applied_evidence_not_rederivation(
    tmp_path, monkeypatch, crash,
):
    """F-1: the applied authority proves it happened; the result says so and
    carries no recomputed fill figures."""
    state_dir = _fresh_state(tmp_path)
    app = _app(state_dir)
    crash(app, monkeypatch)
    _run_until_crash(app, _buy)
    position_before = _foundation(state_dir).snapshot()["positions"]["BTCUSDT"]

    assert _app(state_dir).execution.execution_halted is True

    outcome = _recover(state_dir)

    assert outcome.outcome is ReconciliationOutcome.RECOVERED
    assert outcome.recovery_class == RecoveryClass.COMMIT_APPLIED_EVIDENCE.value
    entry = ExecutionTransactionJournal(state_dir / EXECUTION_TRANSACTION_JOURNAL_FILE).entries["r1"]
    assert entry["state"] == CommitOutcome.COMMITTED.value
    result = entry["result"]
    assert result["recovery"]["method"] == RecoveryClass.COMMIT_APPLIED_EVIDENCE.value
    for figure in ("filled_base_quantity", "filled_quote_notional", "fee_amount", "filled_price"):
        assert figure not in result
    applied = AppliedExecutionArchiveStore(
        state_dir / EXECUTION_APPLIED_EXECUTIONS_FILE
    ).load_index().by_idempotency_key["r1"]
    assert result["execution_id"] == applied.execution_id
    assert _reservation(state_dir, "r1").status is ReservationStatus.COMMITTED
    assert _idempotency_record(state_dir, "r1")["execution_id"] == applied.execution_id

    restarted = _assert_restart_healthy(state_dir)
    # The book was already right; recovery did not touch it.
    assert restarted.portfolio_foundation.snapshot()["positions"]["BTCUSDT"] == position_before
    # The recovered request replays as a completed duplicate - never twice.
    replay = _buy(restarted)
    assert replay["duplicate_reason"] == "DUPLICATE_REQUEST_COMPLETED"
    assert replay["execution_id"] == applied.execution_id
    assert restarted.portfolio_foundation.snapshot()["positions"]["BTCUSDT"] == position_before


def test_k6_recovers_committed_with_the_genuine_recorded_result(tmp_path, monkeypatch):
    """F-1 / K6: the idempotency record already holds the real result; it is
    copied into the journal, never rebuilt."""
    state_dir = _fresh_state(tmp_path)
    app = _app(state_dir)
    _crash_k6(app, monkeypatch)
    _run_until_crash(app, _buy)
    record = dict(_idempotency_record(state_dir, "r1"))

    outcome = _recover(state_dir)

    assert outcome.outcome is ReconciliationOutcome.RECOVERED
    assert outcome.recovery_class == RecoveryClass.COMMIT_APPLIED_EVIDENCE.value
    result = ExecutionTransactionJournal(
        state_dir / EXECUTION_TRANSACTION_JOURNAL_FILE
    ).entries["r1"]["result"]
    record.pop("idempotency_recorded_at")
    assert result == record
    assert "recovery" not in result
    _assert_restart_healthy(state_dir)


def test_k2_marker_with_no_sidecar_append_recovers_as_abort(tmp_path, monkeypatch):
    """Killed after the transition marker, before any sidecar append: the
    working state under the marker is the untouched book."""
    state_dir = _fresh_state(tmp_path)
    app = _app(state_dir)
    _crash_on(monkeypatch, app.portfolio_foundation.applied_archive, "append")
    _run_until_crash(app, _buy)
    assert _foundation(state_dir).ready is False

    outcome = _recover(state_dir)

    assert outcome.outcome is ReconciliationOutcome.RECOVERED
    assert outcome.recovery_class == RecoveryClass.ABORT_NOT_APPLIED.value
    assert _reservation(state_dir, "r1").status is ReservationStatus.RELEASED
    restarted = _assert_restart_healthy(state_dir)
    snapshot = restarted.portfolio_foundation.snapshot()
    assert snapshot["positions"] == {} and snapshot["cash"] == D("10000")


def test_k2_applied_orphan_is_completed_by_paper_rederivation(tmp_path, monkeypatch):
    """K2 - the one inconclusive window. The re-derived settlement produces
    exactly the book an uninterrupted run produces."""
    baseline = _baseline_position(tmp_path)
    state_dir = _fresh_state(tmp_path)
    app = _app(state_dir)
    _crash_on(monkeypatch, app.portfolio_foundation.applied_archive, "append", after=True)
    _run_until_crash(app, _buy)
    assert _foundation(state_dir).ready is False

    outcome = _recover(state_dir)

    assert outcome.outcome is ReconciliationOutcome.RECOVERED
    assert outcome.recovery_class == RecoveryClass.COMMIT_PAPER_REDERIVATION.value
    restarted = _assert_restart_healthy(state_dir)
    snapshot = restarted.portfolio_foundation.snapshot()
    recovered = snapshot["positions"]["BTCUSDT"]
    expected = baseline["positions"]["BTCUSDT"]
    for field in ("base_quantity", "cost_quote", "entry_fees", "average_entry_price",
                  "mark_price", "version"):
        assert recovered[field] == expected[field]
    assert snapshot["cash"] == baseline["cash"]
    reservation = _reservation(state_dir, "r1")
    assert reservation.status is ReservationStatus.COMMITTED
    assert reservation.amount == D(recovered["cost_quote"]) + D(recovered["entry_fees"])
    result = restarted.transaction_journal.entries["r1"]["result"]
    assert result["recovery"]["method"] == RecoveryClass.COMMIT_PAPER_REDERIVATION.value
    assert D(result["filled_quote_notional"]) == D(recovered["cost_quote"])


def test_k2_full_exit_closed_orphan_must_match_the_rederived_close(tmp_path, monkeypatch):
    """A SELL full exit killed after the closed-position append: the archived
    closed record must equal the re-derived one field for field."""
    state_dir = _fresh_state(tmp_path)
    app = _app(state_dir)
    assert _buy(app)["status"] == "PAPER_EXECUTED"
    _crash_on(monkeypatch, app.portfolio_foundation.closed_archive, "append", after=True)
    _run_until_crash(app, _full_exit_sell)

    outcome = _recover(state_dir)

    assert outcome.outcome is ReconciliationOutcome.RECOVERED
    assert outcome.recovery_class == RecoveryClass.COMMIT_PAPER_REDERIVATION.value
    restarted = _assert_restart_healthy(state_dir)
    assert restarted.portfolio_foundation.snapshot()["positions"] == {}
    assert _journal_state(state_dir, "s1") == CommitOutcome.COMMITTED.value


def test_k2_rederivation_refuses_when_a_closed_orphan_disagrees(tmp_path, monkeypatch):
    state_dir = _fresh_state(tmp_path)
    app = _app(state_dir)
    assert _buy(app)["status"] == "PAPER_EXECUTED"
    _crash_on(monkeypatch, app.portfolio_foundation.closed_archive, "append", after=True)
    _run_until_crash(app, _full_exit_sell)

    closed_path = state_dir / EXECUTION_CLOSED_POSITIONS_FILE
    lines = closed_path.read_text(encoding="utf-8").splitlines()
    tampered = json.loads(lines[-1])
    tampered["gross_pnl"] = str(D(tampered["gross_pnl"]) + 1)
    lines[-1] = json.dumps(tampered, sort_keys=True, separators=(",", ":"))
    closed_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    before = _snapshot(state_dir)

    outcome = _recover(state_dir)

    assert outcome.outcome is ReconciliationOutcome.RECONCILIATION_REQUIRED
    assert outcome.reason_code == "RECOVERY_DERIVATION_UNAVAILABLE"
    assert _snapshot(state_dir) == before


# ==========================================================================
# F-1 fail-closed edges
# ==========================================================================


def _k1_state(tmp_path, monkeypatch) -> Path:
    state_dir = _fresh_state(tmp_path)
    app = _app(state_dir)
    _crash_k1(app, monkeypatch)
    _run_until_crash(app, _buy)
    return state_dir


@pytest.mark.parametrize("mode", [None, "LIVE"])
def test_live_or_unstated_mode_stays_fail_closed_exactly_as_before(tmp_path, monkeypatch, mode):
    state_dir = _k1_state(tmp_path, monkeypatch)
    before = _snapshot(state_dir)

    outcome = reconcile(state_dir, apply=True, execution_mode=mode)

    assert outcome.outcome is ReconciliationOutcome.RECONCILIATION_REQUIRED
    assert outcome.reason_code == "JOURNAL_UNRESOLVED"
    assert outcome.recovered == 0
    assert _snapshot(state_dir) == before


def test_invalid_execution_mode_is_refused(tmp_path, monkeypatch):
    state_dir = _k1_state(tmp_path, monkeypatch)
    outcome = reconcile(state_dir, apply=True, execution_mode="TESTNET")
    assert outcome.outcome is ReconciliationOutcome.STATE_INVALID
    assert outcome.reason_code == "EXECUTION_MODE_INVALID"


def test_paper_statement_contradicted_by_the_prepared_request_is_refused(tmp_path, monkeypatch):
    state_dir = _k1_state(tmp_path, monkeypatch)
    journal = ExecutionTransactionJournal(state_dir / EXECUTION_TRANSACTION_JOURNAL_FILE)
    journal.entries["r1"]["request"]["mode"] = "LIVE"
    assert journal.save()
    before = _snapshot(state_dir)

    outcome = _recover(state_dir)

    assert outcome.reason_code == "RECOVERY_MODE_UNPROVEN"
    assert _snapshot(state_dir) == before


def test_prepared_entry_with_a_result_but_no_application_is_ambiguous(tmp_path, monkeypatch):
    """A terminal result with no applied record matches no provable class."""
    from core.execution_idempotency_store import ExecutionIdempotencyStore

    state_dir = _k1_state(tmp_path, monkeypatch)
    store = ExecutionIdempotencyStore(state_dir / EXECUTION_IDEMPOTENCY_STATE_FILE)
    assert store.record("r1", {"success": True, "status": "PAPER_EXECUTED",
                               "execution_id": "x", "commit_outcome": "COMMITTED"})
    before = _snapshot(state_dir)

    outcome = _recover(state_dir)

    assert outcome.reason_code == "RECOVERY_EVIDENCE_AMBIGUOUS"
    assert _snapshot(state_dir) == before


def test_committed_reservation_without_application_is_ambiguous(tmp_path, monkeypatch):
    state_dir = _k1_state(tmp_path, monkeypatch)
    ledger = CapitalReservationLedger(
        JsonReservationStore(state_dir / CAPITAL_RESERVATION_STATE_FILE), D("100000"),
    )
    ledger.commit("r1")
    before = _snapshot(state_dir)

    outcome = _recover(state_dir)

    assert outcome.reason_code == "RECOVERY_EVIDENCE_AMBIGUOUS"
    assert _snapshot(state_dir) == before


def test_commit_status_unknown_is_outside_the_recovery(tmp_path, monkeypatch):
    state_dir = _k1_state(tmp_path, monkeypatch)
    journal = ExecutionTransactionJournal(state_dir / EXECUTION_TRANSACTION_JOURNAL_FILE)
    assert journal.mark_unknown("r1", reason="TEST")
    before = _snapshot(state_dir)

    outcome = _recover(state_dir)

    assert outcome.reason_code == "JOURNAL_UNRESOLVED"
    assert _snapshot(state_dir) == before


def test_rederivation_refuses_without_the_durable_admission_evidence(tmp_path, monkeypatch):
    state_dir = _fresh_state(tmp_path)
    app = _app(state_dir)
    _crash_on(monkeypatch, app.portfolio_foundation.applied_archive, "append", after=True)
    _run_until_crash(app, _buy)
    (state_dir / reconcile_module.DEFAULT_AUDIT_FILE).unlink()
    before = _snapshot(state_dir)

    outcome = _recover(state_dir)

    assert outcome.reason_code == "RECOVERY_DERIVATION_UNAVAILABLE"
    assert _snapshot(state_dir) == before


def test_rederivation_refuses_when_instrument_rules_changed_since_admission(
    tmp_path, monkeypatch,
):
    state_dir = _fresh_state(tmp_path)
    app = _app(state_dir)
    _crash_on(monkeypatch, app.portfolio_foundation.applied_archive, "append", after=True)
    _run_until_crash(app, _buy)
    changed = InstrumentRuleset({
        "BTCUSDT": InstrumentRules(
            venue="BINANCE", symbol="BTCUSDT", base_asset="BTC", quote_asset="USDT",
            quantity_step="0.1", min_quantity="0.1", min_notional="5",
            price_tick="0.01", source="changed", source_version="v2",
            retrieved_at="2026-09-01T00:00:00Z",
        ),
    })
    before = _snapshot(state_dir)

    outcome = _recover(state_dir, instrument_rules=changed)

    assert outcome.reason_code == "RECOVERY_DERIVATION_UNAVAILABLE"
    assert _snapshot(state_dir) == before


def test_dry_run_reports_the_recovery_and_writes_nothing(tmp_path, monkeypatch):
    state_dir = _k1_state(tmp_path, monkeypatch)
    before = _snapshot(state_dir)

    outcome = reconcile(state_dir, apply=False, execution_mode="PAPER")

    assert outcome.outcome is ReconciliationOutcome.WOULD_RECOVER
    assert outcome.recovery_class == RecoveryClass.ABORT_NOT_APPLIED.value
    assert _snapshot(state_dir) == before


def test_failed_recovery_write_restores_every_file_byte_for_byte(tmp_path, monkeypatch):
    state_dir = _fresh_state(tmp_path)
    app = _app(state_dir)
    _crash_k3(app, monkeypatch)
    _run_until_crash(app, _buy)
    monkeypatch.undo()
    before = _snapshot(state_dir)
    monkeypatch.setattr(ExecutionTransactionJournal, "mark_committed", lambda *a, **k: False)

    outcome = _recover(state_dir)

    assert outcome.outcome is ReconciliationOutcome.FAILED
    assert outcome.reason_code == "RECOVERY_WRITE_FAILED"
    assert _snapshot(state_dir) == before


def test_cli_recovers_with_an_explicit_paper_mode_and_leaks_no_identifier(tmp_path, monkeypatch):
    state_dir = _k1_state(tmp_path, monkeypatch)

    completed = subprocess.run(
        [sys.executable, str(RECONCILE_CLI_PATH), "--state-directory", str(state_dir),
         "--execution-mode", "paper", "--apply", "--json"],
        capture_output=True, text=True, cwd=str(REPOSITORY_ROOT),
    )

    assert completed.returncode == 0, completed.stderr
    payload = json.loads(completed.stdout)
    assert payload["outcome"] == "RECOVERED"
    assert payload["recovery_class"] == RecoveryClass.ABORT_NOT_APPLIED.value
    assert "r1" not in completed.stdout.replace(str(state_dir), "")


# ==========================================================================
# F-3 - retry after a released reservation (E1)
# ==========================================================================


def test_e1_retry_after_transient_prepare_failure_executes_on_a_fresh_reservation(tmp_path):
    """E1. Pre-fix: attempt 2 reused the RELEASED record and halted with a
    false COMMIT_STATUS_UNKNOWN on an untouched book."""
    state_dir = _fresh_state(tmp_path)
    app = _app(state_dir)
    journal = app.execution.transaction_journal
    original_prepare = journal.prepare
    journal.prepare = lambda *a, **k: False

    first = _buy(app)
    assert first["error_code"] == "TRANSACTION_PREPARE_FAILED"
    released = _reservation(state_dir, "r1")
    assert released.status is ReservationStatus.RELEASED

    journal.prepare = original_prepare
    second = _buy(app)

    assert second["status"] == "PAPER_EXECUTED"
    assert app.execution.execution_halted is False
    rearmed = _reservation(state_dir, "r1")
    assert rearmed.status is ReservationStatus.COMMITTED
    assert rearmed.version > released.version
    assert _journal_state(state_dir, "r1") == CommitOutcome.COMMITTED.value


def _ledger(tmp_path, total="1000") -> CapitalReservationLedger:
    store = JsonReservationStore(tmp_path / "reservations.json")
    store.initialize_empty()
    return CapitalReservationLedger(store, D(total))


def test_rearm_is_capacity_checked_and_changes_nothing_when_refused(tmp_path):
    ledger = _ledger(tmp_path)
    ledger.reserve("r1", "r1", D("600"))
    ledger.release("r1")
    ledger.reserve("r2", "r2", D("600"))

    with pytest.raises(ValueError, match="insufficient"):
        ledger.reserve("r1", "r1", D("600"))
    assert ledger.get("r1").status is ReservationStatus.RELEASED
    assert ledger.active_reserved_capital() == D("600")


@pytest.mark.parametrize("terminal", ["commit", "mark_indeterminate"])
def test_settled_or_indeterminate_reservation_is_never_reserved_again(tmp_path, terminal):
    ledger = _ledger(tmp_path)
    ledger.reserve("r1", "r1", D("100"))
    getattr(ledger, terminal)("r1")
    before = ledger.get("r1")

    with pytest.raises(ValueError, match="already"):
        ledger.reserve("r1", "r1", D("100"))
    assert ledger.get("r1") == before


def test_live_reservation_is_adopted_not_duplicated(tmp_path):
    ledger = _ledger(tmp_path)
    first = ledger.reserve("r1", "r1", D("100"))
    assert ledger.reserve("r1", "r1", D("100")) == first
    assert ledger.active_reserved_capital() == D("100")


def test_retry_after_success_never_reserves_again(tmp_path):
    """F-3 edge: a request retried after it actually succeeded is answered
    from the idempotency authority; the ledger is untouched."""
    state_dir = _fresh_state(tmp_path)
    app = _app(state_dir)
    assert _buy(app)["status"] == "PAPER_EXECUTED"
    before = _reservation(state_dir, "r1")

    replay = _buy(app)

    assert replay["duplicate_reason"] == "DUPLICATE_REQUEST_COMPLETED"
    assert _reservation(state_dir, "r1") == before
    assert app.reservation_ledger.active_reserved_capital() == D("0")


# ==========================================================================
# F-2 - the orphan sweep never takes a live reservation
# ==========================================================================


def test_orphan_sweep_skips_a_reservation_held_in_flight(tmp_path):
    state_dir = _fresh_state(tmp_path)
    app = _app(state_dir)
    app.reservation_ledger.reserve("inflight", "inflight", D("100"))
    app.execution.pending_request_ids.add("inflight")

    app.execution._release_orphan_reservations()

    assert app.reservation_ledger.get("inflight").status is ReservationStatus.RESERVED


def test_orphan_sweep_skips_a_reservation_with_any_journal_entry(tmp_path):
    state_dir = _fresh_state(tmp_path)
    app = _app(state_dir)
    app.reservation_ledger.reserve("prepared", "prepared", D("100"))
    assert app.transaction_journal.prepare("prepared", {"request_id": "prepared"})

    app.execution._release_orphan_reservations()

    assert app.reservation_ledger.get("prepared").status is ReservationStatus.RESERVED


# ==========================================================================
# F-5 - reservation-commit failure releases the in-flight claim
# ==========================================================================


def test_reservation_commit_failure_releases_the_claim(tmp_path, monkeypatch):
    state_dir = _fresh_state(tmp_path)
    app = _app(state_dir)

    def failing_commit(*args, **kwargs):
        raise RuntimeError("ledger write failed")

    monkeypatch.setattr(app.execution.reservation_ledger, "commit", failing_commit)

    result = _buy(app)

    assert result["error_code"] == "CAPITAL_RESERVATION_COMMIT_FAILED"
    assert "r1" not in app.execution.pending_request_ids
    assert app.execution._reset_refusal_reason() != "EXECUTION_REQUESTS_IN_FLIGHT"
    assert app.execution.execution_halted is True
    assert result in app.execution.get_history()


# ==========================================================================
# F-6 - a refusal inside apply_confirmed leaves nothing behind
# ==========================================================================


@pytest.mark.parametrize("cash", ["1"])
def test_insufficient_cash_refusal_leaves_the_book_ready_across_restart(tmp_path, cash):
    from core.execution_models import ExecutionResult

    store = FinancialStateStore(tmp_path / "state.json")
    store.initialize(D(cash))
    applied = AppliedExecutionArchiveStore(tmp_path / "applied.jsonl")
    closed = ClosedPositionArchiveStore(tmp_path / "closed.jsonl")
    book = ExecutionPortfolioFoundation(store, applied_archive=applied, closed_archive=closed)
    before = store.path.read_bytes()
    evidence = ExecutionResult(
        success=True, status="FILLED", execution_id="e1", order_id="o1", position_id="p1",
        symbol="BTCUSDT", action="BUY", filled_price="10", filled_base_quantity=D("10"),
        filled_quote_notional=D("100"), fee_amount=D("0"), fee_currency="USDT",
        timestamp="2026-09-24T00:00:00+00:00", idempotency_key="k1", provenance_ref="t:1",
    )

    with pytest.raises(ValueError, match="INSUFFICIENT_CASH"):
        book.apply_confirmed(evidence, risk_authorized=True, reservation_confirmed=True)

    assert book.ready
    assert store.path.read_bytes() == before
    assert not applied.path.exists()
    assert ExecutionPortfolioFoundation(store, applied_archive=applied, closed_archive=closed).ready


# ==========================================================================
# Independent-audit remediation (CRITICAL gate FIX step)
# ==========================================================================


def test_sell_applied_evidence_recovery_needs_no_reservation(tmp_path, monkeypatch):
    """A SELL takes no reservation; evidence recovery must accept its absence."""
    state_dir = _fresh_state(tmp_path)
    app = _app(state_dir)
    assert _buy(app)["status"] == "PAPER_EXECUTED"
    _crash_on(monkeypatch, app.execution, "_mirror_paper_book")
    _run_until_crash(app, _full_exit_sell)
    assert _reservation(state_dir, "s1") is None

    outcome = _recover(state_dir)

    assert outcome.outcome is ReconciliationOutcome.RECOVERED
    assert outcome.recovery_class == RecoveryClass.COMMIT_APPLIED_EVIDENCE.value
    restarted = _assert_restart_healthy(state_dir)
    assert restarted.portfolio_foundation.snapshot()["positions"] == {}


def test_k2_full_exit_with_both_sidecar_orphans_is_completed(tmp_path, monkeypatch):
    """Killed after the applied append of a full exit: the closed and the
    applied record both exist beyond their checkpoints and both must match."""
    state_dir = _fresh_state(tmp_path)
    app = _app(state_dir)
    assert _buy(app)["status"] == "PAPER_EXECUTED"
    _crash_on(monkeypatch, app.portfolio_foundation.applied_archive, "append", after=True)
    _run_until_crash(app, _full_exit_sell)

    outcome = _recover(state_dir)

    assert outcome.outcome is ReconciliationOutcome.RECOVERED
    assert outcome.recovery_class == RecoveryClass.COMMIT_PAPER_REDERIVATION.value
    restarted = _assert_restart_healthy(state_dir)
    assert restarted.portfolio_foundation.snapshot()["positions"] == {}
    closed = ClosedPositionArchiveStore(state_dir / EXECUTION_CLOSED_POSITIONS_FILE).load_index()
    assert closed.count == 1


def _k2_state(tmp_path, monkeypatch) -> Path:
    state_dir = _fresh_state(tmp_path)
    app = _app(state_dir)
    _crash_on(monkeypatch, app.portfolio_foundation.applied_archive, "append", after=True)
    _run_until_crash(app, _buy)
    return state_dir


def _set_prepared_at(state_dir: Path, request_id: str, moment: str) -> None:
    journal = ExecutionTransactionJournal(state_dir / EXECUTION_TRANSACTION_JOURNAL_FILE)
    journal.entries[request_id]["prepared_at"] = moment
    assert journal.save()


def test_rederivation_refuses_an_approval_recorded_after_the_prepare(tmp_path, monkeypatch):
    state_dir = _k2_state(tmp_path, monkeypatch)
    _set_prepared_at(state_dir, "r1", "2000-01-01T00:00:00+00:00")
    before = _snapshot(state_dir)

    outcome = _recover(state_dir)

    assert outcome.reason_code == "RECOVERY_DERIVATION_UNAVAILABLE"
    assert _snapshot(state_dir) == before


def test_rederivation_refuses_when_a_newer_attempt_lacks_its_own_approval(
    tmp_path, monkeypatch,
):
    """Audit activity between the last approval and the PREPARE means the
    prepared attempt is not the approved one: its rules are unproven."""
    from core.audit_event_store import AuditEventStore

    state_dir = _k2_state(tmp_path, monkeypatch)
    AuditEventStore(state_dir / reconcile_module.DEFAULT_AUDIT_FILE).append(
        event_type="EXECUTION_REQUEST_RECEIVED", source="test",
        aggregate_type="execution_request", aggregate_id="r1", payload={},
        correlation_id="r1", metadata={"mode": "PAPER"},
    )
    _set_prepared_at(state_dir, "r1", "2099-01-01T00:00:00+00:00")
    before = _snapshot(state_dir)

    outcome = _recover(state_dir)

    assert outcome.reason_code == "RECOVERY_DERIVATION_UNAVAILABLE"
    assert _snapshot(state_dir) == before


def test_orphan_sweep_never_touches_a_non_canonical_id(tmp_path):
    state_dir = _fresh_state(tmp_path)
    app = _app(state_dir)
    app.reservation_ledger.reserve(" padded", " padded", D("100"))

    app.execution._release_orphan_reservations()

    assert app.reservation_ledger.get(" padded").status is ReservationStatus.RESERVED


def test_orphan_release_that_cannot_persist_halts_startup(tmp_path, monkeypatch):
    state_dir = _fresh_state(tmp_path)
    app = _app(state_dir)
    _crash_on(monkeypatch, app.execution.transaction_journal, "prepare")
    _run_until_crash(app, _buy)
    monkeypatch.undo()

    def failing_release(*args, **kwargs):
        raise RuntimeError("reservation persistence failed")

    monkeypatch.setattr(CapitalReservationLedger, "release", failing_release)
    restarted = _app(state_dir)

    assert restarted.execution.execution_halted is True
    assert restarted.execution.halt_reason == "CAPITAL_RESERVATION_RELEASE_FAILED"
    assert _reservation(state_dir, "r1").status is ReservationStatus.RESERVED
