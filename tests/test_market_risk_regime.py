"""Registry v4.79: MarketRiskRegimeProvider - realized-volatility three-zone regime.

Pure computation over candles; no I/O. The percentile check below is an
independent re-implementation (sorted order statistics with linear
interpolation), not a call back into the code under test.
"""

from __future__ import annotations

import ast
import inspect
import math
import random

import pytest

import core.market_risk_regime as module
from core.market_risk_regime import (
    MIN_CLOSED_CANDLES,
    MIN_REFERENCE_WINDOWS,
    REASON_CANDLE_GAP,
    REASON_INSUFFICIENT_HISTORY,
    REASON_MALFORMED_CANDLES,
    REASON_OK,
    REASON_UNEXPECTED_ERROR,
    REGIME_HIGH,
    REGIME_LOW,
    REGIME_NEUTRAL,
    WINDOW_RETURNS,
    MarketRiskRegimeProvider,
    classify_volatility_regime,
)


START_MS = 1_700_000_000_000


def candles_from(closes, *, spacing=60_000):
    return [{"open_time": START_MS + index * spacing, "close": close, "is_closed": True}
            for index, close in enumerate(closes)]


def walk(count, *, seed=7, sigma=0.001, start=100.0):
    rng = random.Random(seed)
    closes, price = [], start
    for _ in range(count):
        closes.append(price)
        price *= math.exp(rng.gauss(0.0, sigma))
    return closes


def assess(closes):
    return MarketRiskRegimeProvider().assess(candles_from(closes))


def independent_percentile(values, fraction):
    ordered = sorted(values)
    position = fraction * (len(ordered) - 1)
    low = math.floor(position)
    high = min(low + 1, len(ordered) - 1)
    return ordered[low] + (ordered[high] - ordered[low]) * (position - low)


def independent_volatilities(closes):
    returns = [math.log(b / a) for a, b in zip(closes, closes[1:])]
    return [math.sqrt(sum(r * r for r in returns[end - WINDOW_RETURNS:end]) / WINDOW_RETURNS)
            for end in range(WINDOW_RETURNS, len(returns) + 1)]


# ---------------------------------------------------------------------------
# Regime boundaries
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(("current", "regime"), [
    (0.0, REGIME_LOW), (0.99, REGIME_LOW), (1.0, REGIME_NEUTRAL), (2.0, REGIME_NEUTRAL),
    (3.0, REGIME_NEUTRAL), (3.01, REGIME_HIGH),
])
def test_three_zone_split_is_strict_at_both_edges(current, regime):
    assert classify_volatility_regime(current, 1.0, 3.0) == regime


def test_flat_market_is_neutral_not_low_or_high():
    assert classify_volatility_regime(0.0, 0.0, 0.0) == REGIME_NEUTRAL


@pytest.mark.parametrize("bad", [
    (float("nan"), 1.0, 2.0), (1.0, float("inf"), 2.0), (-0.1, 0.0, 1.0),
    (True, 0.0, 1.0), ("1", 0.0, 1.0), (None, 0.0, 1.0), (1.0, 3.0, 2.0),
])
def test_classifier_refuses_bad_inputs(bad):
    with pytest.raises(ValueError):
        classify_volatility_regime(*bad)


# ---------------------------------------------------------------------------
# Assessment
# ---------------------------------------------------------------------------


def test_matches_an_independent_computation():
    closes = walk(200)
    reading = assess(closes)
    volatilities = independent_volatilities(closes)
    reference = volatilities[:-1]

    assert reading.available is True and reading.reason == REASON_OK
    assert reading.reference_windows == len(reference) == 200 - 1 - WINDOW_RETURNS
    assert reading.realized_volatility == pytest.approx(volatilities[-1], rel=1e-12)
    assert reading.p20 == pytest.approx(independent_percentile(reference, 0.2), rel=1e-12)
    assert reading.p80 == pytest.approx(independent_percentile(reference, 0.8), rel=1e-12)


def test_volatility_spike_at_the_end_is_high():
    closes = walk(170, sigma=0.0005)
    closes += walk(30, sigma=0.01, seed=3, start=closes[-1])
    reading = assess(closes)
    assert reading.regime == REGIME_HIGH
    assert reading.realized_volatility > reading.p80


def test_calm_after_turbulence_is_low():
    closes = walk(170, sigma=0.01)
    closes += walk(30, sigma=0.0002, seed=5, start=closes[-1])
    reading = assess(closes)
    assert reading.regime == REGIME_LOW
    assert reading.realized_volatility < reading.p20


def test_steady_market_is_neutral():
    # Alternating +/- the same log move: every window has the same RMS, so
    # the current window sits exactly on both p20 and p80.
    closes = [100.0 * (1.001 if i % 2 else 1.0) for i in range(200)]
    reading = assess(closes)
    assert reading.regime == REGIME_NEUTRAL


def test_constant_price_is_neutral_with_zero_volatility():
    reading = assess([100.0] * 200)
    assert (reading.regime, reading.realized_volatility, reading.p20, reading.p80) == (
        REGIME_NEUTRAL, 0.0, 0.0, 0.0)


def test_direction_does_not_matter_only_magnitude():
    closes = walk(200)
    mirrored = [closes[0] * closes[0] / close for close in closes]
    a, b = assess(closes), assess(mirrored)
    assert a.regime == b.regime
    assert a.realized_volatility == pytest.approx(b.realized_volatility, rel=1e-9)


def test_assessment_is_deterministic():
    closes = walk(200)
    assert assess(closes) == assess(list(closes))


# ---------------------------------------------------------------------------
# Insufficient history
# ---------------------------------------------------------------------------


def test_minimum_history_constants_are_consistent():
    assert MIN_CLOSED_CANDLES == WINDOW_RETURNS + MIN_REFERENCE_WINDOWS + 1 == 131


@pytest.mark.parametrize("count", [0, 1, 2, 31, 100, MIN_CLOSED_CANDLES - 1])
def test_too_little_history_is_excluded_not_guessed(count):
    reading = assess(walk(count))
    assert reading.available is False
    assert reading.reason == REASON_INSUFFICIENT_HISTORY
    assert (reading.regime, reading.realized_volatility, reading.p20, reading.p80,
            reading.reference_windows) == (None,) * 5


def test_exactly_the_minimum_history_is_assessed():
    reading = assess(walk(MIN_CLOSED_CANDLES))
    assert reading.available is True
    assert reading.reference_windows == MIN_REFERENCE_WINDOWS


# ---------------------------------------------------------------------------
# Malformed candles
# ---------------------------------------------------------------------------


def corrupt(index, **fields):
    candles = candles_from(walk(200))
    candles[index] = {**candles[index], **fields}
    return candles


@pytest.mark.parametrize("candles", [
    corrupt(50, close=0.0), corrupt(50, close=-1.0), corrupt(50, close=float("nan")),
    corrupt(50, close=float("inf")), corrupt(50, close=True), corrupt(50, close="100"),
    corrupt(50, close=None), corrupt(199, open_time=None), corrupt(0, open_time=1.5),
    corrupt(10, open_time=True), corrupt(10, open_time=START_MS + 9 * 60_000),
    corrupt(1, open_time=START_MS),
    candles_from(walk(200))[:-1] + ["not a dict"],
    "not a list", None, {"close": 1.0},
])
def test_malformed_candles_are_excluded(candles):
    reading = MarketRiskRegimeProvider().assess(candles)
    assert reading.available is False
    assert reading.reason in (REASON_MALFORMED_CANDLES, REASON_INSUFFICIENT_HISTORY)
    assert reading.regime is None


def test_a_gap_is_excluded_as_a_gap():
    candles = candles_from(walk(200))
    for index in range(100, 200):
        candles[index] = {**candles[index], "open_time": candles[index]["open_time"] + 60_000}
    reading = MarketRiskRegimeProvider().assess(candles)
    assert reading.reason == REASON_CANDLE_GAP and reading.available is False


def test_an_unexpected_failure_never_escapes(monkeypatch):
    def explode(*args, **kwargs):
        raise ZeroDivisionError("x")

    monkeypatch.setattr(module.statistics, "quantiles", explode)
    reading = assess(walk(200))
    assert reading.available is False and reading.reason == REASON_UNEXPECTED_ERROR


def test_input_candles_are_not_mutated():
    candles = candles_from(walk(200))
    snapshot = [dict(candle) for candle in candles]
    MarketRiskRegimeProvider().assess(candles)
    assert candles == snapshot


# ---------------------------------------------------------------------------
# Boundary: a fusion vote producer, never a risk gate
# ---------------------------------------------------------------------------


def test_module_has_no_path_to_risk_engine_execution_or_io():
    tree = ast.parse(inspect.getsource(module))
    modules = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            modules.add(node.module or "")
    assert modules == {"__future__", "logging", "math", "statistics", "dataclasses", "typing"}
