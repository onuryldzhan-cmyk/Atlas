"""
============================================================
ATLAS OS HEALTH MONITOR v1.0
============================================================

Continuous health monitoring service for AtlasOS.

Responsibilities
----------------
- Observe AtlasOS kernel health
- Observe aggregate service health
- Detect health status changes
- Detect kernel state changes
- Record health observations
- Record health transitions
- Synchronize kernel state
- Run periodically in a background thread
- Maintain bounded observation history
- Produce diagnostic snapshots

Architecture
------------
AtlasOSKernel
      |
      v
HealthMonitorService
      |
      +-- Periodic health checks
      +-- Transition detection
      +-- Observation history
      +-- Kernel state synchronization
      +-- Diagnostics

Design principles
-----------------
- Thread safe
- Bounded memory usage
- Deterministic manual polling
- Optional automatic background monitoring
- No trading-specific dependencies
- No exchange-specific dependencies
- Compatible with AtlasOS service lifecycle

============================================================
"""

from __future__ import annotations

import logging
import threading

from collections import deque
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any, Mapping

from atlas_os.contracts import (
    HealthStatus,
    ServiceIdentity,
)
from atlas_os.kernel import (
    AtlasOSKernel,
    KernelState,
)
from atlas_os.services import (
    BaseAtlasService,
)


logger = logging.getLogger(
    "AtlasAI.AtlasOS.HealthMonitor"
)


class HealthTransitionType(StrEnum):
    """
    Types of health transitions detected by the monitor.
    """

    INITIALIZED = "INITIALIZED"
    HEALTH_CHANGED = "HEALTH_CHANGED"
    KERNEL_STATE_CHANGED = "KERNEL_STATE_CHANGED"
    HEALTH_AND_STATE_CHANGED = "HEALTH_AND_STATE_CHANGED"


@dataclass(frozen=True, slots=True)
class HealthObservation:
    """
    One immutable AtlasOS health observation.
    """

    sequence: int
    kernel_state: KernelState
    kernel_status: HealthStatus
    service_status: HealthStatus
    total_services: int
    healthy_services: int
    degraded_services: int
    unhealthy_services: int
    unknown_services: int
    uptime_seconds: float
    operational: bool
    message: str
    observed_at: datetime = field(
        default_factory=lambda: datetime.now(UTC)
    )


@dataclass(frozen=True, slots=True)
class HealthTransition:
    """
    A detected change between two health observations.
    """

    transition_type: HealthTransitionType
    previous_kernel_state: KernelState | None
    current_kernel_state: KernelState
    previous_health_status: HealthStatus | None
    current_health_status: HealthStatus
    message: str
    detected_at: datetime = field(
        default_factory=lambda: datetime.now(UTC)
    )


@dataclass(frozen=True, slots=True)
class HealthMonitorSnapshot:
    """
    Immutable diagnostic snapshot of the monitor.
    """

    monitor_name: str
    running: bool
    thread_alive: bool
    interval_seconds: float
    observation_count: int
    transition_count: int
    last_observation: HealthObservation | None
    last_transition: HealthTransition | None
    observations: tuple[HealthObservation, ...]
    transitions: tuple[HealthTransition, ...]
    generated_at: datetime = field(
        default_factory=lambda: datetime.now(UTC)
    )


class HealthMonitorService(BaseAtlasService):
    """
    AtlasOS background health monitoring service.

    The monitor may be used in two ways:

    Manual polling
    --------------
    monitor.poll_once()

    Background monitoring
    ---------------------
    monitor.start()
    ...
    monitor.stop()
    """

    VERSION = "1.0.0"

    NAME = "AtlasOSHealthMonitor"

    def __init__(
        self,
        kernel: AtlasOSKernel,
        *,
        interval_seconds: float = 5.0,
        history_limit: int = 500,
        auto_synchronize_kernel: bool = True,
        daemon: bool = True,
    ) -> None:

        if not isinstance(
            kernel,
            AtlasOSKernel,
        ):
            raise TypeError(
                "kernel must be an AtlasOSKernel instance."
            )

        if interval_seconds <= 0:
            raise ValueError(
                "interval_seconds must be greater than zero."
            )

        if history_limit <= 0:
            raise ValueError(
                "history_limit must be greater than zero."
            )

        super().__init__(
            ServiceIdentity(
                name=self.NAME,
                version=self.VERSION,
                service_type="OBSERVABILITY",
                description=(
                    "Continuous AtlasOS kernel and service "
                    "health monitoring."
                ),
            )
        )

        self._kernel = kernel

        self._interval_seconds = float(
            interval_seconds
        )

        self._history_limit = int(
            history_limit
        )

        self._auto_synchronize_kernel = bool(
            auto_synchronize_kernel
        )

        self._daemon = bool(
            daemon
        )

        self._observations: deque[
            HealthObservation
        ] = deque(
            maxlen=self._history_limit
        )

        self._transitions: deque[
            HealthTransition
        ] = deque(
            maxlen=self._history_limit
        )

        self._sequence = 0

        self._last_observation: (
            HealthObservation | None
        ) = None

        self._last_transition: (
            HealthTransition | None
        ) = None

        self._monitor_thread: (
            threading.Thread | None
        ) = None

        self._stop_event = threading.Event()

        self._data_lock = threading.RLock()

    # =====================================================
    # PROPERTIES
    # =====================================================

    @property
    def kernel(self) -> AtlasOSKernel:
        """
        Return the monitored kernel.
        """

        return self._kernel

    @property
    def interval_seconds(self) -> float:
        """
        Return monitoring interval.
        """

        return self._interval_seconds

    @property
    def history_limit(self) -> int:
        """
        Return maximum retained observation count.
        """

        return self._history_limit

    @property
    def observation_count(self) -> int:
        """
        Return current retained observation count.
        """

        with self._data_lock:
            return len(self._observations)

    @property
    def transition_count(self) -> int:
        """
        Return current retained transition count.
        """

        with self._data_lock:
            return len(self._transitions)

    @property
    def thread_alive(self) -> bool:
        """
        Return True when background monitor thread is alive.
        """

        thread = self._monitor_thread

        return (
            thread is not None
            and thread.is_alive()
        )

    @property
    def last_observation(
        self,
    ) -> HealthObservation | None:
        """
        Return the most recent health observation.
        """

        with self._data_lock:
            return self._last_observation

    @property
    def last_transition(
        self,
    ) -> HealthTransition | None:
        """
        Return the most recent health transition.
        """

        with self._data_lock:
            return self._last_transition

    # =====================================================
    # SERVICE LIFECYCLE
    # =====================================================

    def _on_start(self) -> None:
        """
        Start background health monitoring.
        """

        self._stop_event.clear()

        self.poll_once()

        self._monitor_thread = threading.Thread(
            target=self._monitor_loop,
            name="AtlasOS-HealthMonitor",
            daemon=self._daemon,
        )

        self._monitor_thread.start()

        logger.info(
            "AtlasOS Health Monitor started | "
            "interval=%.3fs",
            self._interval_seconds,
        )

    def _on_stop(self) -> None:
        """
        Stop background monitoring safely.
        """

        self._stop_event.set()

        thread = self._monitor_thread

        if (
            thread is not None
            and thread.is_alive()
            and thread is not threading.current_thread()
        ):

            thread.join(
                timeout=max(
                    self._interval_seconds * 2,
                    1.0,
                )
            )

        self._monitor_thread = None

        logger.info(
            "AtlasOS Health Monitor stopped."
        )

    # =====================================================
    # MONITORING
    # =====================================================

    def poll_once(self) -> HealthObservation:
        """
        Perform one immediate health observation.

        This method is deterministic and can be used independently
        from the background monitoring thread.
        """

        if self._auto_synchronize_kernel:

            self._kernel.synchronize_state()

        report = self._kernel.health()

        service_health = (
            report.service_health
        )

        with self._data_lock:

            self._sequence += 1

            observation = HealthObservation(
                sequence=self._sequence,
                kernel_state=report.kernel_state,
                kernel_status=report.status,
                service_status=service_health.status,
                total_services=(
                    service_health.total_services
                ),
                healthy_services=(
                    service_health.healthy_services
                ),
                degraded_services=(
                    service_health.degraded_services
                ),
                unhealthy_services=(
                    service_health.unhealthy_services
                ),
                unknown_services=(
                    service_health.unknown_services
                ),
                uptime_seconds=report.uptime_seconds,
                operational=report.is_operational,
                message=report.message,
            )

            transition = (
                self._detect_transition(
                    previous=self._last_observation,
                    current=observation,
                )
            )

            self._observations.append(
                observation
            )

            self._last_observation = observation

            if transition is not None:

                self._transitions.append(
                    transition
                )

                self._last_transition = (
                    transition
                )

                self._log_transition(
                    transition
                )

            return observation

    def observations(
        self,
    ) -> tuple[HealthObservation, ...]:
        """
        Return retained observations.
        """

        with self._data_lock:

            return tuple(
                self._observations
            )

    def transitions(
        self,
    ) -> tuple[HealthTransition, ...]:
        """
        Return retained transitions.
        """

        with self._data_lock:

            return tuple(
                self._transitions
            )

    def clear_history(self) -> None:
        """
        Clear observation and transition history.
        """

        with self._data_lock:

            self._observations.clear()
            self._transitions.clear()

            self._last_observation = None
            self._last_transition = None

            self._sequence = 0

    # =====================================================
    # SNAPSHOT
    # =====================================================

    def monitor_snapshot(
        self,
    ) -> HealthMonitorSnapshot:
        """
        Return a complete monitor diagnostic snapshot.
        """

        with self._data_lock:

            return HealthMonitorSnapshot(
                monitor_name=self.identity.name,
                running=self.is_running,
                thread_alive=self.thread_alive,
                interval_seconds=self._interval_seconds,
                observation_count=len(
                    self._observations
                ),
                transition_count=len(
                    self._transitions
                ),
                last_observation=self._last_observation,
                last_transition=self._last_transition,
                observations=tuple(
                    self._observations
                ),
                transitions=tuple(
                    self._transitions
                ),
            )

    # =====================================================
    # BASE SERVICE DIAGNOSTICS
    # =====================================================

    def _health_details(
        self,
    ) -> Mapping[str, Any]:
        """
        Return monitor-specific health details.
        """

        last_observation = (
            self.last_observation
        )

        return {
            "thread_alive": self.thread_alive,
            "interval_seconds": (
                self._interval_seconds
            ),
            "history_limit": (
                self._history_limit
            ),
            "observation_count": (
                self.observation_count
            ),
            "transition_count": (
                self.transition_count
            ),
            "last_kernel_state": (
                last_observation.kernel_state.value
                if last_observation is not None
                else None
            ),
            "last_health_status": (
                last_observation.kernel_status.value
                if last_observation is not None
                else None
            ),
        }

    def _snapshot_metadata(
        self,
    ) -> Mapping[str, Any]:
        """
        Return monitor-specific snapshot metadata.
        """

        return {
            "auto_synchronize_kernel": (
                self._auto_synchronize_kernel
            ),
            "daemon": self._daemon,
            "history_limit": (
                self._history_limit
            ),
        }

    # =====================================================
    # INTERNAL LOOP
    # =====================================================

    def _monitor_loop(self) -> None:
        """
        Execute periodic health checks until shutdown.
        """

        while not self._stop_event.wait(
            self._interval_seconds
        ):

            try:

                self.poll_once()

            except Exception:

                logger.exception(
                    "AtlasOS Health Monitor polling failed."
                )

    # =====================================================
    # TRANSITION DETECTION
    # =====================================================

    @staticmethod
    def _detect_transition(
        *,
        previous: HealthObservation | None,
        current: HealthObservation,
    ) -> HealthTransition | None:
        """
        Detect a health or kernel state transition.
        """

        if previous is None:

            return HealthTransition(
                transition_type=(
                    HealthTransitionType.INITIALIZED
                ),
                previous_kernel_state=None,
                current_kernel_state=(
                    current.kernel_state
                ),
                previous_health_status=None,
                current_health_status=(
                    current.kernel_status
                ),
                message=(
                    "Initial AtlasOS health state recorded."
                ),
            )

        health_changed = (
            previous.kernel_status
            != current.kernel_status
        )

        state_changed = (
            previous.kernel_state
            != current.kernel_state
        )

        if not health_changed and not state_changed:
            return None

        if health_changed and state_changed:

            transition_type = (
                HealthTransitionType
                .HEALTH_AND_STATE_CHANGED
            )

        elif health_changed:

            transition_type = (
                HealthTransitionType
                .HEALTH_CHANGED
            )

        else:

            transition_type = (
                HealthTransitionType
                .KERNEL_STATE_CHANGED
            )

        message = (
            f"Kernel state: "
            f"{previous.kernel_state.value} -> "
            f"{current.kernel_state.value}; "
            f"health: "
            f"{previous.kernel_status.value} -> "
            f"{current.kernel_status.value}."
        )

        return HealthTransition(
            transition_type=transition_type,
            previous_kernel_state=(
                previous.kernel_state
            ),
            current_kernel_state=(
                current.kernel_state
            ),
            previous_health_status=(
                previous.kernel_status
            ),
            current_health_status=(
                current.kernel_status
            ),
            message=message,
        )

    @staticmethod
    def _log_transition(
        transition: HealthTransition,
    ) -> None:
        """
        Log transition according to current health severity.
        """

        if (
            transition.current_health_status
            == HealthStatus.UNHEALTHY
        ):

            logger.error(
                "AtlasOS health transition: %s",
                transition.message,
            )

        elif (
            transition.current_health_status
            == HealthStatus.DEGRADED
        ):

            logger.warning(
                "AtlasOS health transition: %s",
                transition.message,
            )

        else:

            logger.info(
                "AtlasOS health transition: %s",
                transition.message,
            )