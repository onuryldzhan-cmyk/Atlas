"""Audit F-3: daily-loss gate can count open positions' unrealized loss (flag, default OFF, fail closed)."""

from dataclasses import replace

import pytest

from core.risk_engine import RiskEngine, RiskState
from tests.test_phase3_risk_capital_foundation import D, policy, position, request, state


def with_unrealized(s: RiskState, value):
    return replace(s, unrealized_pnl=None if value is None else D(value))


def test_flag_off_is_the_historical_behaviour():
    engine = RiskEngine(policy())
    s = with_unrealized(state(position(), pnl="-10"), "-100")  # realized 10 + unrealized 100 > 50 limit
    assert engine.evaluate(request(), s).reason_code != "DAILY_LOSS_LIMIT_BREACHED"
    assert engine.evaluate(request(), state(position(), pnl="-10")).reason_code != "UNREALIZED_PNL_UNKNOWN"


def test_flag_on_counts_open_losses_and_still_allows_exits():
    engine = RiskEngine(policy(count_unrealized_in_daily_loss=True))
    s = with_unrealized(state(position(), pnl="-10"), "-45")  # 55 >= 5% of 1000
    assert engine.evaluate(request(), s).reason_code == "DAILY_LOSS_LIMIT_BREACHED"
    close = request(symbol="BTCUSDT", action="SELL", reduce_only=True,
                    requested_quote_allocation=D("50"), base_quantity=D("5"))
    assert engine.evaluate(close, s).reason_code == "RISK_REDUCTION_APPROVED"
    ok = with_unrealized(state(position(), pnl="-10"), "-20")
    assert engine.evaluate(request(), ok).reason_code != "DAILY_LOSS_LIMIT_BREACHED"


def test_flag_on_unknown_unrealized_blocks_new_risk_never_guessed_as_zero():
    engine = RiskEngine(policy(count_unrealized_in_daily_loss=True))
    assert engine.evaluate(request(), state(position())).reason_code == "UNREALIZED_PNL_UNKNOWN"


def test_unrealized_must_be_finite_decimal():
    with pytest.raises(ValueError):
        replace(state(), unrealized_pnl=D("NaN"))
    with pytest.raises(ValueError):
        replace(state(), unrealized_pnl=-1.5)


def test_unrealized_gain_never_offsets_a_realized_loss():
    # Independent audit 2026-10-01 F-A (HIGH): F-3 ON must never be looser than OFF.
    off, on = RiskEngine(policy()), RiskEngine(policy(count_unrealized_in_daily_loss=True))
    breached = with_unrealized(state(position(), pnl="-60"), "+40")   # realized 60 >= 50 limit, paper gain 40
    assert off.evaluate(request(), breached).reason_code == "DAILY_LOSS_LIMIT_BREACHED"
    assert on.evaluate(request(), breached).reason_code == "DAILY_LOSS_LIMIT_BREACHED"


@pytest.mark.parametrize("realized,unrealized", [("-60", "40"), ("-60", "-1"), ("-10", "500"), ("0", "-49"), ("-49", "0")])
def test_flag_on_is_never_looser_than_off(realized, unrealized):
    off, on = RiskEngine(policy()), RiskEngine(policy(count_unrealized_in_daily_loss=True))
    s = with_unrealized(state(position(), pnl=realized), unrealized)
    if off.evaluate(request(), s).reason_code == "DAILY_LOSS_LIMIT_BREACHED":
        assert on.evaluate(request(), s).reason_code == "DAILY_LOSS_LIMIT_BREACHED"
