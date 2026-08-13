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
from decimal import Decimal
from pathlib import Path
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
from core.audit_event_store import AuditEventStore
from core.execution_idempotency_store import ExecutionIdempotencyStore
from core.execution_transaction_journal import ExecutionTransactionJournal
from portfolio.capital_manager import CapitalManager
from core.position_controller import PositionController
from core.paper_trader import PaperTrader

from core.risk_engine import RiskEngine, RiskPolicy
from core.capital_reservation import (
    CapitalReservationLedger,
    JsonReservationStore,
)
from core.risk_state_store import JsonRiskStateStore
from core.execution_portfolio_foundation import (
    ExecutionPortfolioFoundation,
    FinancialStateStore,
)

from core.controller.atlas_controller import AtlasController


logger = logging.getLogger("AtlasAI.Application")


# =============================================================
# DURABLE STATE LOCATION
# =============================================================
#
# Every durable file Atlas execution depends on — financial state
# and execution durability alike — is located here, in the
# composition root, and derived from one configured persistence
# root. No domain or execution module invents a path of its own,
# and none of them resolve a default against the process working
# directory: the same configured state directory must produce the
# same durable behaviour from any CWD.
#
# The default root is anchored to the installation directory
# rather than to the CWD for the same reason. The file names and
# the layout below are the established ones; no stored format is
# renamed or migrated here.

DEFAULT_STATE_DIRECTORY = Path(__file__).resolve().parent.parent / "memory_data"

RISK_ACCOUNTING_STATE_FILE = "risk_accounting_state.json"
CAPITAL_RESERVATION_STATE_FILE = "capital_reservations.json"
EXECUTION_FINANCIAL_STATE_FILE = "execution_financial_state.json"

EXECUTION_IDEMPOTENCY_STATE_FILE = "execution_idempotency.json"
EXECUTION_TRANSACTION_JOURNAL_FILE = "execution_transaction_journal.json"
EXECUTION_AUDIT_EVENT_FILE = "audit/atlas_audit_events.jsonl"

PAPER_TRADE_BOOK_FILE = "paper_trades.json"


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
        state_directory: str | Path = DEFAULT_STATE_DIRECTORY,
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
        self.state_directory = Path(state_directory)

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

        # The paper book is a durable execution side effect: open_trade()
        # and close_trade() persist it, and an interrupted execution is
        # classified against it. It therefore belongs under the same
        # configured root as the other durable execution state, not beside
        # whatever directory the process happened to start in.
        self.paper_trader = PaperTrader(
            filename=str(
                self.state_directory / PAPER_TRADE_BOOK_FILE
            ),
        )

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
        # Canonical financial risk services
        # -----------------------------------------------------

        self._build_financial_services()

        # -----------------------------------------------------
        # Durable execution stores
        # -----------------------------------------------------

        self._build_execution_durability()

        # -----------------------------------------------------
        # Execution
        # -----------------------------------------------------

        self.execution = ExecutionManager(
            capital_manager=self.capital,
            position_controller=self.position_controller,
            paper_trader=self.paper_trader,
            event_bus=self.event_bus,
            mode=self.execution_mode,
            idempotency_store=self.idempotency_store,
            audit_store=self.audit_store,
            transaction_journal=self.transaction_journal,
            risk_engine=self.risk_engine,
            reservation_ledger=self.reservation_ledger,
            risk_state_store=self.risk_state_store,
            portfolio_foundation=self.portfolio_foundation,
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
    # CANONICAL FINANCIAL RISK SERVICES
    # =========================================================

    def _build_financial_services(self) -> None:
        """
        Construct the single canonical financial-risk service family.

        Concrete implementation choice and durable-state locations are
        owned here, in the composition root, so that execution and
        intelligence modules never construct infrastructure of their own.

        The risk policy is derived from the already configured portfolio
        capital; no policy number is introduced or overridden here.

        None of these services fabricate a permissive ready state. A
        missing or corrupt store leaves the corresponding service
        not-ready, and the canonical execution path refuses new risk on
        that basis rather than falling back to a legacy component.
        """

        self.risk_policy = RiskPolicy(
            total_capital=Decimal(
                str(
                    self.capital.total_capital
                )
            ),
        )

        self.risk_engine = RiskEngine(
            self.risk_policy,
        )

        self.risk_state_store = JsonRiskStateStore(
            self.state_directory / RISK_ACCOUNTING_STATE_FILE,
        )

        self.reservation_ledger = CapitalReservationLedger(
            JsonReservationStore(
                self.state_directory / CAPITAL_RESERVATION_STATE_FILE,
            ),
            self.risk_policy.allocatable_capital,
        )

        self.portfolio_foundation = ExecutionPortfolioFoundation(
            FinancialStateStore(
                self.state_directory / EXECUTION_FINANCIAL_STATE_FILE,
            ),
        )

        logger.info(
            "Canonical financial services constructed "
            "policy_version=%s reservation_state_ready=%s "
            "portfolio_state_ready=%s",
            self.risk_policy.version,
            self.reservation_ledger.ready,
            self.portfolio_foundation.ready,
        )

    # =========================================================
    # DURABLE EXECUTION STORES
    # =========================================================

    def _build_execution_durability(self) -> None:
        """
        Construct the durable execution stores from the configured root.

        Idempotency, audit, and transaction-journal persistence decide
        whether a restarted Atlas recognises a completed request, detects an
        unresolved transaction, and continues the same audit chain. Leaving
        those locations to a CWD-relative default inside ExecutionManager
        made restart behaviour depend on where the process happened to be
        started; owning them here makes it depend only on configuration.

        Each store keeps its own fail-closed load semantics. A missing or
        corrupt file is not repaired or replaced here.
        """

        self.idempotency_store = ExecutionIdempotencyStore(
            self.state_directory / EXECUTION_IDEMPOTENCY_STATE_FILE,
        )

        self.transaction_journal = ExecutionTransactionJournal(
            self.state_directory / EXECUTION_TRANSACTION_JOURNAL_FILE,
        )

        self.audit_store = AuditEventStore(
            self.state_directory / EXECUTION_AUDIT_EVENT_FILE,
        )

        logger.info(
            "Durable execution stores constructed under %s "
            "idempotency_loaded=%s journal_unresolved=%s",
            self.state_directory,
            self.idempotency_store.loaded,
            self.transaction_journal.has_unresolved(),
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
            self.risk_engine,
            self.reservation_ledger,
            self.risk_state_store,
            self.portfolio_foundation,
            self.idempotency_store,
            self.transaction_journal,
            self.audit_store,
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

            self._start_service(
                name="execution",
                service=self.execution,
                required=True,
            )

            # -------------------------------------------------
            # Exchange connection
            # -------------------------------------------------

            self.runtime.connect()

            self._start_service(
                name="market_feed",
                service=self.market_feed,
                required=True,
            )

            # -------------------------------------------------
            # Intelligence
            # -------------------------------------------------

            self._start_service(
                name="brain",
                service=self.brain,
                required=True,
            )

            # -------------------------------------------------
            # Runtime ready
            # -------------------------------------------------

            self.runtime.ready()

            # -------------------------------------------------
            # Market loop
            # -------------------------------------------------

            self._start_service(
                name="market_loop",
                service=self.market_loop,
                required=True,
            )

            # -------------------------------------------------
            # Controller
            # -------------------------------------------------

            self._start_service(
                name="controller",
                service=self.controller,
                required=True,
            )

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
    # SERVICE START
    # =========================================================

    def _start_service(
        self,
        *,
        name: str,
        service: Any,
        required: bool = True,
    ) -> bool:
        """
        Start one application service and validate its result.

        Supported successful return contracts:
        - None for legacy void start methods
        - True for boolean lifecycle methods
        - dictionaries that do not report an error or failure state

        A service is added to started_services only after its startup
        result has been validated successfully.
        """

        if service is None:
            if required:
                raise RuntimeError(
                    f"Required service is unavailable: {name}"
                )

            logger.info(
                "Optional service unavailable: %s",
                name,
            )
            return False

        start_method = getattr(
            service,
            "start",
            None,
        )

        if not callable(start_method):
            if required:
                raise RuntimeError(
                    f"Required service has no start method: {name}"
                )

            logger.info(
                "Optional service has no start method: %s",
                name,
            )
            return False

        try:
            result = start_method()
            self._validate_start_result(
                name=name,
                result=result,
            )
        except Exception:
            try:
                self._stop_service(
                    name=name,
                    service=service,
                )
            except Exception:
                logger.exception(
                    "Failed service cleanup also failed: %s",
                    name,
                )

            raise

        self.started_services.append(
            name
        )

        logger.info(
            "Service started: %s",
            name,
        )

        return True

    @staticmethod
    def _validate_start_result(
        *,
        name: str,
        result: Any,
    ) -> None:
        """
        Normalize heterogeneous service start return contracts.
        """

        if result is None:
            return

        if isinstance(
            result,
            bool,
        ):
            if not result:
                raise RuntimeError(
                    f"Service startup returned False: {name}"
                )

            return

        if isinstance(
            result,
            dict,
        ):
            status = str(
                result.get(
                    "status",
                    "",
                )
            ).strip().upper()

            failure_statuses = {
                "ERROR",
                "FAIL",
                "FAILED",
                "FAILURE",
                "REJECTED",
            }

            if status in failure_statuses:
                raise RuntimeError(
                    f"Service startup failed: {name}; "
                    f"status={status}"
                )

            if result.get(
                "success"
            ) is False:
                raise RuntimeError(
                    f"Service startup reported success=False: {name}"
                )

            if (
                "running" in result
                and result.get("running") is False
                and status not in {
                    "SKIPPED",
                    "DISABLED",
                }
            ):
                raise RuntimeError(
                    f"Service startup did not enter running state: {name}"
                )

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

        service_map = {
            "execution": self.execution,
            "market_feed": self.market_feed,
            "brain": self.brain,
            "market_loop": self.market_loop,
            "controller": self.controller,
            "scheduler": self.scheduler,
        }

        shutdown_names = list(
            reversed(
                self.started_services
            )
        )

        for name in shutdown_names:
            service = service_map.get(
                name
            )

            if service is None:
                continue

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
    # TERMINAL SHUTDOWN
    # =========================================================

    def shutdown(self) -> bool:
        """
        Perform the public terminal application shutdown.

        The current legacy stop() implementation already performs full
        service cleanup and terminates the runtime. This method provides
        an explicit and stable terminal lifecycle entry point while
        preserving backward compatibility with existing stop() callers.

        The operation is idempotent: repeated calls are safe.
        """

        return self.stop()

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
