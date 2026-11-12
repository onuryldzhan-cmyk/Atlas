"""
============================================================
ATLAS DURABLE APPEND LOG v1
============================================================

Shared physical storage primitive for the append-only execution
authorities (Block 5K).

Why this exists
---------------
``ExecutionIdempotencyStore`` and ``ExecutionTransactionJournal`` both
persisted a single JSON object that was rewritten in full on every write, so
the cost of recording one terminal result grew with the whole history. Their
*logical* models differ - one holds at most one terminal record per
request_id, the other holds an ordered lifecycle event stream - but their
*physical* durability requirements are identical: framed JSON lines, an
O(1) durable append, deterministic ordering, torn-tail detection, and an
atomic full rewrite for the rare compaction paths.

Only that physical layer is shared here. Replay, transition legality, and
conflict semantics stay in each store, where they belong.

Format
------
A JSON-Lines file whose first line is a fixed header identifying the log and
its format version::

    {"log":"execution_idempotency","version":2}
    {"payload...":"...","sequence":0}
    {"payload...":"...","sequence":1}

``sequence`` is reserved by this module: it is stamped on append and
validated on read, so a log whose records are not the deterministic append
order 0, 1, 2, ... is corrupt rather than silently reordered.

This mirrors the existing Atlas JSON-Lines convention established by
``AppliedExecutionArchiveStore`` / ``ClosedPositionArchiveStore`` (Block 5I)
and ``ReservationArchiveStore`` (Block 5H): one canonical record per line,
written durably (write -> flush -> fsync) before the call returns.

Fail-closed reading
-------------------
Every deviation raises ``DurableAppendLogCorruptError``. Nothing is skipped,
repaired, reordered, or guessed:

- a missing or mismatched header
- a line that is not a JSON object
- a non-deterministic ``sequence``
- a torn tail (the file does not end with a newline)

The one tolerated repetition is a byte-identical repeat of the immediately
preceding record, which is the same defensive allowance
``AppliedExecutionArchiveStore`` makes against a storage layer duplicating a
line during a torn write. It cannot change the reconstructed state.

An absent or zero-byte file holds no records. A zero-byte file is what a
crash between file creation and the first write leaves behind, and "no
records" is exactly what that means.

============================================================
"""

from __future__ import annotations

import json

from pathlib import Path
from typing import Any, Mapping, Sequence

from core.durable_append_contract import (
    DurableAppendWriter,
    DurableRecoveryRequiredError,
)


SEQUENCE_FIELD = "sequence"

_HEADER_LOG_FIELD = "log"
_HEADER_VERSION_FIELD = "version"


class DurableAppendLogCorruptError(RuntimeError):
    """The durable log is malformed, torn, mis-versioned, or mis-ordered."""


class DurableAppendLogRecoveryRequiredError(
    DurableAppendLogCorruptError,
    DurableRecoveryRequiredError,
):
    """An earlier INDETERMINATE append left this log unresolved (A2 I-A5)."""


class DurableAppendLog:
    """Append-only JSON-Lines file with a versioned header.

    ``append`` is the only write on the hot path and its cost is independent
    of how many records the log already holds. ``rewrite`` exists for the
    rare compaction paths (reset, bounded test retention, operator
    migration) and is deliberately explicit rather than implicit.
    """

    def __init__(
        self,
        path: str | Path,
        *,
        log_name: str,
        version: int,
        json_default_str: bool = False,
    ) -> None:
        self.path = Path(path)
        self.log_name = str(log_name)
        self.version = int(version)

        # ``ExecutionTransactionJournal`` has always serialized with
        # ``default=str``; ``ExecutionIdempotencyStore`` has always been
        # strict, so an unserializable terminal result fails the write and
        # the record is rolled back. Both behaviours are preserved exactly.
        self._json_default = str if json_default_str else None

        # Lazily established from disk so a store constructed with
        # auto_load=False cannot append over existing sequences.
        self._next_sequence: int | None = None

        # Phase-2 A2: every physical write goes through the shared durable
        # append contract (tail validation, rollback-or-poison, OS lock).
        self._writer = DurableAppendWriter(self.path)

    # =========================================================
    # READ
    # =========================================================

    def exists(self) -> bool:
        return self.path.exists()

    def read(self) -> list[dict[str, Any]]:
        """Return every payload in append order, or raise on corruption."""

        try:
            self._writer.check_recovery_marker()
        except DurableRecoveryRequiredError as exc:
            raise DurableAppendLogRecoveryRequiredError(str(exc)) from exc

        if not self.path.exists():
            self._next_sequence = 0
            self._writer.establish(0)
            return []

        raw = self.path.read_bytes()

        if not raw:
            self._next_sequence = 0
            self._writer.establish(0)
            return []

        if not raw.endswith(b"\n"):
            raise DurableAppendLogCorruptError(
                f"{self.log_name}: torn tail (log does not end with a newline)"
            )

        try:
            text = raw.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise DurableAppendLogCorruptError(
                f"{self.log_name}: log is not valid UTF-8"
            ) from exc

        payloads: list[dict[str, Any]] = []
        previous_line: str | None = None
        header_seen = False
        expected_next = 0

        for line_number, raw_line in enumerate(text.splitlines(), start=1):
            line = raw_line.strip()

            if not line:
                continue

            try:
                record = json.loads(line)
            except Exception as exc:
                raise DurableAppendLogCorruptError(
                    f"{self.log_name}: malformed line {line_number}"
                ) from exc

            if not isinstance(record, dict):
                raise DurableAppendLogCorruptError(
                    f"{self.log_name}: line {line_number} is not an object"
                )

            if not header_seen:
                self._validate_header(record, line_number)
                header_seen = True
                previous_line = line
                continue

            sequence = record.get(SEQUENCE_FIELD)

            if not isinstance(sequence, int) or isinstance(sequence, bool):
                raise DurableAppendLogCorruptError(
                    f"{self.log_name}: line {line_number} has no integer sequence"
                )

            if sequence == expected_next:
                payload = dict(record)
                payload.pop(SEQUENCE_FIELD, None)
                payloads.append(payload)
                expected_next += 1

            elif (
                sequence == expected_next - 1
                and previous_line == line
            ):
                # Byte-identical repeat of the immediately preceding record.
                pass

            else:
                raise DurableAppendLogCorruptError(
                    f"{self.log_name}: non-deterministic sequence at "
                    f"line {line_number}"
                )

            previous_line = line

        if not header_seen:
            raise DurableAppendLogCorruptError(
                f"{self.log_name}: header line is missing"
            )

        self._next_sequence = expected_next
        self._writer.establish(len(raw))

        return payloads

    def _validate_header(
        self,
        record: Mapping[str, Any],
        line_number: int,
    ) -> None:
        if str(record.get(_HEADER_LOG_FIELD, "")) != self.log_name:
            raise DurableAppendLogCorruptError(
                f"{self.log_name}: line {line_number} is not this log's header"
            )

        if record.get(_HEADER_VERSION_FIELD) != self.version:
            raise DurableAppendLogCorruptError(
                f"{self.log_name}: unsupported log format version"
            )

    # =========================================================
    # WRITE
    # =========================================================

    def append(
        self,
        payloads: Sequence[Mapping[str, Any]],
    ) -> None:
        """Durably append payloads without rewriting anything already stored.

        Raises on any serialization or I/O failure so the caller can roll its
        in-memory state back; nothing is partially claimed as durable.
        """

        if not payloads:
            return

        self.path.parent.mkdir(
            parents=True,
            exist_ok=True,
        )

        next_sequence = self._resolve_next_sequence()

        lines: list[str] = []

        if next_sequence == 0 and not self._has_header():
            lines.append(
                self._encode(
                    {
                        _HEADER_LOG_FIELD: self.log_name,
                        _HEADER_VERSION_FIELD: self.version,
                    }
                )
            )

        for offset, payload in enumerate(payloads):
            lines.append(
                self._encode(
                    self._with_sequence(
                        payload,
                        next_sequence + offset,
                    )
                )
            )

        # Raises DurableAppendError (NOT_WRITTEN or INDETERMINATE); the
        # sequence advances only once the whole batch is verified on disk.
        self._writer.append_bytes(
            "".join(
                f"{line}\n" for line in lines
            ).encode("utf-8")
        )

        self._next_sequence = next_sequence + len(payloads)

    def rewrite(
        self,
        payloads: Sequence[Mapping[str, Any]],
    ) -> None:
        """Atomically replace the whole log, resequenced from zero.

        Reserved for compaction paths that are not on the execution hot path:
        bounded test retention, ``reset``, and operator migration. Written to
        a temporary file, fsynced, then ``os.replace``d, so a crash leaves
        either the old log or the new one.
        """

        self.path.parent.mkdir(
            parents=True,
            exist_ok=True,
        )

        lines = [
            self._encode(
                {
                    _HEADER_LOG_FIELD: self.log_name,
                    _HEADER_VERSION_FIELD: self.version,
                }
            )
        ]

        for sequence, payload in enumerate(payloads):
            lines.append(
                self._encode(
                    self._with_sequence(
                        payload,
                        sequence,
                    )
                )
            )

        self._writer.replace_atomically(
            "".join(
                f"{line}\n" for line in lines
            ).encode("utf-8")
        )

        self._next_sequence = len(payloads)

    # =========================================================
    # INTERNALS
    # =========================================================

    def _resolve_next_sequence(self) -> int:
        if self._next_sequence is None or self._writer.verified_size is None:
            # Never append blind: an unread log is counted first so a store
            # constructed with auto_load=False cannot reuse a sequence.
            self.read()

        return int(
            self._next_sequence or 0
        )

    def _has_header(self) -> bool:
        # The verified offset, not a fresh stat: a foreign or torn byte must
        # not suppress the header; the writer rejects such a tail anyway.
        return bool(self._writer.verified_size)

    def writer_status(self) -> dict[str, Any]:
        return self._writer.status()

    def _with_sequence(
        self,
        payload: Mapping[str, Any],
        sequence: int,
    ) -> dict[str, Any]:
        if SEQUENCE_FIELD in payload:
            raise ValueError(
                f"{SEQUENCE_FIELD} is reserved by DurableAppendLog"
            )

        record = dict(payload)
        record[SEQUENCE_FIELD] = int(sequence)

        return record

    def _encode(
        self,
        record: Mapping[str, Any],
    ) -> str:
        return json.dumps(
            record,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            default=self._json_default,
        )
