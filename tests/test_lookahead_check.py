"""Core proposal #6: future candles must never change a trade that already closed."""

from tests.test_backtest_replay import _rows
from tools import backtest_replay as bt
from tools.lookahead_check import check


class Alternating:
    def __init__(self):
        self.n = 0

    def analyze_and_decide(self, symbol, market_data):
        self.n += 1
        return {"symbol": symbol, "action": "BUY" if self.n % 2 else "SELL", "confidence": 95.0, "risk_level": "MEDIUM"}


def test_replay_has_no_lookahead_on_closed_trades():
    out = check({"BTCUSDT": _rows(500, drift=0.001, wobble=0.0)}, 0.7, step=20, brain_factory=Alternating)
    assert out["compared_trades"] >= 2 and out["verdict"] == "NO_LOOKAHEAD_DETECTED", out


def test_a_peeking_strategy_is_caught(monkeypatch):
    # A brain that reads the LAST candle of the whole series it was handed: with more future data its decisions change.
    class Peeker:
        last_close = None

        def __init__(self):
            self.n = 0

        def analyze_and_decide(self, symbol, market_data):
            # trades (BUY/SELL alternating) only when the series it was handed ends above 140
            self.n += 1
            peek = Peeker.last_close is not None and Peeker.last_close > 140
            action = ("BUY" if self.n % 2 else "SELL") if peek else "HOLD"
            return {"symbol": symbol, "action": action, "confidence": 95.0, "risk_level": "MEDIUM"}

    real = bt.replay

    def peeking_replay(data, **kw):
        Peeker.last_close = float(next(iter(data.values()))[-1][4])
        return real(data, **kw)

    monkeypatch.setattr(bt, "replay", peeking_replay)
    rows = _rows(500, drift=0.001, wobble=0.0)
    out = check({"BTCUSDT": rows}, 0.5, step=20, brain_factory=Peeker)
    assert float(rows[249][4]) < 140 < float(rows[-1][4])  # the peek flips between the two runs
    assert out["verdict"] == "LOOKAHEAD_SUSPECTED" and out["mismatches"]
