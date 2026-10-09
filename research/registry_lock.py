"""An exclusive, portable write lock for one hypothesis registry file (Task 005 review F-1).

``HypothesisRegistry`` loads its file once and rewrites the whole file on every
write; it has no lock and does not re-read before writing. Two writers that
each hold an older copy therefore lose each other's records silently (a lost
REGISTERED -> CALIBRATED transition would even re-open a spent hypothesis). The
tools-side writers -- ``tools/strategy_compare.start_study_run`` and the Task 005
pipeline's registration -- take this lock and re-open the registry from disk
inside it, so every read-modify-write sees the latest file and the critical
section is milliseconds long.

The lock is a sidecar file created with O_CREAT | O_EXCL (works on POSIX and
Windows). A lock older than ``stale_after_s`` is never broken automatically:
the writer is refused and told to remove it after checking no writer runs
(fail closed). Direct calls to the registry API that bypass this lock (for
example an interactive ``advance``) are not guarded; that is a documented
residual. This module performs no I/O beyond the lock file and imports nothing
outside the standard library (ADR-0009).
"""

from __future__ import annotations

import os
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator


class RegistryLockError(OSError):
    """The registry is locked by another writer (timeout) or by a stale lock.

    An OSError: like any other I/O failure it is transient for the caller (a FAILED run that
    is retried), never a permanent refusal of the hypothesis.
    """


def lock_path(registry_path: str | Path) -> Path:
    path = Path(registry_path).resolve()  # one lock per file, however the path is spelled
    return path.with_name(path.name + ".lock")


@contextmanager
def registry_write_lock(registry_path: str | Path, *, timeout_s: float = 30.0, stale_after_s: float = 600.0,
                        poll_s: float = 0.05) -> Iterator[Path]:
    lock = lock_path(registry_path)
    lock.parent.mkdir(parents=True, exist_ok=True)
    deadline = time.monotonic() + timeout_s
    while True:
        try:
            fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            break
        except FileExistsError:
            try:
                age = time.time() - lock.stat().st_mtime
            except FileNotFoundError:
                continue  # released between the two calls: try again at once
            if age > stale_after_s:
                raise RegistryLockError(f"{lock} is {age:.0f} s old: a writer may have died holding it; remove it "
                                        f"only after checking that no registry writer is running") from None
            if time.monotonic() > deadline:
                raise RegistryLockError(f"{lock} is held by another writer; gave up after {timeout_s:.0f} s") from None
            time.sleep(poll_s)
    try:
        os.write(fd, f"{os.getpid()}\n".encode("ascii"))
        os.close(fd)
        yield lock
    finally:
        try:
            lock.unlink()
        except FileNotFoundError:
            pass
