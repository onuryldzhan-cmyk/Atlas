from __future__ import annotations

import ast
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

import pytest

from data_layer.projection_replay import ConfirmedExecutionEvidence
from data_layer.recovery import RecoveryDisposition
from data_layer.runtime_safety import FinancialRuntimeSafetyService
from data_layer.sqlite import SQLiteStorage
from core.execution_idempotency_store import ExecutionIdempotencyStore
from core.execution_manager import ExecutionManager
from core.execution_transaction_journal import ExecutionTransactionJournal


ROOT = Path(__file__).resolve().parents[1]
NOW = datetime(2026, 8, 9, tzinfo=UTC)


class Journal:
    def __init__(self, entries=None, *, valid=True):
        self.entries = entries or {}
        self.loaded = valid
        self.load_failed = not valid

    def has_unresolved(self):
        return any(item["state"] in {"PREPARED", "COMMIT_STATUS_UNKNOWN"} for item in self.entries.values())


class Idempotency:
    def __init__(self, completed=None, *, valid=True):
        self.completed_requests = completed or {}
        self.loaded = valid


def confirmed():
    return ConfirmedExecutionEvidence(
        request_id="req-1", order_id="order-1", execution_id="exec-1",
        symbol="BTCUSDT", side="BUY", base_quantity=Decimal("0.25"),
        filled_quote_notional=Decimal("10000"),
        price=Decimal("40000"), fee=Decimal("1"), executed_at=NOW,
        position_id="position-1",
    )


@pytest.fixture
def storage(tmp_path):
    backend = SQLiteStorage(tmp_path / "runtime-safety.sqlite3")
    backend.open()
    yield backend
    backend.close()


def service(journal=None, idempotency=None, **kwargs):
    return FinancialRuntimeSafetyService(
        transaction_journal=journal or Journal(),
        idempotency_store=idempotency or Idempotency(),
        **kwargs,
    )


def test_clean_state_becomes_financially_ready():
    assert service().assess().ready


def test_canonical_execution_manager_clean_start_is_financially_ready(tmp_path):
    manager = ExecutionManager(
        idempotency_store=ExecutionIdempotencyStore(tmp_path / "idempotency.json"),
        transaction_journal=ExecutionTransactionJournal(tmp_path / "journal.json"),
        audit_enabled=False,
    )
    assert manager.start()
    assert manager.running and not manager.execution_halted and not manager.recovery_required


def test_canonical_execution_manager_unresolved_start_blocks_financial_admission(tmp_path):
    journal = ExecutionTransactionJournal(tmp_path / "journal.json")
    assert journal.prepare("req-unresolved", {"action": "BUY", "symbol": "BTCUSDT"})
    manager = ExecutionManager(
        idempotency_store=ExecutionIdempotencyStore(tmp_path / "idempotency.json"),
        transaction_journal=journal,
        audit_enabled=False,
    )
    assert manager.start()
    assert manager.running and manager.execution_halted and manager.recovery_required
    assert manager.halt_reason == "UNRESOLVED_JOURNAL"


@pytest.mark.parametrize(
    "entries,reason",
    [
        ({"req-1": {"state": "PREPARED"}}, "UNRESOLVED_JOURNAL"),
        ({"req-1": {"state": "COMMIT_STATUS_UNKNOWN"}}, "EXTERNAL_OUTCOME_INDETERMINATE"),
    ],
)
def test_unresolved_or_indeterminate_journal_blocks_admission(entries, reason):
    result = service(journal=Journal(entries)).assess()
    assert not result.ready
    assert result.decision.reason == reason
    assert not result.decision.blind_retry_allowed


def test_authority_disagreement_blocks():
    result = service(journal=Journal({"req-1": {"state": "COMMITTED"}})).assess()
    assert not result.ready
    assert result.decision.reason == "SOURCE_DISAGREEMENT"


@pytest.mark.parametrize("check,reason", [("relational_state_valid", "PERSISTED_STATE_CORRUPT"), ("schema_valid", "SCHEMA_OR_MIGRATION_INVALID")])
def test_corruption_or_schema_failure_blocks(check, reason):
    result = service(**{check: lambda: False}).assess()
    assert not result.ready and result.decision.reason == reason


def test_confirmed_missing_projection_replays_without_exchange_and_then_readies(storage):
    calls = 0

    def source():
        nonlocal calls
        calls += 1
        return [confirmed()]

    result = service(storage=storage, confirmed_evidence_source=source).assess()
    assert result.ready and result.replayed == 3 and calls == 1
    assert service(storage=storage, confirmed_evidence_source=source).assess().ready
    with storage.unit_of_work() as uow:
        assert uow.executions.get("exec-1") is not None


def test_restart_replay_is_duplicate_safe(storage):
    first = service(storage=storage, confirmed_evidence_source=lambda: [confirmed()])
    assert first.assess().ready
    restarted = service(storage=storage, confirmed_evidence_source=lambda: [confirmed()])
    assert restarted.assess().ready and restarted.readiness.replayed == 0
    with storage.unit_of_work() as uow:
        assert len(uow.executions.list_for_order("order-1")) == 1


def test_replay_failure_keeps_readiness_blocked(storage, monkeypatch):
    from data_layer.sqlite import SQLiteExecutionRepository

    monkeypatch.setattr(SQLiteExecutionRepository, "add", lambda self, record: (_ for _ in ()).throw(RuntimeError("write failed")))
    result = service(storage=storage, confirmed_evidence_source=lambda: [confirmed()]).assess()
    assert not result.ready
    assert result.decision.disposition is RecoveryDisposition.PROJECTION_REPLAY_REQUIRED
    with storage.unit_of_work() as uow:
        assert uow.orders.get("order-1") is None


def test_canonical_execution_manager_uses_backend_neutral_safety_contract():
    source = (ROOT / "core" / "execution_manager.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    modules = {node.module for node in ast.walk(tree) if isinstance(node, ast.ImportFrom) and node.module}
    names = {alias.name for node in ast.walk(tree) if isinstance(node, ast.Import) for alias in node.names}
    assert "data_layer.runtime_safety" in modules
    assert "data_layer.sqlite" not in modules and "sqlite3" not in names
    assert "self._assess_financial_readiness()" in source
