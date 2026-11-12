"""One Atlas process per durable state root.

Two processes appending to one state root fork the audit chain (2026-09-28
incident, registry v5.05). Every holder of a state root - main.AtlasProcess
and AtlasApplication itself - takes this lock first, so a tool or a second
launch that constructs AtlasApplication directly is refused too, not only
the main entry point.

The lock is an exclusive OS lock (fcntl.flock / msvcrt.locking) on
``<state_root>/atlas.instance.lock``. The OS drops it when the process dies,
so a crash never leaves a stale lock. Within one process it is shared and
reference-counted: the entry point and the application it builds hold the
same lock, and a process may rebuild an application on the same root (as
restart tests do). Only another process is excluded.
"""

from __future__ import annotations

import os
import threading
import time
from pathlib import Path
from typing import Any

INSTANCE_LOCK_FILE_NAME = "atlas.instance.lock"

# Windows releases a dead process's lock "eventually", not instantly, so a
# restart right after a crash retries briefly before concluding that another
# instance really is running.
RETRY_SECONDS = 5.0
RETRY_INTERVAL_SECONDS = 0.25


class InstanceLockHeldError(RuntimeError):
    """Another process holds the state root; this one must not start."""


class InstanceLockUnavailableError(RuntimeError):
    """The lock file could not be opened; starting unlocked is not allowed."""


_registry_guard = threading.Lock()
_held: dict[str, list[Any]] = {}  # resolved root -> [handle, refcount]


def _key(root: Path) -> str:
    # normcase: on Windows C:\AtlasState and c:\atlasstate are one directory
    # and must be one key, or a second handle in this same process would
    # collide with the first and read as "held by another instance".
    return os.path.normcase(str(Path(root).resolve()))


def _try_lock(handle: Any) -> bool:
    """One non-blocking attempt at the exclusive OS lock."""

    try:
        if os.name == "nt":
            import msvcrt

            handle.seek(0)
            msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl

            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        return False

    return True


def acquire(root: Path) -> None:
    """Take (or share, within this process) the lock on ``root``.

    Raises InstanceLockHeldError when another process holds it, and
    InstanceLockUnavailableError when the lock file cannot be opened.
    """

    key = _key(root)

    with _registry_guard:
        entry = _held.get(key)
        if entry is not None:
            entry[1] += 1
            return

        path = Path(root).resolve() / INSTANCE_LOCK_FILE_NAME
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            handle = open(path, "a+b")
        except OSError as exc:
            raise InstanceLockUnavailableError(
                f"Instance lock unavailable: {exc}"
            ) from exc

        deadline = time.monotonic() + RETRY_SECONDS
        while not _try_lock(handle):
            if time.monotonic() >= deadline:
                handle.close()
                raise InstanceLockHeldError(
                    f"Another Atlas instance holds {path}; refusing to start "
                    "a second one on the same state"
                )
            time.sleep(RETRY_INTERVAL_SECONDS)

        _held[key] = [handle, 1]


def release(root: Path) -> None:
    """Drop one reference; the OS lock is released with the last one."""

    key = _key(root)

    with _registry_guard:
        entry = _held.get(key)
        if entry is None:
            return
        entry[1] -= 1
        if entry[1] > 0:
            return
        del _held[key]
        try:
            entry[0].close()
        except OSError:
            pass


def held(root: Path) -> bool:
    """True when this process currently holds ``root``."""

    with _registry_guard:
        return _key(root) in _held
