from __future__ import annotations

import importlib
import json
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest

import core.execution_state as execution_state_module
from core.execution_idempotency_store import ExecutionIdempotencyStore
from core.execution_manager import ExecutionManager
from core.position_controller import PositionController
from core.risk_engine import RiskEngine, RiskPolicy, RiskState
from core.capital_reservation import CapitalReservationLedger, JsonReservationStore
from core.risk_state_store import JsonRiskStateStore, RestoredRiskState


def _decision(request_id: str = "durable-request-001") -> dict[str, Any]:
    return {
        "request_id": request_id,
        "action": "BUY",
        "symbol": "BTCUSDT",
        "price": 65000.0,
        "amount": 100.0,
        "confidence": 90.0,
        "strategy": "DURABLE_TEST",
        "risk": "LOW",
        "mode": "PAPER",
    }


class CountingPaperTrader:
    def __init__(self) -> None:
        self.open_count = 0

    def open_trade(
        self,
        symbol: str,
        price: float,
        amount: float,
    ) -> dict[str, Any]:
        self.open_count += 1
        return {
            "success": True,
            "status": "FILLED",
            "trade_id": f"paper-{self.open_count}",
            "symbol": symbol,
            "price": price,
            "amount": amount,
        }


class RecordingJournal:
    def __init__(
        self,
        *,
        prepare_ok: bool = True,
        commit_ok: bool = True,
        unresolved: bool = False,
    ) -> None:
        self.prepare_ok = prepare_ok
        self.commit_ok = commit_ok
        self.prepare_count = 0
        self.commit_count = 0
        self.unknown_count = 0
        self.unresolved = unresolved
        self.calls: list[tuple[str, str]] = []

    def prepare(
        self,
        request_id: str,
        request_payload: dict[str, Any],
    ) -> bool:
        self.prepare_count += 1
        self.calls.append(("PREPARE", request_id))
        return self.prepare_ok

    def mark_committed(
        self,
        request_id: str,
        result: dict[str, Any],
    ) -> bool:
        self.commit_count += 1
        self.calls.append(("COMMITTED", request_id))
        return self.commit_ok

    def mark_unknown(
        self,
        request_id: str,
        *,
        reason: str,
        result: dict[str, Any] | None = None,
    ) -> bool:
        self.unknown_count += 1
        self.unresolved = True
        self.calls.append(("COMMIT_STATUS_UNKNOWN", request_id))
        return True

    def has_unresolved(self) -> bool:
        return self.unresolved

    def status(self) -> dict[str, Any]:
        return {
            "unresolved_entries": int(self.unresolved),
        }


class FailingRecordStore(ExecutionIdempotencyStore):
    def __init__(self, path: Path) -> None:
        super().__init__(
            file_path=path,
            auto_load=False,
        )

    def record(
        self,
        request_id: str,
        result: dict[str, Any],
        *,
        save: bool = True,
    ) -> bool:
        return False


class SaveFailsStore(ExecutionIdempotencyStore):
    def save(self) -> bool:
        return False


class FailingOpenState:
    def add(self, _: dict[str, Any]) -> None:
        raise OSError("simulated open persistence failure")


class FailingCloseState:
    def add(self, _: dict[str, Any]) -> None:
        return None

    def close(
        self,
        _: str,
        __: dict[str, Any],
    ) -> None:
        raise OSError("simulated close persistence failure")


def _manager(
    tmp_path: Path,
    *,
    store: ExecutionIdempotencyStore | None = None,
    paper_trader: CountingPaperTrader | None = None,
    journal: RecordingJournal | None = None,
) -> ExecutionManager:
    reservation_store = JsonReservationStore(tmp_path / "reservations.json")
    reservation_store.initialize_empty()
    risk_store = JsonRiskStateStore(tmp_path / "risk-state.json")
    risk_store.save(RestoredRiskState(datetime.now(UTC).date(), Decimal("0"),
                                     Decimal("1000"), Decimal("1000"), "phase3-risk-v1"))
    manager = ExecutionManager(
        paper_trader=paper_trader,
        idempotency_store=(
            store
            if store is not None
            else ExecutionIdempotencyStore(
                file_path=tmp_path / "idempotency.json",
            )
        ),
        audit_enabled=False,
        risk_engine=RiskEngine(RiskPolicy(total_capital=Decimal("1000"))),
        reservation_ledger=CapitalReservationLedger(reservation_store, Decimal("800")),
        risk_state_store=risk_store,
    )
    manager.transaction_journal = journal
    manager.start()
    return manager


def _risk_state() -> RiskState:
    return RiskState((), Decimal("0"), Decimal("0"), Decimal("1000"),
                     Decimal("1000"), True, datetime.now(UTC).date().isoformat(),
                     "phase3-risk-v1")


def test_transaction_journal_contract_exists() -> None:
    module = None

    try:
        module = importlib.import_module(
            "core.execution_transaction_journal"
        )
    except ModuleNotFoundError:
        pass

    assert module is not None
    assert hasattr(module, "ExecutionTransactionJournal")
    assert hasattr(module, "CommitOutcome")

    outcomes = {
        str(value.value)
        for value in module.CommitOutcome
    }

    assert outcomes == {
        "COMMITTED",
        "NOT_COMMITTED",
        "COMMIT_STATUS_UNKNOWN",
    }


def test_prepare_record_is_durable_before_financial_side_effect(
    tmp_path: Path,
) -> None:
    trader = CountingPaperTrader()
    journal = RecordingJournal()

    manager = _manager(
        tmp_path,
        paper_trader=trader,
        journal=journal,
    )

    result = manager.execute(_decision(), _risk_state())

    assert result.get("commit_outcome") == "COMMITTED"
    assert journal.calls == [
        ("PREPARE", "durable-request-001"),
        ("COMMITTED", "durable-request-001"),
    ]
    assert trader.open_count == 1


def test_prepare_failure_blocks_side_effect_as_not_committed(
    tmp_path: Path,
) -> None:
    trader = CountingPaperTrader()
    journal = RecordingJournal(
        prepare_ok=False
    )

    manager = _manager(
        tmp_path,
        paper_trader=trader,
        journal=journal,
    )

    result = manager.execute(_decision(), _risk_state())

    assert result["success"] is False
    assert result["status"] == "NOT_COMMITTED"
    assert result["commit_outcome"] == "NOT_COMMITTED"
    assert result["error_code"] == "TRANSACTION_PREPARE_FAILED"
    assert trader.open_count == 0
    assert journal.commit_count == 0


def test_terminal_persistence_failure_returns_unknown_and_halts(
    tmp_path: Path,
) -> None:
    trader = CountingPaperTrader()
    journal = RecordingJournal()
    store = FailingRecordStore(
        tmp_path / "idempotency.json"
    )

    manager = _manager(
        tmp_path,
        store=store,
        paper_trader=trader,
        journal=journal,
    )

    result = manager.execute(_decision(), _risk_state())

    assert result["success"] is False
    assert result["status"] == "COMMIT_STATUS_UNKNOWN"
    assert (
        result["commit_outcome"]
        == "COMMIT_STATUS_UNKNOWN"
    )
    assert result["error_code"] == "DURABLE_COMMIT_FAILED"
    assert trader.open_count == 1
    assert journal.unknown_count == 1

    operational = manager.status()["operational_state"]

    assert operational["execution_halted"] is True
    assert operational["recovery_required"] is True
    assert "durable-request-001" not in (
        manager.completed_request_results
    )


def test_recovery_required_blocks_new_financial_requests(
    tmp_path: Path,
) -> None:
    trader = CountingPaperTrader()
    journal = RecordingJournal(
        unresolved=True
    )

    manager = _manager(
        tmp_path,
        paper_trader=trader,
        journal=journal,
    )

    manager.execution_halted = True
    manager.recovery_required = True
    manager.halt_reason = "UNRESOLVED_TRANSACTION"

    result = manager.execute(
        _decision("durable-request-002")
    )

    assert result["success"] is False
    assert result["status"] == "RECOVERY_REQUIRED"
    assert (
        result["error_code"]
        == "UNRESOLVED_TRANSACTION"
    )
    assert trader.open_count == 0


def test_idempotency_record_rolls_back_memory_when_save_fails(
    tmp_path: Path,
) -> None:
    store = SaveFailsStore(
        file_path=tmp_path / "idempotency.json",
        auto_load=False,
    )

    result = store.record(
        "durable-store-001",
        {
            "status": "PAPER_EXECUTED",
            "success": True,
        },
        save=True,
    )

    assert result is False
    assert store.contains("durable-store-001") is False
    assert store.completed_requests == {}


def test_position_open_rolls_back_memory_when_persistence_fails() -> None:
    controller = PositionController(
        execution_state=FailingOpenState()
    )

    result = controller.open_position(
        symbol="BTCUSDT",
        price=65000.0,
        amount=100.0,
        confidence=90.0,
        strategy="DURABLE_TEST",
        risk="LOW",
    )

    assert result["success"] is False
    assert controller.exists("BTCUSDT") is False
    assert controller.open_count == 0
    assert controller.get_all() == []
    assert result["status"] == "NOT_COMMITTED"


def test_position_close_rolls_back_memory_when_persistence_fails() -> None:
    controller = PositionController()

    opened = controller.open_position(
        symbol="BTCUSDT",
        price=65000.0,
        amount=100.0,
        confidence=90.0,
        strategy="DURABLE_TEST",
        risk="LOW",
    )

    assert opened["success"] is True

    controller.execution_state = FailingCloseState()

    try:
        result = controller.close_position(
            symbol="BTCUSDT",
            price=66000.0,
        )
    except OSError:
        result = {
            "success": False,
            "status": "PERSISTENCE_EXCEPTION",
        }

    assert result["success"] is False
    assert controller.exists("BTCUSDT") is True
    assert controller.close_count == 0
    assert controller.get_closed() == []
    assert result["status"] == "COMMIT_STATUS_UNKNOWN"


def test_execution_state_failed_save_preserves_last_valid_snapshot(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from core.execution_state import ExecutionState

    state = ExecutionState(
        storage=tmp_path
    )

    state.active = {
        "BTCUSDT": {
            "symbol": "BTCUSDT",
            "status": "OPEN",
        }
    }
    state.save()

    original = state.file.read_bytes()

    state.active["ETHUSDT"] = {
        "symbol": "ETHUSDT",
        "status": "OPEN",
    }

    original_dump = execution_state_module.json.dump

    def partial_then_fail(
        payload: Any,
        stream: Any,
        *args: Any,
        **kwargs: Any,
    ) -> None:
        stream.write('{"partial":')
        stream.flush()
        raise OSError("simulated crash during state save")

    monkeypatch.setattr(
        execution_state_module.json,
        "dump",
        partial_then_fail,
    )

    with pytest.raises(OSError):
        state.save()

    monkeypatch.setattr(
        execution_state_module.json,
        "dump",
        original_dump,
    )

    assert state.file.read_bytes() == original

    reloaded = ExecutionState(
        storage=tmp_path
    )

    assert set(reloaded.active) == {
        "BTCUSDT",
    }


def test_transaction_status_exposes_counts_not_request_ids(
    tmp_path: Path,
) -> None:
    module = None

    try:
        module = importlib.import_module(
            "core.execution_transaction_journal"
        )
    except ModuleNotFoundError:
        pass

    assert module is not None

    journal = module.ExecutionTransactionJournal(
        file_path=tmp_path / "journal.json"
    )

    assert journal.prepare(
        "private-request-id-001",
        _decision("private-request-id-001"),
    )

    status = journal.status()
    serialized = json.dumps(
        status,
        sort_keys=True,
        default=str,
    )

    assert status["unresolved_entries"] == 1
    assert "private-request-id-001" not in serialized
    assert "BTCUSDT" not in serialized
