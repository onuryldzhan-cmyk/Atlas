"""tools/backtest_replay.py (registry v5.30): replays the real chain, offline."""

from __future__ import annotations

from decimal import Decimal

from tools import backtest_replay as bt


def _rows(count, start=100.0, drift=0.0004, wobble=0.002):
    import math
    rows, price = [], start
    for i in range(count):
        price *= 1 + drift + wobble * math.sin(i / 7)
        open_ms = 1_700_000_000_000 + i * 60_000
        rows.append([open_ms, f"{price:.4f}", f"{price * 1.001:.4f}", f"{price * 0.999:.4f}",
                     f"{price:.4f}", "10", open_ms + 59_999, "0", 0, "4", "400", "0"])
    return rows


def test_replay_runs_the_real_chain_and_accounts_consistently():
    data = {"BTCUSDT": _rows(420), "ETHUSDT": _rows(420, start=50.0, drift=-0.0004)}
    result = bt.replay(data, step=10)
    summary = bt.summarize(result)
    assert summary["decisions"] > 0
    assert summary["closed_trades"] + summary["open_at_end"] <= summary["buy_signals"]
    for trade in result.trades:
        assert trade.entry_fee > 0 and trade.exit_fee > 0          # fee on both sides
        assert trade.cost + trade.entry_fee <= Decimal("4000")      # never above the LOW cap (40%)
    assert summary["net_pnl"] == sum((t.net for t in result.trades), Decimal("0"))


def test_macro_is_excluded_so_bucket_is_never_low():
    """Without Macro evidence the regime rule caps LOW to MEDIUM (NB-4)."""
    captured = []

    class Spy:
        def __init__(self):
            from ai.core.atlas_brain import AtlasBrain
            self.inner = AtlasBrain()

        def analyze_and_decide(self, symbol, market_data):
            decision = self.inner.analyze_and_decide(symbol, market_data)
            captured.append((market_data.get("evidence_status", {}).get("macro"), decision))
            return decision

    bt.replay({"BTCUSDT": _rows(300)}, step=20, brain_factory=Spy)
    assert captured
    for macro_status, decision in captured:
        assert macro_status != "AVAILABLE"
        level = getattr(decision, "risk_level", None)
        assert str(getattr(level, "value", level)).upper() != "LOW"


def test_main_prints_labelled_report_with_injected_history(capsys):
    rows = _rows(300)

    def fetch(symbol, start):
        page = [r for r in rows if int(r[0]) >= start][:1000]
        return page

    import time
    original = time.time
    time.time = lambda: (int(rows[-1][6]) + 1) / 1000
    try:
        assert bt.main(["--days", "1", "--step", "30", "--symbols", "BTCUSDT"], fetch=fetch) == 0
    finally:
        time.time = original
    out = capsys.readouterr().out
    assert "MACRO-NEUTRAL REPLAY" in out and "Nothing was changed" in out
