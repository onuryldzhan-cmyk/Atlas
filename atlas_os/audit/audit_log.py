"""
============================================================
ATLAS OS AUDIT LOG SERVICE v1.0
============================================================

Persistent event audit infrastructure for AtlasOS.

Responsibilities
----------------
- Subscribe to AtlasOS Event Bus
- Record all system events
- Write immutable JSONL audit records
- Maintain bounded in-memory history
- Query records by event type
- Query records by source
- Query records by severity
- Query records by correlation identifier
- Support audit file rotation
- Recover existing audit records
- Maintain audit statistics
- Isolate file-system failures
- Produce diagnostic snapshots

Architecture
------------
AtlasOS Event Bus
        |
        v
AuditLogService
        |
        +-- JSONL persistence
        +-- In-memory history
        +-- Query engine
        +-- File rotation
        +-- Audit statistics

Design principles
-----------------
- Append-only persistence
- Thread safe
- Failure isolated
- Human-readable JSONL
- Deterministic serialization
- Bounded memory usage
- Restart compatible
- No trading-specific dependency

============================================================
"""

from __future__ import annotations

import json
import logging
import os
import threading
import uuid

from collections import deque
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Iterable, Mapping

from atlas_security import sanitize_sensitive_mapping

from atlas_os.contracts import (
    ServiceIdentity,
)
from atlas_os.events import (
    AtlasEvent,
    EventBusService,
    EventSeverity,
    Subscription,
)
from atlas_os.services import (
    BaseAtlasService,
)


logger = logging.getLogger(
    "AtlasAI.AtlasOS.AuditLog"
)


class AuditLogError(RuntimeError):
    """
    Base exception for Audit Log operations.
    """


class AuditPersistenceError(AuditLogError):
    """
    Raised when an audit record cannot be persisted.
    """


@dataclass(frozen=True, slots=True)
class AuditRecord:
    """
    Immutable normalized audit record.
    """

    audit_id: str
    event_id: str
    event_type: str
    source: str
    severity: str
    correlation_id: str | None
    payload: Mapping[str, Any]
    event_created_at: datetime
    recorded_at: datetime
    schema_version: str = "1.0"

    def to_dict(self) -> dict[str, Any]:
        """
        Convert the audit record into a JSON-compatible dictionary.
        """

        return {
            "schema_version": self.schema_version,
            "audit_id": self.audit_id,
            "event_id": self.event_id,
            "event_type": self.event_type,
            "source": self.source,
            "severity": self.severity,
            "correlation_id": self.correlation_id,
            "payload": sanitize_sensitive_mapping(
                self.payload
            ),
            "event_created_at": (
                self.event_created_at.isoformat()
            ),
            "recorded_at": (
                self.recorded_at.isoformat()
            ),
        }

    @classmethod
    def from_dict(
        cls,
        data: Mapping[str, Any],
    ) -> "AuditRecord":
        """
        Reconstruct an audit record from persisted JSON data.
        """

        return cls(
            schema_version=str(
                data.get(
                    "schema_version",
                    "1.0",
                )
            ),
            audit_id=str(
                data["audit_id"]
            ),
            event_id=str(
                data["event_id"]
            ),
            event_type=str(
                data["event_type"]
            ),
            source=str(
                data["source"]
            ),
            severity=str(
                data["severity"]
            ),
            correlation_id=(
                str(data["correlation_id"])
                if data.get("correlation_id")
                is not None
                else None
            ),
            payload=sanitize_sensitive_mapping(
                data.get(
                    "payload",
                    {},
                )
            ),
            event_created_at=datetime.fromisoformat(
                str(
                    data["event_created_at"]
                )
            ),
            recorded_at=datetime.fromisoformat(
                str(
                    data["recorded_at"]
                )
            ),
        )


@dataclass(frozen=True, slots=True)
class AuditQuery:
    """
    Query criteria for audit records.
    """

    event_types: tuple[str, ...] = ()
    sources: tuple[str, ...] = ()
    severities: tuple[str, ...] = ()
    correlation_id: str | None = None
    start_time: datetime | None = None
    end_time: datetime | None = None
    limit: int | None = None
    newest_first: bool = False


@dataclass(frozen=True, slots=True)
class AuditStatistics:
    """
    Immutable Audit Log runtime statistics.
    """

    records_received: int
    records_persisted: int
    persistence_failures: int
    records_loaded: int
    rotations: int
    current_history_size: int
    current_file_size_bytes: int
    last_recorded_event_type: str | None
    last_error: str | None
    generated_at: datetime = field(
        default_factory=lambda: datetime.now(UTC)
    )


@dataclass(frozen=True, slots=True)
class AuditLogSnapshot:
    """
    Immutable diagnostic snapshot of Audit Log Service.
    """

    running: bool
    subscribed: bool
    audit_file: str
    history_limit: int
    history_size: int
    rotation_size_bytes: int
    statistics: AuditStatistics
    last_record: AuditRecord | None
    generated_at: datetime = field(
        default_factory=lambda: datetime.now(UTC)
    )


class AuditLogService(BaseAtlasService):
    """
    Persistent AtlasOS Event Bus audit listener.

    The service subscribes to the Event Bus wildcard event type and
    records every received event as one JSON object per line.

    Example
    -------
    audit = AuditLogService(
        event_bus,
        audit_file="runtime_data/audit/atlas_os_audit.jsonl",
    )

    audit.start()

    records = audit.query(
        AuditQuery(
            event_types=("KERNEL_STARTED",),
        )
    )
    """

    VERSION = "1.0.0"

    NAME = "AtlasOSAuditLog"

    def __init__(
        self,
        event_bus: EventBusService,
        *,
        audit_file: str | Path = (
            "runtime_data/audit/"
            "atlas_os_audit.jsonl"
        ),
        history_limit: int = 1000,
        rotation_size_bytes: int = 10_000_000,
        load_existing_records: bool = True,
        raise_on_persistence_failure: bool = False,
    ) -> None:

        if not isinstance(
            event_bus,
            EventBusService,
        ):
            raise TypeError(
                "event_bus must be an EventBusService instance."
            )

        if history_limit <= 0:
            raise ValueError(
                "history_limit must be greater than zero."
            )

        if rotation_size_bytes <= 0:
            raise ValueError(
                "rotation_size_bytes must be greater than zero."
            )

        super().__init__(
            ServiceIdentity(
                name=self.NAME,
                version=self.VERSION,
                service_type="AUDIT",
                description=(
                    "Persistent JSONL audit logging service "
                    "for AtlasOS events."
                ),
            )
        )

        self._event_bus = event_bus

        self._audit_file = Path(
            audit_file
        )

        self._history_limit = int(
            history_limit
        )

        self._rotation_size_bytes = int(
            rotation_size_bytes
        )

        self._load_existing_records = bool(
            load_existing_records
        )

        self._raise_on_persistence_failure = bool(
            raise_on_persistence_failure
        )

        self._records: deque[
            AuditRecord
        ] = deque(
            maxlen=self._history_limit
        )

        self._subscription: (
            Subscription | None
        ) = None

        self._records_received = 0
        self._records_persisted = 0
        self._persistence_failures = 0
        self._records_loaded = 0
        self._rotations = 0

        self._last_recorded_event_type: (
            str | None
        ) = None

        self._last_error: str | None = None

        self._audit_lock = threading.RLock()

    # =====================================================
    # PROPERTIES
    # =====================================================

    @property
    def event_bus(self) -> EventBusService:
        """
        Return associated Event Bus.
        """

        return self._event_bus

    @property
    def audit_file(self) -> Path:
        """
        Return audit JSONL file path.
        """

        return self._audit_file

    @property
    def history_limit(self) -> int:
        """
        Return bounded in-memory history limit.
        """

        return self._history_limit

    @property
    def rotation_size_bytes(self) -> int:
        """
        Return maximum file size before rotation.
        """

        return self._rotation_size_bytes

    @property
    def subscribed(self) -> bool:
        """
        Return True when the Event Bus subscription exists.
        """

        with self._audit_lock:
            return self._subscription is not None

    @property
    def record_count(self) -> int:
        """
        Return current in-memory record count.
        """

        with self._audit_lock:
            return len(self._records)

    @property
    def last_record(
        self,
    ) -> AuditRecord | None:
        """
        Return most recently retained audit record.
        """

        with self._audit_lock:

            if not self._records:
                return None

            return self._records[-1]

    # =====================================================
    # SERVICE LIFECYCLE
    # =====================================================

    def _on_start(self) -> None:
        """
        Prepare storage and subscribe to all AtlasOS events.
        """

        self._prepare_storage()

        if self._load_existing_records:
            self.load_existing()

        self._subscription = (
            self._event_bus.subscribe(
                "*",
                self.record_event,
                subscriber_name=self.identity.name,
            )
        )

        logger.info(
            "AtlasOS Audit Log started | file=%s",
            self._audit_file,
        )

    def _on_stop(self) -> None:
        """
        Remove Event Bus subscription.
        """

        subscription = self._subscription

        if subscription is not None:

            try:

                self._event_bus.unsubscribe(
                    subscription.subscription_id
                )

            except Exception:

                logger.exception(
                    "AtlasOS Audit Log could not remove "
                    "Event Bus subscription."
                )

        self._subscription = None

        logger.info(
            "AtlasOS Audit Log stopped."
        )

    # =====================================================
    # EVENT RECORDING
    # =====================================================

    def record_event(
        self,
        event: AtlasEvent,
    ) -> AuditRecord:
        """
        Convert and persist one Atlas event.
        """

        if not isinstance(event, AtlasEvent):
            raise TypeError(
                "event must be an AtlasEvent instance."
            )

        record = AuditRecord(
            audit_id=str(
                uuid.uuid4()
            ),
            event_id=event.event_id,
            event_type=event.event_type,
            source=event.source,
            severity=event.severity.value,
            correlation_id=event.correlation_id,
            payload=sanitize_sensitive_mapping(
                event.payload
            ),
            event_created_at=event.created_at,
            recorded_at=datetime.now(UTC),
        )

        with self._audit_lock:

            self._records_received += 1

        try:

            self._persist_record(
                record
            )

        except Exception as exc:

            error = (
                f"{type(exc).__name__}: {exc}"
            )

            with self._audit_lock:

                self._persistence_failures += 1
                self._last_error = error

            logger.exception(
                "AtlasOS Audit Log persistence failed | "
                "event=%s",
                event.event_type,
            )

            if self._raise_on_persistence_failure:
                raise AuditPersistenceError(
                    error
                ) from exc

        with self._audit_lock:

            self._records.append(
                record
            )

            self._last_recorded_event_type = (
                record.event_type
            )

        return record

    def _persist_record(
        self,
        record: AuditRecord,
    ) -> None:
        """
        Append one audit record to JSONL storage.
        """

        with self._audit_lock:

            self._prepare_storage()

            self._rotate_if_required()

            serialized = json.dumps(
                record.to_dict(),
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
                default=self._json_default,
            )

            with self._audit_file.open(
                mode="a",
                encoding="utf-8",
                newline="\n",
            ) as audit_stream:

                audit_stream.write(
                    serialized
                )

                audit_stream.write(
                    "\n"
                )

                audit_stream.flush()

                try:
                    os.fsync(
                        audit_stream.fileno()
                    )
                except OSError:
                    pass

            self._records_persisted += 1
            self._last_error = None

    # =====================================================
    # STORAGE
    # =====================================================

    def _prepare_storage(self) -> None:
        """
        Create audit directory and file when necessary.
        """

        self._audit_file.parent.mkdir(
            parents=True,
            exist_ok=True,
        )

        self._audit_file.touch(
            exist_ok=True
        )

    def load_existing(self) -> int:
        """
        Load valid records from the current audit file.

        Invalid or corrupted lines are skipped and logged.
        """

        self._prepare_storage()

        loaded_records: list[
            AuditRecord
        ] = []

        with self._audit_file.open(
            mode="r",
            encoding="utf-8",
        ) as audit_stream:

            for line_number, raw_line in enumerate(
                audit_stream,
                start=1,
            ):

                line = raw_line.strip()

                if not line:
                    continue

                try:

                    parsed = json.loads(
                        line
                    )

                    record = (
                        AuditRecord.from_dict(
                            parsed
                        )
                    )

                    loaded_records.append(
                        record
                    )

                except Exception:

                    logger.exception(
                        "Invalid AtlasOS audit line skipped | "
                        "file=%s | line=%s",
                        self._audit_file,
                        line_number,
                    )

        retained = loaded_records[
            -self._history_limit:
        ]

        with self._audit_lock:

            self._records.clear()

            self._records.extend(
                retained
            )

            self._records_loaded += len(
                loaded_records
            )

            if self._records:

                self._last_recorded_event_type = (
                    self._records[-1].event_type
                )

        return len(
            loaded_records
        )

    def rotate(self) -> Path | None:
        """
        Rotate the current audit file manually.

        Returns the rotated file path, or None when the file is empty.
        """

        with self._audit_lock:

            self._prepare_storage()

            if self._current_file_size() == 0:
                return None

            timestamp = datetime.now(
                UTC
            ).strftime(
                "%Y%m%dT%H%M%S_%fZ"
            )

            rotated_path = (
                self._audit_file.with_name(
                    f"{self._audit_file.stem}_"
                    f"{timestamp}"
                    f"{self._audit_file.suffix}"
                )
            )

            self._audit_file.replace(
                rotated_path
            )

            self._audit_file.touch(
                exist_ok=True
            )

            self._rotations += 1

            logger.info(
                "AtlasOS audit file rotated | "
                "old=%s | new=%s",
                self._audit_file,
                rotated_path,
            )

            return rotated_path

    def _rotate_if_required(self) -> None:
        """
        Rotate storage when configured size is reached.
        """

        if (
            self._current_file_size()
            >= self._rotation_size_bytes
        ):
            self.rotate()

    def _current_file_size(self) -> int:
        """
        Return current audit file size.
        """

        try:

            return self._audit_file.stat().st_size

        except FileNotFoundError:

            return 0

    # =====================================================
    # QUERY ENGINE
    # =====================================================

    def records(
        self,
    ) -> tuple[AuditRecord, ...]:
        """
        Return retained in-memory records.
        """

        with self._audit_lock:

            return tuple(
                self._records
            )

    def query(
        self,
        query: AuditQuery,
    ) -> tuple[AuditRecord, ...]:
        """
        Query retained audit history.
        """

        if not isinstance(
            query,
            AuditQuery,
        ):
            raise TypeError(
                "query must be an AuditQuery instance."
            )

        records = list(
            self.records()
        )

        normalized_event_types = {
            value.strip().upper()
            for value in query.event_types
            if value.strip()
        }

        normalized_sources = {
            value.strip().casefold()
            for value in query.sources
            if value.strip()
        }

        normalized_severities = {
            value.strip().upper()
            for value in query.severities
            if value.strip()
        }

        filtered: list[
            AuditRecord
        ] = []

        for record in records:

            if (
                normalized_event_types
                and record.event_type.upper()
                not in normalized_event_types
            ):
                continue

            if (
                normalized_sources
                and record.source.casefold()
                not in normalized_sources
            ):
                continue

            if (
                normalized_severities
                and record.severity.upper()
                not in normalized_severities
            ):
                continue

            if (
                query.correlation_id is not None
                and record.correlation_id
                != query.correlation_id
            ):
                continue

            if (
                query.start_time is not None
                and record.recorded_at
                < query.start_time
            ):
                continue

            if (
                query.end_time is not None
                and record.recorded_at
                > query.end_time
            ):
                continue

            filtered.append(
                record
            )

        if query.newest_first:
            filtered.reverse()

        if query.limit is not None:

            if query.limit < 0:
                raise ValueError(
                    "Query limit cannot be negative."
                )

            filtered = filtered[
                :query.limit
            ]

        return tuple(
            filtered
        )

    def find_by_correlation_id(
        self,
        correlation_id: str,
    ) -> tuple[AuditRecord, ...]:
        """
        Return retained records sharing a correlation ID.
        """

        normalized_id = (
            correlation_id.strip()
        )

        if not normalized_id:
            raise ValueError(
                "Correlation ID cannot be empty."
            )

        return self.query(
            AuditQuery(
                correlation_id=normalized_id
            )
        )

    def clear_memory_history(self) -> None:
        """
        Clear only in-memory audit history.

        Persistent JSONL storage is preserved.
        """

        with self._audit_lock:
            self._records.clear()

    # =====================================================
    # STATISTICS / SNAPSHOT
    # =====================================================

    def statistics(
        self,
    ) -> AuditStatistics:
        """
        Return immutable Audit Log statistics.
        """

        with self._audit_lock:

            return AuditStatistics(
                records_received=(
                    self._records_received
                ),
                records_persisted=(
                    self._records_persisted
                ),
                persistence_failures=(
                    self._persistence_failures
                ),
                records_loaded=(
                    self._records_loaded
                ),
                rotations=self._rotations,
                current_history_size=len(
                    self._records
                ),
                current_file_size_bytes=(
                    self._current_file_size()
                ),
                last_recorded_event_type=(
                    self._last_recorded_event_type
                ),
                last_error=self._last_error,
            )

    def audit_snapshot(
        self,
    ) -> AuditLogSnapshot:
        """
        Return complete Audit Log diagnostics.
        """

        return AuditLogSnapshot(
            running=self.is_running,
            subscribed=self.subscribed,
            audit_file=str(
                self._audit_file
            ),
            history_limit=self._history_limit,
            history_size=self.record_count,
            rotation_size_bytes=(
                self._rotation_size_bytes
            ),
            statistics=self.statistics(),
            last_record=self.last_record,
        )

    # =====================================================
    # BASE SERVICE DIAGNOSTICS
    # =====================================================

    def _health_details(
        self,
    ) -> Mapping[str, Any]:
        """
        Return Audit Log health details.
        """

        statistics = self.statistics()

        return {
            "subscribed": self.subscribed,
            "audit_file": str(
                self._audit_file
            ),
            "audit_file_exists": (
                self._audit_file.exists()
            ),
            "history_size": (
                statistics.current_history_size
            ),
            "records_received": (
                statistics.records_received
            ),
            "records_persisted": (
                statistics.records_persisted
            ),
            "persistence_failures": (
                statistics.persistence_failures
            ),
            "rotations": (
                statistics.rotations
            ),
            "file_size_bytes": (
                statistics.current_file_size_bytes
            ),
            "last_error": (
                statistics.last_error
            ),
        }

    def _snapshot_metadata(
        self,
    ) -> Mapping[str, Any]:
        """
        Return Audit Log configuration metadata.
        """

        return {
            "history_limit": (
                self._history_limit
            ),
            "rotation_size_bytes": (
                self._rotation_size_bytes
            ),
            "load_existing_records": (
                self._load_existing_records
            ),
            "raise_on_persistence_failure": (
                self._raise_on_persistence_failure
            ),
            "storage_format": "JSONL",
            "schema_version": "1.0",
        }

    # =====================================================
    # SERIALIZATION
    # =====================================================

    @staticmethod
    def _json_default(
        value: Any,
    ) -> Any:
        """
        Convert common non-JSON values safely.
        """

        if isinstance(
            value,
            datetime,
        ):
            return value.isoformat()

        if isinstance(
            value,
            Path,
        ):
            return str(value)

        if isinstance(
            value,
            set,
        ):
            return sorted(
                value,
                key=str,
            )

        if hasattr(
            value,
            "value",
        ):
            return value.value

        if hasattr(
            value,
            "__dict__",
        ):
            return dict(
                value.__dict__
            )

        return str(value)
