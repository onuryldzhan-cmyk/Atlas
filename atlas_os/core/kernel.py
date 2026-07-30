"""
============================================================
ATLAS OS KERNEL v1.0
============================================================

Institutional lifecycle orchestrator for AtlasOS.

Responsibilities
----------------
- Manage the AtlasOS lifecycle
- Initialize services in dependency order
- Start services in dependency order
- Stop services in reverse dependency order
- Roll back safely after startup failures
- Produce health and diagnostic snapshots
- Protect lifecycle operations with thread synchronization

Lifecycle
---------
CREATED
   |
INITIALIZING
   |
READY
   |
STARTING
   |
RUNNING
   |
STOPPING
   |
STOPPED

============================================================
"""

from __future__ import annotations

import logging

from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from threading import RLock
from typing import Any

from atlas_os.core.contracts import (
    AtlasService,
    HealthState,
    ServiceState,
)
from atlas_os.core.service_registry import ServiceRegistry


logger = logging.getLogger("AtlasOS.Kernel")


class KernelState(StrEnum):
    """
    AtlasOS Kernel lifecycle states.
    """

    CREATED = "CREATED"
    INITIALIZING = "INITIALIZING"
    READY = "READY"
    STARTING = "STARTING"
    RUNNING = "RUNNING"
    STOPPING = "STOPPING"
    STOPPED = "STOPPED"
    FAILED = "FAILED"


class KernelError(RuntimeError):
    """
    Base exception for AtlasOS Kernel failures.
    """


class InvalidKernelStateError(KernelError):
    """
    Raised when a lifecycle action is called from an invalid state.
    """


class KernelStartupError(KernelError):
    """
    Raised when AtlasOS cannot complete startup.
    """


@dataclass(frozen=True, slots=True)
class KernelSnapshot:
    """
    Immutable AtlasOS Kernel diagnostic snapshot.
    """

    version: str
    state: KernelState
    registered_services: int
    running_services: int
    healthy_services: int
    degraded_services: int
    unhealthy_services: int
    started_at: datetime | None
    stopped_at: datetime | None
    uptime_seconds: float
    last_error: str | None


class AtlasKernel:
    """
    AtlasOS lifecycle coordinator.

    AtlasKernel owns lifecycle orchestration but does not implement
    service business logic. Every managed component must satisfy the
    AtlasService contract.
    """

    VERSION = "1.0"
    NAME = "AtlasKernel"

    def __init__(
        self,
        registry: ServiceRegistry | None = None,
    ) -> None:
        self.registry = registry or ServiceRegistry()

        self._state = KernelState.CREATED
        self._lock = RLock()

        self._startup_order: tuple[AtlasService, ...] = ()
        self._started_services: list[AtlasService] = []

        self._started_at: datetime | None = None
        self._stopped_at: datetime | None = None
        self._last_error: str | None = None

        logger.info(
            "AtlasOS Kernel v%s created.",
            self.VERSION,
        )

    @property
    def state(self) -> KernelState:
        """
        Return current kernel state.
        """

        with self._lock:
            return self._state

    @property
    def is_running(self) -> bool:
        """
        Return True when the kernel is running.
        """

        return self.state == KernelState.RUNNING

    def register_service(
        self,
        service: AtlasService,
    ) -> None:
        """
        Register a service before kernel initialization.
        """

        with self._lock:
            if self._state not in {
                KernelState.CREATED,
                KernelState.STOPPED,
            }:
                raise InvalidKernelStateError(
                    "Services can only be registered while the kernel "
                    "is CREATED or STOPPED."
                )

            self.registry.register(service)

    def initialize(self) -> None:
        """
        Validate dependencies and initialize all services.
        """

        with self._lock:
            if self._state != KernelState.CREATED:
                raise InvalidKernelStateError(
                    "Kernel initialization requires CREATED state. "
                    f"Current state: {self._state}"
                )

            self._state = KernelState.INITIALIZING
            self._last_error = None

        logger.info("AtlasOS Kernel initialization started.")

        try:
            startup_order = self.registry.resolve_startup_order()

            for service in startup_order:
                logger.info(
                    "Initializing service: %s",
                    service.metadata.name,
                )
                service.initialize()

                if service.state not in {
                    ServiceState.READY,
                    ServiceState.STOPPED,
                }:
                    raise KernelError(
                        f"Service '{service.metadata.name}' did not enter "
                        "READY or STOPPED state after initialization. "
                        f"Current state: {service.state}"
                    )

            with self._lock:
                self._startup_order = startup_order
                self._state = KernelState.READY

            logger.info(
                "AtlasOS Kernel initialized with %d services.",
                len(startup_order),
            )

        except Exception as exc:
            self._mark_failed(exc)
            raise KernelError(
                f"AtlasOS initialization failed: {exc}"
            ) from exc

    def start(self) -> None:
        """
        Start all services in dependency order.
        """

        with self._lock:
            if self._state == KernelState.CREATED:
                self.initialize()

            if self._state != KernelState.READY:
                raise InvalidKernelStateError(
                    "Kernel startup requires READY state. "
                    f"Current state: {self._state}"
                )

            self._state = KernelState.STARTING
            self._started_services.clear()
            self._stopped_at = None
            self._last_error = None

        logger.info("AtlasOS Kernel startup started.")

        try:
            for service in self._startup_order:
                logger.info(
                    "Starting service: %s",
                    service.metadata.name,
                )

                service.start()

                if service.state != ServiceState.RUNNING:
                    raise KernelStartupError(
                        f"Service '{service.metadata.name}' did not enter "
                        f"RUNNING state. Current state: {service.state}"
                    )

                self._started_services.append(service)

            with self._lock:
                self._started_at = datetime.now(UTC)
                self._state = KernelState.RUNNING

            logger.info(
                "AtlasOS Kernel is RUNNING with %d services.",
                len(self._started_services),
            )

        except Exception as exc:
            logger.exception(
                "AtlasOS startup failed. Rolling back started services."
            )

            self._rollback_started_services()
            self._mark_failed(exc)

            raise KernelStartupError(
                f"AtlasOS startup failed: {exc}"
            ) from exc

    def stop(self) -> None:
        """
        Stop all running services in reverse startup order.
        """

        with self._lock:
            if self._state == KernelState.STOPPED:
                return

            if self._state not in {
                KernelState.RUNNING,
                KernelState.FAILED,
                KernelState.READY,
            }:
                raise InvalidKernelStateError(
                    "Kernel stop requires RUNNING, READY or FAILED state. "
                    f"Current state: {self._state}"
                )

            self._state = KernelState.STOPPING

        logger.info("AtlasOS Kernel shutdown started.")

        stop_errors: list[str] = []

        for service in reversed(self._started_services):
            try:
                logger.info(
                    "Stopping service: %s",
                    service.metadata.name,
                )
                service.stop()

            except Exception as exc:
                message = (
                    f"{service.metadata.name}: "
                    f"{type(exc).__name__}: {exc}"
                )
                stop_errors.append(message)

                logger.exception(
                    "Service shutdown failed: %s",
                    service.metadata.name,
                )

        with self._lock:
            self._started_services.clear()
            self._stopped_at = datetime.now(UTC)

            if stop_errors:
                self._last_error = "; ".join(stop_errors)
                self._state = KernelState.FAILED
            else:
                self._state = KernelState.STOPPED

        if stop_errors:
            raise KernelError(
                "AtlasOS shutdown completed with errors: "
                + "; ".join(stop_errors)
            )

        logger.info("AtlasOS Kernel stopped successfully.")

    def health(self) -> dict[str, Any]:
        """
        Return the full AtlasOS health report.
        """

        reports = self.registry.health_reports()

        return {
            "kernel": {
                "name": self.NAME,
                "version": self.VERSION,
                "state": self.state.value,
                "healthy": self.state == KernelState.RUNNING,
            },
            "services": [
                {
                    "name": report.service_name,
                    "state": report.state.value,
                    "message": report.message,
                    "details": dict(report.details),
                    "checked_at": report.checked_at.isoformat(),
                }
                for report in reports
            ],
        }

    def snapshot(self) -> KernelSnapshot:
        """
        Return an immutable kernel status snapshot.
        """

        reports = self.registry.health_reports()

        healthy = sum(
            report.state == HealthState.HEALTHY
            for report in reports
        )
        degraded = sum(
            report.state == HealthState.DEGRADED
            for report in reports
        )
        unhealthy = sum(
            report.state == HealthState.UNHEALTHY
            for report in reports
        )

        running = sum(
            service.state == ServiceState.RUNNING
            for service in self.registry.list_services()
        )

        uptime_seconds = 0.0

        if self._started_at is not None:
            end_time = self._stopped_at or datetime.now(UTC)
            uptime_seconds = max(
                0.0,
                (end_time - self._started_at).total_seconds(),
            )

        return KernelSnapshot(
            version=self.VERSION,
            state=self.state,
            registered_services=self.registry.count(),
            running_services=running,
            healthy_services=healthy,
            degraded_services=degraded,
            unhealthy_services=unhealthy,
            started_at=self._started_at,
            stopped_at=self._stopped_at,
            uptime_seconds=uptime_seconds,
            last_error=self._last_error,
        )

    def _rollback_started_services(self) -> None:
        """
        Stop services that started before a startup failure.
        """

        for service in reversed(self._started_services):
            try:
                service.stop()
            except Exception:
                logger.exception(
                    "Rollback failed for service: %s",
                    service.metadata.name,
                )

        self._started_services.clear()

    def _mark_failed(self, error: Exception) -> None:
        """
        Move the kernel into FAILED state.
        """

        with self._lock:
            self._last_error = (
                f"{type(error).__name__}: {error}"
            )
            self._state = KernelState.FAILED

        logger.error(
            "AtlasOS Kernel entered FAILED state: %s",
            self._last_error,
        )

    def __enter__(self) -> AtlasKernel:
        """
        Start the kernel when entering a context manager.
        """

        self.start()
        return self

    def __exit__(
        self,
        exc_type: object,
        exc_value: object,
        traceback: object,
    ) -> None:
        """
        Stop the kernel when leaving a context manager.
        """

        if self.state in {
            KernelState.RUNNING,
            KernelState.READY,
            KernelState.FAILED,
        }:
            self.stop()