from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest


def test_guard_defaults_to_safe_operational_state() -> None:
    from exchange.execution_risk_guard import ExecutionRiskGuard

    guard = ExecutionRiskGuard(
        starting_equity=10_000.0,
        max_daily_loss_percent=5.0,
        max_drawdown_percent=10.0,
    )

    status = guard.status()

    assert status["halted"] is False
    assert status["daily_loss_percent"] == 0.0
    assert status["drawdown_percent"] == 0.0
    assert status["peak_equity"] == 10_000.0
    assert status["current_equity"] == 10_000.0


def test_daily_loss_limit_blocks_new_orders() -> None:
    from exchange.execution_risk_guard import ExecutionRiskGuard

    guard = ExecutionRiskGuard(
        starting_equity=10_000.0,
        max_daily_loss_percent=5.0,
        max_drawdown_percent=20.0,
    )

    guard.record_equity(
        equity=9_400.0,
    )

    decision = guard.authorize_order()

    assert decision["allowed"] is False
    assert decision["status"] == "REJECTED"
    assert decision["reason"] == "MAX_DAILY_LOSS_EXCEEDED"
    assert guard.status()["halted"] is True


def test_drawdown_limit_blocks_new_orders() -> None:
    from exchange.execution_risk_guard import ExecutionRiskGuard

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

    decision = guard.authorize_order()

    assert decision["allowed"] is False
    assert decision["status"] == "REJECTED"
    assert decision["reason"] == "MAX_DRAWDOWN_EXCEEDED"
    assert guard.status()["halted"] is True


def test_peak_equity_only_moves_upward() -> None:
    from exchange.execution_risk_guard import ExecutionRiskGuard

    guard = ExecutionRiskGuard(
        starting_equity=10_000.0,
        max_daily_loss_percent=20.0,
        max_drawdown_percent=20.0,
    )

    guard.record_equity(
        equity=12_000.0,
    )

    guard.record_equity(
        equity=11_000.0,
    )

    status = guard.status()

    assert status["peak_equity"] == 12_000.0
    assert status["current_equity"] == 11_000.0


@pytest.mark.parametrize(
    "equity",
    [
        0,
        -1,
        float("nan"),
        float("inf"),
        "invalid",
    ],
)
def test_invalid_equity_fails_closed(
    equity: object,
) -> None:
    from exchange.execution_risk_guard import ExecutionRiskGuard

    guard = ExecutionRiskGuard(
        starting_equity=10_000.0,
        max_daily_loss_percent=5.0,
        max_drawdown_percent=10.0,
    )

    result = guard.record_equity(
        equity=equity,
    )

    assert result["accepted"] is False
    assert result["reason"] == "INVALID_EQUITY"
    assert guard.authorize_order()["allowed"] is False
    assert guard.status()["halted"] is True


def test_manual_halt_blocks_orders() -> None:
    from exchange.execution_risk_guard import ExecutionRiskGuard

    guard = ExecutionRiskGuard(
        starting_equity=10_000.0,
        max_daily_loss_percent=5.0,
        max_drawdown_percent=10.0,
    )

    guard.halt(
        reason="OPERATOR_EMERGENCY_STOP",
    )

    decision = guard.authorize_order()

    assert decision["allowed"] is False
    assert decision["reason"] == "OPERATOR_EMERGENCY_STOP"


def test_halt_is_latched_until_explicit_reset() -> None:
    from exchange.execution_risk_guard import ExecutionRiskGuard

    guard = ExecutionRiskGuard(
        starting_equity=10_000.0,
        max_daily_loss_percent=5.0,
        max_drawdown_percent=10.0,
    )

    guard.record_equity(
        equity=9_000.0,
    )

    guard.record_equity(
        equity=10_000.0,
    )

    assert guard.authorize_order()["allowed"] is False

    guard.reset_halt(
        operator_approved=True,
    )

    assert guard.authorize_order()["allowed"] is True


def test_reset_without_operator_approval_is_rejected() -> None:
    from exchange.execution_risk_guard import ExecutionRiskGuard

    guard = ExecutionRiskGuard(
        starting_equity=10_000.0,
        max_daily_loss_percent=5.0,
        max_drawdown_percent=10.0,
    )

    guard.halt(
        reason="TEST_HALT",
    )

    result = guard.reset_halt(
        operator_approved=False,
    )

    assert result["reset"] is False
    assert result["reason"] == "OPERATOR_APPROVAL_REQUIRED"
    assert guard.authorize_order()["allowed"] is False


def test_daily_baseline_can_roll_forward_on_new_day() -> None:
    from exchange.execution_risk_guard import ExecutionRiskGuard

    day_one = datetime(
        2026,
        7,
        30,
        10,
        0,
        tzinfo=UTC,
    )

    guard = ExecutionRiskGuard(
        starting_equity=10_000.0,
        max_daily_loss_percent=5.0,
        max_drawdown_percent=20.0,
        now_provider=lambda: day_one,
    )

    guard.record_equity(
        equity=9_700.0,
        observed_at=day_one,
    )

    next_day = day_one + timedelta(
        days=1,
    )

    guard.roll_daily_baseline(
        observed_at=next_day,
    )

    status = guard.status()

    assert status["daily_start_equity"] == 9_700.0
    assert status["daily_loss_percent"] == 0.0


def test_order_allowed_when_all_limits_are_healthy() -> None:
    from exchange.execution_risk_guard import ExecutionRiskGuard

    guard = ExecutionRiskGuard(
        starting_equity=10_000.0,
        max_daily_loss_percent=5.0,
        max_drawdown_percent=10.0,
    )

    guard.record_equity(
        equity=9_800.0,
    )

    decision = guard.authorize_order()

    assert decision == {
        "allowed": True,
        "status": "AUTHORIZED",
        "reason": "RISK_LIMITS_HEALTHY",
    }
