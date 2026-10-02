"""tools/universe_filter_report.py: freqtrade-style filters, report only (2026-10-02)."""
from __future__ import annotations

from tools import universe_filter_report as uf

BOOK = {"bids": [["100", "1"]], "asks": [["100.1", "1"]]}


def _k(closes, spread=0.01):
    return [[0, c, c * (1 + spread), c * (1 - spread), c, 0] for c in closes]


def test_steady_liquid_coin_is_kept():
    closes = [100 * (1.01 if i % 2 else 0.99) for i in range(60)]
    r = uf.evaluate_symbol("BTCUSDT", _k(closes), BOOK)
    assert r["removed_by"] == [] and r["unknown"] == []


def test_new_pumped_wide_spread_coin_is_removed_by_each_filter():
    closes = [1.0 * (1.4 ** i) for i in range(8)]  # 8 days old, +40 % a day
    r = uf.evaluate_symbol("PUMPUSDT", _k(closes, spread=0.2), {"bids": [["1", "1"]], "asks": [["1.02", "1"]]})
    assert "age" in r["removed_by"] and "spread" in r["removed_by"]
    assert r["volatility"] == "UNKNOWN"  # fewer than 11 closes: not judged, not passed


def test_unreadable_data_is_unknown_never_kept():
    r = uf.evaluate_symbol("X", None, None)
    assert r["removed_by"] == [] and set(r["unknown"]) == {"age", "volatility", "range", "spread"}


def test_report_survives_network_errors():
    def boom(symbol):
        raise OSError("blocked")

    [r] = uf.report(["ETHUSDT"], klines=boom, depth=boom)
    assert r["unknown"]
