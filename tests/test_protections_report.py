"""tools/protections_report.py: freqtrade-style protections replayed on closed PAPER trades (observe-only)."""
from __future__ import annotations

from decimal import Decimal as D

from tools import protections_report as pr


def _t(sym, opened, closed, gross, cost="1000"):
    return {"symbol": sym, "opened_at": f"2026-10-01T{opened}:00+00:00", "closed_at": f"2026-10-01T{closed}:00+00:00",
            "cost_quote": cost, "gross_pnl": gross}


def test_cooldown_blocks_reentry_in_the_same_coin_only():
    out = pr.replay([_t("BTCUSDT", "00:00", "01:00", "-5"), _t("BTCUSDT", "02:00", "03:00", "-7"),
                     _t("ETHUSDT", "02:00", "03:00", "4")])
    c = out["rules"]["COOLDOWN"]
    assert c["blocked"] == 1 and c["avoided_net"] > 0  # the BTC re-entry 1 h after its exit; ETH untouched


def test_cooldown_expires_after_five_hours():
    out = pr.replay([_t("BTCUSDT", "00:00", "01:00", "-5"), _t("BTCUSDT", "06:30", "07:00", "-5")])
    assert out["rules"]["COOLDOWN"]["blocked"] == 0


def test_loss_guard_needs_four_losers_across_all_coins():
    losers = [_t(s, f"0{i}:00", f"0{i}:30", "-5") for i, s in enumerate(["A", "B", "C", "D"])]
    out = pr.replay(losers + [_t("E", "04:45", "05:00", "9")])
    g = out["rules"]["LOSS_GUARD"]
    assert g["blocked"] == 1 and g["blocked_wins"] == 1 and g["avoided_net"] < 0  # it would have cut a winner


def test_low_profit_locks_a_coin_with_weak_recent_results():
    out = pr.replay([_t("X", "00:00", "00:10", "1"), _t("X", "00:20", "00:30", "1"), _t("X", "06:00", "06:10", "-3")])
    assert out["rules"]["LOW_PROFIT_6H"]["blocked"] == 1


def test_malformed_records_are_left_out_and_counted():
    out = pr.replay([{"symbol": "A", "opened_at": "bad"}, _t("A", "00:00", "01:00", "1")])
    assert out["trades"] == 1 and out["skipped_malformed"] == 1 and out["combined"]["blocked"] == 0
