"""
Block 5 / Package 5H-0 - Execution Evidence Authority Alignment.

Proves:
- ExecutionIdempotencyStore is unbounded by default (DEFAULT_MAX_RECORDS is
  None); a COMMITTED request_id can no longer be pruned out from under a
  transaction journal entry that still claims it COMMITTED.
- Explicit bounded retention remains available for tests only, and still
  reproduces the historical defect (SOURCE_DISAGREEMENT after the bound is
  crossed) so the regression has a permanent witness.
- ExecutionTransactionJournal.prepare() refuses to reopen a COMMITTED
  entry, so a stale retry can never reset an actually-executed request
  back to PREPARED. NOT_COMMITTED (no side effect occurred) deliberately
  remains re-preparable, matching ExecutionManager's existing retry
  contract for denials that never crossed the side-effect boundary.
- Genuine authority disagreement (independent of retention) still fails
  closed, and CanonicalExecutionEvidenceAdapter still requires agreement.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest

from core.capital_reservation import CapitalReservationLedger, JsonReservationStore
from core.execution_idempotency_store import ExecutionIdempotencyStore
from core.execution_manager import ExecutionManager
from core.execution_transaction_journal import (
    CommitOutcome,
    ExecutionTransactionJournal,
)
from core.instrument_rules import InstrumentRules, InstrumentRuleset
from core.risk_engine import RiskEngine, RiskPolicy, RiskState
from core.risk_state_store import JsonRiskStateStore, RestoredRiskState
from data_layer.canonical_evidence import CanonicalExecutionEvidenceAdapter
from data_layer.contracts import IntegrityViolation
from data_layer.runtime_safety import FinancialRuntimeSafetyService


# The historical ExecutionIdempotencyStore.DEFAULT_MAX_RECORDS this package
# removes from production. Reused here as the synthetic "old threshold" so
# the regression this package fixes has a permanent, literal witness.
OLD_DEFAULT_MAX_RECORDS = 5_000

_BTCUSDT_RULES = InstrumentRuleset({
    "BTCUSDT": InstrumentRules(
        venue="BINANCE", symbol="BTCUSDT", base_asset="BTC", quote_asset="USDT",
        quantity_step="0.00001", min_quantity="0.00001", min_notional="5",
        price_tick="0.01", source="test-fixture", source_version="v1",
        retrieved_at="2026-01-01T00:00:00Z",
    ),
})


def _confirmed_result(request_id: str, *, execution_id: str | None = None) -> dict[str, Any]:
    """A COMMITTED terminal result shaped like the one ExecutionManager
    passes to both transaction_journal.mark_committed() and
    idempotency_store.record() for the same request."""

    return {
        "success": True,
        "status": "PAPER_EXECUTED",
        "commit_outcome": "COMMITTED",
        "request_id": request_id,
        "order_id": f"order-{request_id}",
        "execution_id": execution_id or f"exec-{request_id}",
        "position_id": f"position-{request_id}",
        "symbol": "BTCUSDT",
        "action": "BUY",
        "filled_base_quantity": "0.00100",
        "filled_quote_notional": "50.00",
        "filled_price": "50000.00",
        "fee_amount": "0.05",
        "timestamp": "2026-08-22T00:00:00+00:00",
    }


def _rejected_result(request_id: str) -> dict[str, Any]:
    return {
        "success": False,
        "status": "REJECTED",
        "request_id": request_id,
        "reason": "RISK_REJECTED",
        "timestamp": "2026-08-22T00:00:00+00:00",
    }


def _decision(request_id: str) -> dict[str, Any]:
    return {
        "request_id": request_id,
        "action": "BUY",
        "symbol": "BTCUSDT",
        "price": 65000.0,
        "amount": 100.0,
        "confidence": 90.0,
        "strategy": "BLOCK5H0_TEST",
        "risk": "LOW",
        "mode": "PAPER",
    }


def _risk_state() -> RiskState:
    return RiskState((), Decimal("0"), Decimal("0"), Decimal("1000"),
                      Decimal("1000"), True, datetime.now(UTC).date().isoformat(),
                      "phase3-risk-v1")


class CountingPaperTrader:
    def __init__(self) -> None:
        self.open_count = 0

    def open_trade(self, symbol: str, price: float, amount: float) -> dict[str, Any]:
        self.open_count += 1
        return {
            "success": True,
            "status": "FILLED",
            "trade_id": f"paper-{self.open_count}",
            "symbol": symbol,
            "price": price,
            "amount": amount,
        }


def _full_manager(
    tmp_path: Path,
    *,
    idempotency_store: ExecutionIdempotencyStore,
    transaction_journal: ExecutionTransactionJournal,
    paper_trader: CountingPaperTrader,
) -> ExecutionManager:
    reservation_store = JsonReservationStore(tmp_path / "reservations.json")
    reservation_store.initialize_empty()
    risk_store = JsonRiskStateStore(tmp_path / "risk-state.json")
    risk_store.save(RestoredRiskState(datetime.now(UTC).date(), Decimal("0"),
                                      Decimal("1000"), Decimal("1000"), "phase3-risk-v1"))
    manager = ExecutionManager(
        paper_trader=paper_trader,
        idempotency_store=idempotency_store,
        transaction_journal=transaction_journal,
        audit_enabled=False,
        risk_engine=RiskEngine(RiskPolicy(total_capital=Decimal("1000"))),
        reservation_ledger=CapitalReservationLedger(reservation_store, Decimal("800")),
        risk_state_store=risk_store,
        instrument_rules=_BTCUSDT_RULES,
    )
    manager.start()
    return manager


# =============================================================================
# A. Old-bound crossing
# =============================================================================


def test_a_old_bound_crossing_then_production_unbounded(tmp_path: Path) -> None:
    # Phase 1: reproduce the historical defect with the old explicit bound.
    bounded_store = ExecutionIdempotencyStore(
        file_path=tmp_path / "bounded_idempotency.json",
        max_records=OLD_DEFAULT_MAX_RECORDS,
    )
    assert bounded_store.max_records == OLD_DEFAULT_MAX_RECORDS

    bounded_ids = [f"bounded-{i:05d}" for i in range(OLD_DEFAULT_MAX_RECORDS + 1)]
    for request_id in bounded_ids:
        assert bounded_store.record(request_id, _confirmed_result(request_id), save=False)

    assert len(bounded_store.completed_requests) == OLD_DEFAULT_MAX_RECORDS
    assert bounded_store.stats["records_pruned"] == 1
    assert bounded_ids[0] not in bounded_store.completed_requests
    assert bounded_ids[-1] in bounded_store.completed_requests

    bounded_journal = ExecutionTransactionJournal(file_path=tmp_path / "bounded_journal.json")
    for request_id in bounded_ids:
        bounded_journal.entries[request_id] = {
            "state": CommitOutcome.COMMITTED.value,
            "result": _confirmed_result(request_id),
        }

    bounded_readiness = FinancialRuntimeSafetyService(
        transaction_journal=bounded_journal,
        idempotency_store=bounded_store,
    ).assess()

    assert bounded_readiness.ready is False
    assert bounded_readiness.decision.reason == "SOURCE_DISAGREEMENT"

    # Phase 2: production-unbounded mode, well beyond the old threshold.
    unbounded_store = ExecutionIdempotencyStore(file_path=tmp_path / "unbounded_idempotency.json")
    assert unbounded_store.max_records is None

    wide_ids = [f"wide-{i:05d}" for i in range(OLD_DEFAULT_MAX_RECORDS + 500)]
    for request_id in wide_ids:
        assert unbounded_store.record(request_id, _confirmed_result(request_id), save=False)

    assert len(unbounded_store.completed_requests) == len(wide_ids)
    assert unbounded_store.stats["records_pruned"] == 0
    assert all(rid in unbounded_store.completed_requests for rid in wide_ids)

    wide_journal = ExecutionTransactionJournal(file_path=tmp_path / "wide_journal.json")
    for request_id in wide_ids:
        wide_journal.entries[request_id] = {
            "state": CommitOutcome.COMMITTED.value,
            "result": _confirmed_result(request_id),
        }

    wide_readiness = FinancialRuntimeSafetyService(
        transaction_journal=wide_journal,
        idempotency_store=unbounded_store,
    ).assess()

    assert wide_readiness.ready is True


# =============================================================================
# B. Production default
# =============================================================================


def test_b_production_default_constructs_unbounded(tmp_path: Path) -> None:
    assert ExecutionIdempotencyStore.DEFAULT_MAX_RECORDS is None

    store = ExecutionIdempotencyStore(file_path=tmp_path / "idempotency.json")

    assert store.max_records is None
    assert store.status()["max_records"] is None

    for i in range(50):
        request_id = f"req-{i:03d}"
        assert store.record(request_id, _confirmed_result(request_id), save=False)

    assert len(store.completed_requests) == 50
    assert store.stats["records_pruned"] == 0


# =============================================================================
# C. Restart
# =============================================================================


def test_c_restart_reload_agrees_after_many_committed_requests(tmp_path: Path) -> None:
    idempotency_path = tmp_path / "idempotency.json"
    journal_path = tmp_path / "journal.json"

    store = ExecutionIdempotencyStore(file_path=idempotency_path)
    journal = ExecutionTransactionJournal(file_path=journal_path)

    request_ids = [f"restart-{i:04d}" for i in range(500)]
    for request_id in request_ids:
        result = _confirmed_result(request_id)
        assert store.record(request_id, result, save=False)
        journal.entries[request_id] = {
            "state": CommitOutcome.COMMITTED.value,
            "result": result,
        }

    assert store.save()
    assert journal.save()

    reloaded_store = ExecutionIdempotencyStore(file_path=idempotency_path)
    reloaded_journal = ExecutionTransactionJournal(file_path=journal_path)

    assert reloaded_store.max_records is None
    assert len(reloaded_store.completed_requests) == len(request_ids)
    assert reloaded_store.stats["records_pruned"] == 0

    for request_id in request_ids:
        assert request_id in reloaded_store.completed_requests
        assert reloaded_journal.entries[request_id]["state"] == "COMMITTED"

    manager = ExecutionManager(
        idempotency_store=reloaded_store,
        transaction_journal=reloaded_journal,
        audit_enabled=False,
    )

    assert manager.start()
    assert manager.running is True
    assert manager.execution_halted is False
    assert manager.recovery_required is False


# =============================================================================
# D. Oldest request replay
# =============================================================================


def test_d_oldest_request_still_replays_after_crossing_old_threshold_and_restart(
    tmp_path: Path,
) -> None:
    idempotency_path = tmp_path / "idempotency.json"
    journal_path = tmp_path / "journal.json"

    store = ExecutionIdempotencyStore(file_path=idempotency_path)
    journal = ExecutionTransactionJournal(file_path=journal_path)

    oldest_request_id = "oldest-request"
    oldest_result = _confirmed_result(oldest_request_id, execution_id="exec-oldest")
    assert store.record(oldest_request_id, oldest_result, save=False)
    journal.entries[oldest_request_id] = {
        "state": CommitOutcome.COMMITTED.value,
        "result": oldest_result,
    }

    for i in range(OLD_DEFAULT_MAX_RECORDS):
        filler_id = f"filler-{i:05d}"
        filler_result = _confirmed_result(filler_id)
        assert store.record(filler_id, filler_result, save=False)
        journal.entries[filler_id] = {
            "state": CommitOutcome.COMMITTED.value,
            "result": filler_result,
        }

    assert store.stats["records_pruned"] == 0
    assert len(store.completed_requests) == OLD_DEFAULT_MAX_RECORDS + 1

    assert store.save()
    assert journal.save()

    restarted_store = ExecutionIdempotencyStore(file_path=idempotency_path)
    restarted_journal = ExecutionTransactionJournal(file_path=journal_path)

    assert oldest_request_id in restarted_store.completed_requests

    trader = CountingPaperTrader()
    manager = _full_manager(
        tmp_path,
        idempotency_store=restarted_store,
        transaction_journal=restarted_journal,
        paper_trader=trader,
    )

    result = manager.execute(_decision(oldest_request_id), _risk_state())

    assert result["duplicate_reason"] == "DUPLICATE_REQUEST_COMPLETED"
    assert result["idempotency"]["cache_hit"] is True
    assert result["idempotency"]["original_status"] == "PAPER_EXECUTED"
    assert result["execution_id"] == "exec-oldest"
    assert trader.open_count == 0


# =============================================================================
# E. Rejection pressure
# =============================================================================


def test_e_rejection_pressure_cannot_evict_committed_record(tmp_path: Path) -> None:
    store = ExecutionIdempotencyStore(file_path=tmp_path / "idempotency.json")
    journal = ExecutionTransactionJournal(file_path=tmp_path / "journal.json")

    committed_id = "committed-request"
    committed_result = _confirmed_result(committed_id, execution_id="exec-committed")
    assert store.record(committed_id, committed_result, save=False)
    journal.entries[committed_id] = {
        "state": CommitOutcome.COMMITTED.value,
        "result": committed_result,
    }

    for i in range(1_500):
        rejected_id = f"rejected-{i:05d}"
        assert store.record(rejected_id, _rejected_result(rejected_id), save=False)

    assert store.stats["records_pruned"] == 0
    assert committed_id in store.completed_requests
    assert store.completed_requests[committed_id]["execution_id"] == "exec-committed"

    readiness = FinancialRuntimeSafetyService(
        transaction_journal=journal,
        idempotency_store=store,
    ).assess()

    assert readiness.ready is True


# =============================================================================
# F. Genuine disagreement
# =============================================================================


def test_f_genuine_disagreement_still_fails_closed(tmp_path: Path) -> None:
    store = ExecutionIdempotencyStore(file_path=tmp_path / "idempotency.json")
    journal = ExecutionTransactionJournal(file_path=tmp_path / "journal.json")

    request_id = "req-corrupted"
    result = _confirmed_result(request_id)
    assert store.record(request_id, result, save=False)
    journal.entries[request_id] = {
        "state": CommitOutcome.COMMITTED.value,
        "result": result,
    }

    # Simulate loss/corruption of the idempotency counterpart, independent of
    # any retention policy. Unbounded retention removes the SPURIOUS
    # disagreement pruning used to cause; it must not remove this one.
    assert store.remove(request_id, save=False)

    readiness = FinancialRuntimeSafetyService(
        transaction_journal=journal,
        idempotency_store=store,
    ).assess()

    assert readiness.ready is False
    assert readiness.decision.reason == "SOURCE_DISAGREEMENT"

    manager = ExecutionManager(
        idempotency_store=store,
        transaction_journal=journal,
        audit_enabled=False,
    )

    assert manager.start()
    assert manager.execution_halted is True
    assert manager.recovery_required is True
    assert manager.halt_reason == "SOURCE_DISAGREEMENT"


# =============================================================================
# G. Canonical evidence
# =============================================================================


def test_g_canonical_evidence_adapter_large_committed_set(tmp_path: Path) -> None:
    store = ExecutionIdempotencyStore(file_path=tmp_path / "idempotency.json")
    journal = ExecutionTransactionJournal(file_path=tmp_path / "journal.json")

    request_ids = [f"evidence-{i:05d}" for i in range(2_000)]
    for request_id in request_ids:
        result = _confirmed_result(request_id, execution_id=f"exec-{request_id}")
        assert store.record(request_id, result, save=False)
        journal.entries[request_id] = {
            "state": CommitOutcome.COMMITTED.value,
            "result": result,
        }

    adapter = CanonicalExecutionEvidenceAdapter(journal, store)
    evidence = tuple(adapter())

    assert len(evidence) == len(request_ids)
    assert {item.request_id for item in evidence} == set(request_ids)

    # Mutate one idempotency counterpart so it disagrees with its journal
    # record on a shared field.
    mutated_id = request_ids[0]
    mutated_result = dict(
        store.completed_requests[mutated_id],
        execution_id="tampered-execution-id",
    )
    assert store.record(mutated_id, mutated_result, save=False)

    with pytest.raises(IntegrityViolation):
        tuple(adapter())

    # Now remove the counterpart entirely.
    assert store.remove(mutated_id, save=False)

    with pytest.raises(IntegrityViolation):
        tuple(adapter())


# =============================================================================
# H. Journal terminal guard
# =============================================================================


def test_h1_journal_refuses_to_reopen_committed_entry(tmp_path: Path) -> None:
    journal = ExecutionTransactionJournal(file_path=tmp_path / "journal.json")
    request_id = "req-terminal-committed"

    assert journal.prepare(request_id, {"action": "BUY", "symbol": "BTCUSDT"})
    result = _confirmed_result(request_id)
    assert journal.mark_committed(request_id, result)

    committed_entry = dict(journal.entries[request_id])

    refused = journal.prepare(
        request_id,
        {"action": "BUY", "symbol": "BTCUSDT", "attempt": 2},
    )

    assert refused is False
    assert journal.entries[request_id]["state"] == "COMMITTED"
    assert journal.entries[request_id] == committed_entry


def test_h2_journal_still_allows_reprepare_of_not_committed_entry(tmp_path: Path) -> None:
    """NOT_COMMITTED is the *other* outcome named in CommitOutcome, but it is
    deliberately NOT covered by the terminal guard. ExecutionManager's own
    contract (_resolve_unsuccessful_execution) is that a request resolved
    NOT_COMMITTED - because its side-effect boundary was never crossed -
    "stays retryable": a fresh prepare() for the same request_id must
    succeed again. tests/test_block3_terminal_status_classification.py
    ::test_live_denial_leaves_the_request_retryable already depends on this
    exact behavior (a LIVE_DISABLED denial with no side effect must be
    retryable through the identical path on a second attempt), so guarding
    NOT_COMMITTED the same way COMMITTED is guarded would silently break an
    existing, intentional contract rather than harden one."""

    journal = ExecutionTransactionJournal(file_path=tmp_path / "journal.json")
    request_id = "req-terminal-not-committed"

    assert journal.prepare(request_id, {"action": "BUY", "symbol": "BTCUSDT"})
    assert journal.mark_not_committed(
        request_id,
        reason="LIVE_DISABLED",
    )
    assert journal.entries[request_id]["state"] == "NOT_COMMITTED"

    retried = journal.prepare(
        request_id,
        {"action": "BUY", "symbol": "BTCUSDT", "retry": True},
    )

    assert retried is True
    assert journal.entries[request_id]["state"] == "PREPARED"
    assert journal.entries[request_id]["request"]["retry"] is True


def test_h3_journal_still_allows_reprepare_of_unresolved_states(tmp_path: Path) -> None:
    journal = ExecutionTransactionJournal(file_path=tmp_path / "journal.json")
    request_id = "req-unresolved"

    assert journal.prepare(request_id, {"action": "BUY", "symbol": "BTCUSDT"})
    assert journal.entries[request_id]["state"] == "PREPARED"

    # Re-preparing an unresolved (non-terminal) entry is unchanged behavior.
    assert journal.prepare(
        request_id,
        {"action": "BUY", "symbol": "BTCUSDT", "retry": True},
    )
    assert journal.entries[request_id]["state"] == "PREPARED"
    assert journal.entries[request_id]["request"]["retry"] is True

    assert journal.mark_unknown(request_id, reason="TEST_UNKNOWN")
    assert journal.entries[request_id]["state"] == "COMMIT_STATUS_UNKNOWN"

    # COMMIT_STATUS_UNKNOWN is unresolved, not terminal - prepare() must
    # still be able to move it back to PREPARED for recovery.
    assert journal.prepare(
        request_id,
        {"action": "BUY", "symbol": "BTCUSDT", "retry": 2},
    )
    assert journal.entries[request_id]["state"] == "PREPARED"


# =============================================================================
# I. Explicit bounded test mode
# =============================================================================


def test_i1_explicit_bounded_test_mode_still_prunes(tmp_path: Path) -> None:
    store = ExecutionIdempotencyStore(file_path=tmp_path / "idempotency.json", max_records=3)
    assert store.max_records == 3

    for i in range(5):
        request_id = f"req-{i}"
        assert store.record(request_id, _confirmed_result(request_id), save=False)

    assert len(store.completed_requests) == 3
    assert store.stats["records_pruned"] == 2
    assert "req-0" not in store.completed_requests
    assert "req-1" not in store.completed_requests
    assert "req-4" in store.completed_requests


@pytest.mark.parametrize("invalid_value,expected", [(0, 1), (-5, 1)])
def test_i2_explicit_invalid_bounds_normalize_like_before(
    tmp_path: Path,
    invalid_value: int,
    expected: int,
) -> None:
    store = ExecutionIdempotencyStore(
        file_path=tmp_path / "idempotency.json",
        max_records=invalid_value,
    )

    assert store.max_records == expected


# =============================================================================
# J. Persisted-format compatibility
# =============================================================================


def test_j_v1_persisted_format_loads_without_migration_and_stops_pruning(
    tmp_path: Path,
) -> None:
    path = tmp_path / "idempotency.json"
    legacy_ids = [f"legacy-{i:04d}" for i in range(10)]
    legacy_payload = {
        "version": "1.0",
        "updated_at": "2026-01-01T00:00:00+00:00",
        "completed_requests": {
            request_id: _confirmed_result(request_id) for request_id in legacy_ids
        },
    }
    path.write_text(json.dumps(legacy_payload), encoding="utf-8")

    store = ExecutionIdempotencyStore(file_path=path)

    assert store.VERSION == "1.0"
    assert store.max_records is None
    assert len(store.completed_requests) == len(legacy_ids)
    for request_id in legacy_ids:
        assert request_id in store.completed_requests

    for i in range(200):
        request_id = f"new-{i:05d}"
        assert store.record(request_id, _confirmed_result(request_id), save=False)

    assert store.stats["records_pruned"] == 0
    assert len(store.completed_requests) == len(legacy_ids) + 200
    for request_id in legacy_ids:
        assert request_id in store.completed_requests
