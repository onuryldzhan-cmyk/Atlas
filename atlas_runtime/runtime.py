"""
============================================================
ATLAS RUNTIME v1.0.0
============================================================

Project
-------
Project Atlas AI

Package
-------
atlas_runtime

Purpose
-------
Provide the production-oriented process lifecycle for Project
Atlas AI on top of AtlasOS.

Responsibilities
----------------
- Own the AtlasOS Kernel instance
- Register Atlas services and dependencies
- Validate the service dependency graph
- Start services in dependency order
- Roll back partial startup failures
- Stop services in reverse dependency order
- Track runtime lifecycle and uptime
- Support graceful process shutdown
- Produce plaintext-safe runtime snapshots
- Centralize startup and shutdown logging

Architecture
------------
Operating System / Process
          |
          v
     AtlasRuntime
          |
          v
     AtlasOSKernel
          |
          +-- ConfigurationService
          +-- SecretsManager
          +-- ConfigurationSecretsService
          +-- EventBusService
          +-- MetricsService
          +-- HealthMonitorService
          +-- SchedulerService
          +-- Atlas application services

Design principles
-----------------
- Runtime owns process lifecycle
- Kernel owns service lifecycle
- Services own domain behavior
- Dependencies are explicit
- Startup failures are fail-fast
- Partial startup is rolled back
- Shutdown is idempotent
- Plaintext secrets are never exposed
- Production changes remain human-controlled

============================================================
"""

from __future__ import annotations

import logging
import signal
import threading
import time

from dataclasses import dataclass
from dataclasses import field
from datetime import UTC
from datetime import datetime
from enum import Enum
from types import FrameType
from typing import Any
from typing import Iterable
from typing import Mapping

from atlas_os import AtlasOSKernel
from atlas_os import AtlasService
from atlas_os import KernelSnapshot


logger = logging.getLogger(
    "AtlasRuntime"
)


# =========================================================
# ENUMS
# =========================================================


class AtlasRuntimeState(
    str,
    Enum,
):
    """
    Atlas Runtime process lifecycle state.
    """

    CREATED = "CREATED"

    CONFIGURING = "CONFIGURING"

    READY = "READY"

    STARTING = "STARTING"

    RUNNING = "RUNNING"

    STOPPING = "STOPPING"

    STOPPED = "STOPPED"

    FAILED = "FAILED"


# =========================================================
# EXCEPTIONS
# =========================================================


class AtlasRuntimeError(
    RuntimeError
):
    """
    Base exception for Atlas Runtime failures.
    """


class AtlasRuntimeStateError(
    AtlasRuntimeError
):
    """
    Raised when an operation is invalid for the current state.
    """


class AtlasRuntimeConfigurationError(
    AtlasRuntimeError
):
    """
    Raised when runtime service configuration is invalid.
    """


class AtlasRuntimeStartupError(
    AtlasRuntimeError
):
    """
    Raised when Atlas Runtime cannot start successfully.
    """


class AtlasRuntimeShutdownError(
    AtlasRuntimeError
):
    """
    Raised when Atlas Runtime cannot stop cleanly.
    """


# =========================================================
# DATA MODELS
# =========================================================


@dataclass(
    frozen=True,
    slots=True,
)
class RuntimeServiceRegistration:
    """
    Describes one service registered with Atlas Runtime.
    """

    service_name: str

    dependencies: tuple[
        str,
        ...,
    ] = ()

    critical: bool = True

    registered_at: datetime = field(
        default_factory=lambda: datetime.now(
            UTC
        )
    )


@dataclass(
    frozen=True,
    slots=True,
)
class AtlasRuntimeSnapshot:
    """
    Plaintext-safe Runtime lifecycle snapshot.
    """

    state: AtlasRuntimeState

    created_at: datetime

    started_at: datetime | None

    stopped_at: datetime | None

    uptime_seconds: float

    registered_services: tuple[
        RuntimeServiceRegistration,
        ...,
    ]

    service_count: int

    kernel_snapshot: KernelSnapshot

    shutdown_requested: bool

    last_error: str | None

    metadata: Mapping[
        str,
        Any,
    ]

    created_snapshot_at: datetime = field(
        default_factory=lambda: datetime.now(
            UTC
        )
    )

    plaintext_values_exposed: bool = False


# =========================================================
# RUNTIME
# =========================================================


class AtlasRuntime:
    """
    Production-oriented process lifecycle manager for Atlas AI.

    AtlasRuntime is intentionally small. It does not implement
    trading, analysis, decision-making, execution, learning, or
    research logic.

    Its responsibility is to assemble and control AtlasOS services.
    """

    VERSION = "1.0.0"

    NAME = "AtlasRuntime"

    def __init__(
        self,
        *,
        kernel: AtlasOSKernel | None = None,
        metadata: Mapping[
            str,
            Any,
        ] | None = None,
        install_signal_handlers: bool = True,
    ) -> None:
        """
        Initialize Atlas Runtime.

        Parameters
        ----------
        kernel:
            Optional existing AtlasOSKernel. A new kernel is created
            when omitted.

        metadata:
            Plaintext-safe runtime metadata.

        install_signal_handlers:
            Whether SIGINT and SIGTERM handlers should be installed
            during startup.
        """

        if (
            kernel is not None
            and not isinstance(
                kernel,
                AtlasOSKernel,
            )
        ):
            raise TypeError(
                "kernel must be an AtlasOSKernel "
                "instance or None."
            )

        self._kernel = (
            kernel
            if kernel is not None
            else AtlasOSKernel(
                metadata={
                    "runtime": self.NAME,
                    "runtime_version": self.VERSION,
                }
            )
        )

        self._metadata: dict[
            str,
            Any,
        ] = dict(
            metadata or {}
        )

        self._install_signal_handlers = bool(
            install_signal_handlers
        )

        self._state = (
            AtlasRuntimeState.CREATED
        )

        self._created_at = datetime.now(
            UTC
        )

        self._started_at: datetime | None = None

        self._stopped_at: datetime | None = None

        self._last_error: str | None = None

        self._registrations: dict[
            str,
            RuntimeServiceRegistration,
        ] = {}

        self._registration_order: list[
            str
        ] = []

        self._shutdown_event = (
            threading.Event()
        )

        self._lock = threading.RLock()

        self._signal_handlers_installed = False

        self._previous_signal_handlers: dict[
            signal.Signals,
            Any,
        ] = {}

        logger.info(
            "%s v%s initialized.",
            self.NAME,
            self.VERSION,
        )

    # =====================================================
    # PROPERTIES
    # =====================================================

    @property
    def kernel(
        self,
    ) -> AtlasOSKernel:
        """
        Return the owned AtlasOS Kernel.
        """

        return self._kernel

    @property
    def state(
        self,
    ) -> AtlasRuntimeState:
        """
        Return current Runtime state.
        """

        with self._lock:
            return self._state

    @property
    def is_running(
        self,
    ) -> bool:
        """
        Return whether Runtime is running.
        """

        return (
            self.state
            is AtlasRuntimeState.RUNNING
        )

    @property
    def created_at(
        self,
    ) -> datetime:
        """
        Return Runtime creation time.
        """

        return self._created_at

    @property
    def started_at(
        self,
    ) -> datetime | None:
        """
        Return latest successful startup time.
        """

        with self._lock:
            return self._started_at

    @property
    def stopped_at(
        self,
    ) -> datetime | None:
        """
        Return latest stop time.
        """

        with self._lock:
            return self._stopped_at

    @property
    def last_error(
        self,
    ) -> str | None:
        """
        Return the last Runtime error message.
        """

        with self._lock:
            return self._last_error

    @property
    def service_count(
        self,
    ) -> int:
        """
        Return registered Runtime service count.
        """

        with self._lock:
            return len(
                self._registrations
            )

    @property
    def shutdown_requested(
        self,
    ) -> bool:
        """
        Return whether shutdown has been requested.
        """

        return self._shutdown_event.is_set()

    @property
    def uptime_seconds(
        self,
    ) -> float:
        """
        Return current Runtime uptime.
        """

        with self._lock:
            if self._started_at is None:
                return 0.0

            end_time = (
                self._stopped_at
                if self._state
                is AtlasRuntimeState.STOPPED
                else datetime.now(
                    UTC
                )
            )

            return max(
                0.0,
                (
                    end_time
                    - self._started_at
                ).total_seconds(),
            )

    # =====================================================
    # CONFIGURATION
    # =====================================================

    def register_service(
        self,
        service: AtlasService,
        *,
        dependencies: Iterable[
            str
        ] = (),
        critical: bool = True,
    ) -> RuntimeServiceRegistration:
        """
        Register one AtlasOS service and its dependencies.

        Services may only be registered before Runtime startup.
        """

        if service is None:
            raise TypeError(
                "service is required."
            )

        with self._lock:
            self._ensure_state(
                allowed={
                    AtlasRuntimeState.CREATED,
                    AtlasRuntimeState.CONFIGURING,
                    AtlasRuntimeState.READY,
                    AtlasRuntimeState.STOPPED,
                },
                operation="register service",
            )

            self._state = (
                AtlasRuntimeState.CONFIGURING
            )

            service_name = self._service_name(
                service
            )

            if service_name in self._registrations:
                raise AtlasRuntimeConfigurationError(
                    "Service is already registered with "
                    f"Runtime: {service_name}"
                )

            normalized_dependencies = (
                self._normalize_dependencies(
                    dependencies
                )
            )

            self._kernel.register_service(
                service,
                dependencies=(
                    normalized_dependencies
                ),
            )

            registration = (
                RuntimeServiceRegistration(
                    service_name=service_name,
                    dependencies=(
                        normalized_dependencies
                    ),
                    critical=bool(
                        critical
                    ),
                )
            )

            self._registrations[
                service_name
            ] = registration

            self._registration_order.append(
                service_name
            )

            logger.info(
                "Runtime service registered: %s; "
                "dependencies=%s; critical=%s",
                service_name,
                normalized_dependencies,
                critical,
            )

            return registration

    def register_services(
        self,
        registrations: Iterable[
            tuple[
                AtlasService,
                Iterable[str],
            ]
        ],
    ) -> tuple[
        RuntimeServiceRegistration,
        ...,
    ]:
        """
        Register multiple services.

        Each item must contain:

            (service, dependencies)
        """

        completed: list[
            RuntimeServiceRegistration
        ] = []

        for service, dependencies in registrations:
            completed.append(
                self.register_service(
                    service,
                    dependencies=dependencies,
                )
            )

        return tuple(
            completed
        )

    def validate(
        self,
    ) -> None:
        """
        Validate Runtime and Kernel configuration.
        """

        with self._lock:
            self._ensure_state(
                allowed={
                    AtlasRuntimeState.CREATED,
                    AtlasRuntimeState.CONFIGURING,
                    AtlasRuntimeState.READY,
                    AtlasRuntimeState.STOPPED,
                },
                operation="validate runtime",
            )

            try:
                self._kernel.validate()

            except Exception as error:
                self._state = (
                    AtlasRuntimeState.FAILED
                )

                self._last_error = (
                    f"{type(error).__name__}: "
                    f"{error}"
                )

                raise AtlasRuntimeConfigurationError(
                    "Atlas Runtime configuration "
                    "validation failed."
                ) from error

            self._state = (
                AtlasRuntimeState.READY
            )

            self._last_error = None

            logger.info(
                "Atlas Runtime validation passed. "
                "Registered services: %s.",
                self.service_count,
            )

    # =====================================================
    # STARTUP
    # =====================================================

    def start(
        self,
        *,
        rollback_on_failure: bool = True,
    ) -> Any:
        """
        Start Atlas Runtime and all registered services.

        The returned value is the AtlasOS Kernel orchestration
        result.
        """

        with self._lock:
            if (
                self._state
                is AtlasRuntimeState.RUNNING
            ):
                logger.info(
                    "Atlas Runtime is already running."
                )

                return None

            self._ensure_state(
                allowed={
                    AtlasRuntimeState.CREATED,
                    AtlasRuntimeState.CONFIGURING,
                    AtlasRuntimeState.READY,
                    AtlasRuntimeState.STOPPED,
                    AtlasRuntimeState.FAILED,
                },
                operation="start runtime",
            )

            self._state = (
                AtlasRuntimeState.STARTING
            )

            self._last_error = None

            self._stopped_at = None

            self._shutdown_event.clear()

        logger.info(
            "Atlas Runtime startup initiated."
        )

        try:
            self._kernel.validate()

            if self._install_signal_handlers:
                self._install_shutdown_handlers()

            result = self._kernel.start(
                rollback_on_failure=(
                    rollback_on_failure
                )
            )

            if not self._kernel.is_running:
                raise AtlasRuntimeStartupError(
                    "AtlasOS Kernel did not enter "
                    "RUNNING state."
                )

            with self._lock:
                self._started_at = datetime.now(
                    UTC
                )

                self._state = (
                    AtlasRuntimeState.RUNNING
                )

            logger.info(
                "Atlas Runtime started successfully. "
                "Services: %s.",
                self.service_count,
            )

            return result

        except Exception as error:
            with self._lock:
                self._state = (
                    AtlasRuntimeState.FAILED
                )

                self._last_error = (
                    f"{type(error).__name__}: "
                    f"{error}"
                )

            logger.exception(
                "Atlas Runtime startup failed."
            )

            if self._install_signal_handlers:
                self._restore_signal_handlers()

            if isinstance(
                error,
                AtlasRuntimeError,
            ):
                raise

            raise AtlasRuntimeStartupError(
                "Atlas Runtime startup failed."
            ) from error

    # =====================================================
    # SHUTDOWN
    # =====================================================

    def request_shutdown(
        self,
        *,
        reason: str = "Shutdown requested.",
    ) -> None:
        """
        Request Runtime shutdown.

        This method only sets the shutdown event. It does not perform
        shutdown immediately, making it safe for signal handlers.
        """

        normalized_reason = (
            str(
                reason
            ).strip()
            or "Shutdown requested."
        )

        logger.warning(
            "Atlas Runtime shutdown requested: %s",
            normalized_reason,
        )

        self._shutdown_event.set()

    def stop(
        self,
        *,
        suppress_errors: bool = False,
    ) -> Any:
        """
        Stop Atlas Runtime and AtlasOS Kernel safely.
        """

        with self._lock:
            if self._state in {
                AtlasRuntimeState.CREATED,
                AtlasRuntimeState.READY,
                AtlasRuntimeState.STOPPED,
            }:
                self._state = (
                    AtlasRuntimeState.STOPPED
                )

                self._stopped_at = datetime.now(
                    UTC
                )

                self._shutdown_event.set()

                self._restore_signal_handlers()

                logger.info(
                    "Atlas Runtime stopped."
                )

                return None

            if (
                self._state
                is AtlasRuntimeState.STOPPING
            ):
                return None

            self._state = (
                AtlasRuntimeState.STOPPING
            )

        logger.info(
            "Atlas Runtime shutdown initiated."
        )

        try:
            result = self._kernel.stop()

            with self._lock:
                self._state = (
                    AtlasRuntimeState.STOPPED
                )

                self._stopped_at = datetime.now(
                    UTC
                )

                self._shutdown_event.set()

                self._last_error = None

            logger.info(
                "Atlas Runtime stopped successfully."
            )

            return result

        except Exception as error:
            with self._lock:
                self._state = (
                    AtlasRuntimeState.FAILED
                )

                self._last_error = (
                    f"{type(error).__name__}: "
                    f"{error}"
                )

                self._stopped_at = datetime.now(
                    UTC
                )

                self._shutdown_event.set()

            logger.exception(
                "Atlas Runtime shutdown failed."
            )

            if suppress_errors:
                return None

            raise AtlasRuntimeShutdownError(
                "Atlas Runtime shutdown failed."
            ) from error

        finally:
            self._restore_signal_handlers()

    def run_forever(
        self,
        *,
        poll_interval: float = 0.5,
    ) -> None:
        """
        Start Runtime and block until shutdown is requested.
        """

        interval = float(
            poll_interval
        )

        if interval <= 0:
            raise ValueError(
                "poll_interval must be greater than zero."
            )

        self.start()

        try:
            while not self.shutdown_requested:
                time.sleep(
                    interval
                )

        except KeyboardInterrupt:
            self.request_shutdown(
                reason="Keyboard interrupt."
            )

        finally:
            self.stop(
                suppress_errors=False
            )

    # =====================================================
    # SNAPSHOT
    # =====================================================

    def registrations(
        self,
    ) -> tuple[
        RuntimeServiceRegistration,
        ...,
    ]:
        """
        Return Runtime service registrations in registration order.
        """

        with self._lock:
            return tuple(
                self._registrations[
                    name
                ]
                for name in self._registration_order
            )

    def snapshot(
        self,
    ) -> AtlasRuntimeSnapshot:
        """
        Produce a plaintext-safe Runtime snapshot.
        """

        with self._lock:
            return AtlasRuntimeSnapshot(
                state=self._state,
                created_at=self._created_at,
                started_at=self._started_at,
                stopped_at=self._stopped_at,
                uptime_seconds=(
                    self.uptime_seconds
                ),
                registered_services=(
                    self.registrations()
                ),
                service_count=len(
                    self._registrations
                ),
                kernel_snapshot=(
                    self._kernel.snapshot()
                ),
                shutdown_requested=(
                    self.shutdown_requested
                ),
                last_error=self._last_error,
                metadata=dict(
                    self._metadata
                ),
                plaintext_values_exposed=False,
            )

    # =====================================================
    # SIGNAL HANDLING
    # =====================================================

    def _install_shutdown_handlers(
        self,
    ) -> None:
        """
        Install SIGINT and SIGTERM handlers when allowed.
        """

        with self._lock:
            if self._signal_handlers_installed:
                return

            if (
                threading.current_thread()
                is not threading.main_thread()
            ):
                logger.warning(
                    "Signal handlers were not installed "
                    "because Runtime is not in the main thread."
                )

                return

            supported_signals = [
                signal.SIGINT,
            ]

            if hasattr(
                signal,
                "SIGTERM",
            ):
                supported_signals.append(
                    signal.SIGTERM
                )

            for signal_number in supported_signals:
                self._previous_signal_handlers[
                    signal_number
                ] = signal.getsignal(
                    signal_number
                )

                signal.signal(
                    signal_number,
                    self._handle_shutdown_signal,
                )

            self._signal_handlers_installed = True

    def _restore_signal_handlers(
        self,
    ) -> None:
        """
        Restore previous process signal handlers.
        """

        with self._lock:
            if not self._signal_handlers_installed:
                return

            if (
                threading.current_thread()
                is not threading.main_thread()
            ):
                return

            for (
                signal_number,
                previous_handler,
            ) in self._previous_signal_handlers.items():
                signal.signal(
                    signal_number,
                    previous_handler,
                )

            self._previous_signal_handlers.clear()

            self._signal_handlers_installed = False

    def _handle_shutdown_signal(
        self,
        signal_number: int,
        frame: FrameType | None,
    ) -> None:
        """
        Process SIGINT or SIGTERM safely.
        """

        del frame

        try:
            signal_name = signal.Signals(
                signal_number
            ).name

        except ValueError:
            signal_name = str(
                signal_number
            )

        self.request_shutdown(
            reason=(
                "Operating-system signal received: "
                f"{signal_name}"
            )
        )

    # =====================================================
    # INTERNAL HELPERS
    # =====================================================

    def _ensure_state(
        self,
        *,
        allowed: set[
            AtlasRuntimeState
        ],
        operation: str,
    ) -> None:
        """
        Validate Runtime state for an operation.
        """

        if self._state not in allowed:
            allowed_values = ", ".join(
                sorted(
                    state.value
                    for state in allowed
                )
            )

            raise AtlasRuntimeStateError(
                f"Cannot {operation} while Runtime "
                f"is {self._state.value}. "
                f"Allowed states: {allowed_values}."
            )

    @staticmethod
    def _normalize_dependencies(
        dependencies: Iterable[
            str
        ],
    ) -> tuple[
        str,
        ...,
    ]:
        """
        Normalize and deduplicate dependency names.
        """

        normalized: list[
            str
        ] = []

        seen: set[
            str
        ] = set()

        for dependency in dependencies:
            name = str(
                dependency
            ).strip()

            if not name:
                raise AtlasRuntimeConfigurationError(
                    "Dependency names cannot be empty."
                )

            key = name.casefold()

            if key in seen:
                continue

            seen.add(
                key
            )

            normalized.append(
                name
            )

        return tuple(
            normalized
        )

    @staticmethod
    def _service_name(
        service: AtlasService,
    ) -> str:
        """
        Resolve the canonical service name from AtlasService identity.
        """

        identity = getattr(
            service,
            "identity",
            None,
        )

        if identity is None:
            raise AtlasRuntimeConfigurationError(
                "Registered service has no identity."
            )

        for attribute_name in (
            "name",
            "service_name",
        ):
            value = getattr(
                identity,
                attribute_name,
                None,
            )

            if value is None:
                continue

            normalized = str(
                value
            ).strip()

            if normalized:
                return normalized

        raise AtlasRuntimeConfigurationError(
            "Registered service identity has no "
            "usable name."
        )

    # =====================================================
    # CONTEXT MANAGER
    # =====================================================

    def __enter__(
        self,
    ) -> AtlasRuntime:
        """
        Start Runtime when entering a context.
        """

        self.start()

        return self

    def __exit__(
        self,
        exception_type: type[
            BaseException
        ] | None,
        exception: BaseException | None,
        traceback: Any,
    ) -> bool:
        """
        Stop Runtime when leaving a context.
        """

        del exception_type
        del exception
        del traceback

        self.stop(
            suppress_errors=True
        )

        return False


__all__ = [
    "AtlasRuntime",
    "AtlasRuntimeState",
    "AtlasRuntimeSnapshot",
    "RuntimeServiceRegistration",
    "AtlasRuntimeError",
    "AtlasRuntimeStateError",
    "AtlasRuntimeConfigurationError",
    "AtlasRuntimeStartupError",
    "AtlasRuntimeShutdownError",
]