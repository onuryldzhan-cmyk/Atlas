from __future__ import annotations

from typing import Any

import pytest

from exchange.execution_risk_guard import ExecutionRiskGuard
from exchange.execution_safety_gate import ExecutionSafetyGate
from exchange.exchange_manager import ExchangeManager


class RaisingExchange:
    def __init__(
        self,
        exception: Exception,
    ) -> None:
        self.exception = exception
        self.call_count = 0

    def place_order(
        self,
        symbol: str,
        side: str,
        quantity: float,
    ) -> dict[str, Any]:
        self.call_count += 1
        raise self.exception


class InvalidResponseExchange:
    def __init__(
        self,
        response: Any,
    ) -> None:
        self.response = response
        self.call_count = 0

    def place_order(
        self,
        symbol: str,
        side: str,
        quantity: float,
    ) -> Any:
        self.call_count += 1
        return self.response


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
    )


@pytest.mark.parametrize(
    ("exception", "expected_reason"),
    [
        (
            TimeoutError("exchange timeout"),
            "EXCHANGE_TIMEOUT",
        ),
        (
            ConnectionError("exchange unavailable"),
            "EXCHANGE_CONNECTION_ERROR",
        ),
        (
            RuntimeError("unexpected adapter failure"),
            "EXCHANGE_ADAPTER_ERROR",
        ),
    ],
)
def test_adapter_exception_returns_fail_closed_result(
    exception: Exception,
    expected_reason: str,
) -> None:
    exchange = RaisingExchange(
        exception,
    )

    manager = _build_manager(
        exchange,
    )

    result = manager.place_order(
        "BTCUSDT",
        "BUY",
        0.01,
    )

    assert result["status"] == "ERROR"
    assert result["allowed"] is False
    assert result["reason"] == expected_reason
    assert result["symbol"] == "BTCUSDT"
    assert result["side"] == "BUY"
    assert result["quantity"] == 0.01
    assert result["error_type"] == type(exception).__name__
    assert exchange.call_count == 1


@pytest.mark.parametrize(
    "response",
    [
        None,
        True,
        False,
        [],
        "FILLED",
    ],
)
def test_invalid_adapter_response_fails_closed(
    response: Any,
) -> None:
    exchange = InvalidResponseExchange(
        response,
    )

    manager = _build_manager(
        exchange,
    )

    result = manager.place_order(
        "ETHUSDT",
        "SELL",
        0.5,
    )

    assert result == {
        "status": "ERROR",
        "allowed": False,
        "reason": "INVALID_EXCHANGE_RESPONSE",
        "symbol": "ETHUSDT",
        "side": "SELL",
        "quantity": 0.5,
        "error_type": "InvalidExchangeResponse",
    }

    assert exchange.call_count == 1


def test_exchange_rejection_dictionary_is_preserved() -> None:
    exchange = InvalidResponseExchange(
        {
            "status": "REJECTED",
            "reason": "INSUFFICIENT_BALANCE",
        }
    )

    manager = _build_manager(
        exchange,
    )

    result = manager.place_order(
        "SOLUSDT",
        "BUY",
        1.0,
    )

    assert result == {
        "status": "REJECTED",
        "reason": "INSUFFICIENT_BALANCE",
    }

    assert exchange.call_count == 1


def test_exchange_success_dictionary_is_preserved() -> None:
    exchange = InvalidResponseExchange(
        {
            "status": "FILLED",
            "order_id": "test-order-1",
        }
    )

    manager = _build_manager(
        exchange,
    )

    result = manager.place_order(
        "XRPUSDT",
        "BUY",
        25.0,
    )

    assert result == {
        "status": "FILLED",
        "order_id": "test-order-1",
    }

    assert exchange.call_count == 1
