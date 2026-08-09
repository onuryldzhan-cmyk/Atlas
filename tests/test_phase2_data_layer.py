from __future__ import annotations

import json
import sqlite3
import threading
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

import pytest

from data_layer.config import create_storage, load_storage_configuration
from data_layer.contracts import (
    IntegrityViolation,
    MigrationError,
    StorageConfigurationError,
    StorageError,
    TransactionStateError,
)
from data_layer.legacy_readiness import inspect_legacy_json
from data_layer.migrations import MIGRATIONS, Migration, apply_migrations, validate_migrations
from data_layer.models import ExecutionRecord, OrderRecord, PositionRecord, parse_metadata
from data_layer.sqlite import SQLiteStorage


NOW = datetime(2026, 8, 9, 12, 0, tzinfo=UTC)


def order(order_id: str = "order-1", key: str = "request-1") -> OrderRecord:
    return OrderRecord(
        order_id=order_id,
        symbol="btcusdt",
        side="BUY",
        quantity=Decimal("0.123456789012345678"),
        limit_price=Decimal("61234.123456789"),
        status="NEW",
        created_at=NOW,
        idempotency_key=key,
        strategy="test",
        metadata={"confidence": "0.91"},
    )


@pytest.fixture
def storage(tmp_path: Path):
    backend = SQLiteStorage(tmp_path / "runtime" / "atlas.sqlite3")
    backend.open()
    try:
        yield backend
    finally:
        backend.close()


def test_lifecycle_health_schema_and_reopen_persistence(tmp_path: Path) -> None:
    path = tmp_path / "nested" / "atlas.sqlite3"
    backend = SQLiteStorage(path)
    assert backend.health()["connected"] is False
    with pytest.raises(StorageError):
        backend.unit_of_work()
    backend.open()
    backend.open()
    assert backend.backend_identity == "sqlite-local"
    assert backend.health()["schema_version"] == len(MIGRATIONS)
    with backend.unit_of_work() as uow:
        uow.orders.add(order())
    backend.close()
    backend.open()
    with backend.unit_of_work() as uow:
        assert uow.orders.get("order-1") == order()
    backend.close()


def test_commit_and_multi_repository_atomicity(storage: SQLiteStorage) -> None:
    execution = ExecutionRecord(
        execution_id="exec-1", order_id="order-1",
        quantity=Decimal("0.123456789012345678"),
        price=Decimal("61234.123456789"), fee=Decimal("0.000001"),
        realized_pnl=Decimal("-0.123456789"), executed_at=NOW,
        metadata={"venue": "test"},
    )
    position = PositionRecord(
        position_id="position-1", symbol="BTCUSDT",
        quantity=Decimal("0.123456789012345678"),
        average_price=Decimal("61234.123456789"),
        status="OPEN", updated_at=NOW, metadata={"source": "exec-1"},
    )
    with storage.unit_of_work() as uow:
        uow.orders.add(order())
        uow.executions.add(execution)
        uow.positions.put(position)
    with storage.unit_of_work() as uow:
        assert uow.executions.get("exec-1") == execution
        assert uow.executions.list_for_order("order-1") == [execution]
        assert uow.positions.get_open_for_symbol("btcusdt") == position


def test_exception_rolls_back_all_repositories(storage: SQLiteStorage) -> None:
    with pytest.raises(RuntimeError):
        with storage.unit_of_work() as uow:
            uow.orders.add(order())
            uow.positions.put(PositionRecord(
                position_id="position-1", symbol="BTCUSDT",
                quantity=Decimal("1"), average_price=Decimal("1"),
                status="OPEN", updated_at=NOW,
            ))
            raise RuntimeError("abort")
    with storage.unit_of_work() as uow:
        assert uow.orders.get("order-1") is None
        assert uow.positions.get("position-1") is None


def test_explicit_rollback_and_nested_reuse_rejected(storage: SQLiteStorage) -> None:
    unit = storage.unit_of_work()
    with unit as uow:
        uow.orders.add(order())
        uow.rollback()
    with pytest.raises(TransactionStateError):
        unit.__enter__()
    with storage.unit_of_work() as uow:
        assert uow.orders.get("order-1") is None


def test_repositories_fail_closed_after_explicit_commit(storage: SQLiteStorage) -> None:
    unit = storage.unit_of_work()
    with unit as uow:
        repository = uow.orders
        repository.add(order())
        uow.commit()
        with pytest.raises(TransactionStateError):
            repository.add(order("order-2", "request-2"))
        with pytest.raises(TransactionStateError):
            repository.get("order-1")
        with pytest.raises(TransactionStateError):
            uow.commit()
        with pytest.raises(TransactionStateError):
            uow.rollback()
    with storage.unit_of_work() as check:
        assert check.orders.exists("order-1")
        assert not check.orders.exists("order-2")


def test_repositories_fail_closed_after_explicit_rollback(storage: SQLiteStorage) -> None:
    unit = storage.unit_of_work()
    with unit as uow:
        repository = uow.orders
        repository.add(order())
        uow.rollback()
        with pytest.raises(TransactionStateError):
            repository.add(order("order-2", "request-2"))
        with pytest.raises(TransactionStateError):
            repository.get("order-1")
        with pytest.raises(TransactionStateError):
            uow.commit()
    with storage.unit_of_work() as check:
        assert not check.orders.exists("order-1")
        assert not check.orders.exists("order-2")


def test_stale_repository_after_context_exit_is_rejected(storage: SQLiteStorage) -> None:
    with storage.unit_of_work() as uow:
        repository = uow.orders
    with pytest.raises(TransactionStateError):
        repository.exists("order-1")


class _FailingTransactionConnection:
    def __init__(self, connection: sqlite3.Connection, failure: str):
        self._connection = connection
        self._failure = failure

    def execute(self, *args, **kwargs):
        return self._connection.execute(*args, **kwargs)

    def commit(self) -> None:
        if self._failure == "commit":
            raise sqlite3.OperationalError("injected commit failure")
        self._connection.commit()

    def rollback(self) -> None:
        if self._failure == "rollback":
            raise sqlite3.OperationalError("injected rollback failure")
        self._connection.rollback()

    def close(self) -> None:
        self._connection.close()


@pytest.mark.parametrize("operation", ["commit", "rollback"])
def test_transaction_failure_is_terminal_and_counted(
    storage: SQLiteStorage, monkeypatch: pytest.MonkeyPatch, operation: str
) -> None:
    real_connect = storage._connect
    monkeypatch.setattr(
        storage,
        "_connect",
        lambda: _FailingTransactionConnection(real_connect(), operation),
    )
    unit = storage.unit_of_work()
    with pytest.raises(sqlite3.OperationalError, match=f"injected {operation} failure"):
        with unit as uow:
            repository = uow.orders
            getattr(uow, operation)()
    assert storage.health()["transaction_failures"] == 1
    with pytest.raises(TransactionStateError):
        repository.exists("order-1")


def test_foreign_keys_uniqueness_and_single_open_position(storage: SQLiteStorage) -> None:
    orphan = ExecutionRecord(
        "exec-orphan", "missing", Decimal("1"), Decimal("1"), Decimal("0"), NOW
    )
    with pytest.raises(IntegrityViolation):
        with storage.unit_of_work() as uow:
            uow.executions.add(orphan)
    with storage.unit_of_work() as uow:
        uow.orders.add(order())
    with pytest.raises(IntegrityViolation):
        with storage.unit_of_work() as uow:
            uow.orders.add(order("order-2", "request-1"))
    with storage.unit_of_work() as uow:
        uow.positions.put(PositionRecord(
            "position-1", "BTCUSDT", Decimal("1"), Decimal("10"), "OPEN", NOW
        ))
    with pytest.raises(IntegrityViolation):
        with storage.unit_of_work() as uow:
            uow.positions.put(PositionRecord(
                "position-2", "BTCUSDT", Decimal("2"), Decimal("11"), "OPEN", NOW
            ))


@pytest.mark.parametrize("bad", ["NaN", "Infinity", "-Infinity", "-1", "0"])
def test_invalid_financial_quantity_fails_closed(bad: str) -> None:
    with pytest.raises(IntegrityViolation):
        OrderRecord(
            "order-1", "BTCUSDT", "BUY", Decimal(bad), "NEW", NOW, "request-1"
        ).validated()


def test_invalid_timestamp_symbol_status_and_metadata_fail_closed() -> None:
    with pytest.raises(IntegrityViolation):
        OrderRecord("order-1", "../BTC", "BUY", Decimal("1"), "NEW", NOW, "request-1").validated()
    with pytest.raises(IntegrityViolation):
        OrderRecord("order-1", "BTCUSDT", "BUY", Decimal("1"), "UNKNOWN", NOW, "request-1").validated()
    with pytest.raises(IntegrityViolation):
        OrderRecord("order-1", "BTCUSDT", "BUY", Decimal("1"), "NEW", "2026-01-01", "request-1").validated()
    with pytest.raises(IntegrityViolation):
        OrderRecord(
            "order-1", "BTCUSDT", "BUY", Decimal("1"), "NEW", NOW,
            "request-1", metadata={"bad": float("nan")},
        ).validated()
    with pytest.raises(IntegrityViolation):
        parse_metadata("{broken")


def test_schema_indexes_foreign_keys_and_wal(storage: SQLiteStorage) -> None:
    connection = sqlite3.connect(storage.database_path)
    try:
        indexes = {row[1] for row in connection.execute("PRAGMA index_list(atlas_orders)")}
        assert "idx_atlas_orders_symbol_status" in indexes
        assert connection.execute("PRAGMA journal_mode").fetchone()[0].lower() == "wal"
        assert {
            row[2] for row in connection.execute("PRAGMA foreign_key_list(atlas_executions)")
        } == {"atlas_orders"}
    finally:
        connection.close()


def test_corrupt_financial_row_prevents_reopen(tmp_path: Path) -> None:
    path = tmp_path / "corrupt.sqlite3"
    backend = SQLiteStorage(path)
    backend.open()
    with backend.unit_of_work() as uow:
        uow.orders.add(order())
    backend.close()
    connection = sqlite3.connect(path, isolation_level=None)
    connection.execute(
        "UPDATE atlas_orders SET created_at_utc = 'not-a-timestamp' WHERE order_id = ?",
        ("order-1",),
    )
    connection.close()
    with pytest.raises(IntegrityViolation):
        backend.open()
    assert backend.health()["connected"] is False
    assert backend.health()["last_integrity_check"] == "FAIL"


def test_migrations_repeat_duplicate_checksum_and_future_version(tmp_path: Path) -> None:
    backend = SQLiteStorage(tmp_path / "atlas.sqlite3")
    backend.open()
    backend.close()
    backend.open()
    backend.close()
    with pytest.raises(MigrationError):
        validate_migrations((MIGRATIONS[0], MIGRATIONS[0]))
    connection = sqlite3.connect(tmp_path / "atlas.sqlite3", isolation_level=None)
    connection.execute(
        "UPDATE atlas_schema_migrations SET checksum_sha256 = ? WHERE migration_id = 1",
        ("0" * 64,),
    )
    connection.close()
    with pytest.raises(MigrationError):
        backend.open()

    future = SQLiteStorage(tmp_path / "future.sqlite3")
    future.open()
    future.close()
    connection = sqlite3.connect(tmp_path / "future.sqlite3", isolation_level=None)
    connection.execute(
        "INSERT INTO atlas_schema_migrations VALUES (?, ?, ?, ?)",
        (99, "future", "F" * 64, "2026-08-09T00:00:00Z"),
    )
    connection.close()
    with pytest.raises(MigrationError):
        future.open()


def test_failed_migration_is_transactional(tmp_path: Path) -> None:
    connection = sqlite3.connect(tmp_path / "failed.sqlite3", isolation_level=None)
    broken = (
        Migration(1, "broken", ("CREATE TABLE should_rollback (id INTEGER)", "INVALID SQL")),
    )
    with pytest.raises(sqlite3.OperationalError):
        apply_migrations(connection, broken)
    assert connection.execute(
        "SELECT COUNT(*) FROM sqlite_master WHERE name='should_rollback'"
    ).fetchone()[0] == 0
    connection.close()


def test_locked_database_failure_propagates(tmp_path: Path) -> None:
    backend = SQLiteStorage(tmp_path / "locked.sqlite3", busy_timeout_ms=10)
    backend.open()
    lock = sqlite3.connect(backend.database_path, isolation_level=None)
    lock.execute("BEGIN EXCLUSIVE")
    try:
        with pytest.raises(sqlite3.OperationalError):
            with backend.unit_of_work():
                pass
    finally:
        lock.rollback()
        lock.close()
        backend.close()


def test_concurrent_writers_are_serialized_without_loss(storage: SQLiteStorage) -> None:
    failures: list[Exception] = []
    barrier = threading.Barrier(3)

    def write(index: int) -> None:
        try:
            barrier.wait()
            with storage.unit_of_work() as uow:
                uow.orders.add(order(f"order-{index}", f"request-{index}"))
        except Exception as exc:  # pragma: no cover - asserted below
            failures.append(exc)

    threads = [threading.Thread(target=write, args=(i,)) for i in (1, 2)]
    for thread in threads:
        thread.start()
    barrier.wait()
    for thread in threads:
        thread.join()
    assert failures == []
    with storage.unit_of_work() as uow:
        assert uow.orders.exists("order-1")
        assert uow.orders.exists("order-2")


def test_configuration_selection_and_postgresql_fail_closed(tmp_path: Path) -> None:
    config = load_storage_configuration({}, runtime_root=tmp_path)
    assert config.backend == "sqlite"
    assert isinstance(create_storage(config), SQLiteStorage)
    with pytest.raises(StorageConfigurationError):
        load_storage_configuration({"ATLAS_STORAGE_BACKEND": "unknown"})
    with pytest.raises(StorageConfigurationError):
        load_storage_configuration({"ATLAS_STORAGE_BACKEND": "postgresql"})
    pg = load_storage_configuration({
        "ATLAS_STORAGE_BACKEND": "postgresql",
        "ATLAS_POSTGRESQL_DSN": "postgresql://user:placeholder@db.example/atlas",
    })
    assert pg.safe_status()["postgresql_endpoint"] == "db.example/atlas"
    assert "placeholder" not in json.dumps(pg.safe_status())
    with pytest.raises(StorageConfigurationError, match="NOT_CONFIGURED"):
        create_storage(pg)


@pytest.mark.parametrize(
    "dsn",
    [
        "postgresql://user:secret@db.example:not-a-port/atlas",
        "postgresql://user:secret@db.example:70000/atlas",
        "postgresql://user:secret@:5432/atlas",
        "postgresql://user:secret@/atlas",
        "postgresql://user:secret@[broken/atlas",
    ],
)
def test_malformed_postgresql_dsn_fails_safely_without_secret(dsn: str) -> None:
    with pytest.raises(StorageConfigurationError):
        load_storage_configuration({
            "ATLAS_STORAGE_BACKEND": "postgresql",
            "ATLAS_POSTGRESQL_DSN": dsn,
        })
    from data_layer.config import StorageConfiguration

    status = StorageConfiguration("postgresql", postgresql_dsn=dsn).safe_status()
    assert status["postgresql_endpoint"] == "INVALID_DSN"
    assert "secret" not in json.dumps(status)


@pytest.mark.parametrize(
    ("table", "column", "value"),
    [
        ("atlas_orders", "quantity_text", "0"),
        ("atlas_orders", "limit_price_text", "-1"),
        ("atlas_executions", "quantity_text", "0"),
        ("atlas_executions", "price_text", "-1"),
        ("atlas_executions", "fee_text", "-0.01"),
    ],
)
def test_direct_sql_financial_checks_reject_invalid_values(
    storage: SQLiteStorage, table: str, column: str, value: str
) -> None:
    with storage.unit_of_work() as uow:
        uow.orders.add(order())
        uow.executions.add(ExecutionRecord(
            "exec-1", "order-1", Decimal("1"), Decimal("10"), Decimal("0"), NOW
        ))
    connection = sqlite3.connect(storage.database_path, isolation_level=None)
    try:
        identity_column = "order_id" if table == "atlas_orders" else "execution_id"
        identity = "order-1" if table == "atlas_orders" else "exec-1"
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(
                f"UPDATE {table} SET {column} = ? WHERE {identity_column} = ?",
                (value, identity),
            )
    finally:
        connection.close()


def test_legacy_readiness_is_read_only_deterministic_and_reports_invalid(tmp_path: Path) -> None:
    first = tmp_path / "first.json"
    duplicate = tmp_path / "duplicate.json"
    invalid = tmp_path / "invalid.json"
    first.write_text('[{"id": 1}]', encoding="utf-8")
    duplicate.write_bytes(first.read_bytes())
    invalid.write_text("{bad", encoding="utf-8")
    before = {p: p.read_bytes() for p in (first, duplicate, invalid)}
    report = inspect_legacy_json([invalid, duplicate, first]).as_dict()
    assert report["mode"] == "DRY_RUN_ONLY"
    assert report["scanned_files"] == 3
    assert report["valid_json_files"] == 2
    assert report["invalid_json_files"] == 1
    assert report["duplicate_content_files"] == 1
    assert {p: p.read_bytes() for p in before} == before


def test_canonical_core_does_not_import_relational_backend() -> None:
    root = Path(__file__).resolve().parents[1]
    for relative in ("core/application.py", "core/execution_manager.py", "main.py"):
        source = (root / relative).read_text(encoding="utf-8-sig")
        assert "import sqlite3" not in source
        assert "psycopg" not in source
