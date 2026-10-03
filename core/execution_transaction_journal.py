"""
============================================================
ATLAS EXECUTION TRANSACTION JOURNAL v2.0
============================================================

Durable Execution Commit Journal

Lifecycle
---------
PREPARED
    |
    +--> COMMITTED          (terminal - permanent)
    |
    +--> NOT_COMMITTED      (retryable by design)
    |
    +--> COMMIT_STATUS_UNKNOWN

Storage Model (Block 5K)
------------------------
An append-only JSON-Lines event log (``DurableAppendLog``)::

    {"log":"execution_transaction_journal","version":2}
    {"request_id":"...","state":"PREPARED","entry":{...},"sequence":0}
    {"request_id":"...","state":"COMMITTED","entry":{...},"sequence":1}

Every lifecycle transition appends one event carrying the complete resulting
entry, so the durable cost of a transition no longer depends on how many
requests the journal already holds. The log's own ``sequence`` fixes the
order, the last event for a request_id is that request's current state, and
``entries`` - the in-memory map every reader already uses - is rebuilt by
replaying the log at startup. A restart therefore reconstructs exactly the
entry that was in memory when the last event was written.

Transition legality
-------------------
Legality is enforced on both sides: a refused write never reaches the log,
and a log holding an illegal transition fails closed on load rather than
being replayed into a state no writer could have produced.

- COMMITTED is terminal. It means a financial side effect actually happened
  and is durably recorded, so no later event may reopen it (``prepare``),
  downgrade it (``mark_not_committed`` / ``mark_unknown``), or overwrite its
  result. A repeated ``mark_committed`` carrying the identical result is
  answered as the no-op success it is; one carrying a different result is
  refused.
- NOT_COMMITTED is deliberately NOT terminal: it means the side-effect
  boundary was never crossed, and ``ExecutionManager``'s own contract is
  that such a request stays retryable, so a fresh ``prepare`` must succeed.
- COMMIT_STATUS_UNKNOWN is unresolved, not terminal, and stays re-preparable
  for recovery.

Legacy state (v1.0)
-------------------
The v1.0 journal persisted one whole-file JSON object in
``execution_transaction_journal.json``. It is never reinterpreted or
migrated by the runtime: if it is present while the v2 log is absent, the
journal reports ``migration_required``, fails to load, and startup halts.
``tools/migrate_execution_authority_logs.py`` is the operator path.

Safety
------
- PREPARED is persisted before financial side effects.
- Unknown outcomes remain unresolved.
- Appends are flushed and fsynced before success is reported.
- Compaction (reset only) rewrites atomically.
- Status exposes aggregate counts only.
- Request IDs and order payloads are never exposed by status().
============================================================
"""

from __future__ import annotations

import logging
import threading

from datetime import UTC, datetime
from enum import Enum
from pathlib import Path
from typing import Any, Mapping

from atlas_security import sanitize_sensitive_data

from core.durable_append_log import (
    DurableAppendLog,
    DurableAppendLogCorruptError,
)


logger = logging.getLogger(
    "AtlasAI.ExecutionTransactionJournal"
)


class CommitOutcome(str, Enum):
    COMMITTED = "COMMITTED"
    NOT_COMMITTED = "NOT_COMMITTED"
    COMMIT_STATUS_UNKNOWN = "COMMIT_STATUS_UNKNOWN"


PREPARED_STATE = "PREPARED"


class ExecutionTransactionJournal:
    VERSION = "2.0"

    NAME = "ExecutionTransactionJournal"

    LOG_NAME = "execution_transaction_journal"

    LOG_VERSION = 2

    DEFAULT_FILE = (
        "memory_data/execution_transaction_journal.jsonl"
    )

    # The v1.0 whole-file JSON object this journal no longer writes.
    LEGACY_SUFFIX = ".json"

    UNRESOLVED_STATES = {
        PREPARED_STATE,
        CommitOutcome.COMMIT_STATUS_UNKNOWN.value,
    }

    # COMMITTED means a financial side effect actually happened and is
    # durably recorded: prepare() must never reopen it, so a stale retry or
    # a duplicate claim that slips past idempotency-store detection can
    # never reset it back to PREPARED. NOT_COMMITTED is deliberately
    # excluded: it means the side-effect boundary was never crossed, and
    # ExecutionManager._resolve_unsuccessful_execution's own contract is
    # that such a request "stays retryable" - a fresh prepare() for the
    # same request_id must succeed again. COMMIT_STATUS_UNKNOWN is not
    # terminal at all (see UNRESOLVED_STATES) and was never at risk.
    TERMINAL_STATES = {
        CommitOutcome.COMMITTED.value,
    }

    LIFECYCLE_STATES = frozenset(
        (
            PREPARED_STATE,
            CommitOutcome.COMMITTED.value,
            CommitOutcome.NOT_COMMITTED.value,
            CommitOutcome.COMMIT_STATUS_UNKNOWN.value,
        )
    )

    # Which states each state may legally move to. ``None`` is "no entry
    # yet". COMMITTED accepts only COMMITTED, and the replay additionally
    # requires such an event to carry an identical entry, so a committed
    # outcome can never be rewritten by a later line.
    _LEGAL_TRANSITIONS: dict[str | None, frozenset[str]] = {
        None: LIFECYCLE_STATES,
        PREPARED_STATE: LIFECYCLE_STATES,
        CommitOutcome.NOT_COMMITTED.value: LIFECYCLE_STATES,
        CommitOutcome.COMMIT_STATUS_UNKNOWN.value: LIFECYCLE_STATES,
        CommitOutcome.COMMITTED.value: frozenset(
            (
                CommitOutcome.COMMITTED.value,
            )
        ),
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

        self._log = DurableAppendLog(
            self.file_path,
            log_name=self.LOG_NAME,
            version=self.LOG_VERSION,
            json_default_str=True,
        )

        self.entries: dict[
            str,
            dict[str, Any],
        ] = {}

        self.loaded = False
        self.load_failed = False
        self.migration_required = False

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
            "events_appended": 0,
            "errors": 0,
        }

        if auto_load:
            self.load()

    # =========================================================
    # LEGACY DETECTION
    # =========================================================

    @property
    def legacy_file_path(self) -> Path:
        """The v1.0 whole-file JSON path this journal superseded."""

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

    def load(self) -> bool:
        with self._lock:
            self.stats["loads"] += 1

            self.migration_required = False

            if not self._log.exists():
                if self._legacy_state_present():
                    # A v1.0 journal may hold an unresolved or COMMITTED
                    # entry. Reading it as an empty v2 journal would erase a
                    # live commit-outcome authority, so this fails closed.
                    self.entries = {}
                    self.loaded = False
                    self.load_failed = True
                    self.migration_required = True

                    logger.error(
                        "Execution transaction journal legacy state "
                        "requires operator migration file=%s",
                        self.file_path,
                    )

                    return False

                # Phase-2 A2: pin the verified (empty) offset now, so a later
                # foreign write is detected instead of being read lazily.
                try:
                    self._log.read()
                except Exception as exc:
                    self.entries = {}
                    self.loaded = False
                    self.load_failed = True
                    self._record_error(phase="load", error=exc)
                    return False

                self.entries = {}
                self.loaded = True
                self.load_failed = False
                self.last_loaded_at = self._utc_now()
                return True

            try:
                replayed: dict[
                    str,
                    dict[str, Any],
                ] = {}

                for event in self._log.read():
                    request_id = str(
                        event.get(
                            "request_id",
                            "",
                        )
                    ).strip()

                    if not request_id:
                        raise DurableAppendLogCorruptError(
                            "journal event has no request_id"
                        )

                    raw_entry = event.get(
                        "entry"
                    )

                    if not isinstance(
                        raw_entry,
                        Mapping,
                    ):
                        raise DurableAppendLogCorruptError(
                            "journal event has no entry mapping"
                        )

                    entry = sanitize_sensitive_data(
                        raw_entry,
                        preserve_identifiers=True,
                    )

                    if not isinstance(
                        entry,
                        Mapping,
                    ):
                        raise DurableAppendLogCorruptError(
                            "journal entry is not a mapping"
                        )

                    entry = dict(
                        entry
                    )

                    state = str(
                        event.get(
                            "state",
                            "",
                        )
                    ).strip().upper()

                    if state != str(
                        entry.get(
                            "state",
                            "",
                        )
                    ).strip().upper():
                        raise DurableAppendLogCorruptError(
                            "journal event state disagrees with its entry"
                        )

                    previous = replayed.get(
                        request_id
                    )

                    previous_state = (
                        None
                        if previous is None
                        else str(
                            previous.get(
                                "state",
                                "",
                            )
                        ).strip().upper()
                    )

                    self._require_legal_transition(
                        previous_state=previous_state,
                        next_state=state,
                        previous_entry=previous,
                        next_entry=entry,
                    )

                    replayed[
                        request_id
                    ] = entry

                self.entries = replayed
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

    @classmethod
    def _require_legal_transition(
        cls,
        *,
        previous_state: str | None,
        next_state: str,
        previous_entry: Mapping[str, Any] | None,
        next_entry: Mapping[str, Any],
    ) -> None:
        """Refuse any replayed transition no writer could legally produce."""

        allowed = cls._LEGAL_TRANSITIONS.get(
            previous_state
        )

        if allowed is None or next_state not in allowed:
            raise DurableAppendLogCorruptError(
                "illegal journal state transition"
            )

        if (
            previous_state == CommitOutcome.COMMITTED.value
            and previous_entry is not None
            and dict(
                previous_entry
            )
            != dict(
                next_entry
            )
        ):
            # COMMITTED to COMMITTED is only ever a repeat of the same
            # committed fact. A differing payload would be a rewrite of a
            # permanent authority.
            raise DurableAppendLogCorruptError(
                "committed journal entry was overwritten"
            )

    # =========================================================
    # APPEND
    # =========================================================

    def _append_event_locked(
        self,
        *,
        request_id: str,
        entry: Mapping[str, Any],
    ) -> bool:
        """Durably append one lifecycle event. Called with the lock held."""

        try:
            self._log.append(
                [
                    {
                        "request_id": request_id,
                        "state": str(
                            entry.get(
                                "state",
                                "",
                            )
                        ).strip().upper(),
                        "entry": dict(
                            entry
                        ),
                    }
                ]
            )

        except Exception as exc:
            self._record_error(
                phase="append",
                error=exc,
            )

            logger.exception(
                "Execution transaction journal append failed"
            )

            return False

        self.stats["saves"] += 1
        self.stats["events_appended"] += 1
        self.last_saved_at = self._utc_now()

        return True

    def save(self) -> bool:
        """Compact the log to exactly the current in-memory entry map.

        Lifecycle writes never call this - they append a single event - so
        it is off the execution path. It exists for callers that construct
        or adjust ``entries`` directly and then need one durable snapshot,
        and it rewrites atomically rather than appending, because a whole
        map is not a transition.
        """

        with self._lock:
            try:
                self._log.rewrite(
                    [
                        {
                            "request_id": request_id,
                            "state": str(
                                entry.get(
                                    "state",
                                    "",
                                )
                            ).strip().upper(),
                            "entry": dict(
                                entry
                            ),
                        }
                        for request_id, entry
                        in self.entries.items()
                    ]
                )

            except Exception as exc:
                self._record_error(
                    phase="save",
                    error=exc,
                )

                logger.exception(
                    "Execution transaction journal save failed"
                )

                return False

            self.stats["saves"] += 1
            self.last_saved_at = self._utc_now()

            return True

    def _current_state_locked(
        self,
        request_id: str,
    ) -> str | None:
        existing = self.entries.get(
            request_id
        )

        if not isinstance(
            existing,
            Mapping,
        ):
            return None

        return str(
            existing.get(
                "state",
                "",
            )
        ).strip().upper()

    def _commit_locked(
        self,
        *,
        request_id: str,
        entry: dict[str, Any],
    ) -> bool:
        """Install one entry in memory, rolling back if the append fails."""

        existed = request_id in self.entries

        previous_entry = (
            dict(
                self.entries[
                    request_id
                ]
            )
            if existed
            else None
        )

        self.entries[
            request_id
        ] = entry

        if self._append_event_locked(
            request_id=request_id,
            entry=entry,
        ):
            return True

        if previous_entry is None:
            self.entries.pop(
                request_id,
                None,
            )
        else:
            self.entries[
                request_id
            ] = previous_entry

        return False

    # =========================================================
    # LIFECYCLE WRITES
    # =========================================================

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
            request_payload,
            preserve_identifiers=True,
        )

        if not isinstance(
            sanitized_payload,
            Mapping,
        ):
            return False

        with self._lock:
            if (
                self._current_state_locked(
                    canonical_id
                )
                in self.TERMINAL_STATES
            ):
                logger.warning(
                    "Refusing to reopen terminal transaction "
                    "journal entry request_id=%s",
                    canonical_id,
                )

                return False

            entry = {
                "state": PREPARED_STATE,
                "prepared_at": self._utc_now(),
                "request": dict(
                    sanitized_payload
                ),
            }

            if self._commit_locked(
                request_id=canonical_id,
                entry=entry,
            ):
                self.stats["prepared"] += 1
                return True

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
            if not self._may_transition_locked(
                request_id=canonical_id,
                next_state=(
                    CommitOutcome
                    .COMMIT_STATUS_UNKNOWN
                    .value
                ),
            ):
                return False

            entry = dict(
                self.entries.get(
                    canonical_id,
                    {},
                )
            )

            entry.update(
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
                entry["result"] = (
                    sanitize_sensitive_data(
                        result,
                        preserve_identifiers=True,
                    )
                )

            if self._commit_locked(
                request_id=canonical_id,
                entry=entry,
            ):
                self.stats["unknown"] += 1
                return True

            return False

    def _may_transition_locked(
        self,
        *,
        request_id: str,
        next_state: str,
    ) -> bool:
        """Whether a write may move this request to ``next_state``."""

        current = self._current_state_locked(
            request_id
        )

        allowed = self._LEGAL_TRANSITIONS.get(
            current
        )

        if allowed is not None and next_state in allowed:
            return True

        logger.warning(
            "Refusing illegal transaction journal transition "
            "request_id=%s to=%s",
            request_id,
            next_state,
        )

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
            if not self._may_transition_locked(
                request_id=canonical_id,
                next_state=outcome.value,
            ):
                return False

            entry = dict(
                self.entries.get(
                    canonical_id,
                    {},
                )
            )

            already_committed = (
                str(
                    entry.get(
                        "state",
                        "",
                    )
                ).strip().upper()
                == CommitOutcome.COMMITTED.value
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
                        result,
                        preserve_identifiers=True,
                    )
                )

            if already_committed:
                # The only transition out of COMMITTED is COMMITTED itself,
                # and only as a repeat of the same committed fact. The fresh
                # updated_at stamp is ignored for that comparison: it is
                # provenance, not commit evidence.
                stored = dict(
                    self.entries[
                        canonical_id
                    ]
                )

                if {
                    key: value
                    for key, value in entry.items()
                    if key != "updated_at"
                } != {
                    key: value
                    for key, value in stored.items()
                    if key != "updated_at"
                }:
                    logger.warning(
                        "Refusing to overwrite a committed transaction "
                        "journal entry request_id=%s",
                        canonical_id,
                    )

                    return False

                # Nothing new to record; the committed fact already stands.
                return True

            if self._commit_locked(
                request_id=canonical_id,
                entry=entry,
            ):
                if outcome is CommitOutcome.COMMITTED:
                    self.stats["committed"] += 1
                else:
                    self.stats["not_committed"] += 1

                return True

            return False

    # =========================================================
    # QUERY
    # =========================================================

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
                "migration_required": (
                    self.migration_required
                ),
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

    # =========================================================
    # RESET
    # =========================================================

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

            try:
                self._log.rewrite(
                    []
                )

                self.last_saved_at = self._utc_now()
                self.stats["saves"] += 1

                return True

            except Exception as exc:
                self.entries = previous_entries

                self._record_error(
                    phase="reset",
                    error=exc,
                )

                logger.exception(
                    "Execution transaction journal reset failed"
                )

                return False

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
