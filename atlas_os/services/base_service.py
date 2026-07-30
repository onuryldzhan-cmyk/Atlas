"""
============================================================
ATLAS OS BASE SERVICE v1.0
============================================================

Enterprise lifecycle implementation for AtlasOS services.

Responsibilities
----------------
- Implement the AtlasService contract
- Manage service lifecycle state
- Validate lifecycle transitions
- Record service timestamps
- Produce health reports
- Produce diagnostic snapshots
- Capture startup and shutdown failures
- Provide safe extension hooks

Lifecycle
---------
CREATED
   |
   v
STARTING
   |
   +------> FAILED
   |
   v
RUNNING
   |
   v
STOPPING
   |
   +------> FAILED
   |
   v
STOPPED

Design principles
-----------------
- Thread safe
- Idempotent start and stop behavior
- No trading-specific dependencies
- No exchange-specific dependencies
- Safe for gradual legacy integration

============================================================
"""

from __future__ import annotations

import logging
import threading

from abc import abstractmethod
from datetime import UTC, datetime
from typing import Any, Mapping

from atlas_os.contracts import (
    AtlasService,
    HealthReport,
    HealthStatus,
    ServiceIdentity,
    ServiceSnapshot,
    ServiceState,
)


logger = logging.getLogger(
    "AtlasAI.AtlasOS.BaseService"
)


class ServiceLifecycleError(RuntimeError):
    """
    Raised when a service receives an invalid lifecycle operation.
    """


class BaseAtlasService(AtlasService):
    """
    Reusable lifecycle implementation for AtlasOS services.

    Subclasses implement the following hooks:

    - _on_start()
    - _on_stop()
    - _health_details()
    - _snapshot_metadata()

    The public start and stop methods must not normally be overridden.
    """

    def __init__(
        self,
        identity: ServiceIdentity,
    ) -> None:

        self._identity = identity

        self._state = ServiceState.CREATED

        self._started_at: datetime | None = None
        self._stopped_at: datetime | None = None

        self._last_error: str | None = None

        self._lock = threading.RLock()

    # =====================================================
    # PROPERTIES
    # =====================================================

    @property
    def identity(self) -> ServiceIdentity:
        """
        Return immutable service identity.
        """

        return self._identity

    @property
    def state(self) -> ServiceState:
        """
        Return the current lifecycle state.
        """

        with self._lock:
            return self._state

    @property
    def started_at(self) -> datetime | None:
        """
        Return the last successful start timestamp.
        """

        with self._lock:
            return self._started_at

    @property
    def stopped_at(self) -> datetime | None:
        """
        Return the last successful stop timestamp.
        """

        with self._lock:
            return self._stopped_at

    @property
    def last_error(self) -> str | None:
        """
        Return the most recent lifecycle error.
        """

        with self._lock:
            return self._last_error

    @property
    def is_running(self) -> bool:
        """
        Return True when the service is running.
        """

        return self.state == ServiceState.RUNNING

    # =====================================================
    # START
    # =====================================================

    def start(self) -> None:
        """
        Start the service safely.

        Calling start while already running is treated as an
        idempotent operation and produces no additional side effects.
        """

        with self._lock:

            if self._state == ServiceState.RUNNING:
                return

            if self._state in {
                ServiceState.STARTING,
                ServiceState.STOPPING,
            }:
                raise ServiceLifecycleError(
                    f"Service '{self.identity.name}' cannot start "
                    f"while state is {self._state.value}."
                )

            self._state = ServiceState.STARTING
            self._last_error = None

            try:

                self._on_start()

                self._started_at = datetime.now(UTC)
                self._stopped_at = None
                self._state = ServiceState.RUNNING

                logger.info(
                    "AtlasOS service started: %s v%s",
                    self.identity.name,
                    self.identity.version,
                )

            except Exception as exc:

                self._last_error = (
                    f"{type(exc).__name__}: {exc}"
                )

                self._state = ServiceState.FAILED

                logger.exception(
                    "AtlasOS service start failed: %s",
                    self.identity.name,
                )

                raise

    # =====================================================
    # STOP
    # =====================================================

    def stop(self) -> None:
        """
        Stop the service safely.

        Calling stop before startup or after shutdown is treated as
        an idempotent operation.
        """

        with self._lock:

            if self._state in {
                ServiceState.CREATED,
                ServiceState.STOPPED,
            }:
                self._state = ServiceState.STOPPED

                if self._stopped_at is None:
                    self._stopped_at = datetime.now(UTC)

                return

            if self._state == ServiceState.STOPPING:
                return

            if self._state == ServiceState.STARTING:
                raise ServiceLifecycleError(
                    f"Service '{self.identity.name}' cannot stop "
                    "while startup is in progress."
                )

            self._state = ServiceState.STOPPING

            try:

                self._on_stop()

                self._stopped_at = datetime.now(UTC)
                self._state = ServiceState.STOPPED

                logger.info(
                    "AtlasOS service stopped: %s",
                    self.identity.name,
                )

            except Exception as exc:

                self._last_error = (
                    f"{type(exc).__name__}: {exc}"
                )

                self._state = ServiceState.FAILED

                logger.exception(
                    "AtlasOS service stop failed: %s",
                    self.identity.name,
                )

                raise

    # =====================================================
    # HEALTH
    # =====================================================

    def health(self) -> HealthReport:
        """
        Return a standardized service health report.
        """

        with self._lock:

            state = self._state

            if state == ServiceState.RUNNING:
                status = HealthStatus.HEALTHY
                message = "Service is operating normally."

            elif state == ServiceState.DEGRADED:
                status = HealthStatus.DEGRADED
                message = "Service is operational but degraded."

            elif state == ServiceState.FAILED:
                status = HealthStatus.UNHEALTHY
                message = (
                    self._last_error
                    or "Service lifecycle failed."
                )

            elif state in {
                ServiceState.CREATED,
                ServiceState.STOPPED,
            }:
                status = HealthStatus.UNKNOWN
                message = "Service is not currently running."

            else:
                status = HealthStatus.UNKNOWN
                message = (
                    f"Service lifecycle transition: "
                    f"{state.value}."
                )

            details = dict(
                self._health_details()
            )

            if self._last_error is not None:
                details.setdefault(
                    "last_error",
                    self._last_error,
                )

            return HealthReport(
                service_name=self.identity.name,
                status=status,
                state=state,
                message=message,
                details=details,
            )

    # =====================================================
    # SNAPSHOT
    # =====================================================

    def snapshot(self) -> ServiceSnapshot:
        """
        Return a complete diagnostic snapshot.
        """

        with self._lock:

            return ServiceSnapshot(
                identity=self.identity,
                state=self._state,
                health=self.health(),
                started_at=self._started_at,
                stopped_at=self._stopped_at,
                metadata=dict(
                    self._snapshot_metadata()
                ),
            )

    # =====================================================
    # DEGRADE / RECOVER
    # =====================================================

    def mark_degraded(
        self,
        reason: str,
    ) -> None:
        """
        Mark a running service as degraded.
        """

        normalized_reason = reason.strip()

        if not normalized_reason:
            raise ValueError(
                "Degradation reason cannot be empty."
            )

        with self._lock:

            if self._state != ServiceState.RUNNING:
                raise ServiceLifecycleError(
                    f"Service '{self.identity.name}' can only "
                    "be degraded while running."
                )

            self._state = ServiceState.DEGRADED
            self._last_error = normalized_reason

            logger.warning(
                "AtlasOS service degraded: %s | %s",
                self.identity.name,
                normalized_reason,
            )

    def recover(self) -> None:
        """
        Recover a degraded service to running state.
        """

        with self._lock:

            if self._state != ServiceState.DEGRADED:
                raise ServiceLifecycleError(
                    f"Service '{self.identity.name}' can only "
                    "recover from DEGRADED state."
                )

            self._state = ServiceState.RUNNING
            self._last_error = None

            logger.info(
                "AtlasOS service recovered: %s",
                self.identity.name,
            )

    # =====================================================
    # EXTENSION HOOKS
    # =====================================================

    @abstractmethod
    def _on_start(self) -> None:
        """
        Perform service-specific startup operations.
        """

        raise NotImplementedError

    @abstractmethod
    def _on_stop(self) -> None:
        """
        Perform service-specific shutdown operations.
        """

        raise NotImplementedError

    def _health_details(self) -> Mapping[str, Any]:
        """
        Return service-specific health details.
        """

        return {}

    def _snapshot_metadata(self) -> Mapping[str, Any]:
        """
        Return service-specific diagnostic metadata.
        """

        return {}