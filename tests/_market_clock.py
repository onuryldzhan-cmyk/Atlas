"""Test clock for offline MarketLoop runs (registry v5.14).

Offline feeds replay fixed historical candles. Since new risk now needs a
fresh newest candle (MarketLoop.BUY_MAX_CANDLE_AGE_SECONDS), a test that
drives the real loop pins the loop's cycle clock to one second after the
newest candle the feed will return, i.e. "now" in the simulated market.
"""

from __future__ import annotations

from datetime import UTC, datetime


# MarketLoop._load_candles fetches this many candles per cycle.
LOOP_FETCH_LIMIT = 200


def pin_clock_to_feed(loop, symbol: str = "BTCUSDT") -> None:
    def cutoff() -> datetime:
        rows = loop.market_feed.candles(symbol, limit=LOOP_FETCH_LIMIT)
        newest_close_ms = max(int(row[6]) for row in rows)
        return datetime.fromtimestamp((newest_close_ms + 1_000) / 1000, tz=UTC)

    loop._processing_cutoff = cutoff
