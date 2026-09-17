"""Block 4 / Package 2: SQLite reference backend for the market-data repositories.

Every test binds the backend to a scratch `tmp_path` state directory. The
backend has no default state_directory at all, so no test can reach Atlas's
real runtime state by omission, and several tests assert positively that
nothing is written to the repository root or the process working directory.

The suite is organized as: path/lifecycle, dataset repository, manifest
repository, atomicity, restart, serialization round-trip, property, corruption,
and the behavioural guards that a counterfactual mutation must break.
"""

from __future__ import annotations

import dataclasses
import hashlib
import json
import random
import sqlite3
import threading
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path

import pytest

import data_layer.market_data_sqlite as market_data_sqlite
from data_layer.contracts import (
    IntegrityViolation,
    MigrationError,
    RecordConflict,
    StorageConfigurationError,
    StorageError,
)
from data_layer.market_data_migrations import MARKET_DATA_MIGRATIONS, MARKET_DATA_TABLES
from data_layer.market_data_models import (
    DataProvenance,
    DataTimestamp,
    DatasetIdentity,
    DatasetManifest,
    TimeSemantic,
    compute_content_digest,
)
from data_layer.market_data_sqlite import MarketDataSQLiteStorage
from data_layer.migrations import validate_migrations

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]

RANGE_START = DataTimestamp(
    value=datetime(2026, 8, 1, tzinfo=UTC), semantic=TimeSemantic.EVENT_TIME
)
RANGE_END = DataTimestamp(
    value=datetime(2026, 8, 14, tzinfo=UTC), semantic=TimeSemantic.EVENT_TIME
)
INGESTED = DataTimestamp(
    value=datetime(2026, 8, 14, 1, 0, tzinfo=UTC), semantic=TimeSemantic.INGESTION_TIME
)
GENERATED = DataTimestamp(
    value=datetime(2026, 8, 14, 2, 0, tzinfo=UTC), semantic=TimeSemantic.SNAPSHOT_TIME
)


def identity(
    *, instruments: tuple[str, ...] = ("BTCUSDT",), timeframe: str = "1h",
    transform_version: str = "1.0",
) -> DatasetIdentity:
    return DatasetIdentity(
        source="BINANCE", venue="SPOT", instruments=instruments,
        range_start=RANGE_START, range_end=RANGE_END, timeframe=timeframe,
        schema_version="1.0", transform_version=transform_version,
    )


def manifest(
    payload: object, *, record_count: int = 1, owner: DatasetIdentity | None = None,
    generated_at: DataTimestamp = GENERATED, upstream: str | None = None,
) -> DatasetManifest:
    return DatasetManifest(
        identity=owner if owner is not None else identity(),
        content_hash=compute_content_digest(payload),
        record_count=record_count,
        provenance=DataProvenance(
            source="BINANCE", venue="SPOT", schema_version="1.0", ingested_at=INGESTED,
            record_content_hash=compute_content_digest({"record": payload}),
            upstream_identity_digest=upstream,
        ),
        generated_at=generated_at,
    )


@pytest.fixture
def storage(tmp_path: Path):
    backend = MarketDataSQLiteStorage(state_directory=tmp_path)
    backend.open()
    try:
        yield backend
    finally:
        backend.close()


def raw_connection(backend: MarketDataSQLiteStorage, *, foreign_keys: bool = True):
    """Direct SQLite access, used only to simulate out-of-band corruption."""

    connection = sqlite3.connect(backend.database_path, isolation_level=None)
    connection.execute(f"PRAGMA foreign_keys = {'ON' if foreign_keys else 'OFF'}")
    return connection


def digest_of(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class _StubCursor:
    """The minimum cursor surface the backend uses."""

    def __init__(self, rows: list[tuple]) -> None:
        self._rows = list(rows)

    def fetchone(self):
        return self._rows[0] if self._rows else None

    def fetchall(self):
        return list(self._rows)

    def __iter__(self):
        return iter(self._rows)


class _ConnectionProxy:
    """Delegates everything to a real connection so a subclass can bend one behaviour.

    Attribute writes are forwarded too: the backend assigns row_factory on the
    object sqlite3.connect returned, and a proxy that swallowed that assignment
    would silently disable column-name access and make the test lie.
    """

    def __init__(self, connection) -> None:
        object.__setattr__(self, "_connection", connection)

    def __getattr__(self, name: str):
        return getattr(self._connection, name)

    def __setattr__(self, name: str, value) -> None:
        setattr(self._connection, name, value)

    def execute(self, sql, parameters=()):
        return self._connection.execute(sql, parameters)


class _FetchFailingConnection(_ConnectionProxy):
    """execute() succeeds; stepping the cursor raises, as a malformed image does.

    This is the failure shape that motivated wrapping retrieval: SQLite does
    not report every problem at execute() time, so a translation boundary
    drawn around execute() alone leaves the stepping window uncovered.
    """

    def __init__(self, connection, failure: sqlite3.Error) -> None:
        super().__init__(connection)
        object.__setattr__(self, "_failure", failure)

    def execute(self, sql, parameters=()):
        self._connection.execute(sql, parameters)
        return _FailingCursor(self._failure)


class _FailingCursor:
    def __init__(self, failure: sqlite3.Error) -> None:
        self._failure = failure

    def fetchone(self):
        raise self._failure

    def fetchall(self):
        raise self._failure

    def __iter__(self):
        raise self._failure


class _ForeignKeysIgnoredConnection(_ConnectionProxy):
    """A SQLite build that accepts `PRAGMA foreign_keys = ON` and ignores it.

    SQLite compiled with SQLITE_OMIT_FOREIGN_KEY does exactly this: the PRAGMA
    is accepted silently and the readback still reports 0. It cannot be
    produced from Python against a normal build, so the guard that catches it
    is only reachable through a substituted connection.
    """

    def execute(self, sql, parameters=()):
        if " ".join(str(sql).split()).upper() == "PRAGMA FOREIGN_KEYS":
            return _StubCursor([(0,)])
        return self._connection.execute(sql, parameters)


def table_snapshot(backend: MarketDataSQLiteStorage) -> dict[str, list[tuple]]:
    connection = sqlite3.connect(backend.database_path, isolation_level=None)
    try:
        return {
            table: list(connection.execute(f"SELECT * FROM {table} ORDER BY 1"))
            for table in MARKET_DATA_TABLES
        }
    finally:
        connection.close()


# ---------------------------------------------------------------------------
# state_directory / path policy
# ---------------------------------------------------------------------------


def test_relative_state_directory_is_rejected_without_touching_the_filesystem() -> None:
    # A relative path would resolve against the process working directory,
    # which is exactly the hidden-CWD fallback this backend must not have.
    with pytest.raises(StorageConfigurationError):
        MarketDataSQLiteStorage(state_directory="runtime_data")
    with pytest.raises(StorageConfigurationError):
        MarketDataSQLiteStorage(state_directory=Path("market_data"))


def test_state_directory_has_no_default() -> None:
    # Positional construction must be impossible: the only way to obtain a
    # backend is to name a state directory explicitly.
    with pytest.raises(TypeError):
        MarketDataSQLiteStorage()  # type: ignore[call-arg]
    with pytest.raises(TypeError):
        MarketDataSQLiteStorage(Path.cwd())  # type: ignore[misc]


def test_missing_state_directory_is_rejected_and_not_fabricated(tmp_path: Path) -> None:
    missing = tmp_path / "absent"
    backend = MarketDataSQLiteStorage(state_directory=missing)
    with pytest.raises(StorageConfigurationError):
        backend.open()
    assert not missing.exists()
    assert backend.health()["connected"] is False


def test_file_as_state_directory_is_rejected(tmp_path: Path) -> None:
    target = tmp_path / "not-a-directory"
    target.write_text("payload", encoding="utf-8")
    with pytest.raises(StorageConfigurationError):
        MarketDataSQLiteStorage(state_directory=target).open()
    assert target.read_text(encoding="utf-8") == "payload"


def test_only_the_market_data_leaf_is_created_under_the_supplied_root(tmp_path: Path) -> None:
    root = tmp_path / "state"
    root.mkdir()
    backend = MarketDataSQLiteStorage(state_directory=root)
    backend.open()
    backend.close()

    assert backend.database_path == root / "market_data" / "market_data.sqlite3"
    assert backend.database_path.parent.is_dir()
    assert backend.database_path.is_file()
    # Nothing above the supplied root was invented.
    created = {entry.name for entry in root.iterdir()}
    assert created == {"market_data"}


def test_database_path_stays_under_the_supplied_state_directory(tmp_path: Path) -> None:
    backend = MarketDataSQLiteStorage(state_directory=tmp_path)
    backend.open()
    backend.close()
    assert backend.database_path.resolve().is_relative_to(tmp_path.resolve())


def test_nothing_is_written_to_the_repository_root_or_working_directory(tmp_path: Path) -> None:
    backend = MarketDataSQLiteStorage(state_directory=tmp_path)
    backend.open()
    backend.market_data.put_manifest(manifest({"rows": 1}))
    backend.close()

    for root in (REPOSITORY_ROOT, Path.cwd()):
        assert not (root / "market_data").exists()
        assert not (root / MarketDataSQLiteStorage.DATABASE_FILENAME).exists()

    # The real durable state root, resolved the same way the composition
    # root resolves it. Anchoring this on REPOSITORY_ROOT / "memory_data"
    # alone would keep passing - vacuously - the moment an operator
    # relocates the state directory via ATLAS_STATE_DIRECTORY, which is
    # exactly when this guard matters most.
    from core.application import resolve_state_directory

    configured_state_root = resolve_state_directory()

    assert not (configured_state_root / "market_data").exists()
    assert not (
        configured_state_root / MarketDataSQLiteStorage.DATABASE_FILENAME
    ).exists()


def test_backend_is_not_usable_before_open_or_after_close(tmp_path: Path) -> None:
    backend = MarketDataSQLiteStorage(state_directory=tmp_path)
    subject = identity()
    with pytest.raises(StorageError):
        backend.datasets.exists(subject.identity_digest())
    with pytest.raises(StorageError):
        backend.market_data.put_manifest(manifest({"rows": 1}))

    backend.open()
    assert backend.health()["connected"] is True
    assert backend.health()["migration_state"] == "CURRENT"
    backend.close()

    with pytest.raises(StorageError):
        backend.datasets.get(subject.identity_digest())


def test_negative_busy_timeout_is_rejected(tmp_path: Path) -> None:
    with pytest.raises(ValueError):
        MarketDataSQLiteStorage(state_directory=tmp_path, busy_timeout_ms=-1)


# ---------------------------------------------------------------------------
# DatasetRepository
# ---------------------------------------------------------------------------


def test_register_get_exists_round_trip(storage: MarketDataSQLiteStorage) -> None:
    subject = identity()
    digest = subject.identity_digest()
    assert storage.datasets.exists(digest) is False
    assert storage.datasets.get(digest) is None

    storage.datasets.register(subject)
    assert storage.datasets.exists(digest) is True
    assert storage.datasets.get(digest) == subject


def test_register_is_idempotent_for_an_identical_identity(storage: MarketDataSQLiteStorage) -> None:
    subject = identity()
    storage.datasets.register(subject)
    before = table_snapshot(storage)
    storage.datasets.register(subject)
    storage.datasets.register(identity())
    assert table_snapshot(storage) == before


def test_identity_lookups_reject_a_malformed_key(storage: MarketDataSQLiteStorage) -> None:
    for bad in ("", "not-a-digest", "0" * 63, "g" * 64):
        with pytest.raises(IntegrityViolation):
            storage.datasets.get(bad)
        with pytest.raises(IntegrityViolation):
            storage.datasets.exists(bad)


def test_identity_lookup_accepts_an_upper_case_digest(storage: MarketDataSQLiteStorage) -> None:
    subject = identity()
    storage.datasets.register(subject)
    assert storage.datasets.exists(subject.identity_digest().upper()) is True


def test_register_rejects_a_non_identity(storage: MarketDataSQLiteStorage) -> None:
    with pytest.raises(IntegrityViolation):
        storage.datasets.register("BINANCE")  # type: ignore[arg-type]


def test_registering_over_a_corrupt_identity_row_fails_closed(
    storage: MarketDataSQLiteStorage,
) -> None:
    # identity_digest covers every canonical field, so a stored row that
    # disagrees while keying to the same digest is corruption, not a caller
    # conflict, and must be reported as such rather than silently overwritten.
    subject = identity()
    storage.datasets.register(subject)
    connection = raw_connection(storage)
    try:
        connection.execute("UPDATE market_data_dataset_identities SET timeframe = '4h'")
    finally:
        connection.close()

    with pytest.raises(IntegrityViolation):
        storage.datasets.register(subject)

    connection = raw_connection(storage)
    try:
        assert connection.execute(
            "SELECT timeframe FROM market_data_dataset_identities"
        ).fetchone()[0] == "4h"
    finally:
        connection.close()


# ---------------------------------------------------------------------------
# MarketDataRepository
# ---------------------------------------------------------------------------


def test_put_and_get_manifest_round_trip(storage: MarketDataSQLiteStorage) -> None:
    revision = manifest({"rows": 3}, record_count=3)
    assert storage.market_data.get_manifest(revision.content_hash) is None
    storage.market_data.put_manifest(revision)
    assert storage.market_data.get_manifest(revision.content_hash) == revision


def test_put_manifest_also_registers_its_logical_identity(
    storage: MarketDataSQLiteStorage,
) -> None:
    revision = manifest({"rows": 3})
    storage.market_data.put_manifest(revision)
    assert storage.datasets.exists(revision.logical_identity_digest) is True
    assert storage.datasets.get(revision.logical_identity_digest) == revision.identity


def test_one_identity_owns_many_revisions(storage: MarketDataSQLiteStorage) -> None:
    first = manifest({"rows": 3}, record_count=3)
    corrected = manifest({"rows": 4}, record_count=4)
    storage.market_data.put_manifest(first)
    storage.market_data.put_manifest(corrected)

    digest = identity().identity_digest()
    listed = storage.market_data.list_for_identity(digest)
    assert set(listed) == {first, corrected}
    assert storage.market_data.get_manifest(first.content_hash) == first
    assert storage.market_data.get_manifest(corrected.content_hash) == corrected


def test_list_for_identity_is_ordered_by_content_hash(storage: MarketDataSQLiteStorage) -> None:
    revisions = [manifest({"rows": index}) for index in range(8)]
    for revision in revisions:
        storage.market_data.put_manifest(revision)

    listed = storage.market_data.list_for_identity(identity().identity_digest())
    hashes = [revision.content_hash for revision in listed]
    assert hashes == sorted(revision.content_hash for revision in revisions)


def test_list_ordering_is_independent_of_insertion_order(tmp_path: Path) -> None:
    revisions = [manifest({"rows": index}) for index in range(6)]
    orders = []
    for name, sequence in (("forward", revisions), ("reverse", list(reversed(revisions)))):
        root = tmp_path / name
        root.mkdir()
        backend = MarketDataSQLiteStorage(state_directory=root)
        backend.open()
        for revision in sequence:
            backend.market_data.put_manifest(revision)
        orders.append(
            [item.content_hash for item in backend.market_data.list_for_identity(
                identity().identity_digest()
            )]
        )
        backend.close()
    assert orders[0] == orders[1]


def test_list_for_identity_is_empty_for_an_unknown_or_manifest_free_identity(
    storage: MarketDataSQLiteStorage,
) -> None:
    assert storage.market_data.list_for_identity(identity().identity_digest()) == ()
    storage.datasets.register(identity())
    # A registered identity with no manifest is legal and lists as empty.
    assert storage.market_data.list_for_identity(identity().identity_digest()) == ()


def test_identities_are_separated_by_logical_inputs(storage: MarketDataSQLiteStorage) -> None:
    hourly = identity(timeframe="1h")
    daily = identity(timeframe="1d")
    first = manifest({"rows": 3}, owner=hourly)
    second = manifest({"rows": 5}, owner=daily)
    storage.market_data.put_manifest(first)
    storage.market_data.put_manifest(second)

    assert storage.market_data.list_for_identity(hourly.identity_digest()) == (first,)
    assert storage.market_data.list_for_identity(daily.identity_digest()) == (second,)


def test_manifest_reinsertion_is_idempotent(storage: MarketDataSQLiteStorage) -> None:
    revision = manifest({"rows": 3}, record_count=3)
    storage.market_data.put_manifest(revision)
    before = table_snapshot(storage)
    storage.market_data.put_manifest(revision)
    storage.market_data.put_manifest(manifest({"rows": 3}, record_count=3))
    assert table_snapshot(storage) == before


def test_conflicting_manifest_payload_is_refused_not_overwritten(
    storage: MarketDataSQLiteStorage,
) -> None:
    stored = manifest({"rows": 3}, record_count=3)
    storage.market_data.put_manifest(stored)
    before = table_snapshot(storage)

    conflicting = manifest({"rows": 3}, record_count=99)
    assert conflicting.content_hash == stored.content_hash
    with pytest.raises(RecordConflict):
        storage.market_data.put_manifest(conflicting)

    assert storage.market_data.get_manifest(stored.content_hash) == stored
    assert table_snapshot(storage) == before


def test_same_content_hash_under_a_different_identity_is_refused(
    storage: MarketDataSQLiteStorage,
) -> None:
    stored = manifest({"rows": 3})
    storage.market_data.put_manifest(stored)
    foreign = DatasetManifest(
        identity=identity(timeframe="1d"),
        content_hash=stored.content_hash,
        record_count=stored.record_count,
        provenance=stored.provenance,
        generated_at=stored.generated_at,
    )
    with pytest.raises(RecordConflict):
        storage.market_data.put_manifest(foreign)
    assert storage.market_data.get_manifest(stored.content_hash) == stored


def test_a_differing_generated_at_is_a_conflict_not_an_update(
    storage: MarketDataSQLiteStorage,
) -> None:
    # Equality is decided by reconstructing the whole Package-1 object, so a
    # field outside the primary key still participates.
    stored = manifest({"rows": 3})
    storage.market_data.put_manifest(stored)
    rebuilt = manifest(
        {"rows": 3},
        generated_at=DataTimestamp(
            value=datetime(2026, 8, 15, tzinfo=UTC), semantic=TimeSemantic.SNAPSHOT_TIME
        ),
    )
    with pytest.raises(RecordConflict):
        storage.market_data.put_manifest(rebuilt)
    assert storage.market_data.get_manifest(stored.content_hash) == stored


def test_manifest_lookup_by_identity_digest_finds_nothing(
    storage: MarketDataSQLiteStorage,
) -> None:
    # The two key spaces are distinct: an identity digest is a well-formed
    # digest, so it is accepted as input and correctly matches no manifest.
    revision = manifest({"rows": 3})
    storage.market_data.put_manifest(revision)
    digest = revision.logical_identity_digest
    assert storage.market_data.get_manifest(digest) is None
    assert storage.market_data.list_for_identity(digest) == (revision,)


def test_manifest_lookups_reject_a_malformed_key(storage: MarketDataSQLiteStorage) -> None:
    for bad in ("", "not-a-digest", "0" * 65):
        with pytest.raises(IntegrityViolation):
            storage.market_data.get_manifest(bad)
        with pytest.raises(IntegrityViolation):
            storage.market_data.list_for_identity(bad)


def test_put_manifest_rejects_a_non_manifest(storage: MarketDataSQLiteStorage) -> None:
    with pytest.raises(IntegrityViolation):
        storage.market_data.put_manifest(identity())  # type: ignore[arg-type]


def test_unstorable_record_count_fails_closed(storage: MarketDataSQLiteStorage) -> None:
    oversized = DatasetManifest(
        identity=identity(), content_hash=compute_content_digest({"rows": 1}),
        record_count=2**63, provenance=manifest({"rows": 1}).provenance,
        generated_at=GENERATED,
    )
    with pytest.raises(IntegrityViolation):
        storage.market_data.put_manifest(oversized)


# ---------------------------------------------------------------------------
# atomicity
# ---------------------------------------------------------------------------


def test_put_manifest_rolls_back_the_identity_when_the_manifest_write_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    backend = MarketDataSQLiteStorage(state_directory=tmp_path)
    backend.open()
    revision = manifest({"rows": 3})
    original = market_data_sqlite._execute

    def failing(connection, sql, parameters=()):
        if sql is market_data_sqlite._INSERT_MANIFEST:
            raise StorageError("injected failure before the manifest insert")
        return original(connection, sql, parameters)

    monkeypatch.setattr(market_data_sqlite, "_execute", failing)
    with pytest.raises(StorageError):
        backend.market_data.put_manifest(revision)
    monkeypatch.undo()

    assert backend.datasets.exists(revision.logical_identity_digest) is False
    assert backend.market_data.get_manifest(revision.content_hash) is None
    backend.close()

    reopened = MarketDataSQLiteStorage(state_directory=tmp_path)
    reopened.open()
    assert reopened.datasets.exists(revision.logical_identity_digest) is False
    assert reopened.market_data.get_manifest(revision.content_hash) is None
    assert table_snapshot(reopened) == {table: [] for table in MARKET_DATA_TABLES}
    reopened.close()


def test_an_identity_without_a_manifest_survives_only_via_explicit_register(
    tmp_path: Path,
) -> None:
    backend = MarketDataSQLiteStorage(state_directory=tmp_path)
    backend.open()
    subject = identity()
    backend.datasets.register(subject)
    backend.close()

    reopened = MarketDataSQLiteStorage(state_directory=tmp_path)
    reopened.open()
    assert reopened.datasets.get(subject.identity_digest()) == subject
    assert reopened.market_data.list_for_identity(subject.identity_digest()) == ()
    reopened.close()


def test_a_locked_database_reports_a_storage_error(tmp_path: Path) -> None:
    backend = MarketDataSQLiteStorage(state_directory=tmp_path, busy_timeout_ms=10)
    backend.open()
    lock = sqlite3.connect(backend.database_path, isolation_level=None)
    lock.execute("BEGIN EXCLUSIVE")
    try:
        # A driver-level operational failure must not escape as sqlite3.Error.
        with pytest.raises(StorageError) as failure:
            backend.datasets.register(identity())
        assert not isinstance(failure.value, (IntegrityViolation, RecordConflict))
    finally:
        lock.rollback()
        lock.close()
        backend.close()


def test_concurrent_writers_are_serialized_without_loss(tmp_path: Path) -> None:
    backend = MarketDataSQLiteStorage(state_directory=tmp_path)
    backend.open()
    revisions = [manifest({"rows": index}) for index in range(12)]
    errors: list[BaseException] = []

    def write(revision: DatasetManifest) -> None:
        try:
            backend.market_data.put_manifest(revision)
        except BaseException as exc:  # pragma: no cover - surfaced by the assert
            errors.append(exc)

    threads = [threading.Thread(target=write, args=(revision,)) for revision in revisions]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert errors == []
    listed = backend.market_data.list_for_identity(identity().identity_digest())
    assert set(listed) == set(revisions)
    backend.close()


# ---------------------------------------------------------------------------
# restart
# ---------------------------------------------------------------------------


def test_state_survives_close_and_reopen_exactly(tmp_path: Path) -> None:
    first = manifest({"rows": 3}, record_count=3)
    second = manifest({"rows": 4}, record_count=4)

    backend = MarketDataSQLiteStorage(state_directory=tmp_path)
    backend.open()
    backend.market_data.put_manifest(first)
    backend.market_data.put_manifest(second)
    listed_before = backend.market_data.list_for_identity(identity().identity_digest())
    backend.close()

    reopened = MarketDataSQLiteStorage(state_directory=tmp_path)
    reopened.open()
    assert reopened.market_data.get_manifest(first.content_hash) == first
    assert reopened.market_data.get_manifest(second.content_hash) == second
    assert reopened.market_data.list_for_identity(identity().identity_digest()) == listed_before
    assert reopened.datasets.get(identity().identity_digest()) == identity()
    assert reopened.health()["schema_version"] == len(MARKET_DATA_MIGRATIONS)
    reopened.close()


def test_repeated_open_close_cycles_are_stable(tmp_path: Path) -> None:
    revision = manifest({"rows": 3})
    for cycle in range(3):
        backend = MarketDataSQLiteStorage(state_directory=tmp_path)
        backend.open()
        if cycle == 0:
            backend.market_data.put_manifest(revision)
        assert backend.market_data.get_manifest(revision.content_hash) == revision
        assert backend.health()["migration_state"] == "CURRENT"
        backend.close()


def test_persisted_rows_do_not_depend_on_wall_clock_time(tmp_path: Path) -> None:
    # Writing the same manifest at two different moments into two different
    # databases must produce identical rows: no wall-clock value participates
    # in identity, content, or any stored column.
    revision = manifest({"rows": 3})
    snapshots = []
    for name in ("first", "second"):
        root = tmp_path / name
        root.mkdir()
        backend = MarketDataSQLiteStorage(state_directory=root)
        backend.open()
        backend.market_data.put_manifest(revision)
        snapshots.append(table_snapshot(backend))
        backend.close()
    assert snapshots[0] == snapshots[1]


# ---------------------------------------------------------------------------
# serialization round-trip
# ---------------------------------------------------------------------------


def test_sub_second_and_offset_timestamps_round_trip_losslessly(tmp_path: Path) -> None:
    precise = DataTimestamp(
        value=datetime(2026, 8, 1, 12, 30, 15, 123456, tzinfo=UTC),
        semantic=TimeSemantic.EVENT_TIME,
    )
    offset = DataTimestamp(
        value=datetime(2026, 8, 14, 6, 0, tzinfo=timezone(timedelta(hours=3))),
        semantic=TimeSemantic.EVENT_TIME,
    )
    subject = DatasetIdentity(
        source="BINANCE", venue="SPOT", instruments=("BTCUSDT",),
        range_start=precise, range_end=offset, timeframe="1h",
        schema_version="1.0", transform_version="1.0",
    )
    revision = manifest({"rows": 1}, owner=subject)

    backend = MarketDataSQLiteStorage(state_directory=tmp_path)
    backend.open()
    backend.market_data.put_manifest(revision)
    backend.close()

    reopened = MarketDataSQLiteStorage(state_directory=tmp_path)
    reopened.open()
    restored = reopened.market_data.get_manifest(revision.content_hash)
    assert restored == revision
    assert restored.identity.range_start.value == precise.value
    assert restored.identity.range_end.value == offset.value
    reopened.close()


def test_optional_upstream_identity_digest_round_trips_in_both_states(
    storage: MarketDataSQLiteStorage,
) -> None:
    upstream = identity(timeframe="1m").identity_digest()
    derived = manifest({"rows": 7}, upstream=upstream)
    plain = manifest({"rows": 8})
    storage.market_data.put_manifest(derived)
    storage.market_data.put_manifest(plain)

    assert storage.market_data.get_manifest(
        derived.content_hash
    ).provenance.upstream_identity_digest == upstream
    assert storage.market_data.get_manifest(
        plain.content_hash
    ).provenance.upstream_identity_digest is None


def test_reconstructed_objects_are_frozen_hashable_and_typed(
    storage: MarketDataSQLiteStorage,
) -> None:
    revision = manifest({"rows": 3}, owner=identity(instruments=("ETHUSDT", "BTCUSDT")))
    storage.market_data.put_manifest(revision)
    restored = storage.market_data.get_manifest(revision.content_hash)

    assert isinstance(restored, DatasetManifest)
    assert isinstance(restored.identity.instruments, tuple)
    assert restored.identity.instruments == ("BTCUSDT", "ETHUSDT")
    assert isinstance(restored.generated_at.value, datetime)
    assert restored.generated_at.semantic is TimeSemantic.SNAPSHOT_TIME
    assert restored.provenance.ingested_at.semantic is TimeSemantic.INGESTION_TIME
    assert restored.identity.range_start.semantic is TimeSemantic.EVENT_TIME
    assert hash(restored) == hash(revision)
    with pytest.raises(dataclasses.FrozenInstanceError):
        restored.record_count = 99  # type: ignore[misc]


def test_instruments_are_stored_as_a_canonical_json_array(
    storage: MarketDataSQLiteStorage,
) -> None:
    storage.datasets.register(identity(instruments=("ethusdt", "BTCUSDT")))
    connection = raw_connection(storage)
    try:
        stored = connection.execute(
            "SELECT instruments_json FROM market_data_dataset_identities"
        ).fetchone()[0]
    finally:
        connection.close()
    assert stored == '["BTCUSDT","ETHUSDT"]'
    assert json.loads(stored) == ["BTCUSDT", "ETHUSDT"]


# ---------------------------------------------------------------------------
# property
# ---------------------------------------------------------------------------


def test_property_round_trip_and_ordering_over_generated_datasets(tmp_path: Path) -> None:
    generator = random.Random(20260815)
    identities = [
        identity(timeframe=timeframe, transform_version=version)
        for timeframe in ("1m", "5m", "1h", "1d")
        for version in ("1.0", "2.0")
    ]
    expected: dict[str, list[DatasetManifest]] = {}
    everything: dict[str, DatasetManifest] = {}

    backend = MarketDataSQLiteStorage(state_directory=tmp_path)
    backend.open()
    for owner in identities:
        revisions = []
        for _ in range(generator.randint(1, 5)):
            payload = {"nonce": generator.randrange(1_000_000)}
            revision = manifest(
                payload, record_count=generator.randrange(0, 5000), owner=owner
            )
            if revision.content_hash in everything:
                continue
            revisions.append(revision)
            everything[revision.content_hash] = revision
        expected[owner.identity_digest()] = revisions

    order = list(everything.values())
    generator.shuffle(order)
    for revision in order:
        backend.market_data.put_manifest(revision)

    for content_hash, revision in everything.items():
        assert backend.market_data.get_manifest(content_hash) == revision
    for digest, revisions in expected.items():
        listed = backend.market_data.list_for_identity(digest)
        assert list(listed) == sorted(revisions, key=lambda item: item.content_hash)
        assert set(listed) == set(revisions)
        assert all(item.logical_identity_digest == digest for item in listed)
    backend.close()

    reopened = MarketDataSQLiteStorage(state_directory=tmp_path)
    reopened.open()
    for digest, revisions in expected.items():
        assert list(reopened.market_data.list_for_identity(digest)) == sorted(
            revisions, key=lambda item: item.content_hash
        )
    reopened.close()


# ---------------------------------------------------------------------------
# corruption / fail-closed open
# ---------------------------------------------------------------------------


def test_a_garbled_database_fails_closed_and_is_left_byte_identical(tmp_path: Path) -> None:
    leaf = tmp_path / "market_data"
    leaf.mkdir()
    database = leaf / "market_data.sqlite3"
    database.write_bytes(b"NOT A SQLITE DATABASE" * 64)
    before = digest_of(database)

    backend = MarketDataSQLiteStorage(state_directory=tmp_path)
    with pytest.raises(StorageError):
        backend.open()

    assert digest_of(database) == before
    assert backend.health()["connected"] is False
    assert backend.health()["last_integrity_check"] == "FAIL"


def test_a_dropped_table_fails_closed(tmp_path: Path) -> None:
    backend = MarketDataSQLiteStorage(state_directory=tmp_path)
    backend.open()
    backend.close()
    connection = raw_connection(backend)
    try:
        connection.execute("DROP TABLE market_data_manifests")
    finally:
        connection.close()

    with pytest.raises(StorageError) as failure:
        backend.open()
    assert "market_data_manifests" in str(failure.value)
    assert backend.health()["connected"] is False


def test_migration_checksum_drift_fails_closed(tmp_path: Path) -> None:
    backend = MarketDataSQLiteStorage(state_directory=tmp_path)
    backend.open()
    backend.close()
    connection = raw_connection(backend)
    try:
        connection.execute(
            "UPDATE atlas_schema_migrations SET checksum_sha256 = ? WHERE migration_id = 1",
            ("0" * 64,),
        )
    finally:
        connection.close()

    with pytest.raises(MigrationError):
        backend.open()
    assert backend.health()["connected"] is False


def test_a_future_schema_version_fails_closed(tmp_path: Path) -> None:
    backend = MarketDataSQLiteStorage(state_directory=tmp_path)
    backend.open()
    backend.close()
    connection = raw_connection(backend)
    try:
        connection.execute(
            "INSERT INTO atlas_schema_migrations VALUES (?, ?, ?, ?)",
            (99, "future", "F" * 64, "2026-08-15T00:00:00Z"),
        )
    finally:
        connection.close()

    with pytest.raises(MigrationError):
        backend.open()


@pytest.mark.parametrize(
    ("column", "value"),
    [
        ("range_start_utc", "not-a-timestamp"),
        ("range_end_utc", "2026-08-14T00:00:00"),
        ("instruments_json", '{"not": "an array"}'),
        # Valid values that still re-key the identity: the recomputed digest
        # no longer matches the stored primary key.
        ("range_start_utc", "2026-07-01T00:00:00Z"),
        ("source", "kraken"),
        ("transform_version", "9.9"),
    ],
)
def test_a_corrupt_identity_column_fails_closed_without_repair(
    tmp_path: Path, column: str, value: str,
) -> None:
    backend = MarketDataSQLiteStorage(state_directory=tmp_path)
    backend.open()
    backend.market_data.put_manifest(manifest({"rows": 3}))
    backend.close()

    # Foreign keys are disabled only to *simulate* out-of-band corruption:
    # with them enforced, the composite key already refuses an edit to a
    # column the manifest's provenance mirrors.
    connection = raw_connection(backend, foreign_keys=False)
    try:
        connection.execute(f"UPDATE market_data_dataset_identities SET {column} = ?", (value,))
    finally:
        connection.close()
    corrupted = table_snapshot(backend)

    with pytest.raises(IntegrityViolation):
        backend.open()

    assert backend.health()["connected"] is False
    assert backend.health()["last_integrity_check"] == "FAIL"
    # Nothing was repaired, rewritten, or deleted.
    assert table_snapshot(backend) == corrupted


@pytest.mark.parametrize(
    ("column", "value"),
    [
        ("generated_at_utc", "not-a-timestamp"),
        ("provenance_ingested_at_utc", "2026-08-14T01:00:00"),
        ("record_count", "not-a-number"),
    ],
)
def test_a_corrupt_manifest_column_fails_closed(tmp_path: Path, column: str, value: str) -> None:
    backend = MarketDataSQLiteStorage(state_directory=tmp_path)
    backend.open()
    backend.market_data.put_manifest(manifest({"rows": 3}))
    backend.close()

    connection = raw_connection(backend, foreign_keys=False)
    try:
        connection.execute(f"UPDATE market_data_manifests SET {column} = ?", (value,))
    finally:
        connection.close()

    with pytest.raises(IntegrityViolation):
        backend.open()
    assert backend.health()["connected"] is False


def test_an_orphan_manifest_fails_closed(tmp_path: Path) -> None:
    backend = MarketDataSQLiteStorage(state_directory=tmp_path)
    backend.open()
    backend.market_data.put_manifest(manifest({"rows": 3}))
    backend.close()

    connection = raw_connection(backend, foreign_keys=False)
    try:
        connection.execute("DELETE FROM market_data_dataset_identities")
    finally:
        connection.close()

    with pytest.raises(IntegrityViolation):
        backend.open()


def test_identity_provenance_disagreement_fails_closed(tmp_path: Path) -> None:
    backend = MarketDataSQLiteStorage(state_directory=tmp_path)
    backend.open()
    backend.market_data.put_manifest(manifest({"rows": 3}))
    backend.close()

    connection = raw_connection(backend, foreign_keys=False)
    try:
        connection.execute("UPDATE market_data_manifests SET provenance_venue = 'futures'")
    finally:
        connection.close()

    with pytest.raises(IntegrityViolation):
        backend.open()


def test_schema_keys_indexes_and_foreign_keys_are_present(
    storage: MarketDataSQLiteStorage,
) -> None:
    """Pin the structural guarantees, not just the behaviour built on them.

    Application logic already refuses a conflicting write, so dropping a key
    would leave every behavioural test green while removing the guarantee
    that makes the refusal reliable.
    """

    connection = raw_connection(storage)
    try:
        def primary_key(table: str) -> list[str]:
            return [
                row[1]
                for row in connection.execute(f"PRAGMA table_info({table})")
                if row[5]
            ]

        assert primary_key("market_data_manifests") == ["content_hash"]
        assert primary_key("market_data_dataset_identities") == ["identity_digest"]

        # The composite parent key that carries identity/provenance agreement.
        unique_columns = [
            [entry[2] for entry in connection.execute(f"PRAGMA index_info({row[1]})")]
            for row in connection.execute("PRAGMA index_list(market_data_dataset_identities)")
            if row[2]
        ]
        assert ["identity_digest", "source", "venue", "schema_version"] in unique_columns

        foreign_keys = list(connection.execute("PRAGMA foreign_key_list(market_data_manifests)"))
        assert {row[2] for row in foreign_keys} == {"market_data_dataset_identities"}
        assert {row[3] for row in foreign_keys} == {
            "identity_digest", "provenance_source", "provenance_venue",
            "provenance_schema_version",
        }
        assert {row[6] for row in foreign_keys} == {"RESTRICT"}

        indexes = {
            row[1] for row in connection.execute("PRAGMA index_list(market_data_manifests)")
        }
        assert "idx_market_data_manifests_identity" in indexes
    finally:
        connection.close()


def test_the_composite_foreign_key_makes_disagreement_unrepresentable(
    storage: MarketDataSQLiteStorage,
) -> None:
    # With foreign keys enforced, the storage layer itself refuses both the
    # provenance disagreement and the orphaning delete.
    storage.market_data.put_manifest(manifest({"rows": 3}))
    connection = raw_connection(storage)
    try:
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute("UPDATE market_data_manifests SET provenance_venue = 'futures'")
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute("DELETE FROM market_data_dataset_identities")
    finally:
        connection.close()


def test_foreign_key_enforcement_is_active_on_every_connection(
    storage: MarketDataSQLiteStorage,
) -> None:
    # The composite foreign key carries the identity/provenance guarantee, so
    # a connection that does not enforce it must never be handed out.
    connection = storage._operational_connection()
    try:
        assert int(connection.execute("PRAGMA foreign_keys").fetchone()[0]) == 1
    finally:
        connection.close()


def test_a_connection_that_silently_ignores_foreign_keys_is_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The readback guard itself, not merely the property it protects.

    Issuing `PRAGMA foreign_keys = ON` is not evidence that it took effect;
    SQLite accepts and ignores it when built without foreign-key support. Only
    substituting the connection can drive the readback to 0, so the test above
    (which asserts the resulting property on a normal build) stays green even
    if the guard is deleted. This one does not.
    """

    backend = MarketDataSQLiteStorage(state_directory=tmp_path)
    real_connect = sqlite3.connect
    monkeypatch.setattr(
        market_data_sqlite.sqlite3,
        "connect",
        lambda *args, **kwargs: _ForeignKeysIgnoredConnection(real_connect(*args, **kwargs)),
    )

    with pytest.raises(StorageError) as failure:
        backend.open()
    assert "foreign key" in str(failure.value).lower()
    assert not isinstance(failure.value, sqlite3.Error)

    monkeypatch.undo()

    # Fails closed: never opened, and no repository operation became reachable.
    assert backend.health()["connected"] is False
    for call in (
        lambda: backend.datasets.exists(identity().identity_digest()),
        lambda: backend.datasets.get(identity().identity_digest()),
        lambda: backend.datasets.register(identity()),
        lambda: backend.market_data.put_manifest(manifest({"rows": 1})),
        lambda: backend.market_data.get_manifest(manifest({"rows": 1}).content_hash),
        lambda: backend.market_data.list_for_identity(identity().identity_digest()),
    ):
        with pytest.raises(StorageError):
            call()


def test_a_fetch_time_sqlite_failure_never_escapes_a_public_method(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Retrieval must translate, not only statement execution.

    Driven by a substituted cursor rather than by corrupting pages, because
    whether a real malformed image surfaces at execute() or while stepping
    depends on the query plan SQLite happens to choose -- `list_for_identity`
    currently sorts through a temp b-tree, which materialises the rows early
    and hides the window. A test that relied on that would pass for a reason
    unrelated to the invariant, and would stop testing it the day an index
    changed.
    """

    backend = MarketDataSQLiteStorage(state_directory=tmp_path)
    backend.open()
    revision = manifest({"rows": 3}, record_count=3)
    backend.market_data.put_manifest(revision)

    malformed = sqlite3.DatabaseError("database disk image is malformed")
    unwrapped = MarketDataSQLiteStorage._new_connection
    monkeypatch.setattr(
        MarketDataSQLiteStorage,
        "_new_connection",
        lambda self: _FetchFailingConnection(unwrapped(self), malformed),
    )

    for label, call in (
        ("datasets.get", lambda: backend.datasets.get(identity().identity_digest())),
        ("datasets.exists", lambda: backend.datasets.exists(identity().identity_digest())),
        ("datasets.register", lambda: backend.datasets.register(identity())),
        ("get_manifest", lambda: backend.market_data.get_manifest(revision.content_hash)),
        (
            "list_for_identity",
            lambda: backend.market_data.list_for_identity(identity().identity_digest()),
        ),
        ("put_manifest", lambda: backend.market_data.put_manifest(revision)),
        ("schema_version", lambda: backend.schema_version),
    ):
        with pytest.raises(StorageError) as failure:
            call()
        assert not isinstance(failure.value, sqlite3.Error), f"{label} leaked a sqlite3 exception"
        # Translated, not swallowed: the driver failure stays attached.
        assert failure.value.__cause__ is malformed, f"{label} lost the underlying cause"

    monkeypatch.undo()
    # The backend is undamaged once the driver stops failing.
    assert backend.market_data.get_manifest(revision.content_hash) == revision
    backend.close()


def test_health_reports_an_error_instead_of_leaking_a_fetch_time_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    backend = MarketDataSQLiteStorage(state_directory=tmp_path)
    backend.open()
    unwrapped = MarketDataSQLiteStorage._new_connection
    monkeypatch.setattr(
        MarketDataSQLiteStorage,
        "_new_connection",
        lambda self: _FetchFailingConnection(
            unwrapped(self), sqlite3.DatabaseError("database disk image is malformed")
        ),
    )
    status = backend.health()
    assert status["migration_state"] == "ERROR"
    assert status["schema_version"] is None
    backend.close()


# ---------------------------------------------------------------------------
# invariants a counterfactual mutation must break
# ---------------------------------------------------------------------------


def test_ordering_follows_content_hash_even_when_generated_at_disagrees(
    storage: MarketDataSQLiteStorage,
) -> None:
    # Built so that content-hash order is the exact reverse of generated_at
    # order: switching list_for_identity to a timestamp ordering flips this.
    early = DataTimestamp(
        value=datetime(2026, 8, 10, tzinfo=UTC), semantic=TimeSemantic.SNAPSHOT_TIME
    )
    late = DataTimestamp(
        value=datetime(2026, 8, 20, tzinfo=UTC), semantic=TimeSemantic.SNAPSHOT_TIME
    )
    lower_payload, higher_payload = {"rows": 1}, {"rows": 2}
    if compute_content_digest(lower_payload) > compute_content_digest(higher_payload):
        lower_payload, higher_payload = higher_payload, lower_payload

    first = manifest(lower_payload, generated_at=late)
    second = manifest(higher_payload, generated_at=early)
    assert first.content_hash < second.content_hash
    assert first.generated_at.value > second.generated_at.value

    storage.market_data.put_manifest(second)
    storage.market_data.put_manifest(first)
    listed = storage.market_data.list_for_identity(identity().identity_digest())
    assert [item.content_hash for item in listed] == [first.content_hash, second.content_hash]


_SQL_PREFIXES = (
    "SELECT", "INSERT", "UPDATE", "DELETE", "CREATE", "DROP", "ALTER",
    "BEGIN", "PRAGMA", "WHERE", "FROM", "ORDER BY", "REPLACE",
)


def _looks_like_sql(text: str) -> bool:
    return text.strip().upper().startswith(_SQL_PREFIXES)


def backend_sql_statements() -> list[str]:
    """Every SQL fragment the backend can execute.

    Collected from the module's assembled constants, its inline literals (via
    the AST, so f-string fragments are included), and the migration
    statements. Scanning real SQL rather than raw source keeps these guards
    from matching prose in a docstring that merely names a forbidden pattern.
    """

    import ast

    statements = [
        value
        for name, value in vars(market_data_sqlite).items()
        if isinstance(value, str) and not name.startswith("__") and _looks_like_sql(value)
    ]
    tree = ast.parse(
        (REPOSITORY_ROOT / "data_layer" / "market_data_sqlite.py").read_text(encoding="utf-8")
    )
    statements += [
        node.value
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant)
        and isinstance(node.value, str)
        and _looks_like_sql(node.value)
    ]
    statements += [
        statement for migration in MARKET_DATA_MIGRATIONS for statement in migration.statements
    ]
    assert statements, "no SQL was collected; the scan would pass vacuously"
    return statements


def test_no_timestamp_column_is_used_as_a_sql_ordering_or_comparison_authority() -> None:
    # Stored UTC strings are variable width, so their lexical order does not
    # match chronological order; SQL must never rank or compare them.
    for statement in backend_sql_statements():
        upper = " ".join(statement.upper().split())
        for index in range(len(upper)):
            if upper.startswith("ORDER BY", index):
                assert "_UTC" not in upper[index : index + 120], (
                    f"timestamp column used in ORDER BY: {upper[index : index + 60]}"
                )
        for aggregate in ("MIN(", "MAX("):
            position = 0
            while (position := upper.find(aggregate, position)) != -1:
                assert "_UTC" not in upper[position : position + 60], (
                    f"timestamp column ranked by {aggregate}): {upper[position : position + 60]}"
                )
                position += 1
        for comparison in ("_UTC <", "_UTC >", "_UTC BETWEEN"):
            assert comparison not in upper, f"timestamp columns compared in SQL: {upper[:80]}"


def test_no_overwriting_sql_exists_in_the_backend_or_schema() -> None:
    for statement in backend_sql_statements():
        upper = " ".join(statement.upper().split())
        for forbidden in ("INSERT OR REPLACE", "INSERT OR IGNORE", "ON CONFLICT", "REPLACE INTO"):
            assert forbidden not in upper, f"{forbidden!r} appears in {upper[:80]!r}"
        assert not upper.startswith(("UPDATE ", "DELETE ")), (
            f"the market-data backend must not mutate or delete stored rows: {upper[:80]!r}"
        )


def test_market_data_migrations_are_a_separate_contiguous_forward_only_sequence() -> None:
    from data_layer.migrations import MIGRATIONS as FINANCIAL_MIGRATIONS

    validate_migrations(MARKET_DATA_MIGRATIONS)
    assert MARKET_DATA_MIGRATIONS[0].migration_id == 1
    financial_names = {item.name for item in FINANCIAL_MIGRATIONS}
    assert not {item.name for item in MARKET_DATA_MIGRATIONS} & financial_names
    # The financial sequence must not have grown a market-data migration.
    assert len(FINANCIAL_MIGRATIONS) == 2
    assert all(
        "market_data" not in statement
        for item in FINANCIAL_MIGRATIONS
        for statement in item.statements
    )


def test_market_data_schema_is_absent_from_the_financial_database(tmp_path: Path) -> None:
    from data_layer.sqlite import SQLiteStorage

    financial = SQLiteStorage(tmp_path / "financial" / "atlas.sqlite3")
    financial.open()
    market = MarketDataSQLiteStorage(state_directory=tmp_path)
    market.open()
    try:
        assert financial.database_path != market.database_path
        assert financial.schema_version == 2
        assert market.schema_version == len(MARKET_DATA_MIGRATIONS)
        connection = sqlite3.connect(financial.database_path)
        try:
            tables = {
                row[0]
                for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")
            }
        finally:
            connection.close()
        assert not tables & set(MARKET_DATA_TABLES)
    finally:
        market.close()
        financial.close()


def test_the_backend_satisfies_the_package_1_protocols_structurally(
    storage: MarketDataSQLiteStorage,
) -> None:
    # Structural conformance, without inheritance and without the Protocols
    # having been altered to accommodate a backend.
    from typing import Protocol, runtime_checkable

    from data_layer.market_data_contracts import DatasetRepository, MarketDataRepository

    @runtime_checkable
    class _CheckableDatasetRepository(DatasetRepository, Protocol):
        pass

    @runtime_checkable
    class _CheckableMarketDataRepository(MarketDataRepository, Protocol):
        pass

    assert isinstance(storage.datasets, _CheckableDatasetRepository)
    assert isinstance(storage.market_data, _CheckableMarketDataRepository)
    assert not isinstance(storage.datasets, type(storage.market_data))


def test_the_storage_exception_taxonomy_is_well_formed() -> None:
    """Class relationships only -- this test invokes no backend and proves no behaviour.

    It pins that the taxonomy is a single rooted hierarchy disjoint from
    sqlite3's, which is what makes `pytest.raises(StorageError)` a meaningful
    assertion elsewhere. That every failure path actually lands in this
    taxonomy is proved behaviourally by
    test_a_fetch_time_sqlite_failure_never_escapes_a_public_method,
    test_a_locked_database_reports_a_storage_error, and
    test_a_connection_that_silently_ignores_foreign_keys_is_refused.
    """

    for exception in (RecordConflict, IntegrityViolation, MigrationError, StorageConfigurationError):
        assert issubclass(exception, StorageError)
        assert not issubclass(exception, sqlite3.Error)
    assert issubclass(RecordConflict, IntegrityViolation)
