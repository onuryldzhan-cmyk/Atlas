"""Shadow stage S1: order-book cost estimate, observe-only (2026-10-02)."""
from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import pytest

from tools import shadow_costs as sc

BOOK = {"bids": [["99", "5"], ["98", "100"]], "asks": [["101", "5"], ["102", "100"]]}


def test_book_cost_walks_levels_against_mid():
    c = sc.book_cost(BOOK, Decimal("1000"))
    assert c["mid"] == Decimal("100") and c["spread_bps"] == 200.0
    # BUY 1000: 505 at 101 (5 coins) + 495 at 102 (4.853) -> VWAP 101.4925 -> 149.25 bps over mid
    # SELL 1000: 495 at 99 (5 coins) + 505 at 98 (5.153) -> VWAP 98.4925 -> 150.75 bps under mid
    assert c["buy_bps"] == 149.25 and c["sell_bps"] == 150.75


def test_thin_or_malformed_books_are_missing_never_estimated():
    assert sc.book_cost(BOOK, Decimal("1000000"))["buy_bps"] is None  # deeper than the book
    for bad in ({}, {"bids": [], "asks": []}, {"bids": [["100", "1"]], "asks": [["99", "1"]]}, {"bids": [["x", "1"]], "asks": [["1", "1"]]}):
        assert sc.book_cost(bad, Decimal("10")) is None


def test_run_records_samples_and_warns_without_inventing(tmp_path):
    now = datetime(2026, 10, 2, tzinfo=UTC)

    def fetch(symbol):
        if symbol == "DOWN":
            raise OSError("blocked")
        return BOOK

    out = sc.run(tmp_path, ["BTCUSDT", "DOWN"], Decimal("100"), fetch=fetch, now=now)
    assert out["verdict"] == "OK" and "DOWN" in out["summary"]
    costs = sc.median_costs(tmp_path)
    assert set(costs) == {"BTCUSDT"} and costs["BTCUSDT"]["samples"] == 1
    assert sc.run(tmp_path / "x", ["DOWN"], Decimal("100"), fetch=fetch, now=now)["verdict"] == "WARN"
    assert not (tmp_path / "x" / "shadow" / "book_costs.csv").exists()


def test_report_reprices_only_measured_coins():
    closed = [{"symbol": "BTCUSDT", "cost_quote": "1000", "gross_pnl": "10", "fee_quote": "0"},
              {"symbol": "NOPE", "cost_quote": "1000", "gross_pnl": "10"}]
    out = sc.report(closed, {"BTCUSDT": {"buy_bps": 5.0, "sell_bps": 5.0, "samples": 3}})
    assert out["trades_priced"] == 1 and out["trades_unpriced"] == 1
    assert out["book_cost"] == pytest.approx(1.0)  # 1000 x 10 bps
    assert out["shadow_net_estimate"] == pytest.approx(out["paper_net"] - 1.0)


def test_typical_notional_is_the_median_and_labels_the_default():
    assert sc.typical_notional([{"cost_quote": "100"}, {"cost_quote": "300"}, {"cost_quote": "200"}]) == (Decimal("200"), True)
    assert sc.typical_notional([]) == (sc.DEFAULT_NOTIONAL, False)
