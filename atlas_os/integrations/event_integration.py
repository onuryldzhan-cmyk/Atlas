"""
============================================================
ATLAS OS KERNEL EVENT INTEGRATION v1.0
============================================================

Event-aware integration layer for AtlasOS Kernel and Health Monitor.

Responsibilities
----------------
- Publish kernel lifecycle events
- Publish service lifecycle events
- Publish health transition events
- Preserve existing AtlasOS Kernel behavior
- Preserve existing Health Monitor behavior
- Isolate Event Bus publication failures
- Attach correlation identifiers
- Standardize AtlasOS system event types
- Produce integration statistics

Architecture
------------
EventAwareAtlasOSKernel
    |
    +-- AtlasOSKernel
    +-- EventBusService

EventAwareHealthMonitorService
    |
    +-- HealthMonitorService
    +-- EventBusService

Design principles
-----------------
- No invasive modification of stable kernel code
- Backward compatible
- Event publication failure must not crash Kernel
- Event publication failure must not crash Health Monitor
- Deterministic lifecycle event generation
- Centralized event taxonomy

============================================================
"""

from __future__ import annotations

import logging
import threading
import uuid

from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any, Iterable, Mapping

from atlas_os.contracts import (
    AtlasService,
    HealthStatus,
)
from atlas_os.events import (
    EventBusService,
    EventSeverity,
    PublishResult,
)
from atlas_os.kernel import (
    AtlasOSKernel,
    KernelIdentity,
    KernelState,
)
from atlas_os.observability import (
    HealthMonitorService,
    HealthObservation,
    HealthTransition,
    HealthTransitionType,
)
from atlas_os.services import (
    DependencyServiceManager,
    OrchestrationAction,
    OrchestrationResult,
)


logger = logging.getLogger(
    "AtlasAI.AtlasOS.EventIntegration"
)


class AtlasSystemEventType(StrEnum):
    """
    Standard AtlasOS system event taxonomy.
    """

    KERNEL_STARTING = "KERNEL_STARTING"
    KERNEL_STARTED = "KERNEL_STARTED"
    KERNEL_START_FAILED = "KERNEL_START_FAILED"

    KERNEL_STOPPING = "KERNEL_STOPPING"
    KERNEL_STOPPED = "KERNEL_STOPPED"
    KERNEL_STOP_FAILED = "KERNEL_STOP_FAILED"

    SERVICE_STARTED = "SERVICE_STARTED"
    SERVICE_START_FAILED = "SERVICE_START_FAILED"
    SERVICE_START_SKIPPED = "SERVICE_START_SKIPPED"

    SERVICE_STOPPED = "SERVICE_STOPPED"
    SERVICE_STOP_FAILED = "SERVICE_STOP_FAILED"
    SERVICE_ROLLED_BACK = "SERVICE_ROLLED_BACK"

    HEALTH_MONITOR_INITIALIZED = (
        "HEALTH_MONITOR_INITIALIZED"
    )

    HEALTH_DEGRADED = "HEALTH_DEGRADED"
    HEALTH_RECOVERED = "HEALTH_RECOVERED"
    HEALTH_UNHEALTHY = "HEALTH_UNHEALTHY"

    KERNEL_STATE_CHANGED = "KERNEL_STATE_CHANGED"
    HEALTH_STATUS_CHANGED = "HEALTH_STATUS_CHANGED"

    EVENT_PUBLICATION_FAILED = (
        "EVENT_PUBLICATION_FAILED"
    )


@dataclass(frozen=True, slots=True)
class EventIntegrationStatistics:
    """
    Immutable event integration statistics.
    """

    publication_attempts: int
    successful_publications: int
    failed_publications: int
    last_event_type: str | None
    last_error: str | None
    generated_at: datetime = field(
        default_factory=lambda: datetime.now(UTC)
    )


class _SafeEventPublisher:
    """
    Shared safe Event Bus publication support.

    Event publication failures are captured rather than propagated
    into Kernel or Health Monitor lifecycle operations.
    """

    def _initialize_event_publisher(
        self,
        event_bus: EventBusService,
    ) -> None:

        if not isinstance(
            event_bus,
            EventBusService,
        ):
            raise TypeError(
                "event_bus must be an EventBusService instance."
            )

        self._event_bus = event_bus

        self._publication_attempts = 0
        self._successful_publications = 0
        self._failed_publications = 0

        self._last_published_event_type: (
            str | None
        ) = None

        self._last_publication_error: (
            str | None
        ) = None

        self._publisher_lock = threading.RLock()

    @property
    def event_bus(self) -> EventBusService:
        """
        Return associated Event Bus.
        """

        return self._event_bus

    def event_statistics(
        self,
    ) -> EventIntegrationStatistics:
        """
        Return immutable publication statistics.
        """

        with self._publisher_lock:

            return EventIntegrationStatistics(
                publication_attempts=(
                    self._publication_attempts
                ),
                successful_publications=(
                    self._successful_publications
                ),
                failed_publications=(
                    self._failed_publications
                ),
                last_event_type=(
                    self._last_published_event_type
                ),
                last_error=(
                    self._last_publication_error
                ),
            )

    def _publish_safely(
        self,
        *,
        event_type: AtlasSystemEventType | str,
        source: str,
        payload: Mapping[str, Any] | None = None,
        severity: EventSeverity = EventSeverity.INFO,
        correlation_id: str | None = None,
    ) -> PublishResult | None:
        """
        Publish an event without propagating Event Bus failures.
        """

        resolved_event_type = (
            event_type.value
            if isinstance(
                event_type,
                AtlasSystemEventType,
            )
            else str(event_type)
        )

        with self._publisher_lock:
            self._publication_attempts += 1

        try:

            result = self._event_bus.publish_event(
                event_type=resolved_event_type,
                source=source,
                payload=payload or {},
                severity=severity,
                correlation_id=correlation_id,
            )

            with self._publisher_lock:

                self._successful_publications += 1

                self._last_published_event_type = (
                    resolved_event_type
                )

                self._last_publication_error = None

            return result

        except Exception as exc:

            error = (
                f"{type(exc).__name__}: {exc}"
            )

            with self._publisher_lock:

                self._failed_publications += 1

                self._last_published_event_type = (
                    resolved_event_type
                )

                self._last_publication_error = error

            logger.exception(
                "AtlasOS system event publication failed | "
                "event=%s | source=%s",
                resolved_event_type,
                source,
            )

            return None


class EventAwareAtlasOSKernel(
    _SafeEventPublisher,
    AtlasOSKernel,
):
    """
    AtlasOS Kernel with automatic lifecycle event publication.

    The underlying AtlasOSKernel lifecycle behavior remains unchanged.
    """

    VERSION = "1.0.0"

    NAME = "EventAwareAtlasOSKernel"

    def __init__(
        self,
        event_bus: EventBusService,
        *,
        identity: KernelIdentity | None = None,
        service_manager: DependencyServiceManager | None = None,
        metadata: Mapping[str, Any] | None = None,
    ) -> None:

        AtlasOSKernel.__init__(
            self,
            identity=identity,
            service_manager=service_manager,
            metadata=metadata,
        )

        self._initialize_event_publisher(
            event_bus
        )

    # =====================================================
    # STARTUP
    # =====================================================

    def start(
        self,
        *,
        rollback_on_failure: bool = True,
    ) -> OrchestrationResult:
        """
        Start Kernel and publish lifecycle events.
        """

        if self.state in {
            KernelState.RUNNING,
            KernelState.DEGRADED,
        }:
            return super().start(
                rollback_on_failure=rollback_on_failure
            )

        correlation_id = self._new_correlation_id(
            "kernel-start"
        )

        self._publish_safely(
            event_type=(
                AtlasSystemEventType.KERNEL_STARTING
            ),
            source=self.identity.name,
            payload={
                "kernel_name": self.identity.name,
                "kernel_version": (
                    self.identity.version
                ),
                "environment": (
                    self.identity.environment
                ),
                "service_count": (
                    self.service_count
                ),
                "state": self.state.value,
            },
            severity=EventSeverity.INFO,
            correlation_id=correlation_id,
        )

        try:

            result = super().start(
                rollback_on_failure=rollback_on_failure
            )

        except Exception as exc:

            self._publish_safely(
                event_type=(
                    AtlasSystemEventType
                    .KERNEL_START_FAILED
                ),
                source=self.identity.name,
                payload={
                    "kernel_name": (
                        self.identity.name
                    ),
                    "state": self.state.value,
                    "error": (
                        f"{type(exc).__name__}: {exc}"
                    ),
                },
                severity=EventSeverity.CRITICAL,
                correlation_id=correlation_id,
            )

            raise

        self._publish_start_steps(
            result,
            correlation_id=correlation_id,
        )

        if result.success:

            self._publish_safely(
                event_type=(
                    AtlasSystemEventType.KERNEL_STARTED
                ),
                source=self.identity.name,
                payload={
                    "kernel_name": (
                        self.identity.name
                    ),
                    "kernel_version": (
                        self.identity.version
                    ),
                    "state": self.state.value,
                    "service_count": (
                        self.service_count
                    ),
                    "started_services": list(
                        result.started_services
                    ),
                    "uptime_seconds": (
                        self.uptime_seconds
                    ),
                },
                severity=EventSeverity.INFO,
                correlation_id=correlation_id,
            )

        else:

            self._publish_safely(
                event_type=(
                    AtlasSystemEventType
                    .KERNEL_START_FAILED
                ),
                source=self.identity.name,
                payload={
                    "kernel_name": (
                        self.identity.name
                    ),
                    "state": self.state.value,
                    "started_services": list(
                        result.started_services
                    ),
                    "skipped_services": list(
                        result.skipped_services
                    ),
                    "rolled_back_services": list(
                        result.rolled_back_services
                    ),
                    "error": self.last_error,
                },
                severity=EventSeverity.CRITICAL,
                correlation_id=correlation_id,
            )

        return result

    # =====================================================
    # SHUTDOWN
    # =====================================================

    def stop(self) -> OrchestrationResult:
        """
        Stop Kernel and publish lifecycle events.
        """

        if self.state in {
            KernelState.CREATED,
            KernelState.STOPPED,
        }:

            return super().stop()

        correlation_id = self._new_correlation_id(
            "kernel-stop"
        )

        self._publish_safely(
            event_type=(
                AtlasSystemEventType.KERNEL_STOPPING
            ),
            source=self.identity.name,
            payload={
                "kernel_name": self.identity.name,
                "state": self.state.value,
                "service_count": self.service_count,
                "uptime_seconds": (
                    self.uptime_seconds
                ),
            },
            severity=EventSeverity.INFO,
            correlation_id=correlation_id,
        )

        try:

            result = super().stop()

        except Exception as exc:

            self._publish_safely(
                event_type=(
                    AtlasSystemEventType
                    .KERNEL_STOP_FAILED
                ),
                source=self.identity.name,
                payload={
                    "kernel_name": (
                        self.identity.name
                    ),
                    "state": self.state.value,
                    "error": (
                        f"{type(exc).__name__}: {exc}"
                    ),
                },
                severity=EventSeverity.CRITICAL,
                correlation_id=correlation_id,
            )

            raise

        self._publish_stop_steps(
            result,
            correlation_id=correlation_id,
        )

        if result.success:

            self._publish_safely(
                event_type=(
                    AtlasSystemEventType.KERNEL_STOPPED
                ),
                source=self.identity.name,
                payload={
                    "kernel_name": (
                        self.identity.name
                    ),
                    "state": self.state.value,
                    "stopped_services": list(
                        result.stopped_services
                    ),
                    "uptime_seconds": (
                        self.uptime_seconds
                    ),
                },
                severity=EventSeverity.INFO,
                correlation_id=correlation_id,
            )

        else:

            self._publish_safely(
                event_type=(
                    AtlasSystemEventType
                    .KERNEL_STOP_FAILED
                ),
                source=self.identity.name,
                payload={
                    "kernel_name": (
                        self.identity.name
                    ),
                    "state": self.state.value,
                    "stopped_services": list(
                        result.stopped_services
                    ),
                    "error": self.last_error,
                },
                severity=EventSeverity.CRITICAL,
                correlation_id=correlation_id,
            )

        return result

    # =====================================================
    # SERVICE EVENT TRANSLATION
    # =====================================================

    def _publish_start_steps(
        self,
        result: OrchestrationResult,
        *,
        correlation_id: str,
    ) -> None:
        """
        Convert startup orchestration steps to system events.
        """

        for step in result.steps:

            payload = {
                "service_name": (
                    step.service_name
                ),
                "operation": result.operation,
                "action": step.action.value,
                "success": step.success,
                "state": step.state.value,
                "dependencies": list(
                    step.dependencies
                ),
                "message": step.message,
                "error": step.error,
            }

            if (
                step.action
                == OrchestrationAction.START
                and step.success
            ):

                event_type = (
                    AtlasSystemEventType
                    .SERVICE_STARTED
                )

                severity = EventSeverity.INFO

            elif (
                step.action
                == OrchestrationAction.SKIP
            ):

                event_type = (
                    AtlasSystemEventType
                    .SERVICE_START_SKIPPED
                )

                severity = EventSeverity.WARNING

            elif (
                step.action
                == OrchestrationAction.ROLLBACK
            ):

                event_type = (
                    AtlasSystemEventType
                    .SERVICE_ROLLED_BACK
                )

                severity = EventSeverity.WARNING

            else:

                event_type = (
                    AtlasSystemEventType
                    .SERVICE_START_FAILED
                )

                severity = EventSeverity.ERROR

            self._publish_safely(
                event_type=event_type,
                source=self.identity.name,
                payload=payload,
                severity=severity,
                correlation_id=correlation_id,
            )

    def _publish_stop_steps(
        self,
        result: OrchestrationResult,
        *,
        correlation_id: str,
    ) -> None:
        """
        Convert shutdown orchestration steps to system events.
        """

        for step in result.steps:

            payload = {
                "service_name": (
                    step.service_name
                ),
                "operation": result.operation,
                "action": step.action.value,
                "success": step.success,
                "state": step.state.value,
                "dependencies": list(
                    step.dependencies
                ),
                "message": step.message,
                "error": step.error,
            }

            event_type = (
                AtlasSystemEventType.SERVICE_STOPPED
                if step.success
                else (
                    AtlasSystemEventType
                    .SERVICE_STOP_FAILED
                )
            )

            severity = (
                EventSeverity.INFO
                if step.success
                else EventSeverity.ERROR
            )

            self._publish_safely(
                event_type=event_type,
                source=self.identity.name,
                payload=payload,
                severity=severity,
                correlation_id=correlation_id,
            )

    @staticmethod
    def _new_correlation_id(
        prefix: str,
    ) -> str:
        """
        Generate a lifecycle correlation ID.
        """

        return (
            f"{prefix}-"
            f"{uuid.uuid4()}"
        )


class EventAwareHealthMonitorService(
    _SafeEventPublisher,
    HealthMonitorService,
):
    """
    Health Monitor with automatic transition event publication.
    """

    VERSION = "1.0.0"

    NAME = "EventAwareHealthMonitor"

    def __init__(
        self,
        kernel: AtlasOSKernel,
        event_bus: EventBusService,
        *,
        interval_seconds: float = 5.0,
        history_limit: int = 500,
        auto_synchronize_kernel: bool = True,
        daemon: bool = True,
    ) -> None:

        HealthMonitorService.__init__(
            self,
            kernel,
            interval_seconds=interval_seconds,
            history_limit=history_limit,
            auto_synchronize_kernel=(
                auto_synchronize_kernel
            ),
            daemon=daemon,
        )

        self._initialize_event_publisher(
            event_bus
        )

        self._last_published_transition: (
            HealthTransition | None
        ) = None

    def poll_once(self) -> HealthObservation:
        """
        Poll health and publish newly detected transitions.
        """

        observation = super().poll_once()

        transition = self.last_transition

        if (
            transition is not None
            and transition
            is not self._last_published_transition
        ):

            self._publish_transition(
                transition,
                observation=observation,
            )

            self._last_published_transition = (
                transition
            )

        return observation

    def clear_history(self) -> None:
        """
        Clear monitor history and transition publication marker.
        """

        super().clear_history()

        self._last_published_transition = None

    def _publish_transition(
        self,
        transition: HealthTransition,
        *,
        observation: HealthObservation,
    ) -> None:
        """
        Convert a health transition into AtlasOS events.
        """

        correlation_id = (
            f"health-"
            f"{uuid.uuid4()}"
        )

        payload = {
            "transition_type": (
                transition.transition_type.value
            ),
            "previous_kernel_state": (
                transition.previous_kernel_state.value
                if transition.previous_kernel_state
                is not None
                else None
            ),
            "current_kernel_state": (
                transition.current_kernel_state.value
            ),
            "previous_health_status": (
                transition
                .previous_health_status
                .value
                if transition.previous_health_status
                is not None
                else None
            ),
            "current_health_status": (
                transition
                .current_health_status
                .value
            ),
            "total_services": (
                observation.total_services
            ),
            "healthy_services": (
                observation.healthy_services
            ),
            "degraded_services": (
                observation.degraded_services
            ),
            "unhealthy_services": (
                observation.unhealthy_services
            ),
            "unknown_services": (
                observation.unknown_services
            ),
            "operational": (
                observation.operational
            ),
            "message": transition.message,
        }

        if (
            transition.transition_type
            == HealthTransitionType.INITIALIZED
        ):

            event_type = (
                AtlasSystemEventType
                .HEALTH_MONITOR_INITIALIZED
            )

            severity = EventSeverity.INFO

        elif (
            transition.current_health_status
            == HealthStatus.UNHEALTHY
        ):

            event_type = (
                AtlasSystemEventType
                .HEALTH_UNHEALTHY
            )

            severity = EventSeverity.CRITICAL

        elif (
            transition.current_health_status
            == HealthStatus.DEGRADED
        ):

            event_type = (
                AtlasSystemEventType
                .HEALTH_DEGRADED
            )

            severity = EventSeverity.WARNING

        elif (
            transition.current_health_status
            == HealthStatus.HEALTHY
            and transition.previous_health_status
            in {
                HealthStatus.DEGRADED,
                HealthStatus.UNHEALTHY,
            }
        ):

            event_type = (
                AtlasSystemEventType
                .HEALTH_RECOVERED
            )

            severity = EventSeverity.INFO

        elif (
            transition.transition_type
            == (
                HealthTransitionType
                .KERNEL_STATE_CHANGED
            )
        ):

            event_type = (
                AtlasSystemEventType
                .KERNEL_STATE_CHANGED
            )

            severity = EventSeverity.INFO

        else:

            event_type = (
                AtlasSystemEventType
                .HEALTH_STATUS_CHANGED
            )

            severity = EventSeverity.INFO

        self._publish_safely(
            event_type=event_type,
            source=self.identity.name,
            payload=payload,
            severity=severity,
            correlation_id=correlation_id,
        )