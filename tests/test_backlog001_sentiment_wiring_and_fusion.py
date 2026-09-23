"""BACKLOG-001 / registry v4.66: sentiment wiring, scoring rule and fusion.

Covers the L2 -> L3 -> L4 path end to end without a live Atlas process and
without the network:

- MarketLoop (L3) turns a provider reading into plain values;
- WorldAnalysisEngine (L4) applies the owner-confirmed four-branch rule and
  keeps the 25-74 band out of the vote;
- the real AgentFusion reaches three participants only in the fear or greed
  band, and its measured confidence is compared with registry v4.65's
  fixture-only baseline (0.4702 / 0.4702 / 0.4444).

Every expected value below is produced by the real code under test, never
hand-computed.
"""

from __future__ import annotations

import ast
import inspect

from datetime import UTC, datetime, timedelta
from enum import IntEnum

import pytest

import analysis.world_analysis_engine as world_analysis_module
from ai.core.intelligence.agent_fusion import AgentFusion
from analysis.evidence_status import MarketDataEvidenceStatus as Status
from analysis.world_analysis_engine import WorldAnalysisEngine
from atlas_finance.market_data.fear_greed_provider import (
    REASON_NETWORK_ERROR,
    FearGreedProvider,
    FearGreedReading,
)
from core.application import AtlasApplication
from core.execution_manager import ExecutionManager
from core.market_loop import MarketLoop


NOW = datetime(2026, 9, 23, 12, tzinfo=UTC)


class _Ten(IntEnum):
    TEN = 10


FEAR, NEUTRAL, GREED = 10, 50, 80


def reading(value) -> FearGreedReading:
    return FearGreedReading(available=True, value=value, observed_at=NOW,
                            fetched_at=NOW, reason="OK")


class StubProvider:
    def __init__(self, result) -> None:
        self.result = result
        self.calls = 0

    def get_reading(self):
        self.calls += 1
        if isinstance(self.result, BaseException):
            raise self.result
        return self.result


def sentiment_input(value, band, status="AVAILABLE"):
    return {"provider_status": status, "value": value, "band": band, "reason": "OK"}


def market_data(sentiment, trend="BULLISH", rsi=50, score=None):
    analysis = {"rsi": rsi, "trend": trend}
    if score is None:
        score = MarketLoop.calculate_score(analysis)
    return WorldAnalysisEngine().build_market_data(
        "BTCUSDT", 100.0, analysis, score, sentiment_input=sentiment,
    )


def loop_input(value, trend="BULLISH", rsi=50):
    """Plain values exactly as MarketLoop builds them from a real reading."""
    loop = MarketLoop(brain=None, market_feed=None, sentiment_provider=StubProvider(reading(value)))
    return market_data(loop._sentiment_input(), trend=trend, rsi=rsi)


# ---------------------------------------------------------------------------
# L3: MarketLoop builds plain values
# ---------------------------------------------------------------------------


def test_no_provider_means_no_sentiment_input():
    assert MarketLoop(brain=None, market_feed=None)._sentiment_input() is None


@pytest.mark.parametrize(("value", "band"), [(10, "FEAR"), (24, "FEAR"), (25, "NEUTRAL"),
                                             (74, "NEUTRAL"), (75, "GREED"), (90, "GREED")])
def test_available_reading_becomes_plain_value_and_band(value, band):
    loop = MarketLoop(brain=None, market_feed=None, sentiment_provider=StubProvider(reading(value)))

    result = loop._sentiment_input()

    assert result == {"provider_status": "AVAILABLE", "value": value, "band": band, "reason": "OK"}
    assert all(isinstance(item, (str, int)) for item in result.values())


@pytest.mark.parametrize(("result", "reason"), [
    (FearGreedReading.unavailable("STALE"), "STALE"),
    (FearGreedReading.unavailable(REASON_NETWORK_ERROR), REASON_NETWORK_ERROR),
    (RuntimeError("provider bug"), "PROVIDER_EXCEPTION"),
    (FearGreedReading(True, 150, NOW, NOW, "OK"), "PROVIDER_EXCEPTION"),
    (FearGreedReading(True, "10", NOW, NOW, "OK"), "PROVIDER_EXCEPTION"),
    (FearGreedReading(True, True, NOW, NOW, "OK"), "PROVIDER_EXCEPTION"),
    (FearGreedReading(True, None, NOW, NOW, "OK"), "PROVIDER_EXCEPTION"),
    (FearGreedReading(True, _Ten.TEN, NOW, NOW, "OK"), "PROVIDER_EXCEPTION"),
    (FearGreedReading(1, 10, NOW, NOW, "OK"), "MALFORMED_READING"),
    (FearGreedReading("yes", 10, NOW, NOW, "OK"), "MALFORMED_READING"),
    (object(), "MALFORMED_READING"),
    (None, "MALFORMED_READING"),
])
def test_any_provider_failure_becomes_provider_error_without_a_value(result, reason):
    loop = MarketLoop(brain=None, market_feed=None, sentiment_provider=StubProvider(result))

    plain = loop._sentiment_input()

    assert plain == {"provider_status": "UNAVAILABLE_PROVIDER_ERROR",
                     "value": None, "band": None, "reason": reason}


# ---------------------------------------------------------------------------
# L3 -> L4 through the real process_symbol pipeline
# ---------------------------------------------------------------------------


def candles(count=200, *, rising=True):
    rows = []
    for index in range(count):
        open_ms = 1_700_000_000_000 + index * 60_000
        close = 100.0 + index * 0.5 if rising else 300.0 - index * 0.5
        rows.append([open_ms, f"{close:.2f}", f"{close + 1:.2f}", f"{close - 1:.2f}",
                     f"{close:.2f}", "10", open_ms + 59_999, "0", 0, "4", "400", "0"])
    return rows


class OfflineFeed:
    def __init__(self, *, rising=True) -> None:
        self.rising = rising

    def candles(self, symbol, interval="1m", limit=500):
        return candles(limit, rising=self.rising)


class FusingBrain:
    """Runs the real AgentFusion on exactly the market_data MarketLoop built."""

    def __init__(self) -> None:
        self.market_data = []
        self.signals = []
        self.results = []

    def analyze_and_decide(self, symbol, market_data):
        fusion = AgentFusion()
        signals = fusion.evaluate(symbol, market_data)
        self.market_data.append(market_data)
        self.signals.append(signals)
        self.results.append(fusion.fuse(signals))
        return {"symbol": symbol, "action": "HOLD", "confidence": 0.0}


def run_loop(provider, *, rising=True):
    brain = FusingBrain()
    loop = MarketLoop(brain=brain, market_feed=OfflineFeed(rising=rising), execution=None,
                      symbols=["BTCUSDT"], sentiment_provider=provider)
    loop.process_symbol("BTCUSDT")
    assert len(brain.market_data) == 1
    return brain


def test_pipeline_fear_and_rising_market_reaches_three_participants():
    brain = run_loop(StubProvider(reading(FEAR)), rising=True)
    data = brain.market_data[0]

    assert data["trend"] == "BULLISH"
    assert data["evidence_status"]["sentiment"] == Status.AVAILABLE.value
    assert data["sentiment_score"] == 0.75
    assert data["sentiment_evidence"] == {"fear_greed_index": FEAR, "band": "FEAR",
                                          "trend_basis": "BULLISH", "vote": "BUY", "reason": "OK"}
    assert set(brain.signals[0]) == {"technical", "momentum", "sentiment"}
    assert brain.results[0].reason != "INSUFFICIENT_EVIDENCE"


def test_pipeline_fear_and_falling_market_votes_sell():
    brain = run_loop(StubProvider(reading(FEAR)), rising=False)
    data = brain.market_data[0]

    assert data["trend"] == "BEARISH"
    assert brain.signals[0]["sentiment"] == {"action": "SELL", "score": 0.25}


def test_pipeline_neutral_band_is_withheld():
    brain = run_loop(StubProvider(reading(NEUTRAL)))
    data = brain.market_data[0]

    assert data["evidence_status"]["sentiment"] == Status.UNAVAILABLE_NO_PROVIDER.value
    assert "sentiment_score" not in data
    assert data["sentiment_evidence"]["reason"] == "NEUTRAL_BAND_NO_DIRECTIONAL_SIGNAL"
    assert "sentiment" not in brain.signals[0]
    assert brain.results[0].reason == "INSUFFICIENT_EVIDENCE"


@pytest.mark.parametrize("value", range(25, 75))
def test_neutral_band_withholding_unchanged_for_every_value_25_to_74(value):
    """GRANT-NEUTRAL-BAND-WORDING-FIX (registry v4.68) changed only the
    module comment above build_market_data(); this pins the runtime
    behavior it describes as bit-for-bit unchanged across the full
    neutral band (25-74), independent of trend."""
    data = loop_input(value)

    assert data["evidence_status"]["sentiment"] == Status.UNAVAILABLE_NO_PROVIDER.value
    assert "sentiment_score" not in data
    assert data["sentiment_evidence"] == {
        "fear_greed_index": value,
        "band": "NEUTRAL",
        "vote": None,
        "reason": "NEUTRAL_BAND_NO_DIRECTIONAL_SIGNAL",
    }


def test_pipeline_provider_error_is_reported_and_withheld():
    brain = run_loop(StubProvider(FearGreedReading.unavailable("STALE")))
    data = brain.market_data[0]

    assert data["evidence_status"]["sentiment"] == Status.UNAVAILABLE_PROVIDER_ERROR.value
    assert "sentiment_score" not in data
    assert data["sentiment_evidence"]["reason"] == "STALE"
    assert "sentiment" not in brain.signals[0]
    assert brain.results[0].reason == "INSUFFICIENT_EVIDENCE"


def test_pipeline_without_provider_is_unchanged():
    brain = run_loop(None)
    data = brain.market_data[0]

    assert data["evidence_status"]["sentiment"] == Status.UNAVAILABLE_NO_PROVIDER.value
    assert "sentiment_score" not in data
    assert "sentiment_evidence" not in data


@pytest.mark.parametrize("provider", [StubProvider(reading(FEAR)), StubProvider(reading(GREED)),
                                      StubProvider(RuntimeError("x")), None])
def test_macro_and_market_risk_slots_are_untouched(provider):
    data = run_loop(provider).market_data[0]
    assert data["evidence_status"]["macro"] == Status.UNAVAILABLE_NO_PROVIDER.value
    assert data["evidence_status"]["market_risk"] == Status.UNAVAILABLE_NO_PROVIDER.value
    assert "macro_score" not in data and "risk_score" not in data


def test_loop_respects_the_provider_cache_across_cycles():
    fetches = []

    def transport(url, timeout):
        fetches.append(url)
        return (b'{"data":[{"value":"10","timestamp":"%d"}],"metadata":{"error":null}}'
                % int(datetime.now(UTC).replace(hour=0, minute=0, second=0, microsecond=0).timestamp()))

    provider = FearGreedProvider(transport=transport)
    brain = FusingBrain()
    loop = MarketLoop(brain=brain, market_feed=None, execution=None,
                      symbols=["BTCUSDT", "ETHUSDT"], sentiment_provider=provider)

    for epoch in range(5):
        for symbol in loop.symbols:
            loop.market_feed = OfflineFeed()
            loop.last_processed_candles.clear()
            loop.process_symbol(symbol)

    assert len(brain.market_data) == 10
    assert all(d["evidence_status"]["sentiment"] == "AVAILABLE" for d in brain.market_data)
    assert len(fetches) == 1


def test_composition_root_injects_the_real_provider(tmp_path):
    app = AtlasApplication(state_directory=tmp_path / "state")

    provider = app.market_loop.sentiment_provider
    assert isinstance(provider, FearGreedProvider)
    assert provider is app.sentiment_provider

    # Under pytest the network guard makes the live transport fail closed.
    plain = app.market_loop._sentiment_input()
    assert plain == {"provider_status": "UNAVAILABLE_PROVIDER_ERROR", "value": None,
                     "band": None, "reason": REASON_NETWORK_ERROR}


def test_world_analysis_engine_imports_nothing_network_or_l2():
    tree = ast.parse(inspect.getsource(world_analysis_module))
    modules = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            modules.add(node.module or "")
    assert modules == {"datetime", "analysis.evidence_status"}


# ---------------------------------------------------------------------------
# L4: the owner-confirmed scoring rule
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(("band", "trend", "vote"), [
    ("FEAR", "BULLISH", "BUY"),
    ("FEAR", "BEARISH", "SELL"),
    ("FEAR", None, "SELL"),
    ("GREED", "BULLISH", "SELL"),
    ("GREED", "BEARISH", "HOLD"),
    ("GREED", None, "HOLD"),
])
def test_sentiment_vote_rule(band, trend, vote):
    assert WorldAnalysisEngine.sentiment_vote(band, trend) == vote


@pytest.mark.parametrize("band", ["NEUTRAL", None, "fear", "EXTREME_FEAR"])
def test_no_vote_exists_outside_fear_and_greed(band):
    with pytest.raises(ValueError):
        WorldAnalysisEngine.sentiment_vote(band, "BULLISH")


@pytest.mark.parametrize(("value", "trend", "action"), [
    (FEAR, "BULLISH", "BUY"),
    (FEAR, "BEARISH", "SELL"),
    (FEAR, "NEUTRAL", "SELL"),
    (GREED, "BULLISH", "SELL"),
    (GREED, "BEARISH", "HOLD"),
    (GREED, "NEUTRAL", "HOLD"),
])
def test_rule_through_build_market_data_and_agent_fusion_threshold(value, trend, action):
    data = loop_input(value, trend=trend)

    assert data["evidence_status"]["sentiment"] == Status.AVAILABLE.value
    assert data["sentiment_evidence"]["vote"] == action
    # The encoded score must land in the intended AgentFusion action bucket.
    assert AgentFusion().score_to_action(data["sentiment_score"]) == action
    assert AgentFusion().evaluate("BTCUSDT", data)["sentiment"]["action"] == action


@pytest.mark.parametrize("value", [25, 26, 49, 50, 73, 74])
@pytest.mark.parametrize("trend", ["BULLISH", "BEARISH", "NEUTRAL"])
def test_neutral_band_never_participates(value, trend):
    data = loop_input(value, trend=trend)

    assert data["evidence_status"]["sentiment"] == Status.UNAVAILABLE_NO_PROVIDER.value
    assert "sentiment_score" not in data
    fusion = AgentFusion()
    assert "sentiment" not in fusion.evaluate("BTCUSDT", data)
    assert fusion.last_unavailable_agents["sentiment"] == Status.UNAVAILABLE_NO_PROVIDER.value


@pytest.mark.parametrize("trend", ["bullish", "Bullish", "SIDEWAYS", None, 1, ["BULLISH"]])
def test_non_exact_trend_is_ambiguous_never_bullish(trend):
    fear = market_data(sentiment_input(FEAR, "FEAR"), trend=trend, score=0.5)
    greed = market_data(sentiment_input(GREED, "GREED"), trend=trend, score=0.5)
    assert fear["sentiment_evidence"]["vote"] == "SELL"
    assert greed["sentiment_evidence"]["vote"] == "HOLD"


@pytest.mark.parametrize("rsi", [None, "n/a", object()])
def test_rejected_technical_evidence_makes_trend_ambiguous(rsi):
    data = market_data(sentiment_input(FEAR, "FEAR"), trend="BULLISH", rsi=rsi, score=0.5)

    assert data["evidence_status"]["technical"] == Status.REJECTED_MALFORMED.value
    assert data["sentiment_evidence"]["trend_basis"] == "AMBIGUOUS"
    assert data["sentiment_evidence"]["vote"] == "SELL"


@pytest.mark.parametrize("bad", [
    "AVAILABLE",
    ["AVAILABLE", 10, "FEAR"],
    sentiment_input(10, "FEAR", status="available"),
    sentiment_input(10, "FEAR", status=None),
    sentiment_input(True, "FEAR"),
    sentiment_input(10.0, "FEAR"),
    sentiment_input(_Ten.TEN, "FEAR"),
    sentiment_input("10", "FEAR"),
    sentiment_input(-1, "FEAR"),
    sentiment_input(101, "GREED"),
    sentiment_input(None, "FEAR"),
    sentiment_input(10, "fear"),
    sentiment_input(10, None),
    sentiment_input(10, "EXTREME_FEAR"),
    {},
])
def test_malformed_sentiment_input_is_rejected_without_a_score(bad):
    data = market_data(bad)

    assert data["evidence_status"]["sentiment"] == Status.REJECTED_MALFORMED.value
    assert "sentiment_score" not in data


def test_provider_error_input_is_never_scored_even_with_a_value_attached():
    tampered = {"provider_status": "UNAVAILABLE_PROVIDER_ERROR", "value": 10,
                "band": "FEAR", "reason": "TIMEOUT"}
    data = market_data(tampered)

    assert data["evidence_status"]["sentiment"] == Status.UNAVAILABLE_PROVIDER_ERROR.value
    assert "sentiment_score" not in data
    assert data["sentiment_evidence"]["fear_greed_index"] is None


def test_audit_key_does_not_collide_with_reasoning_adapter_input():
    # ReasoningAdapter reads market_data["fear_greed"] with a default of 50.
    data = loop_input(FEAR)
    assert "fear_greed" not in data


# ---------------------------------------------------------------------------
# Real in-memory AgentFusion fixture
# ---------------------------------------------------------------------------


# Registry v4.65's measured fixture: (technical, momentum, sentiment) scores
# fed straight into fuse(), and the confidence it measured.
V465_BASELINE = {
    "fear_bullish": ((0.7, 0.55, 0.75), "BUY", 0.4702),
    "fear_bearish": ((0.3, 0.55, 0.25), "SELL", 0.4702),
    "fear_ambiguous": ((0.5, 0.55, 0.25), "HOLD", 0.4444),
}


@pytest.mark.parametrize(("case", "trend"), [
    ("fear_bullish", "BULLISH"), ("fear_bearish", "BEARISH"), ("fear_ambiguous", "NEUTRAL"),
])
def test_real_sentiment_signal_reproduces_the_v465_baseline(case, trend):
    (technical, momentum, sentiment), action, confidence = V465_BASELINE[case]
    fusion = AgentFusion()

    signals = fusion.evaluate("BTCUSDT", loop_input(FEAR, trend=trend) | {"technical_score": technical})

    # Technical and sentiment come from the real producer path; the
    # fixture's momentum of 0.55 is not reachable from calculate_momentum()
    # (0.5 +/- 0.2 trend +/- 0.1 RSI), so it is substituted to reproduce the
    # baseline's exact inputs.
    assert signals["sentiment"]["score"] == sentiment
    assert signals["technical"]["score"] == technical
    signals["momentum"] = {"action": fusion.score_to_action(momentum), "score": momentum}

    result = fusion.fuse(signals)

    assert (result.action, result.confidence, result.reason) == (action, confidence, "FUSED_EVIDENCE")


# The fully real pipeline (technical from MarketLoop.calculate_score, momentum
# from AgentFusion.calculate_momentum, sentiment from the rule) at RSI 50.
# Measured from the implementation in the registry v4.66 session.
REAL_PIPELINE_RSI_50 = [
    (FEAR, "BULLISH", 3, "BUY", 0.6491),
    (FEAR, "BEARISH", 3, "SELL", 0.3007),
    (FEAR, "NEUTRAL", 3, "BUY", 0.3537),
    (GREED, "BULLISH", 3, "BUY", 0.5614),
    (GREED, "BEARISH", 3, "HOLD", 0.3623),
    (GREED, "NEUTRAL", 3, "BUY", 0.3662),
    (NEUTRAL, "BULLISH", 2, "HOLD", 0.0),
    (NEUTRAL, "BEARISH", 2, "HOLD", 0.0),
    (NEUTRAL, "NEUTRAL", 2, "HOLD", 0.0),
]


@pytest.mark.parametrize(("value", "trend", "participants", "action", "confidence"),
                         REAL_PIPELINE_RSI_50)
def test_real_pipeline_fusion(value, trend, participants, action, confidence):
    fusion = AgentFusion()
    signals = fusion.evaluate("BTCUSDT", loop_input(value, trend=trend))
    result = fusion.fuse(signals)

    assert len([name for name in signals if name in fusion.WEIGHTS]) == participants
    assert (result.action, result.confidence) == (action, confidence)
    if participants == 2:
        assert result.reason == "INSUFFICIENT_EVIDENCE"


GRID = [(value, trend, rsi)
        for value in (0, 24, 25, 50, 74, 75, 100)
        for trend in ("BULLISH", "BEARISH", "NEUTRAL")
        for rsi in (20, 32, 38, 50, 65, 80)]


@pytest.mark.parametrize(("value", "trend", "rsi"), GRID)
def test_withholding_sentiment_never_raises_confidence_nb4(value, trend, rsi):
    with_sentiment = loop_input(value, trend=trend, rsi=rsi)
    without = dict(with_sentiment, evidence_status=dict(
        with_sentiment["evidence_status"], sentiment=Status.UNAVAILABLE_PROVIDER_ERROR.value))
    without.pop("sentiment_score", None)

    fusion = AgentFusion()
    kept = fusion.fuse(fusion.evaluate("BTCUSDT", with_sentiment))
    removed = fusion.fuse(fusion.evaluate("BTCUSDT", without))

    assert removed.confidence <= kept.confidence
    assert (removed.action, removed.reason) == ("HOLD", "INSUFFICIENT_EVIDENCE")


@pytest.mark.parametrize(("value", "trend", "rsi"), GRID)
def test_sentiment_never_makes_a_trade_it_voted_against_execution_eligible(value, trend, rsi):
    """Sentiment's participation clears the 3-agent floor even when it
    dissents; this pins that such a dissent can never reach execution's
    MIN_CONFIDENCE, and that greed or the neutral band never can either."""

    data = loop_input(value, trend=trend, rsi=rsi)
    fusion = AgentFusion()
    signals = fusion.evaluate("BTCUSDT", data)
    result = fusion.fuse(signals)

    eligible = result.action != "HOLD" and result.confidence * 100 >= ExecutionManager.MIN_CONFIDENCE
    if eligible:
        assert signals["sentiment"]["action"] == result.action
        assert data["sentiment_evidence"]["band"] == "FEAR"
