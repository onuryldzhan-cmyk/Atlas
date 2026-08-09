"""SQLite development/test backend for Atlas repository contracts."""

from __future__ import annotations

import sqlite3
import threading
from datetime import datetime
from decimal import Decimal
from enum import Enum, auto
from pathlib import Path
from typing import Any

from .contracts import IntegrityViolation, StorageError, TransactionStateError, UnitOfWork
from .migrations import MIGRATIONS, apply_migrations
from .models import (
    ExecutionRecord,
    OrderRecord,
    PositionRecord,
    decimal_text,
    metadata_text,
    normalize_symbol,
    parse_metadata,
    utc_text,
)


def _translate_integrity(exc: sqlite3.IntegrityError) -> IntegrityViolation:
    return IntegrityViolation(f"relational integrity violation: {exc}")


class _UnitOfWorkState(Enum):
    NEW = auto()
    ACTIVE = auto()
    COMMITTED = auto()
    ROLLED_BACK = auto()
    FAILED = auto()
    CLOSED = auto()


class _GuardedConnection:
    """Permit repository SQL only during the owning UoW's active transaction."""

    def __init__(self, owner: "SQLiteUnitOfWork", connection: sqlite3.Connection):
        self._owner = owner
        self._connection = connection

    def execute(self, sql: str, parameters=()):
        with self._owner._state_lock:
            self._owner._require_active()
            return self._connection.execute(sql, parameters)


class SQLiteOrderRepository:
    def __init__(self, connection):
        self._connection = connection

    def add(self, record: OrderRecord) -> None:
        record.validated()
        try:
            self._connection.execute(
                """
                INSERT INTO atlas_orders (
                    order_id, symbol, side, quantity_text, limit_price_text,
                    status, idempotency_key, strategy, created_at_utc, metadata_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    record.order_id,
                    normalize_symbol(record.symbol),
                    record.side,
                    decimal_text(record.quantity, "quantity", positive=True),
                    None if record.limit_price is None else decimal_text(record.limit_price, "limit_price", positive=True),
                    record.status,
                    record.idempotency_key,
                    record.strategy,
                    utc_text(record.created_at),
                    metadata_text(record.metadata),
                ),
            )
        except sqlite3.IntegrityError as exc:
            raise _translate_integrity(exc) from exc

    def get(self, order_id: str) -> OrderRecord | None:
        row = self._connection.execute(
            """
            SELECT order_id, symbol, side, quantity_text, status, created_at_utc,
                   idempotency_key, limit_price_text, strategy, metadata_json
            FROM atlas_orders WHERE order_id = ?
            """,
            (order_id,),
        ).fetchone()
        if row is None:
            return None
        return OrderRecord(
            order_id=row[0], symbol=row[1], side=row[2], quantity=Decimal(row[3]),
            status=row[4], created_at=row[5], idempotency_key=row[6],
            limit_price=None if row[7] is None else Decimal(row[7]),
            strategy=row[8], metadata=parse_metadata(row[9]),
        ).validated()

    def exists(self, order_id: str) -> bool:
        return self._connection.execute(
            "SELECT 1 FROM atlas_orders WHERE order_id = ?", (order_id,)
        ).fetchone() is not None


class SQLiteExecutionRepository:
    def __init__(self, connection):
        self._connection = connection

    def add(self, record: ExecutionRecord) -> None:
        record.validated()
        try:
            self._connection.execute(
                """
                INSERT INTO atlas_executions (
                    execution_id, order_id, quantity_text, price_text, fee_text,
                    realized_pnl_text, executed_at_utc, metadata_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    record.execution_id, record.order_id,
                    decimal_text(record.quantity, "quantity", positive=True),
                    decimal_text(record.price, "price", positive=True),
                    decimal_text(record.fee, "fee", nonnegative=True),
                    None if record.realized_pnl is None else decimal_text(record.realized_pnl, "realized_pnl"),
                    utc_text(record.executed_at), metadata_text(record.metadata),
                ),
            )
        except sqlite3.IntegrityError as exc:
            raise _translate_integrity(exc) from exc

    @staticmethod
    def _record(row: sqlite3.Row | tuple[Any, ...]) -> ExecutionRecord:
        return ExecutionRecord(
            execution_id=row[0], order_id=row[1], quantity=Decimal(row[2]),
            price=Decimal(row[3]), fee=Decimal(row[4]),
            realized_pnl=None if row[5] is None else Decimal(row[5]),
            executed_at=row[6], metadata=parse_metadata(row[7]),
        ).validated()

    def get(self, execution_id: str) -> ExecutionRecord | None:
        row = self._connection.execute(
            """
            SELECT execution_id, order_id, quantity_text, price_text, fee_text,
                   realized_pnl_text, executed_at_utc, metadata_json
            FROM atlas_executions WHERE execution_id = ?
            """,
            (execution_id,),
        ).fetchone()
        return None if row is None else self._record(row)

    def list_for_order(self, order_id: str) -> list[ExecutionRecord]:
        rows = self._connection.execute(
            """
            SELECT execution_id, order_id, quantity_text, price_text, fee_text,
                   realized_pnl_text, executed_at_utc, metadata_json
            FROM atlas_executions WHERE order_id = ?
            ORDER BY executed_at_utc, execution_id
            """,
            (order_id,),
        )
        return [self._record(row) for row in rows]


class SQLitePositionRepository:
    def __init__(self, connection):
        self._connection = connection

    def put(self, record: PositionRecord) -> None:
        record.validated()
        try:
            self._connection.execute(
                """
                INSERT INTO atlas_positions (
                    position_id, symbol, quantity_text, average_price_text,
                    realized_pnl_text, status, updated_at_utc, metadata_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(position_id) DO UPDATE SET
                    symbol=excluded.symbol,
                    quantity_text=excluded.quantity_text,
                    average_price_text=excluded.average_price_text,
                    realized_pnl_text=excluded.realized_pnl_text,
                    status=excluded.status,
                    updated_at_utc=excluded.updated_at_utc,
                    metadata_json=excluded.metadata_json
                """,
                (
                    record.position_id, normalize_symbol(record.symbol),
                    decimal_text(record.quantity, "quantity", nonnegative=True),
                    decimal_text(record.average_price, "average_price", nonnegative=True),
                    decimal_text(record.realized_pnl, "realized_pnl"),
                    record.status, utc_text(record.updated_at), metadata_text(record.metadata),
                ),
            )
        except sqlite3.IntegrityError as exc:
            raise _translate_integrity(exc) from exc

    @staticmethod
    def _record(row: sqlite3.Row | tuple[Any, ...]) -> PositionRecord:
        return PositionRecord(
            position_id=row[0], symbol=row[1], quantity=Decimal(row[2]),
            average_price=Decimal(row[3]), realized_pnl=Decimal(row[4]),
            status=row[5], updated_at=row[6], metadata=parse_metadata(row[7]),
        ).validated()

    def get(self, position_id: str) -> PositionRecord | None:
        row = self._connection.execute(
            """
            SELECT position_id, symbol, quantity_text, average_price_text,
                   realized_pnl_text, status, updated_at_utc, metadata_json
            FROM atlas_positions WHERE position_id = ?
            """,
            (position_id,),
        ).fetchone()
        return None if row is None else self._record(row)

    def get_open_for_symbol(self, symbol: str) -> PositionRecord | None:
        row = self._connection.execute(
            """
            SELECT position_id, symbol, quantity_text, average_price_text,
                   realized_pnl_text, status, updated_at_utc, metadata_json
            FROM atlas_positions WHERE symbol = ? AND status = 'OPEN'
            """,
            (normalize_symbol(symbol),),
        ).fetchone()
        return None if row is None else self._record(row)


class SQLiteUnitOfWork(UnitOfWork):
    """One owned connection and one non-nestable database transaction."""

    def __init__(self, storage: "SQLiteStorage"):
        self._storage = storage
        self._connection: sqlite3.Connection | None = None
        self._state = _UnitOfWorkState.NEW
        self._state_lock = threading.RLock()

    def _require_active(self) -> None:
        if self._state is not _UnitOfWorkState.ACTIVE or self._connection is None:
            raise TransactionStateError(
                f"unit of work is not operational (state={self._state.name})"
            )

    def __enter__(self) -> "SQLiteUnitOfWork":
        with self._state_lock:
            if self._state is not _UnitOfWorkState.NEW:
                raise TransactionStateError("unit of work cannot be nested or reused")
            self._connection = self._storage._connect()
            try:
                self._connection.execute("BEGIN IMMEDIATE")
            except Exception:
                self._storage._transaction_failures += 1
                self._state = _UnitOfWorkState.FAILED
                self._connection.close()
                self._connection = None
                raise
            self._state = _UnitOfWorkState.ACTIVE
            guarded = _GuardedConnection(self, self._connection)
            self.orders = SQLiteOrderRepository(guarded)
            self.executions = SQLiteExecutionRepository(guarded)
            self.positions = SQLitePositionRepository(guarded)
            return self

    def commit(self) -> None:
        with self._state_lock:
            self._require_active()
            try:
                self._connection.commit()
            except Exception:
                self._state = _UnitOfWorkState.FAILED
                self._storage._transaction_failures += 1
                raise
            self._state = _UnitOfWorkState.COMMITTED

    def rollback(self) -> None:
        with self._state_lock:
            self._require_active()
            try:
                self._connection.rollback()
            except Exception:
                self._state = _UnitOfWorkState.FAILED
                self._storage._transaction_failures += 1
                raise
            self._state = _UnitOfWorkState.ROLLED_BACK

    def __exit__(self, exc_type, exc, traceback) -> bool:
        try:
            if self._state is _UnitOfWorkState.ACTIVE:
                if exc_type is None:
                    self.commit()
                else:
                    self.rollback()
        finally:
            with self._state_lock:
                if self._connection is not None:
                    self._connection.close()
                    self._connection = None
                if self._state is not _UnitOfWorkState.FAILED:
                    self._state = _UnitOfWorkState.CLOSED
        return False


class SQLiteStorage:
    """Explicit-lifecycle SQLite backend for local development and tests."""

    backend_identity = "sqlite-local"
    capabilities = frozenset({
        "transactions", "foreign_keys", "wal", "busy_timeout",
        "checksummed_migrations", "decimal_text",
    })

    def __init__(self, database_path: Path | str, *, busy_timeout_ms: int = 5_000):
        self.database_path = Path(database_path).expanduser().resolve()
        self.busy_timeout_ms = int(busy_timeout_ms)
        if self.busy_timeout_ms < 0:
            raise ValueError("busy timeout must be nonnegative")
        self._opened = False
        self._lifecycle_lock = threading.RLock()
        self._transaction_failures = 0
        self._last_integrity_check: str | None = None

    def _connect(self) -> sqlite3.Connection:
        if not self._opened:
            raise StorageError("storage backend is not open")
        connection = sqlite3.connect(
            self.database_path,
            timeout=self.busy_timeout_ms / 1000,
            isolation_level=None,
        )
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
                apply_migrations(connection)
                result = connection.execute("PRAGMA integrity_check").fetchone()
                if result is None or result[0] != "ok":
                    raise StorageError("SQLite integrity check failed")
                self._validate_financial_rows(connection)
                self._last_integrity_check = "PASS"
            except Exception:
                self._opened = False
                self._last_integrity_check = "FAIL"
                raise
            finally:
                if connection is not None:
                    connection.close()

    @staticmethod
    def _validate_financial_rows(connection: sqlite3.Connection) -> None:
        orders = SQLiteOrderRepository(connection)
        executions = SQLiteExecutionRepository(connection)
        positions = SQLitePositionRepository(connection)
        for (record_id,) in connection.execute("SELECT order_id FROM atlas_orders"):
            if orders.get(record_id) is None:
                raise IntegrityViolation("order disappeared during integrity validation")
        for (record_id,) in connection.execute(
            "SELECT execution_id FROM atlas_executions"
        ):
            if executions.get(record_id) is None:
                raise IntegrityViolation(
                    "execution disappeared during integrity validation"
                )
        for (record_id,) in connection.execute(
            "SELECT position_id FROM atlas_positions"
        ):
            if positions.get(record_id) is None:
                raise IntegrityViolation(
                    "position disappeared during integrity validation"
                )

    def close(self) -> None:
        with self._lifecycle_lock:
            self._opened = False

    def unit_of_work(self) -> SQLiteUnitOfWork:
        if not self._opened:
            raise StorageError("storage backend is not open")
        return SQLiteUnitOfWork(self)

    @property
    def schema_version(self) -> int:
        connection = self._connect()
        try:
            row = connection.execute(
                "SELECT COALESCE(MAX(migration_id), 0) FROM atlas_schema_migrations"
            ).fetchone()
            return int(row[0])
        finally:
            connection.close()

    def health(self) -> dict[str, Any]:
        status: dict[str, Any] = {
            "backend": self.backend_identity,
            "connected": self._opened,
            "schema_version": None,
            "migration_state": "NOT_CHECKED",
            "last_integrity_check": self._last_integrity_check,
            "transaction_failures": self._transaction_failures,
            "recovery_required": False,
        }
        if not self._opened:
            return status
        try:
            status["schema_version"] = self.schema_version
            status["migration_state"] = (
                "CURRENT" if status["schema_version"] == len(MIGRATIONS) else "MISMATCH"
            )
        except Exception:
            status["migration_state"] = "ERROR"
            status["recovery_required"] = True
        return status
