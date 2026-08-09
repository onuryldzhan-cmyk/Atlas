from __future__ import annotations

from copy import deepcopy
from pathlib import Path

import pytest

from data_layer.canonical_evidence import CanonicalExecutionEvidenceAdapter
from data_layer.contracts import IntegrityViolation
from data_layer.runtime_safety import FinancialRuntimeSafetyService
from data_layer.sqlite import SQLiteStorage


def result():
    return {"success": True, "status": "FILLED", "commit_outcome": "COMMITTED", "request_id": "req-1", "order_id": "order-1", "execution_id": "exec-1", "position_id": "position-1", "symbol": "BTCUSDT", "action": "BUY", "filled_base_quantity": "0.25", "filled_quote_notional": "10000", "filled_price": "40000", "fee_amount": "1", "timestamp": "2026-08-09T00:00:00+00:00"}


class Journal:
    loaded = True
    load_failed = False
    def __init__(self, value=None): self.entries = {"req-1": {"state": "COMMITTED", "result": value or result()}}
    def has_unresolved(self): return any(v["state"] in {"PREPARED", "COMMIT_STATUS_UNKNOWN"} for v in self.entries.values())


class Idempotency:
    loaded = True
    def __init__(self, value=None): self.completed_requests = {"req-1": value or result()}


def test_valid_canonical_authorities_adapt_with_explicit_provenance():
    evidence = tuple(CanonicalExecutionEvidenceAdapter(Journal(), Idempotency())())
    assert len(evidence) == 1 and evidence[0].execution_id == "exec-1"
    assert evidence[0].metadata["provenance"] == ["ExecutionTransactionJournal", "ExecutionIdempotencyStore", "ExecutionResult"]


@pytest.mark.parametrize("mutation", [lambda x: x.pop("order_id"), lambda x: x.update(symbol="ETHUSDT"), lambda x: x.update(commit_outcome="COMMIT_STATUS_UNKNOWN")])
def test_incomplete_conflicting_or_indeterminate_evidence_is_rejected(mutation):
    other = deepcopy(result()); mutation(other)
    with pytest.raises(IntegrityViolation): tuple(CanonicalExecutionEvidenceAdapter(Journal(), Idempotency(other))())


def test_adapter_has_no_exchange_surface_and_makes_no_exchange_call():
    adapter = CanonicalExecutionEvidenceAdapter(Journal(), Idempotency())
    assert not hasattr(adapter, "exchange")
    assert len(tuple(adapter())) == 1


def test_restart_default_adapter_replays_and_verifies_before_ready(tmp_path: Path):
    storage = SQLiteStorage(tmp_path / "projection.sqlite3"); storage.open()
    try:
        first = FinancialRuntimeSafetyService(transaction_journal=Journal(), idempotency_store=Idempotency(), storage=storage).assess()
        second = FinancialRuntimeSafetyService(transaction_journal=Journal(), idempotency_store=Idempotency(), storage=storage).assess()
        assert first.ready and first.replayed == 3
        assert second.ready and second.replayed == 0
    finally: storage.close()


def test_disagreement_blocks_ready(tmp_path: Path):
    other = result(); other["execution_id"] = "exec-conflict"
    storage = SQLiteStorage(tmp_path / "projection.sqlite3"); storage.open()
    try:
        readiness = FinancialRuntimeSafetyService(transaction_journal=Journal(), idempotency_store=Idempotency(other), storage=storage).assess()
        assert not readiness.ready and readiness.decision.reason == "PROJECTION_REPLAY_FAILED"
    finally: storage.close()


@pytest.mark.parametrize("missing", ["filled_base_quantity", "filled_quote_notional", "execution_id", "position_id"])
def test_adapter_rejects_missing_explicit_financial_or_identity_semantics(missing):
    broken = result(); broken.pop(missing)
    with pytest.raises(IntegrityViolation):
        tuple(CanonicalExecutionEvidenceAdapter(Journal(broken), Idempotency(broken))())


def test_ambiguous_legacy_filled_amount_is_never_accepted_as_base_quantity():
    broken = result(); broken.pop("filled_base_quantity"); broken["filled_amount"] = "1000"
    with pytest.raises(IntegrityViolation, match="filled_base_quantity"):
        tuple(CanonicalExecutionEvidenceAdapter(Journal(broken), Idempotency(broken))())
