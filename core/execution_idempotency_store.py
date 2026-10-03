"""
============================================================
ATLAS EXECUTION IDEMPOTENCY STORE v2.0
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
- Append one durable terminal record per completed request
- Protect state with a reentrant lock
- Retain every completed request indefinitely in production; bounded
      retention is opt-in and reserved for explicit test callers
- Recover safely from invalid state files
- Expose health, status, diagnostics, and reset operations

Storage Model (Block 5K)
------------------------
An append-only JSON-Lines log (``DurableAppendLog``)::

    {"log":"execution_idempotency","version":2}
    {"request_id":"...","result":{...},"sequence":0}
    {"request_id":"...","result":{...},"sequence":1}

Recording one terminal result appends one line. Nothing already written is
rewritten, so the cost of completing a request no longer grows with the
number of requests completed before it. The in-memory
``completed_requests`` map is the same O(1) lookup index it has always been
and is rebuilt by replaying the log at startup.

Replay authority
----------------
Exactly one terminal record per request_id is the protocol. On read, a
repeated request_id is resolved as follows and never by picking a side:

- an identical payload is a harmless idempotent duplicate and is tolerated
- a differing payload is a conflicting terminal authority and fails closed

The same rule guards the write path: ``record()`` refuses to durably replace
a request_id's existing terminal result with a different one, so a
conflicting authority can never be created in the first place.

Legacy state (v1.0)
-------------------
The v1.0 store persisted one whole-file JSON object in
``execution_idempotency.json``. That file is never reinterpreted, migrated,
or read as authority by the runtime. If it is present and the v2 log is not,
the store reports ``migration_required`` and refuses to load, which fails
runtime startup closed. ``tools/migrate_execution_authority_logs.py`` is the
operator path.

Safety Principles
-----------------
- Pending requests are never persisted
- FAILED and ERROR results are never persisted
- Appends are flushed and fsynced before success is reported
- Compaction (reset, removal, bounded test retention) rewrites atomically
- Invalid files do not crash Atlas; they fail closed
- Runtime state remains serializable

============================================================
"""

from __future__ import annotations

import logging
import threading

from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Mapping

from atlas_security import sanitize_sensitive_data

from core.durable_append_log import (
    DurableAppendLog,
    DurableAppendLogCorruptError,
)


logger = logging.getLogger(
    "AtlasAI.ExecutionIdempotencyStore"
)


class ExecutionIdempotencyStore:
    """
    Persistent terminal-result registry indexed by request_id.
    """

    VERSION = "2.0"

    NAME = "ExecutionIdempotencyStore"

    LOG_NAME = "execution_idempotency"

    LOG_VERSION = 2

    DEFAULT_FILE = (
        "memory_data/execution_idempotency.jsonl"
    )

    # The v1.0 whole-file JSON object this store no longer writes. Its
    # presence beside an absent v2 log means operator migration is required.
    LEGACY_SUFFIX = ".json"

    # Production is unbounded: a COMMITTED request_id must remain replayable
    # indefinitely. Explicit positive values remain supported for tests that
    # need to exercise bounded retention; production wiring never sets one.
    DEFAULT_MAX_RECORDS = None

    FAILURE_STATUSES = {
        "FAILED",
        "ERROR",
    }

    def __init__(
        self,
        file_path: str | Path = DEFAULT_FILE,
        max_records: int | None = DEFAULT_MAX_RECORDS,
        auto_load: bool = True,
    ) -> None:
        self.file_path = Path(
            file_path
        )

        # None means unbounded (the production default). An explicit
        # positive integer still enables the bounded mode reserved for
        # tests; invalid explicit values normalize the same way this
        # already did before unbounded retention existed.
        self.max_records = (
            None
            if max_records is None
            else max(
                1,
                int(
                    max_records
                ),
            )
        )

        self._lock = threading.RLock()

        self._log = DurableAppendLog(
            self.file_path,
            log_name=self.LOG_NAME,
            version=self.LOG_VERSION,
        )

        self.completed_requests: dict[
            str,
            dict[str, Any],
        ] = {}

        # What the durable log is known to already hold. It is what makes an
        # append-only save() able to write only the new records, and what
        # lets a conflicting durable replacement be refused rather than
        # silently appended.
        self._durable_requests: dict[
            str,
            dict[str, Any],
        ] = {}

        self.loaded = False
        self.migration_required = False

        self.last_loaded_at: str | None = None
        self.last_saved_at: str | None = None
        self.last_error: dict[str, Any] | None = None

        self.stats: dict[str, int] = {
            "loads": 0,
            "saves": 0,
            "records_loaded": 0,
            "records_saved": 0,
            "records_appended": 0,
            "records_rewritten": 0,
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
    # LEGACY DETECTION
    # =========================================================

    @property
    def legacy_file_path(self) -> Path:
        """The v1.0 whole-file JSON path this store superseded."""

        return self.file_path.with_suffix(
            self.LEGACY_SUFFIX
        )

    def _legacy_state_present(self) -> bool:
        try:
            legacy_path = self.legacy_file_path
        except ValueError:
            return False

        if legacy_path == self.file_path:
            return False

        try:
            return legacy_path.is_file()
        except OSError:
            return False

    # =========================================================
    # LOAD
    # =========================================================

    def load(
        self,
    ) -> dict[str, dict[str, Any]]:
        """
        Load completed request results from the durable log.
        """

        with self._lock:
            self.stats["loads"] += 1

            self.migration_required = False

            if not self._log.exists():
                if self._legacy_state_present():
                    # A v1.0 authority is real history. Treating it as an
                    # empty v2 store would let every completed request
                    # execute again, so this fails closed and waits for the
                    # operator migration tool.
                    self.completed_requests = {}
                    self._durable_requests = {}
                    self.loaded = False
                    self.migration_required = True

                    logger.error(
                        "Execution idempotency legacy state requires "
                        "operator migration file=%s",
                        self.file_path,
                    )

                    return {}

                # Phase-2 A2: pin the verified (empty) offset now, so a later
                # foreign write is detected instead of being read lazily.
                try:
                    self._log.read()
                except Exception as exc:
                    self.completed_requests = {}
                    self._durable_requests = {}
                    self.loaded = False
                    self._record_error(phase="load", error=exc)
                    return {}

                self.completed_requests = {}
                self._durable_requests = {}
                self.loaded = True
                self.last_loaded_at = self._utc_now()

                return {}

            try:
                records = self._log.read()

                durable: dict[
                    str,
                    dict[str, Any],
                ] = {}

                for record in records:
                    request_id = str(
                        record.get(
                            "request_id",
                            "",
                        )
                    ).strip()

                    if not request_id:
                        raise DurableAppendLogCorruptError(
                            "terminal record has no request_id"
                        )

                    raw_result = record.get(
                        "result"
                    )

                    if not isinstance(
                        raw_result,
                        Mapping,
                    ):
                        raise DurableAppendLogCorruptError(
                            "terminal record has no result mapping"
                        )

                    result = self._safe_payload(
                        raw_result
                    )

                    if not isinstance(
                        result,
                        Mapping,
                    ):
                        raise DurableAppendLogCorruptError(
                            "terminal record result is not a mapping"
                        )

                    result = dict(
                        result
                    )

                    result.setdefault(
                        "request_id",
                        request_id,
                    )

                    if str(
                        result.get(
                            "status",
                            "UNKNOWN",
                        )
                    ).strip().upper() in self.FAILURE_STATUSES:
                        # record() refuses to persist a failure result, so
                        # one in the durable log is not this store's own
                        # output. It is never filtered away silently.
                        raise DurableAppendLogCorruptError(
                            "terminal record holds a failure status"
                        )

                    previous = durable.get(
                        request_id
                    )

                    if previous is not None and previous != result:
                        # Two durable terminal answers for one request. The
                        # replayed request has no single canonical result,
                        # so the whole authority fails closed rather than
                        # one of them being chosen.
                        raise DurableAppendLogCorruptError(
                            "conflicting terminal records for one request_id"
                        )

                    durable[
                        request_id
                    ] = result

                self._durable_requests = durable

                self.completed_requests = {
                    request_id: dict(
                        result
                    )
                    for request_id, result in durable.items()
                }

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
                self._durable_requests = {}
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
        Durably persist every in-memory record the log does not hold yet.

        The production path appends only the new terminal records, so its
        cost is independent of how much history the log already holds.
        Compaction - bounded test retention, or any removal - rewrites the
        whole log atomically instead, and is never on the execution path.
        """

        with self._lock:
            try:
                self._prune_locked()

                removed = (
                    set(
                        self._durable_requests
                    )
                    - set(
                        self.completed_requests
                    )
                )

                if self.max_records is not None or removed:
                    self._rewrite_locked()

                else:
                    pending: list[
                        tuple[str, dict[str, Any]]
                    ] = []

                    for request_id, result in (
                        self.completed_requests.items()
                    ):
                        durable = self._durable_requests.get(
                            request_id
                        )

                        if durable is None:
                            pending.append(
                                (
                                    request_id,
                                    result,
                                )
                            )

                        elif durable != result:
                            # A terminal result is permanent replay
                            # authority. Appending a second, different
                            # answer for the same request would leave the
                            # log with no canonical result at all.
                            logger.error(
                                "Refusing to durably replace an existing "
                                "terminal idempotency result"
                            )

                            raise ValueError(
                                "conflicting terminal result for an "
                                "already durable request_id"
                            )

                    if pending:
                        self._log.append(
                            [
                                {
                                    "request_id": request_id,
                                    "result": result,
                                }
                                for request_id, result in pending
                            ]
                        )

                        self.stats[
                            "records_appended"
                        ] += len(
                            pending
                        )

                    for request_id, result in pending:
                        self._durable_requests[
                            request_id
                        ] = dict(
                            result
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

    def _rewrite_locked(
        self,
    ) -> None:
        """Compact the log to exactly the current in-memory registry."""

        self._log.rewrite(
            [
                {
                    "request_id": request_id,
                    "result": result,
                }
                for request_id, result
                in self.completed_requests.items()
            ]
        )

        self._durable_requests = {
            request_id: dict(
                result
            )
            for request_id, result
            in self.completed_requests.items()
        }

        self.stats["records_rewritten"] += 1

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

        When durable persistence is requested, the in-memory registry is
        rolled back to exactly its prior state for this request_id if the
        durable append fails. A failed disk write must never leave a request
        marked as durably completed only in process memory.
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
            # Rollback is scoped to the one record this call touches. The
            # whole registry used to be deep-copied on every record(), which
            # made completing a request cost O(history) before a single byte
            # was written.
            existed = (
                canonical_id
                in self.completed_requests
            )

            previous_result = (
                dict(
                    self.completed_requests[
                        canonical_id
                    ]
                )
                if existed
                else None
            )

            previous_stats = {
                key: self.stats[key]
                for key in (
                    "records_added",
                    "records_replaced",
                    "records_pruned",
                )
            }

            # Bounded retention is a test-only mode in which this call may
            # additionally evict older records, so its rollback needs the
            # whole prior key set. Production (unbounded) never prunes and
            # pays nothing for it.
            previous_registry = (
                None
                if self.max_records is None
                else {
                    key: dict(
                        value
                    )
                    for key, value
                    in self.completed_requests.items()
                }
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

            if previous_registry is not None:
                self.completed_requests = previous_registry

            elif previous_result is None:
                self.completed_requests.pop(
                    canonical_id,
                    None,
                )

            else:
                self.completed_requests[
                    canonical_id
                ] = previous_result

            self.stats.update(
                previous_stats
            )

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

        Durable removal compacts the log; there is no tombstone record and
        no execution path that reaches this.
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

        Production leaves max_records unset (None) and never prunes, so
        every COMMITTED request_id stays replayable indefinitely. Bounded
        retention only applies when a caller (a test) passes an explicit
        max_records. Dictionary insertion order is used as the record order.
        """

        if self.max_records is None:
            return

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
                    # Re-review 2026-10-03 (LOW): never destroy a file an
                    # unresolved indeterminate write flagged for investigation.
                    self._log._writer.check_recovery_marker()

                    self.file_path.unlink(
                        missing_ok=True
                    )

                    # Audit 2026-10-03 F4: re-pin the writer at the now-empty
                    # file, or the next append would see a size mismatch and
                    # poison the store until restart.
                    self._log.read()

                    self._durable_requests = {}

                except Exception as exc:
                    self._record_error(
                        phase="reset_delete",
                        error=exc,
                    )

            else:
                try:
                    self._rewrite_locked()

                except Exception as exc:
                    self._record_error(
                        phase="reset",
                        error=exc,
                    )

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
                "migration_required": (
                    self.migration_required
                ),
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
                    and not self.migration_required
                ),
                "loaded": self.loaded,
                "migration_required": (
                    self.migration_required
                ),
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
            value,
            preserve_identifiers=True,
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
