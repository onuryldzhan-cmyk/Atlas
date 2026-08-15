"""SQLite development/test reference backend for the market-data repositories.

Implements the Package-1 Protocols in data_layer.market_data_contracts without
modifying them: `MarketDataSQLiteStorage` owns lifecycle (open/close/health) the
way `StorageBackend` does for the execution schema, and vends the two repository
objects, so the Protocols themselves stay adapter-free.

This is a reference backend for local development, tests, and validation. It
persists dataset *manifests and identities* only -- metadata about dataset
builds. It stores no OHLCV, tick, order-book, or per-record market data, and no
MarketDataQualityStatus: nothing in the Package-1 Protocols addresses those, and
inventing storage for them would pre-empt the ingestion schema that owns them.
Its practical volume ceiling is therefore manifest count, not market-data
volume, and the O(rows) validation performed at open() is the scaling limit.

Bounded context
---------------
Market-data storage is separate from data_layer.contracts.UnitOfWork
(orders/executions/positions). It uses its own database file, its own
connections, its own transaction boundary, and its own migration sequence, and
it is never registered on the execution UnitOfWork. No execution-domain record
type is imported. This module is deliberately unwired: nothing constructs it,
and data_layer/__init__.py must not re-export it, which is what keeps it out of
the runtime closure.

Transaction model
-----------------
One repository method call is one transaction. The Protocols expose no
transaction handle, so the adapter owns the boundary internally -- which is also
the portable choice. Writes take `BEGIN IMMEDIATE`; a connection is opened and
closed per operation, so there is no shared connection, no thread affinity
hazard, and no global or singleton state.

Duplicate and conflict semantics
--------------------------------
A write whose key already exists is resolved by reconstructing the *complete*
stored Package-1 object and comparing it with the requested one, rather than by
comparing a hand-picked subset of columns: a field added to a Package-1 value
object later cannot be silently omitted from that comparison. An equal object is
an idempotent no-op -- a writer retrying after a crash between write and
acknowledgement must not be punished, and rejecting identical rewrites would
force callers into a TOCTOU pre-check. A differing object raises RecordConflict.
Nothing is ever overwritten; there is no INSERT OR REPLACE and no upsert.

Time is serialization, never comparison authority
-------------------------------------------------
Stored `*_utc` values are Package-1 serialized instants. They are variable width
(fractional seconds are omitted when zero), so their lexical order does not match
their chronological order. No CHECK, index, ORDER BY, MIN, or MAX in this module
touches a timestamp column. `list_for_identity` orders by content_hash, which is
deterministic, content-derived, and carries no temporal meaning -- ordering by
generated_at would both be unsound as text and reintroduce the implicit
"latest revision" semantic that Package 1 deliberately refuses to define.

PostgreSQL boundary
-------------------
No rowid reliance, no SQLite-only upsert, no affinity tricks, no implicit
ordering, and no correctness that depends on a PRAGMA going unverified.
`json_valid` is defense in depth only; the Package-1 constructors remain the
reconstruction authority. The ordering domain is fixed-width lowercase hex, so
`ORDER BY content_hash` is identical under SQLite's BINARY collation and any
PostgreSQL collation.

One portability seam is NOT a mechanical translation, and a future PostgreSQL
adapter must handle it deliberately rather than transcribing this module:

    Duplicate writes are resolved by SELECT-before-INSERT (see _store_identity
    and put_manifest). That sequence is safe *here* only because SQLite's
    `BEGIN IMMEDIATE` takes the write lock at transaction start, which
    serializes writers for the whole method call: a concurrent writer either
    waits or fails with a busy timeout, so no second writer can slip between
    this transaction's SELECT and its INSERT.

    PostgreSQL READ COMMITTED provides no such serialization. Two concurrent
    calls writing the same key can both observe "absent" and both attempt the
    INSERT; one then fails with a unique violation instead of returning the
    idempotent no-op this repository contract promises.

    A PostgreSQL adapter must therefore preserve the contract explicitly --
    translate the unique violation into a re-read plus the same complete-object
    comparison used here (equal -> no-op, different -> RecordConflict), or use
    an equivalent conflict-safe formulation. What must be preserved is the
    repository behaviour, not this module's SQL.

This is a portability seam, not an active defect in the SQLite backend: under
SQLite the serialization above holds, and the duplicate/conflict semantics
documented in this module are the observed behaviour.
"""

from __future__ import annotations

import json
import sqlite3
import threading
from contextlib import contextmanager
from collections.abc import Iterator
from pathlib import Path
from typing import Any

from .contracts import (
    IntegrityViolation,
    RecordConflict,
    StorageConfigurationError,
    StorageError,
)
from .market_data_migrations import MARKET_DATA_MIGRATIONS, MARKET_DATA_TABLES
from .market_data_models import (
    DataProvenance,
    DataTimestamp,
    DatasetIdentity,
    DatasetManifest,
    TimeSemantic,
    sha256_hex,
)
from .migrations import apply_migrations

# SQLite stores integers in at most 8 signed bytes; a larger value would raise
# OverflowError out of the driver, which is not part of the storage taxonomy.
_MAX_SQLITE_INTEGER = 2**63 - 1

_IDENTITY_COLUMNS = (
    "identity_digest, source, venue, instruments_json, range_start_utc, "
    "range_end_utc, timeframe, schema_version, transform_version"
)

_SELECT_IDENTITY_BY_DIGEST = (
    f"SELECT {_IDENTITY_COLUMNS} FROM market_data_dataset_identities WHERE identity_digest = ?"
)

_SELECT_ALL_IDENTITIES = f"SELECT {_IDENTITY_COLUMNS} FROM market_data_dataset_identities"

_INSERT_IDENTITY = """
    INSERT INTO market_data_dataset_identities (
        identity_digest, source, venue, instruments_json, range_start_utc,
        range_end_utc, timeframe, schema_version, transform_version
    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
"""

# A LEFT JOIN rather than an INNER JOIN so that a manifest whose parent identity
# is missing surfaces as a fail-closed IntegrityViolation instead of silently
# disappearing from the result set.
_MANIFEST_SELECT = """
    SELECT m.content_hash, m.identity_digest, m.record_count, m.generated_at_utc,
           m.provenance_source, m.provenance_venue, m.provenance_schema_version,
           m.provenance_ingested_at_utc, m.provenance_record_content_hash,
           m.provenance_upstream_identity_digest,
           i.source, i.venue, i.instruments_json, i.range_start_utc,
           i.range_end_utc, i.timeframe, i.schema_version, i.transform_version
    FROM market_data_manifests AS m
    LEFT JOIN market_data_dataset_identities AS i
        ON i.identity_digest = m.identity_digest
"""

_SELECT_MANIFEST_BY_CONTENT_HASH = f"{_MANIFEST_SELECT} WHERE m.content_hash = ?"

_SELECT_MANIFESTS_FOR_IDENTITY = (
    f"{_MANIFEST_SELECT} WHERE m.identity_digest = ? ORDER BY m.content_hash ASC"
)

_SELECT_ALL_MANIFESTS = f"{_MANIFEST_SELECT} ORDER BY m.content_hash ASC"

_INSERT_MANIFEST = """
    INSERT INTO market_data_manifests (
        content_hash, identity_digest, record_count, generated_at_utc,
        provenance_source, provenance_venue, provenance_schema_version,
        provenance_ingested_at_utc, provenance_record_content_hash,
        provenance_upstream_identity_digest
    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
"""


def _translate_sqlite_failure(exc: sqlite3.Error) -> StorageError:
    """Map one driver failure onto the storage taxonomy.

    Constraint violations (primary key, foreign key, CHECK, NOT NULL) are
    persistence-invariant failures and become IntegrityViolation; everything
    else the driver raises is an operational failure and becomes StorageError.

    Factored out so that statement execution and row retrieval translate
    identically instead of drifting apart in duplicated except blocks. Only
    sqlite3.Error is ever passed here, so the storage taxonomy's own
    exceptions -- RecordConflict, IntegrityViolation, MigrationError -- are
    never caught and re-wrapped by this boundary.
    """

    if isinstance(exc, sqlite3.IntegrityError):
        return IntegrityViolation(f"market-data relational integrity violation: {exc}")
    return StorageError(f"market-data storage operation failed: {exc}")


def _execute(connection: sqlite3.Connection, sql: str, parameters: tuple[Any, ...] = ()) -> sqlite3.Cursor:
    """Run a statement that returns no rows to the caller.

    Retrieval must go through _query_one/_query_all instead: SQLite reports
    some failures only while stepping the cursor, which happens after this
    function has returned. See those helpers.
    """

    try:
        return connection.execute(sql, parameters)
    except sqlite3.Error as exc:
        raise _translate_sqlite_failure(exc) from exc


def _query_one(
    connection: sqlite3.Connection, sql: str, parameters: tuple[Any, ...] = ()
) -> sqlite3.Row | None:
    """Run a query and take its first row inside one translation boundary.

    Executing and fetching are wrapped together because SQLite does not report
    every failure at execute() time: a malformed database image, for instance,
    can surface while the cursor is being stepped. Splitting the two would
    leave that second window unwrapped and let a raw sqlite3 exception escape a
    public repository method.
    """

    try:
        return connection.execute(sql, parameters).fetchone()
    except sqlite3.Error as exc:
        raise _translate_sqlite_failure(exc) from exc


def _query_all(
    connection: sqlite3.Connection, sql: str, parameters: tuple[Any, ...] = ()
) -> list[sqlite3.Row]:
    """Run a query and drain it inside one translation boundary.

    The widest fetch-time window in this module: draining a multi-row result
    steps the cursor once per row, so every one of those steps must sit inside
    the same translation as the execute() that started it.
    """

    try:
        return connection.execute(sql, parameters).fetchall()
    except sqlite3.Error as exc:
        raise _translate_sqlite_failure(exc) from exc


def _identity_from_row(row: sqlite3.Row) -> DatasetIdentity:
    """Rebuild a DatasetIdentity, re-running every Package-1 invariant.

    Semantics are pinned rather than stored (D10): the DatasetIdentity
    constructor already requires EVENT_TIME for both range bounds, so a stored
    semantic column could only ever hold one value while adding a drift mode
    with no detection benefit.
    """

    raw_instruments = row["instruments_json"]
    try:
        instruments = json.loads(raw_instruments)
    except (TypeError, ValueError) as exc:
        raise IntegrityViolation("stored dataset instruments are not valid JSON") from exc
    if not isinstance(instruments, list) or not all(isinstance(item, str) for item in instruments):
        raise IntegrityViolation("stored dataset instruments must be a JSON array of strings")
    return DatasetIdentity(
        source=row["source"],
        venue=row["venue"],
        instruments=tuple(instruments),
        range_start=DataTimestamp(value=row["range_start_utc"], semantic=TimeSemantic.EVENT_TIME),
        range_end=DataTimestamp(value=row["range_end_utc"], semantic=TimeSemantic.EVENT_TIME),
        timeframe=row["timeframe"],
        schema_version=row["schema_version"],
        transform_version=row["transform_version"],
    )


def _manifest_from_row(row: sqlite3.Row) -> DatasetManifest:
    """Rebuild a DatasetManifest together with its joined DatasetIdentity.

    The DatasetManifest constructor re-checks that provenance source, venue,
    and schema_version agree with the identity's, so this read path fails
    closed on a disagreement even though the composite foreign key already
    makes one unrepresentable through this backend.
    """

    if row["source"] is None:
        raise IntegrityViolation(
            f"manifest references dataset identity {row['identity_digest']}, which is not stored"
        )
    return DatasetManifest(
        identity=_identity_from_row(row),
        content_hash=row["content_hash"],
        record_count=row["record_count"],
        provenance=DataProvenance(
            source=row["provenance_source"],
            venue=row["provenance_venue"],
            schema_version=row["provenance_schema_version"],
            ingested_at=DataTimestamp(
                value=row["provenance_ingested_at_utc"], semantic=TimeSemantic.INGESTION_TIME
            ),
            record_content_hash=row["provenance_record_content_hash"],
            upstream_identity_digest=row["provenance_upstream_identity_digest"],
        ),
        generated_at=DataTimestamp(
            value=row["generated_at_utc"], semantic=TimeSemantic.SNAPSHOT_TIME
        ),
    )


def _identity_parameters(identity: DatasetIdentity, identity_digest: str) -> tuple[Any, ...]:
    return (
        identity_digest,
        identity.source,
        identity.venue,
        # Deterministic because DatasetIdentity has already normalized and
        # sorted the universe; the constructor re-derives the tuple on read.
        json.dumps(list(identity.instruments), separators=(",", ":")),
        identity.range_start.isoformat(),
        identity.range_end.isoformat(),
        identity.timeframe,
        identity.schema_version,
        identity.transform_version,
    )


def _manifest_parameters(manifest: DatasetManifest, identity_digest: str) -> tuple[Any, ...]:
    if manifest.record_count > _MAX_SQLITE_INTEGER:
        raise IntegrityViolation("record_count exceeds the storable integer range")
    provenance = manifest.provenance
    return (
        manifest.content_hash,
        identity_digest,
        manifest.record_count,
        manifest.generated_at.isoformat(),
        provenance.source,
        provenance.venue,
        provenance.schema_version,
        provenance.ingested_at.isoformat(),
        provenance.record_content_hash,
        provenance.upstream_identity_digest,
    )


def _store_identity(
    connection: sqlite3.Connection, identity: DatasetIdentity, identity_digest: str
) -> None:
    """Insert the identity, or accept it as already stored, inside the caller's transaction.

    The SELECT-before-INSERT below is safe under SQLite because the caller
    holds a BEGIN IMMEDIATE write lock for the whole method call. A future
    PostgreSQL adapter must not transcribe it unguarded -- see the PostgreSQL
    boundary section of the module docstring.
    """

    row = _query_one(connection, _SELECT_IDENTITY_BY_DIGEST, (identity_digest,))
    if row is None:
        _execute(connection, _INSERT_IDENTITY, _identity_parameters(identity, identity_digest))
        return
    stored = _identity_from_row(row)
    if stored == identity:
        return
    # identity_digest covers every field of the canonical payload, so a stored
    # row that differs while keying to the same digest is corrupt far more
    # plausibly than it is a SHA-256 collision. Recomputing separates the two
    # so corruption is not misreported as a caller conflict.
    if stored.identity_digest() != identity_digest:
        raise IntegrityViolation(
            f"stored dataset identity {identity_digest} is corrupt: "
            "its recomputed digest does not match its stored key"
        )
    raise RecordConflict(
        f"dataset identity {identity_digest} is already stored with a different payload"
    )


class SQLiteDatasetRepository:
    """DatasetRepository backed by SQLite; keyed by DatasetIdentity.identity_digest()."""

    def __init__(self, storage: "MarketDataSQLiteStorage") -> None:
        self._storage = storage

    def register(self, identity: DatasetIdentity) -> None:
        if not isinstance(identity, DatasetIdentity):
            raise IntegrityViolation("identity must be a DatasetIdentity")
        identity_digest = identity.identity_digest()
        with self._storage._write_transaction() as connection:
            _store_identity(connection, identity, identity_digest)

    def get(self, identity_digest: str) -> DatasetIdentity | None:
        key = sha256_hex(identity_digest, "identity_digest")
        connection = self._storage._operational_connection()
        try:
            row = _query_one(connection, _SELECT_IDENTITY_BY_DIGEST, (key,))
        finally:
            connection.close()
        return None if row is None else _identity_from_row(row)

    def exists(self, identity_digest: str) -> bool:
        key = sha256_hex(identity_digest, "identity_digest")
        connection = self._storage._operational_connection()
        try:
            row = _query_one(
                connection,
                "SELECT 1 FROM market_data_dataset_identities WHERE identity_digest = ?",
                (key,),
            )
        finally:
            connection.close()
        return row is not None


class SQLiteMarketDataRepository:
    """MarketDataRepository backed by SQLite across the two Package-1 key spaces."""

    def __init__(self, storage: "MarketDataSQLiteStorage") -> None:
        self._storage = storage

    def put_manifest(self, manifest: DatasetManifest) -> None:
        """Persist one concrete revision and its logical identity atomically."""

        if not isinstance(manifest, DatasetManifest):
            raise IntegrityViolation("manifest must be a DatasetManifest")
        identity_digest = manifest.logical_identity_digest
        parameters = _manifest_parameters(manifest, identity_digest)
        with self._storage._write_transaction() as connection:
            # Same transaction as the manifest insert, so a manifest whose
            # parent identity is missing cannot survive a failure here.
            _store_identity(connection, manifest.identity, identity_digest)
            row = _query_one(
                connection, _SELECT_MANIFEST_BY_CONTENT_HASH, (manifest.content_hash,)
            )
            if row is not None:
                if _manifest_from_row(row) == manifest:
                    return
                raise RecordConflict(
                    f"dataset manifest {manifest.content_hash} is already stored with a "
                    "different payload"
                )
            _execute(connection, _INSERT_MANIFEST, parameters)

    def get_manifest(self, content_hash: str) -> DatasetManifest | None:
        """Return the one concrete revision bearing this content hash, or None.

        Addressed by content_hash only. Passing an identity_digest is a valid
        digest but a different key space, so it correctly finds nothing.
        """

        key = sha256_hex(content_hash, "content_hash")
        connection = self._storage._operational_connection()
        try:
            row = _query_one(connection, _SELECT_MANIFEST_BY_CONTENT_HASH, (key,))
        finally:
            connection.close()
        return None if row is None else _manifest_from_row(row)

    def list_for_identity(self, identity_digest: str) -> tuple[DatasetManifest, ...]:
        """Every concrete manifest for this logical identity, ordered by content_hash.

        Never collapses the 1:N relation and never implies a latest revision.
        The ordering domain is fixed-length lowercase hex, so it is identical
        under SQLite's BINARY collation, Python's sort, and any PostgreSQL
        collation.
        """

        key = sha256_hex(identity_digest, "identity_digest")
        connection = self._storage._operational_connection()
        try:
            rows = _query_all(connection, _SELECT_MANIFESTS_FOR_IDENTITY, (key,))
        finally:
            connection.close()
        return tuple(_manifest_from_row(row) for row in rows)


class MarketDataSQLiteStorage:
    """Explicit-lifecycle SQLite backend for the market-data bounded context."""

    backend_identity = "market-data-sqlite-local"
    capabilities = frozenset({
        "transactions", "foreign_keys", "wal", "busy_timeout",
        "checksummed_migrations", "content_addressed_manifests",
    })

    STATE_SUBDIRECTORY = "market_data"
    DATABASE_FILENAME = "market_data.sqlite3"

    def __init__(self, *, state_directory: Path | str, busy_timeout_ms: int = 5_000) -> None:
        """Bind the backend to an explicit, absolute state directory.

        state_directory is keyword-only and has no default, so no caller or
        test can reach Atlas's real runtime state by omitting it, and a
        relative path is rejected outright rather than being resolved against
        the process working directory.
        """

        directory = Path(state_directory).expanduser()
        if not directory.is_absolute():
            raise StorageConfigurationError(
                f"state_directory must be an absolute path, got {str(directory)!r}; "
                "a relative path would resolve against the process working directory"
            )
        self.state_directory = directory.resolve()
        self.database_path = self.state_directory / self.STATE_SUBDIRECTORY / self.DATABASE_FILENAME
        self.busy_timeout_ms = int(busy_timeout_ms)
        if self.busy_timeout_ms < 0:
            raise ValueError("busy timeout must be nonnegative")
        self._opened = False
        self._lifecycle_lock = threading.RLock()
        self._last_integrity_check: str | None = None
        self.datasets = SQLiteDatasetRepository(self)
        self.market_data = SQLiteMarketDataRepository(self)

    # -- lifecycle ---------------------------------------------------------

    def open(self) -> None:
        """Validate the directory, migrate, and verify every stored row.

        Fails closed on any problem: the backend stays unopened and the
        database file is neither repaired, recreated, nor deleted.
        """

        with self._lifecycle_lock:
            if self._opened:
                return
            self._prepare_directories()
            connection = self._new_connection()
            try:
                try:
                    # Persistent header setting; performance only, never load
                    # bearing for any correctness property in this module.
                    connection.execute("PRAGMA journal_mode = WAL")
                except sqlite3.Error as exc:
                    raise StorageError(
                        f"could not configure the market-data journal mode: {exc}"
                    ) from exc
                apply_migrations(connection, MARKET_DATA_MIGRATIONS)
                self._verify_sqlite_integrity(connection)
                self._verify_expected_tables(connection)
                self._validate_stored_identities(connection)
                self._validate_stored_manifests(connection)
            except sqlite3.Error as exc:
                self._last_integrity_check = "FAIL"
                raise StorageError(f"market-data database could not be opened: {exc}") from exc
            except Exception:
                self._last_integrity_check = "FAIL"
                raise
            finally:
                connection.close()
            self._opened = True
            self._last_integrity_check = "PASS"

    def close(self) -> None:
        with self._lifecycle_lock:
            self._opened = False

    # -- paths -------------------------------------------------------------

    def _prepare_directories(self) -> None:
        root = self.state_directory
        if not root.exists():
            raise StorageConfigurationError(f"state_directory does not exist: {root}")
        if not root.is_dir():
            raise StorageConfigurationError(f"state_directory is not a directory: {root}")
        leaf = root / self.STATE_SUBDIRECTORY
        try:
            # parents=False: a missing ancestor is a caller error, not
            # something to fabricate. Only this leaf may be created.
            leaf.mkdir(parents=False, exist_ok=True)
        except OSError as exc:
            raise StorageConfigurationError(
                f"could not create the market-data directory {leaf}: {exc}"
            ) from exc
        resolved_leaf = leaf.resolve()
        if not resolved_leaf.is_relative_to(root):
            raise StorageConfigurationError(
                f"the market-data directory resolves to {resolved_leaf}, outside the supplied "
                f"state_directory {root}"
            )
        if resolved_leaf != self.database_path.parent:
            raise StorageConfigurationError(
                f"the market-data directory resolves to {resolved_leaf}, not to the expected "
                f"{self.database_path.parent}"
            )

    # -- connections -------------------------------------------------------

    def _new_connection(self) -> sqlite3.Connection:
        try:
            connection = sqlite3.connect(
                self.database_path,
                timeout=self.busy_timeout_ms / 1000,
                isolation_level=None,
            )
        except sqlite3.Error as exc:
            raise StorageError(f"could not open the market-data database: {exc}") from exc
        try:
            connection.row_factory = sqlite3.Row
            try:
                connection.execute("PRAGMA foreign_keys = ON")
                connection.execute(f"PRAGMA busy_timeout = {self.busy_timeout_ms}")
                enforcing = connection.execute("PRAGMA foreign_keys").fetchone()
            except sqlite3.Error as exc:
                raise StorageError(
                    f"could not configure the market-data connection: {exc}"
                ) from exc
            # SQLite silently ignores this PRAGMA when built without foreign-key
            # support, which would leave the composite identity/provenance
            # constraint and orphan-manifest prevention unenforced. Reading it
            # back turns a silently-ignored setting into a fail-closed error.
            if enforcing is None or int(enforcing[0]) != 1:
                raise StorageError(
                    "SQLite is not enforcing foreign keys; market-data identity/provenance "
                    "consistency and orphan-manifest prevention would be unenforced"
                )
        except BaseException:
            connection.close()
            raise
        return connection

    def _operational_connection(self) -> sqlite3.Connection:
        if not self._opened:
            raise StorageError("market-data storage backend is not open")
        return self._new_connection()

    @contextmanager
    def _write_transaction(self) -> Iterator[sqlite3.Connection]:
        """One repository call, one immediate transaction, always closed."""

        connection = self._operational_connection()
        try:
            try:
                connection.execute("BEGIN IMMEDIATE")
            except sqlite3.Error as exc:
                raise StorageError(
                    f"could not begin a market-data write transaction: {exc}"
                ) from exc
            try:
                yield connection
            except BaseException:
                try:
                    connection.rollback()
                except sqlite3.Error:
                    pass
                raise
            try:
                connection.commit()
            except sqlite3.Error as exc:
                raise StorageError(
                    f"could not commit the market-data write transaction: {exc}"
                ) from exc
        finally:
            connection.close()

    # -- open-time validation ----------------------------------------------

    @staticmethod
    def _verify_sqlite_integrity(connection: sqlite3.Connection) -> None:
        result = connection.execute("PRAGMA integrity_check").fetchone()
        if result is None or result[0] != "ok":
            raise StorageError("market-data SQLite integrity check failed")

    @staticmethod
    def _verify_expected_tables(connection: sqlite3.Connection) -> None:
        """Catch a table dropped after its migration was recorded as applied."""

        present = {
            row[0]
            for row in connection.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
        }
        missing = [
            name
            for name in (*MARKET_DATA_TABLES, "atlas_schema_migrations")
            if name not in present
        ]
        if missing:
            raise StorageError(
                f"market-data database is missing required tables: {', '.join(missing)}"
            )

    @staticmethod
    def _validate_stored_identities(connection: sqlite3.Connection) -> None:
        for row in connection.execute(_SELECT_ALL_IDENTITIES):
            identity_digest = row["identity_digest"]
            try:
                identity = _identity_from_row(row)
            except IntegrityViolation as exc:
                raise IntegrityViolation(
                    f"stored dataset identity {identity_digest} is invalid: {exc}"
                ) from exc
            # The digest covers every canonical field, so recomputing it
            # detects any edit to any identity column.
            if identity.identity_digest() != identity_digest:
                raise IntegrityViolation(
                    f"stored dataset identity {identity_digest} is corrupt: "
                    "its recomputed digest does not match its stored key"
                )

    @staticmethod
    def _validate_stored_manifests(connection: sqlite3.Connection) -> None:
        # content_hash digests external dataset content that Atlas does not
        # store, so unlike identity_digest it cannot be recomputed here.
        # Structural reconstruction, identity/provenance agreement, and orphan
        # detection are the available guarantees for manifests.
        for row in connection.execute(_SELECT_ALL_MANIFESTS):
            try:
                _manifest_from_row(row)
            except IntegrityViolation as exc:
                raise IntegrityViolation(
                    f"stored dataset manifest {row['content_hash']} is invalid: {exc}"
                ) from exc

    # -- diagnostics -------------------------------------------------------

    @property
    def schema_version(self) -> int:
        connection = self._operational_connection()
        try:
            row = _query_one(
                connection, "SELECT COALESCE(MAX(migration_id), 0) FROM atlas_schema_migrations"
            )
            return int(row[0])
        finally:
            connection.close()

    def health(self) -> dict[str, Any]:
        status: dict[str, Any] = {
            "backend": self.backend_identity,
            "connected": self._opened,
            "database_path": str(self.database_path),
            "schema_version": None,
            "migration_state": "NOT_CHECKED",
            "last_integrity_check": self._last_integrity_check,
        }
        if not self._opened:
            return status
        try:
            status["schema_version"] = self.schema_version
            status["migration_state"] = (
                "CURRENT"
                if status["schema_version"] == len(MARKET_DATA_MIGRATIONS)
                else "MISMATCH"
            )
        except StorageError:
            status["migration_state"] = "ERROR"
        return status


__all__ = [
    "MarketDataSQLiteStorage",
    "SQLiteDatasetRepository",
    "SQLiteMarketDataRepository",
]
