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

        exposure_guard=_healthy_exposure_guard(),)


@pytest.mark.parametrize(
    ("exception", "expected_status", "expected_reason"),
    [
        (
            TimeoutError("exchange timeout"),
            "PENDING_RECONCILIATION",
            "EXCHANGE_OUTCOME_UNKNOWN",
        ),
        (
            ConnectionError("exchange unavailable"),
            "PENDING_RECONCILIATION",
            "EXCHANGE_OUTCOME_UNKNOWN",
        ),
        (
            RuntimeError("unexpected adapter failure"),
            "ERROR",
            "EXCHANGE_ADAPTER_ERROR",
        ),
    ],
)
def test_adapter_exception_returns_fail_closed_result(
    exception: Exception,
    expected_status: str,
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
        idempotency_key="test_exchange_manager_adapter_fail_closed-001",

        order_notional=500.0,
        opens_new_position=False,)

    assert result["status"] == expected_status
    assert result["allowed"] is False
    assert result["reason"] == expected_reason
    assert result["symbol"] == "BTCUSDT"
    assert result["side"] == "BUY"
    assert result["quantity"] == 0.01
    if expected_status == "ERROR":
        assert result["error_type"] == type(exception).__name__
    else:
        assert "error_type" not in result
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
        idempotency_key="test_exchange_manager_adapter_fail_closed-002",

        order_notional=500.0,
        opens_new_position=False,)

    assert result == {
        "status": "PENDING_RECONCILIATION",
        "allowed": False,
        "reason": "EXCHANGE_OUTCOME_UNKNOWN",
        "symbol": "ETHUSDT",
        "side": "SELL",
        "quantity": 0.5,
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
        idempotency_key="test_exchange_manager_adapter_fail_closed-003",

        order_notional=500.0,
        opens_new_position=False,)

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
        idempotency_key="test_exchange_manager_adapter_fail_closed-004",

        order_notional=500.0,
        opens_new_position=False,)

    assert result == {
        "status": "FILLED",
        "order_id": "test-order-1",
    }

    assert exchange.call_count == 1
