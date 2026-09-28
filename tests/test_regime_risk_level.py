"""Decision risk_level from the volatility regime (registry v5.22, Phase A).

Owner grant 2026-09-28; design governance/ATLAS_RISK_LEVEL_FROM_VOLATILITY_REGIME_PROPOSAL_v1.0.md.
Covers the proposal's test plan: mapping, fail-closed inputs, NB-4 (no
evidence removal lowers the level), confidence/action unchanged, and
end-to-end admission through the canonical RiskEngine.
"""

from __future__ import annotations

import copy
import itertools
from datetime import UTC, datetime
from decimal import Decimal as D

import pytest

from ai.core.atlas_brain import AtlasBrain
from ai.core.intelligence.risk_engine import (
    LOW_VOLATILITY_CEILINGS,
    AdvisoryRiskScorer,
    RiskCategory,
    regime_risk_result,
)
from core.risk_engine import RiskDecisionStatus, RiskEngine
from tests.test_exp001_paper_confidence_experiment import buy, policy, state

ORDER = {RiskCategory.LOW: 0, RiskCategory.MEDIUM: 1, RiskCategory.HIGH: 2}


def data(regime="LOW", vol=0.0001, macro_vote="HOLD", *, risk_status="AVAILABLE",
         macro_status="AVAILABLE", drop_risk=False, drop_macro=False):
    d = {"evidence_status": {"market_risk": risk_status, "macro": macro_status}}
    if not drop_risk:
        d["market_risk_evidence"] = {"regime": regime, "realized_volatility": vol}
    if not drop_macro:
        d["macro_evidence"] = {"vote": macro_vote}
    return d


def level(d, symbol="BTCUSDT"):
    return regime_risk_result(d, symbol).level


# ---------------------------------------------------------------- mapping

def test_pinned_ceilings_match_owner_decision_v5_20():
    assert LOW_VOLATILITY_CEILINGS == {
        "BTCUSDT": 0.000277, "ETHUSDT": 0.000388, "BNBUSDT": 0.000340,
        "SOLUSDT": 0.000520, "XRPUSDT": 0.000582,
    }


def test_low_below_ceiling_with_macro_hold_or_buy_is_low():
    assert level(data(macro_vote="HOLD")) is RiskCategory.LOW
    assert level(data(macro_vote="BUY")) is RiskCategory.LOW


@pytest.mark.parametrize("regime,expected", [("NEUTRAL", RiskCategory.MEDIUM), ("HIGH", RiskCategory.HIGH)])
def test_neutral_and_high_map_directly(regime, expected):
    assert level(data(regime=regime)) is expected


@pytest.mark.parametrize("symbol,ceiling", sorted(LOW_VOLATILITY_CEILINGS.items()))
def test_absolute_ceiling_is_strict_per_symbol(symbol, ceiling):
    assert level(data(vol=ceiling * 0.999), symbol) is RiskCategory.LOW
    assert level(data(vol=ceiling), symbol) is RiskCategory.MEDIUM
    assert level(data(vol=ceiling * 1.5), symbol) is RiskCategory.MEDIUM


def test_symbol_normalised_and_unknown_symbol_never_low():
    assert level(data(), " btcusdt ") is RiskCategory.LOW
    assert level(data(), "DOGEUSDT") is RiskCategory.MEDIUM
    assert level(data(), None) is RiskCategory.MEDIUM


@pytest.mark.parametrize("vote", ["SELL", None, "", "hold", "UNKNOWN", 1])
def test_macro_cap_applies_to_sell_and_anything_not_hold_or_buy(vote):
    assert level(data(macro_vote=vote)) is RiskCategory.MEDIUM


@pytest.mark.parametrize("status", ["UNAVAILABLE_NO_PROVIDER", "REJECTED_MALFORMED", None, "available"])
def test_macro_not_available_caps_low(status):
    assert level(data(macro_status=status)) is RiskCategory.MEDIUM


# ------------------------------------------------------------ fail-closed

@pytest.mark.parametrize("bad", [
    None, [], "x", {},
    data(risk_status="UNAVAILABLE_PROVIDER_ERROR"),
    data(risk_status="REJECTED_MALFORMED"),
    data(drop_risk=True),
    data(regime=None), data(regime="low"), data(regime="EXTREME"), data(regime=3),
    {"evidence_status": "AVAILABLE", "market_risk_evidence": {"regime": "LOW"}},
    {"evidence_status": {"market_risk": "AVAILABLE"}, "market_risk_evidence": "LOW"},
])
def test_missing_or_malformed_regime_is_high(bad):
    assert level(bad) is RiskCategory.HIGH


@pytest.mark.parametrize("vol", [None, -0.0001, float("nan"), float("inf"), True, "0.0001"])
def test_bad_volatility_value_never_low(vol):
    assert level(data(vol=vol)) is RiskCategory.MEDIUM


def test_never_raises_on_hostile_mapping():
    class Hostile(dict):
        def get(self, *a, **k):
            raise RuntimeError("boom")
    assert level(Hostile()) is RiskCategory.HIGH


# ------------------------------------------------------------------ NB-4

def test_nb4_removing_any_evidence_never_lowers_the_level():
    grid = itertools.product(["LOW", "NEUTRAL", "HIGH"], [0.0001, 0.001],
                             ["HOLD", "BUY", "SELL"], sorted(LOW_VOLATILITY_CEILINGS))
    for regime, vol, vote, symbol in grid:
        full = level(data(regime, vol, vote), symbol)
        for reduced in (
            data(regime, vol, vote, drop_risk=True),
            data(regime, vol, vote, drop_macro=True),
            data(regime, vol, vote, risk_status="UNAVAILABLE_NO_PROVIDER"),
            data(regime, vol, vote, macro_status="UNAVAILABLE_NO_PROVIDER"),
            data(regime, None, vote),
        ):
            assert ORDER[level(reduced, symbol)] >= ORDER[full], (regime, vol, vote, symbol, reduced)


# -------------------------------------------- brain: only risk_level moved

@pytest.fixture
def brain(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    yield AtlasBrain()


def _market(regime, vol, macro_vote):
    return {
        "symbol": "BTCUSDT", "price": 65_000.0, "technical_score": 0.8,
        "risk_score": 0.5, "macro_score": 0.5, "rsi": 50, "trend": "SIDEWAYS",
        "evidence_status": {"technical": "AVAILABLE", "macro": "AVAILABLE",
                            "sentiment": "UNAVAILABLE_NO_PROVIDER", "market_risk": "AVAILABLE"},
        "market_risk_evidence": {"regime": regime, "realized_volatility": vol},
        "macro_evidence": {"vote": macro_vote},
        "timestamp": datetime.now(UTC).isoformat(),
    }


def test_brain_risk_level_follows_regime_and_confidence_is_unchanged(brain):
    low = brain.analyze_and_decide("BTCUSDT", _market("LOW", 0.0001, "HOLD"))
    capped = brain.analyze_and_decide("BTCUSDT", _market("LOW", 0.0001, "SELL"))
    high = brain.analyze_and_decide("BTCUSDT", _market("HIGH", 0.0001, "HOLD"))

    def rl(dec):
        value = getattr(dec, "risk_level", None)
        return getattr(value, "value", value) if value is not None else dec["risk_level"]

    assert str(rl(low)).upper().endswith("LOW")
    assert str(rl(capped)).upper().endswith("MEDIUM")
    assert str(rl(high)).upper().endswith("HIGH")
    # the advisory score is kept for audit only
    assert "advisory_risk" in low.metadata
    # regime changes the level, never the decision's confidence or action
    same = brain.analyze_and_decide("BTCUSDT", _market("NEUTRAL", 0.0001, "HOLD"))
    assert low.confidence == same.confidence and low.action == same.action


def test_advisory_scorer_itself_is_unchanged():
    r = AdvisoryRiskScorer().calculate(confidence=0.5)
    assert r.score == 0.5 and r.level.value in {"MEDIUM", "HIGH", "LOW"}


# --------------------------------------- end to end through the RiskEngine

@pytest.mark.parametrize("bucket,admitted", [("LOW", True), ("MEDIUM", False), ("HIGH", False)])
def test_confidence_6358_admitted_only_in_low_bucket(bucket, admitted):
    decision = RiskEngine(policy()).evaluate(buy(bucket=bucket, confidence="0.6358"), state())
    assert (decision.status is RiskDecisionStatus.APPROVE) is admitted
    if not admitted:
        assert decision.reason_code == "CONFIDENCE_BELOW_POLICY"
