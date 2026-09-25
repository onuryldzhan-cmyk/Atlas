"""BACKLOG-001 / registry v4.79: macro + market-risk wiring, vote rules and fusion.

Covers the L2 -> L3 -> L4 -> AgentFusion path for the two new agents without
a live Atlas process and without the network:

- MarketLoop (L3) turns a Treasury reading and a volatility-regime reading
  into plain values, fail-closed;
- WorldAnalysisEngine (L4) applies the owner-approved vote rules;
- the real, unchanged AgentFusion handles every combination of
  active/excluded sentiment, macro and market-risk agents;
- NB-4 (removing evidence never raises confidence) and NB-5 (the expected
  five-agent roster is the denominator) hold with 2, 3, 4 and 5 agents.

Expected fusion values are produced by the real code under test, never
hand-computed, except where a closed-form NB-5 identity is the point.
"""

from __future__ import annotations

import contextlib
import io
import itertools

from datetime import UTC, date, datetime

import pytest

from ai.core.intelligence.agent_fusion import AgentFusion
from analysis.evidence_status import MarketDataEvidenceStatus as Status
from analysis.world_analysis_engine import WorldAnalysisEngine
from atlas_finance.market_data.fear_greed_provider import FearGreedReading
from atlas_finance.market_data.treasury_yield_provider import (
    REASON_NETWORK_ERROR,
    REASON_STALE,
    TreasuryYieldProvider,
    TreasuryYieldReading,
)
from core.application import AtlasApplication
from core.execution_manager import ExecutionManager
from core.market_loop import MarketLoop
from core.market_risk_regime import (
    REASON_INSUFFICIENT_HISTORY,
    MarketRiskRegimeProvider,
    MarketRiskRegimeReading,
)


NOW = datetime(2026, 9, 25, 12, tzinfo=UTC)
ELIGIBLE = ExecutionManager.MIN_CONFIDENCE


# ---------------------------------------------------------------------------
# Stub readings and providers
# ---------------------------------------------------------------------------


def treasury(change_bp, spread_bp=31):
    return TreasuryYieldReading(
        available=True, observed_date=date(2026, 9, 24), lookback_date=date(2026, 8, 26),
        ten_year_yield=None, two_year_yield=None, ten_year_change_bp=change_bp,
        curve_spread_bp=spread_bp, fetched_at=NOW, reason="OK")


def regime(name, current, p20=1.0, p80=2.0):
    return MarketRiskRegimeReading(available=True, regime=name, realized_volatility=current,
                                   p20=p20, p80=p80, reference_windows=168, reason="OK")


MACRO_READINGS = {
    "RISING": treasury(52),
    "FALLING": treasury(-40),
    "FALLING_INVERTED": treasury(-40, spread_bp=-20),
    "FLAT": treasury(0),
    "ERROR": TreasuryYieldReading.unavailable(REASON_STALE),
}

RISK_READINGS = {
    "HIGH": regime("HIGH", 3.0),
    "NEUTRAL": regime("NEUTRAL", 1.5),
    "LOW": regime("LOW", 0.5),
    "ERROR": MarketRiskRegimeReading.unavailable(REASON_INSUFFICIENT_HISTORY),
}

SENTIMENT_READINGS = {
    "FEAR": FearGreedReading(available=True, value=10, observed_at=NOW, fetched_at=NOW,
                             reason="OK"),
    "NEUTRAL": FearGreedReading(available=True, value=50, observed_at=NOW, fetched_at=NOW,
                                reason="OK"),
    "ERROR": FearGreedReading.unavailable("NETWORK_ERROR"),
}

# State name -> does that agent participate?
MACRO_ACTIVE = {None: False, "RISING": True, "FALLING": True, "FALLING_INVERTED": True,
                "FLAT": True, "ERROR": False}
RISK_ACTIVE = {None: False, "HIGH": True, "NEUTRAL": True, "LOW": True, "ERROR": False}
SENTIMENT_ACTIVE = {None: False, "FEAR": True, "NEUTRAL": False, "ERROR": False}


class StubMacro:
    def __init__(self, result) -> None:
        self.result = result
        self.calls = 0

    def get_reading(self):
        self.calls += 1
        if isinstance(self.result, BaseException):
            raise self.result
        return self.result


class StubRisk:
    def __init__(self, result) -> None:
        self.result = result
        self.seen = []

    def assess(self, closed_candles):
        self.seen.append(closed_candles)
        if isinstance(self.result, BaseException):
            raise self.result
        return self.result


def stub(readings, cls, name):
    return None if name is None else cls(readings[name])


# ---------------------------------------------------------------------------
# Pipeline harness (same shape as the sentiment wiring tests)
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


def run_loop(*, sentiment=None, macro=None, risk=None, rising=True):
    brain = FusingBrain()
    loop = MarketLoop(brain=brain, market_feed=OfflineFeed(rising=rising), execution=None,
                      symbols=["BTCUSDT"], sentiment_provider=sentiment,
                      macro_provider=macro, market_risk_provider=risk)
    with contextlib.redirect_stdout(io.StringIO()):
        loop.process_symbol("BTCUSDT")
    assert len(brain.market_data) == 1
    return brain


def fuse_market_data(market_data):
    with contextlib.redirect_stdout(io.StringIO()):
        fusion = AgentFusion()
        signals = fusion.evaluate("BTCUSDT", market_data)
        return signals, fusion.fuse(signals)


# ---------------------------------------------------------------------------
# L3: MarketLoop builds plain values
# ---------------------------------------------------------------------------


def macro_loop(provider):
    return MarketLoop(brain=None, market_feed=None, macro_provider=provider)


def risk_loop(provider):
    return MarketLoop(brain=None, market_feed=None, market_risk_provider=provider)


def test_no_providers_means_no_inputs():
    loop = MarketLoop(brain=None, market_feed=None)
    assert loop.macro_provider is None and loop.market_risk_provider is None
    assert loop._macro_input() is None
    assert loop._market_risk_input([]) is None


def test_available_treasury_reading_becomes_plain_values():
    assert macro_loop(StubMacro(treasury(52)))._macro_input() == {
        "provider_status": "AVAILABLE", "ten_year_change_bp": 52, "curve_spread_bp": 31,
        "move": "RISING", "observed_date": "2026-09-24", "reason": "OK"}


MACRO_ERROR = {"provider_status": "UNAVAILABLE_PROVIDER_ERROR", "ten_year_change_bp": None,
               "curve_spread_bp": None, "move": None, "observed_date": None}


@pytest.mark.parametrize(("result", "reason"), [
    (TreasuryYieldReading.unavailable(REASON_STALE), REASON_STALE),
    (TreasuryYieldReading.unavailable(REASON_NETWORK_ERROR), REASON_NETWORK_ERROR),
    (RuntimeError("boom"), "PROVIDER_EXCEPTION"),
    (object(), "MALFORMED_READING"),
    (treasury(True), "PROVIDER_EXCEPTION"),
    (treasury(52.0), "PROVIDER_EXCEPTION"),
    (treasury(52, spread_bp=31.0), "MALFORMED_READING"),
    (treasury(52, spread_bp=None), "MALFORMED_READING"),
])
def test_any_macro_failure_becomes_provider_error_without_values(result, reason):
    assert macro_loop(StubMacro(result))._macro_input() == {**MACRO_ERROR, "reason": reason}


def test_available_regime_reading_becomes_plain_values():
    provider = StubRisk(regime("HIGH", 3.0))
    closed = [{"close": 1.0}]
    assert risk_loop(provider)._market_risk_input(closed) == {
        "provider_status": "AVAILABLE", "regime": "HIGH", "realized_volatility": 3.0,
        "p20": 1.0, "p80": 2.0, "reference_windows": 168, "reason": "OK"}
    assert provider.seen == [closed]


RISK_ERROR = {"provider_status": "UNAVAILABLE_PROVIDER_ERROR", "regime": None,
              "realized_volatility": None, "p20": None, "p80": None, "reference_windows": None}


@pytest.mark.parametrize(("result", "reason"), [
    (MarketRiskRegimeReading.unavailable(REASON_INSUFFICIENT_HISTORY), REASON_INSUFFICIENT_HISTORY),
    (RuntimeError("boom"), "PROVIDER_EXCEPTION"),
    (object(), "MALFORMED_READING"),
])
def test_any_market_risk_failure_becomes_provider_error_without_values(result, reason):
    assert risk_loop(StubRisk(result))._market_risk_input([]) == {**RISK_ERROR, "reason": reason}


def test_market_risk_reads_the_same_closed_candles_the_cycle_analyzed():
    provider = StubRisk(regime("NEUTRAL", 1.5))
    run_loop(risk=provider)
    (seen,) = provider.seen
    assert len(seen) == 200 and all(candle["is_closed"] for candle in seen)


def test_real_regime_provider_through_the_pipeline_is_available():
    data = run_loop(risk=MarketRiskRegimeProvider()).market_data[0]
    assert data["evidence_status"]["market_risk"] == Status.AVAILABLE.value
    assert data["market_risk_evidence"]["reference_windows"] == 200 - 1 - 30
    # The linear-close fixture has monotonically shrinking log returns, so
    # the newest window is the calmest one: LOW, which votes HOLD.
    assert data["market_risk_evidence"]["regime"] == "LOW"
    assert data["risk_score"] == 0.5


def test_short_history_through_the_pipeline_is_excluded():
    class ShortFeed(OfflineFeed):
        def candles(self, symbol, interval="1m", limit=500):
            return candles(100, rising=self.rising)

    brain = FusingBrain()
    loop = MarketLoop(brain=brain, market_feed=ShortFeed(), symbols=["BTCUSDT"],
                      market_risk_provider=MarketRiskRegimeProvider())
    with contextlib.redirect_stdout(io.StringIO()):
        loop.process_symbol("BTCUSDT")
    data = brain.market_data[0]
    assert data["evidence_status"]["market_risk"] == Status.UNAVAILABLE_PROVIDER_ERROR.value
    assert data["market_risk_evidence"]["reason"] == REASON_INSUFFICIENT_HISTORY
    assert "risk_score" not in data and "risk" not in brain.signals[0]


def test_loop_respects_the_treasury_cache_across_cycles():
    urls = []
    header = 'Date,"2 Yr","10 Yr"'
    days = [date(2026, 9, 24 - offset) for offset in range(0, 24)]
    body = ("\r\n".join([header] + [f"{d:%m/%d/%Y},4.80,5.00" for d in days])).encode()

    def transport(url, timeout):
        urls.append(url)
        return body

    provider = TreasuryYieldProvider(transport=transport, clock=lambda: NOW)
    brain = FusingBrain()
    loop = MarketLoop(brain=brain, market_feed=None, symbols=["BTCUSDT", "ETHUSDT"],
                      macro_provider=provider)
    with contextlib.redirect_stdout(io.StringIO()):
        for _ in range(5):
            for symbol in loop.symbols:
                loop.market_feed = OfflineFeed()
                loop.last_processed_candles.clear()
                loop.process_symbol(symbol)

    assert len(brain.market_data) == 10
    assert all(d["evidence_status"]["macro"] == "AVAILABLE" for d in brain.market_data)
    assert len(urls) == 1


def test_composition_root_injects_the_real_providers(tmp_path):
    app = AtlasApplication(state_directory=tmp_path / "state")

    assert isinstance(app.market_loop.macro_provider, TreasuryYieldProvider)
    assert app.market_loop.macro_provider is app.macro_provider
    assert isinstance(app.market_loop.market_risk_provider, MarketRiskRegimeProvider)
    assert app.market_loop.market_risk_provider is app.market_risk_provider

    # Under pytest the network guard makes the live transport fail closed.
    assert app.market_loop._macro_input() == {**MACRO_ERROR, "reason": REASON_NETWORK_ERROR}


# ---------------------------------------------------------------------------
# L4: the vote rules
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(("move", "inverted", "vote"), [
    ("RISING", False, "SELL"), ("RISING", True, "SELL"),
    ("FALLING", False, "BUY"), ("FALLING", True, "HOLD"),
    ("FLAT", False, "HOLD"), ("FLAT", True, "HOLD"),
])
def test_macro_vote_rule(move, inverted, vote):
    assert WorldAnalysisEngine.macro_vote(move, inverted) == vote


@pytest.mark.parametrize(("move", "inverted"), [
    ("UP", False), (None, False), ("RISING", 0), ("FALLING", None), ("FLAT", "False"),
])
def test_no_macro_vote_outside_the_rule(move, inverted):
    with pytest.raises(ValueError):
        WorldAnalysisEngine.macro_vote(move, inverted)


@pytest.mark.parametrize(("regime_name", "vote"), [
    ("HIGH", "SELL"), ("NEUTRAL", "HOLD"), ("LOW", "HOLD"),
])
def test_market_risk_vote_rule_never_buys(regime_name, vote):
    assert WorldAnalysisEngine.market_risk_vote(regime_name) == vote


@pytest.mark.parametrize("bad", ["EXTREME", None, "high"])
def test_no_market_risk_vote_outside_the_rule(bad):
    with pytest.raises(ValueError):
        WorldAnalysisEngine.market_risk_vote(bad)


def build(macro=None, risk=None, sentiment=None, *, rsi=50, trend="BULLISH"):
    analysis = {"rsi": rsi, "trend": trend}
    return WorldAnalysisEngine().build_market_data(
        "BTCUSDT", 100.0, analysis, MarketLoop.calculate_score(analysis),
        sentiment_input=sentiment, macro_input=macro, market_risk_input=risk)


def macro_input(change, spread=31, **overrides):
    loop = macro_loop(StubMacro(treasury(change, spread)))
    return {**loop._macro_input(), **overrides}


def risk_input(name, current, p20=1.0, p80=2.0, **overrides):
    loop = risk_loop(StubRisk(regime(name, current, p20, p80)))
    return {**loop._market_risk_input([]), **overrides}


@pytest.mark.parametrize(("change", "spread", "move", "vote", "score"), [
    (52, 31, "RISING", "SELL", 0.25),
    (25, -10, "RISING", "SELL", 0.25),
    (-25, 0, "FALLING", "BUY", 0.75),
    (-40, -1, "FALLING", "HOLD", 0.50),
    (24, 31, "FLAT", "HOLD", 0.50),
    (-24, -50, "FLAT", "HOLD", 0.50),
])
def test_macro_rule_through_build_market_data(change, spread, move, vote, score):
    data = build(macro=macro_input(change, spread))

    assert data["evidence_status"]["macro"] == Status.AVAILABLE.value
    assert data["macro_score"] == score
    assert data["macro_evidence"] == {
        "source": "US_TREASURY_PAR_YIELD_CURVE", "observed_date": "2026-09-24",
        "ten_year_change_bp": change, "curve_spread_bp": spread,
        "curve_inverted": spread < 0, "move": move, "vote": vote, "reason": "OK"}
    assert AgentFusion().score_to_action(score) == vote


@pytest.mark.parametrize(("name", "current", "vote", "score"), [
    ("HIGH", 3.0, "SELL", 0.25), ("NEUTRAL", 1.5, "HOLD", 0.50),
    ("NEUTRAL", 1.0, "HOLD", 0.50), ("NEUTRAL", 2.0, "HOLD", 0.50), ("LOW", 0.5, "HOLD", 0.50),
])
def test_market_risk_rule_through_build_market_data(name, current, vote, score):
    data = build(risk=risk_input(name, current))

    assert data["evidence_status"]["market_risk"] == Status.AVAILABLE.value
    assert data["risk_score"] == score
    assert data["market_risk_evidence"]["regime"] == name
    assert data["market_risk_evidence"]["vote"] == vote
    assert AgentFusion().score_to_action(score) == vote


@pytest.mark.parametrize("bad", [
    "not a dict", [], {},
    macro_input(52, provider_status="AVAILABLE_ISH"),
    macro_input(52, ten_year_change_bp=True), macro_input(52, ten_year_change_bp=52.0),
    macro_input(52, ten_year_change_bp=None), macro_input(52, ten_year_change_bp=3001),
    macro_input(52, curve_spread_bp=False), macro_input(52, curve_spread_bp=-3001),
    macro_input(52, move="UP"), macro_input(52, move=None), macro_input(52, observed_date=None),
    # Audit F-2: a label that contradicts its own number, and a bad date.
    macro_input(100, move="FALLING"), macro_input(-2000, move="FLAT"),
    macro_input(24, move="RISING"), macro_input(-25, move="FLAT"),
    macro_input(52, observed_date="garbage"), macro_input(52, observed_date="2026-9-24"),
    macro_input(52, observed_date="2026-02-30"),
])
def test_malformed_macro_input_is_rejected_without_a_score(bad):
    data = build(macro=bad)
    assert data["evidence_status"]["macro"] == Status.REJECTED_MALFORMED.value
    assert "macro_score" not in data
    assert data["macro_evidence"] == {"reason": "MALFORMED_MACRO_INPUT"}


@pytest.mark.parametrize("bad", [
    "not a dict", {},
    risk_input("HIGH", 3.0, regime="NEUTRAL"),          # label contradicts numbers
    risk_input("LOW", 0.5, regime="HIGH"),
    risk_input("NEUTRAL", 1.5, regime="LOW"),
    risk_input("HIGH", 3.0, realized_volatility=float("nan")),
    risk_input("HIGH", 3.0, realized_volatility=float("inf")),
    risk_input("HIGH", 3.0, realized_volatility=True),
    risk_input("LOW", 0.5, realized_volatility=-0.5),
    risk_input("NEUTRAL", 1.5, p20=3.0),                 # p20 > p80
    risk_input("NEUTRAL", 1.5, p80=None),
    risk_input("NEUTRAL", 1.5, reference_windows=0),
    risk_input("NEUTRAL", 1.5, reference_windows=True),
    risk_input("NEUTRAL", 1.5, regime="EXTREME"),
    risk_input("NEUTRAL", 1.5, provider_status="MAYBE"),
])
def test_malformed_market_risk_input_is_rejected_without_a_score(bad):
    data = build(risk=bad)
    assert data["evidence_status"]["market_risk"] == Status.REJECTED_MALFORMED.value
    assert "risk_score" not in data
    assert data["market_risk_evidence"] == {"reason": "MALFORMED_MARKET_RISK_INPUT"}


def test_provider_error_input_is_never_scored_even_with_values_attached():
    data = build(
        macro=macro_input(52, provider_status="UNAVAILABLE_PROVIDER_ERROR", reason="STALE"),
        risk=risk_input("HIGH", 3.0, provider_status="UNAVAILABLE_PROVIDER_ERROR",
                        reason="CANDLE_GAP"))
    assert data["evidence_status"]["macro"] == Status.UNAVAILABLE_PROVIDER_ERROR.value
    assert data["evidence_status"]["market_risk"] == Status.UNAVAILABLE_PROVIDER_ERROR.value
    assert "macro_score" not in data and "risk_score" not in data
    assert data["macro_evidence"]["reason"] == "STALE" and data["macro_evidence"]["vote"] is None
    assert data["market_risk_evidence"]["reason"] == "CANDLE_GAP"


def test_no_inputs_keep_both_slots_exactly_as_before():
    data = build()
    assert data["evidence_status"]["macro"] == Status.UNAVAILABLE_NO_PROVIDER.value
    assert data["evidence_status"]["market_risk"] == Status.UNAVAILABLE_NO_PROVIDER.value
    for key in ("macro_score", "risk_score", "macro_evidence", "market_risk_evidence"):
        assert key not in data


def test_audit_keys_do_not_collide_with_reasoning_adapter_inputs():
    data = build(macro=macro_input(52), risk=risk_input("HIGH", 3.0))
    assert not {"fed_policy", "inflation", "fear_greed", "macd"} & set(data)


# ---------------------------------------------------------------------------
# AgentFusion across every active/excluded combination (real pipeline)
# ---------------------------------------------------------------------------


COMBINATIONS = list(itertools.product(
    [None, "FEAR", "NEUTRAL", "ERROR"],
    [None, "RISING", "FALLING", "FALLING_INVERTED", "FLAT", "ERROR"],
    [None, "HIGH", "NEUTRAL", "LOW", "ERROR"],
    [True, False],
))


@pytest.mark.parametrize(("sentiment", "macro", "risk", "rising"), COMBINATIONS)
def test_every_roster_combination_flows_through_unchanged_fusion(sentiment, macro, risk, rising):
    brain = run_loop(
        sentiment=stub(SENTIMENT_READINGS, StubMacro, sentiment),
        macro=stub(MACRO_READINGS, StubMacro, macro),
        risk=stub(RISK_READINGS, StubRisk, risk),
        rising=rising,
    )
    signals, result = brain.signals[0], brain.results[0]

    expected = {"technical", "momentum"}
    expected |= {"sentiment"} if SENTIMENT_ACTIVE[sentiment] else set()
    expected |= {"macro"} if MACRO_ACTIVE[macro] else set()
    expected |= {"risk"} if RISK_ACTIVE[risk] else set()
    assert set(signals) == expected

    if len(expected) < AgentFusion.MIN_PARTICIPATING_AGENTS:
        assert (result.action, result.confidence, result.reason) == (
            "HOLD", 0.0, "INSUFFICIENT_EVIDENCE")
    else:
        assert result.reason != "INSUFFICIENT_EVIDENCE"

    # NB-5: the whole configured roster is the denominator, so confidence
    # can never exceed the participating share of configured weight - and
    # is below 1.0 whenever any of the five agents is missing.
    coverage = sum(AgentFusion.WEIGHTS[name] for name in expected)
    assert 0.0 <= result.confidence <= round(coverage, 4)
    if len(expected) < len(AgentFusion.WEIGHTS):
        assert result.confidence < 1.0


def test_the_roster_is_still_five_and_the_floor_still_three():
    assert set(AgentFusion.WEIGHTS) == {"technical", "momentum", "risk", "macro", "sentiment"}
    assert AgentFusion.MIN_PARTICIPATING_AGENTS == 3
    assert AgentFusion.AGENT_EVIDENCE_STATUS_KEYS["risk"] == "market_risk"
    assert AgentFusion.AGENT_SCORE_KEYS == {"technical": "technical_score",
                                            "macro": "macro_score",
                                            "sentiment": "sentiment_score",
                                            "risk": "risk_score"}


# ---------------------------------------------------------------------------
# NB-4: removing any evidence never raises confidence (2..5 agents)
# ---------------------------------------------------------------------------


SENTIMENT_INPUTS = {
    "FEAR": {"provider_status": "AVAILABLE", "value": 10, "band": "FEAR", "reason": "OK"},
    "GREED": {"provider_status": "AVAILABLE", "value": 80, "band": "GREED", "reason": "OK"},
}
MACRO_INPUTS = {name: macro_input(change, spread) for name, (change, spread) in {
    "RISING": (52, 31), "FALLING": (-40, 31), "FALLING_INVERTED": (-40, -20),
    "FLAT": (0, 31)}.items()}
RISK_INPUTS = {"HIGH": risk_input("HIGH", 3.0), "NEUTRAL": risk_input("NEUTRAL", 1.5),
               "LOW": risk_input("LOW", 0.5)}
MACRO_ERROR_INPUT = {**MACRO_ERROR, "reason": "STALE"}
RISK_ERROR_INPUT = {**RISK_ERROR, "reason": "INSUFFICIENT_HISTORY"}

RSI_CLASSES = (20, 32, 38, 50, 65, 80)
TRENDS = ("BULLISH", "BEARISH", "NEUTRAL")


@pytest.mark.parametrize("macro", sorted(MACRO_INPUTS))
@pytest.mark.parametrize("risk", sorted(RISK_INPUTS))
def test_removing_any_subset_of_agents_never_raises_confidence_nb4(macro, risk):
    checked = 0
    for rsi, trend, sentiment in itertools.product(
            RSI_CLASSES, TRENDS, [None, *sorted(SENTIMENT_INPUTS)]):
        full_inputs = {
            "sentiment": SENTIMENT_INPUTS.get(sentiment),
            "macro": MACRO_INPUTS[macro],
            "risk": RISK_INPUTS[risk],
        }
        _, full = fuse_market_data(build(full_inputs["macro"], full_inputs["risk"],
                                         full_inputs["sentiment"], rsi=rsi, trend=trend))

        for size in range(1, 4):
            for removed in itertools.combinations(full_inputs, size):
                reduced = {k: (None if k in removed else v) for k, v in full_inputs.items()}
                _, result = fuse_market_data(build(reduced["macro"], reduced["risk"],
                                                   reduced["sentiment"], rsi=rsi, trend=trend))
                assert result.confidence <= full.confidence, (
                    rsi, trend, sentiment, macro, risk, removed, full, result)
                checked += 1
    assert checked == len(RSI_CLASSES) * len(TRENDS) * 3 * 7


@pytest.mark.parametrize("macro", sorted(MACRO_INPUTS))
@pytest.mark.parametrize("risk", sorted(RISK_INPUTS))
def test_a_failed_provider_is_exactly_as_conservative_as_no_provider(macro, risk):
    for rsi, trend in itertools.product(RSI_CLASSES, TRENDS):
        absent = fuse_market_data(build(None, None, rsi=rsi, trend=trend))[1]
        failed = fuse_market_data(build(MACRO_ERROR_INPUT, RISK_ERROR_INPUT,
                                        rsi=rsi, trend=trend))[1]
        assert (failed.action, failed.confidence) == (absent.action, absent.confidence)

        macro_failed = fuse_market_data(build(MACRO_ERROR_INPUT, RISK_INPUTS[risk],
                                              rsi=rsi, trend=trend))[1]
        macro_absent = fuse_market_data(build(None, RISK_INPUTS[risk], rsi=rsi, trend=trend))[1]
        assert macro_failed.confidence == macro_absent.confidence

        risk_failed = fuse_market_data(build(MACRO_INPUTS[macro], RISK_ERROR_INPUT,
                                             rsi=rsi, trend=trend))[1]
        risk_absent = fuse_market_data(build(MACRO_INPUTS[macro], None, rsi=rsi, trend=trend))[1]
        assert risk_failed.confidence == risk_absent.confidence


def test_malformed_inputs_never_raise_confidence_over_absence():
    for rsi, trend in itertools.product(RSI_CLASSES, TRENDS):
        absent = fuse_market_data(build(None, None, rsi=rsi, trend=trend))[1]
        malformed = fuse_market_data(build(
            macro_input(52, ten_year_change_bp=True), risk_input("HIGH", 3.0, regime="LOW"),
            rsi=rsi, trend=trend))[1]
        assert malformed.confidence == absent.confidence


# ---------------------------------------------------------------------------
# NB-5: expected-roster denominator with 3, 4 and 5 agents
# ---------------------------------------------------------------------------


EXTRA_AGENTS = ("risk", "macro", "sentiment")


@pytest.mark.parametrize("extras", [
    extras for size in range(0, 4) for extras in itertools.combinations(EXTRA_AGENTS, size)])
def test_unanimous_maximal_conviction_is_capped_by_roster_coverage_nb5(extras):
    participants = ("technical", "momentum", *extras)
    signals = {name: {"action": "BUY", "score": 1.0} for name in participants}

    with contextlib.redirect_stdout(io.StringIO()):
        result = AgentFusion().fuse(signals)

    if len(participants) < 3:
        assert result.reason == "INSUFFICIENT_EVIDENCE" and result.confidence == 0.0
        return

    coverage = round(sum(AgentFusion.WEIGHTS[name] for name in participants), 4)
    assert result.action == "BUY"
    assert result.confidence == coverage
    assert (result.confidence == 1.0) == (len(participants) == 5)


@pytest.mark.parametrize("extras", [
    extras for size in range(1, 4) for extras in itertools.combinations(EXTRA_AGENTS, size)])
def test_hold_votes_never_produce_full_consensus_nb5(extras):
    signals = {"technical": {"action": "BUY", "score": 1.0},
               "momentum": {"action": "BUY", "score": 1.0}}
    signals |= {name: {"action": "HOLD", "score": 0.5} for name in extras}

    with contextlib.redirect_stdout(io.StringIO()):
        result = AgentFusion().fuse(signals)

    assert result.confidence < 1.0
    assert result.confidence <= 0.60 / (0.60 + 0.5 * sum(
        AgentFusion.WEIGHTS[name] for name in extras) + sum(
        AgentFusion.WEIGHTS[name] for name in EXTRA_AGENTS if name not in extras)) + 1e-4


# ---------------------------------------------------------------------------
# Disclosed, owner-accepted consequences (registry v4.79)
# ---------------------------------------------------------------------------


def test_neutral_macro_and_risk_unlock_technical_momentum_eligibility_as_disclosed():
    """Owner decision 2026-09-25: neutral zones vote a participating HOLD.

    With sentiment withholding, a FLAT macro and a NEUTRAL volatility regime
    lift participation from 2 to 4, so technical+momentum alone can now
    clear ExecutionManager.MIN_CONFIDENCE in PAPER. Pinned so any drift is
    noticed; the pre-change 2-agent baseline is pinned alongside it.
    """

    _, before = fuse_market_data(build(None, None, rsi=50, trend="BULLISH"))
    _, after = fuse_market_data(build(MACRO_INPUTS["FLAT"], RISK_INPUTS["NEUTRAL"],
                                      rsi=50, trend="BULLISH"))

    assert (before.action, before.confidence, before.reason) == (
        "HOLD", 0.0, "INSUFFICIENT_EVIDENCE")
    assert (after.action, after.confidence) == ("BUY", 0.6575)
    assert after.confidence * 100 >= ELIGIBLE


def test_high_volatility_never_raises_directional_confidence_over_neutral():
    for rsi, trend, macro in itertools.product(RSI_CLASSES, TRENDS, sorted(MACRO_INPUTS)):
        neutral = fuse_market_data(build(MACRO_INPUTS[macro], RISK_INPUTS["NEUTRAL"],
                                         rsi=rsi, trend=trend))[1]
        high = fuse_market_data(build(MACRO_INPUTS[macro], RISK_INPUTS["HIGH"],
                                      rsi=rsi, trend=trend))[1]
        if neutral.action == "BUY" and high.action == "BUY":
            assert high.confidence <= neutral.confidence, (rsi, trend, macro)


def test_rising_yields_never_raise_buy_confidence_over_flat():
    for rsi, trend, risk in itertools.product(RSI_CLASSES, TRENDS, sorted(RISK_INPUTS)):
        flat = fuse_market_data(build(MACRO_INPUTS["FLAT"], RISK_INPUTS[risk],
                                      rsi=rsi, trend=trend))[1]
        rising = fuse_market_data(build(MACRO_INPUTS["RISING"], RISK_INPUTS[risk],
                                        rsi=rsi, trend=trend))[1]
        if flat.action == "BUY" and rising.action == "BUY":
            assert rising.confidence <= flat.confidence, (rsi, trend, risk)
