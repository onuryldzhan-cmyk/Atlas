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


# ------------------- EXP-001 admissions stay HIGH-sized (owner, v5.22)

from types import SimpleNamespace

from core.risk_engine import EXPERIMENT_SIZING_BUCKET, RiskBucket
from tests.test_exp001_paper_confidence_experiment import engine as exp_engine


def test_experiment_sizing_bucket_is_high():
    assert EXPERIMENT_SIZING_BUCKET is RiskBucket.HIGH


@pytest.mark.parametrize("bucket,confidence,expected", [
    ("MEDIUM", "0.63", RiskBucket.HIGH),    # only the experiment admits -> HIGH limits
    ("HIGH", "0.63", RiskBucket.HIGH),
    ("MEDIUM", "0.75", RiskBucket.MEDIUM),  # default floor met -> own limits
    ("LOW", "0.63", RiskBucket.LOW),        # LOW default floor is 0.60
    ("MEDIUM", "0.55", RiskBucket.HIGH),    # rejected anyway; stricter sizing is harmless
])
def test_sizing_bucket_with_experiment(bucket, confidence, expected):
    assert exp_engine().sizing_bucket(bucket, D(confidence)) is expected


def test_sizing_bucket_without_experiment_is_identity():
    risk = exp_engine(attach=False)
    for bucket in ("LOW", "MEDIUM", "HIGH"):
        assert risk.sizing_bucket(bucket, D("0.63")) is RiskBucket(bucket)


def test_experiment_admission_in_medium_is_capped_at_high_allocation():
    # capital 1000: HIGH allows 100, MEDIUM 250
    risk = exp_engine()
    over = risk.evaluate(buy(bucket="MEDIUM", confidence="0.63", amount="150"), state())
    assert over.reason_code == "REQUEST_EXCEEDS_RISK_LIMIT"
    assert risk.experiment_admissions == 0
    ok = risk.evaluate(buy(bucket="MEDIUM", confidence="0.63", amount="100"), state())
    assert ok.approved and ok.experiment_id == "EXP-001"


def test_default_medium_admission_keeps_medium_limits():
    risk = exp_engine()
    d = risk.evaluate(buy(bucket="MEDIUM", confidence="0.75", amount="150"), state())
    assert d.approved and d.experiment_id == ""


def _loop_with(engine_obj):
    from core.market_loop import MarketLoop
    loop = MarketLoop.__new__(MarketLoop)
    loop.execution = SimpleNamespace(risk_engine=engine_obj)
    return loop


def test_market_loop_sizes_experiment_buys_as_high():
    loop = _loop_with(exp_engine())
    assert loop._sizing_risk_bucket("MEDIUM", {"confidence": 63.58}) == "HIGH"
    assert loop._sizing_risk_bucket("MEDIUM", {"confidence": 75.0}) == "MEDIUM"
    assert loop._sizing_risk_bucket("CRITICAL", {"confidence": 63.58}) == "CRITICAL"


@pytest.mark.parametrize("decision", [{}, {"confidence": None}, {"confidence": "x"}])
def test_market_loop_sizing_failure_is_strictest(decision):
    assert _loop_with(exp_engine())._sizing_risk_bucket("LOW", decision) == "HIGH"


def test_market_loop_without_engine_keeps_bucket():
    assert _loop_with(None)._sizing_risk_bucket("MEDIUM", {"confidence": 63.0}) == "MEDIUM"


# ------------------ end to end from real candles (v5.22 audit test gap)

import contextlib
import io
import math as _math

from core.market_loop import MarketLoop
from core.market_risk_regime import MarketRiskRegimeProvider
from tests.test_backlog001_macro_risk_wiring_and_fusion import FusingBrain, StubMacro, treasury


def _series(step_fraction, count=200, start=100.0):
    """Closes shrinking steps: newest window calmest (regime LOW), with the
    absolute size of the moves set by step_fraction."""
    rows, close = [], start
    for i in range(count):
        close *= 1 + step_fraction * (count - i) / count
        open_ms = 1_700_000_000_000 + i * 60_000
        rows.append([open_ms, f"{close:.6f}", f"{close:.6f}", f"{close:.6f}",
                     f"{close:.6f}", "10", open_ms + 59_999, "0", 0, "4", "400", "0"])
    return rows


class _Feed:
    def __init__(self, rows):
        self.rows = rows

    def candles(self, symbol, interval="1m", limit=500):
        return self.rows[-limit:]


def _pipeline(rows):
    brain = FusingBrain()
    loop = MarketLoop(brain=brain, market_feed=_Feed(rows), execution=None, symbols=["BTCUSDT"],
                      macro_provider=StubMacro(treasury(0)),  # FLAT -> Macro HOLD
                      market_risk_provider=MarketRiskRegimeProvider())
    with contextlib.redirect_stdout(io.StringIO()):
        loop.process_symbol("BTCUSDT")
    return brain.market_data[0]


def test_real_candles_calm_market_below_ceiling_is_low():
    data = _pipeline(_series(0.00005))
    evidence = data["market_risk_evidence"]
    assert evidence["regime"] == "LOW"
    assert evidence["realized_volatility"] < LOW_VOLATILITY_CEILINGS["BTCUSDT"]
    assert regime_risk_result(data, "BTCUSDT").level is RiskCategory.LOW


def test_real_candles_relatively_calm_but_absolutely_volatile_is_not_low():
    """The proposal's open question 4: a relative 3h LOW after a wild period
    must not open the permissive bucket - the absolute ceiling blocks it."""
    data = _pipeline(_series(0.005))
    evidence = data["market_risk_evidence"]
    assert evidence["regime"] == "LOW"
    assert evidence["realized_volatility"] > LOW_VOLATILITY_CEILINGS["BTCUSDT"]
    assert regime_risk_result(data, "BTCUSDT").level is RiskCategory.MEDIUM


@pytest.mark.parametrize("regime,vote,expected", [
    ("LOW", "HOLD", "LOW"), ("LOW", "SELL", "MEDIUM"), ("HIGH", "HOLD", "HIGH"),
])
def test_normalized_execution_decision_carries_the_regime_bucket(brain, regime, vote, expected):
    """Resolves the v5.22 audit UNKNOWN: the bucket MarketLoop hands to
    sizing and risk (decision 'risk', falling back to 'risk_level') is the
    regime-derived one, not the advisory score."""
    market = _market(regime, 0.0001, vote)
    raw = brain.analyze_and_decide("BTCUSDT", market)
    loop = MarketLoop(brain=None, market_feed=None)
    normalized = loop.normalize_decision(raw_decision=raw, symbol="BTCUSDT", price=65_000.0,
                                         market_data=market)
    from core.execution_models import normalize_risk
    assert normalize_risk(normalized.get("risk", normalized.get("risk_level"))) == expected
