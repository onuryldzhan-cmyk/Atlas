"""One Atlas per state root, and no restart on unfixable exits.

The 2026-09-28 paper run forked the audit chain: two Atlas processes on one
state root appended to the same audit log. main.py now takes an exclusive OS
lock on the state root (exit 4 when held elsewhere) and exits 3 on an audit
chain integrity failure; atlas_supervisor.py restarts on neither, because a
restart cannot fix either condition.
"""

from __future__ import annotations

from pathlib import Path

import pytest

import atlas_supervisor
import main
from atlas_supervisor import ProcessSupervisor
from core.audit_event_store import AuditChainIntegrityError, AuditEventStore
from main import AtlasProcess
from tests.test_process_supervisor import _drive


@pytest.fixture(autouse=True)
def no_lock_retry(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(main, "INSTANCE_LOCK_RETRY_SECONDS", 0.0)


@pytest.fixture
def state_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("ATLAS_STATE_DIRECTORY", str(tmp_path))
    return tmp_path


def test_exit_codes_match_between_main_and_supervisor() -> None:
    assert main.INTEGRITY_HALT_EXIT_CODE == atlas_supervisor.INTEGRITY_HALT_EXIT_CODE
    assert main.ALREADY_RUNNING_EXIT_CODE == atlas_supervisor.ALREADY_RUNNING_EXIT_CODE
    # Never a code the OS or the C runtime produces by itself: 0/1 are
    # ordinary exits, 3 is abort() on Windows, 2 is a usage error.
    assert not atlas_supervisor.NO_RESTART_EXIT_CODES & {0, 1, 2, 3}


def test_second_instance_on_the_same_state_root_is_refused(state_root: Path) -> None:
    first = AtlasProcess()
    second = AtlasProcess()

    assert first._acquire_instance_lock() is True
    try:
        assert second._acquire_instance_lock() is False
        assert second.exit_code == main.ALREADY_RUNNING_EXIT_CODE
    finally:
        first._release_instance_lock()


def test_released_lock_can_be_taken_again(state_root: Path) -> None:
    first = AtlasProcess()
    assert first._acquire_instance_lock() is True
    first._release_instance_lock()

    second = AtlasProcess()
    assert second._acquire_instance_lock() is True
    second._release_instance_lock()


def test_unusable_state_root_is_a_normal_failure_not_run_unlocked(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ATLAS_STATE_DIRECTORY", str(tmp_path / "missing"))

    process = AtlasProcess()

    assert process._acquire_instance_lock() is False
    assert process.exit_code == 1
    assert process._instance_lock is None


def test_start_refuses_before_constructing_the_application(
    state_root: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    constructed = []
    monkeypatch.setattr(main, "AtlasApplication", lambda **kw: constructed.append(kw))

    holder = AtlasProcess()
    assert holder._acquire_instance_lock() is True
    try:
        process = AtlasProcess()
        monkeypatch.setattr(process, "install_signal_handlers", lambda: None)
        assert process.execute() == main.ALREADY_RUNNING_EXIT_CODE
        assert constructed == []
    finally:
        holder._release_instance_lock()


def test_audit_integrity_failure_exits_with_the_integrity_code(
    state_root: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    def broken(**kwargs):
        raise AuditChainIntegrityError("Audit event chain verification failed")

    monkeypatch.setattr(main, "AtlasApplication", broken)

    process = AtlasProcess()
    monkeypatch.setattr(process, "install_signal_handlers", lambda: None)

    assert process.execute() == main.INTEGRITY_HALT_EXIT_CODE
    # The lock is released on the way out, so a fixed state can start again.
    assert process._instance_lock is None


def test_other_fatal_errors_keep_exit_code_one(
    state_root: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    def broken(**kwargs):
        raise RuntimeError("something else")

    monkeypatch.setattr(main, "AtlasApplication", broken)

    process = AtlasProcess()
    monkeypatch.setattr(process, "install_signal_handlers", lambda: None)

    assert process.execute() == 1


def test_forked_audit_chain_raises_the_integrity_error(tmp_path: Path) -> None:
    path = tmp_path / "audit.jsonl"
    kw = dict(source="t", aggregate_type="x", payload={})

    first = AuditEventStore(path)
    first.append(event_type="E", aggregate_id="a0", **kw)
    second = AuditEventStore(path)
    first.append(event_type="E", aggregate_id="a1", **kw)
    second.append(event_type="E", aggregate_id="b0", **kw)

    with pytest.raises(AuditChainIntegrityError):
        AuditEventStore(path)

    assert issubclass(AuditChainIntegrityError, RuntimeError)


@pytest.mark.parametrize(
    "code", [atlas_supervisor.INTEGRITY_HALT_EXIT_CODE, atlas_supervisor.ALREADY_RUNNING_EXIT_CODE],
)
def test_supervisor_does_not_restart_on_unfixable_exits(code: int) -> None:
    exit_code, environments, waits = _drive([code], [1.0])

    assert exit_code == code
    assert len(environments) == 1
    assert waits == []


def test_supervisor_still_restarts_an_ordinary_crash() -> None:
    exit_code, environments, _ = _drive([1, 0], [1.0, 1.0])

    assert exit_code == 0
    assert len(environments) == 2


def test_lock_retries_until_a_briefly_held_lock_is_released(
    state_root: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A crashed predecessor whose lock the OS has not released yet."""

    monkeypatch.setattr(main, "INSTANCE_LOCK_RETRY_SECONDS", 5.0)
    monkeypatch.setattr(main, "INSTANCE_LOCK_RETRY_INTERVAL_SECONDS", 0.0)

    attempts = []

    def flaky(handle):
        attempts.append(1)
        return len(attempts) >= 3

    monkeypatch.setattr(AtlasProcess, "_try_lock", staticmethod(flaky))

    process = AtlasProcess()
    assert process._acquire_instance_lock() is True
    assert len(attempts) == 3
    process._release_instance_lock()


def _windows_try_lock(monkeypatch, locking, tmp_path):
    import sys
    import types

    monkeypatch.setitem(
        sys.modules, "msvcrt", types.SimpleNamespace(LK_NBLCK=2, locking=locking),
    )
    with open(tmp_path / "lock", "a+b") as handle:
        # Only the branch choice is patched, after the file is open, so
        # pathlib never sees a foreign os.name.
        monkeypatch.setattr(main.os, "name", "nt")
        try:
            return AtlasProcess._try_lock(handle)
        finally:
            monkeypatch.undo()


def test_windows_branch_uses_a_non_blocking_msvcrt_lock(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = []

    taken = _windows_try_lock(
        monkeypatch, lambda fd, mode, nbytes: calls.append((mode, nbytes)), tmp_path,
    )

    assert taken is True
    assert calls == [(2, 1)]


def test_windows_branch_contention_is_not_taken(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    def refuse(fd, mode, nbytes):
        raise PermissionError(13, "Permission denied")

    assert _windows_try_lock(monkeypatch, refuse, tmp_path) is False
