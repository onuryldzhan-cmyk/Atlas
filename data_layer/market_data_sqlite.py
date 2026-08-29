"""SQLite archive for historical OHLCV bars with per-batch provenance.

This store is deliberately separate from :class:`data_layer.sqlite.SQLiteStorage`.
That backend owns the financial ledger (orders, executions, positions) and
fails closed on integrity problems; a bulk market-data archive has different
durability, size and rebuild characteristics and must never share a lifecycle
with the ledger.

Provenance contract
-------------------
Every bar is attributed to exactly one fetch batch. A batch records the
source, the endpoint, the provider version, the requested window, the UTC
timestamp of the fetch and a SHA-256 checksum. The checksum is computed over
a canonical serialization of the batch's normalized bars, so it can be
recomputed from the stored rows at any time -- see :meth:`verify_batch`.
It covers normalized bars, not the raw HTTP bytes.

Idempotency contract
--------------------
Bars are keyed by ``(symbol, timeframe, open_time_ms)``. Re-storing a batch
that covers an already-archived range inserts nothing and leaves the original
provenance untouched. Where a re-fetch disagrees with an archived bar, the
existing row is kept and the divergence is reported as a conflict rather than
being silently overwritten or silently dropped.
"""

from __future__ import annotations

import hashlib
import sqlite3
import threading

from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Sequence

from .contracts import StorageError

__all__ = [
    "ArchivedBar",
    "BarConflict",
    "BatchProvenance",
    "CoverageGap",
    "CoverageReport",
    "FetchBatch",
    "MarketDataSQLiteStorage",
    "WriteResult",
    "batch_checksum",
    "timeframe_to_milliseconds",
]


TIMEFRAME_MILLISECONDS: dict[str, int] = {
    "1m": 60_000,
    "3m": 180_000,
    "5m": 300_000,
    "15m": 900_000,
    "30m": 1_800_000,
    "1h": 3_600_000,
    "2h": 7_200_000,
    "4h": 14_400_000,
    "6h": 21_600_000,
    "8h": 28_800_000,
    "12h": 43_200_000,
    "1d": 86_400_000,
    "3d": 259_200_000,
    "1w": 604_800_000,
}


def timeframe_to_milliseconds(timeframe: str) -> int:
    """Return the fixed bar width of ``timeframe`` in milliseconds.

    Calendar-relative timeframes such as ``1M`` have no fixed width and are
    rejected, because gap arithmetic over them would be wrong.
    """

    try:
        return TIMEFRAME_MILLISECONDS[timeframe]
    except KeyError:
        raise StorageError(
            f"timeframe {timeframe!r} has no fixed bar width"
        ) from None


@dataclass(frozen=True, slots=True)
class ArchivedBar:
    """One normalized OHLCV bar, keyed by its open time."""

    symbol: str
    timeframe: str
    open_time_ms: int
    close_time_ms: int | None
    open: float
    high: float
    low: float
    close: float
    volume: float
    quote_volume: float | None = None
    trades: int | None = None

    def canonical_line(self) -> str:
        """Deterministic serialization used for checksum computation."""

        return "|".join((
            self.symbol,
            self.timeframe,
            str(self.open_time_ms),
            repr(self.open),
            repr(self.high),
            repr(self.low),
            repr(self.close),
            repr(self.volume),
        ))


def batch_checksum(bars: Sequence[ArchivedBar]) -> str:
    """SHA-256 over the canonical serialization of ``bars``, in open-time order."""

    digest = hashlib.sha256()
    for bar in sorted(bars, key=lambda item: item.open_time_ms):
        digest.update(bar.canonical_line().encode("utf-8"))
        digest.update(b"\n")
    return digest.hexdigest()


@dataclass(frozen=True, slots=True)
class FetchBatch:
    """A contiguous group of bars retrieved by a single provider call."""

    source: str
    endpoint: str
    provider_version: str
    symbol: str
    timeframe: str
    fetched_at: datetime
    bars: Sequence[ArchivedBar]
    requested_start_ms: int | None = None
    requested_end_ms: int | None = None

    def __post_init__(self) -> None:
        if not self.bars:
            raise StorageError("a fetch batch must contain at least one bar")
        if self.fetched_at.tzinfo is None:
            raise StorageError("fetched_at must be timezone aware")
        for bar in self.bars:
            if bar.symbol != self.symbol or bar.timeframe != self.timeframe:
                raise StorageError(
                    "batch bars must all share the batch symbol and timeframe"
                )

    @property
    def checksum(self) -> str:
        return batch_checksum(self.bars)

    @property
    def batch_id(self) -> str:
        """Content-addressed identity of this batch.

        Derived from the request identity plus the batch checksum, so an
        identical re-fetch resolves to the same batch row instead of
        accumulating duplicate provenance records.
        """

        digest = hashlib.sha256()
        for part in (
            self.source,
            self.endpoint,
            self.symbol,
            self.timeframe,
            self.checksum,
        ):
            digest.update(part.encode("utf-8"))
            digest.update(b"\x00")
        return digest.hexdigest()


@dataclass(frozen=True, slots=True)
class BatchProvenance:
    """Stored provenance for one archived batch."""

    batch_id: str
    source: str
    endpoint: str
    provider_version: str
    symbol: str
    timeframe: str
    fetched_at: datetime
    checksum: str
    bar_count: int
    first_open_time_ms: int
    last_open_time_ms: int
    requested_start_ms: int | None
    requested_end_ms: int | None


@dataclass(frozen=True, slots=True)
class BarConflict:
    """An incoming bar that disagrees with the archived bar at the same key."""

    open_time_ms: int
    field_name: str
    archived_value: Any
    incoming_value: Any


@dataclass(frozen=True, slots=True)
class WriteResult:
    """Outcome of storing one batch."""

    batch_id: str
    checksum: str
    inserted: int
    already_present: int
    conflicts: tuple[BarConflict, ...] = ()
    batch_was_new: bool = True

    @property
    def has_conflicts(self) -> bool:
        return bool(self.conflicts)


@dataclass(frozen=True, slots=True)
class CoverageGap:
    """A run of missing bars between two archived bars."""

    gap_start_ms: int
    gap_end_ms: int
    missing_bars: int


@dataclass(frozen=True, slots=True)
class CoverageReport:
    """Exact archived coverage for one symbol/timeframe pair."""

    symbol: str
    timeframe: str
    bar_count: int
    first_open_time_ms: int | None
    last_open_time_ms: int | None
    expected_bars: int
    missing_bars: int
    gaps: tuple[CoverageGap, ...] = field(default=())

    @property
    def first_open_time(self) -> datetime | None:
        return _from_ms(self.first_open_time_ms)

    @property
    def last_open_time(self) -> datetime | None:
        return _from_ms(self.last_open_time_ms)

    @property
    def is_contiguous(self) -> bool:
        return self.missing_bars == 0


def _from_ms(value: int | None) -> datetime | None:
    if value is None:
        return None
    return datetime.fromtimestamp(value / 1000, tz=UTC)


_SCHEMA = (
    """
    CREATE TABLE IF NOT EXISTS market_data_batches (
        batch_id            TEXT    PRIMARY KEY,
        source              TEXT    NOT NULL,
        endpoint            TEXT    NOT NULL,
        provider_version    TEXT    NOT NULL,
        symbol              TEXT    NOT NULL,
        timeframe           TEXT    NOT NULL,
        fetched_at          TEXT    NOT NULL,
        checksum            TEXT    NOT NULL,
        bar_count           INTEGER NOT NULL,
        first_open_time_ms  INTEGER NOT NULL,
        last_open_time_ms   INTEGER NOT NULL,
        requested_start_ms  INTEGER,
        requested_end_ms    INTEGER
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS market_data_bars (
        symbol          TEXT    NOT NULL,
        timeframe       TEXT    NOT NULL,
        open_time_ms    INTEGER NOT NULL,
        close_time_ms   INTEGER,
        open            REAL    NOT NULL,
        high            REAL    NOT NULL,
        low             REAL    NOT NULL,
        close           REAL    NOT NULL,
        volume          REAL    NOT NULL,
        quote_volume    REAL,
        trades          INTEGER,
        source          TEXT    NOT NULL,
        batch_id        TEXT    NOT NULL
                        REFERENCES market_data_batches(batch_id),
        PRIMARY KEY (symbol, timeframe, open_time_ms)
    )
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_market_data_bars_batch
        ON market_data_bars(batch_id)
    """,
)

_BAR_COLUMNS = (
    "close_time_ms",
    "open",
    "high",
    "low",
    "close",
    "volume",
    "quote_volume",
    "trades",
)


class MarketDataSQLiteStorage:
    """Explicit-lifecycle SQLite archive for historical market data."""

    backend_identity = "market-data-sqlite"
    schema_version = 1

    def __init__(self, database_path: Path | str, *, busy_timeout_ms: int = 5_000):
        self.database_path = Path(database_path).expanduser().resolve()
        self.busy_timeout_ms = int(busy_timeout_ms)
        if self.busy_timeout_ms < 0:
            raise ValueError("busy timeout must be nonnegative")
        self._opened = False
        self._lifecycle_lock = threading.RLock()

    # ------------------------------------------------------------------
    # lifecycle
    # ------------------------------------------------------------------

    def _connect(self) -> sqlite3.Connection:
        if not self._opened:
            raise StorageError("market data archive is not open")
        connection = sqlite3.connect(
            self.database_path,
            timeout=self.busy_timeout_ms / 1000,
            isolation_level=None,
        )
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute(f"PRAGMA busy_timeout = {self.busy_timeout_ms}")
        return connection

    def open(self) -> None:
        with self._lifecycle_lock:
            if self._opened:
                return
            self.database_path.parent.mkdir(parents=True, exist_ok=True)
            self._opened = True
            connection: sqlite3.Connection | None = None
            try:
                connection = self._connect()
                connection.execute("PRAGMA journal_mode = WAL")
                for statement in _SCHEMA:
                    connection.execute(statement)
            except Exception:
                self._opened = False
                raise
            finally:
                if connection is not None:
                    connection.close()

    def close(self) -> None:
        with self._lifecycle_lock:
            self._opened = False

    def __enter__(self) -> "MarketDataSQLiteStorage":
        self.open()
        return self

    def __exit__(self, exc_type, exc, traceback) -> bool:
        self.close()
        return False

    # ------------------------------------------------------------------
    # writes
    # ------------------------------------------------------------------

    def store_batch(self, batch: FetchBatch) -> WriteResult:
        """Persist ``batch`` idempotently and report exactly what changed."""

        bars = sorted(batch.bars, key=lambda item: item.open_time_ms)
        batch_id = batch.batch_id
        checksum = batch.checksum

        connection = self._connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            try:
                batch_was_new = self._insert_batch(
                    connection, batch, bars, batch_id, checksum
                )
                inserted, already_present, conflicts = self._insert_bars(
                    connection, batch, bars, batch_id
                )
                if batch_was_new and inserted == 0:
                    # No bar references this batch row, so it carries no
                    # provenance. Drop it rather than leaving an orphan.
                    connection.execute(
                        "DELETE FROM market_data_batches WHERE batch_id = ?",
                        (batch_id,),
                    )
                    batch_was_new = False
                connection.execute("COMMIT")
            except Exception:
                connection.execute("ROLLBACK")
                raise
        finally:
            connection.close()

        return WriteResult(
            batch_id=batch_id,
            checksum=checksum,
            inserted=inserted,
            already_present=already_present,
            conflicts=tuple(conflicts),
            batch_was_new=batch_was_new,
        )

    @staticmethod
    def _insert_batch(
        connection: sqlite3.Connection,
        batch: FetchBatch,
        bars: Sequence[ArchivedBar],
        batch_id: str,
        checksum: str,
    ) -> bool:
        cursor = connection.execute(
            """
            INSERT INTO market_data_batches (
                batch_id, source, endpoint, provider_version, symbol,
                timeframe, fetched_at, checksum, bar_count,
                first_open_time_ms, last_open_time_ms,
                requested_start_ms, requested_end_ms
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(batch_id) DO NOTHING
            """,
            (
                batch_id,
                batch.source,
                batch.endpoint,
                batch.provider_version,
                batch.symbol,
                batch.timeframe,
                batch.fetched_at.astimezone(UTC).isoformat(),
                checksum,
                len(bars),
                bars[0].open_time_ms,
                bars[-1].open_time_ms,
                batch.requested_start_ms,
                batch.requested_end_ms,
            ),
        )
        return cursor.rowcount == 1

    def _insert_bars(
        self,
        connection: sqlite3.Connection,
        batch: FetchBatch,
        bars: Sequence[ArchivedBar],
        batch_id: str,
    ) -> tuple[int, int, list[BarConflict]]:
        existing = self._existing_bars(connection, batch, bars)

        conflicts: list[BarConflict] = []
        pending: list[tuple[Any, ...]] = []
        already_present = 0

        for bar in bars:
            archived = existing.get(bar.open_time_ms)
            if archived is None:
                pending.append((
                    bar.symbol,
                    bar.timeframe,
                    bar.open_time_ms,
                    bar.close_time_ms,
                    bar.open,
                    bar.high,
                    bar.low,
                    bar.close,
                    bar.volume,
                    bar.quote_volume,
                    bar.trades,
                    batch.source,
                    batch_id,
                ))
                continue
            already_present += 1
            conflicts.extend(_compare_bar(bar, archived))

        if pending:
            connection.executemany(
                """
                INSERT INTO market_data_bars (
                    symbol, timeframe, open_time_ms, close_time_ms,
                    open, high, low, close, volume,
                    quote_volume, trades, source, batch_id
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(symbol, timeframe, open_time_ms) DO NOTHING
                """,
                pending,
            )

        return len(pending), already_present, conflicts

    @staticmethod
    def _existing_bars(
        connection: sqlite3.Connection,
        batch: FetchBatch,
        bars: Sequence[ArchivedBar],
    ) -> dict[int, sqlite3.Row]:
        rows = connection.execute(
            f"""
            SELECT open_time_ms, {", ".join(_BAR_COLUMNS)}
            FROM market_data_bars
            WHERE symbol = ? AND timeframe = ?
              AND open_time_ms BETWEEN ? AND ?
            """,
            (
                batch.symbol,
                batch.timeframe,
                bars[0].open_time_ms,
                bars[-1].open_time_ms,
            ),
        ).fetchall()
        return {int(row["open_time_ms"]): row for row in rows}

    # ------------------------------------------------------------------
    # reads
    # ------------------------------------------------------------------

    def get_batch(self, batch_id: str) -> BatchProvenance | None:
        connection = self._connect()
        try:
            row = connection.execute(
                "SELECT * FROM market_data_batches WHERE batch_id = ?",
                (batch_id,),
            ).fetchone()
        finally:
            connection.close()
        if row is None:
            return None
        return BatchProvenance(
            batch_id=row["batch_id"],
            source=row["source"],
            endpoint=row["endpoint"],
            provider_version=row["provider_version"],
            symbol=row["symbol"],
            timeframe=row["timeframe"],
            fetched_at=datetime.fromisoformat(row["fetched_at"]),
            checksum=row["checksum"],
            bar_count=int(row["bar_count"]),
            first_open_time_ms=int(row["first_open_time_ms"]),
            last_open_time_ms=int(row["last_open_time_ms"]),
            requested_start_ms=row["requested_start_ms"],
            requested_end_ms=row["requested_end_ms"],
        )

    def provenance_for_bar(
        self, symbol: str, timeframe: str, open_time_ms: int
    ) -> BatchProvenance | None:
        """Return the fetch batch that a specific archived bar came from."""

        connection = self._connect()
        try:
            row = connection.execute(
                """
                SELECT batch_id FROM market_data_bars
                WHERE symbol = ? AND timeframe = ? AND open_time_ms = ?
                """,
                (symbol, timeframe, open_time_ms),
            ).fetchone()
        finally:
            connection.close()
        if row is None:
            return None
        return self.get_batch(row["batch_id"])

    def get_bars(
        self,
        symbol: str,
        timeframe: str,
        *,
        start_ms: int | None = None,
        end_ms: int | None = None,
    ) -> tuple[ArchivedBar, ...]:
        clauses = ["symbol = ?", "timeframe = ?"]
        parameters: list[Any] = [symbol, timeframe]
        if start_ms is not None:
            clauses.append("open_time_ms >= ?")
            parameters.append(start_ms)
        if end_ms is not None:
            clauses.append("open_time_ms <= ?")
            parameters.append(end_ms)

        connection = self._connect()
        try:
            rows = connection.execute(
                f"""
                SELECT symbol, timeframe, open_time_ms, {", ".join(_BAR_COLUMNS)}
                FROM market_data_bars
                WHERE {" AND ".join(clauses)}
                ORDER BY open_time_ms
                """,
                parameters,
            ).fetchall()
        finally:
            connection.close()

        return tuple(
            ArchivedBar(
                symbol=row["symbol"],
                timeframe=row["timeframe"],
                open_time_ms=int(row["open_time_ms"]),
                close_time_ms=row["close_time_ms"],
                open=row["open"],
                high=row["high"],
                low=row["low"],
                close=row["close"],
                volume=row["volume"],
                quote_volume=row["quote_volume"],
                trades=row["trades"],
            )
            for row in rows
        )

    def last_open_time_ms(self, symbol: str, timeframe: str) -> int | None:
        """Latest archived open time, used to resume an interrupted fetch."""

        connection = self._connect()
        try:
            row = connection.execute(
                """
                SELECT MAX(open_time_ms) AS last_open
                FROM market_data_bars
                WHERE symbol = ? AND timeframe = ?
                """,
                (symbol, timeframe),
            ).fetchone()
        finally:
            connection.close()
        if row is None or row["last_open"] is None:
            return None
        return int(row["last_open"])

    def archived_pairs(self) -> tuple[tuple[str, str], ...]:
        connection = self._connect()
        try:
            rows = connection.execute(
                """
                SELECT DISTINCT symbol, timeframe
                FROM market_data_bars
                ORDER BY symbol, timeframe
                """
            ).fetchall()
        finally:
            connection.close()
        return tuple((row["symbol"], row["timeframe"]) for row in rows)

    # ------------------------------------------------------------------
    # coverage and verification
    # ------------------------------------------------------------------

    def coverage(self, symbol: str, timeframe: str) -> CoverageReport:
        """Report exact coverage, including every gap. Nothing is filled in."""

        interval_ms = timeframe_to_milliseconds(timeframe)

        connection = self._connect()
        try:
            open_times = [
                int(row["open_time_ms"])
                for row in connection.execute(
                    """
                    SELECT open_time_ms FROM market_data_bars
                    WHERE symbol = ? AND timeframe = ?
                    ORDER BY open_time_ms
                    """,
                    (symbol, timeframe),
                )
            ]
        finally:
            connection.close()

        if not open_times:
            return CoverageReport(
                symbol=symbol,
                timeframe=timeframe,
                bar_count=0,
                first_open_time_ms=None,
                last_open_time_ms=None,
                expected_bars=0,
                missing_bars=0,
            )

        gaps: list[CoverageGap] = []
        for previous, current in zip(open_times, open_times[1:]):
            step = current - previous
            if step == interval_ms:
                continue
            missing = (step // interval_ms) - 1
            gaps.append(
                CoverageGap(
                    gap_start_ms=previous + interval_ms,
                    gap_end_ms=current - interval_ms,
                    missing_bars=int(missing),
                )
            )

        first_open = open_times[0]
        last_open = open_times[-1]
        expected = ((last_open - first_open) // interval_ms) + 1

        return CoverageReport(
            symbol=symbol,
            timeframe=timeframe,
            bar_count=len(open_times),
            first_open_time_ms=first_open,
            last_open_time_ms=last_open,
            expected_bars=int(expected),
            missing_bars=int(expected) - len(open_times),
            gaps=tuple(gaps),
        )

    def verify_batch(self, batch_id: str) -> bool:
        """Recompute a batch checksum from the archived rows it produced.

        Returns ``False`` when the batch is unknown, when some of its bars are
        no longer attributed to it, or when the recomputed digest differs from
        the digest recorded at fetch time.
        """

        provenance = self.get_batch(batch_id)
        if provenance is None:
            return False

        connection = self._connect()
        try:
            rows = connection.execute(
                f"""
                SELECT symbol, timeframe, open_time_ms, {", ".join(_BAR_COLUMNS)}
                FROM market_data_bars
                WHERE batch_id = ?
                ORDER BY open_time_ms
                """,
                (batch_id,),
            ).fetchall()
        finally:
            connection.close()

        if len(rows) != provenance.bar_count:
            return False

        bars = tuple(
            ArchivedBar(
                symbol=row["symbol"],
                timeframe=row["timeframe"],
                open_time_ms=int(row["open_time_ms"]),
                close_time_ms=row["close_time_ms"],
                open=row["open"],
                high=row["high"],
                low=row["low"],
                close=row["close"],
                volume=row["volume"],
                quote_volume=row["quote_volume"],
                trades=row["trades"],
            )
            for row in rows
        )
        return batch_checksum(bars) == provenance.checksum

    def health(self) -> dict[str, Any]:
        status: dict[str, Any] = {
            "backend": self.backend_identity,
            "connected": self._opened,
            "schema_version": self.schema_version,
            "database_path": str(self.database_path),
            "bar_count": None,
            "batch_count": None,
        }
        if not self._opened:
            return status
        connection = self._connect()
        try:
            status["bar_count"] = int(
                connection.execute(
                    "SELECT COUNT(*) FROM market_data_bars"
                ).fetchone()[0]
            )
            status["batch_count"] = int(
                connection.execute(
                    "SELECT COUNT(*) FROM market_data_batches"
                ).fetchone()[0]
            )
        finally:
            connection.close()
        return status


def _compare_bar(incoming: ArchivedBar, archived: sqlite3.Row) -> list[BarConflict]:
    conflicts: list[BarConflict] = []
    for column in _BAR_COLUMNS:
        archived_value = archived[column]
        incoming_value = getattr(incoming, column)
        if archived_value == incoming_value:
            continue
        conflicts.append(
            BarConflict(
                open_time_ms=incoming.open_time_ms,
                field_name=column,
                archived_value=archived_value,
                incoming_value=incoming_value,
            )
        )
    return conflicts
