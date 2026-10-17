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

import functools
import logging
import os
import re
import traceback

from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from collections.abc import Mapping
from typing import Any

from core import instance_lock
from core.exit_guard import ExitGuard
from core.system_health import assess as assess_system_health
from core.experiment_ledger import EXPERIMENT_LEDGER_FILE, ExperimentAdmissionLedger
from core.logger import AtlasLogger
from core.runtime import AtlasRuntime
from core.event_bus import EventBus
from core.scheduler import Scheduler
from core.lifecycle import LifecycleManager
from core.service_container import ServiceContainer

from core.brain import AtlasBrain
from core.market_loop import MarketLoop, TELEMETRY_LOGGER_NAME

from exchange.market_feed import MarketFeed

from atlas_finance.market_data.fear_greed_provider import FearGreedProvider
from atlas_finance.market_data.treasury_yield_provider import (
    TreasuryYieldProvider,
)

from core.market_risk_regime import MarketRiskRegimeProvider

from core.execution_manager import ExecutionManager
from core.audit_event_store import AuditEventStore
from core.execution_idempotency_store import ExecutionIdempotencyStore
from core.execution_transaction_journal import ExecutionTransactionJournal
from data_layer.evidence_store import (
    DATABASE_FILENAME as EVIDENCE_DATABASE_FILENAME,
    EvidenceStore,
)
from portfolio.capital_manager import CapitalManager
from core.position_controller import PositionController
from core.paper_trader import PaperTrader

from core.risk_engine import (
    EXP001_PAPER_CONFIDENCE_EXPERIMENT,
    PAPER_CONFIDENCE_EXPERIMENTS,
    RiskEngine,
    RiskPolicy,
)
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

# The research Evidence Store root (ADR-0008). A third operator-relocatable
# root rather than a subdirectory of the durable state root: it is a
# continuously-appended SQLite database whose growth and backup profile are
# nothing like the small, precious financial state in memory_data, and
# keeping them apart lets the operator back up each on its own terms and put
# evidence on a different disk. It is anchored to the installation directory
# by default for the same CWD-independence reason as the two roots above.
DEFAULT_EVIDENCE_DIRECTORY = (
    Path(__file__).resolve().parent.parent / "evidence_store"
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
EVIDENCE_DIRECTORY_ENV = "ATLAS_EVIDENCE_DIRECTORY"

# The durable MarketLoop telemetry root (registry v4.71). Unlike the three
# roots above it has NO installation-anchored default: this installation
# sits inside a OneDrive-synced tree (ADR-0007), and a disabled telemetry
# log costs no correctness, so an unset variable means "write no file"
# rather than "write next to the code".
LOG_DIRECTORY_ENV = "ATLAS_LOG_DIRECTORY"


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
    default: Path | None,
) -> Path | None:
    """
    Return the operator override for one root, or the default when unset.

    An override must be absolute, must already exist, and must be a
    directory. It is never created here: creating it would turn a typo into
    a new empty state root, which is exactly the outcome being guarded
    against. ``~`` is expanded first, so ``~/atlas_state`` is accepted while
    a genuinely relative path is not.

    A ``None`` default means the root is optional and simply unconfigured
    when the variable is unset (the telemetry log root).
    """

    raw = os.environ.get(variable)

    if raw is None:
        return default

    candidate_text = raw.strip()

    if not candidate_text:
        unset_outcome = (
            f"use the default ({default})"
            if default is not None
            else "leave it unconfigured"
        )
        raise ConfiguredDirectoryError(
            f"{variable} is set but empty. Unset it to {unset_outcome}, "
            f"or set it to an absolute path to an existing directory.",
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


def resolve_evidence_directory() -> Path:
    """
    Return the research Evidence Store root in force right now.

    Same fail-closed contract as the two roots above, and deliberately the
    same implementation: an override that is mistyped or not yet created
    raises rather than silently opening a different, empty evidence
    database while the operator believes the configured one is in use.

    The directory is never created here. That is the whole point of the
    check: creating it would turn a typo into a new empty evidence root,
    which is exactly the outcome being guarded against.
    """

    return _resolve_configured_directory(
        variable=EVIDENCE_DIRECTORY_ENV,
        default=DEFAULT_EVIDENCE_DIRECTORY,
    )


def resolve_log_directory() -> Path | None:
    """
    Return the durable telemetry log root, or None when unconfigured.

    Same fail-closed validator as the three roots above: a set override
    that is empty, relative, missing, or not a directory raises rather
    than silently writing telemetry somewhere the operator did not choose.
    Unset means disabled - there is no installation-anchored fallback.
    """

    return _resolve_configured_directory(
        variable=LOG_DIRECTORY_ENV,
        default=None,
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


def count_experiment_admissions(audit_store: AuditEventStore, experiment_id: str) -> int:
    """Count RISK_APPROVED audit events tagged with ``experiment_id``.

    Raises if the log cannot be read, so the caller can fail closed.
    """

    count = 0

    for event in audit_store.query(event_type="RISK_APPROVED"):
        details = event.payload.get("details")

        if isinstance(details, Mapping) and details.get("experiment_id") == experiment_id:
            count += 1

    return count


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


# =============================================================
# EXECUTION HALT-REASON CLASSIFICATION
# =============================================================
#
# ExecutionManager.halt_reason (read via execution.status()'s
# operational_state) is sometimes a fixed module-level constant and
# sometimes a portfolio-foundation diagnostic that embeds a raw
# execution_id, idempotency_key, position_id, or archive line number - see
# health()'s docstring and test_health_never_publishes_the_halt_reason.
# health() must never publish that diagnostic text verbatim.
#
# This allowlist is the fail-closed alternative: only these exact,
# already-public constant codes are ever published on health()'s "reason"
# field. Anything else - including the diagnostic text, and including any
# genuinely-safe constant this list has not yet caught up with - is
# reported as the generic unclassified code instead. A false negative here
# (a safe constant reported as unclassified) only costs a less specific
# reason; a false positive would leak a secret, so the list is deliberately
# an allowlist rather than a denylist.
_SAFE_EXECUTION_HALT_REASON_CODES = frozenset(
    {
        "UNRESOLVED_TRANSACTION",
        "EXECUTION_INTERRUPTED_AFTER_SIDE_EFFECT",
        "DURABLE_FINANCIAL_FINALIZATION_FAILED",
        "CAPITAL_RESERVATION_COMMIT_FAILED",
        "CAPITAL_RESERVATION_RELEASE_FAILED",
        "SOURCE_DISAGREEMENT",
        "INSTRUMENT_RULES_UNAVAILABLE",
        "INSTRUMENT_RULES_POSITION_MISALIGNED",
        "VENUE_UPPER_BOUNDS_UNAVAILABLE",
        "VENUE_RULES_STALE",
        "FINANCIAL_STATE_RECOVERY_REQUIRED",
    }
)

UNCLASSIFIED_EXECUTION_HALT_REASON = "EXECUTION_HALT_REASON_UNCLASSIFIED"


def _classify_execution_halt_reason(raw: Any) -> str:
    """Map a raw execution halt_reason onto a safe-to-publish code.

    Only an exact match against the allowlist above is ever returned
    verbatim; everything else - a non-string, an unrecognised constant, or
    free-form diagnostic text - collapses to the generic unclassified code.
    """

    if isinstance(raw, str) and raw in _SAFE_EXECUTION_HALT_REASON_CODES:
        return raw

    return UNCLASSIFIED_EXECUTION_HALT_REASON


def _release_instance_lock_on_failed_init(init):
    """Give back the state-root lock when construction fails after taking it.

    A failed __init__ never reaches stop(), so without this a long-lived
    process (a tool, a test, a rebuild after a failure) would keep the
    reference - and the OS lock - for good.
    """

    @functools.wraps(init)
    def wrapper(self, *args, **kwargs):
        try:
            init(self, *args, **kwargs)
        except BaseException:
            root = getattr(self, "_instance_lock_root", None)
            self._instance_lock_root = None
            if root is not None:
                instance_lock.release(root)
            raise

    return wrapper


class AtlasApplication:
    """
    Central Atlas composition root.

    This class creates and connects the main services, controls their
    startup and shutdown order, and exposes a stable application status.

    Business logic should not be implemented inside this class.
    """

    VERSION = "13.0"
    NAME = "AtlasApplication"

    @_release_instance_lock_on_failed_init
    def __init__(
        self,
        *,
        exchange_name: str = "binance_global",
        execution_mode: str = "PAPER",
        symbols: list[str] | None = None,
        market_interval: float = 10.0,
        state_directory: str | Path | None = None,
        evidence_directory: str | Path | None = None,
        venue_rule_freshness_policy: VenueRuleFreshnessPolicy | None = None,
        log_directory: str | Path | None = None,
        paper_confidence_experiment: bool = False,
        paper_confidence_experiment_id: str = "EXP-001",
        paper_fee_rate: Decimal | str = "0",
        count_unrealized_in_daily_loss: bool = False,
        sleeves_enabled: bool = False,
        paper_slippage_bps: Decimal | str = "0",
        order_lifecycle_observe: bool = False,
        funding_sentiment: bool = False,
        fusion_full_weight_denominator: bool = False,
        paper_fill_model: str = "LAST_PRICE",
    ) -> None:
        logger.info(
            "Initializing %s v%s",
            self.NAME,
            self.VERSION,
        )

        self.exchange_name = str(exchange_name)
        # Task 014 (registry v5.98): normalised exactly as ExecutionManager normalises it, and an unknown
        # mode is refused instead of being reported here while the manager silently runs PAPER. LIVE stays
        # constructible for tests; it has no authority (live_execution_enabled is never passed) and no adapter.
        self.execution_mode = str(execution_mode).strip().upper()
        if self.execution_mode not in ("PAPER", "LIVE"):
            raise ValueError(f"execution_mode {execution_mode!r} is not PAPER or LIVE")
        # Registry v5.23: 0 by default (historical fee-free paper, kept for
        # every test and tool that builds the application); main.py passes
        # PAPER_FEE_RATE_PER_SIDE for the real runtime.
        self.paper_fee_rate = Decimal(str(paper_fee_rate))
        # Owner switches F-3, S1 and F-4 (2026-10-01). Off for every test or
        # tool that builds the application; main.py turns them on for the real
        # runtime, the same opt-in pattern as paper_fee_rate.
        self.count_unrealized_in_daily_loss = bool(count_unrealized_in_daily_loss)
        self.sleeves_enabled = bool(sleeves_enabled)
        self.paper_slippage_bps = Decimal(str(paper_slippage_bps))
        self.order_lifecycle_observe = bool(order_lifecycle_observe)
        self.funding_sentiment = bool(funding_sentiment)
        self.fusion_full_weight_denominator = bool(fusion_full_weight_denominator)
        # Shadow stage S2 (owner approval 2026-10-02): BOOK prices PAPER fills against
        # the live order book (core/atlas_config.py validates it and its own state dir).
        self.paper_fill_model = str(paper_fill_model).strip().upper()
        if self.paper_fill_model not in ("LAST_PRICE", "BOOK"):
            raise ValueError("paper_fill_model must be LAST_PRICE or BOOK")
        if not self.paper_slippage_bps.is_finite() or not Decimal("0") <= self.paper_slippage_bps <= Decimal("100"):
            raise ValueError("paper_slippage_bps must be within [0, 100]")
        # registry v5.01 EXP-001. Off unless the production entry point asks
        # for it, so a bare or test-built application keeps default floors
        # regardless of the calendar date. Honoured in PAPER only.
        self.paper_confidence_experiment = paper_confidence_experiment is True
        self.paper_confidence_experiment_id = str(paper_confidence_experiment_id)
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

        # One process per state root (core/instance_lock.py, registry
        # v5.08): taken before any durable store is opened, so a tool or a
        # second launch that builds an AtlasApplication directly is refused
        # here, not only the main entry point. Shared within a process.
        instance_lock.acquire(self.state_directory)
        self._instance_lock_root: Path | None = self.state_directory

        # Resolved for provenance and for the startup log only: nothing in
        # AtlasApplication opens the market archive. Resolving it here anyway
        # means a mistyped override is refused when Atlas starts rather than
        # silently at the next archive fetch, which is the fail-closed
        # direction for a root the operator believes is configured.
        self.market_archive_directory = resolve_market_archive_directory()

        # The research Evidence Store root (ADR-0008). Same "None means
        # resolve from the environment" contract as state_directory, so a
        # test or tool can point the store at its own scratch directory and
        # is never affected by what the operator has exported. Resolving
        # here means a mistyped override is refused when Atlas starts, not
        # at the first claim write.
        self.evidence_directory = (
            resolve_evidence_directory()
            if evidence_directory is None
            else Path(evidence_directory)
        )

        # Durable MarketLoop telemetry root (registry v4.71). Same "None
        # means resolve from the environment" contract; the resolved value
        # may itself be None, which means no telemetry file is written.
        self.log_directory = (
            resolve_log_directory()
            if log_directory is None
            else Path(log_directory)
        )

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

        # Last, so a construction failure above never leaves an open file
        # or a running listener thread behind.
        self.logger_manager.initialize()

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

        self.logger_manager = AtlasLogger(
            log_directory=self.log_directory,
            telemetry_logger_name=TELEMETRY_LOGGER_NAME,
        )
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

        # The paper book is a passive mirror of ExecutionPortfolioFoundation,
        # not an execution side effect: ExecutionManager projects durable
        # position truth onto it after each commit and once at startup, and
        # no execution outcome is classified against it. It still lives
        # under the same configured root as the durable execution state,
        # not beside whatever directory the process happened to start in.
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
        # The research Evidence Store (ADR-0008). Constructed here so the
        # composition root owns its path like every other durable store,
        # and so a future dashboard task can reach it off the runtime
        # object. Construction touches no disk: the database is opened in
        # start(), where a failure can be reported without preventing a
        # bare AtlasApplication() from being built in a test.
        self.evidence_store = EvidenceStore(
            self.evidence_directory / EVIDENCE_DATABASE_FILENAME,
        )

        self.brain = AtlasBrain(
            event_bus=self.event_bus,
            state_directory=self.state_directory,
            evidence_store=self.evidence_store,
            closed_positions_path=(
                self.state_directory / EXECUTION_CLOSED_POSITIONS_FILE
            ),
        )
        self.brain.fusion_full_weight_denominator = self.fusion_full_weight_denominator

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
        # EXP-001 paper confidence experiment (registry v5.01)
        # -----------------------------------------------------

        self._attach_paper_confidence_experiment()

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
            # registry v5.23: per-side paper fee, opted in by main.py only
            paper_fee_rate=self.paper_fee_rate,
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

        # Phase-2 B2: Brain-independent reduce-only exit path. Inert by
        # default (OBSERVE, no rules); ENFORCE or any rule is an owner
        # decision. It is not yet invoked from MarketLoop's cycle.
        self.exit_guard = ExitGuard(
            self.execution,
            self.portfolio_foundation,
        )

        # -----------------------------------------------------
        # Market loop
        # -----------------------------------------------------

        # Sentiment evidence (registry v4.66). Construction performs no
        # I/O; the provider fetches lazily, caches, and fails closed.
        self.sentiment_provider = FearGreedProvider()

        # Macro and market-risk evidence (registry v4.79). The Treasury
        # provider, like the sentiment provider, performs no I/O on
        # construction and fetches lazily, caches, and fails closed. The
        # market-risk provider performs no I/O at all: it reads the
        # candles MarketLoop already fetched. It is a fusion-input vote
        # only and is independent of the RiskEngine wired above.
        self.macro_provider = TreasuryYieldProvider()
        self.market_risk_provider = MarketRiskRegimeProvider()

        self.market_loop = MarketLoop(
            brain=self.brain,
            market_feed=self.market_feed,
            execution=self.execution,
            event_bus=self.event_bus,
            symbols=self.symbols,
            interval=self.market_interval,
            position_sizing_service=self.position_sizing_service,
            sentiment_provider=self.sentiment_provider,
            macro_provider=self.macro_provider,
            market_risk_provider=self.market_risk_provider,
        )
        # Audit F-3: fresh closed-candle marks for the risk engine's optional
        # unrealized daily-loss check (read-only; unused while the flag is off).
        self.execution.mark_price_provider = self.market_loop.mark_prices
        self.execution.paper_slippage_bps = self.paper_slippage_bps
        if self.paper_fill_model == "BOOK" and self.execution_mode == "PAPER":
            from atlas_finance.market_data.order_book_provider import OrderBookFillProvider

            self.execution.paper_fill_provider = OrderBookFillProvider()
        # Order state machine stage 1: observe only (owner approved 2026-10-01).
        self.execution.order_lifecycle_observe = self.order_lifecycle_observe
        # Design C: Binance funding rate as sentiment evidence when Fear & Greed is
        # neutral. OFF unless main.py turns it on (after audit + owner).
        if self.funding_sentiment:
            from atlas_finance.market_data.funding_rate_provider import FundingRateProvider
            self.market_loop.funding_provider = FundingRateProvider()
        # S1 step 2: record each position's risk bucket in a sidecar (decisions
        # are unchanged while sleeves_enabled stays False).
        from core.position_risk_buckets import POSITION_RISK_BUCKETS_FILE, PositionRiskBucketStore
        self.execution.position_risk_buckets = PositionRiskBucketStore(self.state_directory / POSITION_RISK_BUCKETS_FILE)

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
            count_unrealized_in_daily_loss=self.count_unrealized_in_daily_loss,
            sleeves_enabled=self.sleeves_enabled,
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
            "market_archive_root_source=%s evidence_root=%s "
            "evidence_root_source=%s) "
            "idempotency_loaded=%s journal_unresolved=%s",
            self.state_directory,
            self._root_source(STATE_DIRECTORY_ENV),
            self.market_archive_directory,
            self._root_source(MARKET_ARCHIVE_DIRECTORY_ENV),
            self.evidence_directory,
            self._root_source(EVIDENCE_DIRECTORY_ENV),
            self.idempotency_store.loaded,
            self.transaction_journal.has_unresolved(),
        )

    def _attach_paper_confidence_experiment(self) -> None:
        """Attach EXP-001 to the RiskEngine when opted in, and in PAPER mode only.

        The sample cap must survive restarts, so prior tagged admissions are
        counted from the durable audit log. If that log cannot be read the
        experiment stays unattached: the default floors are the fail-closed
        state.
        """

        if not self.paper_confidence_experiment or self.execution_mode != "PAPER":
            return

        experiment_id = getattr(self, "paper_confidence_experiment_id", "EXP-001")
        experiment = PAPER_CONFIDENCE_EXPERIMENTS.get(experiment_id)
        if experiment is None:
            logger.error("unknown experiment %r not attached; default confidence floors remain",
                         experiment_id)
            return

        try:
            audited = count_experiment_admissions(
                self.audit_store,
                experiment.experiment_id,
            )
        except Exception:
            logger.exception(
                "%s not attached: audit log unreadable, default confidence floors remain",
                experiment.experiment_id,
            )
            return

        # registry v5.17: a second, independent durable count. The larger of
        # the two wins, so losing audit lines can never re-open admissions;
        # an unreadable ledger keeps the experiment off (fail-closed).
        ledger = ExperimentAdmissionLedger(
            self.state_directory / EXPERIMENT_LEDGER_FILE,
        )

        try:
            recorded = ledger.count(experiment.experiment_id)
        except Exception:
            logger.exception(
                "%s not attached: admission ledger unreadable, default confidence floors remain",
                experiment.experiment_id,
            )
            return

        prior = max(audited, recorded)

        self.risk_engine.attach_experiment(
            experiment,
            prior_admissions=prior,
            admission_recorder=ledger.record,
        )

        logger.info(
            "%s attached (PAPER): floor=%s buckets=%s window=%s..%s admissions=%s/%s",
            experiment.experiment_id,
            experiment.minimum_confidence,
            sorted(b.value for b in experiment.buckets),
            experiment.starts_at.isoformat(),
            experiment.ends_at.isoformat(),
            prior,
            experiment.max_admissions,
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
            # Research evidence (observational, fail-open)
            # -------------------------------------------------
            #
            # Opened before the brain starts so the first cycle can already
            # record claims. This is the one durable store Atlas starts
            # WITHOUT: evidence carries no trading authority, so refusing
            # to trade because a research database would not open would be
            # a far worse outcome than running without it. The failure is
            # logged and remains visible in evidence_store.health().
            # getattr rather than attribute access: the store is optional by
            # design, and startup must not acquire a hard dependency on a
            # subsystem that carries no trading authority. That also keeps
            # the startup-order contract drivable by a partially constructed
            # application, which is how the lifecycle tests assert it.
            evidence_store = getattr(self, "evidence_store", None)

            if evidence_store is None:
                logger.info(
                    "No evidence store configured; continuing without "
                    "research evidence recording",
                )
            else:
                evidence_root = getattr(self, "evidence_directory", None)
                try:
                    evidence_store.open()
                    logger.info(
                        "Evidence store ready (evidence_root=%s "
                        "evidence_root_source=%s)",
                        evidence_root,
                        self._root_source(EVIDENCE_DIRECTORY_ENV),
                    )
                except Exception:
                    logger.exception(
                        "Evidence store could not be opened at %s; continuing "
                        "without research evidence recording",
                        evidence_root,
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

        try:
            return self._stop_services()
        finally:
            root = getattr(self, "_instance_lock_root", None)
            self._instance_lock_root = None
            if root is not None:
                instance_lock.release(root)

    def _stop_services(self) -> bool:

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

        # After the market loop has stopped: drains any queued telemetry
        # records into the file. A no-op when telemetry is disabled, and
        # skipped for an instance that never ran __init__ (no manager).
        # Observability only: close() never raises and is time-bounded, and
        # its outcome deliberately does not count as a shutdown error, so a
        # telemetry failure cannot change stop()'s result or the exit code.
        logger_manager = getattr(self, "logger_manager", None)
        if logger_manager is not None:
            logger_manager.close()

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

        The raw halt *reason* is still never published here. health() is
        returned verbatim to /api/health (see web_app._safe_runtime_health),
        and ExecutionManager.halt_reason can carry a portfolio-foundation
        diagnostic that embeds a raw execution_id, idempotency_key,
        position_id, or archive line number.

        What is published, when execution_halted or execution_recovery_
        required is True, is execution_halt_reason: the raw reason passed
        through _classify_execution_halt_reason's allowlist, which only
        ever returns one of a fixed set of known-safe constant codes or the
        generic UNCLASSIFIED_EXECUTION_HALT_REASON. See
        test_health_never_publishes_the_halt_reason, which still asserts
        the raw diagnostic text never reaches this payload. The full,
        unclassified reason remains available to an operator through the
        logs and status() (and, per the same loopback trust boundary, the
        /api/status route).

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

        execution_halt_reason = (
            _classify_execution_halt_reason(
                execution_operational_state.get("halt_reason"),
            )
            if execution_halted is True or execution_recovery_required is True
            else None
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

        brain_health = self._safe_health(
            self.brain,
        )

        system_health = assess_system_health(
            {
                "running": self.running,
                "loop_running": market_status.get("running"),
                "loop_thread_alive": market_health.get("thread_alive"),
                "loop_progress_age_seconds": market_health.get(
                    "loop_progress_age_seconds",
                ),
                "loop_interval_seconds": market_health.get(
                    "loop_interval_seconds",
                ),
                "market_data_stale": market_health.get("market_data_stale"),
                "execution_running": execution_status.get("running"),
                "execution_halted": execution_halted,
                "recovery_required": execution_recovery_required,
                "audit_persistence_state": execution_operational_state.get(
                    "audit_persistence_state",
                ),
                "brain_healthy": brain_health.get("healthy"),
                "policy_manifest_block": execution_operational_state.get(
                    "policy_manifest_block",
                ),
            }
        )

        return {
            "healthy": healthy,
            "running": self.running,
            # Phase-2 D1: tri-state signals; UNKNOWN is never healthy. The
            # legacy "healthy" flag above is unchanged for existing readers.
            "system_health": system_health,
            "execution_halted": execution_halted,
            "execution_recovery_required": execution_recovery_required,
            "execution_halt_reason": execution_halt_reason,
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

            "exit_guard": self._safe_status(
                getattr(self, "exit_guard", None),
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
