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
        self.response: dict[str, Any] = {
            "status": "FILLED",
            "order_id": "exchange-order-1",
        }

    def place_order(
        self,
        symbol: str,
        side: str,
        quantity: float,
    ) -> dict[str, Any]:
        self.orders.append(
            {
                "symbol": symbol,
                "side": side,
                "quantity": quantity,
            }
        )

        return dict(
            self.response
        )


class FailingOnceExchange:
    def __init__(self) -> None:
        self.call_count = 0

    def place_order(
        self,
        symbol: str,
        side: str,
        quantity: float,
    ) -> dict[str, Any]:
        self.call_count += 1

        if self.call_count == 1:
            raise ConnectionError(
                "temporary exchange outage"
            )

        return {
            "status": "FILLED",
            "order_id": "retry-order-1",
        }


def _healthy_guard() -> ExecutionRiskGuard:
    return ExecutionRiskGuard(
        starting_equity=10_000.0,
        max_daily_loss_percent=5.0,
        max_drawdown_percent=10.0,
    )


def _build_manager(
    exchange: Any,
) -> ExchangeManager:
    return ExchangeManager(
        exchange_name="test",
        exchange=exchange,
        safety_gate=ExecutionSafetyGate(
            mode="LIVE",
            live_enabled=True,
        ),
        risk_guard=_healthy_guard(),

        exposure_guard=_healthy_exposure_guard(),)


def test_missing_idempotency_key_rejects_live_order() -> None:
    exchange = SpyExchange()
    manager = _build_manager(exchange)

    result = manager.place_order(
        "BTCUSDT",
        "BUY",
        0.01,

        order_notional=500.0,
        opens_new_position=False,)

    assert result["status"] == "REJECTED"
    assert result["allowed"] is False
    assert result["reason"] == "IDEMPOTENCY_KEY_REQUIRED"
    assert exchange.orders == []


@pytest.mark.parametrize(
    "key",
    [
        "",
        "   ",
        None,
    ],
)
def test_blank_idempotency_key_rejects_order(
    key: object,
) -> None:
    exchange = SpyExchange()
    manager = _build_manager(exchange)

    result = manager.place_order(
        "BTCUSDT",
        "BUY",
        0.01,
        idempotency_key=key,

        order_notional=500.0,
        opens_new_position=False,)

    assert result["status"] == "REJECTED"
    assert result["reason"] == "IDEMPOTENCY_KEY_REQUIRED"
    assert exchange.orders == []


def test_same_key_and_same_order_calls_exchange_once() -> None:
    exchange = SpyExchange()
    manager = _build_manager(exchange)

    first = manager.place_order(
        "BTCUSDT",
        "BUY",
        0.01,
        idempotency_key="order-request-001",

        order_notional=500.0,
        opens_new_position=False,)

    second = manager.place_order(
        "BTCUSDT",
        "BUY",
        0.01,
        idempotency_key="order-request-001",

        order_notional=500.0,
        opens_new_position=False,)

    assert first == {
        "status": "FILLED",
        "order_id": "exchange-order-1",
    }

    assert second == first

    assert exchange.orders == [
        {
            "symbol": "BTCUSDT",
            "side": "BUY",
            "quantity": 0.01,
        }
    ]


def test_same_key_with_different_order_is_rejected() -> None:
    exchange = SpyExchange()
    manager = _build_manager(exchange)

    first = manager.place_order(
        "BTCUSDT",
        "BUY",
        0.01,
        idempotency_key="order-request-002",

        order_notional=500.0,
        opens_new_position=False,)

    second = manager.place_order(
        "ETHUSDT",
        "BUY",
        0.50,
        idempotency_key="order-request-002",

        order_notional=500.0,
        opens_new_position=False,)

    assert first["status"] == "FILLED"

    assert second["status"] == "REJECTED"
    assert second["allowed"] is False
    assert second["reason"] == "IDEMPOTENCY_KEY_CONFLICT"

    assert len(exchange.orders) == 1


def test_key_is_normalized_before_duplicate_check() -> None:
    exchange = SpyExchange()
    manager = _build_manager(exchange)

    manager.place_order(
        "BTCUSDT",
        "BUY",
        0.01,
        idempotency_key="  Request-ABC  ",

        order_notional=500.0,
        opens_new_position=False,)

    result = manager.place_order(
        "BTCUSDT",
        "BUY",
        0.01,
        idempotency_key="Request-ABC",

        order_notional=500.0,
        opens_new_position=False,)

    assert result["status"] == "FILLED"
    assert len(exchange.orders) == 1


def test_failed_adapter_call_does_not_permanently_consume_key() -> None:
    exchange = FailingOnceExchange()
    manager = _build_manager(exchange)

    first = manager.place_order(
        "BTCUSDT",
        "BUY",
        0.01,
        idempotency_key="retry-request-001",

        order_notional=500.0,
        opens_new_position=False,)

    second = manager.place_order(
        "BTCUSDT",
        "BUY",
        0.01,
        idempotency_key="retry-request-001",

        order_notional=500.0,
        opens_new_position=False,)

    assert first["status"] == "ERROR"
    assert first["reason"] == "EXCHANGE_CONNECTION_ERROR"

    assert second["status"] == "FILLED"
    assert exchange.call_count == 2


def test_exchange_rejection_is_cached_for_same_request() -> None:
    exchange = SpyExchange()
    exchange.response = {
        "status": "REJECTED",
        "reason": "INSUFFICIENT_BALANCE",
    }

    manager = _build_manager(exchange)

    first = manager.place_order(
        "SOLUSDT",
        "BUY",
        1.0,
        idempotency_key="rejected-request-001",

        order_notional=500.0,
        opens_new_position=False,)

    second = manager.place_order(
        "SOLUSDT",
        "BUY",
        1.0,
        idempotency_key="rejected-request-001",

        order_notional=500.0,
        opens_new_position=False,)

    assert first == {
        "status": "REJECTED",
        "reason": "INSUFFICIENT_BALANCE",
    }

    assert second == first
    assert len(exchange.orders) == 1


def test_idempotency_status_does_not_expose_order_payloads() -> None:
    exchange = SpyExchange()
    manager = _build_manager(exchange)

    manager.place_order(
        "BTCUSDT",
        "BUY",
        0.01,
        idempotency_key="status-request-001",

        order_notional=500.0,
        opens_new_position=False,)

    status = manager.status()

    assert status["idempotency"]["enabled"] is True
    assert status["idempotency"]["cached_entries"] == 1
    assert "entries" not in status["idempotency"]
    assert "status-request-001" not in str(status)

def test_same_key_with_different_order_notional_is_rejected_as_idempotency_conflict() -> None:
    exchange = SpyExchange()
    manager = _build_manager(exchange)

    first = manager.place_order(
        "BTCUSDT",
        "BUY",
        0.01,
        idempotency_key="economic-intent-notional-001",
        order_notional=500.0,
        opens_new_position=False,
    )

    second = manager.place_order(
        "BTCUSDT",
        "BUY",
        0.01,
        idempotency_key="economic-intent-notional-001",
        order_notional=750.0,
        opens_new_position=False,
    )

    assert first["status"] == "FILLED"
    assert second["status"] == "REJECTED"
    assert second["reason"] == "IDEMPOTENCY_KEY_CONFLICT"
    assert len(exchange.orders) == 1


def test_same_key_with_different_position_opening_intent_is_rejected_as_idempotency_conflict() -> None:
    exchange = SpyExchange()
    manager = _build_manager(exchange)

    first = manager.place_order(
        "BTCUSDT",
        "BUY",
        0.01,
        idempotency_key="economic-intent-position-001",
        order_notional=500.0,
        opens_new_position=False,
    )

    second = manager.place_order(
        "BTCUSDT",
        "BUY",
        0.01,
        idempotency_key="economic-intent-position-001",
        order_notional=500.0,
        opens_new_position=True,
    )

    assert first["status"] == "FILLED"
    assert second["status"] == "REJECTED"
    assert second["reason"] == "IDEMPOTENCY_KEY_CONFLICT"
    assert len(exchange.orders) == 1
