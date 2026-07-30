"""
============================================================
ATLAS PHASE 6A5.2 — MARKET LOOP INTEGRATION TEST
============================================================

Validates the real legacy compatibility chain:

Fake legacy MarketFeed.candles()
    -> MarketLoop._load_candles()
    -> CandleProcessor.normalize()
    -> TechnicalAnalyzer.analyze()
    -> Brain.analyze_and_decide()
    -> DecisionAdapter.normalize()

Safety:
- Offline
- No Binance connection
- No order execution
- No production source modification
============================================================
"""

from __future__ import annotations

import unittest
from datetime import UTC, datetime, timedelta
from typing import Any

from core.candle_processor import CandleProcessor
from core.market_loop import MarketLoop
from core.technical_analyzer import TechnicalAnalyzer


def build_legacy_candles(
    count: int = 200,
    *,
    start_price: float = 60_000.0,
) -> list[list[Any]]:
    start = datetime(2026, 1, 1, tzinfo=UTC)
    rows: list[list[Any]] = []

    for index in range(count):
        open_time = start + timedelta(minutes=index)
        open_ms = int(open_time.timestamp() * 1000)
        close_ms = open_ms + 59_999

        base = start_price + (index * 4.0)
        open_price = base
        high_price = base + 35.0
        low_price = base - 25.0
        close_price = base + 12.0
        volume = 10.0 + (index * 0.05)

        rows.append([
            open_ms,
            f"{open_price:.2f}",
            f"{high_price:.2f}",
            f"{low_price:.2f}",
            f"{close_price:.2f}",
            f"{volume:.5f}",
            close_ms,
            "0.0",
            0,
            f"{volume * 0.4:.5f}",
            f"{close_price * volume * 0.4:.8f}",
            "0",
        ])

    return rows


class FakeLegacyMarketFeed:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    def candles(
        self,
        symbol: str,
        interval: str = "1m",
        limit: int = 500,
    ) -> list[list[Any]]:
        self.calls.append({
            "symbol": symbol,
            "interval": interval,
            "limit": limit,
        })
        return build_legacy_candles(limit)


class FakeBrain:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    def analyze_and_decide(
        self,
        symbol: str,
        market_data: Any,
    ) -> dict[str, Any]:
        self.calls.append({
            "symbol": symbol,
            "market_data": market_data,
        })
        return {
            "symbol": symbol,
            "action": "HOLD",
            "confidence": 75.0,
            "risk": "LOW",
            "strategy": "PHASE6A5_INTEGRATION_TEST",
            "reason": "Offline integration contract validation.",
        }


class MarketLoopIntegrationTests(unittest.TestCase):

    def test_candle_processor_accepts_binance_legacy_rows(self) -> None:
        processor = CandleProcessor()
        rows = build_legacy_candles(200)

        normalized = processor.normalize(rows)

        self.assertEqual(len(normalized), 200)
        self.assertIsNotNone(normalized[0])
        self.assertIsNotNone(normalized[-1])

    def test_technical_analyzer_accepts_normalized_candles(self) -> None:
        processor = CandleProcessor()
        analyzer = TechnicalAnalyzer()

        normalized = processor.normalize(build_legacy_candles(200))
        result = analyzer.analyze(normalized)

        self.assertIsNotNone(result)

    def test_market_loop_requests_real_legacy_contract(self) -> None:
        feed = FakeLegacyMarketFeed()
        brain = FakeBrain()
        loop = MarketLoop(
            brain=brain,
            market_feed=feed,
            execution=None,
            event_bus=None,
            symbols=["BTCUSDT"],
            interval=10,
        )

        candles = loop._load_candles("BTCUSDT")

        self.assertEqual(len(candles), 200)
        self.assertEqual(len(feed.calls), 1)
        self.assertEqual(feed.calls[0]["symbol"], "BTCUSDT")
        self.assertEqual(feed.calls[0]["interval"], "1m")
        self.assertEqual(feed.calls[0]["limit"], 200)

    def test_process_symbol_reaches_brain_without_execution(self) -> None:
        feed = FakeLegacyMarketFeed()
        brain = FakeBrain()
        loop = MarketLoop(
            brain=brain,
            market_feed=feed,
            execution=None,
            event_bus=None,
            symbols=["BTCUSDT"],
            interval=10,
        )

        result = loop.process_symbol("BTCUSDT")

        self.assertEqual(len(feed.calls), 1)
        self.assertEqual(len(brain.calls), 1)
        self.assertEqual(brain.calls[0]["symbol"], "BTCUSDT")
        self.assertIsNotNone(result)

        if isinstance(result, dict):
            action = str(
                result.get(
                    "action",
                    result.get("decision", {}).get("action", ""),
                )
            ).upper()
            self.assertIn(action, {"HOLD", ""})


if __name__ == "__main__":
    unittest.main(verbosity=2)
