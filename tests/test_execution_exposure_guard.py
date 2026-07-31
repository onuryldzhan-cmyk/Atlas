from __future__ import annotations

from typing import Any

import pytest


def _guard():
    from exchange.execution_exposure_guard import (
        ExecutionExposureGuard,
    )

    return ExecutionExposureGuard(
        portfolio_equity=10_000.0,
        max_order_notional=2_000.0,
        max_symbol_exposure=3_000.0,
        max_total_exposure=7_000.0,
        max_open_positions=5,
        minimum_cash_reserve=2_000.0,
    )


def test_healthy_order_is_authorized() -> None:
    guard = _guard()

    guard.update_portfolio(
        cash=6_000.0,
        total_exposure=4_000.0,
        symbol_exposures={
            "BTCUSDT": 1_000.0,
        },
        open_positions=2,
    )

    decision = guard.authorize_order(
        symbol="BTCUSDT",
        order_notional=500.0,
        opens_new_position=False,
    )

    assert decision == {
        "allowed": True,
        "status": "AUTHORIZED",
        "reason": "EXPOSURE_LIMITS_HEALTHY",
    }


def test_max_order_notional_is_enforced() -> None:
    guard = _guard()

    guard.update_portfolio(
        cash=10_000.0,
        total_exposure=0.0,
        symbol_exposures={},
        open_positions=0,
    )

    decision = guard.authorize_order(
        symbol="BTCUSDT",
        order_notional=2_500.0,
        opens_new_position=True,
    )

    assert decision["allowed"] is False
    assert decision["reason"] == "MAX_ORDER_NOTIONAL_EXCEEDED"


def test_symbol_exposure_limit_is_enforced() -> None:
    guard = _guard()

    guard.update_portfolio(
        cash=7_000.0,
        total_exposure=3_000.0,
        symbol_exposures={
            "BTCUSDT": 2_700.0,
        },
        open_positions=2,
    )

    decision = guard.authorize_order(
        symbol="BTCUSDT",
        order_notional=500.0,
        opens_new_position=False,
    )

    assert decision["allowed"] is False
    assert decision["reason"] == "MAX_SYMBOL_EXPOSURE_EXCEEDED"


def test_total_exposure_limit_is_enforced() -> None:
    guard = _guard()

    guard.update_portfolio(
        cash=3_500.0,
        total_exposure=6_500.0,
        symbol_exposures={},
        open_positions=4,
    )

    decision = guard.authorize_order(
        symbol="ETHUSDT",
        order_notional=1_000.0,
        opens_new_position=True,
    )

    assert decision["allowed"] is False
    assert decision["reason"] == "MAX_TOTAL_EXPOSURE_EXCEEDED"


def test_maximum_open_positions_is_enforced() -> None:
    guard = _guard()

    guard.update_portfolio(
        cash=5_000.0,
        total_exposure=5_000.0,
        symbol_exposures={},
        open_positions=5,
    )

    decision = guard.authorize_order(
        symbol="SOLUSDT",
        order_notional=500.0,
        opens_new_position=True,
    )

    assert decision["allowed"] is False
    assert decision["reason"] == "MAX_OPEN_POSITIONS_REACHED"


def test_existing_position_does_not_increment_position_count() -> None:
    guard = _guard()

    guard.update_portfolio(
        cash=5_000.0,
        total_exposure=5_000.0,
        symbol_exposures={
            "BTCUSDT": 1_000.0,
        },
        open_positions=5,
    )

    decision = guard.authorize_order(
        symbol="BTCUSDT",
        order_notional=500.0,
        opens_new_position=False,
    )

    assert decision["allowed"] is True


def test_minimum_cash_reserve_is_enforced() -> None:
    guard = _guard()

    guard.update_portfolio(
        cash=2_300.0,
        total_exposure=6_000.0,
        symbol_exposures={},
        open_positions=4,
    )

    decision = guard.authorize_order(
        symbol="XRPUSDT",
        order_notional=500.0,
        opens_new_position=True,
    )

    assert decision["allowed"] is False
    assert decision["reason"] == "MINIMUM_CASH_RESERVE_VIOLATION"


@pytest.mark.parametrize(
    "order_notional",
    [
        0,
        -1,
        float("nan"),
        float("inf"),
        "invalid",
    ],
)
def test_invalid_order_notional_fails_closed(
    order_notional: Any,
) -> None:
    guard = _guard()

    guard.update_portfolio(
        cash=10_000.0,
        total_exposure=0.0,
        symbol_exposures={},
        open_positions=0,
    )

    decision = guard.authorize_order(
        symbol="BTCUSDT",
        order_notional=order_notional,
        opens_new_position=True,
    )

    assert decision["allowed"] is False
    assert decision["reason"] == "INVALID_ORDER_NOTIONAL"


@pytest.mark.parametrize(
    "portfolio_data",
    [
        {
            "cash": -1,
            "total_exposure": 0,
            "symbol_exposures": {},
            "open_positions": 0,
        },
        {
            "cash": 10_000,
            "total_exposure": float("nan"),
            "symbol_exposures": {},
            "open_positions": 0,
        },
        {
            "cash": 10_000,
            "total_exposure": 0,
            "symbol_exposures": {"BTCUSDT": -1},
            "open_positions": 0,
        },
        {
            "cash": 10_000,
            "total_exposure": 0,
            "symbol_exposures": {},
            "open_positions": -1,
        },
    ],
)
def test_invalid_portfolio_snapshot_fails_closed(
    portfolio_data: dict[str, Any],
) -> None:
    guard = _guard()

    result = guard.update_portfolio(
        **portfolio_data,
    )

    assert result["accepted"] is False
    assert result["reason"] == "INVALID_PORTFOLIO_SNAPSHOT"

    decision = guard.authorize_order(
        symbol="BTCUSDT",
        order_notional=100.0,
        opens_new_position=True,
    )

    assert decision["allowed"] is False
    assert decision["reason"] == "PORTFOLIO_STATE_UNAVAILABLE"


def test_missing_portfolio_snapshot_fails_closed() -> None:
    guard = _guard()

    decision = guard.authorize_order(
        symbol="BTCUSDT",
        order_notional=100.0,
        opens_new_position=True,
    )

    assert decision["allowed"] is False
    assert decision["reason"] == "PORTFOLIO_STATE_UNAVAILABLE"


def test_status_does_not_expose_symbol_positions() -> None:
    guard = _guard()

    guard.update_portfolio(
        cash=8_000.0,
        total_exposure=2_000.0,
        symbol_exposures={
            "BTCUSDT": 2_000.0,
        },
        open_positions=1,
    )

    status = guard.status()

    assert status["portfolio_available"] is True
    assert status["tracked_symbols"] == 1
    assert "symbol_exposures" not in status
    assert "BTCUSDT" not in str(status)
