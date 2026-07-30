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
- Handle Ctrl+C safely
- Handle fatal startup/runtime errors
- Guarantee graceful application shutdown

============================================================
"""

from __future__ import annotations

import logging
import signal
import sys
import threading
import time
import traceback

from datetime import UTC, datetime
from typing import Any

from core.application import AtlasApplication


LOGGER_NAME = "AtlasAI.Main"

logger = logging.getLogger(LOGGER_NAME)


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
    """

    VERSION = "1.0"

    def __init__(self) -> None:
        self.application: AtlasApplication | None = None

        self.shutdown_event = threading.Event()

        self.shutdown_reason = ""

        self.started_at = datetime.now(
            UTC
        ).isoformat()

        self.exit_code = 0

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

        logger.info(
            "Constructing AtlasApplication"
        )

        self.application = AtlasApplication(
            execution_mode="PAPER",
        )

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

        stopped = self.application.stop()

        if not stopped:
            self.exit_code = max(
                self.exit_code,
                1,
            )

            logger.warning(
                "Atlas stopped with one or more shutdown errors"
            )

        return stopped

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

            self.run_forever()

        except KeyboardInterrupt:
            self.shutdown_reason = (
                "Keyboard interrupt"
            )

            logger.warning(
                "Keyboard interrupt received"
            )

        except Exception as exc:
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
            try:
                self.stop()
            except Exception:
                self.exit_code = 1

                logger.exception(
                    "Fatal error during Atlas shutdown"
                )

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