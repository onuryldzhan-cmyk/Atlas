"""
============================================================
ATLAS OS SERVICE REGISTRY v1.0
============================================================

Central service registration and lifecycle coordination system.

Responsibilities
----------------
- Register AtlasOS services
- Prevent duplicate service names
- Retrieve services by name
- Remove services safely
- Start services individually
- Start all registered services
- Stop services individually
- Stop all services in reverse order
- Collect health reports
- Produce registry snapshots
- Isolate lifecycle failures

Design principles
-----------------
- Thread safe
- Deterministic startup order
- Reverse shutdown order
- No trading-specific dependencies
- No exchange-specific dependencies
- Safe failure isolation
- Gradual legacy integration support

============================================================
"""

from __future__ import annotations

import logging
import threading

from dataclasses import dataclass, field
from datetime import UTC, datetime
from types import MappingProxyType
from typing import Mapping

from atlas_os.contracts import (
    AtlasService,
    HealthReport,
    HealthStatus,
    ServiceSnapshot,
    ServiceState,
)


logger = logging.getLogger(
    "AtlasAI.AtlasOS.ServiceRegistry"
)


class ServiceRegistryError(RuntimeError):
    """
    Base exception for service registry operations.
    """


class DuplicateServiceError(ServiceRegistryError):
    """
    Raised when a service name is already registered.
    """


class ServiceNotFoundError(ServiceRegistryError):
    """
    Raised when a requested service is not registered.
    """


class ServiceRemovalError(ServiceRegistryError):
    """
    Raised when a running service is removed unsafely.
    """


@dataclass(frozen=True, slots=True)
class ServiceOperationResult:
    """
    Result of a service lifecycle operation.
    """

    service_name: str
    operation: str
    success: bool
    state: ServiceState
    message: str = ""
    error: str | None = None
    completed_at: datetime = field(
        default_factory=lambda: datetime.now(UTC)
    )


@dataclass(frozen=True, slots=True)
class RegistryHealthReport:
    """
    Aggregated health report for all registered services.
    """

    status: HealthStatus
    total_services: int
    healthy_services: int
    degraded_services: int
    unhealthy_services: int
    unknown_services: int
    reports: Mapping[str, HealthReport]
    checked_at: datetime = field(
        default_factory=lambda: datetime.now(UTC)
    )

    @property
    def is_operational(self) -> bool:
        """
        Return True when no registered service is unhealthy.
        """

        return self.unhealthy_services == 0


@dataclass(frozen=True, slots=True)
class RegistrySnapshot:
    """
    Immutable diagnostic snapshot of the registry.
    """

    service_count: int
    registration_order: tuple[str, ...]
    services: Mapping[str, ServiceSnapshot]
    health: RegistryHealthReport
    generated_at: datetime = field(
        default_factory=lambda: datetime.now(UTC)
    )


class ServiceRegistry:
    """
    Central registry for AtlasOS-managed services.

    Service names are treated as case-insensitive identifiers.

    Example
    -------
    registry = ServiceRegistry()

    registry.register(market_feed)
    registry.register(risk_service)

    registry.start_all()
    report = registry.health()
    registry.stop_all()
    """

    VERSION = "1.0.0"

    NAME = "AtlasOSServiceRegistry"

    def __init__(self) -> None:

        self._services: dict[str, AtlasService] = {}

        self._display_names: dict[str, str] = {}

        self._registration_order: list[str] = []

        self._lock = threading.RLock()

    # =====================================================
    # BASIC INFORMATION
    # =====================================================

    def __len__(self) -> int:
        """
        Return the number of registered services.
        """

        with self._lock:
            return len(self._services)

    def __contains__(
        self,
        service_name: object,
    ) -> bool:
        """
        Return True when a service name is registered.
        """

        if not isinstance(service_name, str):
            return False

        key = self._normalize_name(
            service_name
        )

        with self._lock:
            return key in self._services

    @property
    def service_count(self) -> int:
        """
        Return the number of registered services.
        """

        return len(self)

    @property
    def registration_order(self) -> tuple[str, ...]:
        """
        Return service names in deterministic registration order.
        """

        with self._lock:

            return tuple(
                self._display_names[key]
                for key in self._registration_order
            )

    # =====================================================
    # REGISTRATION
    # =====================================================

    def register(
        self,
        service: AtlasService,
    ) -> None:
        """
        Register an Atlas service.

        Duplicate names are rejected case-insensitively.
        """

        if not isinstance(service, AtlasService):
            raise TypeError(
                "Registered object must implement AtlasService."
            )

        service_name = service.identity.name.strip()

        key = self._normalize_name(
            service_name
        )

        with self._lock:

            if key in self._services:
                raise DuplicateServiceError(
                    f"Service '{service_name}' is already registered."
                )

            self._services[key] = service

            self._display_names[key] = service_name

            self._registration_order.append(
                key
            )

            logger.info(
                "AtlasOS service registered: %s v%s",
                service.identity.name,
                service.identity.version,
            )

    def unregister(
        self,
        service_name: str,
        *,
        stop_if_running: bool = False,
    ) -> AtlasService:
        """
        Remove and return a registered service.

        A running or degraded service cannot be removed unless
        stop_if_running is True.
        """

        key = self._normalize_name(
            service_name
        )

        with self._lock:

            service = self._get_required_by_key(
                key
            )

            if service.state in {
                ServiceState.RUNNING,
                ServiceState.DEGRADED,
                ServiceState.STARTING,
                ServiceState.STOPPING,
            }:

                if not stop_if_running:
                    raise ServiceRemovalError(
                        f"Service '{service.identity.name}' cannot "
                        f"be removed while state is "
                        f"{service.state.value}."
                    )

                service.stop()

            del self._services[key]
            del self._display_names[key]

            self._registration_order.remove(
                key
            )

            logger.info(
                "AtlasOS service unregistered: %s",
                service.identity.name,
            )

            return service

    # =====================================================
    # LOOKUP
    # =====================================================

    def get(
        self,
        service_name: str,
    ) -> AtlasService | None:
        """
        Return a registered service or None.
        """

        key = self._normalize_name(
            service_name
        )

        with self._lock:
            return self._services.get(key)

    def require(
        self,
        service_name: str,
    ) -> AtlasService:
        """
        Return a registered service.

        Raise ServiceNotFoundError when it does not exist.
        """

        key = self._normalize_name(
            service_name
        )

        with self._lock:
            return self._get_required_by_key(key)

    def services(self) -> tuple[AtlasService, ...]:
        """
        Return services in registration order.
        """

        with self._lock:

            return tuple(
                self._services[key]
                for key in self._registration_order
            )

    def names(self) -> tuple[str, ...]:
        """
        Return registered service names.
        """

        return self.registration_order

    # =====================================================
    # INDIVIDUAL LIFECYCLE
    # =====================================================

    def start(
        self,
        service_name: str,
    ) -> ServiceOperationResult:
        """
        Start one registered service.
        """

        service = self.require(
            service_name
        )

        return self._start_service(
            service
        )

    def stop(
        self,
        service_name: str,
    ) -> ServiceOperationResult:
        """
        Stop one registered service.
        """

        service = self.require(
            service_name
        )

        return self._stop_service(
            service
        )

    # =====================================================
    # BULK LIFECYCLE
    # =====================================================

    def start_all(
        self,
        *,
        stop_on_failure: bool = False,
        rollback_started: bool = False,
    ) -> tuple[ServiceOperationResult, ...]:
        """
        Start all services in registration order.

        Parameters
        ----------
        stop_on_failure:
            Stop starting additional services after the first failure.

        rollback_started:
            Stop services successfully started during this operation
            when a later service fails.
        """

        services = self.services()

        results: list[ServiceOperationResult] = []

        started_services: list[AtlasService] = []

        for service in services:

            result = self._start_service(
                service
            )

            results.append(
                result
            )

            if result.success:

                if service.state == ServiceState.RUNNING:
                    started_services.append(
                        service
                    )

                continue

            if rollback_started:

                for started_service in reversed(
                    started_services
                ):
                    self._stop_service(
                        started_service
                    )

            if stop_on_failure:
                break

        return tuple(results)

    def stop_all(
        self,
    ) -> tuple[ServiceOperationResult, ...]:
        """
        Stop all services in reverse registration order.

        Reverse shutdown helps dependent services stop before
        foundational services.
        """

        services = tuple(
            reversed(
                self.services()
            )
        )

        results: list[ServiceOperationResult] = []

        for service in services:

            results.append(
                self._stop_service(service)
            )

        return tuple(results)

    # =====================================================
    # HEALTH
    # =====================================================

    def health(self) -> RegistryHealthReport:
        """
        Return aggregated health for all services.
        """

        reports: dict[str, HealthReport] = {}

        healthy = 0
        degraded = 0
        unhealthy = 0
        unknown = 0

        for service in self.services():

            report = service.health()

            reports[
                service.identity.name
            ] = report

            if report.status == HealthStatus.HEALTHY:
                healthy += 1

            elif report.status == HealthStatus.DEGRADED:
                degraded += 1

            elif report.status == HealthStatus.UNHEALTHY:
                unhealthy += 1

            else:
                unknown += 1

        total = len(reports)

        if unhealthy > 0:
            overall_status = HealthStatus.UNHEALTHY

        elif degraded > 0:
            overall_status = HealthStatus.DEGRADED

        elif total > 0 and healthy == total:
            overall_status = HealthStatus.HEALTHY

        else:
            overall_status = HealthStatus.UNKNOWN

        return RegistryHealthReport(
            status=overall_status,
            total_services=total,
            healthy_services=healthy,
            degraded_services=degraded,
            unhealthy_services=unhealthy,
            unknown_services=unknown,
            reports=MappingProxyType(
                reports.copy()
            ),
        )

    # =====================================================
    # SNAPSHOT
    # =====================================================

    def snapshot(self) -> RegistrySnapshot:
        """
        Return an immutable registry diagnostic snapshot.
        """

        snapshots: dict[
            str,
            ServiceSnapshot,
        ] = {}

        for service in self.services():

            snapshots[
                service.identity.name
            ] = service.snapshot()

        return RegistrySnapshot(
            service_count=len(snapshots),
            registration_order=self.registration_order,
            services=MappingProxyType(
                snapshots.copy()
            ),
            health=self.health(),
        )

    # =====================================================
    # INTERNAL OPERATIONS
    # =====================================================

    def _start_service(
        self,
        service: AtlasService,
    ) -> ServiceOperationResult:
        """
        Start a service and convert exceptions to operation results.
        """

        try:

            service.start()

            return ServiceOperationResult(
                service_name=service.identity.name,
                operation="START",
                success=True,
                state=service.state,
                message="Service started successfully.",
            )

        except Exception as exc:

            error = (
                f"{type(exc).__name__}: {exc}"
            )

            logger.exception(
                "AtlasOS registry could not start service: %s",
                service.identity.name,
            )

            return ServiceOperationResult(
                service_name=service.identity.name,
                operation="START",
                success=False,
                state=service.state,
                message="Service startup failed.",
                error=error,
            )

    def _stop_service(
        self,
        service: AtlasService,
    ) -> ServiceOperationResult:
        """
        Stop a service and convert exceptions to operation results.
        """

        try:

            service.stop()

            return ServiceOperationResult(
                service_name=service.identity.name,
                operation="STOP",
                success=True,
                state=service.state,
                message="Service stopped successfully.",
            )

        except Exception as exc:

            error = (
                f"{type(exc).__name__}: {exc}"
            )

            logger.exception(
                "AtlasOS registry could not stop service: %s",
                service.identity.name,
            )

            return ServiceOperationResult(
                service_name=service.identity.name,
                operation="STOP",
                success=False,
                state=service.state,
                message="Service shutdown failed.",
                error=error,
            )

    def _get_required_by_key(
        self,
        key: str,
    ) -> AtlasService:
        """
        Return service by normalized key.
        """

        service = self._services.get(
            key
        )

        if service is None:
            raise ServiceNotFoundError(
                f"Service '{key}' is not registered."
            )

        return service

    @staticmethod
    def _normalize_name(
        service_name: str,
    ) -> str:
        """
        Normalize a service name for case-insensitive lookup.
        """

        if not isinstance(service_name, str):
            raise TypeError(
                "Service name must be a string."
            )

        normalized = service_name.strip().casefold()

        if not normalized:
            raise ValueError(
                "Service name cannot be empty."
            )

        return normalized