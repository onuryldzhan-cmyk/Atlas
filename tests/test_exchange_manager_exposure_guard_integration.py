from __future__ import annotations

from typing import Any

from exchange.execution_exposure_guard import (
    ExecutionExposureGuard,
)
from exchange.execution_risk_guard import (
    ExecutionRiskGuard,
)
from exchange.execution_safety_gate import (
    ExecutionSafetyGate,
)
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


def _risk_guard() -> ExecutionRiskGuard:
    return ExecutionRiskGuard(
        starting_equity=10_000.0,
        max_daily_loss_percent=5.0,
        max_drawdown_percent=10.0,
    )


def _exposure_guard() -> ExecutionExposureGuard:
    guard = ExecutionExposureGuard(
        portfolio_equity=10_000.0,
        max_order_notional=2_000.0,
        max_symbol_exposure=3_000.0,
        max_total_exposure=7_000.0,
        max_open_positions=5,
        minimum_cash_reserve=2_000.0,
    )

    guard.update_portfolio(
        cash=6_000.0,
        total_exposure=4_000.0,
        symbol_exposures={
            "BTCUSDT": 1_000.0,
        },
        open_positions=2,
    )

    return guard


def _build_manager(
    *,
    exposure_guard: ExecutionExposureGuard | None,
) -> tuple[ExchangeManager, SpyExchange]:
    exchange = SpyExchange()

    manager = ExchangeManager(
        exchange_name="test",
        exchange=exchange,
        safety_gate=ExecutionSafetyGate(
            mode="LIVE",
            live_enabled=True,
        ),
        risk_guard=_risk_guard(),
        exposure_guard=exposure_guard,
    )

    return manager, exchange


def test_healthy_exposure_guard_allows_order() -> None:
    manager, exchange = _build_manager(
        exposure_guard=_exposure_guard(),
    )

    result = manager.place_order(
        "BTCUSDT",
        "BUY",
        0.01,
        order_notional=500.0,
        opens_new_position=False,
        idempotency_key="exposure-healthy-001",
    )

    assert result["status"] == "FILLED"
    assert len(exchange.orders) == 1


def test_missing_exposure_guard_fails_closed() -> None:
    manager, exchange = _build_manager(
        exposure_guard=None,
    )

    result = manager.place_order(
        "BTCUSDT",
        "BUY",
        0.01,
        order_notional=500.0,
        opens_new_position=False,
        idempotency_key="exposure-missing-001",
    )

    assert result["status"] == "REJECTED"
    assert result["reason"] == "EXPOSURE_GUARD_NOT_CONFIGURED"
    assert exchange.orders == []


def test_order_notional_limit_blocks_exchange_call() -> None:
    manager, exchange = _build_manager(
        exposure_guard=_exposure_guard(),
    )

    result = manager.place_order(
        "BTCUSDT",
        "BUY",
        0.01,
        order_notional=2_500.0,
        opens_new_position=False,
        idempotency_key="exposure-order-limit-001",
    )

    assert result["status"] == "REJECTED"
    assert result["reason"] == "MAX_ORDER_NOTIONAL_EXCEEDED"
    assert exchange.orders == []


def test_symbol_exposure_limit_blocks_exchange_call() -> None:
    guard = _exposure_guard()

    guard.update_portfolio(
        cash=7_000.0,
        total_exposure=3_000.0,
        symbol_exposures={
            "BTCUSDT": 2_700.0,
        },
        open_positions=2,
    )

    manager, exchange = _build_manager(
        exposure_guard=guard,
    )

    result = manager.place_order(
        "BTCUSDT",
        "BUY",
        0.01,
        order_notional=500.0,
        opens_new_position=False,
        idempotency_key="exposure-symbol-limit-001",
    )

    assert result["status"] == "REJECTED"
    assert result["reason"] == "MAX_SYMBOL_EXPOSURE_EXCEEDED"
    assert exchange.orders == []


def test_total_exposure_limit_blocks_exchange_call() -> None:
    guard = _exposure_guard()

    guard.update_portfolio(
        cash=3_500.0,
        total_exposure=6_500.0,
        symbol_exposures={},
        open_positions=4,
    )

    manager, exchange = _build_manager(
        exposure_guard=guard,
    )

    result = manager.place_order(
        "ETHUSDT",
        "BUY",
        0.50,
        order_notional=1_000.0,
        opens_new_position=True,
        idempotency_key="exposure-total-limit-001",
    )

    assert result["status"] == "REJECTED"
    assert result["reason"] == "MAX_TOTAL_EXPOSURE_EXCEEDED"
    assert exchange.orders == []


def test_open_position_limit_blocks_exchange_call() -> None:
    guard = _exposure_guard()

    guard.update_portfolio(
        cash=5_000.0,
        total_exposure=5_000.0,
        symbol_exposures={},
        open_positions=5,
    )

    manager, exchange = _build_manager(
        exposure_guard=guard,
    )

    result = manager.place_order(
        "SOLUSDT",
        "BUY",
        1.0,
        order_notional=500.0,
        opens_new_position=True,
        idempotency_key="exposure-position-limit-001",
    )

    assert result["status"] == "REJECTED"
    assert result["reason"] == "MAX_OPEN_POSITIONS_REACHED"
    assert exchange.orders == []


def test_minimum_cash_reserve_blocks_exchange_call() -> None:
    guard = _exposure_guard()

    guard.update_portfolio(
        cash=2_300.0,
        total_exposure=6_000.0,
        symbol_exposures={},
        open_positions=4,
    )

    manager, exchange = _build_manager(
        exposure_guard=guard,
    )

    result = manager.place_order(
        "XRPUSDT",
        "BUY",
        100.0,
        order_notional=500.0,
        opens_new_position=True,
        idempotency_key="exposure-cash-limit-001",
    )

    assert result["status"] == "REJECTED"
    assert result["reason"] == "MINIMUM_CASH_RESERVE_VIOLATION"
    assert exchange.orders == []


def test_missing_order_notional_fails_closed() -> None:
    manager, exchange = _build_manager(
        exposure_guard=_exposure_guard(),
    )

    result = manager.place_order(
        "BTCUSDT",
        "BUY",
        0.01,
        opens_new_position=False,
        idempotency_key="exposure-no-notional-001",
    )

    assert result["status"] == "REJECTED"
    assert result["reason"] == "INVALID_ORDER_NOTIONAL"
    assert exchange.orders == []


def test_missing_position_intent_fails_closed() -> None:
    manager, exchange = _build_manager(
        exposure_guard=_exposure_guard(),
    )

    result = manager.place_order(
        "BTCUSDT",
        "BUY",
        0.01,
        order_notional=500.0,
        idempotency_key="exposure-no-intent-001",
    )

    assert result["status"] == "REJECTED"
    assert result["reason"] == "INVALID_POSITION_INTENT"
    assert exchange.orders == []
