"""
============================================================
ATLAS OS SERVICE CONTRACTS v1.0
============================================================

Enterprise service lifecycle contracts for Project Atlas AI.

Purpose
-------
This module defines the common service language used by AtlasOS.

Every managed Atlas service will eventually expose:

- Identity
- Version
- Lifecycle state
- Start operation
- Stop operation
- Health information
- Diagnostic snapshot

Design principles
-----------------
- Framework independent
- Threading independent
- Exchange independent
- Trading independent
- Safe for gradual legacy integration
- No production side effects

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
    Standard lifecycle states for every AtlasOS-managed service.
    """

    CREATED = "CREATED"
    STARTING = "STARTING"
    RUNNING = "RUNNING"
    DEGRADED = "DEGRADED"
    STOPPING = "STOPPING"
    STOPPED = "STOPPED"
    FAILED = "FAILED"


class HealthStatus(StrEnum):
    """
    Standard health conditions reported by Atlas services.
    """

    HEALTHY = "HEALTHY"
    DEGRADED = "DEGRADED"
    UNHEALTHY = "UNHEALTHY"
    UNKNOWN = "UNKNOWN"


@dataclass(frozen=True, slots=True)
class ServiceIdentity:
    """
    Immutable identity of an Atlas service.
    """

    name: str
    version: str
    service_type: str
    description: str = ""

    def __post_init__(self) -> None:
        if not self.name.strip():
            raise ValueError("Service name cannot be empty.")

        if not self.version.strip():
            raise ValueError("Service version cannot be empty.")

        if not self.service_type.strip():
            raise ValueError("Service type cannot be empty.")


@dataclass(frozen=True, slots=True)
class HealthReport:
    """
    Immutable health report returned by an Atlas service.
    """

    service_name: str
    status: HealthStatus
    state: ServiceState
    message: str = ""
    checked_at: datetime = field(
        default_factory=lambda: datetime.now(UTC)
    )
    details: Mapping[str, Any] = field(default_factory=dict)

    @property
    def is_operational(self) -> bool:
        """
        Return True when the service can continue operating.
        """

        return self.status in {
            HealthStatus.HEALTHY,
            HealthStatus.DEGRADED,
        }


@dataclass(frozen=True, slots=True)
class ServiceSnapshot:
    """
    Diagnostic snapshot of an Atlas service.
    """

    identity: ServiceIdentity
    state: ServiceState
    health: HealthReport
    started_at: datetime | None = None
    stopped_at: datetime | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)


class AtlasService(ABC):
    """
    Base contract implemented by AtlasOS-managed services.

    This interface deliberately contains no threading, scheduling,
    database, exchange or trading implementation. Those concerns
    belong to specialized AtlasOS components.
    """

    @property
    @abstractmethod
    def identity(self) -> ServiceIdentity:
        """
        Return immutable service identity.
        """

        raise NotImplementedError

    @property
    @abstractmethod
    def state(self) -> ServiceState:
        """
        Return the current lifecycle state.
        """

        raise NotImplementedError

    @abstractmethod
    def start(self) -> None:
        """
        Start the service.

        Implementations must make repeated calls safe or explicitly
        reject invalid lifecycle transitions.
        """

        raise NotImplementedError

    @abstractmethod
    def stop(self) -> None:
        """
        Stop the service safely.
        """

        raise NotImplementedError

    @abstractmethod
    def health(self) -> HealthReport:
        """
        Return the current service health report.
        """

        raise NotImplementedError

    @abstractmethod
    def snapshot(self) -> ServiceSnapshot:
        """
        Return a diagnostic snapshot for observability and audit.
        """

        raise NotImplementedError