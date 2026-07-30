"""
============================================================
ATLAS OS SERVICE CONTRACTS v1.0
============================================================

Core service lifecycle contracts for AtlasOS.

Responsibilities
----------------
- Define service lifecycle states
- Define service metadata
- Establish a standard interface for AtlasOS services
- Provide lifecycle validation
- Provide health and diagnostic contracts

Design Principles
-----------------
- Explicit lifecycle management
- Fail-safe startup and shutdown
- Observable service health
- Dependency-aware initialization
- No hidden global state

============================================================
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any, Mapping


class ServiceState(StrEnum):
    """
    Lifecycle states shared by all AtlasOS services.
    """

    CREATED = "CREATED"
    INITIALIZING = "INITIALIZING"
    READY = "READY"
    STARTING = "STARTING"
    RUNNING = "RUNNING"
    STOPPING = "STOPPING"
    STOPPED = "STOPPED"
    FAILED = "FAILED"


class HealthState(StrEnum):
    """
    Standard health states exposed by AtlasOS services.
    """

    HEALTHY = "HEALTHY"
    DEGRADED = "DEGRADED"
    UNHEALTHY = "UNHEALTHY"
    UNKNOWN = "UNKNOWN"


@dataclass(frozen=True, slots=True)
class ServiceMetadata:
    """
    Immutable identity and dependency information for a service.
    """

    name: str
    version: str
    description: str = ""
    dependencies: tuple[str, ...] = ()
    critical: bool = True
    tags: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not self.name.strip():
            raise ValueError("Service name cannot be empty.")

        if not self.version.strip():
            raise ValueError(
                f"Service '{self.name}' must declare a version."
            )

        if self.name in self.dependencies:
            raise ValueError(
                f"Service '{self.name}' cannot depend on itself."
            )


@dataclass(frozen=True, slots=True)
class HealthReport:
    """
    Standard health report returned by every AtlasOS service.
    """

    service_name: str
    state: HealthState
    message: str = ""
    details: Mapping[str, Any] = field(default_factory=dict)
    checked_at: datetime = field(
        default_factory=lambda: datetime.now(UTC)
    )


@dataclass(frozen=True, slots=True)
class ServiceSnapshot:
    """
    Serializable service status snapshot.
    """

    name: str
    version: str
    state: ServiceState
    critical: bool
    dependencies: tuple[str, ...]
    started_at: datetime | None
    stopped_at: datetime | None
    last_error: str | None


class AtlasService(ABC):
    """
    Base contract for every service managed by AtlasOS.

    Services must implement:

    - initialize()
    - start()
    - stop()
    - health_check()

    The registry and kernel use this interface without needing to know
    implementation-specific details.
    """

    @property
    @abstractmethod
    def metadata(self) -> ServiceMetadata:
        """
        Return immutable service metadata.
        """

    @property
    @abstractmethod
    def state(self) -> ServiceState:
        """
        Return the current lifecycle state.
        """

    @abstractmethod
    def initialize(self) -> None:
        """
        Prepare internal resources without starting active work.
        """

    @abstractmethod
    def start(self) -> None:
        """
        Start the service.
        """

    @abstractmethod
    def stop(self) -> None:
        """
        Stop the service and release resources.
        """

    @abstractmethod
    def health_check(self) -> HealthReport:
        """
        Return current service health.
        """

    @abstractmethod
    def snapshot(self) -> ServiceSnapshot:
        """
        Return a serializable lifecycle snapshot.
        """