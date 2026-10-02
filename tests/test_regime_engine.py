"""Regime engine v2 (research): each regime on a constructed series, unknown on too little data."""

from __future__ import annotations

import math

from tools import regime_engine as re_


def series(fn, n=600):
    return [fn(i) for i in range(n)]


def test_steady_uptrend_is_trend_up():
    closes = series(lambda i: 100 * (1.002 ** i) * (1 + 0.0005 * math.sin(i)))
    assert re_.classify(closes)["regime"] == "TREND_UP"


def test_steady_downtrend_is_trend_down():
    closes = series(lambda i: 100 * (0.998 ** i) * (1 + 0.0005 * math.sin(i)))
    assert re_.classify(closes)["regime"] == "TREND_DOWN"


def test_chop_is_sideways():
    closes = series(lambda i: 100 * (1 + 0.01 * (1 if i % 2 else -1)))
    assert re_.classify(closes)["regime"] == "SIDEWAYS"


def test_crash_with_volatility_spike_is_panic():
    calm = series(lambda i: 100 * (1 + 0.001 * math.sin(i)), 560)
    crash = [calm[-1] * (1 - 0.02 * (k + 1)) * (1 + (0.01 if k % 2 else -0.01)) for k in range(8)]
    assert re_.classify(calm + crash)["regime"] == "PANIC"


def test_too_little_data_is_unknown_not_guessed():
    assert re_.classify([100.0] * 10)["regime"] == "UNKNOWN"
    assert re_.classify([100.0] * 300 + [0.0])["regime"] == "UNKNOWN"


def test_history_counts_regimes():
    closes = series(lambda i: 100 * (1.002 ** i))
    hist = re_.history(closes)
    assert sum(hist.values()) > 0 and "UNKNOWN" not in hist


def test_float_pstdev_matches_statistics_and_labels_are_unchanged():
    """2026-10-02 speed fix: _pstdev replaces the exact-Fraction statistics.pstdev (329 s cycle)."""
    import random
    import statistics

    rng = random.Random(11)
    for _ in range(200):
        xs = [rng.gauss(0, rng.choice([1e-4, 1e-2, 0.05])) for _ in range(rng.randint(2, 60))]
        assert abs(re_._pstdev(xs) - statistics.pstdev(xs)) <= 1e-12 * max(1.0, statistics.pstdev(xs))
