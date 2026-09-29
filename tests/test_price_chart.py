"""Price chart (v5.72): observation-only candle buffer and a read-only endpoint that never guesses."""

from __future__ import annotations

from types import SimpleNamespace

import web_app
from core.market_loop import MarketLoop


def candle(t, c):
    return {"open_time": t, "open": c, "high": c + 1, "low": c - 1, "close": c}


def test_buffer_keeps_the_last_closed_candles_immutably_and_never_raises():
    loop = MarketLoop.__new__(MarketLoop)
    loop.recent_candles = {}
    loop._remember_candles("BTCUSDT", [candle(60_000 * i, 100 + i) for i in range(300)])
    rows = loop.candles("btcusdt")
    assert len(rows) == MarketLoop.RECENT_CANDLE_LIMIT and rows[-1][4] == 399.0 and isinstance(rows, tuple)
    loop._remember_candles("BTCUSDT", [{"bad": 1}])  # malformed input: previous snapshot kept, no exception
    assert loop.candles("BTCUSDT") == rows
    assert loop.candles("ETHUSDT") == ()


def test_payload_validates_and_converts():
    loop = SimpleNamespace(candles=lambda s: ((120_000, 1.0, 2.0, 0.5, 1.5),) if s == "BTCUSDT" else ())
    ok = web_app._candles_payload(loop, "btcusdt")
    assert ok["available"] and ok["candles"] == [{"time": 120, "open": 1.0, "high": 2.0, "low": 0.5, "close": 1.5}]
    assert web_app._candles_payload(loop, "ETHUSDT")["reason"] == "NO_CANDLES_YET"
    assert web_app._candles_payload(loop, "../etc")["reason"] == "INVALID_SYMBOL"
    assert web_app._candles_payload(None, "BTCUSDT")["reason"] == "MARKET_LOOP_NOT_ATTACHED"
