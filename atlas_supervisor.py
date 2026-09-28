"""
============================================================
PROJECT ATLAS AI — PROCESS SUPERVISOR v1.0
============================================================

Parent process that keeps the merged Atlas runtime running.

``atlas_service.py`` is one process with one exit-code authority: 0 means a
clean, deliberate stop and anything else means a fault. This module is the
thing that acts on that distinction - it launches Atlas as a child, waits,
and restarts it under a bounded policy when it exits abnormally.

Launch model
------------
Console-launched only. An operator opens a terminal and starts this module;
there is no boot-time, Session 0, or headless auto-start here, and nothing
below is built toward one. That is a deliberate owner decision, not an
omission: a console is what makes ``CTRL_BREAK_EVENT`` deliverable, and a
console-less launch would need a different stop mechanism entirely.

Why a child process rather than an in-process runtime
-----------------------------------------------------
``main.py`` is the only module allowed to construct AtlasApplication
(tests/architecture/test_composition_root_is_unique.py). Supervising a
*subprocess* keeps that true: this module imports nothing from Atlas at
all - not even for logging - and constructs nothing. It also means a
supervisor defect cannot corrupt runtime state, because it has no access
to any: its entire contract with Atlas is an exit code and a signal.

The small logging setup below is deliberately not imported from
``main.configure_logging``. Importing it would pull the whole composition
root, and every adapter beneath it, into the watchdog process - trading
that isolation away for a dozen lines of stdlib boilerplate.

Stopping the child
------------------
The child is started with ``CREATE_NEW_PROCESS_GROUP``, which is what makes
it addressable: ``CTRL_BREAK_EVENT`` can be sent to that group alone.
Windows offers no way to send SIGINT to another process, so Ctrl+Break is
the only graceful stop available - see
``AtlasProcess.install_signal_handlers``, which registers SIGBREAK for
exactly this.

Exactly one graceful signal is ever sent. ``AtlasProcess._handle_signal``
early-returns once its shutdown event is set, so a second signal would be
silently ignored and would only look like an escalation without being one.
Escalation is therefore ``terminate()`` then ``kill()``, never a repeat
signal.

The same grouping is why an operator's Ctrl+C needs forwarding: a child in a
new process group has Ctrl+C handling disabled, so the console event reaches
this supervisor and not Atlas. Left alone that would orphan a running
runtime, so the stop path below always signals the child explicitly.

Hung-child detection
--------------------
A child that is alive but stuck - not exiting, not ticking its own main
loop - is detected through a heartbeat file, not by polling the operator
surface (that would pull an HTTP/domain dependency into a module that
otherwise imports nothing from Atlas). ``main.AtlasProcess.run_forever``
overwrites the file once per tick when it is told where to write it (see
``ENV_HEARTBEAT_FILE`` below); this supervisor watches only the file's
mtime, which keeps the isolation this module's docstring describes above
intact - it never reads the file's contents, never imports anything to
interpret it, and the detection is bare process/thread liveness, not a
judgement about trading progress (that already belongs to MarketLoop's own
staleness reporting and deliberately never gates health()). It proves only
that the child's main thread is alive; progress-based liveness is a
deliberately deferred, owner-accepted limitation.

The mtime is only ever compared with an earlier mtime, for *change*, and
never with a clock. A heartbeat counts as seen when the mtime differs from
the snapshot taken just before the child was launched; every age this
module computes is on the monotonic clock, measured from the moment such a
change was observed. Two consequences follow, and both are the point:

* A heartbeat file left behind by an earlier run can never make a new
  child look alive (or, once its mtime ages, look hung): it is deleted
  best-effort before each launch, and if that delete fails, its unchanged
  mtime still does not count.
* A wall-clock jump in either direction cannot cause a kill. The child
  stamps the file on the wall clock, but only the fact that the stamp
  changed is used, and "how long ago" is measured on the monotonic clock.

A child that has produced no heartbeat is STARTING inside
``startup_grace_seconds`` (nothing is done), then NO_HEARTBEAT_YET until
``first_heartbeat_deadline_seconds`` (one warning, no kill), and past that
deadline it is stopped as hung at startup. Once a heartbeat has been seen
the child is RUNNING, and it is stopped as hung only when no further
change has been observed for ``stale_after_seconds``.

The heartbeat root is ``ATLAS_LOG_DIRECTORY`` (ADR-0007's off-OneDrive
telemetry root), read directly rather than imported from
``core.application.resolve_log_directory`` - the same "reads its own copy
of the environment, imports nothing from Atlas" contract as the rest of
this module. An unset or invalid value disables hung-child detection
entirely rather than failing the supervisor: unlike the durable state
roots, a missing heartbeat root costs nothing but this one optional check,
so it fails open, not closed - loudly, with a WARNING naming which case
applies.

A detected hang is stopped exactly like a real exit would be - through
``stop_child()`` - and then folded into the same restart bookkeeping as an
abnormal exit, so the backoff/give-up policy above applies to a hang
exactly as it already does to a crash.

============================================================
"""

from __future__ import annotations

import logging
import os
import signal
import subprocess
import sys
import threading
import time
import uuid

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any


LOGGER_NAME = "AtlasAI.Supervisor"

logger = logging.getLogger(LOGGER_NAME)


REPOSITORY_ROOT = Path(__file__).resolve().parent

# The supervised process: the merged Core + operator surface.
CHILD_SCRIPT = REPOSITORY_ROOT / "atlas_service.py"

# A clean, deliberate stop. Never restarted - restarting it would turn every
# operator-requested shutdown into an infinite loop.
CLEAN_EXIT_CODE = 0

# Provenance handed to the child. Read back by AtlasApplication.health(), so
# an operator can see that Atlas is supervised and how many times this
# supervisor has already restarted it.
ENV_EPOCH = "ATLAS_SUPERVISOR_EPOCH"
ENV_RESTART_COUNT = "ATLAS_SUPERVISOR_RESTART_COUNT"

# Told to the child only when hung-child detection is active, so
# main.AtlasProcess knows where to write its liveness heartbeat. Absent
# means "no heartbeat file configured" for both sides, independently -
# the child then writes nothing and this supervisor never checks staleness.
ENV_HEARTBEAT_FILE = "ATLAS_SUPERVISOR_HEARTBEAT_FILE"

# Same string as core.application.LOG_DIRECTORY_ENV, defined independently
# here rather than imported - see this module's docstring on why it reads
# its own copy of the environment instead of depending on Atlas.
LOG_DIRECTORY_ENV = "ATLAS_LOG_DIRECTORY"

HEARTBEAT_FILE_NAME = "supervisor_heartbeat.json"

# Windows-only, and both absent on POSIX. Resolved here so the module stays
# importable anywhere while the behaviour below remains Windows-specific.
CREATION_FLAGS = getattr(
    subprocess,
    "CREATE_NEW_PROCESS_GROUP",
    0,
)

STOP_SIGNAL = getattr(
    signal,
    "CTRL_BREAK_EVENT",
    getattr(signal, "SIGTERM", signal.SIGINT),
)

# How long a graceful stop is given before escalation. Atlas's own shutdown
# is bounded by signal-delivery latency (run_forever polls on a one-second
# tick), the web server join (20s), and AtlasApplication.stop() flushing
# financial state. This must comfortably exceed their sum: escalating early
# would kill the process during the flush, which is the exact failure the
# SIGBREAK handler exists to prevent.
GRACEFUL_STOP_TIMEOUT_SECONDS = 45.0

# After escalation. On Windows terminate() and kill() are the same call
# (TerminateProcess); the pair is kept because it is correct on POSIX too and
# costs one extra wait at most.
TERMINATE_GRACE_SECONDS = 5.0

# How often the child is checked for exit while it runs.
POLL_INTERVAL_SECONDS = 0.25


# ============================================================
# RESTART POLICY
# ============================================================


@dataclass(frozen=True)
class RestartPolicy:
    """When Atlas may be restarted, how long to wait, and when to give up.

    Pure decision logic with no clock and no I/O, so every boundary below is
    testable directly rather than by waiting minutes for one.
    """

    # Five restarts, then stop. An unexplained repeated crash is a condition
    # for an operator, not something to retry forever: past this point the
    # restarts are no longer recovering anything, they are only hiding that
    # nobody has looked.
    max_attempts: int = 5

    # Atlas startup connects to an exchange and loads every durable store, so
    # a sub-five-second retry storm would hammer the venue and churn the
    # stores. The 300s ceiling still lets a network outage recover unattended.
    backoff_seconds: tuple[float, ...] = (5.0, 15.0, 45.0, 120.0, 300.0)

    # How long the child must run before its crash counts as a fresh
    # incident. MarketLoop's default interval is 10s, so this is roughly 60
    # loop iterations - evidence the runtime reached steady state rather than
    # merely finishing startup.
    #
    # Deliberately greater than the largest backoff: if it were not, a slow
    # crash-loop could reset its own counter simply by sitting in backoff,
    # and the give-up rule would never be reached.
    healthy_run_seconds: float = 600.0

    def __post_init__(self) -> None:
        if self.max_attempts < 1:
            raise ValueError("max_attempts must be at least 1")

        if len(self.backoff_seconds) < self.max_attempts:
            raise ValueError(
                "backoff_seconds must cover every attempt "
                f"({len(self.backoff_seconds)} < {self.max_attempts})"
            )

        if self.healthy_run_seconds <= max(self.backoff_seconds):
            raise ValueError(
                "healthy_run_seconds must exceed the largest backoff, or a "
                "slow crash-loop can reset its own attempt counter"
            )

    def exhausted(self, attempt: int) -> bool:
        """True when ``attempt`` is past the last restart allowed."""

        return attempt > self.max_attempts

    def backoff_for(self, attempt: int) -> float:
        """Seconds to wait before restart number ``attempt`` (1-based)."""

        if attempt < 1:
            raise ValueError("attempt is 1-based")

        index = min(
            attempt,
            len(self.backoff_seconds),
        ) - 1

        return self.backoff_seconds[index]

    def resets_counter(self, run_seconds: float) -> bool:
        """True when a run was long enough to forgive earlier attempts."""

        return run_seconds >= self.healthy_run_seconds


# ============================================================
# HEARTBEAT POLICY
# ============================================================


@dataclass(frozen=True)
class HeartbeatPolicy:
    """When a live child with a stale heartbeat counts as hung.

    Pure decision logic with no clock and no I/O, same testing rationale as
    RestartPolicy above.
    """

    # Comfortably above the child's 1s tick (main.AtlasProcess.run_forever)
    # so ordinary scheduler jitter or a slow GC pause is never mistaken for
    # a hang. Short enough that a genuine deadlock is still caught well
    # inside a single operator shift.
    stale_after_seconds: float = 30.0

    # Startup connects to an exchange and loads every durable store before
    # run_forever's loop ever ticks once - the same cost
    # GRACEFUL_STOP_TIMEOUT_SECONDS's comment describes for shutdown. A
    # child with no heartbeat yet is left entirely alone for this long
    # after launch (monotonic), so a slow-but-healthy startup is never
    # mistaken for a hang.
    startup_grace_seconds: float = 120.0

    # Past the grace a child with no heartbeat yet is only warned about;
    # past this (also measured from launch) it is stopped as hung at
    # startup. The gap is deliberate: a slow start is far more likely than
    # a hung one, and a wrong kill here feeds the restart budget.
    first_heartbeat_deadline_seconds: float = 300.0

    # How often the heartbeat file is actually re-read. Must not be checked
    # on every 0.25s poll tick; that would mean nothing but wasted stat()
    # calls between real staleness verdicts.
    check_interval_seconds: float = 5.0

    def __post_init__(self) -> None:
        for name, value in (
            ("stale_after_seconds", self.stale_after_seconds),
            ("startup_grace_seconds", self.startup_grace_seconds),
            (
                "first_heartbeat_deadline_seconds",
                self.first_heartbeat_deadline_seconds,
            ),
            ("check_interval_seconds", self.check_interval_seconds),
        ):
            if value <= 0:
                raise ValueError(f"{name} must be positive")

        if self.check_interval_seconds >= self.stale_after_seconds:
            raise ValueError(
                "check_interval_seconds must be smaller than "
                "stale_after_seconds, or a hang could sit undetected for "
                "an extra full staleness window"
            )

        if (
            self.first_heartbeat_deadline_seconds
            <= self.startup_grace_seconds
        ):
            raise ValueError(
                "first_heartbeat_deadline_seconds must exceed "
                "startup_grace_seconds, or a slow start is killed without "
                "ever being warned about"
            )

    def is_stale(self, *, now: float, heartbeat_at: float) -> bool:
        """True when a heartbeat last seen at ``heartbeat_at`` is stale.

        Both times are monotonic seconds: ``heartbeat_at`` is when this
        supervisor observed the heartbeat file's mtime *change*, never the
        mtime itself, which is stamped on the wall clock and has no fixed
        relationship to the monotonic one.
        """

        return (now - heartbeat_at) >= self.stale_after_seconds

    def startup_phase(self, *, since_launch: float) -> str:
        """Where a child that has produced no heartbeat yet stands.

        ``since_launch`` is monotonic seconds since the child was started.
        Only meaningful before a first heartbeat has been seen; after that
        the child is RUNNING and is judged by is_stale() alone.
        """

        if since_launch < self.startup_grace_seconds:
            return PHASE_STARTING

        if since_launch < self.first_heartbeat_deadline_seconds:
            return PHASE_NO_HEARTBEAT_YET

        return PHASE_HUNG_AT_STARTUP


# The heartbeat states a live child moves through. Plain strings so a log
# line or a test can name them directly.
PHASE_STARTING = "STARTING"
PHASE_NO_HEARTBEAT_YET = "NO_HEARTBEAT_YET"
PHASE_HUNG_AT_STARTUP = "HUNG_AT_STARTUP"
PHASE_RUNNING = "RUNNING"
PHASE_STALE = "STALE"

# Why hung-child detection is off, when it is. Named in the startup WARNING
# so an operator can tell a forgotten variable from a mistyped one.
HEARTBEAT_DISABLED_UNSET = "UNSET"
HEARTBEAT_DISABLED_RELATIVE = "RELATIVE"
HEARTBEAT_DISABLED_NOT_A_DIRECTORY = "NOT_A_DIRECTORY"
HEARTBEAT_DISABLED_BY_CALLER = "DISABLED_BY_CALLER"


@dataclass(frozen=True)
class HeartbeatResolution:
    """The heartbeat file to watch, or why there is none."""

    path: Path | None
    disabled_reason: str | None = None
    # The directory the environment named, as resolved, when it was
    # rejected - for the WARNING, so the operator sees what was checked.
    rejected_directory: Path | None = None


def _resolve_heartbeat_file() -> HeartbeatResolution:
    """Return this run's heartbeat file, or why the check is disabled.

    Deliberately fails open: an unset or unusable ATLAS_LOG_DIRECTORY costs
    nothing but this one optional check, unlike the durable state roots in
    core.application, where the same situation must fail closed. Nothing is
    created here; the child creates the file itself on its first tick.
    """

    raw = os.environ.get(LOG_DIRECTORY_ENV)

    if not raw or not raw.strip():
        return HeartbeatResolution(
            path=None,
            disabled_reason=HEARTBEAT_DISABLED_UNSET,
        )

    directory = Path(raw.strip()).expanduser()

    if not directory.is_absolute():
        return HeartbeatResolution(
            path=None,
            disabled_reason=HEARTBEAT_DISABLED_RELATIVE,
            rejected_directory=directory.absolute(),
        )

    if not directory.is_dir():
        return HeartbeatResolution(
            path=None,
            disabled_reason=HEARTBEAT_DISABLED_NOT_A_DIRECTORY,
            rejected_directory=directory,
        )

    return HeartbeatResolution(path=directory / HEARTBEAT_FILE_NAME)


def _read_heartbeat_mtime(path: Path) -> int | None:
    """Return a heartbeat file's mtime in nanoseconds, or None if unreadable.

    The value is only ever compared with an earlier one for equality, never
    with a clock, so the integer nanosecond form is used: exact, with no
    float rounding that could make two distinct writes compare equal.

    None reads as "nothing observed" - the same "unknown never flips the
    verdict on its own" convention AtlasApplication.health() already
    applies to thread liveness - never as evidence of a heartbeat.
    """

    try:
        return path.stat().st_mtime_ns
    except OSError:
        return None


def _discard_heartbeat_file(path: Path) -> None:
    """Delete a heartbeat file left by an earlier run. Raises OSError."""

    path.unlink(missing_ok=True)


# Marks a constructor argument as "not provided" where None is already a
# meaningful, distinct value the caller can pass explicitly (see
# ProcessSupervisor.__init__'s heartbeat_file parameter).
_UNSET = object()


@dataclass(frozen=True)
class _Hung:
    """_await_exit's verdict for a live child judged hung.

    Distinct from both an int exit code and None (which already means
    "operator stop requested").
    """

    # PHASE_HUNG_AT_STARTUP or PHASE_STALE.
    phase: str

    # Monotonic seconds since the last heartbeat change was seen, or None
    # when none was ever seen (hung at startup).
    heartbeat_age: float | None

    since_launch: float

# A synthetic exit code fed into the same restart bookkeeping a real
# abnormal exit uses. Never CLEAN_EXIT_CODE, and chosen distinct from any
# value a real Windows process reports (always >= 0) so a log line
# inspecting the code can tell the two apart.
_HUNG_EXIT_CODE = -1


# ============================================================
# SUPERVISOR
# ============================================================


class ProcessSupervisor:
    """Runs Atlas as a child process and restarts it under ``policy``.

    The clock and the launcher are injected so the policy above can be
    exercised at its boundaries without waiting them out in real time.
    Signal delivery and process teardown are deliberately *not* abstracted:
    those are the parts that are silently wrong until run for real.
    """

    VERSION = "1.0"

    def __init__(
        self,
        *,
        policy: RestartPolicy | None = None,
        launch: Callable[[dict[str, str]], Any] | None = None,
        monotonic: Callable[[], float] | None = None,
        epoch: str | None = None,
        heartbeat_policy: HeartbeatPolicy | None = None,
        heartbeat_file: Path | None = _UNSET,
        heartbeat_mtime: Callable[[Path], Any] | None = None,
        heartbeat_discard: Callable[[Path], None] | None = None,
    ) -> None:
        self.policy = policy if policy is not None else RestartPolicy()
        self.launch = launch if launch is not None else _launch_atlas_service
        self.monotonic = monotonic if monotonic is not None else time.monotonic

        self.epoch = epoch if epoch is not None else uuid.uuid4().hex

        self.child: Any | None = None
        self.restart_count = 0
        self.stop_reason = ""

        self.heartbeat_policy = (
            heartbeat_policy if heartbeat_policy is not None else HeartbeatPolicy()
        )

        # heartbeat_file has three distinct states an ordinary "or a
        # default" default cannot express: not provided (resolve it from
        # ATLAS_LOG_DIRECTORY, the real production behaviour), explicitly
        # None (detection off, what every existing scripted-clock test
        # wants), or an explicit path (what a heartbeat-specific test
        # wants). _UNSET is the only thing that triggers resolution.
        if heartbeat_file is _UNSET:
            self.heartbeat_resolution = _resolve_heartbeat_file()
        elif heartbeat_file is None:
            self.heartbeat_resolution = HeartbeatResolution(
                path=None,
                disabled_reason=HEARTBEAT_DISABLED_BY_CALLER,
            )
        else:
            self.heartbeat_resolution = HeartbeatResolution(path=heartbeat_file)

        self.heartbeat_file: Path | None = self.heartbeat_resolution.path

        # The mtime reader's values are only compared for change, never
        # against any clock - see this module's docstring.
        self.heartbeat_mtime = (
            heartbeat_mtime if heartbeat_mtime is not None else _read_heartbeat_mtime
        )
        self.heartbeat_discard = (
            heartbeat_discard
            if heartbeat_discard is not None
            else _discard_heartbeat_file
        )

        # Doubles as the backoff sleep, so an operator stop during a
        # five-minute wait is acted on immediately rather than five minutes
        # later.
        self._stop_event = threading.Event()

    # --------------------------------------------------------
    # SIGNALS
    # --------------------------------------------------------

    def install_signal_handlers(self) -> None:
        """Register operating-system termination handlers.

        Same shape as AtlasProcess: handlers record intent and never perform
        shutdown work, so the main loop stays the only thing that stops a
        child.
        """

        signal.signal(
            signal.SIGINT,
            self._handle_signal,
        )

        for name in ("SIGTERM", "SIGBREAK"):
            if hasattr(signal, name):
                signal.signal(
                    getattr(signal, name),
                    self._handle_signal,
                )

    def _handle_signal(
        self,
        signal_number: int,
        frame: Any,
    ) -> None:
        del frame

        if self._stop_event.is_set():
            return

        try:
            signal_name = signal.Signals(signal_number).name
        except ValueError:
            signal_name = str(signal_number)

        self.stop_reason = f"Operating-system signal: {signal_name}"

        logger.warning(
            "Supervisor shutdown requested: %s",
            self.stop_reason,
        )

        self._stop_event.set()

    def request_stop(self) -> None:
        """Ask the supervisor to stop its child and exit."""

        if not self._stop_event.is_set():
            self.stop_reason = self.stop_reason or "Stop requested"
            self._stop_event.set()

    # --------------------------------------------------------
    # CHILD LIFECYCLE
    # --------------------------------------------------------

    def _child_environment(self) -> dict[str, str]:
        environment = dict(os.environ)

        environment[ENV_EPOCH] = self.epoch
        environment[ENV_RESTART_COUNT] = str(self.restart_count)

        if self.heartbeat_file is not None:
            environment[ENV_HEARTBEAT_FILE] = str(self.heartbeat_file)

        return environment

    def _start_child(self) -> Any:
        logger.info(
            "Starting Atlas | epoch=%s restart_count=%s",
            self.epoch,
            self.restart_count,
        )

        child = self.launch(
            self._child_environment()
        )

        self.child = child

        return child

    def _prepare_heartbeat(self) -> Any:
        """Clear the previous run's heartbeat and snapshot what remains.

        Called immediately before each launch when detection is active.
        The delete is best-effort: a heartbeat left behind by an earlier
        run would otherwise make a healthy-but-slow new child look alive
        and then hung. If it cannot be deleted, the snapshot returned here
        still neutralises it - only an mtime that *differs* from this
        snapshot counts as a heartbeat from the new child.
        """

        try:
            self.heartbeat_discard(self.heartbeat_file)
        except OSError as exc:
            logger.warning(
                "Could not delete the previous heartbeat file %s (%s); "
                "continuing - its unchanged mtime will not count as a "
                "heartbeat from the new child",
                self.heartbeat_file,
                type(exc).__name__,
            )

        return self.heartbeat_mtime(self.heartbeat_file)

    def _await_exit(
        self,
        child: Any,
        started_at: float,
        heartbeat_baseline: Any = None,
    ) -> int | None | _Hung:
        """Wait for the child to exit, to be requested to stop, or to hang.

        Returns the child's exit code, None when a stop interrupted the
        wait (the caller stops the child itself in that case), or a _Hung
        verdict when a configured heartbeat says the live child is hung.

        Polling rather than a blocking wait: on Windows a blocking wait is
        not interrupted by a console control event, so a blocked supervisor
        would ignore the operator's Ctrl+C until Atlas happened to exit.

        ``started_at`` is self.monotonic() at launch, and every age below is
        on that same clock. ``heartbeat_baseline`` is the heartbeat mtime
        snapshotted just before launch (see _prepare_heartbeat); it is only
        ever compared for change.
        """

        policy = self.heartbeat_policy

        last_mtime = heartbeat_baseline
        last_change_at: float | None = None
        last_check_at: float | None = None
        warned_no_heartbeat = False
        warned_unreadable = False

        while True:
            if self._stop_event.is_set():
                return None

            returncode = child.poll()

            if returncode is not None:
                return int(returncode)

            if self.heartbeat_file is not None:
                now = self.monotonic()

                due_for_check = (
                    last_check_at is None
                    or now - last_check_at >= policy.check_interval_seconds
                )

                if due_for_check:
                    last_check_at = now
                    since_launch = now - started_at

                    mtime = self.heartbeat_mtime(self.heartbeat_file)

                    if mtime is not None and mtime != last_mtime:
                        if last_change_at is None:
                            logger.info(
                                "First heartbeat from Atlas after %.1fs",
                                since_launch,
                            )
                        elif warned_unreadable:
                            logger.info(
                                "Heartbeat file readable again"
                            )

                        last_mtime = mtime
                        last_change_at = now
                        warned_unreadable = False

                    if last_change_at is None:
                        phase = policy.startup_phase(
                            since_launch=since_launch,
                        )

                        if phase == PHASE_HUNG_AT_STARTUP:
                            return _Hung(
                                phase=PHASE_HUNG_AT_STARTUP,
                                heartbeat_age=None,
                                since_launch=since_launch,
                            )

                        if (
                            phase == PHASE_NO_HEARTBEAT_YET
                            and not warned_no_heartbeat
                        ):
                            warned_no_heartbeat = True

                            logger.warning(
                                "No heartbeat from Atlas yet after %.0fs "
                                "(startup_grace=%.0fs); it will be stopped "
                                "as hung at startup if none arrives by "
                                "%.0fs after launch",
                                since_launch,
                                policy.startup_grace_seconds,
                                policy.first_heartbeat_deadline_seconds,
                            )

                    elif mtime is None:
                        # RUNNING, but the file cannot be read right now.
                        # Unknown is not evidence of a hang: no verdict
                        # until it can be read again.
                        if not warned_unreadable:
                            warned_unreadable = True

                            logger.warning(
                                "Heartbeat file %s unreadable; hung-child "
                                "detection paused until it can be read",
                                self.heartbeat_file,
                            )

                    elif policy.is_stale(
                        now=now,
                        heartbeat_at=last_change_at,
                    ):
                        return _Hung(
                            phase=PHASE_STALE,
                            heartbeat_age=now - last_change_at,
                            since_launch=since_launch,
                        )

            self._stop_event.wait(
                timeout=POLL_INTERVAL_SECONDS
            )

    def stop_child(self, child: Any) -> int | None:
        """Stop the child gracefully, escalating only if it will not go.

        Never raises, and never sends a second graceful signal: the child
        ignores one once its shutdown is already under way, so a repeat would
        look like an escalation without being one.
        """

        if child.poll() is not None:
            return _returncode_of(child)

        logger.info(
            "Stopping Atlas gracefully | signal=%s timeout=%ss",
            getattr(STOP_SIGNAL, "name", STOP_SIGNAL),
            GRACEFUL_STOP_TIMEOUT_SECONDS,
        )

        try:
            child.send_signal(STOP_SIGNAL)
        except Exception:
            logger.exception(
                "Could not signal Atlas; escalating directly"
            )
        else:
            try:
                return int(
                    child.wait(
                        timeout=GRACEFUL_STOP_TIMEOUT_SECONDS
                    )
                )
            except subprocess.TimeoutExpired:
                logger.error(
                    "Atlas did not stop within %ss of the graceful signal; "
                    "escalating to termination. The financial-state flush "
                    "may not have completed.",
                    GRACEFUL_STOP_TIMEOUT_SECONDS,
                )

        return self._escalate(child)

    def _escalate(self, child: Any) -> int | None:
        """Terminate, then kill. On Windows these are the same call."""

        for step in ("terminate", "kill"):
            action = getattr(child, step, None)

            if not callable(action):
                continue

            try:
                action()
            except Exception:
                logger.exception(
                    "Atlas %s failed",
                    step,
                )

            try:
                return int(
                    child.wait(
                        timeout=TERMINATE_GRACE_SECONDS
                    )
                )
            except subprocess.TimeoutExpired:
                continue
            except Exception:
                logger.exception(
                    "Waiting for Atlas after %s failed",
                    step,
                )
                break

        logger.error(
            "Atlas could not be stopped"
        )

        return _returncode_of(child)

    # --------------------------------------------------------
    # MAIN LOOP
    # --------------------------------------------------------

    def _release_child(self) -> None:
        """Stop any child still held, on every way out of the loop.

        This supervisor is the only thing holding the Atlas process. If it
        leaves while a child is live, Atlas keeps running with nobody
        watching it and its durable financial state still open - the exact
        outcome this package exists to prevent, reached from the other
        direction.

        It runs from a ``finally`` rather than an ``except`` because the
        realistic fault is KeyboardInterrupt: a supervisor used without
        ``install_signal_handlers`` takes one straight through on Ctrl+C,
        and KeyboardInterrupt is a BaseException that ``except Exception``
        does not catch.

        The child still gets the full graceful budget here. A fault in the
        supervisor is no reason to cut short the financial-state flush.
        """

        child = self.child

        if child is None:
            return

        self.child = None

        try:
            self.stop_child(child)
        except Exception:
            logger.exception(
                "Could not stop Atlas while the supervisor was exiting"
            )

    def run(self) -> int:
        """Supervise Atlas until it stops cleanly or the policy gives up.

        Returns 0 when Atlas exited cleanly or an operator stopped it, and 1
        when the restart policy was exhausted. Never returns while a child it
        launched is still running.
        """

        logger.info(
            "Atlas supervisor %s active | epoch=%s",
            self.VERSION,
            self.epoch,
        )

        if self.heartbeat_file is not None:
            logger.info(
                "Hung-child detection active | heartbeat_file=%s "
                "stale_after=%ss startup_grace=%ss "
                "first_heartbeat_deadline=%ss",
                self.heartbeat_file,
                self.heartbeat_policy.stale_after_seconds,
                self.heartbeat_policy.startup_grace_seconds,
                self.heartbeat_policy.first_heartbeat_deadline_seconds,
            )
        else:
            logger.warning(
                "Hung-child detection is OFF | reason=%s %s=%s; Atlas will "
                "still be restarted when it exits, but a hang will NOT be "
                "detected",
                self.heartbeat_resolution.disabled_reason,
                LOG_DIRECTORY_ENV,
                self.heartbeat_resolution.rejected_directory,
            )

        try:
            return self._supervise()
        finally:
            self._release_child()

    def _supervise(self) -> int:
        """The supervision loop itself. See run() for the contract."""

        attempt = 0

        while True:
            heartbeat_baseline = (
                self._prepare_heartbeat()
                if self.heartbeat_file is not None
                else None
            )

            child = self._start_child()

            started_at = self.monotonic()

            returncode = self._await_exit(
                child,
                started_at,
                heartbeat_baseline,
            )

            ran_for = self.monotonic() - started_at

            if returncode is None:
                # Operator stop. The child's own exit code is irrelevant: a
                # requested shutdown is a clean outcome for the supervisor
                # whatever the runtime reports on its way out.
                self.stop_child(child)

                self.child = None

                logger.info(
                    "Atlas supervisor stopped | reason=%s",
                    self.stop_reason or "Stop requested",
                )

                return 0

            was_hung = isinstance(returncode, _Hung)

            if was_hung:
                if returncode.phase == PHASE_HUNG_AT_STARTUP:
                    logger.critical(
                        "Atlas child hung at startup: no heartbeat at all "
                        "within %.0fs of launch (policy "
                        "first_heartbeat_deadline=%.0fs); stopping it and "
                        "treating it as an abnormal exit",
                        returncode.since_launch,
                        self.heartbeat_policy.first_heartbeat_deadline_seconds,
                    )
                else:
                    logger.critical(
                        "Atlas child unresponsive: no heartbeat for %.0fs "
                        "(policy stale_after=%.0fs) after %.1fs of runtime; "
                        "stopping it and treating it as an abnormal exit",
                        returncode.heartbeat_age,
                        self.heartbeat_policy.stale_after_seconds,
                        returncode.since_launch,
                    )

                self.stop_child(child)

                returncode = _HUNG_EXIT_CODE

            self.child = None

            if returncode == CLEAN_EXIT_CODE:
                logger.info(
                    "Atlas exited cleanly after %.1fs; not restarting",
                    ran_for,
                )

                return 0

            if not was_hung:
                logger.error(
                    "Atlas exited abnormally | exit_code=%s after %.1fs",
                    returncode,
                    ran_for,
                )

            # A hang is never a healthy run, however long the child lived
            # before hanging: letting it reset the counter would restart a
            # process that keeps hanging late forever. Only a run that ended
            # on its own may forgive earlier attempts.
            if not was_hung and self.policy.resets_counter(ran_for):
                if attempt:
                    logger.info(
                        "Atlas had run %.1fs (>= %.0fs); "
                        "restart attempts reset",
                        ran_for,
                        self.policy.healthy_run_seconds,
                    )

                attempt = 0

            attempt += 1

            if self.policy.exhausted(attempt):
                logger.critical(
                    "Atlas failed %s times without a healthy run of %.0fs; "
                    "giving up. This needs an operator: the restarts are no "
                    "longer recovering anything.",
                    self.policy.max_attempts,
                    self.policy.healthy_run_seconds,
                )

                return 1

            delay = self.policy.backoff_for(attempt)

            logger.warning(
                "Restarting Atlas in %.0fs | attempt %s of %s",
                delay,
                attempt,
                self.policy.max_attempts,
            )

            if self._stop_event.wait(timeout=delay):
                logger.info(
                    "Atlas supervisor stopped during backoff | reason=%s",
                    self.stop_reason or "Stop requested",
                )

                return 0

            self.restart_count += 1


# ============================================================
# HELPERS
# ============================================================


def _returncode_of(child: Any) -> int | None:
    returncode = getattr(child, "returncode", None)

    return None if returncode is None else int(returncode)


def _launch_atlas_service(
    environment: dict[str, str],
) -> subprocess.Popen:
    """Start the merged Atlas process in its own process group.

    CREATE_NEW_PROCESS_GROUP is what makes CTRL_BREAK_EVENT addressable to
    Atlas alone. It also disables Ctrl+C for the child, which is why the
    supervisor forwards its own console interrupt explicitly rather than
    relying on the console to reach both.
    """

    return subprocess.Popen(
        [sys.executable, str(CHILD_SCRIPT)],
        cwd=str(REPOSITORY_ROOT),
        env=environment,
        creationflags=CREATION_FLAGS,
    )


# ============================================================
# PUBLIC MAIN
# ============================================================


def _configure_logging() -> None:
    """Configure the supervisor's console logger.

    Deliberately duplicates main.configure_logging's format rather than
    importing it - see this module's docstring - and, like it, avoids adding
    a second handler when called more than once in one process.
    """

    root_logger = logging.getLogger()

    root_logger.setLevel(
        logging.INFO
    )

    if root_logger.handlers:
        return

    handler = logging.StreamHandler(
        stream=sys.stdout
    )

    handler.setLevel(
        logging.INFO
    )

    handler.setFormatter(
        logging.Formatter(
            fmt=(
                "%(asctime)s | "
                "%(levelname)-8s | "
                "%(name)s | "
                "%(message)s"
            ),
            datefmt="%Y-%m-%d %H:%M:%S",
        )
    )

    root_logger.addHandler(
        handler
    )


def main() -> int:
    """Atlas supervisor command-line entry point."""

    _configure_logging()

    print()
    print("=" * 64)
    print("PROJECT ATLAS AI — SUPERVISOR")
    print("Restarts Atlas on abnormal exit. Ctrl+C stops both.")
    print("=" * 64)
    print()

    supervisor = ProcessSupervisor()

    supervisor.install_signal_handlers()

    return supervisor.run()


# ============================================================
# SCRIPT ENTRY
# ============================================================


if __name__ == "__main__":
    raise SystemExit(
        main()
    )
