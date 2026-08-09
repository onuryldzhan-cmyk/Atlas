"""Forward-only, checksummed relational schema migrations."""

from __future__ import annotations

import hashlib
import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime

from .contracts import MigrationError


@dataclass(frozen=True, slots=True)
class Migration:
    migration_id: int
    name: str
    statements: tuple[str, ...]

    @property
    def checksum(self) -> str:
        body = "\n-- statement --\n".join(self.statements).encode("utf-8")
        return hashlib.sha256(body).hexdigest().upper()


MIGRATIONS = (
    Migration(
        1,
        "financial_repository_foundation",
        (
            """
            CREATE TABLE atlas_orders (
                order_id TEXT PRIMARY KEY CHECK (trim(order_id) <> ''),
                symbol TEXT NOT NULL CHECK (trim(symbol) <> ''),
                side TEXT NOT NULL CHECK (side IN ('BUY','SELL')),
                quantity_text TEXT NOT NULL CHECK (CAST(quantity_text AS REAL) > 0),
                limit_price_text TEXT CHECK (limit_price_text IS NULL OR CAST(limit_price_text AS REAL) > 0),
                status TEXT NOT NULL CHECK (status IN (
                    'NEW','ACCEPTED','PARTIALLY_FILLED','FILLED','CANCELLED','REJECTED'
                )),
                idempotency_key TEXT NOT NULL UNIQUE CHECK (trim(idempotency_key) <> ''),
                strategy TEXT,
                created_at_utc TEXT NOT NULL,
                metadata_json TEXT NOT NULL CHECK (json_valid(metadata_json))
            )
            """,
            "CREATE INDEX idx_atlas_orders_symbol_status ON atlas_orders(symbol, status)",
            """
            CREATE TABLE atlas_executions (
                execution_id TEXT PRIMARY KEY CHECK (trim(execution_id) <> ''),
                order_id TEXT NOT NULL CHECK (trim(order_id) <> '') REFERENCES atlas_orders(order_id) ON DELETE RESTRICT,
                quantity_text TEXT NOT NULL CHECK (CAST(quantity_text AS REAL) > 0),
                price_text TEXT NOT NULL CHECK (CAST(price_text AS REAL) > 0),
                fee_text TEXT NOT NULL CHECK (CAST(fee_text AS REAL) >= 0),
                realized_pnl_text TEXT,
                executed_at_utc TEXT NOT NULL,
                metadata_json TEXT NOT NULL CHECK (json_valid(metadata_json))
            )
            """,
            "CREATE INDEX idx_atlas_executions_order_time ON atlas_executions(order_id, executed_at_utc)",
            """
            CREATE TABLE atlas_positions (
                position_id TEXT PRIMARY KEY CHECK (trim(position_id) <> ''),
                symbol TEXT NOT NULL CHECK (trim(symbol) <> ''),
                quantity_text TEXT NOT NULL CHECK (CAST(quantity_text AS REAL) >= 0),
                average_price_text TEXT NOT NULL CHECK (CAST(average_price_text AS REAL) >= 0),
                realized_pnl_text TEXT NOT NULL,
                status TEXT NOT NULL CHECK (status IN ('OPEN','CLOSED')),
                updated_at_utc TEXT NOT NULL,
                metadata_json TEXT NOT NULL CHECK (json_valid(metadata_json))
            )
            """,
            "CREATE INDEX idx_atlas_positions_symbol_status ON atlas_positions(symbol, status)",
            "CREATE UNIQUE INDEX uq_atlas_open_position_symbol ON atlas_positions(symbol) WHERE status = 'OPEN'",
        ),
    ),
)


def validate_migrations(migrations: tuple[Migration, ...] = MIGRATIONS) -> None:
    ids = [item.migration_id for item in migrations]
    if len(ids) != len(set(ids)):
        raise MigrationError("duplicate migration ID")
    if ids != sorted(ids) or ids != list(range(1, len(ids) + 1)):
        raise MigrationError("migrations must be contiguous and ordered")
    if any(not item.name.strip() or not item.statements for item in migrations):
        raise MigrationError("migration identity/statements are incomplete")


def apply_migrations(
    connection: sqlite3.Connection,
    migrations: tuple[Migration, ...] = MIGRATIONS,
) -> int:
    validate_migrations(migrations)
    connection.execute("BEGIN IMMEDIATE")
    try:
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS atlas_schema_migrations (
                migration_id INTEGER PRIMARY KEY,
                name TEXT NOT NULL UNIQUE,
                checksum_sha256 TEXT NOT NULL,
                applied_at_utc TEXT NOT NULL
            )
            """
        )
        applied = {
            row[0]: (row[1], row[2])
            for row in connection.execute(
                "SELECT migration_id, name, checksum_sha256 FROM atlas_schema_migrations"
            )
        }
        latest = max(applied, default=0)
        if latest > len(migrations):
            raise MigrationError("database schema is newer than this application")
        for migration in migrations:
            prior = applied.get(migration.migration_id)
            identity = (migration.name, migration.checksum)
            if prior is not None:
                if prior != identity:
                    raise MigrationError(
                        f"migration {migration.migration_id} identity/checksum mismatch"
                    )
                continue
            if migration.migration_id != latest + 1:
                raise MigrationError("migration history contains a gap")
            for statement in migration.statements:
                connection.execute(statement)
            connection.execute(
                """
                INSERT INTO atlas_schema_migrations
                    (migration_id, name, checksum_sha256, applied_at_utc)
                VALUES (?, ?, ?, ?)
                """,
                (
                    migration.migration_id,
                    migration.name,
                    migration.checksum,
                    datetime.now(UTC).isoformat().replace("+00:00", "Z"),
                ),
            )
            latest = migration.migration_id
        connection.commit()
        return latest
    except Exception:
        connection.rollback()
        raise
