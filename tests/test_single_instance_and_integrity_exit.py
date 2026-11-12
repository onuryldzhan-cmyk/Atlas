"""One Atlas per state root, and no restart on unfixable exits.

The 2026-09-28 paper run forked the audit chain: two Atlas processes on one
state root appended to the same audit log. main.py now takes an exclusive OS
lock on the state root (exit 4 when held elsewhere) and exits 3 on an audit
chain integrity failure; atlas_supervisor.py restarts on neither, because a
restart cannot fix either condition.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

import atlas_supervisor
import main
from atlas_supervisor import ProcessSupervisor
from core import instance_lock
from core.application import AtlasApplication
from core.audit_event_store import AuditChainIntegrityError, AuditEventStore
from core.instance_lock import InstanceLockHeldError
from main import AtlasProcess
from tests.test_process_supervisor import _drive


@pytest.fixture(autouse=True)
def no_lock_retry(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(instance_lock, "RETRY_SECONDS", 0.0)


HOLDER = """
import sys, time
from pathlib import Path
from core import instance_lock
instance_lock.acquire(Path(sys.argv[1]))
print("HELD", flush=True)
sys.stdin.readline()
"""


@pytest.fixture
def other_process(state_root: Path):
    """A second OS process holding the state-root lock, like the second
    Atlas of the 2026-09-28 incident."""

    proc = subprocess.Popen(
        [sys.executable, "-c", HOLDER, str(state_root)],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True,
        cwd=str(Path(__file__).resolve().parents[1]),
    )
    assert proc.stdout.readline().strip() == "HELD"
    yield proc
    proc.stdin.write("\n")
    proc.stdin.flush()
    proc.wait(timeout=10)


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


def test_second_process_on_the_same_state_root_is_refused(
    state_root: Path, other_process,
) -> None:
    process = AtlasProcess()

    assert process._acquire_instance_lock() is False
    assert process.exit_code == main.ALREADY_RUNNING_EXIT_CODE


def test_application_built_directly_is_refused_while_another_process_holds_it(
    state_root: Path, other_process,
) -> None:
    """The gap the audit found: tools constructing AtlasApplication
    directly used to bypass the lock taken in AtlasProcess."""

    with pytest.raises(InstanceLockHeldError):
        AtlasApplication(state_directory=state_root)


def test_lock_is_shared_and_released_with_the_last_holder(state_root: Path) -> None:
    process = AtlasProcess()
    assert process._acquire_instance_lock() is True
    app = AtlasApplication(state_directory=state_root)
    assert instance_lock.held(state_root)

    process._release_instance_lock()
    assert instance_lock.held(state_root)  # the application still holds it

    app.stop()
    assert not instance_lock.held(state_root)


def test_released_lock_can_be_taken_by_another_process(state_root: Path) -> None:
    process = AtlasProcess()
    assert process._acquire_instance_lock() is True
    process._release_instance_lock()

    probe = subprocess.run(
        [sys.executable, "-c",
         "import sys; from pathlib import Path; from core import instance_lock;"
         "instance_lock.RETRY_SECONDS = 0; instance_lock.acquire(Path(sys.argv[1])); print('OK')",
         str(state_root)],
        capture_output=True, text=True, cwd=str(Path(__file__).resolve().parents[1]),
    )
    assert probe.stdout.strip() == "OK", probe.stderr


def test_unusable_state_root_is_a_normal_failure_not_run_unlocked(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ATLAS_STATE_DIRECTORY", str(tmp_path / "missing"))

    process = AtlasProcess()

    assert process._acquire_instance_lock() is False
    assert process.exit_code == 1
    assert process._instance_lock is None


def test_start_refuses_before_constructing_the_application(
    state_root: Path, monkeypatch: pytest.MonkeyPatch, other_process,
) -> None:
    constructed = []
    monkeypatch.setattr(main, "AtlasApplication", lambda **kw: constructed.append(kw))

    process = AtlasProcess()
    monkeypatch.setattr(process, "install_signal_handlers", lambda: None)
    assert process.execute() == main.ALREADY_RUNNING_EXIT_CODE
    assert constructed == []


def test_lock_refusal_raised_during_construction_exits_already_running(
    state_root: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    def refused(**kwargs):
        raise InstanceLockHeldError("held elsewhere")

    monkeypatch.setattr(main, "AtlasApplication", refused)
    process = AtlasProcess()
    monkeypatch.setattr(process, "install_signal_handlers", lambda: None)

    assert process.execute() == main.ALREADY_RUNNING_EXIT_CODE


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


class _PreContractWriter:
    """The pre-Phase-2-A2 writer: trusts its own in-memory chain head and
    appends without re-checking the file. Two of these on one file recreate
    the 2026-09-28 fork, which the real AuditEventStore now refuses to
    produce (A2 I-A7), so fork fixtures are built with this raw writer."""

    def __init__(self, path):
        from core.audit_event import GENESIS_HASH, AuditEvent
        self._event = AuditEvent
        self.path = Path(path)
        self.head = GENESIS_HASH
        if self.path.exists():
            lines = [l for l in self.path.read_text("utf-8").splitlines() if l.strip()]
            if lines:
                self.head = json.loads(lines[-1])["event_hash"]

    def append(self, *, event_type, source, aggregate_type, aggregate_id, payload):
        event = self._event.create(
            event_type=event_type, source=source, aggregate_type=aggregate_type,
            aggregate_id=aggregate_id, payload=payload, previous_hash=self.head,
        )
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8", newline="\n") as f:
            f.write(event.to_json() + "\n")
        self.head = event.event_hash
        return event


def test_forked_audit_chain_raises_the_integrity_error(tmp_path: Path) -> None:
    path = tmp_path / "audit.jsonl"
    kw = dict(source="t", aggregate_type="x", payload={})

    first = _PreContractWriter(path)
    first.append(event_type="E", aggregate_id="a0", **kw)
    second = _PreContractWriter(path)
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

    monkeypatch.setattr(instance_lock, "RETRY_SECONDS", 5.0)
    monkeypatch.setattr(instance_lock, "RETRY_INTERVAL_SECONDS", 0.0)

    attempts = []

    def flaky(handle):
        attempts.append(1)
        return len(attempts) >= 3

    monkeypatch.setattr(instance_lock, "_try_lock", flaky)

    instance_lock.acquire(state_root)
    assert len(attempts) == 3
    instance_lock.release(state_root)


def _windows_try_lock(monkeypatch, locking, tmp_path):
    import types

    monkeypatch.setitem(
        sys.modules, "msvcrt", types.SimpleNamespace(LK_NBLCK=2, locking=locking),
    )
    with open(tmp_path / "lock", "a+b") as handle:
        # Only the branch choice is patched, after the file is open, so
        # pathlib never sees a foreign os.name.
        monkeypatch.setattr(instance_lock.os, "name", "nt")
        try:
            return instance_lock._try_lock(handle)
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


def test_failed_construction_gives_the_lock_back(state_root: Path) -> None:
    """Construction that fails after taking the lock must not keep it."""

    audit = state_root / "audit" / "atlas_audit_events.jsonl"
    kw = dict(source="t", aggregate_type="x", payload={})
    first = _PreContractWriter(audit)
    first.append(event_type="E", aggregate_id="a0", **kw)
    second = _PreContractWriter(audit)
    first.append(event_type="E", aggregate_id="a1", **kw)
    second.append(event_type="E", aggregate_id="b0", **kw)

    with pytest.raises(AuditChainIntegrityError):
        AtlasApplication(state_directory=state_root)

    assert not instance_lock.held(state_root)


def test_the_constructor_signature_is_unchanged_by_the_wrapper() -> None:
    import inspect

    params = inspect.signature(AtlasApplication).parameters
    assert "state_directory" in params
    assert "paper_confidence_experiment" in params
