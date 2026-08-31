"""Contract tests for the historical market-data archive."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from data_layer.contracts import StorageError
from data_layer.market_data_archive_sqlite import (
    ArchivedBar,
    FetchBatch,
    MarketDataSQLiteStorage,
    batch_checksum,
    timeframe_to_milliseconds,
)

HOUR_MS = 3_600_000
ORIGIN_MS = 1_502_942_400_000  # 2017-08-17T04:00:00Z, Binance's first BTCUSDT hour


@pytest.fixture()
def storage(tmp_path):
    store = MarketDataSQLiteStorage(tmp_path / "archive.sqlite3")
    store.open()
    yield store
    store.close()


def make_bar(index: int, *, symbol: str = "BTCUSDT", close: float | None = None):
    open_time_ms = ORIGIN_MS + index * HOUR_MS
    price = 100.0 + index
    return ArchivedBar(
        symbol=symbol,
        timeframe="1h",
        open_time_ms=open_time_ms,
        close_time_ms=open_time_ms + HOUR_MS - 1,
        open=price,
        high=price + 5.0,
        low=price - 5.0,
        close=price if close is None else close,
        volume=10.0 + index,
        quote_volume=1000.0 + index,
        trades=42 + index,
    )


def make_batch(bars, *, symbol: str = "BTCUSDT", fetched_at: datetime | None = None):
    return FetchBatch(
        source="binance_public_klines",
        endpoint="/api/v3/klines",
        provider_version="1.0.0",
        symbol=symbol,
        timeframe="1h",
        fetched_at=fetched_at or datetime(2026, 8, 28, 12, 0, tzinfo=UTC),
        bars=tuple(bars),
        requested_start_ms=bars[0].open_time_ms,
        requested_end_ms=bars[-1].open_time_ms,
    )


class TestTimeframes:
    def test_known_timeframe_returns_fixed_width(self):
        assert timeframe_to_milliseconds("1h") == HOUR_MS

    def test_calendar_month_is_rejected(self):
        with pytest.raises(StorageError):
            timeframe_to_milliseconds("1M")


class TestChecksum:
    def test_checksum_is_order_independent(self):
        bars = [make_bar(index) for index in range(5)]
        assert batch_checksum(bars) == batch_checksum(list(reversed(bars)))

    def test_checksum_changes_when_a_price_changes(self):
        bars = [make_bar(index) for index in range(3)]
        mutated = list(bars)
        mutated[1] = make_bar(1, close=999.0)
        assert batch_checksum(bars) != batch_checksum(mutated)


class TestIdempotentWrites:
    def test_first_write_inserts_every_bar(self, storage):
        result = storage.store_batch(make_batch([make_bar(i) for i in range(10)]))

        assert result.inserted == 10
        assert result.already_present == 0
        assert result.batch_was_new is True
        assert not result.has_conflicts

    def test_identical_rewrite_inserts_nothing(self, storage):
        batch = make_batch([make_bar(i) for i in range(10)])
        storage.store_batch(batch)

        second = storage.store_batch(batch)

        assert second.inserted == 0
        assert second.already_present == 10
        assert not second.has_conflicts
        assert storage.health()["bar_count"] == 10

    def test_identical_rewrite_preserves_original_provenance(self, storage):
        first_fetch = datetime(2026, 8, 28, 12, 0, tzinfo=UTC)
        later_fetch = datetime(2026, 8, 29, 18, 30, tzinfo=UTC)
        bars = [make_bar(i) for i in range(4)]

        first = storage.store_batch(make_batch(bars, fetched_at=first_fetch))
        storage.store_batch(make_batch(bars, fetched_at=later_fetch))

        provenance = storage.get_batch(first.batch_id)
        assert provenance is not None
        assert provenance.fetched_at == first_fetch
        assert storage.health()["batch_count"] == 1

    def test_overlapping_batch_only_inserts_the_new_tail(self, storage):
        storage.store_batch(make_batch([make_bar(i) for i in range(10)]))

        overlap = storage.store_batch(make_batch([make_bar(i) for i in range(5, 15)]))

        assert overlap.inserted == 5
        assert overlap.already_present == 5
        assert storage.health()["bar_count"] == 15

    def test_batch_carrying_no_new_bars_records_no_orphan_provenance(self, storage):
        bars = [make_bar(i) for i in range(6)]
        storage.store_batch(make_batch(bars))

        # A distinct batch identity (different endpoint) over identical bars.
        duplicate = FetchBatch(
            source="binance_public_klines",
            endpoint="/api/v3/klines?mirror",
            provider_version="1.0.0",
            symbol="BTCUSDT",
            timeframe="1h",
            fetched_at=datetime(2026, 9, 1, tzinfo=UTC),
            bars=tuple(bars),
        )
        result = storage.store_batch(duplicate)

        assert result.inserted == 0
        assert result.batch_was_new is False
        assert storage.get_batch(result.batch_id) is None
        assert storage.health()["batch_count"] == 1


class TestConflictDetection:
    def test_divergent_refetch_is_reported_and_not_overwritten(self, storage):
        storage.store_batch(make_batch([make_bar(i) for i in range(3)]))

        revised = [make_bar(0), make_bar(1, close=777.0), make_bar(2)]
        result = storage.store_batch(make_batch(revised))

        assert result.inserted == 0
        assert result.has_conflicts
        conflict = next(c for c in result.conflicts if c.field_name == "close")
        assert conflict.archived_value == 101.0
        assert conflict.incoming_value == 777.0

        stored = storage.get_bars("BTCUSDT", "1h")
        assert stored[1].close == 101.0

    def test_matching_refetch_reports_no_conflicts(self, storage):
        bars = [make_bar(i) for i in range(3)]
        storage.store_batch(make_batch(bars))

        result = storage.store_batch(make_batch(bars))

        assert result.conflicts == ()


class TestProvenance:
    def test_every_bar_resolves_to_its_fetch_batch(self, storage):
        fetched_at = datetime(2026, 8, 28, 9, 15, tzinfo=UTC)
        storage.store_batch(
            make_batch([make_bar(i) for i in range(4)], fetched_at=fetched_at)
        )

        provenance = storage.provenance_for_bar("BTCUSDT", "1h", ORIGIN_MS + 2 * HOUR_MS)

        assert provenance is not None
        assert provenance.source == "binance_public_klines"
        assert provenance.endpoint == "/api/v3/klines"
        assert provenance.fetched_at == fetched_at
        assert len(provenance.checksum) == 64

    def test_checksum_verifies_against_the_archived_rows(self, storage):
        result = storage.store_batch(make_batch([make_bar(i) for i in range(8)]))

        assert storage.verify_batch(result.batch_id) is True

    def test_verification_fails_when_an_archived_row_is_tampered_with(self, storage):
        result = storage.store_batch(make_batch([make_bar(i) for i in range(8)]))

        connection = storage._connect()
        try:
            connection.execute(
                "UPDATE market_data_bars SET close = 1.0 WHERE open_time_ms = ?",
                (ORIGIN_MS,),
            )
        finally:
            connection.close()

        assert storage.verify_batch(result.batch_id) is False

    def test_unknown_batch_does_not_verify(self, storage):
        assert storage.verify_batch("0" * 64) is False


class TestBatchValidation:
    def test_empty_batch_is_rejected(self):
        with pytest.raises(StorageError):
            FetchBatch(
                source="binance_public_klines",
                endpoint="/api/v3/klines",
                provider_version="1.0.0",
                symbol="BTCUSDT",
                timeframe="1h",
                fetched_at=datetime(2026, 8, 28, 12, 0, tzinfo=UTC),
                bars=(),
            )

    def test_naive_fetch_timestamp_is_rejected(self):
        with pytest.raises(StorageError):
            FetchBatch(
                source="binance_public_klines",
                endpoint="/api/v3/klines",
                provider_version="1.0.0",
                symbol="BTCUSDT",
                timeframe="1h",
                fetched_at=datetime(2026, 8, 28, 12, 0),
                bars=(make_bar(0),),
            )

    def test_mixed_symbol_batch_is_rejected(self):
        with pytest.raises(StorageError):
            make_batch([make_bar(0), make_bar(1, symbol="ETHUSDT")])


class TestCoverage:
    def test_empty_archive_reports_nothing(self, storage):
        report = storage.coverage("BTCUSDT", "1h")

        assert report.bar_count == 0
        assert report.first_open_time is None
        assert report.missing_bars == 0

    def test_contiguous_archive_reports_no_gaps(self, storage):
        storage.store_batch(make_batch([make_bar(i) for i in range(24)]))

        report = storage.coverage("BTCUSDT", "1h")

        assert report.bar_count == 24
        assert report.expected_bars == 24
        assert report.is_contiguous
        assert report.gaps == ()
        assert report.first_open_time == datetime.fromtimestamp(
            ORIGIN_MS / 1000, tz=UTC
        )

    def test_gaps_are_reported_exactly_and_never_filled(self, storage):
        present = [make_bar(i) for i in range(5)]
        present += [make_bar(i) for i in range(8, 12)]
        storage.store_batch(make_batch(present))

        report = storage.coverage("BTCUSDT", "1h")

        assert report.bar_count == 9
        assert report.expected_bars == 12
        assert report.missing_bars == 3
        assert len(report.gaps) == 1
        gap = report.gaps[0]
        assert gap.missing_bars == 3
        assert gap.gap_start_ms == ORIGIN_MS + 5 * HOUR_MS
        assert gap.gap_end_ms == ORIGIN_MS + 7 * HOUR_MS
        assert len(storage.get_bars("BTCUSDT", "1h")) == 9

    def test_coverage_is_isolated_per_symbol(self, storage):
        storage.store_batch(make_batch([make_bar(i) for i in range(10)]))
        storage.store_batch(
            make_batch(
                [make_bar(i, symbol="ETHUSDT") for i in range(3)], symbol="ETHUSDT"
            )
        )

        assert storage.coverage("BTCUSDT", "1h").bar_count == 10
        assert storage.coverage("ETHUSDT", "1h").bar_count == 3
        assert storage.archived_pairs() == (("BTCUSDT", "1h"), ("ETHUSDT", "1h"))


class TestResumeSupport:
    def test_high_water_mark_is_the_latest_open_time(self, storage):
        storage.store_batch(make_batch([make_bar(i) for i in range(7)]))

        assert storage.last_open_time_ms("BTCUSDT", "1h") == ORIGIN_MS + 6 * HOUR_MS

    def test_high_water_mark_is_none_for_an_unarchived_symbol(self, storage):
        assert storage.last_open_time_ms("SOLUSDT", "1h") is None


class TestLifecycle:
    def test_operations_require_an_open_archive(self, tmp_path):
        store = MarketDataSQLiteStorage(tmp_path / "closed.sqlite3")

        with pytest.raises(StorageError):
            store.coverage("BTCUSDT", "1h")

    def test_archive_survives_reopen(self, tmp_path):
        path = tmp_path / "persist.sqlite3"
        with MarketDataSQLiteStorage(path) as store:
            store.store_batch(make_batch([make_bar(i) for i in range(5)]))

        with MarketDataSQLiteStorage(path) as reopened:
            assert reopened.coverage("BTCUSDT", "1h").bar_count == 5
