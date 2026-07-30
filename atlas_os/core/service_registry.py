"""
============================================================
ATLAS OS SERVICE REGISTRY v1.0
============================================================

Central registry for AtlasOS managed services.

Responsibilities
----------------
- Register services
- Prevent duplicate registrations
- Validate service dependencies
- Resolve deterministic startup order
- Expose service health and lifecycle snapshots
- Provide thread-safe service access

============================================================
"""

from __future__ import annotations

import logging

from collections import defaultdict, deque
from threading import RLock
from typing import Iterable

from atlas_os.core.contracts import (
    AtlasService,
    HealthReport,
    ServiceSnapshot,
)


logger = logging.getLogger("AtlasOS.ServiceRegistry")


class ServiceRegistryError(RuntimeError):
    """
    Base error raised by the AtlasOS service registry.
    """


class DuplicateServiceError(ServiceRegistryError):
    """
    Raised when a service name is registered more than once.
    """


class ServiceNotFoundError(ServiceRegistryError):
    """
    Raised when a requested service is not registered.
    """


class MissingDependencyError(ServiceRegistryError):
    """
    Raised when a declared dependency is not registered.
    """


class CircularDependencyError(ServiceRegistryError):
    """
    Raised when service dependencies contain a cycle.
    """


class ServiceRegistry:
    """
    Thread-safe central registry for AtlasOS services.

    The registry owns service discovery and dependency ordering.
    It does not directly control service startup or shutdown. That
    responsibility belongs to AtlasKernel.
    """

    VERSION = "1.0"
    NAME = "ServiceRegistry"

    def __init__(self) -> None:
        self._services: dict[str, AtlasService] = {}
        self._lock = RLock()

        logger.info(
            "AtlasOS Service Registry v%s initialized.",
            self.VERSION,
        )

    def register(
        self,
        service: AtlasService,
        *,
        replace: bool = False,
    ) -> None:
        """
        Register a service.

        Parameters
        ----------
        service:
            Service implementing the AtlasService contract.

        replace:
            Allow replacement of an existing registration. This should
            normally remain False in production.
        """

        if not isinstance(service, AtlasService):
            raise TypeError(
                "Registered service must implement AtlasService."
            )

        name = service.metadata.name

        with self._lock:
            if name in self._services and not replace:
                raise DuplicateServiceError(
                    f"Service '{name}' is already registered."
                )

            self._services[name] = service

        logger.info(
            "Service registered: %s v%s",
            service.metadata.name,
            service.metadata.version,
        )

    def unregister(self, name: str) -> AtlasService:
        """
        Remove and return a registered service.
        """

        with self._lock:
            try:
                service = self._services.pop(name)
            except KeyError as exc:
                raise ServiceNotFoundError(
                    f"Service '{name}' is not registered."
                ) from exc

        logger.info("Service unregistered: %s", name)

        return service

    def get(self, name: str) -> AtlasService:
        """
        Retrieve a service by name.
        """

        with self._lock:
            try:
                return self._services[name]
            except KeyError as exc:
                raise ServiceNotFoundError(
                    f"Service '{name}' is not registered."
                ) from exc

    def contains(self, name: str) -> bool:
        """
        Return True when a service is registered.
        """

        with self._lock:
            return name in self._services

    def list_services(self) -> tuple[AtlasService, ...]:
        """
        Return services in registration order.
        """

        with self._lock:
            return tuple(self._services.values())

    def names(self) -> tuple[str, ...]:
        """
        Return registered service names.
        """

        with self._lock:
            return tuple(self._services.keys())

    def count(self) -> int:
        """
        Return the number of registered services.
        """

        with self._lock:
            return len(self._services)

    def validate_dependencies(self) -> None:
        """
        Validate that all declared dependencies exist.
        """

        with self._lock:
            registered_names = set(self._services)

            for service in self._services.values():
                for dependency in service.metadata.dependencies:
                    if dependency not in registered_names:
                        raise MissingDependencyError(
                            f"Service '{service.metadata.name}' requires "
                            f"missing dependency '{dependency}'."
                        )

    def resolve_startup_order(self) -> tuple[AtlasService, ...]:
        """
        Resolve services into dependency-safe startup order.

        Uses Kahn's topological sorting algorithm.
        """

        with self._lock:
            self.validate_dependencies()

            services = dict(self._services)

        in_degree: dict[str, int] = {
            name: 0
            for name in services
        }

        dependents: dict[str, list[str]] = defaultdict(list)

        for name, service in services.items():
            for dependency in service.metadata.dependencies:
                in_degree[name] += 1
                dependents[dependency].append(name)

        ready = deque(
            name
            for name in services
            if in_degree[name] == 0
        )

        ordered_names: list[str] = []

        while ready:
            current = ready.popleft()
            ordered_names.append(current)

            for dependent in dependents[current]:
                in_degree[dependent] -= 1

                if in_degree[dependent] == 0:
                    ready.append(dependent)

        if len(ordered_names) != len(services):
            cyclic_services = sorted(
                name
                for name, degree in in_degree.items()
                if degree > 0
            )

            raise CircularDependencyError(
                "Circular service dependency detected: "
                + ", ".join(cyclic_services)
            )

        return tuple(
            services[name]
            for name in ordered_names
        )

    def health_reports(self) -> tuple[HealthReport, ...]:
        """
        Collect health reports from all services.
        """

        reports: list[HealthReport] = []

        for service in self.list_services():
            reports.append(service.health_check())

        return tuple(reports)

    def snapshots(self) -> tuple[ServiceSnapshot, ...]:
        """
        Collect lifecycle snapshots from all services.
        """

        return tuple(
            service.snapshot()
            for service in self.list_services()
        )

    def register_many(
        self,
        services: Iterable[AtlasService],
    ) -> None:
        """
        Register multiple services.
        """

        for service in services:
            self.register(service)

    def clear(self) -> None:
        """
        Clear the registry.

        This operation does not stop running services and is intended
        primarily for tests and controlled shutdown procedures.
        """

        with self._lock:
            self._services.clear()

        logger.info("Service registry cleared.")