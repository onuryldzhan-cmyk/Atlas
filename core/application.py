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
import os
import re
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
from core.position_sizing import PositionSizingService
from core.capital_reservation import (
    CapitalReservationLedger,
    JsonReservationStore,
    ReservationArchiveStore,
)
from core.instrument_rules import (
    InstrumentRulesConfigError,
    load_instrument_ruleset,
)
from core.venue_rule_freshness import (
    VenueRuleFreshnessPolicy,
    VenueRuleFreshnessService,
)
from core.risk_state_store import JsonRiskStateStore
from core.execution_portfolio_foundation import (
    AppliedExecutionArchiveStore,
    ClosedPositionArchiveStore,
    ExecutionPortfolioFoundation,
    FinancialStateStore,
)

from core.controller.atlas_controller import AtlasController

from core.tool_gateway_contracts import CapabilityGateway
from core.local_capability_adapter import (
    LocalCapabilityProbeAdapter,
    UnconfiguredPolicyGate,
)


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

# The bulk historical market-data archive root. Nothing in the running
# application opens it - tools/fetch_historical_market_data.py is its only
# writer - but it is resolved here so both operator-relocatable roots answer
# to one validation implementation instead of drifting into two.
DEFAULT_MARKET_ARCHIVE_DIRECTORY = (
    Path(__file__).resolve().parent.parent / "data" / "market_archive"
)

# =============================================================
# OPERATOR-CONFIGURED ROOT OVERRIDES
# =============================================================
#
# Both roots above are installation-anchored defaults, and both may be
# relocated by the operator - the durable state root in particular must be
# movable off a cloud-synced volume, where sync-driven locking and delayed
# or partial writes can corrupt execution state.
#
# The override is an environment variable rather than a CLI flag or a config
# file because the supervisor already hands its child a full copy of
# os.environ (atlas_supervisor.py), so a variable exported once in the
# operator's shell survives every supervised restart without changing how
# Atlas is launched, and because core/application.py already reads the
# supervisor provenance variables the same way.
#
# The failure mode these functions exist to prevent is silent: an override
# that is mistyped, not yet created, or points at a file would - if it fell
# back to the default - open a DIFFERENT, EMPTY financial state while the
# operator believes the configured one is in use. That is why an override
# that is present but unusable raises instead of falling back. An absent
# override is not an error: it is the documented default.

STATE_DIRECTORY_ENV = "ATLAS_STATE_DIRECTORY"
MARKET_ARCHIVE_DIRECTORY_ENV = "ATLAS_MARKET_ARCHIVE_DIRECTORY"


class ConfiguredDirectoryError(RuntimeError):
    """
    An operator-supplied directory override is present but unusable.

    Raised at construction time, never swallowed and never downgraded to a
    fallback: the whole point of the check is that continuing with the
    default would be worse than not starting.
    """


def _resolve_configured_directory(
    *,
    variable: str,
    default: Path,
) -> Path:
    """
    Return the operator override for one root, or the default when unset.

    An override must be absolute, must already exist, and must be a
    directory. It is never created here: creating it would turn a typo into
    a new empty state root, which is exactly the outcome being guarded
    against. ``~`` is expanded first, so ``~/atlas_state`` is accepted while
    a genuinely relative path is not.
    """

    raw = os.environ.get(variable)

    if raw is None:
        return default

    candidate_text = raw.strip()

    if not candidate_text:
        raise ConfiguredDirectoryError(
            f"{variable} is set but empty. Unset it to use the default "
            f"({default}), or set it to an absolute path to an existing "
            f"directory.",
        )

    candidate = Path(candidate_text).expanduser()

    if not candidate.is_absolute():
        raise ConfiguredDirectoryError(
            f"{variable} must be an absolute path, got {candidate_text!r}. "
            f"A relative path would make durable state depend on the "
            f"process working directory.",
        )

    if not candidate.exists():
        raise ConfiguredDirectoryError(
            f"{variable} points at {str(candidate)!r}, which does not "
            f"exist. Create the directory (and move the existing state "
            f"into it) before setting the variable; it is deliberately "
            f"not created here.",
        )

    if not candidate.is_dir():
        raise ConfiguredDirectoryError(
            f"{variable} points at {str(candidate)!r}, which is not a "
            f"directory.",
        )

    return candidate.resolve()


def resolve_state_directory() -> Path:
    """
    Return the durable state root in force for a run starting now.

    Read at construction time rather than at import time so the value
    reflects the environment Atlas is actually started in, and so a bad
    override surfaces as a startup failure with a usable message rather
    than an import error in an unrelated tool.
    """

    return _resolve_configured_directory(
        variable=STATE_DIRECTORY_ENV,
        default=DEFAULT_STATE_DIRECTORY,
    )


def resolve_market_archive_directory() -> Path:
    """
    Return the historical market-data archive root in force right now.

    Same contract as resolve_state_directory(). Imported by
    tools/fetch_historical_market_data.py, which is the only writer of that
    archive, so the tool and the runtime can never disagree about where it
    lives.
    """

    return _resolve_configured_directory(
        variable=MARKET_ARCHIVE_DIRECTORY_ENV,
        default=DEFAULT_MARKET_ARCHIVE_DIRECTORY,
    )

# Block 5D: the checked-in static venue instrument-precision authority
# (owner decision 1). Anchored to the installation directory for the same
# reason DEFAULT_STATE_DIRECTORY is: the same runtime must load the same
# rules regardless of the process's working directory.
DEFAULT_INSTRUMENT_RULES_PATH = (
    Path(__file__).resolve().parent.parent / "config" / "instrument_rules.json"
)

RISK_ACCOUNTING_STATE_FILE = "risk_accounting_state.json"
CAPITAL_RESERVATION_STATE_FILE = "capital_reservations.json"
# Block 5H: immutable, append-only archive of terminal (COMMITTED/RELEASED)
# reservations CapitalReservationLedger.compact() has moved out of the
# working-set file above. Read through by CapitalReservationLedger.get()
# forever; never auto-compacted or read by AtlasApplication itself.
CAPITAL_RESERVATION_ARCHIVE_FILE = "capital_reservations_archive.jsonl"
EXECUTION_FINANCIAL_STATE_FILE = "execution_financial_state.json"
# Block 5I: immutable, append-only sidecars execution_financial_state.json's
# (schema v2) applied_checkpoint / closed_checkpoint point at. Read through
# by ExecutionPortfolioFoundation at construction; never auto-compacted or
# migrated by AtlasApplication itself.
EXECUTION_APPLIED_EXECUTIONS_FILE = "execution_applied_executions.jsonl"
EXECUTION_CLOSED_POSITIONS_FILE = "execution_closed_positions.jsonl"

EXECUTION_IDEMPOTENCY_STATE_FILE = "execution_idempotency.jsonl"
EXECUTION_TRANSACTION_JOURNAL_FILE = "execution_transaction_journal.jsonl"
EXECUTION_AUDIT_EVENT_FILE = "audit/atlas_audit_events.jsonl"

PAPER_TRADE_BOOK_FILE = "paper_trades.json"


# =============================================================
# SUPERVISOR PROVENANCE
# =============================================================
#
# atlas_supervisor.py hands these to the child it launches, so the
# operator surface can say whether Atlas is being supervised and how
# many times it has already been restarted. They are read once at
# construction - the values cannot change during a process lifetime -
# and never written.
#
# Both are validated strictly rather than trusted. health() is returned
# verbatim to /api/health, so anything able to set this process's
# environment could otherwise place arbitrary text into an HTTP
# response body. A value that does not match its expected shape is
# reported as absent, not echoed: an unverifiable claim of supervision
# is not published as a verified one.

SUPERVISOR_EPOCH_ENV = "ATLAS_SUPERVISOR_EPOCH"
SUPERVISOR_RESTART_COUNT_ENV = "ATLAS_SUPERVISOR_RESTART_COUNT"

_SUPERVISOR_EPOCH_PATTERN = re.compile(r"\A[0-9a-f]{32}\Z")


def _read_supervisor_epoch() -> str | None:
    """Return the supervisor run identifier, or None when unverifiable."""

    value = os.environ.get(SUPERVISOR_EPOCH_ENV)

    if value is None:
        return None

    return value if _SUPERVISOR_EPOCH_PATTERN.match(value) else None


def _read_supervisor_restart_count() -> int | None:
    """Return the restart count, or None when absent or malformed."""

    value = os.environ.get(SUPERVISOR_RESTART_COUNT_ENV)

    if value is None:
        return None

    try:
        count = int(value)
    except (TypeError, ValueError):
        return None

    return count if count >= 0 else None


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
        state_directory: str | Path | None = None,
        venue_rule_freshness_policy: VenueRuleFreshnessPolicy | None = None,
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
        # None means "resolve from the environment now", which is the
        # documented default path; an explicit argument always wins, so every
        # test and tool can still point a runtime at its own directory and is
        # never affected by what the operator has exported.
        self.state_directory = (
            resolve_state_directory()
            if state_directory is None
            else Path(state_directory)
        )

        # Resolved for provenance and for the startup log only: nothing in
        # AtlasApplication opens the market archive. Resolving it here anyway
        # means a mistyped override is refused when Atlas starts rather than
        # silently at the next archive fetch, which is the fail-closed
        # direction for a root the operator believes is configured.
        self.market_archive_directory = resolve_market_archive_directory()

        # Block 6A: the venue-rule freshness policy in force for this run.
        # Operator-configurable at the composition boundary; the documented
        # default bounds staleness at the operator refresh cadence.
        self.venue_rule_freshness_policy = (
            venue_rule_freshness_policy
            if venue_rule_freshness_policy is not None
            else VenueRuleFreshnessPolicy()
        )

        self.running = False
        self.initialized = False

        self.created_at = datetime.now(UTC).isoformat()
        self.started_at: str | None = None
        self.stopped_at: str | None = None

        self.errors: list[dict[str, Any]] = []
        self.started_services: list[str] = []

        # Read once: a supervisor cannot change these mid-process, and
        # health() must not touch the environment on every call.
        self.supervisor_epoch = _read_supervisor_epoch()
        self.supervisor_restart_count = _read_supervisor_restart_count()

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

        # The intelligence layer persists its own memory, world model and
        # reasoning records. Those defaulted to a CWD-relative "memory_data"
        # directory, which put AI state wherever the process happened to be
        # started and split it away from the configured durable root. The
        # resolved root is threaded through so both land in exactly the same
        # place, whatever the operator configured.
        self.brain = AtlasBrain(
            event_bus=self.event_bus,
            state_directory=self.state_directory,
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
        # Venue instrument precision (Block 5D)
        # -----------------------------------------------------

        self._build_instrument_rules()

        # -----------------------------------------------------
        # Execution
        # -----------------------------------------------------

        # The trade-enabled symbol universe this run is configured for. A
        # symbol left unspecified falls back to MarketLoop's own default
        # list, so the instrument-rules startup gate checks exactly the
        # symbols MarketLoop will actually scan and trade.
        configured_symbols = (
            list(self.symbols) if self.symbols else list(MarketLoop.DEFAULT_SYMBOLS)
        )

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
            instrument_rules=self.instrument_ruleset,
            instrument_rule_freshness=self.venue_rule_freshness,
            configured_symbols=configured_symbols,
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
            position_sizing_service=self.position_sizing_service,
        )

        # -----------------------------------------------------
        # Controller
        # -----------------------------------------------------

        self.controller = AtlasController(
            brain=self.brain,
            market_loop=self.market_loop,
            execution=self.execution,
        )

        self._build_capability_gateway()

    # =========================================================
    # CAPABILITY GATEWAY
    # =========================================================

    def _build_capability_gateway(self) -> None:
        """
        Bind the capability contracts to their concrete implementations.

        This is the only place in Atlas allowed to decide which policy gate
        and which adapters exist, exactly as it is for the risk services
        below. Intelligence cannot reach an adapter directly — the L4->L2
        forbidden edge makes that a structural impossibility rather than a
        convention — so the composition root is the sole binding point.

        Nothing built here runs. The gateway is not started, not scheduled,
        not subscribed to the event bus, and not referenced by the brain,
        the market loop, or the execution path. It performs work only if a
        caller invokes it, and today no caller does.

        It also cannot perform work if one did. `UnconfiguredPolicyGate`
        denies every operation, and the gateway consults the policy before
        it touches an adapter, so every invocation through this instance
        stops at POLICY_DENIED with no side effect. Widening that requires
        constructing a different gate here, which is a visible diff and a
        reviewable decision.

        The adapter is registered rather than hidden so that the wiring is
        inspectable and injectable — a caller receives the adapter from the
        container instead of importing the concrete class.
        """

        self.capability_policy_gate = UnconfiguredPolicyGate()

        self.capability_gateway = CapabilityGateway(
            self.capability_policy_gate,
        )

        self.capability_probe_adapter = LocalCapabilityProbeAdapter()

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

        # The single upstream sizing authority (Block 5C). It proposes a BUY
        # quote allocation only; it shares this exact RiskPolicy instance
        # rather than a duplicate, so its bucket allocation percentage can
        # never drift from the one RiskEngine approves against.
        self.position_sizing_service = PositionSizingService(
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
            archive=ReservationArchiveStore(
                self.state_directory / CAPITAL_RESERVATION_ARCHIVE_FILE,
            ),
        )

        self.portfolio_foundation = ExecutionPortfolioFoundation(
            FinancialStateStore(
                self.state_directory / EXECUTION_FINANCIAL_STATE_FILE,
            ),
            applied_archive=AppliedExecutionArchiveStore(
                self.state_directory / EXECUTION_APPLIED_EXECUTIONS_FILE,
            ),
            closed_archive=ClosedPositionArchiveStore(
                self.state_directory / EXECUTION_CLOSED_POSITIONS_FILE,
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
            "(state_root_source=%s market_archive_root=%s "
            "market_archive_root_source=%s) "
            "idempotency_loaded=%s journal_unresolved=%s",
            self.state_directory,
            self._root_source(STATE_DIRECTORY_ENV),
            self.market_archive_directory,
            self._root_source(MARKET_ARCHIVE_DIRECTORY_ENV),
            self.idempotency_store.loaded,
            self.transaction_journal.has_unresolved(),
        )

    @staticmethod
    def _root_source(variable: str) -> str:
        """
        Report whether a root came from an override or from the default.

        The path alone does not say that: an operator who exported a variable
        pointing at the installation default would see an identical line. The
        source is what makes a wrong-directory incident diagnosable from the
        log.
        """

        return variable if os.environ.get(variable) else "default"

    # =========================================================
    # VENUE INSTRUMENT PRECISION (BLOCK 5D)
    # =========================================================

    def _build_instrument_rules(self) -> None:
        """
        Load the checked-in static venue instrument-rules config.

        This is the sole place that reads ``config/instrument_rules.json``
        (owner decision 1): ``ExecutionManager`` consumes the result but
        never constructs, mutates, or invents an entry. A missing, malformed,
        or contract-invalid config does not fabricate a permissive ruleset -
        it leaves ``self.instrument_ruleset`` as ``None``, and
        ``ExecutionManager.start()`` then halts fail-closed with
        ``INSTRUMENT_RULES_UNAVAILABLE`` for any trade-enabled or held
        symbol, exactly as an unready durable store already halts startup
        above.

        Block 6A: this is also where the runtime's single venue-rule
        freshness authority is built. The composition root owns the clock -
        the financial core is handed the service, never an ambient
        ``datetime.now()`` - and the same instance backs the startup gate and
        every health/status surface, so they cannot disagree about how old
        the rules are.
        """

        self.venue_rule_freshness = VenueRuleFreshnessService(
            policy=self.venue_rule_freshness_policy,
        )

        try:
            self.instrument_ruleset = load_instrument_ruleset(
                DEFAULT_INSTRUMENT_RULES_PATH
            )
        except InstrumentRulesConfigError as exc:
            self.instrument_ruleset = None
            logger.error(
                "Instrument rules unavailable path=%s error=%s",
                DEFAULT_INSTRUMENT_RULES_PATH,
                exc,
            )
            return

        freshness = self.venue_rule_freshness.assess(self.instrument_ruleset)

        logger.info(
            "Instrument rules loaded symbols=%s schema_version=%s "
            "freshness=%s age_seconds=%s maximum_age_seconds=%s",
            self.instrument_ruleset.symbols,
            self.instrument_ruleset.schema_version,
            freshness.status.value,
            freshness.age_seconds,
            freshness.maximum_age_seconds,
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
            # Registered, not started: these have no lifecycle, and the
            # startup sequence below never references them.
            self.capability_gateway,
            self.capability_probe_adapter,
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

    @staticmethod
    def _safe_health(
        service: Any,
    ) -> dict[str, Any]:
        """
        Obtain a service health report without allowing one broken service
        to break the complete Atlas health response.

        This mirrors _safe_status for services that expose health() as a
        surface distinct from status(). MarketLoop is one: its staleness
        verdict lives on health(), while thread liveness lives on both.
        """

        if service is None:
            return {
                "available": False,
            }

        health_method = getattr(
            service,
            "health",
            None,
        )

        if not callable(health_method):
            return {
                "available": True,
                "health_supported": False,
            }

        try:
            result = health_method()

            if isinstance(result, dict):
                return result

            return {
                "available": True,
                "value": result,
            }

        except Exception as exc:
            logger.exception(
                "Service health failed: %s",
                type(service).__name__,
            )

            return {
                "available": True,
                "healthy": False,
                "health_unreadable": True,
                "health_error": str(exc),
            }

    # =========================================================
    # HEALTH
    # =========================================================

    def health(self) -> dict[str, Any]:
        """
        Return a concise application health report.

        Market-data signals
        -------------------
        market_data_stale is reported only. It mirrors MarketLoop.health()'s
        own contract, where staleness never affects healthy and never gates
        trading or decisions - so it must not silently become a health gate
        one layer up either. A market_data_stale of None is genuinely
        "unknown", and an unreadable health() is not the same condition as
        an absent one: market_data_stale_reason names the unreadable case
        explicitly, because the operator's remediation differs.

        market_loop_thread_alive, by contrast, does gate healthy: the market
        worker is a daemon thread, and a thread that has died while the loop
        still believes it is running is a genuinely unhealthy application,
        not a stale-data condition. An absent thread_alive key means the
        market service does not expose thread liveness at all, which is
        unknown rather than evidence of a dead thread, so it does not flip
        healthy on its own.

        Execution recovery state
        ------------------------
        execution_halted and execution_recovery_required also gate healthy,
        for the same reason thread_alive does. ExecutionManager.start()
        returns True when it finds corrupt or unresolved durable state: it
        sets execution_halted / recovery_required, keeps running True, and
        every later admission fails closed with RECOVERY_REQUIRED. Reading
        only execution_status["running"] therefore reported a runtime that
        will never trade again as healthy - and under process supervision
        that is indistinguishable from a working Atlas, because the process
        is alive and answering.

        This is a read-only correction. Nothing here changes when execution
        halts, what halts it, or how it recovers; it only stops health()
        from contradicting the halt.

        Only an explicit True flips healthy. An absent operational_state, or
        a non-dictionary one, means the execution service does not expose
        recovery state at all - unknown, not evidence of a halt - exactly as
        an absent thread_alive is treated above.

        The halt *reason* is deliberately not published here. health() is
        returned verbatim to /api/health (see web_app._safe_runtime_health),
        and ExecutionManager.halt_reason can carry a portfolio-foundation
        diagnostic that embeds a raw execution_id, idempotency_key,
        position_id, or archive line number. The booleans say that an
        operator is needed; the logs and status() say why.

        Supervisor provenance
        ---------------------
        supervised / supervisor_epoch / supervisor_restart_count report
        whether atlas_supervisor.py launched this process and how many times
        it has restarted it. They are read from the environment once at
        construction and validated there; an absent or malformed value is
        reported as absent rather than echoed. They are provenance only and
        never gate healthy - a restarted Atlas is not by itself an unhealthy
        one, and the conditions that are unhealthy are already above.
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

        market_health = self._safe_health(
            self.market_loop,
        )

        execution_operational_state = execution_status.get(
            "operational_state",
        )

        if not isinstance(execution_operational_state, dict):
            execution_operational_state = {}

        execution_halted = execution_operational_state.get(
            "execution_halted",
        )

        execution_recovery_required = execution_operational_state.get(
            "recovery_required",
        )

        healthy = bool(
            runtime_status.get("healthy", True)
            and execution_status.get("running", True)
            and execution_halted is not True
            and execution_recovery_required is not True
            and market_status.get("running", True)
            and market_status.get("thread_alive") is not False
            and not self.errors
        )

        return {
            "healthy": healthy,
            "running": self.running,
            "execution_halted": execution_halted,
            "execution_recovery_required": execution_recovery_required,
            "supervised": self.supervisor_epoch is not None,
            "supervisor_epoch": self.supervisor_epoch,
            "supervisor_restart_count": self.supervisor_restart_count,
            "runtime_state": runtime_status.get(
                "state",
                "UNKNOWN",
            ),
            "error_count": len(self.errors),
            "market_data_stale": market_health.get(
                "market_data_stale",
            ),
            "market_data_stale_reason": (
                "MARKET_HEALTH_UNREADABLE"
                if market_health.get("health_unreadable") is True
                else None
            ),
            "market_loop_thread_alive": market_status.get(
                "thread_alive",
            ),
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
