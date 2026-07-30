"""
============================================================
ATLAS OS KERNEL v1.0
============================================================

Central runtime kernel for Project Atlas AI.

Responsibilities
----------------
- Maintain AtlasOS system identity
- Own the dependency-aware service manager
- Coordinate system startup
- Coordinate safe shutdown
- Track runtime state
- Track startup and shutdown timestamps
- Calculate system uptime
- Aggregate service health
- Produce diagnostic snapshots
- Capture kernel lifecycle failures
- Provide a stable AtlasOS entry point

Architecture
------------
AtlasOSKernel
    |
    +-- DependencyServiceManager
            |
            +-- ServiceRegistry
                    |
                    +-- AtlasService implementations

Design principles
-----------------
- Thread safe
- Deterministic lifecycle
- Idempotent startup and shutdown
- No trading-specific behavior
- No direct exchange dependency
- No direct database dependency
- Safe for gradual legacy integration
- Observable and testable

============================================================
"""

from __future__ import annotations

import logging
import threading

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from types import MappingProxyType
from typing import Any, Iterable, Mapping

from atlas_os.contracts import (
    AtlasService,
    HealthStatus,
    ServiceState,
)
from atlas_os.services import (
    DependencyDeclaration,
    DependencyServiceManager,
    OrchestrationPlan,
    OrchestrationResult,
    RegistryHealthReport,
)


logger = logging.getLogger(
    "AtlasAI.AtlasOS.Kernel"
)


class KernelState(StrEnum):
    """
    Standard AtlasOS kernel lifecycle states.
    """

    CREATED = "CREATED"
    STARTING = "STARTING"
    RUNNING = "RUNNING"
    DEGRADED = "DEGRADED"
    STOPPING = "STOPPING"
    STOPPED = "STOPPED"
    FAILED = "FAILED"


class KernelLifecycleError(RuntimeError):
    """
    Raised when an invalid kernel lifecycle transition occurs.
    """


@dataclass(frozen=True, slots=True)
class KernelIdentity:
    """
    Immutable AtlasOS system identity.
    """

    name: str = "AtlasOS"
    version: str = "1.0.0"
    platform_name: str = "Project Atlas AI"
    environment: str = "DEVELOPMENT"
    description: str = (
        "Enterprise operating system kernel for Project Atlas AI."
    )

    def __post_init__(self) -> None:

        if not self.name.strip():
            raise ValueError(
                "Kernel name cannot be empty."
            )

        if not self.version.strip():
            raise ValueError(
                "Kernel version cannot be empty."
            )

        if not self.platform_name.strip():
            raise ValueError(
                "Platform name cannot be empty."
            )

        if not self.environment.strip():
            raise ValueError(
                "Kernel environment cannot be empty."
            )


@dataclass(frozen=True, slots=True)
class KernelHealthReport:
    """
    Aggregated health report of the AtlasOS kernel.
    """

    kernel_name: str
    kernel_state: KernelState
    status: HealthStatus
    service_health: RegistryHealthReport
    message: str
    uptime_seconds: float
    last_error: str | None = None
    checked_at: datetime = field(
        default_factory=lambda: datetime.now(UTC)
    )

    @property
    def is_operational(self) -> bool:
        """
        Return True when the kernel can continue operating.
        """

        return (
            self.kernel_state
            in {
                KernelState.RUNNING,
                KernelState.DEGRADED,
            }
            and self.status
            in {
                HealthStatus.HEALTHY,
                HealthStatus.DEGRADED,
            }
        )


@dataclass(frozen=True, slots=True)
class KernelSnapshot:
    """
    Immutable AtlasOS kernel diagnostic snapshot.
    """

    identity: KernelIdentity
    state: KernelState
    health: KernelHealthReport
    service_count: int
    dependencies: tuple[DependencyDeclaration, ...]
    startup_plan: OrchestrationPlan | None
    last_start_result: OrchestrationResult | None
    last_stop_result: OrchestrationResult | None
    created_at: datetime
    started_at: datetime | None
    stopped_at: datetime | None
    uptime_seconds: float
    metadata: Mapping[str, Any]
    generated_at: datetime = field(
        default_factory=lambda: datetime.now(UTC)
    )


class AtlasOSKernel:
    """
    Central runtime coordinator of AtlasOS.

    The kernel does not implement trading, risk, portfolio, market
    analysis or execution behavior. It coordinates Atlas services
    that implement those responsibilities.

    Example
    -------
    kernel = AtlasOSKernel()

    kernel.register_service(
        market_feed_service
    )

    kernel.register_service(
        risk_service,
        dependencies=("MarketFeedService",),
    )

    kernel.start()

    report = kernel.health()

    kernel.stop()
    """

    VERSION = "1.0.0"

    NAME = "AtlasOSKernel"

    def __init__(
        self,
        *,
        identity: KernelIdentity | None = None,
        service_manager: DependencyServiceManager | None = None,
        metadata: Mapping[str, Any] | None = None,
    ) -> None:

        self._identity = (
            identity
            if identity is not None
            else KernelIdentity()
        )

        self._service_manager = (
            service_manager
            if service_manager is not None
            else DependencyServiceManager()
        )

        self._state = KernelState.CREATED

        self._created_at = datetime.now(UTC)
        self._started_at: datetime | None = None
        self._stopped_at: datetime | None = None

        self._last_error: str | None = None

        self._last_start_result: (
            OrchestrationResult | None
        ) = None

        self._last_stop_result: (
            OrchestrationResult | None
        ) = None

        self._startup_plan: (
            OrchestrationPlan | None
        ) = None

        self._metadata: dict[str, Any] = dict(
            metadata or {}
        )

        self._lock = threading.RLock()

    # =====================================================
    # PROPERTIES
    # =====================================================

    @property
    def identity(self) -> KernelIdentity:
        """
        Return immutable kernel identity.
        """

        return self._identity

    @property
    def state(self) -> KernelState:
        """
        Return current kernel lifecycle state.
        """

        with self._lock:
            return self._state

    @property
    def service_manager(self) -> DependencyServiceManager:
        """
        Return dependency-aware service manager.
        """

        return self._service_manager

    @property
    def registry(self):
        """
        Return underlying service registry.
        """

        return self._service_manager.registry

    @property
    def service_count(self) -> int:
        """
        Return registered service count.
        """

        return self._service_manager.service_count

    @property
    def created_at(self) -> datetime:
        """
        Return kernel creation timestamp.
        """

        return self._created_at

    @property
    def started_at(self) -> datetime | None:
        """
        Return last successful startup timestamp.
        """

        with self._lock:
            return self._started_at

    @property
    def stopped_at(self) -> datetime | None:
        """
        Return last successful shutdown timestamp.
        """

        with self._lock:
            return self._stopped_at

    @property
    def last_error(self) -> str | None:
        """
        Return most recent kernel lifecycle error.
        """

        with self._lock:
            return self._last_error

    @property
    def is_running(self) -> bool:
        """
        Return True when kernel is running or degraded.
        """

        return self.state in {
            KernelState.RUNNING,
            KernelState.DEGRADED,
        }

    @property
    def uptime(self) -> timedelta:
        """
        Return current or most recent runtime duration.
        """

        with self._lock:

            if self._started_at is None:
                return timedelta(0)

            endpoint = (
                datetime.now(UTC)
                if self._state
                in {
                    KernelState.RUNNING,
                    KernelState.DEGRADED,
                    KernelState.STARTING,
                    KernelState.STOPPING,
                }
                else (
                    self._stopped_at
                    or datetime.now(UTC)
                )
            )

            elapsed = endpoint - self._started_at

            if elapsed.total_seconds() < 0:
                return timedelta(0)

            return elapsed

    @property
    def uptime_seconds(self) -> float:
        """
        Return uptime in seconds.
        """

        return self.uptime.total_seconds()

    # =====================================================
    # SERVICE REGISTRATION
    # =====================================================

    def register_service(
        self,
        service: AtlasService,
        *,
        dependencies: Iterable[str] = (),
    ) -> None:
        """
        Register an AtlasOS-managed service.

        Services cannot be registered while the kernel is starting,
        running, degraded or stopping.
        """

        with self._lock:

            self._ensure_configuration_state(
                operation="register services"
            )

            self._service_manager.register(
                service,
                dependencies=dependencies,
            )

            self._startup_plan = None

    def unregister_service(
        self,
        service_name: str,
        *,
        stop_if_running: bool = False,
        allow_dependants: bool = False,
    ) -> AtlasService:
        """
        Unregister a managed service.
        """

        with self._lock:

            self._ensure_configuration_state(
                operation="unregister services"
            )

            removed = (
                self._service_manager.unregister(
                    service_name,
                    stop_if_running=stop_if_running,
                    allow_dependants=allow_dependants,
                )
            )

            self._startup_plan = None

            return removed

    # =====================================================
    # VALIDATION / PLANNING
    # =====================================================

    def validate(self) -> None:
        """
        Validate AtlasOS service dependency graph.
        """

        self._service_manager.validate()

    def plan(self) -> OrchestrationPlan:
        """
        Calculate and store complete startup plan.
        """

        with self._lock:

            plan = self._service_manager.plan_all()

            self._startup_plan = plan

            return plan

    # =====================================================
    # STARTUP
    # =====================================================

    def start(
        self,
        *,
        rollback_on_failure: bool = True,
    ) -> OrchestrationResult:
        """
        Start AtlasOS and all registered services.

        Startup is idempotent when the kernel is already running.
        """

        with self._lock:

            if self._state in {
                KernelState.RUNNING,
                KernelState.DEGRADED,
            }:

                if self._last_start_result is not None:
                    return self._last_start_result

                return OrchestrationResult(
                    operation="START",
                    success=True,
                    steps=(),
                )

            if self._state in {
                KernelState.STARTING,
                KernelState.STOPPING,
            }:
                raise KernelLifecycleError(
                    f"Kernel cannot start while state is "
                    f"{self._state.value}."
                )

            self._state = KernelState.STARTING
            self._last_error = None

            try:

                self.validate()

                self._startup_plan = self.plan()

                result = self._service_manager.start_all(
                    rollback_on_failure=rollback_on_failure,
                )

                self._last_start_result = result

                if result.success:

                    self._started_at = datetime.now(UTC)
                    self._stopped_at = None

                    service_health = (
                        self.registry.health()
                    )

                    if (
                        service_health.status
                        == HealthStatus.DEGRADED
                    ):
                        self._state = (
                            KernelState.DEGRADED
                        )
                    else:
                        self._state = (
                            KernelState.RUNNING
                        )

                    logger.info(
                        "AtlasOS kernel started: %s v%s | "
                        "services=%s",
                        self.identity.name,
                        self.identity.version,
                        self.service_count,
                    )

                else:

                    self._state = KernelState.FAILED

                    self._last_error = (
                        "One or more AtlasOS services failed "
                        "during startup."
                    )

                    logger.error(
                        "AtlasOS kernel startup failed."
                    )

                return result

            except Exception as exc:

                self._last_error = (
                    f"{type(exc).__name__}: {exc}"
                )

                self._state = KernelState.FAILED

                logger.exception(
                    "AtlasOS kernel lifecycle startup failure."
                )

                raise

    # =====================================================
    # SHUTDOWN
    # =====================================================

    def stop(self) -> OrchestrationResult:
        """
        Stop all AtlasOS services safely.

        Shutdown is idempotent.
        """

        with self._lock:

            if self._state in {
                KernelState.CREATED,
                KernelState.STOPPED,
            }:

                self._state = KernelState.STOPPED

                if self._stopped_at is None:
                    self._stopped_at = datetime.now(UTC)

                if self._last_stop_result is not None:
                    return self._last_stop_result

                result = OrchestrationResult(
                    operation="STOP",
                    success=True,
                    steps=(),
                )

                self._last_stop_result = result

                return result

            if self._state == KernelState.STOPPING:

                if self._last_stop_result is not None:
                    return self._last_stop_result

                return OrchestrationResult(
                    operation="STOP",
                    success=True,
                    steps=(),
                )

            if self._state == KernelState.STARTING:
                raise KernelLifecycleError(
                    "Kernel cannot stop while startup "
                    "is in progress."
                )

            self._state = KernelState.STOPPING

            try:

                result = self._service_manager.stop_all()

                self._last_stop_result = result

                self._stopped_at = datetime.now(UTC)

                if result.success:

                    self._state = KernelState.STOPPED

                    logger.info(
                        "AtlasOS kernel stopped: %s",
                        self.identity.name,
                    )

                else:

                    self._state = KernelState.FAILED

                    self._last_error = (
                        "One or more AtlasOS services failed "
                        "during shutdown."
                    )

                    logger.error(
                        "AtlasOS kernel shutdown completed "
                        "with failures."
                    )

                return result

            except Exception as exc:

                self._last_error = (
                    f"{type(exc).__name__}: {exc}"
                )

                self._state = KernelState.FAILED

                logger.exception(
                    "AtlasOS kernel lifecycle shutdown failure."
                )

                raise

    # =====================================================
    # HEALTH
    # =====================================================

    def health(self) -> KernelHealthReport:
        """
        Return aggregated AtlasOS kernel health.
        """

        with self._lock:

            service_health = self.registry.health()

            if self._state == KernelState.RUNNING:

                if (
                    service_health.status
                    == HealthStatus.UNHEALTHY
                ):
                    status = HealthStatus.UNHEALTHY
                    message = (
                        "Kernel is running but one or more "
                        "services are unhealthy."
                    )

                elif (
                    service_health.status
                    == HealthStatus.DEGRADED
                ):
                    status = HealthStatus.DEGRADED
                    message = (
                        "Kernel is operating with degraded "
                        "services."
                    )

                else:
                    status = HealthStatus.HEALTHY
                    message = (
                        "Kernel and all services are operating "
                        "normally."
                    )

            elif self._state == KernelState.DEGRADED:

                status = HealthStatus.DEGRADED
                message = (
                    "Kernel is operating in degraded mode."
                )

            elif self._state == KernelState.FAILED:

                status = HealthStatus.UNHEALTHY
                message = (
                    self._last_error
                    or "Kernel lifecycle failed."
                )

            else:

                status = HealthStatus.UNKNOWN
                message = (
                    f"Kernel is not operational. "
                    f"State={self._state.value}."
                )

            return KernelHealthReport(
                kernel_name=self.identity.name,
                kernel_state=self._state,
                status=status,
                service_health=service_health,
                message=message,
                uptime_seconds=self.uptime_seconds,
                last_error=self._last_error,
            )

    # =====================================================
    # STATE SYNCHRONIZATION
    # =====================================================

    def synchronize_state(self) -> KernelState:
        """
        Synchronize kernel state with current service health.

        This can be called by a future health monitor.
        """

        with self._lock:

            if self._state not in {
                KernelState.RUNNING,
                KernelState.DEGRADED,
            }:
                return self._state

            service_health = self.registry.health()

            if (
                service_health.status
                == HealthStatus.UNHEALTHY
            ):
                self._state = KernelState.DEGRADED

                self._last_error = (
                    "One or more AtlasOS services are unhealthy."
                )

            elif (
                service_health.status
                == HealthStatus.DEGRADED
            ):
                self._state = KernelState.DEGRADED

                self._last_error = (
                    "One or more AtlasOS services are degraded."
                )

            elif (
                service_health.status
                == HealthStatus.HEALTHY
            ):
                self._state = KernelState.RUNNING
                self._last_error = None

            return self._state

    # =====================================================
    # METADATA
    # =====================================================

    def set_metadata(
        self,
        key: str,
        value: Any,
    ) -> None:
        """
        Set runtime kernel metadata.
        """

        normalized_key = key.strip()

        if not normalized_key:
            raise ValueError(
                "Metadata key cannot be empty."
            )

        with self._lock:
            self._metadata[normalized_key] = value

    def metadata(self) -> Mapping[str, Any]:
        """
        Return immutable metadata copy.
        """

        with self._lock:

            return MappingProxyType(
                self._metadata.copy()
            )

    # =====================================================
    # SNAPSHOT
    # =====================================================

    def snapshot(self) -> KernelSnapshot:
        """
        Return a complete AtlasOS kernel diagnostic snapshot.
        """

        with self._lock:

            return KernelSnapshot(
                identity=self.identity,
                state=self._state,
                health=self.health(),
                service_count=self.service_count,
                dependencies=(
                    self._service_manager.declarations()
                ),
                startup_plan=self._startup_plan,
                last_start_result=self._last_start_result,
                last_stop_result=self._last_stop_result,
                created_at=self._created_at,
                started_at=self._started_at,
                stopped_at=self._stopped_at,
                uptime_seconds=self.uptime_seconds,
                metadata=MappingProxyType(
                    self._metadata.copy()
                ),
            )

    # =====================================================
    # INTERNAL VALIDATION
    # =====================================================

    def _ensure_configuration_state(
        self,
        *,
        operation: str,
    ) -> None:
        """
        Ensure services are modified only while kernel is offline.
        """

        if self._state in {
            KernelState.STARTING,
            KernelState.RUNNING,
            KernelState.DEGRADED,
            KernelState.STOPPING,
        }:
            raise KernelLifecycleError(
                f"Kernel cannot {operation} while state is "
                f"{self._state.value}."
            )