from __future__ import annotations

from typing import Any

from exchange.execution_risk_guard import ExecutionRiskGuard
from exchange.execution_safety_gate import ExecutionSafetyGate
from exchange.exchange_manager import ExchangeManager


class SpyExchange:
    def __init__(self) -> None:
        self.orders: list[dict[str, Any]] = []

    def place_order(
        self,
        symbol: str,
        side: str,
        quantity: float,
    ) -> dict[str, Any]:
        order = {
            "symbol": symbol,
            "side": side,
            "quantity": quantity,
        }

        self.orders.append(order)

        return {
            "status": "FILLED",
            "order": order,
        }


def _build_manager(
    *,
    guard: ExecutionRiskGuard,
) -> tuple[ExchangeManager, SpyExchange]:
    exchange = SpyExchange()

    manager = ExchangeManager(
        exchange_name="test",
        exchange=exchange,
        safety_gate=ExecutionSafetyGate(
            mode="LIVE",
            live_enabled=True,
        ),
        risk_guard=guard,
    )

    return manager, exchange


def test_healthy_risk_guard_allows_single_exchange_call() -> None:
    guard = ExecutionRiskGuard(
        starting_equity=10_000.0,
        max_daily_loss_percent=5.0,
        max_drawdown_percent=10.0,
    )

    manager, exchange = _build_manager(
        guard=guard,
    )

    result = manager.place_order(
        "BTCUSDT",
        "BUY",
        0.01,
        idempotency_key="test_exchange_manager_risk_guard_integration-001",
    )

    assert result["status"] == "FILLED"

    assert exchange.orders == [
        {
            "symbol": "BTCUSDT",
            "side": "BUY",
            "quantity": 0.01,
        }
    ]


def test_daily_loss_halt_blocks_exchange_call() -> None:
    guard = ExecutionRiskGuard(
        starting_equity=10_000.0,
        max_daily_loss_percent=5.0,
        max_drawdown_percent=20.0,
    )

    guard.record_equity(
        equity=9_400.0,
    )

    manager, exchange = _build_manager(
        guard=guard,
    )

    result = manager.place_order(
        "ETHUSDT",
        "BUY",
        0.25,
        idempotency_key="test_exchange_manager_risk_guard_integration-002",
    )

    assert result == {
        "status": "REJECTED",
        "allowed": False,
        "reason": "MAX_DAILY_LOSS_EXCEEDED",
        "symbol": "ETHUSDT",
        "side": "BUY",
        "quantity": 0.25,
    }

    assert exchange.orders == []


def test_drawdown_halt_blocks_exchange_call() -> None:
    guard = ExecutionRiskGuard(
        starting_equity=10_000.0,
        max_daily_loss_percent=50.0,
        max_drawdown_percent=10.0,
    )

    guard.record_equity(
        equity=12_000.0,
    )

    guard.record_equity(
        equity=10_700.0,
    )

    manager, exchange = _build_manager(
        guard=guard,
    )

    result = manager.place_order(
        "SOLUSDT",
        "SELL",
        1.0,
        idempotency_key="test_exchange_manager_risk_guard_integration-003",
    )

    assert result["status"] == "REJECTED"
    assert result["reason"] == "MAX_DRAWDOWN_EXCEEDED"
    assert exchange.orders == []


def test_manual_halt_blocks_exchange_call() -> None:
    guard = ExecutionRiskGuard(
        starting_equity=10_000.0,
        max_daily_loss_percent=5.0,
        max_drawdown_percent=10.0,
    )

    guard.halt(
        reason="OPERATOR_EMERGENCY_STOP",
    )

    manager, exchange = _build_manager(
        guard=guard,
    )

    result = manager.place_order(
        "BNBUSDT",
        "BUY",
        0.5,
        idempotency_key="test_exchange_manager_risk_guard_integration-004",
    )

    assert result["status"] == "REJECTED"
    assert result["reason"] == "OPERATOR_EMERGENCY_STOP"
    assert exchange.orders == []


def test_invalid_equity_halt_blocks_exchange_call() -> None:
    guard = ExecutionRiskGuard(
        starting_equity=10_000.0,
        max_daily_loss_percent=5.0,
        max_drawdown_percent=10.0,
    )

    guard.record_equity(
        equity=float("nan"),
    )

    manager, exchange = _build_manager(
        guard=guard,
    )

    result = manager.place_order(
        "XRPUSDT",
        "BUY",
        100.0,
        idempotency_key="test_exchange_manager_risk_guard_integration-005",
    )

    assert result["status"] == "REJECTED"
    assert result["reason"] == "INVALID_EQUITY"
    assert exchange.orders == []


def test_manager_without_risk_guard_fails_closed() -> None:
    exchange = SpyExchange()

    manager = ExchangeManager(
        exchange_name="test",
        exchange=exchange,
        safety_gate=ExecutionSafetyGate(
            mode="LIVE",
            live_enabled=True,
        ),
    )

    result = manager.place_order(
        "BTCUSDT",
        "BUY",
        0.01,
        idempotency_key="test_exchange_manager_risk_guard_integration-006",
    )

    assert result["status"] == "REJECTED"
    assert result["reason"] == "RISK_GUARD_NOT_CONFIGURED"
    assert exchange.orders == []


def test_risk_guard_is_checked_before_exchange_adapter() -> None:
    guard = ExecutionRiskGuard(
        starting_equity=10_000.0,
        max_daily_loss_percent=5.0,
        max_drawdown_percent=10.0,
    )

    guard.halt(
        reason="TEST_RISK_HALT",
    )

    manager, exchange = _build_manager(
        guard=guard,
    )

    manager.place_order(
        "BTCUSDT",
        "SELL",
        0.02,
        idempotency_key="test_exchange_manager_risk_guard_integration-007",
    )

    assert exchange.orders == []
