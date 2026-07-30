"""
============================================================
ATLAS EXECUTIVE BRAIN v10.0
============================================================

Institutional Intelligence Lifecycle Orchestrator

Responsibilities
----------------
- Receive normalized market observations
- Coordinate the intelligence engine
- Produce normalized trading decisions
- Maintain deterministic lifecycle state
- Operate fail-closed while offline
- Expose structured status and health information
- Support application-managed start and stop operations

Architecture
------------
MarketLoop
    |
    v
AtlasBrain
    |
    +-- Intelligence Brain
    |
    +-- Decision Adapter
    |
    v
Decision
    |
    v
ExecutionManager

Lifecycle
---------
CONSTRUCTED
    |
    v
STARTED
    |
    v
STOPPED

The constructor does not mark the service as running.
Intelligence loading occurs during start().
Processing while offline returns a fail-closed response.

============================================================
"""

from __future__ import annotations

import logging

from datetime import UTC
from datetime import datetime
from typing import Any

from core.decision_adapter import DecisionAdapter


logger = logging.getLogger(
    "AtlasAI.Brain"
)


class BrainState:
    """
    Mutable operational state owned by AtlasBrain.
    """

    def __init__(self) -> None:
        self.last_input: Any | None = None
        self.last_analysis: dict[str, Any] | None = None
        self.last_decision: Any | None = None

        self.total_cycles: int = 0
        self.total_errors: int = 0
        self.total_rejections: int = 0

        self.created_at: datetime = datetime.now(UTC)
        self.started_at: datetime | None = None
        self.stopped_at: datetime | None = None

        self.last_error: dict[str, Any] | None = None


class AtlasBrain:
    """
    Atlas executive intelligence lifecycle service.

    The service is deliberately inactive after construction.
    The application lifecycle must call start() before analysis.
    """

    VERSION = "10.0"

    NAME = "AtlasBrain"

    def __init__(
        self,
        event_bus: Any | None = None,
    ) -> None:
        self.event_bus = event_bus
        self.state = BrainState()

        self.intelligence: Any | None = None

        self.initialized: bool = True
        self.running: bool = False

        logger.info(
            "%s v%s constructed",
            self.NAME,
            self.VERSION,
        )

    # =========================================================
    # LIFECYCLE
    # =========================================================

    def start(self) -> bool:
        """
        Start the brain service.

        The method is idempotent. Calling it while already running
        returns True without creating a second intelligence instance.
        """

        if self.running:
            logger.debug(
                "%s is already running",
                self.NAME,
            )
            return True

        if self.intelligence is None:
            loaded = self.load_intelligence()

            if not loaded:
                self.running = False
                return False

        self.running = True
        self.state.started_at = datetime.now(UTC)
        self.state.stopped_at = None

        logger.info(
            "%s v%s started",
            self.NAME,
            self.VERSION,
        )

        self._publish_event(
            "atlas.brain.started",
            {
                "version": self.VERSION,
                "started_at": self.state.started_at.isoformat(),
            },
        )

        return True

    def stop(self) -> bool:
        """
        Stop the brain service safely.

        The intelligence object remains constructed so the service can
        be restarted without recreating all intelligence dependencies.
        """

        if not self.running:
            logger.debug(
                "%s is already stopped",
                self.NAME,
            )
            return True

        self.running = False
        self.state.stopped_at = datetime.now(UTC)

        logger.info(
            "%s stopped",
            self.NAME,
        )

        self._publish_event(
            "atlas.brain.stopped",
            {
                "version": self.VERSION,
                "stopped_at": self.state.stopped_at.isoformat(),
            },
        )

        return True

    def shutdown(self) -> bool:
        """
        Fully shut down the brain service.

        Shutdown stops the lifecycle and releases the intelligence
        reference. A later start() call will create a fresh instance.
        """

        self.stop()

        intelligence = self.intelligence

        if intelligence is not None:
            shutdown_method = getattr(
                intelligence,
                "shutdown",
                None,
            )

            if callable(shutdown_method):
                try:
                    shutdown_method()
                except Exception as exc:
                    self._record_error(
                        phase="intelligence_shutdown",
                        error=exc,
                    )

        self.intelligence = None

        logger.info(
            "%s shutdown completed",
            self.NAME,
        )

        return True

    # =========================================================
    # INTELLIGENCE LOADING
    # =========================================================

    def load_intelligence(self) -> bool:
        """
        Load the underlying Atlas intelligence implementation.

        Returns:
            True when the intelligence engine is available.
            False when loading fails.
        """

        if self.intelligence is not None:
            return True

        try:
            from ai.core.atlas_brain import (
                AtlasBrain as IntelligenceBrain,
            )

            self.intelligence = IntelligenceBrain()

            logger.info(
                "Intelligence Brain connected",
            )

            return True

        except Exception as exc:
            self.intelligence = None

            self._record_error(
                phase="load_intelligence",
                error=exc,
            )

            logger.exception(
                "Intelligence Brain loading failed",
            )

            return False

    # =========================================================
    # OBSERVATION
    # =========================================================

    def observe(
        self,
        data: dict[str, Any],
    ) -> dict[str, Any]:
        """
        Register an input observation.

        This method is called only after lifecycle validation.
        """

        self.state.last_input = data
        self.state.total_cycles += 1

        return data

    # =========================================================
    # ANALYSIS
    # =========================================================

    def analyze(
        self,
        observation: dict[str, Any],
    ) -> dict[str, Any]:
        """
        Analyze a market observation.

        The service fails closed while not running or while the
        underlying intelligence engine is unavailable.
        """

        if not self.running:
            self.state.total_rejections += 1

            return self._offline_analysis(
                reason="BRAIN_NOT_RUNNING",
                observation=observation,
            )

        if self.intelligence is None:
            self.state.total_rejections += 1

            return self._offline_analysis(
                reason="INTELLIGENCE_UNAVAILABLE",
                observation=observation,
            )

        try:
            symbol = observation.get(
                "symbol",
                "UNKNOWN",
            )

            result = self.intelligence.analyze_and_decide(
                symbol,
                observation,
            )

            analysis = {
                "status": "SUCCESS",
                "symbol": symbol,
                "result": result,
                "timestamp": datetime.now(UTC).isoformat(),
            }

            self.state.last_analysis = analysis

            return analysis

        except Exception as exc:
            self._record_error(
                phase="analyze",
                error=exc,
            )

            analysis = {
                "status": "ERROR",
                "symbol": observation.get(
                    "symbol",
                    "UNKNOWN",
                ),
                "error_type": type(exc).__name__,
                "error": str(exc),
                "timestamp": datetime.now(UTC).isoformat(),
            }

            self.state.last_analysis = analysis

            return analysis

    # =========================================================
    # DECISION
    # =========================================================

    def decide(
        self,
        analysis: dict[str, Any],
    ) -> Any | None:
        """
        Convert successful intelligence output into an Atlas decision.
        """

        if not self.running:
            self.state.total_rejections += 1
            return None

        if analysis.get("status") != "SUCCESS":
            return None

        try:
            decision = DecisionAdapter.convert(
                analysis["result"],
            )

            self.state.last_decision = decision

            return decision

        except Exception as exc:
            self._record_error(
                phase="decide",
                error=exc,
            )

            return None

    # =========================================================
    # MAIN ENTRY
    # =========================================================

    def process(
        self,
        data: dict[str, Any],
    ) -> dict[str, Any]:
        """
        Process one market observation through the complete brain path.

        This entry point is fail-closed while the service is offline.
        """

        timestamp = datetime.now(UTC).isoformat()

        if not self.running:
            self.state.total_rejections += 1

            return {
                "status": "OFFLINE",
                "reason": "BRAIN_NOT_RUNNING",
                "symbol": data.get("symbol"),
                "decision": None,
                "analysis": {
                    "status": "OFFLINE",
                    "reason": "BRAIN_NOT_RUNNING",
                },
                "time": timestamp,
            }

        try:
            observation = self.observe(
                data,
            )

            analysis = self.analyze(
                observation,
            )

            decision = self.decide(
                analysis,
            )

            serialized_decision = (
                decision.to_dict()
                if decision is not None
                and hasattr(decision, "to_dict")
                else decision
            )

            return {
                "status": (
                    "SUCCESS"
                    if analysis.get("status") == "SUCCESS"
                    else analysis.get("status", "ERROR")
                ),
                "symbol": data.get("symbol"),
                "decision": serialized_decision,
                "analysis": analysis,
                "time": timestamp,
            }

        except Exception as exc:
            self._record_error(
                phase="process",
                error=exc,
            )

            return {
                "status": "ERROR",
                "symbol": data.get("symbol"),
                "decision": None,
                "error_type": type(exc).__name__,
                "error": str(exc),
                "time": timestamp,
            }

    # =========================================================
    # MARKET LOOP COMPATIBILITY
    # =========================================================

    def analyze_and_decide(
        self,
        symbol: str,
        market_data: dict[str, Any],
    ) -> Any | None:
        """
        Compatibility entry point used by MarketLoop.
        """

        payload = {
            "symbol": symbol,
            **market_data,
        }

        result = self.process(
            payload,
        )

        return result.get(
            "decision",
        )

    # =========================================================
    # STATUS AND HEALTH
    # =========================================================

    def status(self) -> dict[str, Any]:
        """
        Return structured service status.
        """

        return {
            "name": self.NAME,
            "version": self.VERSION,
            "initialized": self.initialized,
            "running": self.running,
            "intelligence_loaded": self.intelligence is not None,
            "cycles": self.state.total_cycles,
            "errors": self.state.total_errors,
            "rejections": self.state.total_rejections,
            "created_at": self.state.created_at.isoformat(),
            "started_at": (
                self.state.started_at.isoformat()
                if self.state.started_at is not None
                else None
            ),
            "stopped_at": (
                self.state.stopped_at.isoformat()
                if self.state.stopped_at is not None
                else None
            ),
            "last_error": self.state.last_error,
        }

    def health(self) -> dict[str, Any]:
        """
        Return lifecycle-aware health information.

        An intentionally stopped service is reported as offline rather
        than healthy and operational.
        """

        intelligence_loaded = self.intelligence is not None

        if self.running and intelligence_loaded:
            state = "HEALTHY"
            healthy = True
        elif self.running and not intelligence_loaded:
            state = "DEGRADED"
            healthy = False
        else:
            state = "OFFLINE"
            healthy = False

        return {
            "name": self.NAME,
            "version": self.VERSION,
            "healthy": healthy,
            "state": state,
            "initialized": self.initialized,
            "running": self.running,
            "intelligence_loaded": intelligence_loaded,
            "error_count": self.state.total_errors,
            "rejection_count": self.state.total_rejections,
            "last_error": self.state.last_error,
        }

    # =========================================================
    # INTERNAL HELPERS
    # =========================================================

    def _offline_analysis(
        self,
        *,
        reason: str,
        observation: dict[str, Any],
    ) -> dict[str, Any]:
        analysis = {
            "status": "OFFLINE",
            "reason": reason,
            "symbol": observation.get(
                "symbol",
                "UNKNOWN",
            ),
            "result": None,
            "timestamp": datetime.now(UTC).isoformat(),
        }

        self.state.last_analysis = analysis

        return analysis

    def _record_error(
        self,
        *,
        phase: str,
        error: Exception,
    ) -> None:
        self.state.total_errors += 1

        self.state.last_error = {
            "phase": phase,
            "type": type(error).__name__,
            "message": str(error),
            "time": datetime.now(UTC).isoformat(),
        }

    def _publish_event(
        self,
        event_name: str,
        payload: dict[str, Any],
    ) -> None:
        """
        Publish lifecycle events when a compatible event bus exists.

        Event publication failures are isolated from the core lifecycle.
        """

        if self.event_bus is None:
            return

        publish_method = getattr(
            self.event_bus,
            "publish",
            None,
        )

        if not callable(publish_method):
            return

        try:
            publish_method(
                event_name,
                payload,
            )
        except TypeError:
            try:
                publish_method(
                    {
                        "type": event_name,
                        "payload": payload,
                    }
                )
            except Exception as exc:
                self._record_error(
                    phase="event_publish",
                    error=exc,
                )
        except Exception as exc:
            self._record_error(
                phase="event_publish",
                error=exc,
            )
