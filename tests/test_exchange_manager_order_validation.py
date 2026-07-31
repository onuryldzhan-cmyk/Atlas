from __future__ import annotations

from typing import Any

import pytest

from exchange.execution_exposure_guard import (
    ExecutionExposureGuard,
)
from exchange.execution_risk_guard import ExecutionRiskGuard
from exchange.execution_safety_gate import ExecutionSafetyGate
from exchange.exchange_manager import ExchangeManager



def _healthy_exposure_guard() -> ExecutionExposureGuard:
    guard = ExecutionExposureGuard(
        portfolio_equity=10_000.0,
        max_order_notional=2_000.0,
        max_symbol_exposure=3_000.0,
        max_total_exposure=7_000.0,
        max_open_positions=5,
        minimum_cash_reserve=2_000.0,
    )

    result = guard.update_portfolio(
        cash=10_000.0,
        total_exposure=0.0,
        symbol_exposures={},
        open_positions=0,
    )

    if result.get("accepted") is not True:
        raise RuntimeError(
            "Healthy exposure fixture was rejected"
        )

    return guard


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


def _build_manager() -> tuple[ExchangeManager, SpyExchange]:
    exchange = SpyExchange()

    manager = ExchangeManager(
        exchange_name="test",
        exchange=exchange,
        safety_gate=ExecutionSafetyGate(
            mode="LIVE",
            live_enabled=True,
        ),
        risk_guard=ExecutionRiskGuard(
            starting_equity=10_000.0,
            max_daily_loss_percent=5.0,
            max_drawdown_percent=10.0,
        ),

        exposure_guard=_healthy_exposure_guard(),)

    return manager, exchange


def test_empty_symbol_is_rejected_before_exchange_call() -> None:
    manager, exchange = _build_manager()

    result = manager.place_order(
        "   ",
        "BUY",
        1.0,
        idempotency_key="test_exchange_manager_order_validation-001",

        order_notional=500.0,
        opens_new_position=False,)

    assert result["status"] == "REJECTED"
    assert result["allowed"] is False
    assert result["reason"] == "INVALID_SYMBOL"
    assert exchange.orders == []


def test_invalid_symbol_characters_are_rejected() -> None:
    manager, exchange = _build_manager()

    result = manager.place_order(
        "BTC/USDT",
        "BUY",
        1.0,
        idempotency_key="test_exchange_manager_order_validation-002",

        order_notional=500.0,
        opens_new_position=False,)

    assert result["status"] == "REJECTED"
    assert result["reason"] == "INVALID_SYMBOL"
    assert exchange.orders == []


def test_invalid_side_is_rejected_before_exchange_call() -> None:
    manager, exchange = _build_manager()

    result = manager.place_order(
        "BTCUSDT",
        "HOLD",
        1.0,
        idempotency_key="test_exchange_manager_order_validation-003",

        order_notional=500.0,
        opens_new_position=False,)

    assert result["status"] == "REJECTED"
    assert result["allowed"] is False
    assert result["reason"] == "INVALID_SIDE"
    assert exchange.orders == []


@pytest.mark.parametrize(
    "quantity",
    [
        0,
        -1,
        float("nan"),
        float("inf"),
        "not-a-number",
    ],
)
def test_invalid_quantity_is_rejected_without_adapter_call(
    quantity: Any,
) -> None:
    manager, exchange = _build_manager()

    result = manager.place_order(
        "BTCUSDT",
        "BUY",
        quantity,
        idempotency_key="test_exchange_manager_order_validation-004",

        order_notional=500.0,
        opens_new_position=False,)

    assert result["status"] == "REJECTED"
    assert result["allowed"] is False
    assert result["reason"] == "INVALID_QUANTITY"
    assert exchange.orders == []


def test_valid_order_is_normalized_and_delegated_once() -> None:
    manager, exchange = _build_manager()

    result = manager.place_order(
        " btcusdt ",
        " buy ",
        0.25,
        idempotency_key="test_exchange_manager_order_validation-005",

        order_notional=500.0,
        opens_new_position=False,)

    assert result["status"] == "FILLED"

    assert exchange.orders == [
        {
            "symbol": "BTCUSDT",
            "side": "BUY",
            "quantity": 0.25,
        }
    ]
