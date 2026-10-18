"""Range-regime (SIDEWAYS/TRANSITION) confidence floor in RiskEngine: opt-in, raise-only, fail closed."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal as D

import pytest

from core import market_cycle
from core.risk_engine import (
    NON_RANGE_REGIMES,
    RANGE_REGIME_MEDIUM_FLOOR,
    RANGE_REGIMES,
    EXP001_PAPER_CONFIDENCE_EXPERIMENT,
    RiskBucket,
    RiskEngine,
    RiskPolicy,
    RiskRequest,
    RiskState,
)


def _state():
    return RiskState((), D("0"), D("0"), D("1000"), D("1000"), True, datetime.now(UTC).date().isoformat(),
                     "phase3-risk-v1")


def _request(confidence="0.72", bucket="MEDIUM", **changes):
    values = dict(symbol="ETHUSDT", action="BUY", confidence=D(confidence), requested_quote_allocation=D("100"),
                  execution_price=D("10"), risk_bucket=bucket, base_quantity=D("10"))
    values.update(changes)
    return RiskRequest(**values)


def _engine(on=True):
    floors = RANGE_REGIME_MEDIUM_FLOOR if on else {}
    return RiskEngine(RiskPolicy(total_capital=D("1000"), range_regime_minimum_confidence=floors))


@pytest.mark.parametrize("regime", ["SIDEWAYS", "TRANSITION", "sideways", " Transition "])
def test_medium_buy_between_70_and_75_is_refused_in_a_range_regime(regime):
    result = _engine().evaluate(_request(market_regime=regime), _state())
    assert result.approved is False and result.reason_code == "CONFIDENCE_BELOW_POLICY"
    assert result.detail["range_regime_floor"].startswith("0.75")


@pytest.mark.parametrize("regime", ["SIDEWAYS", "TRANSITION"])
def test_medium_buy_at_or_above_75_is_approved_in_a_range_regime(regime):
    assert _engine().evaluate(_request("0.75", market_regime=regime), _state()).approved is True
    assert _engine().evaluate(_request("0.90", market_regime=regime), _state()).approved is True


@pytest.mark.parametrize("regime", sorted(NON_RANGE_REGIMES))
def test_directional_regimes_keep_the_normal_70_floor(regime):
    assert _engine().evaluate(_request("0.72", market_regime=regime), _state()).approved is True


@pytest.mark.parametrize("regime", [None, "", "UNKNOWN", "BULLISH", 7, ["SIDEWAYS"]])
def test_missing_or_unknown_regime_fails_closed(regime):
    result = _engine().evaluate(_request("0.72", market_regime=regime), _state())
    assert result.approved is False and result.reason_code == "CONFIDENCE_BELOW_POLICY"


def test_below_the_normal_floor_is_still_refused_in_every_regime():
    for regime in ("TREND_UP", "SIDEWAYS", None):
        assert _engine().evaluate(_request("0.69", market_regime=regime), _state()).approved is False


def test_only_the_configured_bucket_is_raised():
    # HIGH keeps its own 0.80 floor and LOW its 0.60 floor: the range-regime map names only MEDIUM
    assert _engine().evaluate(_request("0.80", bucket="HIGH", market_regime="SIDEWAYS"), _state()).approved is True
    assert _engine().evaluate(_request("0.60", bucket="LOW", market_regime="SIDEWAYS"), _state()).approved is True
    assert _engine().evaluate(_request("0.79", bucket="HIGH", market_regime="SIDEWAYS"), _state()).approved is False


def test_default_policy_ignores_the_regime_and_decisions_are_unchanged():
    off, plain = _engine(on=False), RiskEngine(RiskPolicy(total_capital=D("1000")))
    assert RiskPolicy(total_capital=D("1000")).range_regime_minimum_confidence == {}
    for regime in (None, "SIDEWAYS", "TRANSITION", "TREND_UP"):
        a = off.evaluate(_request("0.72", market_regime=regime), _state())
        b = plain.evaluate(_request("0.72"), _state())
        assert a.approved is True and a.to_dict() == b.to_dict()
    rejected = off.evaluate(_request("0.50", market_regime="SIDEWAYS"), _state())
    assert rejected.reason_code == "CONFIDENCE_BELOW_POLICY" and not rejected.detail


def test_the_floor_cannot_be_lowered_by_the_regime_hook_and_exits_never_see_it():
    engine = _engine()
    assert engine.evaluate(_request("0.80", market_regime="SIDEWAYS"), _state()).approved is True
    held = RiskState((), D("0"), D("0"), D("1000"), D("1000"), True, datetime.now(UTC).date().isoformat(),
                     "phase3-risk-v1")
    sell = _request("0.0", action="SELL", reduce_only=True, market_regime="SIDEWAYS")
    assert engine.evaluate(sell, held).reason_code != "CONFIDENCE_BELOW_POLICY"


def test_a_paper_confidence_experiment_cannot_undercut_the_range_floor():
    policy = RiskPolicy(total_capital=D("1000"), range_regime_minimum_confidence=RANGE_REGIME_MEDIUM_FLOOR)
    experiment = EXP001_PAPER_CONFIDENCE_EXPERIMENT
    engine = RiskEngine(policy)
    engine.attach_experiment(experiment, prior_admissions=0, clock=lambda: experiment.starts_at)
    low = experiment.minimum_confidence
    if RiskBucket.MEDIUM in experiment.buckets:
        assert low < D("0.75")
        refused = engine.evaluate(_request(str(max(low, D("0.60"))), market_regime="SIDEWAYS"), _state())
        assert refused.approved is False and refused.reason_code == "CONFIDENCE_BELOW_POLICY"
        # outside a range regime the experiment still admits below the normal floor
        admitted = engine.evaluate(_request(str(max(low, D("0.60"))), market_regime="TREND_UP"), _state())
        assert admitted.approved is True and admitted.experiment_id


@pytest.mark.parametrize("bad", ["0", "1.5", "-0.1", "nan", "x"])
def test_invalid_floor_values_are_refused(bad):
    with pytest.raises((ValueError, TypeError)):
        RiskPolicy(total_capital=D("1000"), range_regime_minimum_confidence={RiskBucket.MEDIUM: bad})


def test_unknown_bucket_in_the_floor_map_is_refused():
    with pytest.raises(ValueError):
        RiskPolicy(total_capital=D("1000"), range_regime_minimum_confidence={"EXTREME": D("0.75")})


def test_regime_labels_match_the_runtime_classifier():
    assert RANGE_REGIMES | NON_RANGE_REGIMES | {market_cycle.UNKNOWN} == set(market_cycle.REGIMES)
    assert not RANGE_REGIMES & NON_RANGE_REGIMES


def test_execution_manager_forwards_only_a_string_regime():
    from core.execution_manager import _request_market_regime

    class R:
        def __init__(self, metadata):
            self.metadata = metadata

    assert _request_market_regime(R({"market_regime": "SIDEWAYS"})) == "SIDEWAYS"
    for metadata in ({}, {"market_regime": 3}, {"market_regime": None}, None, "x"):
        assert _request_market_regime(R(metadata)) is None
    assert _request_market_regime(object()) is None
