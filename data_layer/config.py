"""Storage backend selection with explicit PostgreSQL fail-closed behavior."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit

from .contracts import StorageConfigurationError


@dataclass(frozen=True, slots=True)
class StorageConfiguration:
    backend: str
    sqlite_path: Path | None = None
    postgresql_dsn: str | None = None

    def safe_status(self) -> dict[str, str | None]:
        return {
            "backend": self.backend,
            "sqlite_path": str(self.sqlite_path) if self.sqlite_path else None,
            "postgresql_endpoint": _safe_postgresql_endpoint(self.postgresql_dsn),
        }


def _safe_postgresql_endpoint(dsn: str | None) -> str | None:
    if not dsn:
        return None
    try:
        parsed = urlsplit(dsn)
        port_number = parsed.port
    except ValueError:
        return "INVALID_DSN"
    if parsed.scheme not in {"postgresql", "postgres"}:
        return "INVALID_DSN"
    if not parsed.hostname:
        return "INVALID_DSN"
    host = parsed.hostname
    port = f":{port_number}" if port_number is not None else ""
    database = parsed.path.lstrip("/") or "UNSPECIFIED"
    return f"{host}{port}/{database}"


def load_storage_configuration(
    environ: dict[str, str] | None = None,
    *,
    runtime_root: Path | None = None,
) -> StorageConfiguration:
    values = os.environ if environ is None else environ
    backend = values.get("ATLAS_STORAGE_BACKEND", "sqlite").strip().lower()
    if backend == "sqlite":
        root = Path(runtime_root or values.get("ATLAS_RUNTIME_DATA_DIR", "runtime_data"))
        configured = values.get("ATLAS_SQLITE_PATH")
        path = Path(configured) if configured else root / "atlas-local.sqlite3"
        if not path.is_absolute():
            path = Path.cwd() / path
        return StorageConfiguration("sqlite", sqlite_path=path.resolve())
    if backend == "postgresql":
        dsn = values.get("ATLAS_POSTGRESQL_DSN", "").strip()
        if not dsn:
            raise StorageConfigurationError(
                "PostgreSQL selected but ATLAS_POSTGRESQL_DSN is not configured"
            )
        if _safe_postgresql_endpoint(dsn) == "INVALID_DSN":
            raise StorageConfigurationError("invalid PostgreSQL DSN")
        return StorageConfiguration("postgresql", postgresql_dsn=dsn)
    raise StorageConfigurationError(f"unsupported storage backend: {backend!r}")


def create_storage(config: StorageConfiguration):
    if config.backend == "sqlite" and config.sqlite_path is not None:
        from .sqlite import SQLiteStorage
        return SQLiteStorage(config.sqlite_path)
    if config.backend == "postgresql":
        raise StorageConfigurationError(
            "PostgreSQL adapter is NOT_CONFIGURED; refusing SQLite fallback"
        )
    raise StorageConfigurationError("storage configuration is incomplete")
