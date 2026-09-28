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


def test_portfolio_limits_apply_across_symbols_on_one_clock():
    """Registry v5.31 fidelity fix: every symbol steps on one clock and the
    RiskEngine sees all open positions, so portfolio caps really bind."""
    from core.risk_engine import RiskPolicy

    class AlwaysBuy:
        def analyze_and_decide(self, symbol, market_data):
            return {"symbol": symbol, "action": "BUY", "confidence": 95.0, "risk_level": "LOW"}

    symbols = ("BTCUSDT", "ETHUSDT", "BNBUSDT", "SOLUSDT", "XRPUSDT")
    data = {s: _rows(260) for s in symbols}
    result = bt.replay(data, step=20, brain_factory=AlwaysBuy)
    policy = RiskPolicy(total_capital=bt.CAPITAL)
    held = result.open_trades
    assert result.trades == []                              # never a SELL
    assert 0 < len(held) <= policy.max_positions
    committed = sum((t.cost + t.entry_fee for t in held), Decimal("0"))
    assert committed <= bt.CAPITAL * policy.portfolio_exposure_pct + Decimal("0.01")
    assert sum(result.buy_rejections.values()) > 0          # later BUYs were refused by limits


def test_round_trip_trades_are_booked_with_fees_and_net():
    """Guards the v5.30 bug where every BUY was refused (quantity x price
    mismatch), which made the report silently show zero trades."""

    class Alternating:
        def __init__(self):
            self.n = 0

        def analyze_and_decide(self, symbol, market_data):
            self.n += 1
            action = "BUY" if self.n % 2 else "SELL"
            return {"symbol": symbol, "action": action, "confidence": 95.0, "risk_level": "MEDIUM"}

    result = bt.replay({"BTCUSDT": _rows(400, drift=0.001, wobble=0.0)}, step=20, brain_factory=Alternating)
    summary = bt.summarize(result)
    assert summary["closed_trades"] >= 3
    assert summary["buy_rejections"] == {}
    for trade in result.trades:
        assert trade.entry_fee > 0 and trade.exit_fee > 0
        assert trade.cost + trade.entry_fee <= bt.CAPITAL * Decimal("0.25") + Decimal("0.01")  # MEDIUM cap
        assert trade.exit_price > trade.entry_price                                          # rising series
    assert summary["net_pnl"] == sum((t.net for t in result.trades), Decimal("0"))
    assert summary["fees"] > 0
