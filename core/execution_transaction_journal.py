"""
============================================================
ATLAS EXECUTION TRANSACTION JOURNAL v1.0
============================================================

Durable Execution Commit Journal

Lifecycle
---------
PREPARED
    |
    +--> COMMITTED
    |
    +--> NOT_COMMITTED
    |
    +--> COMMIT_STATUS_UNKNOWN

Safety
------
- PREPARED is persisted before financial side effects.
- Unknown outcomes remain unresolved.
- Writes use temporary-file replacement.
- Status exposes aggregate counts only.
- Request IDs and order payloads are never exposed by status().
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
    "AtlasAI.ExecutionTransactionJournal"
)


class CommitOutcome(str, Enum):
    COMMITTED = "COMMITTED"
    NOT_COMMITTED = "NOT_COMMITTED"
    COMMIT_STATUS_UNKNOWN = "COMMIT_STATUS_UNKNOWN"


class ExecutionTransactionJournal:
    VERSION = "1.0"

    NAME = "ExecutionTransactionJournal"

    DEFAULT_FILE = (
        "memory_data/execution_transaction_journal.json"
    )

    UNRESOLVED_STATES = {
        "PREPARED",
        CommitOutcome.COMMIT_STATUS_UNKNOWN.value,
    }

    def __init__(
        self,
        file_path: str | Path = DEFAULT_FILE,
        *,
        auto_load: bool = True,
    ) -> None:
        self.file_path = Path(
            file_path
        )

        self._lock = threading.RLock()

        self.entries: dict[
            str,
            dict[str, Any],
        ] = {}

        self.loaded = False
        self.load_failed = False

        self.last_loaded_at: str | None = None
        self.last_saved_at: str | None = None
        self.last_error: dict[str, Any] | None = None

        self.stats: dict[str, int] = {
            "loads": 0,
            "saves": 0,
            "prepared": 0,
            "committed": 0,
            "not_committed": 0,
            "unknown": 0,
            "errors": 0,
        }

        if auto_load:
            self.load()

    def load(self) -> bool:
        with self._lock:
            self.stats["loads"] += 1

            if not self.file_path.exists():
                self.entries = {}
                self.loaded = True
                self.load_failed = False
                self.last_loaded_at = self._utc_now()
                return True

            try:
                with self.file_path.open(
                    "r",
                    encoding="utf-8",
                ) as stream:
                    payload = json.load(
                        stream
                    )

                raw_entries = payload.get(
                    "entries",
                    {},
                )

                if not isinstance(
                    raw_entries,
                    Mapping,
                ):
                    raise ValueError(
                        "entries must be a mapping"
                    )

                normalized: dict[
                    str,
                    dict[str, Any],
                ] = {}

                for raw_request_id, raw_entry in (
                    raw_entries.items()
                ):
                    request_id = str(
                        raw_request_id
                    ).strip()

                    if (
                        not request_id
                        or not isinstance(
                            raw_entry,
                            Mapping,
                        )
                    ):
                        continue

                    entry = sanitize_sensitive_data(
                        raw_entry
                    )

                    if not isinstance(
                        entry,
                        Mapping,
                    ):
                        continue

                    normalized[
                        request_id
                    ] = dict(
                        entry
                    )

                self.entries = normalized
                self.loaded = True
                self.load_failed = False
                self.last_loaded_at = self._utc_now()

                return True

            except Exception as exc:
                self.entries = {}
                self.loaded = False
                self.load_failed = True

                self._record_error(
                    phase="load",
                    error=exc,
                )

                logger.exception(
                    "Execution transaction journal load failed"
                )

                return False

    def save(self) -> bool:
        with self._lock:
            temporary_path = self.file_path.with_suffix(
                self.file_path.suffix + ".tmp"
            )

            try:
                self.file_path.parent.mkdir(
                    parents=True,
                    exist_ok=True,
                )

                payload = {
                    "version": self.VERSION,
                    "updated_at": self._utc_now(),
                    "entries": self.entries,
                }

                with temporary_path.open(
                    "w",
                    encoding="utf-8",
                    newline="\n",
                ) as stream:
                    json.dump(
                        payload,
                        stream,
                        ensure_ascii=False,
                        indent=2,
                        sort_keys=True,
                        default=str,
                    )

                    stream.flush()

                    os.fsync(
                        stream.fileno()
                    )

                os.replace(
                    temporary_path,
                    self.file_path,
                )

                self.stats["saves"] += 1
                self.last_saved_at = self._utc_now()

                return True

            except Exception as exc:
                try:
                    temporary_path.unlink(
                        missing_ok=True
                    )

                except Exception:
                    pass

                self._record_error(
                    phase="save",
                    error=exc,
                )

                logger.exception(
                    "Execution transaction journal save failed"
                )

                return False

    def prepare(
        self,
        request_id: str,
        request_payload: Mapping[str, Any],
    ) -> bool:
        canonical_id = str(
            request_id
        ).strip()

        if (
            not canonical_id
            or not isinstance(
                request_payload,
                Mapping,
            )
        ):
            return False

        sanitized_payload = sanitize_sensitive_data(
            request_payload
        )

        if not isinstance(
            sanitized_payload,
            Mapping,
        ):
            return False

        with self._lock:
            previous_entries = {
                key: dict(
                    value
                )
                for key, value in self.entries.items()
            }

            self.entries[
                canonical_id
            ] = {
                "state": "PREPARED",
                "prepared_at": self._utc_now(),
                "request": dict(
                    sanitized_payload
                ),
            }

            if self.save():
                self.stats["prepared"] += 1
                return True

            self.entries = previous_entries
            return False

    def mark_committed(
        self,
        request_id: str,
        result: Mapping[str, Any],
    ) -> bool:
        return self._mark_terminal(
            request_id=request_id,
            outcome=CommitOutcome.COMMITTED,
            result=result,
        )

    def mark_not_committed(
        self,
        request_id: str,
        *,
        reason: str,
        result: Mapping[str, Any] | None = None,
    ) -> bool:
        return self._mark_terminal(
            request_id=request_id,
            outcome=CommitOutcome.NOT_COMMITTED,
            result=result,
            reason=reason,
        )

    def mark_unknown(
        self,
        request_id: str,
        *,
        reason: str,
        result: Mapping[str, Any] | None = None,
    ) -> bool:
        canonical_id = str(
            request_id
        ).strip()

        if not canonical_id:
            return False

        with self._lock:
            previous_entries = {
                key: dict(
                    value
                )
                for key, value in self.entries.items()
            }

            previous = dict(
                self.entries.get(
                    canonical_id,
                    {},
                )
            )

            previous.update(
                {
                    "state": (
                        CommitOutcome
                        .COMMIT_STATUS_UNKNOWN
                        .value
                    ),
                    "reason": str(
                        reason
                    ),
                    "updated_at": self._utc_now(),
                }
            )

            if result is not None:
                previous["result"] = (
                    sanitize_sensitive_data(
                        result
                    )
                )

            self.entries[
                canonical_id
            ] = previous

            if self.save():
                self.stats["unknown"] += 1
                return True

            self.entries = previous_entries
            return False

    def _mark_terminal(
        self,
        *,
        request_id: str,
        outcome: CommitOutcome,
        result: Mapping[str, Any] | None,
        reason: str | None = None,
    ) -> bool:
        canonical_id = str(
            request_id
        ).strip()

        if not canonical_id:
            return False

        with self._lock:
            previous_entries = {
                key: dict(
                    value
                )
                for key, value in self.entries.items()
            }

            entry = dict(
                self.entries.get(
                    canonical_id,
                    {},
                )
            )

            entry.update(
                {
                    "state": outcome.value,
                    "updated_at": self._utc_now(),
                }
            )

            if reason is not None:
                entry["reason"] = str(
                    reason
                )

            if result is not None:
                entry["result"] = (
                    sanitize_sensitive_data(
                        result
                    )
                )

            self.entries[
                canonical_id
            ] = entry

            if self.save():
                if outcome is CommitOutcome.COMMITTED:
                    self.stats["committed"] += 1
                else:
                    self.stats["not_committed"] += 1

                return True

            self.entries = previous_entries
            return False

    def has_unresolved(self) -> bool:
        with self._lock:
            if self.load_failed:
                return True

            return any(
                str(
                    entry.get(
                        "state",
                        "",
                    )
                ).upper()
                in self.UNRESOLVED_STATES
                for entry in self.entries.values()
            )

    def status(self) -> dict[str, Any]:
        with self._lock:
            state_counts: dict[str, int] = {}

            for entry in self.entries.values():
                state = str(
                    entry.get(
                        "state",
                        "UNKNOWN",
                    )
                ).upper()

                state_counts[state] = (
                    state_counts.get(
                        state,
                        0,
                    )
                    + 1
                )

            unresolved_entries = sum(
                state_counts.get(
                    state,
                    0,
                )
                for state in self.UNRESOLVED_STATES
            )

            return {
                "name": self.NAME,
                "version": self.VERSION,
                "loaded": self.loaded,
                "load_failed": self.load_failed,
                "entries": len(
                    self.entries
                ),
                "unresolved_entries": (
                    unresolved_entries
                ),
                "state_counts": state_counts,
                "last_loaded_at": self.last_loaded_at,
                "last_saved_at": self.last_saved_at,
                "statistics": dict(
                    self.stats
                ),
            }

    def reset(
        self,
        *,
        delete_file: bool = False,
    ) -> bool:
        with self._lock:
            previous_entries = {
                key: dict(
                    value
                )
                for key, value in self.entries.items()
            }

            self.entries.clear()

            if delete_file:
                try:
                    self.file_path.unlink(
                        missing_ok=True
                    )

                    return True

                except Exception as exc:
                    self.entries = previous_entries

                    self._record_error(
                        phase="reset",
                        error=exc,
                    )

                    return False

            if self.save():
                return True

            self.entries = previous_entries
            return False

    def _record_error(
        self,
        *,
        phase: str,
        error: Exception,
    ) -> None:
        self.stats["errors"] += 1

        self.last_error = {
            "phase": phase,
            "error_type": type(
                error
            ).__name__,
            "timestamp": self._utc_now(),
        }

    @staticmethod
    def _utc_now() -> str:
        return datetime.now(
            UTC
        ).isoformat()
