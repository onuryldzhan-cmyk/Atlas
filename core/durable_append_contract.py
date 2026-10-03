"""
============================================================
ATLAS DURABLE APPEND CONTRACT v1 (Phase-2 A2)
============================================================

One shared physical-write contract for the hot-path append-only stores:
``AuditEventStore``, ``DurableAppendLog`` (and through it
``ExecutionTransactionJournal`` and ``ExecutionIdempotencyStore``).

Why this exists
---------------
Each store wrote ``write -> flush -> fsync`` and, on any exception, simply
did not advance its in-memory head. But a failed fsync, or a write that
raised after some bytes reached the file, may already have changed the
disk. The next append then reused the same sequence / previous_hash, or
glued a new record onto a torn tail.

Invariants
----------
I-A1  Indeterminate write. Every failed append is classified from the
      file's actual size: NOT_WRITTEN (the file is exactly at the last
      verified offset, either untouched or rolled back by a durable
      truncate) or INDETERMINATE (it is not, and could not be rolled back).
I-A2  Poisoned writer. After INDETERMINATE, or after detecting a foreign
      modification, the writer refuses every further write in this process.
I-A3  Disk is the source of truth. ``verified_size`` advances only after
      write+flush+fsync of the whole record succeeded; callers advance their
      own head only when ``append_bytes`` returns.
I-A4  No sequence/hash reuse: follows from I-A1..I-A3 - a record that may be
      on disk is never followed by a second record built on the same head.
I-A5  Restart integrity. An INDETERMINATE outcome leaves a best-effort
      ``<file>.recovery_required`` marker; ``check_recovery_marker`` makes
      every subsequent load fail closed until an operator acknowledges it.
I-A6  Tail validation. Before every append the file size must equal the
      last verified offset, so nothing is ever glued onto a torn or foreign
      tail.
I-A7  Concurrent writers. Appends hold an exclusive OS-level lock on
      ``<file>.lock`` (fcntl on POSIX, msvcrt on Windows) and re-check the
      size under it; a second process that appended in between is detected
      and fails closed (I-A2) rather than forking the chain.

What this does not do: replay, transition legality, and record semantics
stay in each store.
============================================================
"""

from __future__ import annotations

import contextlib
import json
import os
import threading

from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Iterator


NOT_WRITTEN = "NOT_WRITTEN"
INDETERMINATE = "INDETERMINATE"

RECOVERY_MARKER_SUFFIX = ".recovery_required"

# Binary append, unbuffered: os.write on this descriptor goes straight to the
# file (O_BINARY keeps Windows from translating newlines).
_APPEND_FLAGS = os.O_WRONLY | os.O_APPEND | os.O_CREAT | getattr(os, "O_BINARY", 0)
LOCK_SUFFIX = ".lock"


class DurableAppendError(RuntimeError):
    """An append did not durably complete. ``outcome`` classifies the disk."""

    outcome = NOT_WRITTEN


class DurableAppendNotWrittenError(DurableAppendError):
    """The file is verifiably at its pre-append size; nothing was stored."""

    outcome = NOT_WRITTEN


class DurableAppendIndeterminateError(DurableAppendError):
    """The record may or may not be on disk. The writer is now poisoned."""

    outcome = INDETERMINATE


class DurableWriterPoisonedError(DurableAppendError):
    """The writer refused an append because an earlier fault poisoned it."""

    outcome = NOT_WRITTEN


class DurableRecoveryRequiredError(RuntimeError):
    """A previous process left an unresolved INDETERMINATE write behind."""


# =========================================================
# OS-LEVEL FILE LOCK
# =========================================================

if os.name == "nt":  # pragma: no cover - exercised on Windows only
    import msvcrt

    def _lock_fd(fd: int) -> None:
        os.lseek(fd, 0, os.SEEK_SET)
        # LK_LOCK retries for ~10s and then raises, which fails the append
        # closed (NOT_WRITTEN) rather than writing without the lock.
        msvcrt.locking(fd, msvcrt.LK_LOCK, 1)

    def _unlock_fd(fd: int) -> None:
        os.lseek(fd, 0, os.SEEK_SET)
        msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)

else:
    import fcntl

    def _lock_fd(fd: int) -> None:
        fcntl.flock(fd, fcntl.LOCK_EX)

    def _unlock_fd(fd: int) -> None:
        fcntl.flock(fd, fcntl.LOCK_UN)


class DurableAppendWriter:
    """Physical append writer implementing invariants I-A1..I-A7."""

    def __init__(
        self,
        path: str | Path,
        *,
        fsync_enabled: bool = True,
    ) -> None:
        self.path = Path(path)
        self.fsync_enabled = bool(fsync_enabled)

        self._thread_lock = threading.RLock()

        # Byte offset of the end of the last verified record. ``None`` until
        # the owning store has read and validated the file.
        self.verified_size: int | None = None

        self.poisoned: dict[str, Any] | None = None

    # =========================================================
    # PATHS
    # =========================================================

    @property
    def marker_path(self) -> Path:
        return self.path.with_name(self.path.name + RECOVERY_MARKER_SUFFIX)

    @property
    def lock_path(self) -> Path:
        return self.path.with_name(self.path.name + LOCK_SUFFIX)

    # =========================================================
    # STATE
    # =========================================================

    def check_recovery_marker(self) -> None:
        """Fail closed if a previous INDETERMINATE write is unresolved."""

        if self.marker_path.exists():
            raise DurableRecoveryRequiredError(
                f"{self.path.name}: unresolved indeterminate write "
                f"(marker {self.marker_path.name}); operator recovery required - "
                "see docs/operations/DURABLE_APPEND_RECOVERY.md"
            )

    def establish(self, size: int) -> None:
        """Record the offset a validating read just verified."""

        with self._thread_lock:
            self.verified_size = int(size)

    def current_size(self) -> int:
        try:
            return self.path.stat().st_size
        except FileNotFoundError:
            return 0

    def status(self) -> dict[str, Any]:
        with self._thread_lock:
            return {
                "verified_size": self.verified_size,
                "poisoned": dict(self.poisoned) if self.poisoned else None,
                "recovery_marker": self.marker_path.exists(),
            }

    def acknowledge_recovery(self) -> None:
        """Operator-only: remove the marker after the file was inspected.

        Never called by runtime code. The next load re-validates the file
        from scratch, so acknowledging cannot make a corrupt file loadable.
        """

        with self._thread_lock:
            self.marker_path.unlink(missing_ok=True)
            self.poisoned = None
            self.verified_size = None

    # =========================================================
    # LOCKING
    # =========================================================

    @contextlib.contextmanager
    def exclusive(self) -> Iterator[None]:
        """Thread lock plus a cross-process lock on ``<file>.lock``."""

        with self._thread_lock:
            self.path.parent.mkdir(parents=True, exist_ok=True)

            fd = os.open(self.lock_path, os.O_RDWR | os.O_CREAT, 0o644)

            try:
                _lock_fd(fd)

                try:
                    yield
                finally:
                    _unlock_fd(fd)
            finally:
                os.close(fd)

    # =========================================================
    # APPEND
    # =========================================================

    def append_bytes(self, data: bytes) -> int:
        """Durably append ``data``; return the new verified size.

        Raises a ``DurableAppendError`` subclass on every failure; its
        ``outcome`` says whether the disk may hold the record.
        """

        with self.exclusive():
            self._require_writable()

            # Unbuffered OS-level descriptor (audit 2026-10-03 F1, HIGH): with a
            # buffered stream, close() re-flushed bytes left in the buffer
            # AFTER _resolve_failure had rolled the file back, so a failure
            # classified NOT_WRITTEN could still land a torn record on disk
            # and escape as a plain OSError. os.write leaves nothing behind.
            fd = os.open(self.path, _APPEND_FLAGS, 0o644)
            failure: BaseException | None = None

            try:
                size = os.fstat(fd).st_size

                if size != self.verified_size:
                    # I-A6/I-A7: torn or foreign tail. Never glue onto it.
                    self._poison(
                        "tail_mismatch",
                        f"file size {size} != verified {self.verified_size}",
                    )

                    raise DurableWriterPoisonedError(
                        f"{self.path.name}: file changed outside this writer "
                        f"(size {size}, verified {self.verified_size})"
                    )

                try:
                    view = memoryview(data)

                    while view:
                        written = os.write(fd, view)
                        view = view[written:]

                    if self.fsync_enabled:
                        os.fsync(fd)

                except BaseException as exc:
                    self._resolve_failure(fd, size, exc)
                    raise  # pragma: no cover - _resolve_failure always raises

            except BaseException as exc:
                failure = exc
                raise

            finally:
                try:
                    os.close(fd)
                except BaseException as close_exc:
                    # A close failure after a successful write+fsync leaves
                    # the outcome unknowable: poison and mark (I-A1/I-A5).
                    # If an earlier error is already propagating, that error
                    # (already classified) wins.
                    if failure is None:
                        self._poison("indeterminate_close", repr(close_exc))
                        self._write_marker(repr(close_exc))
                        raise DurableAppendIndeterminateError(
                            f"{self.path.name}: close after append failed: "
                            f"{close_exc!r}"
                        ) from close_exc

            self.verified_size = size + len(data)

            return self.verified_size

    def replace_atomically(self, data: bytes) -> int:
        """Compaction: write a temp file, fsync, ``os.replace``."""

        with self.exclusive():
            # A whole-file replace does not build on the old tail, so it
            # needs no verified offset - but a poisoned writer or an
            # unresolved marker still refuses it.
            self._require_writable(require_verified=False)

            temporary_path = self.path.with_name(self.path.name + ".tmp")

            try:
                with temporary_path.open("wb") as stream:
                    stream.write(data)
                    stream.flush()

                    if self.fsync_enabled:
                        os.fsync(stream.fileno())

                os.replace(temporary_path, self.path)

            except Exception:
                with contextlib.suppress(Exception):
                    temporary_path.unlink(missing_ok=True)

                raise

            self.verified_size = len(data)

            return self.verified_size

    # =========================================================
    # INTERNALS
    # =========================================================

    def _require_writable(self, *, require_verified: bool = True) -> None:
        if self.poisoned is not None:
            raise DurableWriterPoisonedError(
                f"{self.path.name}: writer poisoned by "
                f"{self.poisoned.get('reason')}; restart recovery required"
            )

        if require_verified and self.verified_size is None:
            raise DurableWriterPoisonedError(
                f"{self.path.name}: append before the log was verified"
            )

        self.check_recovery_marker()

    def _resolve_failure(
        self,
        fd: int,
        expected_size: int,
        exc: BaseException,
    ) -> None:
        """Classify a failed append (I-A1) and raise accordingly."""

        try:
            actual = os.fstat(fd).st_size
        except Exception:
            actual = None

        if actual == expected_size:
            raise DurableAppendNotWrittenError(
                f"{self.path.name}: append failed before any byte was "
                f"stored: {exc!r}"
            ) from exc

        # Bytes may have reached the file. Try a durable rollback to the
        # verified offset; only a successful truncate+fsync makes the
        # outcome NOT_WRITTEN again.
        try:
            os.ftruncate(fd, expected_size)

            if self.fsync_enabled:
                os.fsync(fd)

            if os.fstat(fd).st_size == expected_size:
                raise DurableAppendNotWrittenError(
                    f"{self.path.name}: append failed and was rolled back "
                    f"to the verified offset: {exc!r}"
                ) from exc

        except DurableAppendNotWrittenError:
            raise

        except Exception:
            pass

        self._poison("indeterminate_write", repr(exc))
        self._write_marker(repr(exc))

        raise DurableAppendIndeterminateError(
            f"{self.path.name}: append outcome is indeterminate: {exc!r}"
        ) from exc

    def _poison(self, reason: str, detail: str) -> None:
        self.poisoned = {
            "reason": reason,
            "detail": detail,
            "at": datetime.now(UTC).isoformat(),
        }

    def _write_marker(self, detail: str) -> None:
        # Best effort: the disk that just failed may refuse this too. The
        # in-process poison already blocks writes; the marker carries the
        # fact across a restart when the disk allows it.
        with contextlib.suppress(Exception):
            payload = json.dumps(
                {
                    "file": self.path.name,
                    "verified_size": self.verified_size,
                    "detail": detail,
                    "at": datetime.now(UTC).isoformat(),
                },
                sort_keys=True,
            )

            with self.marker_path.open("w", encoding="utf-8") as stream:
                stream.write(payload + "\n")
                stream.flush()
                os.fsync(stream.fileno())
