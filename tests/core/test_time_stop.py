"""SA-FEE-DRAG.1: holding-time cap and profit-activated trailing stop (research replay only)."""

from __future__ import annotations

from decimal import Decimal

import pytest

from tests.test_backtest_replay import _rows
from tools import backtest_replay as bt
from tools.lookahead_check import check

FEE = Decimal("0.001")
D = Decimal


class _AlwaysBuy:
    def analyze_and_decide(self, symbol, market_data):
        return {"symbol": symbol, "action": "BUY", "confidence": 95.0, "risk_level": "LOW"}


def _position(entry=D("100"), qty=D("10"), entry_ms=0) -> bt.Position:
    cost = entry * qty
    fee = cost * FEE
    return bt.Position("BTCUSDT", "LOW", False, "t0", cost, qty=qty, qty_bought=qty, cost_total=cost,
                       fees_in=fee, cost_open=cost, fees_open=fee, peak=entry, entry_ms=entry_ms)


def _exit(pos, price, minutes, **kw):
    return bt.time_trailing_exit(pos, price=D(str(price)), now_ms=minutes * 60_000, fee_rate=FEE, **kw)


def _series(*legs, start=100.0):
    """1-minute candles following straight-line legs of (candles, total_move)."""
    rows, price, i = [], start, 0
    for count, move in legs:
        per = (1 + move) ** (1 / count)
        for _ in range(count):
            price *= per
            open_ms = 1_700_000_000_000 + i * 60_000
            rows.append([open_ms, f"{price:.4f}", f"{price * 1.0005:.4f}", f"{price * 0.9995:.4f}", f"{price:.4f}",
                         "10", open_ms + 59_999, "0", 0, "4", "400", "0"])
            i += 1
    return rows


# ------------------------------------------------------------------ the exit rule itself

def test_no_rule_configured_never_exits():
    assert _exit(_position(), 50, 10_000) is None


def test_time_stop_waits_for_the_cap():
    assert _exit(_position(), 90, 48 * 60 - 1, max_hold_min=48 * 60) is None


def test_time_stop_closes_a_loser_at_the_cap():
    assert _exit(_position(), 99, 48 * 60, max_hold_min=48 * 60) == "TIME_STOP"


def test_time_stop_closes_a_flat_position_because_fees_make_it_a_loss():
    assert _exit(_position(), 100, 48 * 60, max_hold_min=48 * 60) == "TIME_STOP"


def test_time_stop_keeps_a_position_that_is_net_positive_after_fees():
    # break-even needs ~+0.2% (two 0.1% fees); +1% is a real profit
    assert _exit(_position(), 101, 48 * 60, max_hold_min=48 * 60) is None


def test_trailing_stop_is_not_armed_below_the_activation():
    pos = _position()
    assert _exit(pos, 101.4, 10, trail_activation=D("0.015"), trail_distance=D("0.01")) is None
    assert not pos.trail_active
    assert _exit(pos, 99, 11, trail_activation=D("0.015"), trail_distance=D("0.01")) is None  # a drop alone is not a trail


def test_trailing_stop_arms_then_exits_on_a_pullback_from_the_peak():
    pos = _position()
    kw = dict(trail_activation=D("0.015"), trail_distance=D("0.01"))
    assert _exit(pos, 101.5, 10, **kw) is None and pos.trail_active
    assert _exit(pos, 104, 11, **kw) is None and pos.peak == D("104")
    assert _exit(pos, 103.0, 12, **kw) is None          # 0.96% below the peak: inside the distance
    assert _exit(pos, 102.9, 13, **kw) == "TRAIL_STOP"  # >1% below the 104 peak


def test_trailing_stop_stays_armed_after_price_falls_back_under_the_activation():
    pos = _position()
    kw = dict(trail_activation=D("0.015"), trail_distance=D("0.01"))
    _exit(pos, 102, 10, **kw)
    assert _exit(pos, 100.5, 11, **kw) == "TRAIL_STOP"


def test_degenerate_positions_and_prices_are_ignored():
    kw = dict(max_hold_min=1, trail_activation=D("0.01"), trail_distance=D("0.01"))
    empty = _position(qty=D("0"))
    assert _exit(empty, 50, 100, **kw) is None
    assert _exit(_position(), 0, 100, **kw) is None
    assert _exit(_position(), -5, 100, **kw) is None


def test_trailing_wins_over_time_stop_when_both_apply():
    pos = _position()
    kw = dict(max_hold_min=60, trail_activation=D("0.015"), trail_distance=D("0.01"))
    _exit(pos, 103, 10, **kw)
    assert _exit(pos, 101, 61, **kw) == "TRAIL_STOP"


# ------------------------------------------------------------------ inside the replay

def _run(data, **kw):
    return bt.replay(data, step=10, brain_factory=_AlwaysBuy, **kw)


def test_defaults_reproduce_the_baseline_exactly():
    data = {"BTCUSDT": _rows(600)}
    off = dict(max_hold_min=0, trail_activation=0, trail_distance=0)
    assert bt.summarize(_run(data)) == bt.summarize(_run(data, **off))


def test_time_stop_closes_bag_held_losers_in_the_replay():
    data = {"BTCUSDT": _series((400, 0.0), (800, -0.05))}
    base = _run(data)
    capped = _run(data, max_hold_min=300)
    assert base.exit_reasons.get("TIME_STOP", 0) == 0
    assert capped.exit_reasons.get("TIME_STOP", 0) > 0
    assert len(capped.trades) > len(base.trades)


def test_trailing_stop_locks_in_a_gain_after_the_run_up():
    data = {"BTCUSDT": _series((400, 0.0), (300, 0.04), (300, -0.04))}
    result = _run(data, trail_activation=0.015, trail_distance=0.01)
    assert result.exit_reasons.get("TRAIL_STOP", 0) > 0
    assert any(t.exit_reason == "TRAIL_STOP" for t in result.trades)


def test_no_lookahead_with_the_new_rules_enabled():
    data = {"BTCUSDT": _series((300, 0.0), (300, 0.04), (300, -0.04), (300, 0.03))}
    out = check(data, 0.75, step=10, brain_factory=_AlwaysBuy, max_hold_min=240,
                trail_activation=0.015, trail_distance=0.01)
    assert out["compared_trades"] >= 1 and out["verdict"] == "NO_LOOKAHEAD_DETECTED", out


def test_a_stopped_out_symbol_does_not_rebuy_on_the_same_step():
    data = {"BTCUSDT": _series((400, 0.0), (800, -0.05))}
    result = _run(data, max_hold_min=300)
    stops = [t for t in result.trades if t.exit_reason == "TIME_STOP"]
    entries = [t.entry_time for t in result.trades + result.open_trades]
    assert stops and all(s.exit_time not in entries for s in stops)


@pytest.mark.parametrize("kw", [dict(max_hold_min=-1), dict(trail_activation=-0.1, trail_distance=0.01),
                                dict(trail_activation=0.015), dict(trail_distance=1),
                                dict(trail_activation=0.015, trail_distance=-0.01)])
def test_invalid_parameters_are_refused(kw):
    with pytest.raises(ValueError):
        _run({"BTCUSDT": _rows(300)}, **kw)


# ------------------------------------------------------------------ comparison matrix

def test_matrix_compares_the_same_candles_and_reports_the_fee_drag_delta():
    data = {"BTCUSDT": _series((400, 0.0), (300, 0.04), (300, -0.04), (300, 0.0))}
    report = bt.compare_time_stop(data, max_hold_min=300, trail_activation=0.015, trail_distance=0.01,
                                  step=10, brain_factory=_AlwaysBuy)
    base, enforced = report["baseline"], report["time_stop"]
    assert report["fee_drag_delta"] == enforced["fees"] - base["fees"]
    for row in (base, enforced):
        assert 0 <= row["max_drawdown_pct"] <= 100 and 0 <= row["win_rate"] <= 100
    text = bt.format_matrix(report)
    for label in ("Net P&L ($)", "Win rate (%)", "Max drawdown (%)", "Fee drag delta ($)"):
        assert label in text


def test_matrix_counts_open_positions_so_realised_losses_are_not_flattered():
    data = {"BTCUSDT": _series((400, 0.0), (800, -0.05))}
    result = _run(data)
    assert result.marked_open and bt.matrix_row(result)["trades"] == len(result.trades) + len(result.marked_open)


def test_cli_prints_the_comparison_matrix(capsys):
    rows = _series((400, 0.0), (300, 0.03), (300, -0.03))

    def fetch(symbol, start):
        return [r for r in rows if int(r[0]) >= start][:1000]

    import time
    original = time.time
    time.time = lambda: (int(rows[-1][6]) + 1) / 1000
    try:
        assert bt.main(["--days", "1", "--step", "30", "--symbols", "BTCUSDT", "--compare-time-stop"], fetch=fetch) == 0
    finally:
        time.time = original
    out = capsys.readouterr().out
    assert "TIME-STOP COMPARISON" in out and "Fee drag delta" in out and "Nothing was changed" in out
