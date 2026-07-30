"""
============================================================
ATLAS CONTROLLER v2.0
============================================================

Institutional System Control Interface


Responsibilities
----------------

- Represent the Atlas control layer
- Track controller lifecycle
- Expose system and component status
- Provide access to brain, market loop and execution diagnostics
- Maintain controller runtime statistics


Architecture Ownership
----------------------

AtlasApplication owns service lifecycle operations:

- MarketLoop.start()
- MarketLoop.stop()
- ExecutionManager.start()
- ExecutionManager.stop()
- MarketFeed.start()
- MarketFeed.stop()

AtlasController must not start or stop those services.

This prevents:

- Duplicate service startup
- Duplicate service shutdown
- Conflicting lifecycle ownership
- Inconsistent service state


Architecture
------------

AtlasApplication
    |
    +-- Runtime lifecycle
    +-- Market Feed lifecycle
    +-- Execution lifecycle
    +-- Market Loop lifecycle
    |
    v
AtlasController
    |
    +-- Status interface
    +-- Diagnostics interface
    +-- User-control state


============================================================
"""

from __future__ import annotations

import logging

from datetime import UTC, datetime
from typing import Any


logger = logging.getLogger(
    "AtlasAI.Controller"
)


class AtlasController:
    """
    Atlas control and diagnostic interface.

    The controller tracks its own availability but does not own the
    lifecycle of MarketLoop, ExecutionManager, MarketFeed or AtlasBrain.
    """

    VERSION = "2.0"

    NAME = "AtlasController"

    STATUS_INITIALIZED = "INITIALIZED"
    STATUS_RUNNING = "RUNNING"
    STATUS_STOPPED = "STOPPED"
    STATUS_ERROR = "ERROR"

    def __init__(
        self,
        brain: Any = None,
        market_loop: Any = None,
        execution: Any = None,
    ) -> None:
        self.brain = brain
        self.market_loop = market_loop
        self.execution = execution

        self.running = False
        self.state = self.STATUS_INITIALIZED

        self.created_at = datetime.now(
            UTC
        ).isoformat()

        self.started_at: str | None = None
        self.stopped_at: str | None = None

        self.start_count = 0
        self.stop_count = 0
        self.errors = 0

        self.last_error: dict[str, Any] | None = None

        logger.info(
            "Atlas Controller v%s initialized",
            self.VERSION,
        )

    # =========================================================
    # START CONTROLLER
    # =========================================================

    def start(self) -> dict[str, Any]:
        """
        Activate the controller interface.

        Important:
            This method does not start MarketLoop or any other service.
            AtlasApplication owns service startup.
        """

        if self.running:
            return {
                "status": "ALREADY_RUNNING",
                "running": True,
                "started_at": self.started_at,
            }

        try:
            self.running = True
            self.state = self.STATUS_RUNNING

            self.started_at = datetime.now(
                UTC
            ).isoformat()

            self.stopped_at = None
            self.start_count += 1
            self.last_error = None

            logger.info(
                "Atlas Controller started"
            )

            return {
                "status": "STARTED",
                "running": True,
                "started_at": self.started_at,
            }

        except Exception as exc:
            self.running = False
            self.state = self.STATUS_ERROR
            self.errors += 1

            self.last_error = self._build_error_record(
                phase="controller_start",
                error=exc,
            )

            logger.exception(
                "Atlas Controller startup failed"
            )

            return {
                "status": "ERROR",
                "running": False,
                "error": str(
                    exc
                ),
            }

    # =========================================================
    # STOP CONTROLLER
    # =========================================================

    def stop(self) -> dict[str, Any]:
        """
        Deactivate the controller interface.

        Important:
            This method does not stop MarketLoop or any other service.
            AtlasApplication owns service shutdown.
        """

        if not self.running:
            return {
                "status": "ALREADY_STOPPED",
                "running": False,
                "stopped_at": self.stopped_at,
            }

        try:
            self.running = False
            self.state = self.STATUS_STOPPED

            self.stopped_at = datetime.now(
                UTC
            ).isoformat()

            self.stop_count += 1
            self.last_error = None

            logger.info(
                "Atlas Controller stopped"
            )

            return {
                "status": "STOPPED",
                "running": False,
                "stopped_at": self.stopped_at,
            }

        except Exception as exc:
            self.state = self.STATUS_ERROR
            self.errors += 1

            self.last_error = self._build_error_record(
                phase="controller_stop",
                error=exc,
            )

            logger.exception(
                "Atlas Controller shutdown failed"
            )

            return {
                "status": "ERROR",
                "running": self.running,
                "error": str(
                    exc
                ),
            }

    # =========================================================
    # STATUS
    # =========================================================

    def status(self) -> dict[str, Any]:
        """
        Return complete controller and component status.
        """

        return {
            "name": self.NAME,
            "version": self.VERSION,
            "state": self.state,
            "running": self.running,
            "created_at": self.created_at,
            "started_at": self.started_at,
            "stopped_at": self.stopped_at,
            "start_count": self.start_count,
            "stop_count": self.stop_count,
            "errors": self.errors,
            "brain": self._read_component_status(
                self.brain
            ),
            "market_loop": self._read_component_status(
                self.market_loop
            ),
            "execution": self._read_component_status(
                self.execution
            ),
            "last_error": self.last_error,
            "timestamp": datetime.now(
                UTC
            ).isoformat(),
        }

    # =========================================================
    # HEALTH
    # =========================================================

    def health(self) -> dict[str, Any]:
        """
        Return concise controller health information.
        """

        healthy = bool(
            self.state != self.STATUS_ERROR
            and self.errors == 0
        )

        return {
            "healthy": healthy,
            "running": self.running,
            "state": self.state,
            "version": self.VERSION,
            "errors": self.errors,
        }

    # =========================================================
    # COMPONENT STATUS
    # =========================================================

    @staticmethod
    def _read_component_status(
        component: Any,
    ) -> Any:
        """
        Safely read status information from an Atlas component.

        Supported contracts:

        - component.get_system_status()
        - component.status()
        - component.health()
        - component.running
        """

        if component is None:
            return None

        for method_name in (
            "get_system_status",
            "status",
            "health",
            "snapshot",
            "diagnostics",
        ):
            method = getattr(
                component,
                method_name,
                None,
            )

            if not callable(
                method
            ):
                continue

            try:
                return method()

            except TypeError:
                continue

            except Exception as exc:
                return {
                    "available": False,
                    "method": method_name,
                    "error": str(
                        exc
                    ),
                }

        return {
            "available": True,
            "type": type(
                component
            ).__name__,
            "running": getattr(
                component,
                "running",
                None,
            ),
            "version": getattr(
                component,
                "VERSION",
                None,
            ),
        }

    # =========================================================
    # ERROR RECORD
    # =========================================================

    @staticmethod
    def _build_error_record(
        *,
        phase: str,
        error: Exception,
    ) -> dict[str, Any]:
        """
        Create a structured controller error record.
        """

        return {
            "timestamp": datetime.now(
                UTC
            ).isoformat(),
            "phase": phase,
            "type": type(
                error
            ).__name__,
            "message": str(
                error
            ),
        }

    # =========================================================
    # REPRESENTATION
    # =========================================================

    def __repr__(self) -> str:
        return (
            f"<{self.NAME} "
            f"version={self.VERSION} "
            f"state={self.state} "
            f"running={self.running}>"
        )