"""
Block 5 / Package 5J - Execution Authority Recovery.

Closes two carried findings:

B5H-0-9
    ``ExecutionManager.reset()`` erased the durable idempotency authority
    while leaving every COMMITTED transaction-journal entry in place -
    manufacturing ``SOURCE_DISAGREEMENT`` out of a healthy book, and (because
    ``_claim_request`` answers duplicates from the in-memory completed map
    alone) letting an already-executed request execute a second time in the
    same process. Test A is the permanent witness of that asymmetry; test B
    proves production can no longer reach it.

B5H-0-12
    There was no supported operator path out of an already-divergent
    journal/idempotency pair. ``tools/reconcile_execution_authorities.py`` is
    that path: verify-first, fail-closed, repairing exactly one class and
    only when three independent durable authorities prove one unique
    terminal truth.

Every test uses an isolated state directory under ``tmp_path``; none of them
constructs a runtime that could reach the repository's real state files.
"""

from __future__ import annotations

import json
import subprocess
import sys
from datetime import UTC, datetime
from decimal import Decimal as D
from pathlib import Path
from typing import Any

import pytest

from core.capital_reservation import CapitalReservationLedger, JsonReservationStore
from core.execution_idempotency_store import ExecutionIdempotencyStore
from core.execution_manager import ExecutionManager, ExecutionResetRefusedError
from core.execution_models import ExecutionResult
from core.execution_portfolio_foundation import (
    AppliedExecutionArchiveStore,
    ClosedPositionArchiveStore,
    ExecutionPortfolioFoundation,
    FinancialStateStore,
    mint_long_position_id,
)
from core.execution_transaction_journal import (
    CommitOutcome,
    ExecutionTransactionJournal,
)
from core.instrument_rules import InstrumentRules, InstrumentRuleset
from core.risk_engine import RiskEngine, RiskPolicy, RiskState
from core.risk_state_store import JsonRiskStateStore, RestoredRiskState
from data_layer.runtime_safety import FinancialRuntimeSafetyService

import tools.reconcile_execution_authorities as reconcile_module
from tools.reconcile_execution_authorities import (
    ReconciliationOutcome,
    reconcile,
)

REPOSITORY_ROOT = Path(__file__).resolve().parent.parent
RECONCILE_CLI_PATH = REPOSITORY_ROOT / "tools" / "reconcile_execution_authorities.py"

JOURNAL_FILE = reconcile_module.DEFAULT_JOURNAL_FILE
IDEMPOTENCY_FILE = reconcile_module.DEFAULT_IDEMPOTENCY_FILE
FINANCIAL_STATE_FILE = reconcile_module.DEFAULT_FINANCIAL_STATE_FILE
APPLIED_FILE = reconcile_module.DEFAULT_APPLIED_FILE
CLOSED_FILE = reconcile_module.DEFAULT_CLOSED_FILE

# Every state file the tool may read. Tests that assert "nothing else moved"
# compare the bytes of all of them.
ALL_STATE_FILES = (
    JOURNAL_FILE, IDEMPOTENCY_FILE, FINANCIAL_STATE_FILE, APPLIED_FILE, CLOSED_FILE,
)

_SYMBOL = "BTCUSDT"

_BTCUSDT_RULES = InstrumentRuleset({
    _SYMBOL: InstrumentRules(
        venue="BINANCE", symbol=_SYMBOL, base_asset="BTC", quote_asset="USDT",
        quantity_step="0.00001", min_quantity="0.00001", min_notional="5",
        price_tick="0.01", source="test-fixture", source_version="v1",
        retrieved_at="2026-01-01T00:00:00Z",
    ),
})


# ---------------------------------------------------------------------------
# helpers - real production classes only, isolated state directories only
# ---------------------------------------------------------------------------


def _confirmed_result(
    request_id: str, *, execution_id: str, position_id: str,
    symbol: str = _SYMBOL, action: str = "BUY",
) -> dict[str, Any]:
    """The COMMITTED terminal result ExecutionManager hands to BOTH
    ``transaction_journal.mark_committed()`` and ``idempotency_store.record()``
    for the same request - including the top-level ``request_id``
    ``execute()`` sets before either write."""

    return {
        "success": True,
        "status": "PAPER_EXECUTED",
        "commit_outcome": CommitOutcome.COMMITTED.value,
        "request_id": request_id,
        "order_id": f"order-{request_id}",
        "execution_id": execution_id,
        "position_id": position_id,
        "symbol": symbol,
        "action": action,
        "filled_base_quantity": "1",
        "filled_quote_notional": "10",
        "filled_price": "10",
        "fee_amount": "0",
        "timestamp": "2026-08-24T00:00:00+00:00",
    }


def _fill(
    *, execution_id: str, position_id: str, request_id: str, symbol: str = _SYMBOL,
) -> ExecutionResult:
    return ExecutionResult(
        success=True, status="PAPER_EXECUTED", execution_id=execution_id,
        position_id=position_id, symbol=symbol, action="BUY",
        filled_price=D("10"), filled_base_quantity=D("1"),
        filled_quote_notional=D("10"), fee_amount=D("0"), fee_currency="USDT",
        idempotency_key=request_id, provenance_ref=f"transaction-journal:{request_id}",
    )


def _symbol_for(index: int) -> str:
    """A distinct symbol per request, so every applied execution opens its own
    fresh position rather than adding to one - which keeps each request's
    applied-authority record independent."""
    return _SYMBOL if index == 0 else f"SYM{index}USDT"


def _build_book(
    directory: Path, request_ids: tuple[str, ...] | list[str], *, cash: str = "1000",
) -> dict[str, dict[str, Any]]:
    """Build a healthy state directory holding one COMMITTED execution per id.

    The applied-execution authority and the financial checkpoints are produced
    by ``ExecutionPortfolioFoundation.apply_confirmed`` - the same call the
    runtime makes - never by hand-written checkpoint JSON.
    """
    directory.mkdir(parents=True, exist_ok=True)
    store = FinancialStateStore(directory / FINANCIAL_STATE_FILE)
    store.initialize(D(cash))
    foundation = ExecutionPortfolioFoundation(
        store,
        applied_archive=AppliedExecutionArchiveStore(directory / APPLIED_FILE),
        closed_archive=ClosedPositionArchiveStore(directory / CLOSED_FILE),
    )
    journal = ExecutionTransactionJournal(directory / JOURNAL_FILE)
    idempotency = ExecutionIdempotencyStore(directory / IDEMPOTENCY_FILE)

    results: dict[str, dict[str, Any]] = {}
    for index, request_id in enumerate(request_ids):
        symbol = _symbol_for(index)
        execution_id = f"exec-{request_id}"
        position_id = mint_long_position_id(symbol, request_id)

        # 1. financial application (applied sidecar + checkpoint) - first
        foundation.apply_confirmed(
            _fill(execution_id=execution_id, position_id=position_id,
                  request_id=request_id, symbol=symbol),
            risk_authorized=True, reservation_confirmed=True,
            expected_position_version=None,
        )
        result = _confirmed_result(
            request_id, execution_id=execution_id, position_id=position_id, symbol=symbol,
        )
        # 2. idempotency terminal result, 3. journal COMMITTED - the exact
        #    production write order (see ExecutionManager.execute).
        assert journal.prepare(request_id, {"request_id": request_id, "symbol": symbol})
        assert idempotency.record(request_id, result, save=True)
        assert journal.mark_committed(request_id, result)
        results[request_id] = result

    return results


def _snapshot(directory: Path) -> dict[str, bytes | None]:
    return {
        name: (directory / name).read_bytes() if (directory / name).exists() else None
        for name in ALL_STATE_FILES
    }


def _drop_idempotency_record(directory: Path, request_id: str) -> None:
    """Remove one terminal result durably, exactly as the pre-5J
    ``ExecutionManager.reset()`` removed all of them: the journal keeps its
    COMMITTED entry, the replay authority loses its counterpart."""
    store = ExecutionIdempotencyStore(directory / IDEMPOTENCY_FILE)
    assert store.remove(request_id, save=True)


def _risk_state() -> RiskState:
    return RiskState((), D("0"), D("0"), D("1000"), D("1000"), True,
                     datetime.now(UTC).date().isoformat(), "phase3-risk-v1")


def _decision(request_id: str) -> dict[str, Any]:
    return {
        "request_id": request_id, "action": "BUY", "symbol": _SYMBOL,
        "price": 65000.0, "amount": 100.0, "confidence": 90.0,
        "strategy": "BLOCK5J_TEST", "risk": "LOW", "mode": "PAPER",
    }


class CountingPaperTrader:
    def __init__(self) -> None:
        self.open_count = 0

    def open_trade(self, symbol: str, price: float, amount: float) -> dict[str, Any]:
        self.open_count += 1
        return {"success": True, "status": "FILLED", "trade_id": f"paper-{self.open_count}",
                "symbol": symbol, "price": price, "amount": amount}


def _manager(
    directory: Path, tmp_path: Path, *, paper_trader: CountingPaperTrader | None = None,
    full: bool = False,
) -> ExecutionManager:
    idempotency = ExecutionIdempotencyStore(directory / IDEMPOTENCY_FILE)
    journal = ExecutionTransactionJournal(directory / JOURNAL_FILE)
    if not full:
        return ExecutionManager(
            idempotency_store=idempotency, transaction_journal=journal, audit_enabled=False,
        )

    reservation_store = JsonReservationStore(tmp_path / "reservations.json")
    reservation_store.initialize_empty()
    risk_store = JsonRiskStateStore(tmp_path / "risk-state.json")
    risk_store.save(RestoredRiskState(datetime.now(UTC).date(), D("0"),
                                      D("1000"), D("1000"), "phase3-risk-v1"))
    return ExecutionManager(
        paper_trader=paper_trader, idempotency_store=idempotency,
        transaction_journal=journal, audit_enabled=False,
        risk_engine=RiskEngine(RiskPolicy(total_capital=D("1000"))),
        reservation_ledger=CapitalReservationLedger(reservation_store, D("800")),
        risk_state_store=risk_store, instrument_rules=_BTCUSDT_RULES,
    )


def run_cli(*arguments: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(RECONCILE_CLI_PATH), *arguments],
        capture_output=True, text=True, cwd=str(REPOSITORY_ROOT),
    )


# ===========================================================================
# A - the reset asymmetry this package removes (permanent witness)
# ===========================================================================


def test_a_erasing_only_the_idempotency_authority_manufactures_disagreement(tmp_path):
    """What pre-5J ExecutionManager.reset() did, reproduced at the store level.

    The idempotency store cannot see the journal, so its own reset() is not
    the defect - calling it *alone* from a runtime that also owns the journal
    was. This is the exact asymmetry, and the resulting state is the one
    FinancialRuntimeSafetyService refuses to start.
    """
    directory = tmp_path / "state"
    _build_book(directory, ["req-a"])

    journal = ExecutionTransactionJournal(directory / JOURNAL_FILE)
    idempotency = ExecutionIdempotencyStore(directory / IDEMPOTENCY_FILE)
    assert FinancialRuntimeSafetyService(
        transaction_journal=journal, idempotency_store=idempotency,
    ).assess().ready is True

    # The pre-5J reset: one half of the pair erased, the other untouched.
    idempotency.reset(delete_file=False)

    assert journal.entries["req-a"]["state"] == CommitOutcome.COMMITTED.value
    assert idempotency.completed_requests == {}

    readiness = FinancialRuntimeSafetyService(
        transaction_journal=journal, idempotency_store=idempotency,
    ).assess()
    assert readiness.ready is False
    assert readiness.decision.reason == "SOURCE_DISAGREEMENT"


# ===========================================================================
# B - production reset can no longer create disagreement
# ===========================================================================


def test_b_reset_refuses_when_durable_execution_history_exists(tmp_path):
    directory = tmp_path / "state"
    _build_book(directory, ["req-b"])
    before = _snapshot(directory)

    manager = _manager(directory, tmp_path)

    with pytest.raises(ExecutionResetRefusedError) as raised:
        manager.reset()

    assert str(raised.value) == "EXECUTION_HISTORY_PRESENT"

    # Nothing was erased: not the durable authority, not the in-memory replay
    # map, not a single byte of any state file.
    assert _snapshot(directory) == before
    assert manager.idempotency_store.completed_requests.keys() == {"req-b"}
    assert manager.completed_request_results.keys() == {"req-b"}
    assert FinancialRuntimeSafetyService(
        transaction_journal=manager.transaction_journal,
        idempotency_store=manager.idempotency_store,
    ).assess().ready is True


def test_b_reset_refuses_while_a_request_is_in_flight(tmp_path):
    directory = tmp_path / "state"
    directory.mkdir()
    manager = _manager(directory, tmp_path)
    manager.pending_request_ids.add("req-inflight")

    with pytest.raises(ExecutionResetRefusedError) as raised:
        manager.reset()

    assert str(raised.value) == "EXECUTION_REQUESTS_IN_FLIGHT"
    assert manager.pending_request_ids == {"req-inflight"}


def test_b_reset_refuses_when_an_authority_did_not_load(tmp_path):
    directory = tmp_path / "state"
    directory.mkdir()
    (directory / JOURNAL_FILE).write_text("{not json", encoding="utf-8")

    manager = _manager(directory, tmp_path)
    assert manager.transaction_journal.load_failed is True

    with pytest.raises(ExecutionResetRefusedError) as raised:
        manager.reset()

    assert str(raised.value) == "EXECUTION_HISTORY_INDETERMINATE"


def test_b_reset_on_a_clean_runtime_clears_diagnostics_and_writes_nothing(tmp_path):
    directory = tmp_path / "state"
    directory.mkdir()
    manager = _manager(directory, tmp_path)
    manager.errors.append({"phase": "test"})
    manager.stats["requests_completed"] = 7

    manager.reset()

    assert manager.errors == []
    assert manager.stats["requests_completed"] == 0
    # A reset never creates or rewrites a durable authority file.
    assert not (directory / IDEMPOTENCY_FILE).exists()
    assert not (directory / JOURNAL_FILE).exists()


def test_b_reset_no_longer_touches_the_idempotency_store(tmp_path):
    """The durable-erase capability is gone from the runtime path entirely -
    reset() cannot reach ExecutionIdempotencyStore.reset() even in the clean
    case where it would be harmless."""
    directory = tmp_path / "state"
    directory.mkdir()
    manager = _manager(directory, tmp_path)

    calls: list[bool] = []
    manager.idempotency_store.reset = lambda **_: calls.append(True)  # type: ignore[method-assign]

    manager.reset()

    assert calls == []


# ===========================================================================
# C - genuine disagreement still fails closed
# ===========================================================================


def test_c_genuine_disagreement_without_application_proof_fails_closed(tmp_path):
    """A COMMITTED journal entry whose execution was never financially applied
    is a real question about whether money moved. The runtime refuses to
    start, and the tool refuses to answer it."""
    directory = tmp_path / "state"
    directory.mkdir()
    journal = ExecutionTransactionJournal(directory / JOURNAL_FILE)
    result = _confirmed_result("req-c", execution_id="exec-c", position_id="pos-c")
    assert journal.mark_committed("req-c", result)

    manager = _manager(directory, tmp_path)
    assert manager.start()
    assert manager.execution_halted is True
    assert manager.recovery_required is True
    assert manager.halt_reason == "SOURCE_DISAGREEMENT"

    outcome = reconcile(directory, apply=True)
    assert outcome.outcome is ReconciliationOutcome.RECONCILIATION_REQUIRED
    assert outcome.reason_code == "FINANCIAL_APPLICATION_UNPROVEN"
    assert outcome.repaired == 0


# ===========================================================================
# D / E - the one safe repair, and its exact equivalence to the canonical result
# ===========================================================================


def test_d_complete_matching_authorities_repair_successfully(tmp_path):
    directory = tmp_path / "state"
    results = _build_book(directory, ["req-d1", "req-d2"])
    _drop_idempotency_record(directory, "req-d1")

    assert FinancialRuntimeSafetyService(
        transaction_journal=ExecutionTransactionJournal(directory / JOURNAL_FILE),
        idempotency_store=ExecutionIdempotencyStore(directory / IDEMPOTENCY_FILE),
    ).assess().ready is False

    outcome = reconcile(directory, apply=True)

    assert outcome.outcome is ReconciliationOutcome.RECONCILED
    assert outcome.reason_code == "RECONCILIATION_COMPLETE"
    assert (outcome.repairable, outcome.repaired, outcome.refused) == (1, 1, 0)

    repaired = ExecutionIdempotencyStore(directory / IDEMPOTENCY_FILE)
    assert repaired.completed_requests.keys() == {"req-d1", "req-d2"}
    # The record this run did not touch is untouched.
    assert repaired.completed_requests["req-d2"]["execution_id"] == "exec-req-d2"
    assert results["req-d1"]["execution_id"] == "exec-req-d1"


def test_e_repaired_record_is_field_equivalent_to_the_canonical_result(tmp_path):
    directory = tmp_path / "state"
    _build_book(directory, ["req-e"])

    healthy = dict(
        ExecutionIdempotencyStore(directory / IDEMPOTENCY_FILE).completed_requests["req-e"]
    )
    _drop_idempotency_record(directory, "req-e")

    assert reconcile(directory, apply=True).outcome is ReconciliationOutcome.RECONCILED

    journal_result = ExecutionTransactionJournal(
        directory / JOURNAL_FILE
    ).entries["req-e"]["result"]
    repaired = ExecutionIdempotencyStore(
        directory / IDEMPOTENCY_FILE
    ).completed_requests["req-e"]

    # Every field the canonical commit-outcome authority holds is reproduced
    # exactly; the only field the repair adds is the store's own provenance
    # stamp, which carries no financial meaning.
    for field, value in journal_result.items():
        assert repaired[field] == value, field
    assert set(repaired) - set(journal_result) == {"idempotency_recorded_at"}

    # And the repaired record matches what the original healthy record held,
    # field for field, apart from that same stamp.
    for field, value in healthy.items():
        if field == "idempotency_recorded_at":
            continue
        assert repaired[field] == value, field


# ===========================================================================
# F / G - restart readiness and replay safety after a repair
# ===========================================================================


def test_f_runtime_is_ready_after_repair_and_restart(tmp_path):
    directory = tmp_path / "state"
    _build_book(directory, ["req-f"])
    _drop_idempotency_record(directory, "req-f")

    assert reconcile(directory, apply=True).outcome is ReconciliationOutcome.RECONCILED

    manager = _manager(directory, tmp_path)
    assert manager.start() is True
    assert manager.running is True
    assert manager.execution_halted is False
    assert manager.recovery_required is False


def test_g_repaired_request_replays_as_duplicate_and_never_executes_twice(tmp_path):
    directory = tmp_path / "state"
    results = _build_book(directory, ["req-g"])
    _drop_idempotency_record(directory, "req-g")

    assert reconcile(directory, apply=True).outcome is ReconciliationOutcome.RECONCILED

    trader = CountingPaperTrader()
    manager = _manager(directory, tmp_path, paper_trader=trader, full=True)
    assert manager.start()

    replayed = manager.execute(_decision("req-g"), _risk_state())

    assert replayed["duplicate_reason"] == "DUPLICATE_REQUEST_COMPLETED"
    assert replayed["idempotency"]["cache_hit"] is True
    assert replayed["execution_id"] == results["req-g"]["execution_id"]
    assert trader.open_count == 0


# ===========================================================================
# H / I / J - refusal classes
# ===========================================================================


def test_h_conflicting_results_between_authorities_refuse(tmp_path):
    directory = tmp_path / "state"
    _build_book(directory, ["req-h"])

    store = ExecutionIdempotencyStore(directory / IDEMPOTENCY_FILE)
    diverged = dict(store.completed_requests["req-h"])
    diverged["filled_quote_notional"] = "999999"
    store.completed_requests["req-h"] = diverged
    assert store.save()

    outcome = reconcile(directory, apply=True)

    assert outcome.outcome is ReconciliationOutcome.RECONCILIATION_REQUIRED
    assert outcome.reason_code == "AUTHORITY_RESULT_CONFLICT"
    assert outcome.repaired == 0


def test_h_a_terminal_result_with_no_journal_entry_is_never_reconstructed(tmp_path):
    directory = tmp_path / "state"
    _build_book(directory, ["req-h2"])

    journal = ExecutionTransactionJournal(directory / JOURNAL_FILE)
    journal.entries.pop("req-h2")
    assert journal.save()

    outcome = reconcile(directory, apply=True)

    assert outcome.outcome is ReconciliationOutcome.RECONCILIATION_REQUIRED
    assert outcome.reason_code == "JOURNAL_ENTRY_ABSENT"
    assert outcome.repaired == 0


def test_i_missing_application_proof_refuses(tmp_path):
    """The applied-execution authority is the proof that money actually
    moved. Without a record naming this exact request_id and execution_id,
    the missing terminal result is not provably safe to recreate."""
    directory = tmp_path / "state"
    _build_book(directory, ["req-i"])
    _drop_idempotency_record(directory, "req-i")

    # An applied authority whose execution_id disagrees with the journal's
    # result is not proof of this execution.
    lines = (directory / APPLIED_FILE).read_text(encoding="utf-8").splitlines()
    record = json.loads(lines[0])
    record["execution_id"] = "exec-some-other-execution"
    (directory / APPLIED_FILE).write_text(
        json.dumps(record, sort_keys=True, separators=(",", ":")) + "\n", encoding="utf-8",
    )

    outcome = reconcile(directory, apply=True)

    assert outcome.outcome is ReconciliationOutcome.RECONCILIATION_REQUIRED
    assert outcome.reason_code == "FINANCIAL_APPLICATION_UNPROVEN"
    assert outcome.repaired == 0


def test_i_divergent_financial_checkpoint_refuses(tmp_path):
    """The applied record exists, but the book that would confirm it does not
    load cleanly - so the application is not proven committed."""
    directory = tmp_path / "state"
    _build_book(directory, ["req-i2"])
    _drop_idempotency_record(directory, "req-i2")

    payload = json.loads((directory / FINANCIAL_STATE_FILE).read_text(encoding="utf-8"))
    payload["applied_checkpoint"] = {
        "sequence": 41, "execution_id": "exec-unrelated", "idempotency_key": "req-unrelated",
    }
    FinancialStateStore(directory / FINANCIAL_STATE_FILE).save(payload)

    outcome = reconcile(directory, apply=True)

    assert outcome.outcome is ReconciliationOutcome.RECONCILIATION_REQUIRED
    assert outcome.reason_code == "FINANCIAL_APPLICATION_UNPROVEN"


@pytest.mark.parametrize(
    ("corrupt_file", "expected_reason", "expected_outcome"),
    [
        (JOURNAL_FILE, "JOURNAL_UNREADABLE", ReconciliationOutcome.STATE_INVALID),
        (IDEMPOTENCY_FILE, "IDEMPOTENCY_UNREADABLE", ReconciliationOutcome.STATE_INVALID),
    ],
)
def test_j_corrupt_authority_files_refuse(
    tmp_path, corrupt_file, expected_reason, expected_outcome,
):
    directory = tmp_path / "state"
    _build_book(directory, ["req-j"])
    (directory / corrupt_file).write_text("{ not json at all", encoding="utf-8")

    outcome = reconcile(directory, apply=True)

    assert outcome.outcome is expected_outcome
    assert outcome.reason_code == expected_reason


def test_j_corrupt_applied_authority_refuses(tmp_path):
    directory = tmp_path / "state"
    _build_book(directory, ["req-j2"])
    _drop_idempotency_record(directory, "req-j2")
    (directory / APPLIED_FILE).write_text("{ torn line\n", encoding="utf-8")

    outcome = reconcile(directory, apply=True)

    assert outcome.outcome is ReconciliationOutcome.STATE_INVALID
    assert outcome.reason_code == "APPLIED_AUTHORITY_CORRUPT"


def test_j_unresolved_journal_entry_blocks_all_reconciliation(tmp_path):
    """An unresolved transaction is a live question about whether money
    moved. Nothing is reconciled around it - not even a candidate that would
    otherwise be provable."""
    directory = tmp_path / "state"
    _build_book(directory, ["req-j3"])
    _drop_idempotency_record(directory, "req-j3")

    journal = ExecutionTransactionJournal(directory / JOURNAL_FILE)
    assert journal.prepare("req-unresolved", {"request_id": "req-unresolved"})

    before = _snapshot(directory)
    outcome = reconcile(directory, apply=True)

    assert outcome.outcome is ReconciliationOutcome.RECONCILIATION_REQUIRED
    assert outcome.reason_code == "JOURNAL_UNRESOLVED"
    assert outcome.repaired == 0
    assert _snapshot(directory) == before


def test_j_malformed_journal_state_refuses(tmp_path):
    directory = tmp_path / "state"
    _build_book(directory, ["req-j4"])

    journal = ExecutionTransactionJournal(directory / JOURNAL_FILE)
    journal.entries["req-j4"]["state"] = "SOMETHING_ELSE"
    assert journal.save()

    outcome = reconcile(directory, apply=True)

    assert outcome.outcome is ReconciliationOutcome.RECONCILIATION_REQUIRED
    assert outcome.reason_code == "JOURNAL_ENTRY_MALFORMED"


def test_j_absent_state_directory_refuses(tmp_path):
    outcome = reconcile(tmp_path / "no-such-directory", apply=True)

    assert outcome.outcome is ReconciliationOutcome.STATE_INVALID
    assert outcome.reason_code == "STATE_DIRECTORY_ABSENT"


# ===========================================================================
# K - dry run writes nothing
# ===========================================================================


def test_k_dry_run_changes_no_bytes(tmp_path):
    directory = tmp_path / "state"
    _build_book(directory, ["req-k"])
    _drop_idempotency_record(directory, "req-k")
    before = _snapshot(directory)

    outcome = reconcile(directory)

    assert outcome.outcome is ReconciliationOutcome.WOULD_RECONCILE
    assert outcome.reason_code == "DRY_RUN"
    assert (outcome.repairable, outcome.repaired) == (1, 0)
    assert _snapshot(directory) == before

    # The CLI default is the dry run; --apply is the only way to write.
    completed = run_cli("--state-directory", str(directory))
    assert completed.returncode == 0
    assert "WOULD_RECONCILE" in completed.stdout
    assert _snapshot(directory) == before


def test_k_apply_and_dry_run_together_is_a_usage_error(tmp_path):
    directory = tmp_path / "state"
    _build_book(directory, ["req-k2"])
    before = _snapshot(directory)

    completed = run_cli("--state-directory", str(directory), "--apply", "--dry-run")

    assert completed.returncode == 1
    assert _snapshot(directory) == before


# ===========================================================================
# L / M - a failed repair restores originals and never reports success
# ===========================================================================


def test_l_failed_post_write_verification_restores_originals_byte_for_byte(
    tmp_path, monkeypatch,
):
    """The pre-write gates are strict enough that no natural input is known to
    reach a post-write failure; the post-write gates are defence in depth, so
    the failure is injected here to prove the restore path itself."""
    directory = tmp_path / "state"
    _build_book(directory, ["req-l"])
    _drop_idempotency_record(directory, "req-l")
    before = _snapshot(directory)

    monkeypatch.setattr(
        reconcile_module, "_verify_repair",
        lambda **_: "POST_REPAIR_VERIFICATION_FAILED",
    )

    outcome = reconcile(directory, apply=True)

    assert outcome.outcome is ReconciliationOutcome.FAILED
    assert outcome.reason_code == "POST_REPAIR_VERIFICATION_FAILED"
    assert outcome.repaired == 0
    assert _snapshot(directory) == before


def test_m_post_write_failure_reports_non_zero_and_not_reconciled(tmp_path):
    directory = tmp_path / "state"
    _build_book(directory, ["req-m"])
    _drop_idempotency_record(directory, "req-m")

    assert reconcile_module._exit_code(
        reconcile_module.ReconciliationResult(
            ReconciliationOutcome.FAILED, "POST_REPAIR_RUNTIME_NOT_READY", str(directory),
        )
    ) == 3
    assert reconcile_module._exit_code(
        reconcile_module.ReconciliationResult(
            ReconciliationOutcome.RECONCILIATION_REQUIRED, "AUTHORITY_RESULT_CONFLICT",
            str(directory),
        )
    ) == 2
    assert reconcile_module._exit_code(
        reconcile_module.ReconciliationResult(
            ReconciliationOutcome.RECONCILED, "RECONCILIATION_COMPLETE", str(directory),
        )
    ) == 0


def test_m_repair_that_the_idempotency_store_will_not_persist_fails_closed(
    tmp_path, monkeypatch,
):
    directory = tmp_path / "state"
    _build_book(directory, ["req-m2"])
    _drop_idempotency_record(directory, "req-m2")
    before = _snapshot(directory)

    monkeypatch.setattr(ExecutionIdempotencyStore, "save", lambda self: False)

    outcome = reconcile(directory, apply=True)

    assert outcome.outcome is ReconciliationOutcome.FAILED
    assert outcome.reason_code == "IDEMPOTENCY_WRITE_FAILED"
    assert _snapshot(directory) == before


# ===========================================================================
# N - operator output safety (ADR-0005)
# ===========================================================================


_SECRET_TOKENS = (
    "SECRET-REQUEST-ID", "SECRET-EXEC-ID", "SECRET-POSITION-ID", "SECRET-ORDER-ID",
)


def _assert_output_is_safe(text: str) -> None:
    for token in _SECRET_TOKENS:
        assert token not in text, token
    # No raw state-file payload fragments either. ("journal_entries" is a
    # count field of this tool's own output, so "entries" is not a marker.)
    for fragment in (
        "filled_quote_notional", "commit_outcome", "completed_requests",
        "PAPER_EXECUTED", "order_id",
    ):
        assert fragment not in text, fragment


def test_n_operator_output_never_exposes_identifiers_or_payloads(tmp_path):
    directory = tmp_path / "state"
    directory.mkdir()

    # A book whose every identifier is a marker string, in every outcome the
    # CLI can report.
    store = FinancialStateStore(directory / FINANCIAL_STATE_FILE)
    store.initialize(D("1000"))
    foundation = ExecutionPortfolioFoundation(
        store,
        applied_archive=AppliedExecutionArchiveStore(directory / APPLIED_FILE),
        closed_archive=ClosedPositionArchiveStore(directory / CLOSED_FILE),
    )
    position_id = mint_long_position_id(_SYMBOL, "SECRET-POSITION-ID")
    foundation.apply_confirmed(
        _fill(execution_id="SECRET-EXEC-ID", position_id=position_id,
              request_id="SECRET-REQUEST-ID"),
        risk_authorized=True, reservation_confirmed=True, expected_position_version=None,
    )
    result = _confirmed_result(
        "SECRET-REQUEST-ID", execution_id="SECRET-EXEC-ID", position_id=position_id,
    )
    result["order_id"] = "SECRET-ORDER-ID"
    journal = ExecutionTransactionJournal(directory / JOURNAL_FILE)
    assert journal.mark_committed("SECRET-REQUEST-ID", result)

    for arguments in (
        ("--state-directory", str(directory)),
        ("--state-directory", str(directory), "--json"),
        ("--state-directory", str(directory), "--apply"),
        ("--state-directory", str(directory), "--apply", "--json"),
    ):
        completed = run_cli(*arguments)
        _assert_output_is_safe(completed.stdout)
        _assert_output_is_safe(completed.stderr)

    # ... and the same for the successful repair path.
    assert ExecutionIdempotencyStore(directory / IDEMPOTENCY_FILE).record(
        "SECRET-REQUEST-ID", result, save=True,
    )
    ExecutionIdempotencyStore(directory / IDEMPOTENCY_FILE).remove(
        "SECRET-REQUEST-ID", save=True,
    )
    repaired = run_cli("--state-directory", str(directory), "--apply", "--json")
    assert repaired.returncode == 0
    payload = json.loads(repaired.stdout)
    assert payload["outcome"] == "RECONCILED"
    assert payload["reason_code"] == "RECONCILIATION_COMPLETE"
    _assert_output_is_safe(repaired.stdout)


def test_n_reset_refusal_message_is_a_fixed_token_only(tmp_path):
    directory = tmp_path / "state"
    _build_book(directory, ["SECRET-REQUEST-ID"])
    manager = _manager(directory, tmp_path)

    with pytest.raises(ExecutionResetRefusedError) as raised:
        manager.reset()

    _assert_output_is_safe(str(raised.value))
    assert str(raised.value) == "EXECUTION_HISTORY_PRESENT"


# ===========================================================================
# O - no unrelated state is ever mutated
# ===========================================================================


def test_o_repair_mutates_only_the_idempotency_authority(tmp_path):
    directory = tmp_path / "state"
    _build_book(directory, ["req-o1", "req-o2", "req-o3"])
    _drop_idempotency_record(directory, "req-o2")
    before = _snapshot(directory)

    outcome = reconcile(directory, apply=True)
    after = _snapshot(directory)

    assert outcome.outcome is ReconciliationOutcome.RECONCILED
    for name in ALL_STATE_FILES:
        if name == IDEMPOTENCY_FILE:
            assert after[name] != before[name]
        else:
            assert after[name] == before[name], name

    # The book itself is untouched: no pending transition, and the applied
    # checkpoint still names the last execution the runtime actually applied.
    financial = json.loads((directory / FINANCIAL_STATE_FILE).read_text(encoding="utf-8"))
    assert financial["transition"] is None
    assert financial["applied_checkpoint"]["idempotency_key"] == "req-o3"
    assert financial["cash"] == json.loads(before[FINANCIAL_STATE_FILE])["cash"]


def test_o_a_healthy_book_reports_agreement_and_writes_nothing(tmp_path):
    directory = tmp_path / "state"
    _build_book(directory, ["req-o4", "req-o5"])
    before = _snapshot(directory)

    outcome = reconcile(directory, apply=True)

    assert outcome.outcome is ReconciliationOutcome.AUTHORITIES_AGREE
    assert outcome.reason_code == "AUTHORITIES_ALREADY_AGREE"
    assert (outcome.journal_entries, outcome.idempotency_records) == (2, 2)
    assert _snapshot(directory) == before
