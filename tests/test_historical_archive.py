"""Contract tests for the historical market-data archiver."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from atlas_finance.market_data.exceptions import MarketDataRateLimitError
from atlas_finance.market_data.historical_archive import (
    HistoricalArchiver,
    StopReason,
)
from atlas_finance.market_data.models import MarketCandle
from data_layer.market_data_archive_sqlite import MarketDataSQLiteStorage

HOUR = timedelta(hours=1)
ORIGIN = datetime(2017, 8, 17, 4, 0, tzinfo=UTC)


def make_candle(index: int, *, symbol: str = "BTCUSDT", closed: bool = True):
    open_time = ORIGIN + index * HOUR
    price = 100.0 + index
    return MarketCandle(
        symbol=symbol,
        timeframe="1h",
        open_time=open_time,
        close_time=open_time + HOUR,
        open=price,
        high=price + 5.0,
        low=price - 5.0,
        close=price + 1.0,
        volume=10.0 + index,
        provider="BinancePublicData",
        closed=closed,
        metadata={"quote_volume": 1000.0 + index, "trades": 7 + index},
    )


class FakeProvider:
    """Serves a fixed history, honouring start_time and the page limit."""

    PROVIDER_NAME = "BinancePublicData"
    VERSION = "1.0.0"

    def __init__(self, candles, *, rate_limit_on_call: int | None = None):
        self._candles = list(candles)
        self._rate_limit_on_call = rate_limit_on_call
        self.calls: list[dict] = []

    def get_candles(
        self,
        symbol,
        timeframe="5m",
        limit=100,
        *,
        start_time=None,
        end_time=None,
    ):
        self.calls.append(
            {
                "symbol": symbol,
                "timeframe": timeframe,
                "limit": limit,
                "start_time": start_time,
                "end_time": end_time,
            }
        )
        if (
            self._rate_limit_on_call is not None
            and len(self.calls) == self._rate_limit_on_call
        ):
            raise MarketDataRateLimitError("rate limit reached. status=429")

        selected = [
            candle
            for candle in self._candles
            if candle.symbol == symbol
            and (start_time is None or candle.open_time >= start_time)
            and (end_time is None or candle.open_time <= end_time)
        ]
        return tuple(selected[:limit])


@pytest.fixture()
def storage(tmp_path):
    store = MarketDataSQLiteStorage(tmp_path / "archive.sqlite3")
    store.open()
    yield store
    store.close()


def build_archiver(storage, provider, **overrides):
    options = {
        "page_size": 10,
        "request_interval_seconds": 0.0,
        "history_floor": ORIGIN,
        "sleep": lambda _seconds: None,
    }
    options.update(overrides)
    return HistoricalArchiver(provider, storage, **options)


class TestPagination:
    def test_history_longer_than_one_page_is_fully_archived(self, storage):
        provider = FakeProvider(make_candle(i) for i in range(25))
        archiver = build_archiver(storage, provider)

        result = archiver.archive_symbol("BTCUSDT", "1h", end=ORIGIN + 24 * HOUR)

        assert result.bars_inserted == 25
        assert result.stop_reason == StopReason.COMPLETE
        assert provider.calls[0]["start_time"] == ORIGIN
        assert provider.calls[1]["start_time"] == ORIGIN + 10 * HOUR
        assert storage.coverage("BTCUSDT", "1h").bar_count == 25

    def test_each_page_advances_past_the_last_open_time(self, storage):
        provider = FakeProvider(make_candle(i) for i in range(25))
        archiver = build_archiver(storage, provider)

        archiver.archive_symbol("BTCUSDT", "1h", end=ORIGIN + 24 * HOUR)

        starts = [call["start_time"] for call in provider.calls]
        assert starts == sorted(starts)
        assert len(starts) == len(set(starts))

    def test_archived_history_is_contiguous(self, storage):
        provider = FakeProvider(make_candle(i) for i in range(25))
        archiver = build_archiver(storage, provider)

        archiver.archive_symbol("BTCUSDT", "1h", end=ORIGIN + 24 * HOUR)

        assert storage.coverage("BTCUSDT", "1h").is_contiguous


class TestUnclosedBars:
    def test_in_progress_bar_is_not_archived(self, storage):
        candles = [make_candle(i) for i in range(5)]
        candles.append(make_candle(5, closed=False))
        provider = FakeProvider(candles)
        archiver = build_archiver(storage, provider)

        result = archiver.archive_symbol("BTCUSDT", "1h", end=ORIGIN + 5 * HOUR)

        assert result.bars_inserted == 5
        assert storage.coverage("BTCUSDT", "1h").last_open_time == ORIGIN + 4 * HOUR


class TestIdempotency:
    def test_rerunning_the_same_range_inserts_nothing_new(self, storage):
        provider = FakeProvider(make_candle(i) for i in range(25))
        archiver = build_archiver(storage, provider)
        end = ORIGIN + 24 * HOUR

        archiver.archive_symbol("BTCUSDT", "1h", start=ORIGIN, end=end)
        second = archiver.archive_symbol("BTCUSDT", "1h", start=ORIGIN, end=end)

        assert second.bars_inserted == 0
        assert second.bars_already_present == 25
        assert not second.has_conflicts
        assert storage.health()["bar_count"] == 25

    def test_resume_starts_after_the_archived_high_water_mark(self, storage):
        provider = FakeProvider(make_candle(i) for i in range(25))
        archiver = build_archiver(storage, provider)

        archiver.archive_symbol("BTCUSDT", "1h", start=ORIGIN, end=ORIGIN + 9 * HOUR)
        provider.calls.clear()
        archiver.archive_symbol("BTCUSDT", "1h", end=ORIGIN + 24 * HOUR)

        assert provider.calls[0]["start_time"] == ORIGIN + 10 * HOUR
        assert storage.coverage("BTCUSDT", "1h").bar_count == 25


class TestRateLimiting:
    def test_rate_limit_stops_the_run_and_is_reported(self, storage):
        provider = FakeProvider(
            (make_candle(i) for i in range(25)), rate_limit_on_call=2
        )
        archiver = build_archiver(storage, provider)

        result = archiver.archive_symbol("BTCUSDT", "1h", end=ORIGIN + 24 * HOUR)

        assert result.stop_reason == StopReason.RATE_LIMITED
        assert "429" in (result.rate_limit_detail or "")
        assert len(provider.calls) == 2

    def test_bars_fetched_before_the_rate_limit_are_retained(self, storage):
        provider = FakeProvider(
            (make_candle(i) for i in range(25)), rate_limit_on_call=2
        )
        archiver = build_archiver(storage, provider)

        archiver.archive_symbol("BTCUSDT", "1h", end=ORIGIN + 24 * HOUR)

        assert storage.coverage("BTCUSDT", "1h").bar_count == 10

    def test_a_paced_run_sleeps_between_requests(self, storage):
        provider = FakeProvider(make_candle(i) for i in range(25))
        delays: list[float] = []
        archiver = build_archiver(
            storage,
            provider,
            request_interval_seconds=0.25,
            sleep=delays.append,
        )

        archiver.archive_symbol("BTCUSDT", "1h", end=ORIGIN + 24 * HOUR)

        assert delays == [0.25] * (len(provider.calls) - 1)


class TestGuards:
    def test_request_ceiling_stops_the_run(self, storage):
        provider = FakeProvider(make_candle(i) for i in range(100))
        archiver = build_archiver(storage, provider, max_requests_per_symbol=3)

        result = archiver.archive_symbol("BTCUSDT", "1h", end=ORIGIN + 99 * HOUR)

        assert result.stop_reason == StopReason.MAX_REQUESTS
        assert result.requests_made == 3

    def test_naive_start_is_rejected(self, storage):
        archiver = build_archiver(storage, FakeProvider([]))

        with pytest.raises(ValueError):
            archiver.archive_symbol("BTCUSDT", "1h", start=datetime(2020, 1, 1))

    def test_empty_history_produces_an_empty_report(self, storage):
        archiver = build_archiver(storage, FakeProvider([]))

        result = archiver.archive_symbol("BTCUSDT", "1h", end=ORIGIN + 10 * HOUR)

        assert result.bars_inserted == 0
        assert result.first_open_time is None
        assert result.stop_reason == StopReason.COMPLETE


class TestProvenanceRecording:
    def test_archived_bars_carry_binance_provenance(self, storage):
        provider = FakeProvider(make_candle(i) for i in range(5))
        archiver = build_archiver(storage, provider)

        archiver.archive_symbol("BTCUSDT", "1h", end=ORIGIN + 4 * HOUR)

        provenance = storage.provenance_for_bar(
            "BTCUSDT", "1h", int(ORIGIN.timestamp() * 1000)
        )
        assert provenance is not None
        assert provenance.source == "binance_public_klines"
        assert provenance.endpoint == "/api/v3/klines"
        assert provenance.provider_version == "1.0.0"
        assert provenance.fetched_at.tzinfo is not None
        assert storage.verify_batch(provenance.batch_id) is True

    def test_quote_volume_and_trade_count_are_preserved(self, storage):
        provider = FakeProvider(make_candle(i) for i in range(3))
        archiver = build_archiver(storage, provider)

        archiver.archive_symbol("BTCUSDT", "1h", end=ORIGIN + 2 * HOUR)

        bars = storage.get_bars("BTCUSDT", "1h")
        assert bars[0].quote_volume == 1000.0
        assert bars[0].trades == 7
