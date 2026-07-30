"""
============================================================
ATLAS APPLICATION CORE v13.0
============================================================

Institutional Application Bootstrap and Lifecycle Orchestrator

Responsibilities
----------------
- Construct Atlas services
- Register dependencies
- Coordinate startup order
- Coordinate graceful shutdown
- Expose unified system status
- Preserve startup and shutdown errors
- Prevent partial or duplicate startup
- Keep live execution disabled by default

Architecture
------------

AtlasApplication
        |
        +-- Infrastructure
        |      |-- AtlasRuntime
        |      |-- EventBus
        |      |-- Scheduler
        |      |-- LifecycleManager
        |      |-- ServiceContainer
        |
        +-- Portfolio
        |      |-- CapitalManager
        |      |-- PositionController
        |      |-- PaperTrader
        |
        +-- Intelligence
        |      |-- AtlasBrain
        |
        +-- Market
        |      |-- MarketFeed
        |      |-- MarketLoop
        |
        +-- Execution
        |      |-- ExecutionManager
        |
        +-- Control
               |-- AtlasController

============================================================
"""

from __future__ import annotations

import logging
import traceback

from datetime import UTC, datetime
from typing import Any

from core.logger import AtlasLogger
from core.runtime import AtlasRuntime
from core.event_bus import EventBus
from core.scheduler import Scheduler
from core.lifecycle import LifecycleManager
from core.service_container import ServiceContainer

from core.brain import AtlasBrain
from core.market_loop import MarketLoop

from exchange.market_feed import MarketFeed

from core.execution_manager import ExecutionManager
from portfolio.capital_manager import CapitalManager
from core.position_controller import PositionController
from core.paper_trader import PaperTrader

from core.controller.atlas_controller import AtlasController


logger = logging.getLogger("AtlasAI.Application")


class AtlasApplication:
    """
    Central Atlas composition root.

    This class creates and connects the main services, controls their
    startup and shutdown order, and exposes a stable application status.

    Business logic should not be implemented inside this class.
    """

    VERSION = "13.0"
    NAME = "AtlasApplication"

    def __init__(
        self,
        *,
        exchange_name: str = "binance_global",
        execution_mode: str = "PAPER",
        symbols: list[str] | None = None,
        market_interval: float = 10.0,
    ) -> None:
        logger.info(
            "Initializing %s v%s",
            self.NAME,
            self.VERSION,
        )

        self.exchange_name = str(exchange_name)
        self.execution_mode = str(execution_mode).upper()
        self.symbols = list(symbols) if symbols else None
        self.market_interval = float(market_interval)

        self.running = False
        self.initialized = False

        self.created_at = datetime.now(UTC).isoformat()
        self.started_at: str | None = None
        self.stopped_at: str | None = None

        self.errors: list[dict[str, Any]] = []
        self.started_services: list[str] = []

        self._build_infrastructure()
        self._build_services()
        self._register_services()

        self.initialized = True

        logger.info(
            "%s initialized successfully",
            self.NAME,
        )

    # =========================================================
    # BUILD INFRASTRUCTURE
    # =========================================================

    def _build_infrastructure(self) -> None:
        """
        Create infrastructure-only services.
        """

        self.logger_manager = AtlasLogger()
        self.runtime = AtlasRuntime()
        self.event_bus = EventBus()
        self.scheduler = Scheduler()
        self.lifecycle = LifecycleManager()
        self.container = ServiceContainer()

    # =========================================================
    # BUILD BUSINESS SERVICES
    # =========================================================

    def _build_services(self) -> None:
        """
        Create and connect Atlas business services.
        """

        # -----------------------------------------------------
        # Portfolio
        # -----------------------------------------------------

        self.capital = CapitalManager()
        self.paper_trader = PaperTrader()

        self.position_controller = PositionController(
            event_bus=self.event_bus,
        )

        # -----------------------------------------------------
        # Intelligence
        # -----------------------------------------------------

        self.brain = AtlasBrain(
            event_bus=self.event_bus,
        )

        # -----------------------------------------------------
        # Market data
        # -----------------------------------------------------

        self.market_feed = MarketFeed(
            exchange_name=self.exchange_name,
        )

        # -----------------------------------------------------
        # Execution
        # -----------------------------------------------------

        self.execution = ExecutionManager(
            capital_manager=self.capital,
            position_controller=self.position_controller,
            paper_trader=self.paper_trader,
            event_bus=self.event_bus,
            mode=self.execution_mode,
        )

        # -----------------------------------------------------
        # Market loop
        # -----------------------------------------------------

        self.market_loop = MarketLoop(
            brain=self.brain,
            market_feed=self.market_feed,
            execution=self.execution,
            event_bus=self.event_bus,
            symbols=self.symbols,
            interval=self.market_interval,
        )

        # -----------------------------------------------------
        # Controller
        # -----------------------------------------------------

        self.controller = AtlasController(
            brain=self.brain,
            market_loop=self.market_loop,
            execution=self.execution,
        )

    # =========================================================
    # SERVICE REGISTRATION
    # =========================================================

    def _register_services(self) -> None:
        """
        Register all constructed services in the dependency container.

        This is the first active Dependency Injection step. Other modules
        may later retrieve services from the container instead of creating
        duplicate instances.
        """

        services = (
            self.logger_manager,
            self.runtime,
            self.event_bus,
            self.scheduler,
            self.lifecycle,
            self.capital,
            self.paper_trader,
            self.position_controller,
            self.brain,
            self.market_feed,
            self.execution,
            self.market_loop,
            self.controller,
        )

        for service in services:
            self.container.register(
                type(service),
                service,
            )

        logger.info(
            "Application services registered: %s",
            self.container.list_services(),
        )

    # =========================================================
    # START
    # =========================================================

    def start(self) -> bool:
        """
        Start Atlas services in dependency-safe order.

        Returns:
            True when Atlas starts successfully.
            False when startup fails.
        """

        if self.running:
            logger.warning(
                "Atlas is already running",
            )
            return True

        self.started_services.clear()
        self.stopped_at = None

        try:
            logger.info(
                "=================================================="
            )
            logger.info(
                "ATLAS STARTUP SEQUENCE"
            )
            logger.info(
                "=================================================="
            )

            self.runtime.boot()
            self.runtime.initialize()

            self.started_at = datetime.now(UTC).isoformat()

            # -------------------------------------------------
            # Execution subsystem
            # -------------------------------------------------

            self.execution.start()
            self.started_services.append("execution")

            # -------------------------------------------------
            # Exchange connection
            # -------------------------------------------------

            self.runtime.connect()

            self.market_feed.start()
            self.started_services.append("market_feed")

            # -------------------------------------------------
            # Intelligence
            # -------------------------------------------------

            self._start_optional_service(
                name="brain",
                service=self.brain,
            )

            # -------------------------------------------------
            # Runtime ready
            # -------------------------------------------------

            self.runtime.ready()

            # -------------------------------------------------
            # Market loop
            # -------------------------------------------------

            self.market_loop.start()
            self.started_services.append("market_loop")

            # -------------------------------------------------
            # Controller
            # -------------------------------------------------

            self.controller.start()
            self.started_services.append("controller")

            self.runtime.start()
            self.running = True

            logger.info(
                "ATLAS SYSTEM ONLINE"
            )
            logger.info(
                "Started services: %s",
                self.started_services,
            )

            return True

        except Exception as exc:
            self._record_error(
                phase="startup",
                error=exc,
            )

            logger.exception(
                "Atlas startup failed"
            )

            try:
                self.runtime.fail(
                    str(exc),
                )
            except Exception:
                logger.exception(
                    "Runtime failure transition failed"
                )

            self._rollback_startup()
            return False

    # =========================================================
    # OPTIONAL SERVICE START
    # =========================================================

    def _start_optional_service(
        self,
        *,
        name: str,
        service: Any,
    ) -> None:
        """
        Start a service only when it exposes a callable start method.
        """

        start_method = getattr(
            service,
            "start",
            None,
        )

        if callable(start_method):
            start_method()

        self.started_services.append(name)

    # =========================================================
    # STARTUP ROLLBACK
    # =========================================================

    def _rollback_startup(self) -> None:
        """
        Stop any service that may have started before startup failed.
        """

        logger.warning(
            "Rolling back partial Atlas startup"
        )

        self.stop()

    # =========================================================
    # STOP
    # =========================================================

    def stop(self) -> bool:
        """
        Stop Atlas services in reverse dependency order.
        """

        logger.info(
            "=================================================="
        )
        logger.info(
            "ATLAS SHUTDOWN SEQUENCE"
        )
        logger.info(
            "=================================================="
        )

        shutdown_errors = 0

        try:
            self.runtime.stop()
        except Exception as exc:
            shutdown_errors += 1
            self._record_error(
                phase="runtime_stop",
                error=exc,
            )

        shutdown_order = (
            ("controller", self.controller),
            ("market_loop", self.market_loop),
            ("execution", self.execution),
            ("market_feed", self.market_feed),
            ("scheduler", self.scheduler),
        )

        for name, service in shutdown_order:
            try:
                self._stop_service(
                    name=name,
                    service=service,
                )
            except Exception as exc:
                shutdown_errors += 1
                self._record_error(
                    phase=f"shutdown:{name}",
                    error=exc,
                )

                logger.exception(
                    "Service shutdown failed: %s",
                    name,
                )

        try:
            self.lifecycle.stop_all()
        except Exception as exc:
            shutdown_errors += 1
            self._record_error(
                phase="lifecycle_stop_all",
                error=exc,
            )

            logger.exception(
                "Lifecycle shutdown failed"
            )

        self.running = False
        self.stopped_at = datetime.now(UTC).isoformat()
        self.started_services.clear()

        try:
            self.runtime.shutdown()
        except Exception as exc:
            shutdown_errors += 1
            self._record_error(
                phase="runtime_shutdown",
                error=exc,
            )

        if shutdown_errors:
            logger.warning(
                "Atlas stopped with %s shutdown error(s)",
                shutdown_errors,
            )
            return False

        logger.info(
            "ATLAS SYSTEM OFFLINE"
        )
        return True

    # =========================================================
    # SERVICE STOP
    # =========================================================

    @staticmethod
    def _stop_service(
        *,
        name: str,
        service: Any,
    ) -> None:
        """
        Stop a service when it exposes a callable stop method.
        """

        if service is None:
            return

        stop_method = getattr(
            service,
            "stop",
            None,
        )

        if not callable(stop_method):
            logger.debug(
                "Service has no stop method: %s",
                name,
            )
            return

        stop_method()

        logger.info(
            "Service stopped: %s",
            name,
        )

    # =========================================================
    # ERROR RECORDING
    # =========================================================

    def _record_error(
        self,
        *,
        phase: str,
        error: Exception,
    ) -> None:
        """
        Store structured application errors for diagnostics.
        """

        self.errors.append(
            {
                "time": datetime.now(UTC).isoformat(),
                "phase": phase,
                "type": type(error).__name__,
                "error": str(error),
                "traceback": traceback.format_exc(),
            }
        )

    # =========================================================
    # SAFE STATUS
    # =========================================================

    @staticmethod
    def _safe_status(
        service: Any,
    ) -> dict[str, Any]:
        """
        Obtain a service status without allowing one broken service to
        break the complete Atlas status response.
        """

        if service is None:
            return {
                "available": False,
            }

        status_method = getattr(
            service,
            "status",
            None,
        )

        if not callable(status_method):
            return {
                "available": True,
                "status_supported": False,
            }

        try:
            result = status_method()

            if isinstance(result, dict):
                return result

            return {
                "available": True,
                "value": result,
            }

        except Exception as exc:
            logger.exception(
                "Service status failed: %s",
                type(service).__name__,
            )

            return {
                "available": True,
                "healthy": False,
                "status_error": str(exc),
            }

    # =========================================================
    # HEALTH
    # =========================================================

    def health(self) -> dict[str, Any]:
        """
        Return a concise application health report.
        """

        runtime_status = self._safe_status(
            self.runtime,
        )

        execution_status = self._safe_status(
            self.execution,
        )

        market_status = self._safe_status(
            self.market_loop,
        )

        healthy = bool(
            runtime_status.get("healthy", True)
            and execution_status.get("running", True)
            and market_status.get("running", True)
            and not self.errors
        )

        return {
            "healthy": healthy,
            "running": self.running,
            "runtime_state": runtime_status.get(
                "state",
                "UNKNOWN",
            ),
            "error_count": len(self.errors),
        }

    # =========================================================
    # STATUS
    # =========================================================

    def status(self) -> dict[str, Any]:
        """
        Return the stable public Atlas application status contract.

        The 'runtime' key is intentionally guaranteed because main.py
        reads status['runtime']['state'].
        """

        return {
            "application": {
                "name": self.NAME,
                "version": self.VERSION,
                "initialized": self.initialized,
                "running": self.running,
                "created_at": self.created_at,
                "started_at": self.started_at,
                "stopped_at": self.stopped_at,
                "execution_mode": self.execution_mode,
                "exchange": self.exchange_name,
            },

            "runtime": self._safe_status(
                self.runtime,
            ),

            "brain": self._safe_status(
                self.brain,
            ),

            "execution": self._safe_status(
                self.execution,
            ),

            "market_feed": self._safe_status(
                self.market_feed,
            ),

            "market_loop": self._safe_status(
                self.market_loop,
            ),

            "controller": self._safe_status(
                self.controller,
            ),

            "capital": self._safe_status(
                self.capital,
            ),

            "position_controller": self._safe_status(
                self.position_controller,
            ),

            "services": {
                "registered": self.container.list_services(),
                "started": list(self.started_services),
            },

            "health": self.health(),

            "errors": {
                "count": len(self.errors),
                "latest": (
                    self.errors[-1]
                    if self.errors
                    else None
                ),
            },
        }

    # =========================================================
    # REPRESENTATION
    # =========================================================

    def __repr__(self) -> str:
        return (
            f"<{self.NAME} "
            f"version={self.VERSION} "
            f"running={self.running} "
            f"mode={self.execution_mode}>"
        )