"""Finding S-1: numeric accuracy of the live indicator layer.

STAGE1-PAPER-001 Item 1 (signal correctness) records that the indicator
layer which produces ``rsi`` and ``trend`` has no numerical assertion
anywhere in the suite - its only test contact is
``tests/phase6/test_market_loop_integration.py:155``,
``self.assertIsNotNone(result)``. Every downstream guard (fusion, the
participation floor, the confidence ladder, the risk engine) consumes
those values as *given*, so a systematically wrong indicator produces a
confident, well-formed, risk-approved wrong decision that every safety
layer passes.

This module closes that gap. It does not replace the existing smoke
test, which stays as it is; it adds the numeric assertions that were
missing.

WHICH MODULE IS UNDER TEST, AND WHY
-----------------------------------
``core/technical_analyzer.py`` is the indicator implementation inside the
runtime closure (``packaging/atlas_runtime_closure.json`` lists exactly
that path; ``analysis/technical_analyzer.py`` and
``ai/core/atlas_multi_agent.py`` are not in the closure). It is
instantiated once at ``core/market_loop.py:147`` and called at
``core/market_loop.py:589``. The fields the decision path actually
consumes are ``rsi`` and ``trend`` - see
``MarketLoop.calculate_score()`` at ``core/market_loop.py:1755``, which
reads those two keys and nothing else. ``trend`` is derived from EMA20
against EMA50. The full ``analyze()`` surface is covered here anyway,
since the other fields travel with the analysis dict.

There is deliberately no MACD or ATR test: no ``def macd``/``def atr``
exists in ``core/``, ``analysis/`` or ``ai/`` at all. The only such
implementation in the repository is ``strategy/strategy_base.py``, which
STAGE1-PAPER-001 records as outside the runtime closure.

REFERENCE VALUES AND TOLERANCE
------------------------------
Expected values are either hand-computed literals (the arithmetic is
written out in the test that uses them) or produced by the independent
reference implementations at the top of this module, which are written
from the textbook definitions rather than adapted from the production
code.

RSI convention: ``TechnicalAnalyzer.rsi()`` averages the last ``period``
gains and losses with a *simple* mean. That is Cutler's RSI, not
Wilder's smoothed RSI. STAGE1-PAPER-001 records "which RSI convention is
canonical" as an open question for the owner, so these tests pin the
convention the code actually implements and prove it is distinguishable
from Wilder - they do not change it.

TOLERANCE is 1e-9 throughout. The implementation rounds its outputs (RSI
to 2 decimals, EMA to 4, volatility and momentum to 3), so the expected
values are exact under that rounding and the only slack needed is IEEE
754 representation noise. A wider tolerance would let a real error hide.

These tests are offline and purely in-memory: they construct no runtime,
open no socket, and touch no state directory.
"""

from __future__ import annotations

import statistics

from typing import Any

import pytest

from core.market_loop import MarketLoop
from core.technical_analyzer import TechnicalAnalyzer


# Exact under the implementation's own rounding; covers float
# representation noise only. See the module docstring.
TOLERANCE = 1e-9


# ---------------------------------------------------------------------------
# Independent reference implementations
#
# Written from the textbook definitions, not adapted from
# core/technical_analyzer.py, so that agreement is evidence rather than
# a tautology.
# ---------------------------------------------------------------------------


def reference_ema(prices: list[float], period: int) -> float:
    """Textbook SMA-seeded EMA.

    Seed with the simple mean of the first ``period`` prices, then apply
    EMA_t = (P_t - EMA_{t-1}) * k + EMA_{t-1} with k = 2 / (period + 1).
    """

    multiplier = 2.0 / (period + 1)
    value = sum(prices[:period]) / period

    for price in prices[period:]:
        value = (price - value) * multiplier + value

    return value


def reference_cutler_rsi(prices: list[float], period: int = 14) -> float:
    """Cutler's RSI: simple (not Wilder-smoothed) averages.

    Average gain and average loss are the arithmetic means of the last
    ``period`` price changes, then RSI = 100 - 100 / (1 + RS).
    """

    gains: list[float] = []
    losses: list[float] = []

    for index in range(1, len(prices)):
        change = prices[index] - prices[index - 1]
        gains.append(max(change, 0.0))
        losses.append(max(-change, 0.0))

    average_gain = sum(gains[-period:]) / period
    average_loss = sum(losses[-period:]) / period

    if average_loss == 0:
        return 100.0

    relative_strength = average_gain / average_loss

    return 100.0 - (100.0 / (1.0 + relative_strength))


def reference_wilder_rsi(prices: list[float], period: int = 14) -> float:
    """Wilder's smoothed RSI - the *other* convention.

    Used only to prove the implementation is distinguishable from
    Wilder. Seed with the mean of the first ``period`` changes, then
    smooth: avg = (avg * (period - 1) + current) / period.
    """

    gains: list[float] = []
    losses: list[float] = []

    for index in range(1, len(prices)):
        change = prices[index] - prices[index - 1]
        gains.append(max(change, 0.0))
        losses.append(max(-change, 0.0))

    average_gain = sum(gains[:period]) / period
    average_loss = sum(losses[:period]) / period

    for index in range(period, len(gains)):
        average_gain = (
            average_gain * (period - 1) + gains[index]
        ) / period
        average_loss = (
            average_loss * (period - 1) + losses[index]
        ) / period

    if average_loss == 0:
        return 100.0

    relative_strength = average_gain / average_loss

    return 100.0 - (100.0 / (1.0 + relative_strength))


# ---------------------------------------------------------------------------
# Fixed input series
# ---------------------------------------------------------------------------


def alternating_series(
    start: float,
    *,
    up: float,
    down: float,
    pairs: int,
) -> list[float]:
    """``1 + 2 * pairs`` prices alternating +up, -down from ``start``."""

    prices = [start]
    value = start

    for _ in range(pairs):
        value += up
        prices.append(value)
        value -= down
        prices.append(value)

    return prices


def candle(
    *,
    open_price: float,
    close_price: float,
    volume: float = 1.0,
) -> dict[str, Any]:
    """Minimal candle in the shape ``TechnicalAnalyzer.analyze()`` reads."""

    return {
        "open": open_price,
        "high": max(open_price, close_price) + 1.0,
        "low": min(open_price, close_price) - 1.0,
        "close": close_price,
        "volume": volume,
    }


def candles_from_closes(closes: list[float]) -> list[dict[str, Any]]:
    """Rising-bar candles whose closes are exactly ``closes``."""

    return [
        candle(open_price=close_price - 0.5, close_price=close_price)
        for close_price in closes
    ]


@pytest.fixture()
def analyzer() -> TechnicalAnalyzer:
    return TechnicalAnalyzer()


# ---------------------------------------------------------------------------
# EMA
# ---------------------------------------------------------------------------


def test_ema_matches_a_hand_computed_golden_vector(
    analyzer: TechnicalAnalyzer,
) -> None:
    """EMA(5) of 1..10 is exactly 8.0.

    Seed = mean(1,2,3,4,5) = 3.0, k = 2/6 = 1/3.
      p=6  -> (6-3)/3 + 3 = 4.0
      p=7  -> (7-4)/3 + 4 = 5.0
      p=8  -> (8-5)/3 + 5 = 6.0
      p=9  -> (9-6)/3 + 6 = 7.0
      p=10 -> (10-7)/3 + 7 = 8.0
    """

    prices = [float(value) for value in range(1, 11)]

    assert analyzer.ema(prices, 5) == pytest.approx(8.0, abs=TOLERANCE)


def test_ema_equals_the_simple_mean_when_length_equals_period(
    analyzer: TechnicalAnalyzer,
) -> None:
    """With no prices past the seed window, EMA is the seed SMA."""

    assert analyzer.ema([2.0, 4.0, 6.0, 8.0], 4) == pytest.approx(
        5.0, abs=TOLERANCE
    )


def test_ema_matches_the_independent_reference_on_a_long_series(
    analyzer: TechnicalAnalyzer,
) -> None:
    """Agreement with the textbook definition over 60 varied prices."""

    prices = [
        100.0 + (index * 1.5) + ((index % 7) * 3.0)
        for index in range(60)
    ]

    for period in (20, 50):
        expected = round(reference_ema(prices, period), 4)

        assert analyzer.ema(prices, period) == pytest.approx(
            expected, abs=TOLERANCE
        )


def test_ema_weights_recent_prices_and_lags_a_step_change(
    analyzer: TechnicalAnalyzer,
) -> None:
    """Two properties that together distinguish an EMA from a mean.

    On an *accelerating* series the recent-weighted average must exceed
    the equal-weighted one, so an implementation that quietly returned
    an SMA would fail. On a step change the EMA must still lag the SMA,
    because the pre-step history is never fully discarded, so an
    implementation that just returned the latest price would fail too.

    Note that a perfectly linear series is deliberately not used here:
    for an arithmetic progression the two averages coincide exactly
    (EMA(10) of 1..30 and mean(21..30) are both 25.5), so a linear
    series cannot discriminate between them at all.
    """

    accelerating = [float(value * value) for value in range(1, 31)]
    stepped = [100.0] * 20 + [200.0] * 10

    accelerating_ema = analyzer.ema(accelerating, 10)
    stepped_ema = analyzer.ema(stepped, 10)

    assert accelerating_ema is not None
    assert stepped_ema is not None

    assert accelerating_ema > sum(accelerating[-10:]) / 10
    assert stepped_ema < sum(stepped[-10:]) / 10


def test_ema_returns_none_when_the_series_is_shorter_than_the_period(
    analyzer: TechnicalAnalyzer,
) -> None:
    """Edge case: insufficient data yields None, never a partial value."""

    assert analyzer.ema([1.0, 2.0, 3.0], 5) is None
    assert analyzer.ema([], 5) is None
    # Boundary: exactly `period` prices is enough.
    assert analyzer.ema([1.0, 2.0, 3.0, 4.0, 5.0], 5) is not None


# ---------------------------------------------------------------------------
# RSI
# ---------------------------------------------------------------------------


def test_rsi_of_a_symmetric_alternating_series_is_fifty(
    analyzer: TechnicalAnalyzer,
) -> None:
    """Seven +1 changes and seven -1 changes give RS = 1, so RSI = 50.

    avg_gain = 7/14 = 0.5, avg_loss = 7/14 = 0.5, RS = 1,
    RSI = 100 - 100/2 = 50.
    """

    prices = alternating_series(100.0, up=1.0, down=1.0, pairs=7)

    assert len(prices) == 15

    assert analyzer.rsi(prices) == pytest.approx(50.0, abs=TOLERANCE)


def test_rsi_two_up_one_down_golden_vector(
    analyzer: TechnicalAnalyzer,
) -> None:
    """Seven +2 changes and seven -1 changes give RSI = 66.67.

    avg_gain = 14/14 = 1.0, avg_loss = 7/14 = 0.5, RS = 2,
    RSI = 100 - 100/3 = 66.6666..., rounded to 66.67.
    """

    prices = alternating_series(100.0, up=2.0, down=1.0, pairs=7)

    assert len(prices) == 15

    assert analyzer.rsi(prices) == pytest.approx(66.67, abs=TOLERANCE)


def test_rsi_of_a_strictly_falling_series_is_zero(
    analyzer: TechnicalAnalyzer,
) -> None:
    """No gains at all: RS = 0, RSI = 100 - 100/1 = 0."""

    prices = [100.0 - index for index in range(15)]

    assert analyzer.rsi(prices) == pytest.approx(0.0, abs=TOLERANCE)


def test_rsi_of_a_strictly_rising_series_is_one_hundred(
    analyzer: TechnicalAnalyzer,
) -> None:
    """Zero average loss short-circuits to 100 rather than dividing."""

    prices = [100.0 + index for index in range(15)]

    assert analyzer.rsi(prices) == 100


def test_rsi_of_a_perfectly_flat_series_is_one_hundred(
    analyzer: TechnicalAnalyzer,
) -> None:
    """Edge case, pinned deliberately rather than asserted as desirable.

    Every change is zero, so average loss is zero and the implementation
    takes the same short-circuit as an all-gains series, reporting 100 -
    the "overbought" end of the scale - for a market that has not moved
    at all.

    This is the conventional behaviour of a zero-loss RSI and it is
    conservative where it matters: at ``core/market_loop.py:1793`` an RSI
    above 70 *subtracts* 0.10 from the market quality score, so a flat
    feed scores lower, not higher. It is recorded here so the behaviour
    is visible and cannot change silently. Whether a flat series should
    instead report 50 is an owner decision, not something this test
    asserts.
    """

    prices = [100.0] * 20

    assert analyzer.rsi(prices) == 100


def test_rsi_uses_only_the_most_recent_period_changes(
    analyzer: TechnicalAnalyzer,
) -> None:
    """A violent early history must not leak into a 14-period RSI.

    The series climbs by +50 twenty-five times, then alternates +1/-1
    fourteen times. Only the alternating tail is inside the window, so
    the answer is 50.0 - the same as if the climb had never happened.
    An implementation that averaged over the whole series, or that took
    the wrong slice, would report a near-100 value here.
    """

    prices = [100.0]
    value = 100.0

    for _ in range(25):
        value += 50.0
        prices.append(value)

    for _ in range(7):
        value += 1.0
        prices.append(value)
        value -= 1.0
        prices.append(value)

    assert len(prices) == 40

    assert analyzer.rsi(prices) == pytest.approx(50.0, abs=TOLERANCE)


def test_rsi_follows_cutlers_simple_average_not_wilder_smoothing(
    analyzer: TechnicalAnalyzer,
) -> None:
    """Pin the convention the implementation actually uses.

    On a series whose early history is extreme, Cutler's RSI (simple
    mean of the last 14 changes) and Wilder's RSI (exponentially
    smoothed from the first 14 changes) diverge sharply, because Wilder
    carries the early history forward forever. The implementation must
    match Cutler and must be far from Wilder.

    STAGE1-PAPER-001 records the choice between the two as an open
    question for the owner. This test does not answer it; it makes the
    current answer explicit, so that switching conventions becomes a
    deliberate, visible change rather than a silent one.
    """

    prices = [100.0]
    value = 100.0

    for _ in range(25):
        value += 50.0
        prices.append(value)

    for _ in range(7):
        value += 1.0
        prices.append(value)
        value -= 1.0
        prices.append(value)

    actual = analyzer.rsi(prices)
    cutler = round(reference_cutler_rsi(prices), 2)
    wilder = reference_wilder_rsi(prices)

    assert actual == pytest.approx(cutler, abs=TOLERANCE)
    assert wilder > 90.0
    assert abs(actual - wilder) > 10.0


def test_rsi_matches_the_independent_reference_on_a_varied_series(
    analyzer: TechnicalAnalyzer,
) -> None:
    """Agreement with the Cutler reference over a longer mixed series."""

    prices = [
        100.0
        + ((index % 5) * 2.5)
        - ((index % 3) * 1.75)
        + (index * 0.4)
        for index in range(80)
    ]

    expected = round(reference_cutler_rsi(prices), 2)

    assert analyzer.rsi(prices) == pytest.approx(expected, abs=TOLERANCE)


def test_rsi_returns_none_below_its_minimum_history(
    analyzer: TechnicalAnalyzer,
) -> None:
    """Edge case and boundary: 14 prices is too few, 15 is enough."""

    fourteen = [100.0 + index for index in range(14)]
    fifteen = [100.0 + index for index in range(15)]

    assert analyzer.rsi(fourteen) is None
    assert analyzer.rsi(fifteen) is not None
    assert analyzer.rsi([]) is None


# ---------------------------------------------------------------------------
# Volatility
# ---------------------------------------------------------------------------


def test_volatility_measures_returns_not_price_level(
    analyzer: TechnicalAnalyzer,
) -> None:
    """Constant *growth rate* means zero return volatility.

    Prices compound at exactly 10% per step, so every simple return is
    0.1 and their standard deviation is zero - even though the prices
    themselves span a wide range. An implementation that took the
    standard deviation of prices rather than of returns would report a
    large number here.
    """

    prices = [100.0 * (1.1**index) for index in range(12)]

    assert analyzer.volatility(prices) == pytest.approx(
        0.0, abs=TOLERANCE
    )


def test_volatility_matches_the_textbook_definition(
    analyzer: TechnicalAnalyzer,
) -> None:
    """Sample standard deviation of simple returns, expressed in percent."""

    prices = [
        100.0 + ((index % 4) * 3.0) + (index * 0.75)
        for index in range(15)
    ]

    returns = [
        (prices[index] - prices[index - 1]) / prices[index - 1]
        for index in range(1, len(prices))
    ]

    expected = round(statistics.stdev(returns) * 100, 3)

    assert analyzer.volatility(prices) == pytest.approx(
        expected, abs=TOLERANCE
    )


def test_volatility_returns_zero_below_its_minimum_history(
    analyzer: TechnicalAnalyzer,
) -> None:
    """Edge case: fewer than 10 prices yields 0, never an exception."""

    assert analyzer.volatility([100.0] * 9) == 0
    assert analyzer.volatility([]) == 0


# ---------------------------------------------------------------------------
# Momentum
# ---------------------------------------------------------------------------


def test_momentum_golden_vector(
    analyzer: TechnicalAnalyzer,
) -> None:
    """Percent change from the 10th-from-last price to the last.

    Prices are 100..110. prices[-1] = 110, prices[-10] = 101, so
    (110 - 101) / 101 * 100 = 8.910891..., rounded to 8.911.
    """

    prices = [float(value) for value in range(100, 111)]

    assert analyzer.momentum(prices) == pytest.approx(
        8.911, abs=TOLERANCE
    )


def test_momentum_is_negative_on_a_falling_series(
    analyzer: TechnicalAnalyzer,
) -> None:
    """Sign convention: a decline reports a negative momentum."""

    prices = [float(value) for value in range(110, 99, -1)]

    momentum = analyzer.momentum(prices)

    assert momentum < 0
    assert momentum == pytest.approx(
        round((100.0 - 109.0) / 109.0 * 100, 3), abs=TOLERANCE
    )


def test_momentum_returns_zero_below_its_minimum_history(
    analyzer: TechnicalAnalyzer,
) -> None:
    """Edge case: fewer prices than the period yields 0."""

    assert analyzer.momentum([100.0] * 9) == 0
    assert analyzer.momentum([]) == 0


# ---------------------------------------------------------------------------
# Volume pressure
# ---------------------------------------------------------------------------


def test_volume_pressure_is_one_when_every_recent_candle_closed_up(
    analyzer: TechnicalAnalyzer,
) -> None:
    candles = [
        candle(open_price=100.0, close_price=101.0, volume=1.0)
        for _ in range(10)
    ]

    assert analyzer.volume_pressure(candles) == pytest.approx(
        1.0, abs=TOLERANCE
    )


def test_volume_pressure_is_minus_one_when_every_recent_candle_closed_down(
    analyzer: TechnicalAnalyzer,
) -> None:
    candles = [
        candle(open_price=101.0, close_price=100.0, volume=1.0)
        for _ in range(10)
    ]

    assert analyzer.volume_pressure(candles) == pytest.approx(
        -1.0, abs=TOLERANCE
    )


def test_volume_pressure_is_volume_weighted_not_candle_counted(
    analyzer: TechnicalAnalyzer,
) -> None:
    """Two heavy up-candles must outweigh eight light down-candles.

    up = 2 * 40 = 80, down = 8 * 1 = 8, total = 88,
    (80 - 8) / 88 = 0.81818..., rounded to 0.818. A count-based
    implementation would report a negative number instead.
    """

    candles = [
        candle(open_price=100.0, close_price=101.0, volume=40.0)
        for _ in range(2)
    ] + [
        candle(open_price=101.0, close_price=100.0, volume=1.0)
        for _ in range(8)
    ]

    assert analyzer.volume_pressure(candles) == pytest.approx(
        0.818, abs=TOLERANCE
    )


def test_volume_pressure_uses_only_the_last_ten_candles(
    analyzer: TechnicalAnalyzer,
) -> None:
    """Older candles are outside the window and must not contribute."""

    candles = [
        candle(open_price=100.0, close_price=101.0, volume=500.0)
        for _ in range(30)
    ] + [
        candle(open_price=101.0, close_price=100.0, volume=1.0)
        for _ in range(10)
    ]

    assert analyzer.volume_pressure(candles) == pytest.approx(
        -1.0, abs=TOLERANCE
    )


def test_volume_pressure_counts_an_unchanged_close_as_downward(
    analyzer: TechnicalAnalyzer,
) -> None:
    """Edge case pinned, not endorsed.

    The implementation tests ``close > open`` and treats everything else
    - including an exactly unchanged candle - as down-volume. A doji
    therefore reads as selling pressure. Recorded so the asymmetry is
    visible; whether it should be neutral is an owner decision.
    """

    candles = [
        candle(open_price=100.0, close_price=100.0, volume=1.0)
        for _ in range(10)
    ]

    assert analyzer.volume_pressure(candles) == pytest.approx(
        -1.0, abs=TOLERANCE
    )


def test_volume_pressure_handles_zero_total_volume(
    analyzer: TechnicalAnalyzer,
) -> None:
    """Edge case: no volume at all yields 0 rather than dividing by zero."""

    candles = [
        candle(open_price=100.0, close_price=101.0, volume=0.0)
        for _ in range(10)
    ]

    assert analyzer.volume_pressure(candles) == 0


def test_volume_pressure_returns_zero_below_its_minimum_history(
    analyzer: TechnicalAnalyzer,
) -> None:
    assert analyzer.volume_pressure([]) == 0
    assert (
        analyzer.volume_pressure(
            [candle(open_price=100.0, close_price=101.0)] * 9
        )
        == 0
    )


# ---------------------------------------------------------------------------
# analyze() - the function the market loop actually calls
# ---------------------------------------------------------------------------


def test_analyze_returns_an_empty_dict_for_no_candles(
    analyzer: TechnicalAnalyzer,
) -> None:
    """Edge case: the loop's ``isinstance(analysis, dict)`` guard sees {}."""

    assert analyzer.analyze([]) == {}


def test_analyze_reports_bullish_when_ema20_exceeds_ema50(
    analyzer: TechnicalAnalyzer,
) -> None:
    """A rising series puts the fast average above the slow one."""

    closes = [100.0 + (index * 2.0) for index in range(60)]
    analysis = analyzer.analyze(candles_from_closes(closes))

    assert analysis["ema20"] > analysis["ema50"]
    assert analysis["trend"] == "BULLISH"


def test_analyze_reports_bearish_when_ema20_falls_below_ema50(
    analyzer: TechnicalAnalyzer,
) -> None:
    closes = [220.0 - (index * 2.0) for index in range(60)]
    analysis = analyzer.analyze(candles_from_closes(closes))

    assert analysis["ema20"] < analysis["ema50"]
    assert analysis["trend"] == "BEARISH"


def test_analyze_reports_neutral_when_ema50_is_unavailable(
    analyzer: TechnicalAnalyzer,
) -> None:
    """Edge case: under 50 candles there is no slow average to compare."""

    closes = [100.0 + (index * 2.0) for index in range(30)]
    analysis = analyzer.analyze(candles_from_closes(closes))

    assert analysis["ema50"] is None
    assert analysis["trend"] == "NEUTRAL"


def test_analyze_fields_agree_with_the_direct_indicator_calls(
    analyzer: TechnicalAnalyzer,
) -> None:
    """analyze() must report the same numbers the indicators produce."""

    closes = [
        100.0 + ((index % 6) * 2.0) + (index * 0.5)
        for index in range(60)
    ]
    candles = candles_from_closes(closes)
    analysis = analyzer.analyze(candles)

    assert analysis["ema20"] == analyzer.ema(closes, 20)
    assert analysis["ema50"] == analyzer.ema(closes, 50)
    assert analysis["rsi"] == analyzer.rsi(closes)
    assert analysis["volatility"] == analyzer.volatility(closes)
    assert analysis["momentum"] == analyzer.momentum(closes)
    assert analysis["volume_pressure"] == analyzer.volume_pressure(
        candles
    )
    assert analysis["last_close"] == closes[-1]


# ---------------------------------------------------------------------------
# Indicator output -> the value the decision path actually scores
# ---------------------------------------------------------------------------


def test_indicator_output_drives_the_market_quality_score(
    analyzer: TechnicalAnalyzer,
) -> None:
    """End-to-end from candles to the score the decision path consumes.

    ``MarketLoop.calculate_score()`` (``core/market_loop.py:1755``) is
    the only consumer of the indicator dict, and it reads exactly two
    fields. The series below is built so both are independently
    derivable:

    - 45 strongly rising closes put EMA20 above EMA50, so trend is
      BULLISH, worth +0.20.
    - the last 14 changes alternate +1/-1, so RSI is 50.0, which lands
      in the 40..60 band worth +0.15.

    From the base of 0.5 the score is therefore 0.5 + 0.15 + 0.20 =
    0.85, derived from calculate_score()'s stated rules rather than
    read off a previous run.
    """

    closes = [100.0]
    value = 100.0

    for _ in range(45):
        value += 5.0
        closes.append(value)

    for _ in range(7):
        value += 1.0
        closes.append(value)
        value -= 1.0
        closes.append(value)

    analysis = analyzer.analyze(candles_from_closes(closes))

    assert analysis["rsi"] == pytest.approx(50.0, abs=TOLERANCE)
    assert analysis["trend"] == "BULLISH"

    assert MarketLoop.calculate_score(analysis) == pytest.approx(
        0.85, abs=TOLERANCE
    )


def test_market_quality_score_penalises_an_overbought_reading(
    analyzer: TechnicalAnalyzer,
) -> None:
    """A strictly rising series reads RSI 100 and loses the 0.10 penalty.

    trend is BULLISH (+0.20) and RSI is above 70 (-0.10), so the score
    is 0.5 + 0.20 - 0.10 = 0.60.
    """

    closes = [100.0 + (index * 3.0) for index in range(60)]
    analysis = analyzer.analyze(candles_from_closes(closes))

    assert analysis["rsi"] == 100
    assert analysis["trend"] == "BULLISH"

    assert MarketLoop.calculate_score(analysis) == pytest.approx(
        0.60, abs=TOLERANCE
    )
