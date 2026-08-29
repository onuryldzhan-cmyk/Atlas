"""
============================================================
ATLAS HISTORICAL MARKET DATA ARCHIVER v1.0.0
============================================================

Project Atlas AI

Pages a public market-data provider through a symbol's full available
history and archives every closed bar with recorded provenance.

Responsibilities
----------------
- Walk the provider forward one page at a time
- Never archive an unclosed (in-progress) bar
- Attribute every stored bar to a checksummed fetch batch
- Resume from the archive instead of refetching covered history
- Stop and report on rate limiting rather than hammering the venue

Security boundary
-----------------
This service reads public market data only. It holds no API key, places
no orders and touches no capital.

============================================================
"""

from __future__ import annotations

import logging
import time

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Protocol, Sequence

from data_layer.market_data_sqlite import (
    ArchivedBar,
    BarConflict,
    FetchBatch,
    MarketDataSQLiteStorage,
    timeframe_to_milliseconds,
)

from atlas_finance.market_data.exceptions import (
    MarketDataRateLimitError,
)
from atlas_finance.market_data.models import MarketCandle

logger = logging.getLogger("AtlasFinance.HistoricalArchiver")

__all__ = [
    "ArchiveRunResult",
    "HistoricalArchiver",
    "StopReason",
]

#: Binance's first spot listings predate this by a wide margin; requesting an
#: earlier start simply returns the venue's first available candle.
DEFAULT_HISTORY_FLOOR = datetime(2017, 1, 1, tzinfo=UTC)

KLINES_ENDPOINT = "/api/v3/klines"
SOURCE_NAME = "binance_public_klines"


class StopReason:
    """Why a run ended. Recorded verbatim in the run result."""

    COMPLETE = "COMPLETE"
    RATE_LIMITED = "RATE_LIMITED"
    MAX_REQUESTS = "MAX_REQUESTS"
    NO_PROGRESS = "NO_PROGRESS"


class CandleProvider(Protocol):
    """The provider surface the archiver depends on."""

    PROVIDER_NAME: str
    VERSION: str

    def get_candles(
        self,
        symbol: str,
        timeframe: str = ...,
        limit: int = ...,
        *,
        start_time: datetime | None = ...,
        end_time: datetime | None = ...,
    ) -> Sequence[MarketCandle]: ...


@dataclass(frozen=True, slots=True)
class ArchiveRunResult:
    """Outcome of archiving one symbol/timeframe."""

    symbol: str
    timeframe: str
    requests_made: int
    bars_fetched: int
    bars_inserted: int
    bars_already_present: int
    batches_recorded: int
    conflicts: tuple[BarConflict, ...]
    first_open_time: datetime | None
    last_open_time: datetime | None
    stop_reason: str
    rate_limit_detail: str | None = None

    @property
    def has_conflicts(self) -> bool:
        return bool(self.conflicts)


class HistoricalArchiver:
    """Fetch a symbol's full history and archive it with provenance."""

    def __init__(
        self,
        provider: CandleProvider,
        storage: MarketDataSQLiteStorage,
        *,
        page_size: int = 1000,
        request_interval_seconds: float = 0.25,
        max_requests_per_symbol: int = 2000,
        history_floor: datetime = DEFAULT_HISTORY_FLOOR,
        sleep: object = time.sleep,
    ) -> None:
        if page_size < 1:
            raise ValueError("page_size must be positive")
        if request_interval_seconds < 0:
            raise ValueError("request_interval_seconds must be nonnegative")
        if max_requests_per_symbol < 1:
            raise ValueError("max_requests_per_symbol must be positive")
        if history_floor.tzinfo is None:
            raise ValueError("history_floor must be timezone aware")

        self._provider = provider
        self._storage = storage
        self._page_size = page_size
        self._request_interval_seconds = request_interval_seconds
        self._max_requests_per_symbol = max_requests_per_symbol
        self._history_floor = history_floor
        self._sleep = sleep

    def archive_symbol(
        self,
        symbol: str,
        timeframe: str = "1h",
        *,
        start: datetime | None = None,
        end: datetime | None = None,
        resume: bool = True,
    ) -> ArchiveRunResult:
        """Page from ``start`` (or the archive's high-water mark) to ``end``."""

        interval_ms = timeframe_to_milliseconds(timeframe)
        end_time = end or datetime.now(tz=UTC)

        cursor_ms = self._starting_cursor(
            symbol,
            timeframe,
            start=start,
            resume=resume,
            interval_ms=interval_ms,
        )
        end_ms = int(end_time.timestamp() * 1000)

        requests_made = 0
        bars_fetched = 0
        bars_inserted = 0
        bars_already_present = 0
        batches_recorded = 0
        conflicts: list[BarConflict] = []
        stop_reason = StopReason.COMPLETE
        rate_limit_detail: str | None = None

        while cursor_ms <= end_ms:
            if requests_made >= self._max_requests_per_symbol:
                stop_reason = StopReason.MAX_REQUESTS
                break

            if requests_made and self._request_interval_seconds > 0:
                self._sleep(self._request_interval_seconds)

            requested_start_ms = cursor_ms
            try:
                candles = self._provider.get_candles(
                    symbol,
                    timeframe,
                    self._page_size,
                    start_time=datetime.fromtimestamp(cursor_ms / 1000, tz=UTC),
                    end_time=end_time,
                )
            except MarketDataRateLimitError as error:
                stop_reason = StopReason.RATE_LIMITED
                rate_limit_detail = str(error)
                logger.warning(
                    "Rate limited while archiving %s %s; stopping. detail=%s",
                    symbol,
                    timeframe,
                    error,
                )
                break

            requests_made += 1

            if not candles:
                break

            closed = [candle for candle in candles if candle.closed]
            bars_fetched += len(closed)
            last_open_ms = int(candles[-1].open_time.timestamp() * 1000)

            if closed:
                bars = tuple(
                    _to_archived_bar(candle, symbol, timeframe)
                    for candle in closed
                )
                batch = FetchBatch(
                    source=SOURCE_NAME,
                    endpoint=KLINES_ENDPOINT,
                    provider_version=self._provider.VERSION,
                    symbol=symbol,
                    timeframe=timeframe,
                    fetched_at=datetime.now(tz=UTC),
                    bars=bars,
                    requested_start_ms=requested_start_ms,
                    requested_end_ms=end_ms,
                )
                result = self._storage.store_batch(batch)
                bars_inserted += result.inserted
                bars_already_present += result.already_present
                batches_recorded += 1 if result.batch_was_new else 0
                conflicts.extend(result.conflicts)

            next_cursor_ms = last_open_ms + interval_ms
            if next_cursor_ms <= cursor_ms:
                # The venue returned no forward progress; refuse to spin.
                stop_reason = StopReason.NO_PROGRESS
                break
            cursor_ms = next_cursor_ms

            if len(candles) < self._page_size:
                break

        coverage = self._storage.coverage(symbol, timeframe)

        return ArchiveRunResult(
            symbol=symbol,
            timeframe=timeframe,
            requests_made=requests_made,
            bars_fetched=bars_fetched,
            bars_inserted=bars_inserted,
            bars_already_present=bars_already_present,
            batches_recorded=batches_recorded,
            conflicts=tuple(conflicts),
            first_open_time=coverage.first_open_time,
            last_open_time=coverage.last_open_time,
            stop_reason=stop_reason,
            rate_limit_detail=rate_limit_detail,
        )

    def _starting_cursor(
        self,
        symbol: str,
        timeframe: str,
        *,
        start: datetime | None,
        resume: bool,
        interval_ms: int,
    ) -> int:
        if start is not None:
            if start.tzinfo is None:
                raise ValueError("start must be timezone aware")
            return int(start.timestamp() * 1000)

        if resume:
            high_water_ms = self._storage.last_open_time_ms(symbol, timeframe)
            if high_water_ms is not None:
                return high_water_ms + interval_ms

        return int(self._history_floor.timestamp() * 1000)


def _to_archived_bar(
    candle: MarketCandle,
    symbol: str,
    timeframe: str,
) -> ArchivedBar:
    metadata = candle.metadata or {}
    return ArchivedBar(
        symbol=symbol,
        timeframe=timeframe,
        open_time_ms=int(candle.open_time.timestamp() * 1000),
        close_time_ms=(
            int(candle.close_time.timestamp() * 1000)
            if candle.close_time is not None
            else None
        ),
        open=candle.open,
        high=candle.high,
        low=candle.low,
        close=candle.close,
        volume=candle.volume,
        quote_volume=metadata.get("quote_volume"),
        trades=metadata.get("trades"),
    )
