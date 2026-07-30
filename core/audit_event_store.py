"""
============================================================
ATLAS AUDIT EVENT STORE v1.0
============================================================

Append-Only Cryptographic Audit Log

Purpose
-------
Persist immutable Atlas audit events in chronological order.

Responsibilities
----------------
- Append events to a JSON Lines file
- Link each event to the previous event hash
- Perform durable fsync writes
- Restore the final chain state
- Detect malformed or modified records
- Verify complete audit history
- Query events by common identifiers
- Expose health and diagnostics

Storage Format
--------------
One canonical JSON event per line:

{"event_id":"...", ...}
{"event_id":"...", ...}
{"event_id":"...", ...}

Security Model
--------------
Each event contains:

previous_hash
event_hash

Changing, deleting, reordering, or inserting historical records
causes chain verification to fail.

============================================================
"""

from __future__ import annotations

import json
import logging
import os
import threading

from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Mapping

from core.audit_event import (
    GENESIS_HASH,
    AuditEvent,
)


logger = logging.getLogger(
    "AtlasAI.AuditEventStore"
)


class AuditEventStore:
    """
    Thread-safe append-only cryptographic audit store.
    """

    VERSION = "1.0"

    NAME = "AuditEventStore"

    DEFAULT_FILE = (
        "memory_data/audit/atlas_audit_events.jsonl"
    )

    def __init__(
        self,
        file_path: str | Path = DEFAULT_FILE,
        *,
        verify_on_load: bool = True,
        fsync_enabled: bool = True,
    ) -> None:
        self.file_path = Path(
            file_path
        )

        self.verify_on_load = bool(
            verify_on_load
        )

        self.fsync_enabled = bool(
            fsync_enabled
        )

        self._lock = threading.RLock()

        self.loaded = False

        self.event_count = 0

        self.last_event_id: str | None = None

        self.last_event_hash = GENESIS_HASH

        self.last_event_timestamp: str | None = None

        self.last_error: dict[str, Any] | None = None

        self.last_verification: dict[
            str,
            Any,
        ] | None = None

        self.stats: dict[str, int] = {
            "loads": 0,
            "appends": 0,
            "reads": 0,
            "queries": 0,
            "verifications": 0,
            "verification_failures": 0,
            "malformed_records": 0,
            "write_failures": 0,
            "errors": 0,
        }

        self.load_state()

        logger.info(
            "%s v%s initialized file=%s events=%s",
            self.NAME,
            self.VERSION,
            self.file_path,
            self.event_count,
        )

    # =========================================================
    # LOAD STATE
    # =========================================================

    def load_state(
        self,
    ) -> dict[str, Any]:
        """
        Restore audit chain head from disk.
        """

        with self._lock:
            self.stats[
                "loads"
            ] += 1

            if not self.file_path.exists():
                self.loaded = True
                self.event_count = 0
                self.last_event_id = None
                self.last_event_hash = (
                    GENESIS_HASH
                )
                self.last_event_timestamp = None

                return self.status()

            if self.verify_on_load:
                verification = self.verify_chain()

                if not verification[
                    "valid"
                ]:
                    self.loaded = False

                    raise RuntimeError(
                        "Audit event chain verification failed: "
                        f"{verification.get('error')}"
                    )

            events = self.read_all()

            if not events:
                self.loaded = True
                self.event_count = 0
                self.last_event_id = None
                self.last_event_hash = (
                    GENESIS_HASH
                )
                self.last_event_timestamp = None

                return self.status()

            last_event = events[-1]

            self.loaded = True
            self.event_count = len(
                events
            )
            self.last_event_id = (
                last_event.event_id
            )
            self.last_event_hash = (
                last_event.event_hash
            )
            self.last_event_timestamp = (
                last_event.timestamp
            )

            return self.status()

    # =========================================================
    # APPEND
    # =========================================================

    def append(
        self,
        *,
        event_type: str,
        source: str,
        aggregate_type: str,
        aggregate_id: str,
        payload: Mapping[str, Any],
        event_id: str | None = None,
        timestamp: str | datetime | None = None,
        correlation_id: str | None = None,
        causation_id: str | None = None,
        metadata: Mapping[str, Any] | None = None,
    ) -> AuditEvent:
        """
        Create and durably append one chained event.
        """

        with self._lock:
            event = AuditEvent.create(
                event_type=event_type,
                source=source,
                aggregate_type=aggregate_type,
                aggregate_id=aggregate_id,
                payload=payload,
                previous_hash=(
                    self.last_event_hash
                ),
                event_id=event_id,
                timestamp=timestamp,
                correlation_id=correlation_id,
                causation_id=causation_id,
                metadata=metadata,
            )

            validation = event.validate()

            if not validation[
                "valid"
            ]:
                raise ValueError(
                    "Invalid audit event: "
                    f"{validation['errors']}"
                )

            self._append_event_locked(
                event
            )

            return event

    def append_event(
        self,
        event: AuditEvent,
    ) -> AuditEvent:
        """
        Append an externally constructed event.

        The event must reference the current chain head.
        """

        with self._lock:
            if event.previous_hash != (
                self.last_event_hash
            ):
                raise ValueError(
                    "Audit event previous_hash does not "
                    "match current chain head"
                )

            validation = event.validate()

            if not validation[
                "valid"
            ]:
                raise ValueError(
                    "Invalid audit event: "
                    f"{validation['errors']}"
                )

            self._append_event_locked(
                event
            )

            return event

    def _append_event_locked(
        self,
        event: AuditEvent,
    ) -> None:
        """
        Append a validated event while the store lock is held.
        """

        try:
            self.file_path.parent.mkdir(
                parents=True,
                exist_ok=True,
            )

            encoded_line = (
                event.to_json()
                + "\n"
            )

            with self.file_path.open(
                "a",
                encoding="utf-8",
                newline="\n",
            ) as file:
                file.write(
                    encoded_line
                )

                file.flush()

                if self.fsync_enabled:
                    os.fsync(
                        file.fileno()
                    )

            self.event_count += 1
            self.last_event_id = (
                event.event_id
            )
            self.last_event_hash = (
                event.event_hash
            )
            self.last_event_timestamp = (
                event.timestamp
            )

            self.stats[
                "appends"
            ] += 1

            logger.info(
                "Audit event appended type=%s "
                "event_id=%s aggregate=%s:%s",
                event.event_type,
                event.event_id,
                event.aggregate_type,
                event.aggregate_id,
            )

        except Exception as exc:
            self.stats[
                "write_failures"
            ] += 1

            self._record_error(
                phase="append",
                error=exc,
            )

            logger.exception(
                "Audit event append failed"
            )

            raise

    # =========================================================
    # READ
    # =========================================================

    def read_all(
        self,
    ) -> list[AuditEvent]:
        """
        Read the complete audit log.
        """

        with self._lock:
            self.stats[
                "reads"
            ] += 1

            if not self.file_path.exists():
                return []

            events: list[
                AuditEvent
            ] = []

            with self.file_path.open(
                "r",
                encoding="utf-8",
            ) as file:
                for line_number, raw_line in enumerate(
                    file,
                    start=1,
                ):
                    line = raw_line.strip()

                    if not line:
                        continue

                    try:
                        data = json.loads(
                            line
                        )

                        event = AuditEvent.from_dict(
                            data
                        )

                        events.append(
                            event
                        )

                    except Exception as exc:
                        self.stats[
                            "malformed_records"
                        ] += 1

                        raise ValueError(
                            "Malformed audit record "
                            f"at line {line_number}: {exc}"
                        ) from exc

            return events

    def tail(
        self,
        limit: int = 20,
    ) -> list[AuditEvent]:
        """
        Return the newest audit events.
        """

        normalized_limit = max(
            1,
            int(
                limit
            ),
        )

        events = self.read_all()

        return events[
            -normalized_limit:
        ]

    # =========================================================
    # QUERY
    # =========================================================

    def query(
        self,
        *,
        event_type: str | None = None,
        source: str | None = None,
        aggregate_type: str | None = None,
        aggregate_id: str | None = None,
        correlation_id: str | None = None,
        limit: int | None = None,
    ) -> list[AuditEvent]:
        """
        Query audit events using exact-match filters.
        """

        with self._lock:
            self.stats[
                "queries"
            ] += 1

        events = self.read_all()

        filtered: list[
            AuditEvent
        ] = []

        for event in events:
            if (
                event_type is not None
                and event.event_type
                != event_type
            ):
                continue

            if (
                source is not None
                and event.source
                != source
            ):
                continue

            if (
                aggregate_type is not None
                and event.aggregate_type
                != aggregate_type
            ):
                continue

            if (
                aggregate_id is not None
                and event.aggregate_id
                != aggregate_id
            ):
                continue

            if (
                correlation_id is not None
                and event.correlation_id
                != correlation_id
            ):
                continue

            filtered.append(
                event
            )

        if limit is not None:
            normalized_limit = max(
                1,
                int(
                    limit
                ),
            )

            return filtered[
                -normalized_limit:
            ]

        return filtered

    # =========================================================
    # VERIFICATION
    # =========================================================

    def verify_chain(
        self,
    ) -> dict[str, Any]:
        """
        Verify all event hashes and previous-hash links.
        """

        with self._lock:
            self.stats[
                "verifications"
            ] += 1

            if not self.file_path.exists():
                result = {
                    "valid": True,
                    "events_verified": 0,
                    "last_event_id": None,
                    "last_event_hash": (
                        GENESIS_HASH
                    ),
                    "error": None,
                    "verified_at": (
                        self._utc_now()
                    ),
                }

                self.last_verification = result

                return dict(
                    result
                )

            expected_previous_hash = (
                GENESIS_HASH
            )

            events_verified = 0

            last_event_id: str | None = None
            last_event_hash = GENESIS_HASH

            try:
                with self.file_path.open(
                    "r",
                    encoding="utf-8",
                ) as file:
                    for (
                        line_number,
                        raw_line,
                    ) in enumerate(
                        file,
                        start=1,
                    ):
                        line = raw_line.strip()

                        if not line:
                            continue

                        data = json.loads(
                            line
                        )

                        event = AuditEvent.from_dict(
                            data
                        )

                        if (
                            event.previous_hash
                            != expected_previous_hash
                        ):
                            raise ValueError(
                                "Previous hash mismatch "
                                f"at line {line_number}"
                            )

                        if not event.verify_hash():
                            raise ValueError(
                                "Event hash mismatch "
                                f"at line {line_number}"
                            )

                        expected_previous_hash = (
                            event.event_hash
                        )

                        last_event_id = (
                            event.event_id
                        )

                        last_event_hash = (
                            event.event_hash
                        )

                        events_verified += 1

                result = {
                    "valid": True,
                    "events_verified": (
                        events_verified
                    ),
                    "last_event_id": (
                        last_event_id
                    ),
                    "last_event_hash": (
                        last_event_hash
                    ),
                    "error": None,
                    "verified_at": (
                        self._utc_now()
                    ),
                }

                self.last_verification = result

                return dict(
                    result
                )

            except Exception as exc:
                self.stats[
                    "verification_failures"
                ] += 1

                self._record_error(
                    phase="verify_chain",
                    error=exc,
                )

                result = {
                    "valid": False,
                    "events_verified": (
                        events_verified
                    ),
                    "last_event_id": (
                        last_event_id
                    ),
                    "last_event_hash": (
                        last_event_hash
                    ),
                    "error": str(
                        exc
                    ),
                    "error_type": type(
                        exc
                    ).__name__,
                    "verified_at": (
                        self._utc_now()
                    ),
                }

                self.last_verification = result

                return dict(
                    result
                )

    # =========================================================
    # STATUS
    # =========================================================

    def status(
        self,
    ) -> dict[str, Any]:
        with self._lock:
            return {
                "name": self.NAME,
                "version": self.VERSION,
                "file_path": str(
                    self.file_path
                ),
                "loaded": self.loaded,
                "event_count": (
                    self.event_count
                ),
                "last_event_id": (
                    self.last_event_id
                ),
                "last_event_hash": (
                    self.last_event_hash
                ),
                "last_event_timestamp": (
                    self.last_event_timestamp
                ),
                "verify_on_load": (
                    self.verify_on_load
                ),
                "fsync_enabled": (
                    self.fsync_enabled
                ),
                "statistics": dict(
                    self.stats
                ),
            }

    def health(
        self,
    ) -> dict[str, Any]:
        with self._lock:
            verification_valid = (
                self.last_verification is None
                or self.last_verification.get(
                    "valid",
                    False,
                )
            )

            return {
                "healthy": (
                    self.loaded
                    and verification_valid
                    and self.stats[
                        "write_failures"
                    ]
                    == 0
                ),
                "loaded": self.loaded,
                "event_count": (
                    self.event_count
                ),
                "chain_valid": (
                    verification_valid
                ),
                "last_error": (
                    dict(
                        self.last_error
                    )
                    if self.last_error
                    else None
                ),
            }

    def diagnostics(
        self,
    ) -> dict[str, Any]:
        return {
            "status": self.status(),
            "health": self.health(),
            "verification": (
                dict(
                    self.last_verification
                )
                if self.last_verification
                else None
            ),
        }

    # =========================================================
    # ERROR MANAGEMENT
    # =========================================================

    def _record_error(
        self,
        *,
        phase: str,
        error: Exception,
    ) -> None:
        with self._lock:
            self.stats[
                "errors"
            ] += 1

            self.last_error = {
                "phase": phase,
                "error": str(
                    error
                ),
                "error_type": type(
                    error
                ).__name__,
                "timestamp": (
                    self._utc_now()
                ),
            }

    # =========================================================
    # TIME
    # =========================================================

    @staticmethod
    def _utc_now(
    ) -> str:
        return datetime.now(
            UTC
        ).isoformat()