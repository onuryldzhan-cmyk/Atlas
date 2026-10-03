"""
============================================================
PROJECT ATLAS AI — MAIN ENTRY POINT v6.0
============================================================

Institutional Application Entry Point

Responsibilities
----------------
- Configure application logging
- Construct AtlasApplication
- Start the Atlas lifecycle
- Display startup diagnostics
- Keep the main process alive
- Handle Ctrl+C / Ctrl+Break safely
- Handle fatal startup/runtime errors
- Guarantee graceful application shutdown

============================================================
"""

from __future__ import annotations

import json
import logging
import os
import signal
import sys
import threading
import time
import traceback

from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from core.application import DEFAULT_INSTRUMENT_RULES_PATH, AtlasApplication, resolve_state_directory
from core.atlas_config import AtlasConfigError, load_config
from core.execution_manager import PAPER_FEE_RATE_PER_SIDE
from core.audit_event_store import AuditChainIntegrityError
from core import instance_lock
from core.instance_lock import INSTANCE_LOCK_FILE_NAME, InstanceLockHeldError
from core.instrument_rules import InstrumentRulesConfigError, load_instrument_ruleset


LOGGER_NAME = "AtlasAI.Main"

logger = logging.getLogger(LOGGER_NAME)

# Same string as atlas_supervisor.ENV_HEARTBEAT_FILE, defined independently
# here rather than imported - atlas_supervisor.py must import nothing from
# Atlas (see its docstring), so a shared constant module is not an option;
# this is the same cross-process-literal precedent core.application's
# SUPERVISOR_EPOCH_ENV already follows for ENV_EPOCH.
HEARTBEAT_FILE_ENV = "ATLAS_SUPERVISOR_HEARTBEAT_FILE"

# Fixed, not configurable (CFG-001): core/atlas_config.load_config refuses
# any mode but PAPER while live authority is DENIED.
EXECUTION_MODE = "PAPER"

# Registry v5.41 (owner: 20 coins, real data only): Atlas scans and may trade
# exactly the symbols that have a real Binance venue rule in
# config/instrument_rules.json, written only by
# tools/refresh_venue_instrument_rules.py from Binance's exchangeInfo. A coin
# without a real rule is never scanned; nothing is invented.
MAX_TRADE_UNIVERSE = 20


def trade_universe(path: Path | str = DEFAULT_INSTRUMENT_RULES_PATH) -> list[str] | None:
    """The configured symbols, or None to keep MarketLoop's defaults.

    None when the rules file cannot be read: AtlasApplication then loads it
    itself and halts execution fail-closed exactly as before this change.
    """

    try:
        symbols = sorted(load_instrument_ruleset(path).symbols)
    except InstrumentRulesConfigError:
        return None
    if len(symbols) > MAX_TRADE_UNIVERSE:
        raise ValueError(f"{len(symbols)} symbols in {path}: at most {MAX_TRADE_UNIVERSE} (owner decision v5.41)")
    return symbols or None
def apply_policy_manifest(application, path: Path | str | None = None):
    """Phase-2 G1: verify the runtime policy against the manifest; block new risk on any mismatch.

    Read-only towards configuration: the only effect is ExecutionManager's
    policy_manifest_block (new BUYs refused, reduce-only exits per B1).
    """

    from core import policy_manifest

    check = policy_manifest.verify(
        policy_manifest.runtime_policy(application),
        policy_manifest.MANIFEST_PATH if path is None else path,
    )
    application.execution.set_policy_manifest_block(check.block_reason)
    if check.block_new_risk:
        logger.critical("Policy manifest %s: %s - BLOCK_NEW_RISK (exits stay possible) %s",
                        check.status, check.detail, check.to_dict()["mismatches"])
    else:
        logger.info("Policy manifest MATCH (registry %s, proposal %s, owner approval %s)",
                    check.registry_id, check.proposal_id, check.owner_approval)
    return check


# EXP-001 stopped early by the owner on 2026-09-29 (registry v5.71): 16 trades,
# 6/16 winners after fees, gross -74.48, net -99.30; back to the policy floor.
# 2026-10-01: owner switched on EXP-002 ("Sadece EXP-002"), approved by the
# independent audit docs/audits/INDEPENDENT_AUDIT_FUNDING_SENTIMENT_EXP002_2026-10-01.md
# with funding sentiment OFF: MEDIUM only, floor 0.62, 30 admissions, 2026-10-02..16, PAPER.
PAPER_CONFIDENCE_EXPERIMENT = True
PAPER_CONFIDENCE_EXPERIMENT_ID = "EXP-002"

# Minimum spacing between two "heartbeat write failed" announcements, so a
# target that flaps between failing and working cannot flood the log.
HEARTBEAT_FAILURE_LOG_INTERVAL_SECONDS = 300.0

# While AtlasApplication.stop() flushes financial state the main loop no
# longer ticks, so a stop slower than the supervisor's staleness window would
# read as a hang and get the process killed mid-flush. A background writer
# keeps the heartbeat fresh during stop(), but only for this long: a stop()
# that is itself hung must still become visible to the supervisor.
SHUTDOWN_HEARTBEAT_MAX_SECONDS = 120.0
SHUTDOWN_HEARTBEAT_INTERVAL_SECONDS = 1.0

# Registry v5.15 (owner: panel and trading decoupled). With a restart hook,
# a failed or dead operator panel never stops trading; it is retried at
# this interval until it serves again.
SUBORDINATE_RESTART_INTERVAL_SECONDS = 30.0

# Exit codes atlas_supervisor.py must NOT restart on (it keeps its own copy,
# checked equal by tests). A restart cannot fix either condition: corrupted
# durable state fails the same check again, and a second instance on the
# same state root is exactly what corrupts it. Chosen outside what Windows
# and the C runtime produce on their own (abort() exits 3 on Windows).
INTEGRITY_HALT_EXIT_CODE = 75
ALREADY_RUNNING_EXIT_CODE = 76



# ============================================================
# LOGGING
# ============================================================


def configure_logging() -> None:
    """
    Configure the root Atlas console logger.

    This function intentionally avoids adding duplicate handlers when
    main.py is executed more than once in the same Python process.
    """

    root_logger = logging.getLogger()

    root_logger.setLevel(
        logging.INFO
    )

    if root_logger.handlers:
        return

    formatter = logging.Formatter(
        fmt=(
            "%(asctime)s | "
            "%(levelname)-8s | "
            "%(name)s | "
            "%(message)s"
        ),
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    console_handler = logging.StreamHandler(
        stream=sys.stdout
    )

    console_handler.setLevel(
        logging.INFO
    )

    console_handler.setFormatter(
        formatter
    )

    root_logger.addHandler(
        console_handler
    )


# ============================================================
# SAFE VALUE HELPERS
# ============================================================


def safe_dict(
    value: Any,
) -> dict[str, Any]:
    """
    Return a dictionary or an empty dictionary.
    """

    if isinstance(value, dict):
        return value

    return {}


def safe_value(
    source: dict[str, Any],
    key: str,
    default: Any = "UNKNOWN",
) -> Any:
    """
    Safely retrieve a dictionary value.
    """

    return source.get(
        key,
        default,
    )


# ============================================================
# STATUS DISPLAY
# ============================================================


def display_startup_status(
    app: AtlasApplication,
) -> None:
    """
    Print a concise and safe Atlas startup report.
    """

    status = safe_dict(
        app.status()
    )

    application_status = safe_dict(
        status.get("application")
    )

    runtime_status = safe_dict(
        status.get("runtime")
    )

    health_status = safe_dict(
        status.get("health")
    )

    services_status = safe_dict(
        status.get("services")
    )

    print()
    print("=" * 64)
    print("PROJECT ATLAS AI — SYSTEM STATUS")
    print("=" * 64)

    print(
        "Application :",
        safe_value(
            application_status,
            "name",
            "AtlasApplication",
        ),
    )

    print(
        "Version     :",
        safe_value(
            application_status,
            "version",
        ),
    )

    print(
        "Mode        :",
        safe_value(
            application_status,
            "execution_mode",
        ),
    )

    print(
        "Exchange    :",
        safe_value(
            application_status,
            "exchange",
        ),
    )

    print(
        "Running     :",
        safe_value(
            application_status,
            "running",
            False,
        ),
    )

    print(
        "Runtime     :",
        safe_value(
            runtime_status,
            "state",
        ),
    )

    print(
        "Healthy     :",
        safe_value(
            health_status,
            "healthy",
            False,
        ),
    )

    registered_services = services_status.get(
        "registered",
        [],
    )

    started_services = services_status.get(
        "started",
        [],
    )

    print(
        "Registered  :",
        len(registered_services)
        if isinstance(registered_services, list)
        else registered_services,
    )

    print(
        "Started     :",
        (
            ", ".join(started_services)
            if isinstance(started_services, list)
            else started_services
        ),
    )

    print("=" * 64)
    print()


# ============================================================
# MAIN PROCESS CONTROLLER
# ============================================================


class AtlasProcess:
    """
    Controls the Atlas process lifecycle.

    Signal handlers do not perform shutdown work directly. They only set
    the shutdown event so the main thread can stop Atlas safely.

    Composition hooks
    -----------------
    ``on_started`` and ``on_stopping`` let a composition entry point attach
    a second, subordinate component to this process - today the in-process
    web surface built by ``atlas_service.py`` - without moving the lifecycle
    authority out of this class. Both default to ``None``, which reproduces
    the single-component behaviour this class has always had.

    The contract they must satisfy:

    - ``on_started`` runs on the main thread after AtlasApplication has
      started successfully and before ``run_forever()`` begins. It receives
      the live application. Raising from it is a startup failure: the
      exception is handled exactly like any other fatal error, so the
      process still reaches ``stop()`` and still returns a non-zero code.
    - ``on_stopping`` runs inside ``execute()``'s ``finally``, *before*
      AtlasApplication is stopped, so a subordinate component stops
      accepting work that reaches into the runtime before the runtime is
      torn down. It can never prevent ``stop()``: a failure there is
      recorded as a non-zero exit code and swallowed.
    - ``is_subordinate_alive`` is polled by ``run_forever()`` on the same
      one-second tick that already watches ``application.running``. It
      answers one question - is the subordinate component still alive -
      and returning ``False`` is an unexpected stop, handled by the exit
      code 1 path that condition already uses. Returning ``True``, raising,
      or being absent all mean "nothing known to be wrong"; see
      ``_subordinate_alive``.
    """

    VERSION = "1.0"

    def __init__(
        self,
        *,
        on_started: Callable[[AtlasApplication], None] | None = None,
        on_stopping: Callable[[], None] | None = None,
        is_subordinate_alive: Callable[[], bool] | None = None,
        restart_subordinate: Callable[[], None] | None = None,
    ) -> None:
        self.application: AtlasApplication | None = None

        self.on_started = on_started
        self.on_stopping = on_stopping
        self.is_subordinate_alive = is_subordinate_alive
        # When set, the subordinate (the operator panel) is decoupled from
        # trading: a start failure or a death is logged and retried instead
        # of ending the process. When None, the original contract holds.
        self.restart_subordinate = restart_subordinate
        self._subordinate_down = False
        self._subordinate_next_retry_at = 0.0
        self._subordinate_restart_thread: threading.Thread | None = None

        # Latches once so a permanently failing liveness probe cannot fill
        # the runtime log with one traceback per second.
        self._liveness_probe_failed = False

        self.shutdown_event = threading.Event()

        self.shutdown_reason = ""

        self.started_at = datetime.now(
            UTC
        ).isoformat()

        self.exit_code = 0

        # Read once at construction, like the supervisor provenance
        # variables in core.application: the value cannot change during a
        # process lifetime. Absent means atlas_supervisor.py has hung-child
        # detection disabled (or this process was not launched by it at
        # all), and no heartbeat is written - matching exactly what an
        # unsupervised or directly-run process has always done.
        self._heartbeat_file = self._resolve_heartbeat_file()
        self._instance_lock: Any = None

        # Write-failure logging state for _write_heartbeat: logged on the
        # transition into failure and back out, never per tick.
        self._heartbeat_failing = False
        self._heartbeat_failure_announced = False
        self._heartbeat_failure_logged_at: float | None = None

    @staticmethod
    def _resolve_heartbeat_file() -> Path | None:
        raw = os.environ.get(HEARTBEAT_FILE_ENV)

        return Path(raw) if raw else None

    # --------------------------------------------------------
    # SIGNALS
    # --------------------------------------------------------

    def install_signal_handlers(self) -> None:
        """
        Register operating-system termination handlers.
        """

        signal.signal(
            signal.SIGINT,
            self._handle_signal,
        )

        if hasattr(signal, "SIGTERM"):
            signal.signal(
                signal.SIGTERM,
                self._handle_signal,
            )

        # Windows only. Ctrl+Break - and the CTRL_BREAK_EVENT a parent sends
        # to a child started with CREATE_NEW_PROCESS_GROUP - arrives as
        # SIGBREAK, not SIGINT: on Windows a child cannot be sent SIGINT from
        # outside at all. Without this registration the default SIGBREAK
        # disposition terminates the process, so AtlasApplication.stop() -
        # and the financial-state flush it guarantees - never runs.
        #
        # Guarded exactly like SIGTERM above, because signal.SIGBREAK does not
        # exist on POSIX. It is bound to the same handler deliberately: the
        # shutdown path must never branch by signal type, so an
        # operator-requested stop stays a clean exit-0 shutdown whichever
        # signal delivered it.
        if hasattr(signal, "SIGBREAK"):
            signal.signal(
                signal.SIGBREAK,
                self._handle_signal,
            )

    def _handle_signal(
        self,
        signal_number: int,
        frame: Any,
    ) -> None:
        """
        Request a graceful shutdown.
        """

        del frame

        if self.shutdown_event.is_set():
            return

        try:
            signal_name = signal.Signals(
                signal_number
            ).name
        except ValueError:
            signal_name = str(
                signal_number
            )

        self.shutdown_reason = (
            f"Operating-system signal: {signal_name}"
        )

        logger.warning(
            "Shutdown requested: %s",
            self.shutdown_reason,
        )

        self.shutdown_event.set()

    # --------------------------------------------------------
    # START
    # --------------------------------------------------------

    def start(self) -> bool:
        """
        Construct and start Atlas.
        """

        if not self._validate_configuration():
            return False

        if not self._acquire_instance_lock():
            return False

        logger.info(
            "Constructing AtlasApplication"
        )

        self.application = AtlasApplication(
            execution_mode=EXECUTION_MODE,
            # EXP-001 stopped by the owner (v5.71). EXP-002 switched on by the
            # owner 2026-10-01; experiments stay literals at this one call site.
            paper_confidence_experiment=True,
            paper_confidence_experiment_id="EXP-002",
            paper_fee_rate=PAPER_FEE_RATE_PER_SIDE,
            # Owner switch-on 2026-10-01 ("Aç onayı da veriyorum") after the
            # independent audits: F-3 (unrealized loss in the daily loss limit),
            # S1 capital sleeves, F-4 5 bp adverse PAPER slippage. Literals at
            # this one call site, like the experiment flag above.
            count_unrealized_in_daily_loss=True,
            sleeves_enabled=True,
            paper_slippage_bps="5",
            # Shadow stage S2: the operator chooses with ATLAS_FILL_MODEL (validated
            # in core/atlas_config.py; BOOK needs its own 'shadow' state directory).
            paper_fill_model=getattr(self, "paper_fill_model", "LAST_PRICE"),
            # Order state machine stage 1 (owner approved 2026-10-01): observe and
            # report illegal transitions; never changes a result.
            order_lifecycle_observe=True,
            symbols=trade_universe(),
        )

        # Phase-2 G1: compare the constructed runtime policy with the
        # governance manifest before anything trades. A mismatch blocks new
        # risk only; nothing from the manifest is ever applied.
        apply_policy_manifest(self.application)

        logger.info(
            "Starting AtlasApplication"
        )

        started = self.application.start()

        if not started:
            self.exit_code = 1

            logger.error(
                "AtlasApplication reported startup failure"
            )

            self._display_latest_error()

            return False

        display_startup_status(
            self.application
        )

        return True

    # --------------------------------------------------------
    # MAIN LOOP
    # --------------------------------------------------------

    def _write_heartbeat(self) -> None:
        """Prove the main loop is still ticking, for atlas_supervisor.py.

        Best-effort by design: a failure to write this file must never slow
        down or interrupt the shutdown-detection loop below, which is what
        actually keeps Atlas supervised correctly. Overwritten every tick,
        so its mtime alone - which is all the supervisor reads - is the
        whole signal; the content carries nothing.

        Not silent, though: a failure is logged once when it starts and once
        when writing recovers, never per tick, and a new failure is not
        announced again within HEARTBEAT_FAILURE_LOG_INTERVAL_SECONDS of the
        previous announcement, so a flapping target cannot flood the log.
        Each announcement is a single in-memory log call, never a retry or
        a wait.
        """

        if self._heartbeat_file is None:
            return

        try:
            self._heartbeat_file.write_text(
                json.dumps(
                    {
                        "written_at": time.time(),
                        **self._loop_progress_payload(),
                    }
                ),
                encoding="utf-8",
            )
        except OSError as exc:
            if self._heartbeat_failing:
                return

            self._heartbeat_failing = True

            now = time.monotonic()
            last = self._heartbeat_failure_logged_at

            if (
                last is None
                or now - last >= HEARTBEAT_FAILURE_LOG_INTERVAL_SECONDS
            ):
                self._heartbeat_failure_logged_at = now
                self._heartbeat_failure_announced = True

                logger.warning(
                    "Supervisor heartbeat write failed (%s) for %s; the "
                    "supervisor may treat Atlas as hung if this persists. "
                    "Further failures are not logged until writing recovers",
                    type(exc).__name__,
                    self._heartbeat_file,
                )

            return

        if self._heartbeat_failing:
            self._heartbeat_failing = False

            if self._heartbeat_failure_announced:
                self._heartbeat_failure_announced = False

                logger.info(
                    "Supervisor heartbeat write recovered for %s",
                    self._heartbeat_file,
                )

    def _loop_progress_payload(self) -> dict:
        """Phase-2 D1: MarketLoop progress for the supervisor's stall check.

        Reads one plain attribute without taking any lock, so the heartbeat
        tick can never block behind a busy market cycle. Absent or unreadable
        progress is reported as null (unknown), never as fresh.
        """

        try:
            loop = getattr(self.application, "market_loop", None)
            progress = getattr(loop, "last_loop_progress_monotonic", None)
            interval = getattr(loop, "interval", None)

            return {
                "loop_progress_age_seconds": (
                    round(time.monotonic() - progress, 3)
                    if isinstance(progress, (int, float))
                    else None
                ),
                "loop_interval_seconds": (
                    interval if isinstance(interval, (int, float)) else None
                ),
            }
        except Exception:
            return {
                "loop_progress_age_seconds": None,
                "loop_interval_seconds": None,
            }

    def run_forever(self) -> None:
        """
        Keep the primary process alive until shutdown is requested.

        Market analysis remains the responsibility of MarketLoop.
        This loop only supervises the application process.
        """

        logger.info(
            "Atlas main process is active"
        )

        logger.info(
            "Press Ctrl+C to stop Atlas safely"
        )

        while not self.shutdown_event.wait(
            timeout=1.0
        ):
            self._write_heartbeat()

            if self.application is None:
                self.exit_code = 1
                self.shutdown_reason = (
                    "Application instance disappeared"
                )
                break

            if not self.application.running:
                self.exit_code = 1
                self.shutdown_reason = (
                    "AtlasApplication stopped unexpectedly"
                )

                logger.error(
                    self.shutdown_reason
                )

                break

            if self._subordinate_down or not self._subordinate_alive():
                if self.restart_subordinate is not None:
                    self._handle_subordinate_down()
                    continue

                self.exit_code = 1
                self.shutdown_reason = (
                    "Subordinate component stopped unexpectedly"
                )

                logger.error(
                    self.shutdown_reason
                )

                break

    def _handle_subordinate_down(self) -> None:
        """Keep trading while the panel is down; retry it on an interval.

        Never raises, never stops the process, and never blocks the main
        loop: the restart runs on a worker thread, so the supervisor
        heartbeat and signal handling keep their one-second tick even while
        a restart waits out its start/stop timeouts (registry v5.15).
        """

        now = time.monotonic()

        if not self._subordinate_down:
            self._subordinate_down = True
            self._subordinate_next_retry_at = (
                now + SUBORDINATE_RESTART_INTERVAL_SECONDS
            )
            logger.critical(
                "Operator panel stopped unexpectedly; trading continues and "
                "the panel is retried every %.0fs",
                SUBORDINATE_RESTART_INTERVAL_SECONDS,
            )
            return

        worker = self._subordinate_restart_thread

        if worker is not None and worker.is_alive():
            return

        if now < self._subordinate_next_retry_at:
            return

        self._subordinate_next_retry_at = (
            now + SUBORDINATE_RESTART_INTERVAL_SECONDS
        )

        worker = threading.Thread(
            target=self._restart_subordinate_once,
            name="atlas-panel-restart",
            daemon=True,
        )
        self._subordinate_restart_thread = worker
        worker.start()

    def _restart_subordinate_once(self) -> None:
        """One restart attempt, on the worker thread. Never raises."""

        try:
            self.restart_subordinate()
        except Exception as exc:
            logger.warning(
                "Operator panel restart failed (%s: %s); retrying in %.0fs",
                type(exc).__name__,
                exc,
                SUBORDINATE_RESTART_INTERVAL_SECONDS,
            )
            return

        self._subordinate_down = False
        logger.info("Operator panel restarted and serving again")

    def _subordinate_alive(self) -> bool:
        """
        Ask the composition hook whether its component is still alive.

        Only an explicit ``False`` is evidence of death. No hook, a hook
        that answers anything else, and a hook that raises all read as
        alive - the same "unknown never flips the verdict on its own" rule
        AtlasApplication.health() already applies to thread liveness.

        A raising probe deliberately does not stop Atlas. This value decides
        whether the process exits 1, and an exit 1 is what a supervisor
        restarts on, so a buggy probe that threw would turn into a restart
        loop around a perfectly healthy runtime. Missing one dead web thread
        is the smaller failure, and the exception is logged either way.
        """

        probe = self.is_subordinate_alive

        if probe is None:
            return True

        try:
            return probe() is not False
        except Exception:
            if not self._liveness_probe_failed:
                self._liveness_probe_failed = True

                logger.exception(
                    "Subordinate liveness probe failed; "
                    "treating the component as alive"
                )

            return True

    # --------------------------------------------------------
    # ERROR DETAILS
    # --------------------------------------------------------

    def _display_latest_error(self) -> None:
        """
        Log the latest structured application error when available.
        """

        if self.application is None:
            return

        status = safe_dict(
            self.application.status()
        )

        errors = safe_dict(
            status.get("errors")
        )

        latest = errors.get(
            "latest"
        )

        if not isinstance(latest, dict):
            return

        logger.error(
            "Application error phase: %s",
            latest.get(
                "phase",
                "UNKNOWN",
            ),
        )

        logger.error(
            "Application error type: %s",
            latest.get(
                "type",
                "UNKNOWN",
            ),
        )

        logger.error(
            "Application error: %s",
            latest.get(
                "error",
                "UNKNOWN",
            ),
        )

    # --------------------------------------------------------
    # STOP
    # --------------------------------------------------------

    def stop(self) -> bool:
        """
        Stop Atlas safely.
        """

        if self.application is None:
            return True

        logger.info(
            "Stopping AtlasApplication"
        )

        finished = threading.Event()
        keeper = self._start_shutdown_heartbeat(finished)

        try:
            stopped = self.application.stop()
        finally:
            finished.set()

            if keeper is not None:
                keeper.join(timeout=SHUTDOWN_HEARTBEAT_INTERVAL_SECONDS * 2)

        if not stopped:
            self.exit_code = max(
                self.exit_code,
                1,
            )

            logger.warning(
                "Atlas stopped with one or more shutdown errors"
            )

        return stopped

    def _validate_configuration(self) -> bool:
        """CFG-001: validate every setting at once, before any state is touched.

        Invalid -> exit 1 (owner decision, registry v5.20), with every
        problem logged, so one run shows the operator everything to fix.
        """

        try:
            config = load_config(
                os.environ,
                execution_mode=EXECUTION_MODE,
                paper_confidence_experiment=PAPER_CONFIDENCE_EXPERIMENT,
            )
        except AtlasConfigError as exc:
            self.exit_code = 1
            self.shutdown_reason = f"Invalid configuration ({len(exc.errors)} problem(s))"
            logger.critical(self.shutdown_reason)
            for problem in exc.errors:
                logger.critical("  config: %s", problem)
            return False

        self.paper_fill_model = config.fill_model
        logger.info(
            "Configuration valid | %s",
            " ".join(f"{k}={v}" for k, v in config.describe().items()),
        )

        return True

    def _acquire_instance_lock(self) -> bool:
        """Hold the state-root lock (core/instance_lock.py) for this process.

        Held elsewhere -> ALREADY_RUNNING_EXIT_CODE, which the supervisor
        does not restart on. Any other failure to take it is a normal
        startup failure (exit 1) - never "run anyway without a lock".
        AtlasApplication takes the same lock again (shared within this
        process), so paths that bypass this method are refused too.
        """

        try:
            root = resolve_state_directory()
            instance_lock.acquire(root)
        except InstanceLockHeldError as exc:
            self.exit_code = ALREADY_RUNNING_EXIT_CODE
            self.shutdown_reason = str(exc)
            logger.critical(self.shutdown_reason)
            return False
        except Exception as exc:
            self.exit_code = 1
            self.shutdown_reason = f"Instance lock unavailable: {exc}"
            logger.critical(self.shutdown_reason)
            return False

        self._instance_lock = root

        return True

    def _release_instance_lock(self) -> None:
        """Drop this process's reference to the state-root lock."""

        root = self._instance_lock

        if root is None:
            return

        self._instance_lock = None
        instance_lock.release(root)

    def _start_shutdown_heartbeat(
        self,
        finished: threading.Event,
    ) -> threading.Thread | None:
        """Keep the supervisor heartbeat fresh while stop() runs, bounded.

        Writes every SHUTDOWN_HEARTBEAT_INTERVAL_SECONDS until ``finished``
        is set or SHUTDOWN_HEARTBEAT_MAX_SECONDS have passed, whichever is
        first. The bound is deliberate: a hung stop() must still go stale.
        """

        if self._heartbeat_file is None:
            return None

        def keep_alive() -> None:
            deadline = time.monotonic() + SHUTDOWN_HEARTBEAT_MAX_SECONDS

            while time.monotonic() < deadline:
                self._write_heartbeat()

                if finished.wait(timeout=SHUTDOWN_HEARTBEAT_INTERVAL_SECONDS):
                    return

            logger.warning(
                "Shutdown still running after %.0fs; supervisor heartbeat "
                "no longer refreshed",
                SHUTDOWN_HEARTBEAT_MAX_SECONDS,
            )

        keeper = threading.Thread(
            target=keep_alive,
            name="atlas-shutdown-heartbeat",
            daemon=True,
        )
        keeper.start()

        return keeper

    # --------------------------------------------------------
    # COMPOSITION HOOKS
    # --------------------------------------------------------

    def _notify_started(self) -> None:
        """
        Hand the started application to the composition hook.

        Exceptions are deliberately not caught here: a subordinate
        component that cannot start is a startup failure, and execute()'s
        own handler already turns that into exit_code 1 plus a guaranteed
        shutdown.
        """

        if self.on_started is None:
            return

        if self.application is None:
            return

        logger.info(
            "Running composition start hook"
        )

        self.on_started(
            self.application
        )

    def _notify_stopping(self) -> None:
        """
        Let the composition hook stop before AtlasApplication does.

        This runs on the shutdown path, where the only thing that matters
        is that AtlasApplication.stop() is still reached: a failure here
        is recorded and swallowed, never propagated.
        """

        if self.on_stopping is None:
            return

        logger.info(
            "Running composition stop hook"
        )

        try:
            self.on_stopping()
        except Exception:
            self.exit_code = max(
                self.exit_code,
                1,
            )

            logger.exception(
                "Composition stop hook failed"
            )

    # --------------------------------------------------------
    # COMPLETE PROCESS
    # --------------------------------------------------------

    def execute(self) -> int:
        """
        Run the full Atlas process lifecycle.
        """

        self.install_signal_handlers()

        try:
            if not self.start():
                return self.exit_code

            try:
                self._notify_started()
            except Exception:
                if self.restart_subordinate is None:
                    raise

                logger.critical(
                    "Operator panel failed to start; trading continues "
                    "without it and the panel is retried every %.0fs",
                    SUBORDINATE_RESTART_INTERVAL_SECONDS,
                    exc_info=True,
                )
                self._subordinate_down = True
                self._subordinate_next_retry_at = (
                    time.monotonic() + SUBORDINATE_RESTART_INTERVAL_SECONDS
                )

            self.run_forever()

        except KeyboardInterrupt:
            self.shutdown_reason = (
                "Keyboard interrupt"
            )

            logger.warning(
                "Keyboard interrupt received"
            )

        except Exception as exc:
            if isinstance(exc, AuditChainIntegrityError):
                self.exit_code = INTEGRITY_HALT_EXIT_CODE
            elif isinstance(exc, InstanceLockHeldError):
                self.exit_code = ALREADY_RUNNING_EXIT_CODE
            else:
                self.exit_code = 1

            self.shutdown_reason = (
                f"Fatal error: {exc}"
            )

            logger.critical(
                "Fatal Atlas error: %s",
                exc,
            )

            logger.debug(
                "Fatal traceback:\n%s",
                traceback.format_exc(),
            )

        finally:
            self._notify_stopping()

            try:
                self.stop()
            except Exception:
                self.exit_code = 1

                logger.exception(
                    "Fatal error during Atlas shutdown"
                )

            self._release_instance_lock()

            logger.info(
                "Atlas process finished | "
                "exit_code=%s | reason=%s",
                self.exit_code,
                (
                    self.shutdown_reason
                    or "Normal shutdown"
                ),
            )

        return self.exit_code


# ============================================================
# PUBLIC MAIN
# ============================================================


def main() -> int:
    """
    Atlas command-line entry point.
    """

    configure_logging()

    print()
    print("=" * 64)
    print("PROJECT ATLAS AI")
    print("Institutional AI Investment Platform")
    print("=" * 64)
    print()

    process = AtlasProcess()

    return process.execute()


# ============================================================
# SCRIPT ENTRY
# ============================================================


if __name__ == "__main__":
    raise SystemExit(
        main()
    )