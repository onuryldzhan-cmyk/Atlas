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

import logging
import os
import subprocess
import sys
import threading

from collections.abc import Callable
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

    assert (
        with_heartbeat._child_environment()[ENV_HEARTBEAT_FILE]
        == "C:\\atlas\\heartbeat.json"
    )
    assert ENV_HEARTBEAT_FILE not in without_heartbeat._child_environment()


# =====================================================================
# HUNG-CHILD DETECTION: simulated monotonic clock, live fake child
# =====================================================================


# Well past every scenario below (the longest ends at 6 x 300s of startup
# hangs), well short of a run that would hang the suite.
_SIMULATION_CEILING_SECONDS = 5_000.0


class _SimulatedTime:
    """A monotonic clock that only moves when the supervisor waits.

    Installed as both the supervisor's monotonic clock and (through
    _SimulatedStopEvent) the thing every poll/backoff wait advances, so a
    run of several simulated minutes executes instantly and every age the
    supervisor computes is exact.
    """

    def __init__(self) -> None:
        self.now = 0.0

    def monotonic(self) -> float:
        return self.now


class _SimulatedStopEvent(threading.Event):
    """Advances _SimulatedTime by each wait; sets itself at ``stop_at``.

    ``stop_at`` stands in for an operator stop, which is how a scenario
    with a child that never exits on its own is brought to an end.

    Past ``_SIMULATION_CEILING_SECONDS`` of simulated time it raises
    instead, so a regression that stops ever reaching a verdict fails
    the test rather than hanging the suite.
    """

    def __init__(
        self,
        clock: _SimulatedTime,
        stop_at: float | None = None,
    ) -> None:
        super().__init__()
        self.clock = clock
        self.stop_at = stop_at
        self.waits: list[float | None] = []

    def wait(self, timeout: float | None = None) -> bool:
        self.waits.append(timeout)
        self.clock.now += timeout or 0.0

        if self.clock.now > _SIMULATION_CEILING_SECONDS:
            raise AssertionError(
                f"simulated run exceeded {_SIMULATION_CEILING_SECONDS}s "
                "without the expected verdict"
            )

        if self.stop_at is not None and self.clock.now >= self.stop_at:
            self.set()

        return self.is_set()


class _HangingChild:
    """A child that never exits on its own - alive until stopped.

    poll() keeps returning None (the real signature of a hung process)
    until send_signal/terminate/kill marks it stopped, mirroring what a
    real stop_child() escalation would eventually observe. Records the
    simulated time each graceful signal arrived.
    """

    def __init__(
        self,
        exit_code: int = 0,
        clock: _SimulatedTime | None = None,
    ) -> None:
        self._alive = True
        self._exit_code = exit_code
        self._clock = clock
        self.signals: list[int] = []
        self.signalled_at: list[float] = []
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

        if self._clock is not None:
            self.signalled_at.append(self._clock.now)

        self._alive = False

    def terminate(self) -> None:
        self.terminate_calls += 1
        self._alive = False

    def kill(self) -> None:
        self.kill_calls += 1
        self._alive = False


# Production defaults, stated explicitly so a scenario's timings read
# directly off them: grace 120s, first-heartbeat deadline 300s, stale
# after 30s, checked every 5s.
_HEARTBEAT_POLICY = HeartbeatPolicy(
    stale_after_seconds=30.0,
    startup_grace_seconds=120.0,
    first_heartbeat_deadline_seconds=300.0,
    check_interval_seconds=5.0,
)

_QUICK_RESTARTS = RestartPolicy(
    max_attempts=5,
    backoff_seconds=(0.001, 0.002, 0.003, 0.004, 0.005),
    healthy_run_seconds=600.0,
)

# A wall-clock-looking mtime stamp, in the integer nanoseconds the real
# reader returns. The supervisor must treat these as opaque.
_WALL_NS = 1_790_000_000 * 1_000_000_000

# What a heartbeat file left behind by an earlier run reports, unchanging.
_LEFTOVER_MTIME = _WALL_NS - 3_600 * 1_000_000_000


def _child_writes(
    clock: _SimulatedTime,
    *,
    before: Any,
    from_second: float,
    until_second: float = float("inf"),
    stamp: Callable[[float], int] | None = None,
) -> Callable[[Path], Any]:
    """An mtime reader for a child that writes once per second.

    Before ``from_second`` (and after ``until_second``) the file reports
    ``before`` / its last written stamp; in between, a new stamp per whole
    simulated second - which is what main.AtlasProcess's 1s tick produces.
    """

    stamp = stamp or (lambda second: _WALL_NS + int(second) * 1_000_000_000)

    def read(path: Path) -> Any:
        del path

        if clock.now < from_second:
            return before

        return stamp(min(clock.now, until_second))

    return read


def _heartbeat_supervisor(
    clock: _SimulatedTime,
    children: list[Any],
    *,
    heartbeat_mtime: Callable[[Path], Any],
    stop_at: float | None = None,
    heartbeat_discard: Callable[[Path], None] | None = None,
    policy: RestartPolicy = _QUICK_RESTARTS,
) -> tuple[ProcessSupervisor, _SimulatedStopEvent, list[dict[str, str]]]:
    environments: list[dict[str, str]] = []

    def launch(environment: dict[str, str]) -> Any:
        environments.append(dict(environment))
        return children.pop(0)

    supervisor = ProcessSupervisor(
        policy=policy,
        launch=launch,
        monotonic=clock.monotonic,
        epoch="e" * 32,
        heartbeat_file=Path("simulated_heartbeat.json"),
        heartbeat_policy=_HEARTBEAT_POLICY,
        heartbeat_mtime=heartbeat_mtime,
        heartbeat_discard=(
            heartbeat_discard
            if heartbeat_discard is not None
            else (lambda path: None)
        ),
    )

    event = _SimulatedStopEvent(clock, stop_at=stop_at)
    supervisor._stop_event = event

    return supervisor, event, environments


def _refuse_delete(path: Path) -> None:
    raise PermissionError(13, "file in use", str(path))


def _messages(caplog: pytest.LogCaptureFixture, level: int) -> list[str]:
    return [
        record.getMessage()
        for record in caplog.records
        if record.name == atlas_supervisor.LOGGER_NAME
        and record.levelno == level
    ]


# ---------------------------------------------------------------------
# Policy: the startup phases
# ---------------------------------------------------------------------


def test_heartbeat_startup_phase_boundaries_are_exact() -> None:
    policy = _HEARTBEAT_POLICY

    assert policy.startup_phase(since_launch=0.0) == "STARTING"
    assert policy.startup_phase(since_launch=119.999) == "STARTING"
    assert policy.startup_phase(since_launch=120.0) == "NO_HEARTBEAT_YET"
    assert policy.startup_phase(since_launch=299.999) == "NO_HEARTBEAT_YET"
    assert policy.startup_phase(since_launch=300.0) == "HUNG_AT_STARTUP"


def test_heartbeat_default_first_heartbeat_deadline_is_300s() -> None:
    policy = HeartbeatPolicy()

    assert policy.first_heartbeat_deadline_seconds == 300.0
    assert policy.first_heartbeat_deadline_seconds > policy.startup_grace_seconds


def test_first_heartbeat_deadline_must_exceed_the_grace() -> None:
    with pytest.raises(ValueError, match="first_heartbeat_deadline_seconds"):
        HeartbeatPolicy(
            startup_grace_seconds=120.0,
            first_heartbeat_deadline_seconds=120.0,
        )


# ---------------------------------------------------------------------
# Scenarios
# ---------------------------------------------------------------------


def test_a_hung_child_is_stopped_and_restarted_like_an_abnormal_exit(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """RUNNING, then no heartbeat change for 30s -> forced down, restarted.

    The child writes every second until t=200 and then freezes. The last
    change is observed at the t=200 check, so the verdict lands at the
    t=230 check - and the log reports that 30s heartbeat age, not the 230s
    the child had been running (LOW-7).
    """

    caplog.set_level(logging.INFO, logger=atlas_supervisor.LOGGER_NAME)

    clock = _SimulatedTime()
    hanging_child = _HangingChild(clock=clock)
    children: list[Any] = [hanging_child, _FakeChild(0)]

    supervisor, event, environments = _heartbeat_supervisor(
        clock,
        children,
        heartbeat_mtime=_child_writes(
            clock,
            before=None,
            from_second=10.0,
            until_second=200.0,
        ),
    )

    assert supervisor.run() == 0

    assert children == []
    assert len(environments) == 2
    # Resolved through the graceful path, exactly like a real stop - never
    # straight to terminate/kill - and at exactly the 30s staleness bound.
    assert hanging_child.signals == [atlas_supervisor.STOP_SIGNAL]
    assert hanging_child.terminate_calls == 0
    assert hanging_child.signalled_at == [230.0]

    critical = _messages(caplog, logging.CRITICAL)
    assert len(critical) == 1
    assert "no heartbeat for 30s" in critical[0]
    assert "after 230.0s of runtime" in critical[0]

    # The same restart bookkeeping as a crash: first backoff, then a
    # relaunch told it is restart number 1.
    assert 0.001 in event.waits
    assert environments[1][ENV_RESTART_COUNT] == "1"


def test_no_hang_check_runs_before_the_startup_grace_elapses(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """STARTING: no heartbeat at all inside the grace -> nothing happens.

    The operator stops the supervisor at t=119.75, a quarter-second before
    the grace ends. No warning, no kill, one launch.
    """

    caplog.set_level(logging.INFO, logger=atlas_supervisor.LOGGER_NAME)

    clock = _SimulatedTime()
    child = _HangingChild(clock=clock)

    supervisor, _, environments = _heartbeat_supervisor(
        clock,
        [child],
        heartbeat_mtime=lambda path: None,
        stop_at=119.75,
    )

    assert supervisor.run() == 0

    assert len(environments) == 1
    # The only signal is the operator stop's, at the stop time.
    assert child.signalled_at == [119.75]
    assert _messages(caplog, logging.WARNING) == []
    assert _messages(caplog, logging.CRITICAL) == []


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
        # If the heartbeat were ever consulted despite no file being
        # configured, these would fail the run.
        heartbeat_mtime=lambda path: pytest.fail("heartbeat read"),
        heartbeat_discard=lambda path: pytest.fail("heartbeat discard"),
    )

    assert supervisor.run() == 0
    assert launched["count"] == 1


def test_a_stale_leftover_file_does_not_count_as_a_heartbeat(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """HIGH-1: the delete fails and a previous run's file stays behind.

    Its mtime never changes. The new child is slow: it first writes at
    t=200, past the grace but inside the first-heartbeat deadline, then
    keeps writing. The leftover must not be mistaken for a heartbeat - if
    it were, the child would look RUNNING from t=0 and be killed as stale
    at t=30, long before its first real heartbeat.
    """

    caplog.set_level(logging.INFO, logger=atlas_supervisor.LOGGER_NAME)

    clock = _SimulatedTime()
    child = _HangingChild(clock=clock)

    supervisor, _, environments = _heartbeat_supervisor(
        clock,
        [child],
        heartbeat_mtime=_child_writes(
            clock,
            before=_LEFTOVER_MTIME,
            from_second=200.0,
        ),
        heartbeat_discard=_refuse_delete,
        stop_at=600.0,
    )

    assert supervisor.run() == 0

    assert len(environments) == 1
    assert child.signalled_at == [600.0]
    assert _messages(caplog, logging.CRITICAL) == []

    warnings = _messages(caplog, logging.WARNING)
    assert any("Could not delete the previous heartbeat file" in m for m in warnings)
    assert sum("No heartbeat from Atlas yet" in m for m in warnings) == 1


def test_a_leftover_file_cannot_keep_a_never_started_child_alive(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """HIGH-1, other direction: the delete fails, the child never writes.

    The leftover file is present and readable the whole time. Only a
    *change* counts, so the child is stopped as hung at startup at the
    first check at or after the 300s deadline.
    """

    caplog.set_level(logging.INFO, logger=atlas_supervisor.LOGGER_NAME)

    clock = _SimulatedTime()
    hung = _HangingChild(clock=clock)
    children: list[Any] = [hung, _FakeChild(0)]

    supervisor, _, environments = _heartbeat_supervisor(
        clock,
        children,
        heartbeat_mtime=lambda path: _LEFTOVER_MTIME,
        heartbeat_discard=_refuse_delete,
    )

    assert supervisor.run() == 0

    assert len(environments) == 2
    assert hung.signalled_at == [300.0]

    critical = _messages(caplog, logging.CRITICAL)
    assert len(critical) == 1
    assert "hung at startup" in critical[0]


def test_a_missing_file_with_a_never_started_child_is_hung_at_startup(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """HIGH-1: no file at all used to mean "unknown" forever.

    Before the redesign a child hung during startup, with no heartbeat
    file, was never caught. Now: one warning past the grace, then a stop
    at the deadline, then the ordinary restart.
    """

    caplog.set_level(logging.INFO, logger=atlas_supervisor.LOGGER_NAME)

    clock = _SimulatedTime()
    hung = _HangingChild(clock=clock)
    children: list[Any] = [hung, _FakeChild(0)]

    supervisor, event, environments = _heartbeat_supervisor(
        clock,
        children,
        heartbeat_mtime=lambda path: None,
    )

    assert supervisor.run() == 0

    assert len(environments) == 2
    assert hung.signalled_at == [300.0]
    assert hung.terminate_calls == 0

    warnings = _messages(caplog, logging.WARNING)
    assert sum("No heartbeat from Atlas yet" in m for m in warnings) == 1
    assert any("after 120s" in m for m in warnings)

    assert "hung at startup" in _messages(caplog, logging.CRITICAL)[0]
    assert event.waits.count(0.001) == 1


def test_a_slow_start_inside_the_deadline_is_warned_about_not_killed(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """NO_HEARTBEAT_YET: first heartbeat at t=250 -> one warning, no kill."""

    caplog.set_level(logging.INFO, logger=atlas_supervisor.LOGGER_NAME)

    clock = _SimulatedTime()
    child = _HangingChild(clock=clock)

    supervisor, _, environments = _heartbeat_supervisor(
        clock,
        [child],
        heartbeat_mtime=_child_writes(clock, before=None, from_second=250.0),
        stop_at=900.0,
    )

    assert supervisor.run() == 0

    assert len(environments) == 1
    assert child.signalled_at == [900.0]
    assert _messages(caplog, logging.CRITICAL) == []

    warnings = _messages(caplog, logging.WARNING)
    assert sum("No heartbeat from Atlas yet" in m for m in warnings) == 1

    assert any(
        "First heartbeat from Atlas after 250.0s" in m
        for m in _messages(caplog, logging.INFO)
    )


@pytest.mark.parametrize(
    "jump_seconds",
    [-100_000_000, +100_000_000],
    ids=["backward", "forward"],
)
def test_a_wall_clock_jump_never_causes_a_kill(
    jump_seconds: int,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """MEDIUM-2: the child's wall clock jumps ~3 years mid-run.

    Its heartbeat stamps jump with it, but they keep changing every
    second, so the child is alive. The supervisor's own wall clock is made
    to jump too, so any lingering dependence on time.time() in the verdict
    would surface here.
    """

    caplog.set_level(logging.INFO, logger=atlas_supervisor.LOGGER_NAME)

    clock = _SimulatedTime()
    child = _HangingChild(clock=clock)

    def stamp(second: float) -> int:
        shifted = second + (jump_seconds if second >= 300.0 else 0)
        return _WALL_NS + int(shifted) * 1_000_000_000

    real_time = atlas_supervisor.time.time

    def jumping_wall_clock() -> float:
        return real_time() + (jump_seconds if clock.now >= 300.0 else 0)

    monkeypatch.setattr(atlas_supervisor.time, "time", jumping_wall_clock)

    supervisor, _, environments = _heartbeat_supervisor(
        clock,
        [child],
        heartbeat_mtime=_child_writes(
            clock,
            before=None,
            from_second=5.0,
            stamp=stamp,
        ),
        stop_at=900.0,
    )

    assert supervisor.run() == 0

    assert len(environments) == 1
    assert child.signalled_at == [900.0]
    assert _messages(caplog, logging.CRITICAL) == []


def test_an_unreadable_heartbeat_while_running_is_not_a_hang(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """RUNNING, then the file cannot be read for 200s, then can again.

    Unknown is not evidence of a hang: detection pauses (one warning) and
    resumes when the file is readable - here with a fresh stamp.
    """

    caplog.set_level(logging.INFO, logger=atlas_supervisor.LOGGER_NAME)

    clock = _SimulatedTime()
    child = _HangingChild(clock=clock)
    writes = _child_writes(clock, before=None, from_second=5.0)

    def read(path: Path) -> Any:
        if 100.0 <= clock.now < 300.0:
            return None

        return writes(path)

    supervisor, _, _ = _heartbeat_supervisor(
        clock,
        [child],
        heartbeat_mtime=read,
        stop_at=600.0,
    )

    assert supervisor.run() == 0

    assert child.signalled_at == [600.0]
    assert _messages(caplog, logging.CRITICAL) == []
    assert (
        sum("unreadable" in m for m in _messages(caplog, logging.WARNING)) == 1
    )


def test_repeated_startup_hangs_exhaust_the_restart_budget() -> None:
    """Restart bookkeeping is intact: a hang is counted like a crash.

    Every child hangs at startup. Six launches (the original plus five
    restarts), each stopped once at its own 300s deadline and never
    escalated, then the policy gives up with exit code 1. 300s of uptime
    is under the 600s healthy-run window, so nothing is forgiven.
    """

    clock = _SimulatedTime()
    children: list[Any] = [_HangingChild(clock=clock) for _ in range(6)]
    launched = list(children)

    supervisor, event, environments = _heartbeat_supervisor(
        clock,
        children,
        heartbeat_mtime=lambda path: None,
    )

    assert supervisor.run() == 1

    assert len(environments) == 6
    assert [env[ENV_RESTART_COUNT] for env in environments] == [
        "0", "1", "2", "3", "4", "5",
    ]
    assert all(child.signals == [atlas_supervisor.STOP_SIGNAL] for child in launched)
    assert all(child.terminate_calls == 0 for child in launched)

    backoffs = [wait for wait in event.waits if wait != atlas_supervisor.POLL_INTERVAL_SECONDS]
    assert backoffs == [0.001, 0.002, 0.003, 0.004, 0.005]


# ---------------------------------------------------------------------
# The pre-launch delete, against a real file
# ---------------------------------------------------------------------


def test_a_leftover_heartbeat_file_is_deleted_before_each_launch(
    tmp_path: Path,
) -> None:
    heartbeat = tmp_path / atlas_supervisor.HEARTBEAT_FILE_NAME
    heartbeat.write_text("{}", encoding="utf-8")

    present_at_launch: list[bool] = []

    def launch(environment: dict[str, str]) -> Any:
        present_at_launch.append(heartbeat.exists())
        # The child writes one, as a real one would, before exiting.
        heartbeat.write_text("{}", encoding="utf-8")
        return _FakeChild(1 if len(present_at_launch) == 1 else 0)

    supervisor = ProcessSupervisor(
        policy=_QUICK_RESTARTS,
        launch=launch,
        monotonic=lambda: 0.0,
        heartbeat_file=heartbeat,
        heartbeat_policy=_HEARTBEAT_POLICY,
    )
    supervisor._stop_event = _RecordingEvent()

    assert supervisor.run() == 0
    assert present_at_launch == [False, False]


def test_a_failed_pre_launch_delete_is_logged_and_the_launch_proceeds(
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.INFO, logger=atlas_supervisor.LOGGER_NAME)

    launched: list[int] = []

    supervisor = ProcessSupervisor(
        launch=lambda environment: launched.append(1) or _FakeChild(0),
        monotonic=lambda: 0.0,
        heartbeat_file=tmp_path / atlas_supervisor.HEARTBEAT_FILE_NAME,
        heartbeat_policy=_HEARTBEAT_POLICY,
        heartbeat_discard=_refuse_delete,
    )

    assert supervisor.run() == 0
    assert launched == [1]
    assert any(
        "Could not delete the previous heartbeat file" in m
        and "PermissionError" in m
        for m in _messages(caplog, logging.WARNING)
    )


def test_the_real_mtime_reader_reports_change_exactly(tmp_path: Path) -> None:
    """The default reader: None when absent, integer ns, new on rewrite."""

    heartbeat = tmp_path / atlas_supervisor.HEARTBEAT_FILE_NAME

    assert atlas_supervisor._read_heartbeat_mtime(heartbeat) is None

    heartbeat.write_text("{}", encoding="utf-8")
    first = atlas_supervisor._read_heartbeat_mtime(heartbeat)

    assert isinstance(first, int)

    os.utime(heartbeat, ns=(first + 1_000_000_000, first + 1_000_000_000))

    assert atlas_supervisor._read_heartbeat_mtime(heartbeat) != first


# ---------------------------------------------------------------------
# MEDIUM-3: a disabled detector says why
# ---------------------------------------------------------------------


@pytest.mark.parametrize(
    ("configure", "reason"),
    [
        ("unset", "UNSET"),
        ("relative", "RELATIVE"),
        ("missing", "NOT_A_DIRECTORY"),
        ("file", "NOT_A_DIRECTORY"),
    ],
)
def test_disabled_detection_warns_with_its_case_and_path(
    configure: str,
    reason: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.INFO, logger=atlas_supervisor.LOGGER_NAME)

    if configure == "unset":
        monkeypatch.delenv(LOG_DIRECTORY_ENV, raising=False)
        expected_path = None
    elif configure == "relative":
        monkeypatch.setenv(LOG_DIRECTORY_ENV, "relative_logs")
        expected_path = Path("relative_logs").absolute()
    elif configure == "missing":
        expected_path = tmp_path / "does_not_exist"
        monkeypatch.setenv(LOG_DIRECTORY_ENV, str(expected_path))
    else:
        expected_path = tmp_path / "a_file"
        expected_path.write_text("", encoding="utf-8")
        monkeypatch.setenv(LOG_DIRECTORY_ENV, str(expected_path))

    supervisor = ProcessSupervisor(
        launch=lambda environment: _FakeChild(0),
        monotonic=lambda: 0.0,
    )

    assert supervisor.heartbeat_file is None
    assert supervisor.heartbeat_resolution.disabled_reason == reason
    assert supervisor.heartbeat_resolution.rejected_directory == expected_path

    assert supervisor.run() == 0

    warnings = _messages(caplog, logging.WARNING)
    assert len(warnings) == 1
    assert "Hung-child detection is OFF" in warnings[0]
    assert f"reason={reason}" in warnings[0]
    assert f"{LOG_DIRECTORY_ENV}={expected_path}" in warnings[0]


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


# Heartbeats for its first 1.5s, then keeps ticking (so it can still take a
# signal) but stops writing - a live child whose heartbeat has gone stale.
# The relaunch, told restart_count=1, exits cleanly at once.
_CHILD_HEARTBEAT_THEN_FREEZE = '''
import os
import signal
import sys
import threading
import time

if int(os.environ["ATLAS_SUPERVISOR_RESTART_COUNT"]) >= 1:
    raise SystemExit(0)

heartbeat = os.environ["ATLAS_SUPERVISOR_HEARTBEAT_FILE"]
marker = sys.argv[1]
stop = threading.Event()
signal.signal(signal.SIGBREAK, lambda number, frame: stop.set())

started = time.monotonic()
while not stop.is_set() and time.monotonic() - started < 60:
    if time.monotonic() - started < 1.5:
        with open(heartbeat, "w", encoding="utf-8") as handle_out:
            handle_out.write("{}")
    stop.wait(0.1)

with open(marker, "w", encoding="utf-8") as handle_out:
    handle_out.write("flushed")

raise SystemExit(0)
'''


@WINDOWS_ONLY
def test_a_real_child_with_a_stale_heartbeat_is_stopped_and_restarted(
    tmp_path: Path,
) -> None:
    """Hung-child detection end to end, on the real clock and filesystem.

    A heartbeat file from an "earlier run" is present beforehand and must be
    deleted before launch; the real child then heartbeats, freezes, is
    stopped with one real CTRL_BREAK (and flushes), and is relaunched.
    """

    script = _write_child(
        tmp_path,
        _CHILD_HEARTBEAT_THEN_FREEZE,
        "atlas_child_heartbeat_then_freeze.py",
    )
    marker = tmp_path / "flushed.txt"
    heartbeat = tmp_path / atlas_supervisor.HEARTBEAT_FILE_NAME
    heartbeat.write_text("{}", encoding="utf-8")

    leftover_present_at_launch: list[bool] = []
    processes: list[subprocess.Popen] = []

    def launch(environment: dict[str, str]) -> subprocess.Popen:
        leftover_present_at_launch.append(heartbeat.exists())
        process = subprocess.Popen(
            [sys.executable, str(script), str(marker)],
            env=environment,
            creationflags=atlas_supervisor.CREATION_FLAGS,
        )
        processes.append(process)
        return process

    supervisor = ProcessSupervisor(
        policy=RestartPolicy(
            max_attempts=5,
            backoff_seconds=(0.01,) * 5,
            healthy_run_seconds=600.0,
        ),
        launch=launch,
        heartbeat_file=heartbeat,
        heartbeat_policy=HeartbeatPolicy(
            stale_after_seconds=1.0,
            startup_grace_seconds=5.0,
            first_heartbeat_deadline_seconds=20.0,
            check_interval_seconds=0.2,
        ),
    )

    try:
        assert supervisor.run() == 0
    finally:
        for process in processes:
            if process.poll() is None:
                process.kill()
                process.wait(timeout=30)

    assert leftover_present_at_launch[0] is False
    assert len(processes) == 2
    # Stopped through its handler (the flush ran), then relaunched and
    # exited cleanly.
    assert [process.returncode for process in processes] == [0, 0]
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
