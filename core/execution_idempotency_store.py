"""
============================================================
ATLAS EXECUTION IDEMPOTENCY STORE v1.0
============================================================

Restart-Safe Execution Request Registry

Purpose
-------
Persist terminal execution request results so Atlas can detect
duplicate execution requests after a process restart.

Responsibilities
----------------
- Persist completed request IDs
- Restore completed execution results
- Perform atomic JSON writes
- Protect state with a reentrant lock
- Maintain bounded storage
- Recover safely from invalid state files
- Expose health, status, diagnostics, and reset operations

Storage Model
-------------
{
    "version": "1.0",
    "updated_at": "...",
    "completed_requests": {
        "<request_id>": {
            "status": "PAPER_EXECUTED",
            ...
        }
    }
}

Safety Principles
-----------------
- Pending requests are never persisted
- FAILED and ERROR results are never persisted
- Writes use temporary-file replacement
- Invalid files do not crash Atlas
- Runtime state remains serializable

============================================================
"""

from __future__ import annotations

import json
import logging
import os
import threading

from datetime import UTC, datetime
from enum import Enum
from pathlib import Path
from typing import Any, Mapping

from atlas_security import sanitize_sensitive_data


logger = logging.getLogger(
    "AtlasAI.ExecutionIdempotencyStore"
)


class ExecutionIdempotencyStore:
    """
    Persistent terminal-result registry indexed by request_id.
    """

    VERSION = "1.0"

    NAME = "ExecutionIdempotencyStore"

    DEFAULT_FILE = (
        "memory_data/execution_idempotency.json"
    )

    DEFAULT_MAX_RECORDS = 5_000

    FAILURE_STATUSES = {
        "FAILED",
        "ERROR",
    }

    def __init__(
        self,
        file_path: str | Path = DEFAULT_FILE,
        max_records: int = DEFAULT_MAX_RECORDS,
        auto_load: bool = True,
    ) -> None:
        self.file_path = Path(
            file_path
        )

        self.max_records = max(
            1,
            int(
                max_records
            ),
        )

        self._lock = threading.RLock()

        self.completed_requests: dict[
            str,
            dict[str, Any],
        ] = {}

        self.loaded = False

        self.last_loaded_at: str | None = None
        self.last_saved_at: str | None = None
        self.last_error: dict[str, Any] | None = None

        self.stats: dict[str, int] = {
            "loads": 0,
            "saves": 0,
            "records_loaded": 0,
            "records_saved": 0,
            "cache_hits": 0,
            "cache_misses": 0,
            "records_added": 0,
            "records_replaced": 0,
            "records_pruned": 0,
            "errors": 0,
        }

        if auto_load:
            self.load()

        logger.info(
            "%s v%s initialized file=%s records=%s",
            self.NAME,
            self.VERSION,
            self.file_path,
            len(
                self.completed_requests
            ),
        )

    # =========================================================
    # LOAD
    # =========================================================

    def load(
        self,
    ) -> dict[str, dict[str, Any]]:
        """
        Load completed request results from disk.
        """

        with self._lock:
            self.stats["loads"] += 1

            if not self.file_path.exists():
                self.completed_requests = {}
                self.loaded = True
                self.last_loaded_at = self._utc_now()

                return {}

            try:
                with self.file_path.open(
                    "r",
                    encoding="utf-8",
                ) as file:
                    payload = json.load(
                        file
                    )

                raw_records = payload.get(
                    "completed_requests",
                    {},
                )

                if not isinstance(
                    raw_records,
                    Mapping,
                ):
                    raise ValueError(
                        "completed_requests must be a mapping"
                    )

                normalized: dict[
                    str,
                    dict[str, Any],
                ] = {}

                for raw_request_id, raw_result in (
                    raw_records.items()
                ):
                    request_id = str(
                        raw_request_id
                    ).strip()

                    if not request_id:
                        continue

                    if not isinstance(
                        raw_result,
                        Mapping,
                    ):
                        continue

                    result = self._safe_payload(
                        raw_result
                    )

                    status = str(
                        result.get(
                            "status",
                            "UNKNOWN",
                        )
                    ).strip().upper()

                    if status in self.FAILURE_STATUSES:
                        continue

                    result.setdefault(
                        "request_id",
                        request_id,
                    )

                    normalized[
                        request_id
                    ] = result

                self.completed_requests = normalized

                self._prune_locked()

                self.loaded = True
                self.last_loaded_at = self._utc_now()

                self.stats[
                    "records_loaded"
                ] += len(
                    self.completed_requests
                )

                logger.info(
                    "Execution idempotency state loaded "
                    "records=%s file=%s",
                    len(
                        self.completed_requests
                    ),
                    self.file_path,
                )

                return {
                    request_id: dict(
                        result
                    )
                    for request_id, result
                    in self.completed_requests.items()
                }

            except Exception as exc:
                self.completed_requests = {}
                self.loaded = False

                self._record_error(
                    phase="load",
                    error=exc,
                )

                logger.exception(
                    "Execution idempotency state load failed"
                )

                return {}

    # =========================================================
    # SAVE
    # =========================================================

    def save(
        self,
    ) -> bool:
        """
        Atomically persist all completed request results.
        """

        with self._lock:
            try:
                self.file_path.parent.mkdir(
                    parents=True,
                    exist_ok=True,
                )

                self._prune_locked()

                payload = {
                    "version": self.VERSION,
                    "updated_at": self._utc_now(),
                    "completed_requests": (
                        self.completed_requests
                    ),
                }

                temporary_path = self.file_path.with_suffix(
                    self.file_path.suffix + ".tmp"
                )

                with temporary_path.open(
                    "w",
                    encoding="utf-8",
                ) as file:
                    json.dump(
                        payload,
                        file,
                        ensure_ascii=False,
                        indent=2,
                        sort_keys=True,
                    )

                    file.flush()

                    os.fsync(
                        file.fileno()
                    )

                os.replace(
                    temporary_path,
                    self.file_path,
                )

                self.last_saved_at = self._utc_now()

                self.stats["saves"] += 1
                self.stats[
                    "records_saved"
                ] += len(
                    self.completed_requests
                )

                return True

            except Exception as exc:
                self._record_error(
                    phase="save",
                    error=exc,
                )

                logger.exception(
                    "Execution idempotency state save failed"
                )

                return False

    # =========================================================
    # LOOKUP
    # =========================================================

    def get(
        self,
        request_id: str,
    ) -> dict[str, Any] | None:
        """
        Return one cached terminal result.
        """

        canonical_id = str(
            request_id
        ).strip()

        if not canonical_id:
            return None

        with self._lock:
            result = self.completed_requests.get(
                canonical_id
            )

            if result is None:
                self.stats["cache_misses"] += 1
                return None

            self.stats["cache_hits"] += 1

            return dict(
                result
            )

    def contains(
        self,
        request_id: str,
    ) -> bool:
        """
        Return whether request_id has a terminal result.
        """

        canonical_id = str(
            request_id
        ).strip()

        if not canonical_id:
            return False

        with self._lock:
            return (
                canonical_id
                in self.completed_requests
            )

    # =========================================================
    # RECORD
    # =========================================================

    def record(
        self,
        request_id: str,
        result: Mapping[str, Any],
        *,
        save: bool = True,
    ) -> bool:
        """
        Store a terminal non-failure result.

        When durable persistence is requested, the in-memory registry
        is rolled back completely if saving fails. A failed disk write
        must never leave a request marked as durably completed only in
        process memory.
        """

        canonical_id = str(
            request_id
        ).strip()

        if not canonical_id:
            return False

        if not isinstance(
            result,
            Mapping,
        ):
            return False

        normalized = self._safe_payload(
            result
        )

        if not isinstance(
            normalized,
            Mapping,
        ):
            return False

        normalized = dict(
            normalized
        )

        status = str(
            normalized.get(
                "status",
                "UNKNOWN",
            )
        ).strip().upper()

        if status in self.FAILURE_STATUSES:
            return False

        normalized.setdefault(
            "request_id",
            canonical_id,
        )

        normalized.setdefault(
            "idempotency_recorded_at",
            self._utc_now(),
        )

        with self._lock:
            previous_records = {
                stored_request_id: dict(
                    stored_result
                )
                for stored_request_id, stored_result
                in self.completed_requests.items()
            }

            previous_records_added = self.stats[
                "records_added"
            ]

            previous_records_replaced = self.stats[
                "records_replaced"
            ]

            previous_records_pruned = self.stats[
                "records_pruned"
            ]

            existed = (
                canonical_id
                in self.completed_requests
            )

            self.completed_requests[
                canonical_id
            ] = normalized

            if existed:
                self.stats[
                    "records_replaced"
                ] += 1
            else:
                self.stats[
                    "records_added"
                ] += 1

            self._prune_locked()

            if not save:
                return True

            persisted = self.save()

            if persisted:
                return True

            self.completed_requests = previous_records

            self.stats[
                "records_added"
            ] = previous_records_added

            self.stats[
                "records_replaced"
            ] = previous_records_replaced

            self.stats[
                "records_pruned"
            ] = previous_records_pruned

            logger.error(
                "Execution idempotency record rolled back "
                "after persistence failure"
            )

            return False

    def remove(
        self,
        request_id: str,
        *,
        save: bool = True,
    ) -> bool:
        """
        Remove one request result.
        """

        canonical_id = str(
            request_id
        ).strip()

        if not canonical_id:
            return False

        with self._lock:
            existed = self.completed_requests.pop(
                canonical_id,
                None,
            )

        if existed is None:
            return False

        if save:
            return self.save()

        return True

    # =========================================================
    # PRUNING
    # =========================================================

    def _prune_locked(
        self,
    ) -> None:
        """
        Retain only the newest bounded request records.

        Dictionary insertion order is used as the record order.
        """

        excess = (
            len(
                self.completed_requests
            )
            - self.max_records
        )

        if excess <= 0:
            return

        request_ids = list(
            self.completed_requests
        )

        for request_id in request_ids[
            :excess
        ]:
            self.completed_requests.pop(
                request_id,
                None,
            )

            self.stats[
                "records_pruned"
            ] += 1

    # =========================================================
    # RESET
    # =========================================================

    def reset(
        self,
        *,
        delete_file: bool = False,
    ) -> None:
        """
        Clear persistent idempotency state.
        """

        with self._lock:
            self.completed_requests.clear()

            if delete_file:
                try:
                    self.file_path.unlink(
                        missing_ok=True
                    )

                except Exception as exc:
                    self._record_error(
                        phase="reset_delete",
                        error=exc,
                    )

            else:
                self.save()

        logger.info(
            "Execution idempotency store reset"
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
                "records": len(
                    self.completed_requests
                ),
                "max_records": self.max_records,
                "last_loaded_at": self.last_loaded_at,
                "last_saved_at": self.last_saved_at,
                "statistics": dict(
                    self.stats
                ),
            }

    def health(
        self,
    ) -> dict[str, Any]:
        with self._lock:
            return {
                "healthy": (
                    self.last_error is None
                ),
                "loaded": self.loaded,
                "file_path": str(
                    self.file_path
                ),
                "records": len(
                    self.completed_requests
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
        with self._lock:
            return {
                "status": self.status(),
                "health": self.health(),
                "request_ids": list(
                    self.completed_requests
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
        self.stats["errors"] += 1

        self.last_error = {
            "phase": phase,
            "error": str(
                error
            ),
            "error_type": type(
                error
            ).__name__,
            "timestamp": self._utc_now(),
        }

    # =========================================================
    # SERIALIZATION
    # =========================================================

    @classmethod
    def _safe_payload(
        cls,
        value: Any,
    ) -> Any:
        return sanitize_sensitive_data(
            value
        )

    # =========================================================
    # TIME
    # =========================================================

    @staticmethod
    def _utc_now(
    ) -> str:
        return datetime.now(
            UTC
        ).isoformat()
