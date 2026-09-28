"""SUPERVISOR-1 step 3: the parent process that restarts Atlas.

What has to be true, and why each part is tested the way it is:

POLICY
    The backoff values, the give-up bound, and the 600s counter reset are
    pure decisions with no clock, so they are asserted directly. Waiting out
    a real 600s window to test its boundary would be both slow and less
    precise than checking the boundary itself.

LOOP
    The restart loop is driven with a scripted clock and a fake child, so
    the ordering that matters - which backoff is chosen, when the counter
    resets, when the loop gives up - is observable without real time passing.
    The backoff delays are read back through a recording stop event, which
    is what the supervisor actually waits on.

REAL PROCESSES
    Everything about signal delivery and teardown is exercised against real
    child processes with real CTRL_BREAK_EVENT delivery. That part is
    exactly the kind of thing that is silently wrong until it is run for
    real, so none of it is mocked: the child is a genuine process in its own
    process group, and the supervisor stops it the way it will in production.

No test here starts Atlas itself. The supervisor's contract is with a child
process's exit code, so the children below are small scripts that produce
the exit codes and signal behaviour Atlas produces - not the runtime, which
a test may not start.
"""

from __future__ import annotations

import subprocess
import sys
import threading

from pathlib import Path
from typing import Any

import pytest

import atlas_supervisor

from atlas_supervisor import (
    ENV_EPOCH,
    ENV_HEARTBEAT_FILE,
    ENV_RESTART_COUNT,
    HeartbeatPolicy,
    LOG_DIRECTORY_ENV,
    ProcessSupervisor,
    RestartPolicy,
)


WINDOWS_ONLY = pytest.mark.skipif(
    not hasattr(__import__("signal"), "CTRL_BREAK_EVENT"),
    reason="CTRL_BREAK_EVENT / CREATE_NEW_PROCESS_GROUP are Windows-only",
)


# =====================================================================
# POLICY
# =====================================================================


def test_default_backoff_sequence_is_the_agreed_one() -> None:
    policy = RestartPolicy()

    assert [policy.backoff_for(n) for n in range(1, 6)] == [
        5.0,
        15.0,
        45.0,
        120.0,
        300.0,
    ]


def test_five_restarts_are_allowed_and_the_sixth_gives_up() -> None:
    policy = RestartPolicy()

    assert [policy.exhausted(n) for n in range(1, 7)] == [
        False,
        False,
        False,
        False,
        False,
        True,
    ]


def test_counter_reset_boundary_is_exact() -> None:
    """Just under 600s does not forgive; exactly 600s does."""

    policy = RestartPolicy()

    assert policy.resets_counter(599.999) is False
    assert policy.resets_counter(600.0) is True
    assert policy.resets_counter(600.001) is True


def test_backoff_is_one_based() -> None:
    with pytest.raises(ValueError):
        RestartPolicy().backoff_for(0)


def test_a_reset_window_inside_the_backoff_ceiling_is_rejected() -> None:
    """The invariant that keeps a slow crash-loop from resetting itself.

    If the healthy-run window were not longer than the largest backoff, a
    process that crashed once per backoff period would keep clearing its own
    attempt counter and the give-up rule would never be reached.
    """

    with pytest.raises(ValueError, match="largest backoff"):
        RestartPolicy(
            max_attempts=2,
            backoff_seconds=(10.0, 600.0),
            healthy_run_seconds=600.0,
        )


def test_backoff_must_cover_every_attempt() -> None:
    with pytest.raises(ValueError, match="cover every attempt"):
        RestartPolicy(
            max_attempts=5,
            backoff_seconds=(1.0, 2.0),
            healthy_run_seconds=100.0,
        )


# =====================================================================
# LOOP: scripted clock, fake child
# =====================================================================


class _FakeChild:
    """A child that has already exited with a scripted code."""

    def __init__(self, returncode: int) -> None:
        self.returncode = returncode
        self.signals: list[int] = []
        self.terminated = False
        self.killed = False

    def poll(self) -> int | None:
        return self.returncode

    def wait(self, timeout: float | None = None) -> int:
        del timeout
        return self.returncode

    def send_signal(self, number: int) -> None:
        self.signals.append(number)

    def terminate(self) -> None:
        self.terminated = True

    def kill(self) -> None:
        self.killed = True


class _RecordingEvent(threading.Event):
    """Records the timeouts the supervisor waits on.

    Every child below has already exited when it is polled, so the poll loop
    never waits. Every recorded timeout is therefore a backoff.
    """

    def __init__(self) -> None:
        super().__init__()
        self.waits: list[float | None] = []

    def wait(self, timeout: float | None = None) -> bool:
        self.waits.append(timeout)
        return super().wait(0)


_FAST_POLICY = RestartPolicy(
    max_attempts=5,
    # Distinct so the recorded sequence identifies which attempt was chosen.
    backoff_seconds=(0.001, 0.002, 0.003, 0.004, 0.005),
    healthy_run_seconds=600.0,
)


def _drive(
    exit_codes: list[int],
    run_durations: list[float],
    *,
    policy: RestartPolicy = _FAST_POLICY,
) -> tuple[int, list[dict[str, str]], list[float | None]]:
    """Run the supervisor over a scripted sequence of child runs.

    Returns the supervisor's exit code, the environment each launch was
    given, and the backoff delays it waited on.
    """

    codes = list(exit_codes)
    # run() reads the clock twice per iteration: once before the child is
    # awaited and once after, so a run of duration d is the pair (0, d).
    ticks: list[float] = []
    for duration in run_durations:
        ticks.extend((0.0, duration))

    environments: list[dict[str, str]] = []

    def launch(environment: dict[str, str]) -> _FakeChild:
        environments.append(dict(environment))
        return _FakeChild(codes.pop(0))

    supervisor = ProcessSupervisor(
        policy=policy,
        launch=launch,
        monotonic=lambda: ticks.pop(0),
        epoch="a" * 32,
    )

    recording = _RecordingEvent()
    supervisor._stop_event = recording

    return supervisor.run(), environments, recording.waits


def test_a_clean_first_exit_is_never_restarted() -> None:
    """Exit 0 is terminal. Restarting it would loop every operator stop."""

    exit_code, environments, waits = _drive([0], [1.0])

    assert exit_code == 0
    assert len(environments) == 1
    assert waits == []


def test_an_abnormal_exit_is_restarted() -> None:
    exit_code, environments, waits = _drive([1, 0], [1.0, 1.0])

    assert exit_code == 0
    assert len(environments) == 2
    assert waits == [0.001]


def test_five_rapid_crashes_give_up_with_a_non_zero_exit() -> None:
    """Six launches: the original plus five restarts, then stop."""

    exit_code, environments, waits = _drive(
        [1, 1, 1, 1, 1, 1],
        [1.0] * 6,
    )

    assert exit_code == 1
    assert len(environments) == 6
    assert waits == [0.001, 0.002, 0.003, 0.004, 0.005]


def test_a_run_just_under_the_window_does_not_reset_the_counter() -> None:
    """599.999s of uptime still counts as part of the same incident."""

    _, _, waits = _drive(
        [1, 1, 1, 0],
        [1.0, 1.0, 599.999, 1.0],
    )

    # Third crash escalated to the third backoff: nothing was forgiven.
    assert waits == [0.001, 0.002, 0.003]


def test_a_run_at_the_window_resets_the_counter() -> None:
    """600.0s of uptime makes the next crash a fresh incident."""

    _, _, waits = _drive(
        [1, 1, 1, 0],
        [1.0, 1.0, 600.0, 1.0],
    )

    # Third crash fell back to the first backoff: the counter reset.
    assert waits == [0.001, 0.002, 0.001]


def test_a_reset_restores_the_full_five_attempt_budget() -> None:
    """The reset must forgive the count, not merely the backoff choice."""

    exit_code, environments, _ = _drive(
        # Four crashes, then a healthy run, then five more crashes. Without
        # the reset the budget would be gone well before the end.
        [1, 1, 1, 1, 1, 1, 1, 1, 1, 1],
        [1.0, 1.0, 1.0, 1.0, 600.0, 1.0, 1.0, 1.0, 1.0, 1.0],
        policy=_FAST_POLICY,
    )

    assert exit_code == 1
    assert len(environments) == 10


def test_each_launch_is_told_the_epoch_and_its_restart_count() -> None:
    _, environments, _ = _drive([1, 1, 0], [1.0, 1.0, 1.0])

    assert [env[ENV_RESTART_COUNT] for env in environments] == ["0", "1", "2"]
    assert {env[ENV_EPOCH] for env in environments} == {"a" * 32}


def test_a_stop_during_backoff_ends_the_supervisor_cleanly() -> None:
    """A five-minute backoff must not outlive an operator's Ctrl+C."""

    codes = [1, 0]
    ticks = [0.0, 1.0, 0.0, 1.0]

    supervisor = ProcessSupervisor(
        policy=_FAST_POLICY,
        launch=lambda environment: _FakeChild(codes.pop(0)),
        monotonic=lambda: ticks.pop(0),
        epoch="b" * 32,
    )

    class _StopOnBackoff(_RecordingEvent):
        def wait(self, timeout: float | None = None) -> bool:
            self.waits.append(timeout)
            return True

    supervisor._stop_event = _StopOnBackoff()

    assert supervisor.run() == 0
    # The second child was never launched.
    assert codes == [0]


# =====================================================================
# HEARTBEAT POLICY
# =====================================================================


def test_heartbeat_default_thresholds_are_internally_consistent() -> None:
    policy = HeartbeatPolicy()

    assert policy.check_interval_seconds < policy.stale_after_seconds
    assert policy.startup_grace_seconds > 0


def test_heartbeat_check_interval_must_be_smaller_than_staleness() -> None:
    with pytest.raises(ValueError, match="check_interval_seconds"):
        HeartbeatPolicy(
            stale_after_seconds=5.0,
            check_interval_seconds=5.0,
        )


def test_heartbeat_thresholds_must_be_positive() -> None:
    with pytest.raises(ValueError, match="must be positive"):
        HeartbeatPolicy(stale_after_seconds=0.0)


def test_heartbeat_is_stale_boundary_is_exact() -> None:
    policy = HeartbeatPolicy(stale_after_seconds=30.0)

    assert policy.is_stale(now=1029.999, heartbeat_at=1000.0) is False
    assert policy.is_stale(now=1030.0, heartbeat_at=1000.0) is True


# =====================================================================
# HEARTBEAT FILE RESOLUTION
# =====================================================================


def test_heartbeat_file_resolves_from_log_directory_env(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(LOG_DIRECTORY_ENV, str(tmp_path))

    supervisor = ProcessSupervisor(launch=lambda environment: None)

    assert supervisor.heartbeat_file == (
        tmp_path / atlas_supervisor.HEARTBEAT_FILE_NAME
    )


def test_heartbeat_disabled_when_log_directory_env_is_unset(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv(LOG_DIRECTORY_ENV, raising=False)

    supervisor = ProcessSupervisor(launch=lambda environment: None)

    assert supervisor.heartbeat_file is None


def test_heartbeat_disabled_when_log_directory_does_not_exist(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(
        LOG_DIRECTORY_ENV,
        str(tmp_path / "does_not_exist"),
    )

    supervisor = ProcessSupervisor(launch=lambda environment: None)

    assert supervisor.heartbeat_file is None


def test_child_environment_carries_the_heartbeat_file_only_when_configured() -> (
    None
):
    with_heartbeat = ProcessSupervisor(
        launch=lambda environment: None,
        heartbeat_file=Path("C:/atlas/heartbeat.json"),
    )
    without_heartbeat = ProcessSupervisor(
        launch=lambda environment: None,
        heartbeat_file=None,
    )

    # str(Path(...)) is the platform's own spelling of the path: backslashes
    # on Windows, forward slashes elsewhere. Comparing against it keeps the
    # contract (the configured file is carried verbatim) portable to CI.
    assert (
        with_heartbeat._child_environment()[ENV_HEARTBEAT_FILE]
        == str(Path("C:/atlas/heartbeat.json"))
    )
    assert ENV_HEARTBEAT_FILE not in without_heartbeat._child_environment()


# =====================================================================
# HUNG-CHILD DETECTION: scripted clock, live fake child
# =====================================================================


class _HangingChild:
    """A child that never exits on its own - alive until stopped.

    poll() keeps returning None (the real signature of a hung process)
    until send_signal/terminate/kill marks it stopped, mirroring what a
    real stop_child() escalation would eventually observe.
    """

    def __init__(self, exit_code: int = 0) -> None:
        self._alive = True
        self._exit_code = exit_code
        self.signals: list[int] = []
        self.terminate_calls = 0
        self.kill_calls = 0

    def poll(self) -> int | None:
        return None if self._alive else self._exit_code

    def wait(self, timeout: float | None = None) -> int:
        del timeout
        self._alive = False
        return self._exit_code

    def send_signal(self, number: int) -> None:
        self.signals.append(number)
        self._alive = False

    def terminate(self) -> None:
        self.terminate_calls += 1
        self._alive = False

    def kill(self) -> None:
        self.kill_calls += 1
        self._alive = False


_FAST_HEARTBEAT_POLICY = HeartbeatPolicy(
    stale_after_seconds=30.0,
    startup_grace_seconds=120.0,
    check_interval_seconds=5.0,
)


def test_a_hung_child_is_stopped_and_restarted_like_an_abnormal_exit() -> None:
    """No heartbeat progress past staleness -> forced down, then restarted."""

    hanging_child = _HangingChild()
    clean_child = _FakeChild(0)

    children = [hanging_child, clean_child]

    def launch(environment: dict[str, str]) -> Any:
        return children.pop(0)

    # started_at_wall, then one in-loop check that is already well past both
    # the startup grace and the check interval, with a heartbeat mtime that
    # is already well past staleness.
    wall_ticks = [1_000.0, 2_000.0, 0.0, 0.0]

    supervisor = ProcessSupervisor(
        policy=RestartPolicy(
            max_attempts=5,
            backoff_seconds=(0.001,) * 5,
            healthy_run_seconds=600.0,
        ),
        launch=launch,
        monotonic=lambda: 0.0,
        heartbeat_file=Path("dummy_heartbeat.json"),
        heartbeat_policy=_FAST_HEARTBEAT_POLICY,
        heartbeat_mtime=lambda path: 500.0,
        wall_clock=lambda: wall_ticks.pop(0),
    )

    recording = _RecordingEvent()
    supervisor._stop_event = recording

    assert supervisor.run() == 0

    assert children == []
    # The hang was resolved through the graceful path, exactly like a real
    # stop - never straight to terminate/kill.
    assert hanging_child.signals == [atlas_supervisor.STOP_SIGNAL]
    assert hanging_child.terminate_calls == 0


def test_no_hang_check_runs_before_the_startup_grace_elapses() -> None:
    """A hanging child within its grace window must never be forced down.

    wall_clock() is pinned at a constant well inside the 120s default grace
    window (started_at_wall and every in-loop "now" are the same value), and
    the heartbeat mtime is pinned to a value that would read as stale the
    instant a check were ever made. If the grace window were not honoured,
    this child would be declared hung and a second one would be launched;
    proving it is never restarted proves the check never ran.
    """

    launched = {"count": 0}

    def launch(environment: dict[str, str]) -> Any:
        launched["count"] += 1
        return _HangingChild()

    supervisor = ProcessSupervisor(
        launch=launch,
        monotonic=lambda: 0.0,
        heartbeat_file=Path("dummy_heartbeat.json"),
        heartbeat_policy=_FAST_HEARTBEAT_POLICY,
        heartbeat_mtime=lambda path: 0.0,
        wall_clock=lambda: 10.0,
    )

    class _StopAfterFewPolls(threading.Event):
        """Ends the loop deterministically without any real sleeping."""

        def __init__(self) -> None:
            super().__init__()
            self.calls = 0

        def wait(self, timeout: float | None = None) -> bool:
            del timeout
            self.calls += 1

            if self.calls >= 3:
                self.set()

            return self.is_set()

    supervisor._stop_event = _StopAfterFewPolls()

    assert supervisor.run() == 0
    assert launched["count"] == 1


def test_hung_detection_is_inactive_when_no_heartbeat_file_is_configured() -> (
    None
):
    """Without a configured heartbeat file, a live child is never hung."""

    child = _FakeChild(0)
    launched = {"count": 0}

    def launch(environment: dict[str, str]) -> Any:
        launched["count"] += 1
        return child

    supervisor = ProcessSupervisor(
        launch=launch,
        monotonic=lambda: 0.0,
        heartbeat_file=None,
        # If staleness were ever consulted despite no file being configured,
        # this would report every check as stale.
        heartbeat_mtime=lambda path: 0.0,
        wall_clock=lambda: 10_000.0,
    )

    assert supervisor.run() == 0
    assert launched["count"] == 1


# =====================================================================
# REAL PROCESSES: genuine CTRL_BREAK_EVENT delivery and teardown
# =====================================================================


_CHILD_EXITS_WITH_RESTART_COUNT = '''
import os
import sys

# Exits abnormally until the supervisor has restarted it twice, proving the
# restart-count environment variable actually reaches a real child.
count = int(os.environ["ATLAS_SUPERVISOR_RESTART_COUNT"])

print("ATLAS_CHILD_LAUNCH count=%d epoch=%s" % (
    count, os.environ["ATLAS_SUPERVISOR_EPOCH"],
))
sys.stdout.flush()

raise SystemExit(0 if count >= 2 else 1)
'''


# Both children below wait on a bounded tick rather than one long block,
# because that is what AtlasProcess.run_forever() does - and it has to. A
# Windows console control event is delivered on a thread Windows injects;
# the Python-level handler only runs when the main thread next executes
# bytecode, so a main thread parked in a single long wait does not observe
# the signal until that wait returns. The supervisor's graceful-stop budget
# therefore assumes a child that ticks, and these stubs must model that
# faithfully or they would be testing a child Atlas is not.
_CHILD_TICK = 0.2

_CHILD_GRACEFUL = '''
import signal
import sys
import threading
import time

marker = sys.argv[1]
stop = threading.Event()


def handle(number, frame):
    stop.set()


signal.signal(signal.SIGBREAK, handle)

print("ATLAS_CHILD_READY")
sys.stdout.flush()

deadline = time.monotonic() + 120
while not stop.is_set() and time.monotonic() < deadline:
    stop.wait(0.2)

# Evidence the handler ran rather than the process being killed outright -
# the same thing AtlasApplication.stop()'s flush represents in production.
with open(marker, "w", encoding="utf-8") as handle_out:
    handle_out.write("flushed")

raise SystemExit(0)
'''


_CHILD_IGNORES_BREAK = '''
import signal
import sys
import threading
import time

received = []

signal.signal(signal.SIGBREAK, lambda number, frame: received.append(number))

print("ATLAS_CHILD_READY")
sys.stdout.flush()

# Ticks, so the handler genuinely runs and the signal is genuinely ignored -
# rather than never being observed at all, which would test nothing.
idle = threading.Event()
deadline = time.monotonic() + 300
while time.monotonic() < deadline:
    idle.wait(0.2)

raise SystemExit(0)
'''


class _SignalCountingChild:
    """A real Popen, wrapped only to count the signals sent to it.

    Delegation rather than simulation: the process, the process group, and
    the signal are all genuine. The counter exists because "never send a
    second graceful signal" is a claim about the supervisor's behaviour that
    cannot be read off the child.
    """

    def __init__(self, process: subprocess.Popen) -> None:
        self.process = process
        self.signals: list[int] = []
        self.terminate_calls = 0
        self.kill_calls = 0

    @property
    def returncode(self) -> int | None:
        return self.process.returncode

    def poll(self) -> int | None:
        return self.process.poll()

    def wait(self, timeout: float | None = None) -> int:
        return self.process.wait(timeout=timeout)

    def send_signal(self, number: int) -> None:
        self.signals.append(number)
        self.process.send_signal(number)

    def terminate(self) -> None:
        self.terminate_calls += 1
        self.process.terminate()

    def kill(self) -> None:
        self.kill_calls += 1
        self.process.kill()


def _write_child(tmp_path: Path, source: str, name: str) -> Path:
    script = tmp_path / name
    script.write_text(source, encoding="utf-8")
    return script


def _spawn(script: Path, *arguments: str) -> subprocess.Popen:
    return subprocess.Popen(
        [sys.executable, str(script), *arguments],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        creationflags=atlas_supervisor.CREATION_FLAGS,
    )


def _await_ready(process: subprocess.Popen, marker: str) -> None:
    assert process.stdout is not None

    for line in process.stdout:
        if line.startswith(marker):
            return

    raise AssertionError(f"child never printed {marker}")


@WINDOWS_ONLY
def test_a_real_child_is_restarted_until_it_exits_cleanly(
    tmp_path: Path,
) -> None:
    """End to end with real processes, including the restart-count handoff."""

    script = _write_child(
        tmp_path,
        _CHILD_EXITS_WITH_RESTART_COUNT,
        "atlas_child_restart_count.py",
    )

    launches: list[subprocess.Popen] = []

    def launch(environment: dict[str, str]) -> subprocess.Popen:
        process = subprocess.Popen(
            [sys.executable, str(script)],
            env=environment,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            creationflags=atlas_supervisor.CREATION_FLAGS,
        )
        launches.append(process)
        return process

    supervisor = ProcessSupervisor(
        policy=RestartPolicy(
            max_attempts=5,
            backoff_seconds=(0.01,) * 5,
            healthy_run_seconds=600.0,
        ),
        launch=launch,
    )

    assert supervisor.run() == 0

    # Two crashes, then a clean exit that is not restarted.
    assert len(launches) == 3
    assert [process.returncode for process in launches] == [1, 1, 0]


@WINDOWS_ONLY
def test_stop_child_delivers_one_real_ctrl_break_and_lets_it_flush(
    tmp_path: Path,
) -> None:
    """The production stop path: one signal, a real handler, a clean exit."""

    marker = tmp_path / "flushed.txt"
    script = _write_child(tmp_path, _CHILD_GRACEFUL, "atlas_child_graceful.py")

    process = _spawn(script, str(marker))
    _await_ready(process, "ATLAS_CHILD_READY")

    child = _SignalCountingChild(process)
    supervisor = ProcessSupervisor(launch=lambda environment: child)

    try:
        returncode = supervisor.stop_child(child)
    finally:
        if process.poll() is None:
            process.kill()
            process.wait(timeout=30)

    assert returncode == 0
    assert marker.read_text(encoding="utf-8") == "flushed"

    # Exactly one graceful signal, and no escalation was needed.
    assert child.signals == [atlas_supervisor.STOP_SIGNAL]
    assert child.terminate_calls == 0
    assert child.kill_calls == 0


@WINDOWS_ONLY
def test_a_child_that_ignores_the_signal_is_terminated_not_re_signalled(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Escalation is terminate(), never a repeat signal.

    AtlasProcess._handle_signal early-returns once its shutdown event is
    set, so a second signal is silently ignored - it would look like an
    escalation without being one.
    """

    monkeypatch.setattr(
        atlas_supervisor,
        "GRACEFUL_STOP_TIMEOUT_SECONDS",
        2.0,
    )

    script = _write_child(
        tmp_path,
        _CHILD_IGNORES_BREAK,
        "atlas_child_ignores_break.py",
    )

    process = _spawn(script)
    _await_ready(process, "ATLAS_CHILD_READY")

    child = _SignalCountingChild(process)
    supervisor = ProcessSupervisor(launch=lambda environment: child)

    try:
        supervisor.stop_child(child)
    finally:
        if process.poll() is None:
            process.kill()
            process.wait(timeout=30)

    assert process.poll() is not None, "the child was not stopped"

    # One graceful signal only; the escalation was a terminate.
    assert child.signals == [atlas_supervisor.STOP_SIGNAL]
    assert child.terminate_calls == 1


@WINDOWS_ONLY
def test_an_operator_stop_stops_the_real_child_rather_than_orphaning_it(
    tmp_path: Path,
) -> None:
    """Ctrl+C on the supervisor's console must reach Atlas.

    A child in a new process group has Ctrl+C disabled, so the console event
    reaches the supervisor alone. Without explicit forwarding the supervisor
    would exit and leave a running runtime behind.
    """

    marker = tmp_path / "flushed.txt"
    script = _write_child(
        tmp_path,
        _CHILD_GRACEFUL,
        "atlas_child_operator_stop.py",
    )

    started = threading.Event()
    processes: list[subprocess.Popen] = []

    def launch(environment: dict[str, str]) -> subprocess.Popen:
        process = _spawn(script, str(marker))
        processes.append(process)
        _await_ready(process, "ATLAS_CHILD_READY")
        started.set()
        return process

    supervisor = ProcessSupervisor(launch=launch)

    def request_stop_once_running() -> None:
        started.wait(timeout=60)
        supervisor.request_stop()

    stopper = threading.Thread(target=request_stop_once_running, daemon=True)
    stopper.start()

    try:
        assert supervisor.run() == 0
    finally:
        stopper.join(timeout=30)
        for process in processes:
            if process.poll() is None:
                process.kill()
                process.wait(timeout=30)

    assert len(processes) == 1
    assert processes[0].returncode == 0

    # The child shut down through its handler, not by being orphaned or
    # killed: the flush ran.
    assert marker.read_text(encoding="utf-8") == "flushed"


# =====================================================================
# SUPERVISOR PROVENANCE ON health()
# =====================================================================


def test_health_reports_supervision_from_a_validated_environment(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from core.application import AtlasApplication

    monkeypatch.setenv(ENV_EPOCH, "c" * 32)
    monkeypatch.setenv(ENV_RESTART_COUNT, "4")

    report = AtlasApplication(
        state_directory=tmp_path / "state",
    ).health()

    assert report["supervised"] is True
    assert report["supervisor_epoch"] == "c" * 32
    assert report["supervisor_restart_count"] == 4


def test_health_reports_an_unsupervised_process_as_unsupervised(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from core.application import AtlasApplication

    monkeypatch.delenv(ENV_EPOCH, raising=False)
    monkeypatch.delenv(ENV_RESTART_COUNT, raising=False)

    report = AtlasApplication(
        state_directory=tmp_path / "state",
    ).health()

    assert report["supervised"] is False
    assert report["supervisor_epoch"] is None
    assert report["supervisor_restart_count"] is None


def test_health_never_echoes_a_malformed_supervisor_environment(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """These values are published verbatim to /api/health.

    Anything able to set this process's environment could otherwise place
    arbitrary text into an HTTP response body, so an unverifiable claim of
    supervision is reported as absent rather than echoed.
    """

    from core.application import AtlasApplication

    monkeypatch.setenv(ENV_EPOCH, "<script>alert(1)</script>")
    monkeypatch.setenv(ENV_RESTART_COUNT, "not-a-number")

    report = AtlasApplication(
        state_directory=tmp_path / "state",
    ).health()

    assert report["supervised"] is False
    assert report["supervisor_epoch"] is None
    assert report["supervisor_restart_count"] is None
    assert "script" not in repr(report)


def test_supervision_is_provenance_and_never_gates_healthy(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A restarted Atlas is not by itself an unhealthy Atlas."""

    from core.application import AtlasApplication

    class _Running:
        def status(self) -> dict[str, Any]:
            return {"running": True, "healthy": True}

    monkeypatch.setenv(ENV_EPOCH, "d" * 32)
    monkeypatch.setenv(ENV_RESTART_COUNT, "5")

    application = AtlasApplication(state_directory=tmp_path / "state")
    application.execution = _Running()
    application.market_loop = _Running()

    report = application.health()

    assert report["supervisor_restart_count"] == 5
    assert report["healthy"] is True


# =====================================================================
# DEFAULT WIRING
# =====================================================================


def test_the_default_launcher_points_at_the_merged_entry_point() -> None:
    """The one thing about the real launcher a test can check.

    Every real-process test above injects its own launcher, because the
    default one starts Atlas - which connects to an exchange and writes the
    durable execution stores, so no test may run it. That leaves the target
    path itself unexercised, and a wrong path would fail only in front of an
    operator. Asserting it here costs nothing and catches exactly that.
    """

    assert atlas_supervisor.CHILD_SCRIPT.name == "atlas_service.py"
    assert atlas_supervisor.CHILD_SCRIPT.is_file()

    assert (
        ProcessSupervisor().launch is atlas_supervisor._launch_atlas_service
    )


def test_the_child_is_launched_in_its_own_process_group() -> None:
    """CREATE_NEW_PROCESS_GROUP is what makes CTRL_BREAK_EVENT addressable.

    Without it the graceful stop has no target, so this is a correctness
    property of the supervisor rather than a detail of how it spawns.
    """

    if not hasattr(subprocess, "CREATE_NEW_PROCESS_GROUP"):
        pytest.skip("Windows-only creation flag")

    assert (
        atlas_supervisor.CREATION_FLAGS
        == subprocess.CREATE_NEW_PROCESS_GROUP
    )
    assert atlas_supervisor.STOP_SIGNAL == __import__("signal").CTRL_BREAK_EVENT


def test_the_graceful_stop_budget_exceeds_the_runtime_shutdown_path() -> None:
    """Escalating early would kill Atlas during the financial-state flush.

    Atlas's shutdown is bounded by signal-delivery latency (run_forever polls
    on a one-second tick) plus the web server join, and then
    AtlasApplication.stop() has to flush. The budget must leave room for all
    three.
    """

    import atlas_service

    floor = 1.0 + atlas_service.WEB_SHUTDOWN_TIMEOUT_SECONDS

    assert atlas_supervisor.GRACEFUL_STOP_TIMEOUT_SECONDS > floor
