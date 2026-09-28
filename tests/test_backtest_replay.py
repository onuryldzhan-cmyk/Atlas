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


# ---------------- staged entries/exits and sleeves (registry v5.32, owner-approved)

def _path(scenario, warmup=205, base=100.0):
    """Warm-up candles oscillating +-0.01% around `base`, then the scenario closes."""
    import math
    closes = [base * (1 + 0.0001 * math.sin(i)) for i in range(warmup)] + list(scenario)
    rows = []
    for i, c in enumerate(closes):
        open_ms = 1_700_000_000_000 + i * 60_000
        rows.append([open_ms, f"{c:.4f}", f"{c:.4f}", f"{c:.4f}", f"{c:.4f}", "10", open_ms + 59_999, "0", 0, "4", "400", "0"])
    return rows


class BuyOnce:
    def __init__(self, risk_level="LOW"):
        self.done = False
        self.risk_level = risk_level

    def analyze_and_decide(self, symbol, market_data):
        action = "HOLD" if self.done else "BUY"
        self.done = True
        return {"symbol": symbol, "action": action, "confidence": 95.0, "risk_level": self.risk_level}


def test_single_wick_does_not_stop_but_two_closes_below_minus_3pct_sell_everything():
    scenario = [96.5, 100.0, 100.0] + [96.5, 96.4] + [96.3] * 3
    result = bt.replay({"BTCUSDT": _path(scenario)}, step=1, staged=True, brain_factory=BuyOnce)
    assert [t.exit_reason for t in result.trades] == ["HARD_STOP"]
    trade = result.trades[0]
    assert trade.exit_price.quantize(Decimal("0.0001")) == Decimal("96.4000")  # 2nd confirming close, not the wick
    assert trade.net < 0 and result.open_trades == []


def test_take_profit_ladder_then_trailing_stop():
    scenario = [100.5, 101.6, 102.0, 103.1, 104.0, 102.4, 102.0]
    result = bt.replay({"BTCUSDT": _path(scenario)}, step=1, staged=True, brain_factory=BuyOnce)
    assert result.partial_sells == 2                       # +1.5% and +3% steps sold part
    assert [t.exit_reason for t in result.trades] == ["TRAILING_STOP"]
    trade = result.trades[0]
    assert trade.net > 0 and trade.exit_fee > 0
    # average exit is between the first take-profit and the trailing exit
    assert Decimal("101.5") < trade.exit_price < Decimal("104")


def test_three_tranches_on_confirmation_never_exceed_the_target():
    class AlwaysBuy:
        def analyze_and_decide(self, symbol, market_data):
            return {"symbol": symbol, "action": "BUY", "confidence": 95.0, "risk_level": "LOW"}

    scenario = [100.0 * (1 + 0.0001 * i) for i in range(1, 60)]   # slow rise, below +1.5%
    result = bt.replay({"BTCUSDT": _path(scenario)}, step=1, staged=True, brain_factory=AlwaysBuy)
    assert result.tranche_adds == 2                         # 3 tranches in total
    held = result.open_trades[0]
    target = bt.CAPITAL * Decimal("0.40")                   # LOW per-position cap
    assert held.cost + held.entry_fee <= target + Decimal("0.01")
    assert held.cost + held.entry_fee > target * Decimal("0.99")


def test_no_tranche_added_below_average_entry():
    class AlwaysBuy:
        def analyze_and_decide(self, symbol, market_data):
            return {"symbol": symbol, "action": "BUY", "confidence": 95.0, "risk_level": "LOW"}

    scenario = [99.5] * 40                                  # below entry, above the -3% stop
    result = bt.replay({"BTCUSDT": _path(scenario)}, step=1, staged=True, brain_factory=AlwaysBuy)
    assert result.tranche_adds == 0


def test_sleeves_cap_each_bucket_across_all_symbols():
    class AlwaysBuyHigh:
        def analyze_and_decide(self, symbol, market_data):
            return {"symbol": symbol, "action": "BUY", "confidence": 95.0, "risk_level": "HIGH"}

    symbols = ("BTCUSDT", "ETHUSDT", "BNBUSDT", "SOLUSDT", "XRPUSDT")
    data = {s: _path([100.0] * 5) for s in symbols}
    capped = bt.replay(data, step=1, sleeves=True, brain_factory=AlwaysBuyHigh)
    uncapped = bt.replay(data, step=1, sleeves=False, brain_factory=AlwaysBuyHigh)
    total = lambda r: sum((t.cost + t.entry_fee for t in r.open_trades), Decimal("0"))
    assert total(capped) <= bt.CAPITAL * Decimal("0.15") + Decimal("0.01")   # "1.5 of 10"
    assert total(uncapped) > total(capped)
    assert capped.buy_rejections.get("SLEEVE_FULL", 0) > 0


def test_baseline_mode_is_unchanged_by_staged_code():
    scenario = [96.5, 96.4, 96.3]
    result = bt.replay({"BTCUSDT": _path(scenario)}, step=1, staged=False, brain_factory=BuyOnce)
    assert result.trades == [] and len(result.open_trades) == 1   # no stop in baseline mode
