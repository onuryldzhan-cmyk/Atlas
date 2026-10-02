"""
============================================================
ATLAS EXECUTION MANAGER v29.0
============================================================

Institutional Execution Orchestrator

Purpose
-------
ExecutionManager is the application-level coordinator for Atlas orders.
It validates canonical execution requests, applies risk and position gates,
calculates capital allocation, coordinates paper execution, synchronizes the
authoritative PositionController, publishes lifecycle events, and maintains
bounded operational diagnostics.

Design principles
-----------------
- Execution contracts have one source of truth: core.execution_models
- PositionController owns position lifecycle state
- PaperTrader owns paper-fill and paper-account simulation
- CapitalManager owns position sizing and capital availability
- Live execution is denied by default
- Dependency failures are explicit and observable
- Compatibility fallbacks are isolated at adapter boundaries
- No production change is silently accepted

Architecture
------------
Atlas Brain / Decision Engine
            |
            v
      ExecutionRequest
            |
            v
      ExecutionManager
       /      |       \
 Risk Gate  Capital   Mode Router
              |          |
              |      Paper / Live
              |          |
              +---- PositionController
                         |
                  Audit / Event Bus

============================================================
"""

from __future__ import annotations

from contextlib import nullcontext
from dataclasses import dataclass
import logging
from decimal import ROUND_DOWN, ROUND_HALF_EVEN, ROUND_UP, Decimal, InvalidOperation, localcontext
import threading
import time
import uuid

from datetime import UTC, date, datetime
from enum import Enum
from typing import Any, Mapping, cast

from atlas_security import sanitize_sensitive_data

from core.audit_event_store import (
    AuditEventStore,
)

from core.execution_idempotency_store import (
    ExecutionIdempotencyStore,
)

from core.execution_transaction_journal import (
    CommitOutcome,
    ExecutionTransactionJournal,
)

from core.execution_models import (
    ExecutionRequest,
    ExecutionResult,
    normalize_risk,
)
from core.execution_portfolio_foundation import (
    SETTLEMENT_CONTEXT_PRECISION,
    ExecutionPortfolioFoundation,
    mint_long_position_id,
)
from core.fee_accounting import FeeNormalizer, FeeRejected
from core.instrument_rules import (
    FULL_EXIT_ABOVE_VENUE_MAXIMUM,
    VENUE_UPPER_BOUNDS_UNAVAILABLE,
    InstrumentRuleset,
    floor_to_step,
    is_aligned_to_step,
)
from core.venue_rule_freshness import (
    VenueRuleFreshnessReport,
    VenueRuleFreshnessService,
)

from core.risk_engine import (
    PositionExposure,
    RiskEngine,
    RiskRequest,
    RiskState,
)
from core.capital_reservation import CapitalReservationLedger, ReservationStatus
from core.risk_state_store import RestoredRiskState

from data_layer.runtime_safety import (
    FinancialRuntimeSafetyService,
)


# Registry v5.23 (owner decision: 0.1% per side, the public Binance spot base
# rate; the owner's account tier is UNKNOWN). Pinned here, not configurable:
# changing it is a governed change. Applies to paper fills only.
PAPER_FEE_RATE_PER_SIDE = Decimal("0.001")
PAPER_FEE_QUANTUM = Decimal("0.00000001")

logger = logging.getLogger(
    "AtlasAI.ExecutionManager"
)


class ExecutionResetRefusedError(RuntimeError):
    """``ExecutionManager.reset()`` refused a destructive runtime reset.

    Block 5J. The transaction journal and the idempotency store are a paired
    execution authority: the journal owns the commit outcome, the idempotency
    store owns the terminal result a replayed request must be answered with,
    and ``FinancialRuntimeSafetyService`` requires every COMMITTED journal
    entry to still have its idempotency counterpart. Erasing one half while
    leaving the other manufactures ``SOURCE_DISAGREEMENT`` out of a healthy
    book, so ``reset()`` refuses rather than proceeding. The message is a
    fixed reason token (never a request_id, execution_id, or state payload).
    """


class _Continue:
    """Marker a ``_decision_*`` phase returns to let the run go on (T-0013 audit, LOW).

    ``None`` is deliberately not the marker: if a terminal result were ever None
    (e.g. a patched ``reject``), the single original body returned it; with None
    as the marker the split would have fallen through to execution (fail-open).
    """

    __slots__ = ()


_CONTINUE = _Continue()


@dataclass
class _DecisionRun:
    """State one ``ExecutionManager._execute_decision`` call threads through its phases (T-0013).

    ``request_claimed`` and ``last_audit_event_id`` are written by the phases
    exactly where the original single body assigned its locals, so the
    ``except`` and ``finally`` clauses observe the same values.
    """

    started_at: float
    request: ExecutionRequest | None = None
    request_id: str | None = None
    request_claimed: bool = False
    last_audit_event_id: str | None = None


class ExecutionManager:
    """
    Validate, route, execute, and observe Atlas execution requests.

    The manager accepts dictionaries, dataclasses, model objects, or any object
    exposing ``to_dict()``. All inputs are converted into the canonical
    ``ExecutionRequest`` contract before validation.

    Sizing authority
    ----------------
    ``amount`` is quote-currency capital throughout, never base units.

    This manager sizes nothing. A request arrives carrying the allocation its
    caller intends, ``RiskEngine`` either approves that exact amount or
    refuses the request, and from approval onward the approved amount is the
    only quantity execution may commit. A BUY that carries no allocation is
    refused as ``UNSIZED_REQUEST_REJECTED`` rather than being handed a size
    from anywhere: policy ceilings bound an intent, they never manufacture
    one. There is no post-risk allocation step, no CapitalManager sizing, no
    confidence-derived size, and no default-allocation fallback.

    The one exception is not sizing at all: a reduction that names no amount
    means "exit this position", so it resolves to the exposure the durable
    book actually holds (``_requested_quote_allocation``).

    Financial precision
    -------------------
    The approved allocation is carried as an exact ``Decimal`` on
    ``ExecutionRequest.approved_quote_allocation`` and read from there by
    every authoritative consumer - admission key, reservation, execution and
    durable finalization alike. ``ExecutionRequest.amount`` is a lossy
    ``float`` mirror maintained for historical callers; changing it cannot
    change what executes.

    ``CapitalManager`` is composed for status and compatibility reporting
    only. It holds no execution authority - it cannot size, veto, override,
    or reinterpret a canonical ``RiskDecision``.
    """

    VERSION = "31.3"

    NAME = "ExecutionManager"

    MODE_PAPER = "PAPER"
    MODE_LIVE = "LIVE"

    MIN_CONFIDENCE = 60.0

    MAX_HISTORY = 500
    MAX_REJECTIONS = 500
    MAX_ERRORS = 500

    VALID_ACTIONS = {
        "BUY",
        "SELL",
    }

    NON_EXECUTION_ACTIONS = {
        "HOLD",
        "WAIT",
        "NEUTRAL",
        "NONE",
        "NO_ACTION",
    }

    SUCCESS_STATUSES = {
        "PAPER_EXECUTED",
        "EXECUTED",
        "COMPLETED",
        "SUCCESS",
        "FILLED",
        "CLOSED",
    }

    FAILURE_STATUSES = {
        "FAILED",
        "ERROR",
    }


    # Registry v5.23: class default so instances built without __init__
    # (e.g. test doubles via __new__) keep the historical fee-free paper path.
    paper_fee_rate: Decimal = Decimal("0")

    def __init__(
        self,
        capital_manager: Any | None = None,
        position_controller: Any | None = None,
        paper_trader: Any | None = None,
        event_bus: Any | None = None,
        mode: str = MODE_PAPER,
        minimum_confidence: float = MIN_CONFIDENCE,
        live_execution_enabled: bool = False,
        idempotency_store: (
            ExecutionIdempotencyStore | None
        ) = None,
        idempotency_file: str = (
            ExecutionIdempotencyStore.DEFAULT_FILE
        ),
        audit_store: (
            AuditEventStore | None
        ) = None,
        audit_file: str = (
            AuditEventStore.DEFAULT_FILE
        ),
        audit_enabled: bool = True,
        transaction_journal: (
            ExecutionTransactionJournal | None
        ) = None,
        transaction_journal_file: str = (
            ExecutionTransactionJournal.DEFAULT_FILE
        ),
        financial_safety_service: (
            FinancialRuntimeSafetyService | None
        ) = None,
        risk_engine: RiskEngine | None = None,
        reservation_ledger: CapitalReservationLedger | None = None,
        risk_state_store: Any | None = None,
        portfolio_foundation: ExecutionPortfolioFoundation | None = None,
        instrument_rules: InstrumentRuleset | None = None,
        instrument_rule_freshness: VenueRuleFreshnessService | None = None,
        configured_symbols: list[str] | tuple[str, ...] | None = None,
        paper_fee_rate: Decimal = Decimal("0"),
    ) -> None:
        # Registry v5.23: per-side paper fee rate. Default 0 keeps the
        # historical fee-free behaviour for any directly built manager; the
        # composition root passes PAPER_FEE_RATE_PER_SIDE.
        paper_fee_rate = Decimal(str(paper_fee_rate))
        if not paper_fee_rate.is_finite() or paper_fee_rate < 0 or paper_fee_rate >= 1:
            raise ValueError("paper_fee_rate must be in [0, 1)")
        self.paper_fee_rate = paper_fee_rate
        # Retained for status/compatibility reporting only. No execution path
        # reads it: it is never asked to size an allocation and never asked to
        # approve a request. Removing the parameter outright would break every
        # existing caller for no safety gain, so the authority is withdrawn
        # rather than the composition.
        self.capital_manager = capital_manager
        self.position_controller = position_controller
        self.paper_trader = paper_trader
        self.event_bus = event_bus
        self.risk_engine = risk_engine
        self.reservation_ledger = reservation_ledger
        self.risk_state_store = risk_state_store
        self.portfolio_foundation = portfolio_foundation
        # S1 step 2 (owner approved option B, 2026-10-01): optional sidecar of
        # the bucket each position was opened under. None keeps every
        # exposure at risk_bucket=None (UNKNOWN), exactly as before.
        self.position_risk_buckets: Any | None = None
        # Order state machine stage 1 (observe only), default OFF.
        self.order_lifecycle_observe: bool = False
        self.order_lifecycle_violations: list[dict[str, str]] = []
        # Audit F-B: held coins with no fresh price (F-3 then refuses new risk).
        self.unpriced_held_symbols: list[str] = []

        # Block 5D: the sole venue instrument-precision authority. This
        # manager consumes it but never constructs, mutates, or invents an
        # entry - the composition root loads it once from the checked-in
        # static config and injects it here. ``configured_symbols`` is the
        # trade-enabled symbol universe the composition root knows about; a
        # missing rule for any of them halts startup fail-closed rather than
        # being discovered on the first admitted request.
        self.instrument_rules = instrument_rules

        # Block 6A: how old those rules are allowed to be, and what happens
        # when they are older. Defaulted rather than left ``None`` so no
        # construction path is silently ungated; the composition root injects
        # the shared instance so its policy and clock are the ones in force.
        self.instrument_rule_freshness = (
            instrument_rule_freshness
            if instrument_rule_freshness is not None
            else VenueRuleFreshnessService()
        )

        self._configured_symbols: tuple[str, ...] = tuple(
            sorted(
                {
                    str(symbol).strip().upper()
                    for symbol in (configured_symbols or ())
                    if str(symbol).strip()
                }
            )
        )

        self.last_risk_decision: dict[str, Any] | None = None
        self._risk_admissions: dict[str, tuple[str, ...]] = {}

        # Request ids whose execution has passed the paper/live side-effect
        # boundary.  PaperTrader.open_trade()/close_trade() persist to their
        # own durable book, so once that boundary is crossed an interrupted
        # request has an outcome this manager cannot prove either way.
        self._execution_side_effect_ids: set[str] = set()

        # Set by start(): whether this run came online holding live authority.
        self._live_authorized_at_start = False

        self.mode = self._normalize_mode(
            mode
        )

        self.minimum_confidence = self._clamp(
            self._to_float(
                minimum_confidence
            ),
            minimum=0.0,
            maximum=100.0,
        )

        self.live_execution_enabled = bool(
            live_execution_enabled
        )

        self.running = False

        self._lock = threading.RLock()

        # (reason, stored_day, today) of the last rollover refusal written to
        # the audit log, so a refusal that persists across many requests is
        # recorded once rather than once per risk_check.
        self._last_audited_rollover_refusal: tuple[str, str, str] | None = None

        self.history: list[dict[str, Any]] = []
        self.rejections: list[dict[str, Any]] = []
        self.errors: list[dict[str, Any]] = []

        # =====================================================
        # EXECUTION IDEMPOTENCY
        # =====================================================
        #
        # pending_request_ids:
        #   Requests atomically claimed by an active execution.
        #
        # completed_request_results:
        #   Terminal results indexed by canonical request_id.
        #
        # FAILED / ERROR results are not retained so the same
        # request may be retried deliberately.
        self.pending_request_ids: set[str] = set()

        self.idempotency_store = (
            idempotency_store
            if idempotency_store is not None
            else ExecutionIdempotencyStore(
                file_path=idempotency_file,
            )
        )

        self.completed_request_results: dict[
            str,
            dict[str, Any],
        ] = {
            request_id: dict(
                result
            )
            for request_id, result
            in self.idempotency_store.completed_requests.items()
        }

        self.transaction_journal = (
            transaction_journal
            if transaction_journal is not None
            else ExecutionTransactionJournal(
                file_path=transaction_journal_file,
            )
        )

        self._financial_safety_service_injected = (
            financial_safety_service is not None
        )
        self.financial_safety_service = (
            financial_safety_service
            if financial_safety_service is not None
            else FinancialRuntimeSafetyService(
                transaction_journal=self.transaction_journal,
                idempotency_store=self.idempotency_store,
            )
        )

        self.audit_enabled = bool(
            audit_enabled
        )

        self.audit_store = (
            audit_store
            if audit_store is not None
            else AuditEventStore(
                file_path=audit_file,
            )
        )

        # =====================================================
        # OPERATIONAL RUNTIME STATE
        # =====================================================
        #
        # This state extends the existing execution architecture.
        # It does not replace idempotency, audit, risk, routing,
        # persistence, or execution behavior.
        #
        # HEALTHY:
        #   Normal execution admission is permitted.
        #
        # AUDIT_DEGRADED:
        #   At least one runtime audit write has failed.
        #
        # EXECUTION_HALTED:
        #   New execution admission has been stopped.
        #
        # RECOVERY_REQUIRED:
        #   Explicit operator recovery is required.
        self.audit_runtime_state = "HEALTHY"

        self.execution_halted = False

        self.recovery_required = False

        self.last_audit_failure: dict[
            str,
            Any,
        ] | None = None

        self.audit_incident_count = 0

        self.halt_reason: str | None = None

        self.stats: dict[str, int] = self._new_stats()

        self.stats[
            "persistent_records_loaded"
        ] = len(
            self.completed_request_results
        )

        logger.info(
            "Execution Manager v%s initialized mode=%s "
            "minimum_confidence=%.2f live_enabled=%s",
            self.VERSION,
            self.mode,
            self.minimum_confidence,
            self.live_execution_enabled,
        )

    # =========================================================
    # LIFECYCLE
    # =========================================================

    def _assess_financial_readiness(self):
        """Keep the default gate bound to the canonical specialized stores."""
        if not self._financial_safety_service_injected:
            self.financial_safety_service = FinancialRuntimeSafetyService(
                transaction_journal=self.transaction_journal,
                idempotency_store=self.idempotency_store,
            )
        return self.financial_safety_service.assess()

    def _durable_financial_ready(self) -> tuple[bool, str | None]:
        foundation = self.portfolio_foundation
        if foundation is None:
            # The durable portfolio cutover is opt-in at construction time.
            # Existing transaction-journal users retain their established
            # commit-outcome contract when no foundation is configured.
            return True, None
        if not foundation.ready:
            reason = foundation.diagnostics().get("reason")
            return False, str(reason or "FINANCIAL_STATE_RECOVERY_REQUIRED")
        return True, None

    def _instrument_rules_startup_check(self) -> tuple[bool, str | None]:
        """Verify venue instrument rules cover every symbol this run needs.

        Block 5D owner decisions 2 and 4. Two independent symbol sources are
        checked: the composition root's configured trade-enabled symbols
        (decision 2 - a symbol Atlas is set up to trade must have a verified
        rule before the first order attempt, not discovered as a runtime
        admission failure) and every symbol the durable book currently holds
        a position in (a held position is implicitly configured regardless of
        whether it is still in the trade-enabled list, and its alignment
        cannot even be checked without a rule for it).

        A configured or held symbol with no rule halts as
        ``INSTRUMENT_RULES_UNAVAILABLE``. A held position whose durable
        ``base_quantity`` is not an exact multiple of the rule's
        ``quantity_step`` halts as ``INSTRUMENT_RULES_POSITION_MISALIGNED``
        - never floored, rounded, or written off; only an operator can
        resolve it. Both are startup-only: this manager never mutates the
        durable book to fix either condition.
        """
        symbols = set(self._configured_symbols)

        foundation = self.portfolio_foundation
        foundation_usable = foundation is not None and foundation.ready
        if foundation_usable:
            positions = self._derived_position_exposures()
            symbols.update(position.symbol for position in positions)
        else:
            positions = ()

        if not symbols:
            return True, None

        if self.instrument_rules is None:
            return False, "INSTRUMENT_RULES_UNAVAILABLE"

        for symbol in sorted(symbols):
            if self.instrument_rules.get(symbol) is None:
                return False, "INSTRUMENT_RULES_UNAVAILABLE"

        for position in positions:
            rules = self.instrument_rules.get(position.symbol)
            if rules is not None and not is_aligned_to_step(
                position.base_quantity, rules.quantity_step
            ):
                return False, "INSTRUMENT_RULES_POSITION_MISALIGNED"

        # Block 6A: rules that exist for every needed symbol can still be too
        # old to trade on. A live-authorized runtime halts unless they are
        # FRESH; a bounded PAPER runtime continues on STALE rules only
        # because the policy explicitly permits it, and never silently -
        # ``venue_rules`` on health() and status() carries the state, and the
        # warning below names it at startup.
        decision = self.instrument_rule_freshness.evaluate_gate(
            self.instrument_rules,
            live_authorized=self.live_authorized,
        )

        if not decision.allowed:
            return False, decision.reason

        if not decision.report.is_fresh:
            logger.warning(
                "Venue instrument rules not fresh status=%s venue=%s "
                "age_seconds=%s maximum_age_seconds=%s observed_at=%s",
                decision.report.status.value,
                decision.report.venue,
                decision.report.age_seconds,
                decision.report.maximum_age_seconds,
                decision.report.observed_at,
            )

        # Block 6B (readiness gate V1): a runtime that can actually reach a
        # venue may not come online against rules that do not model the
        # venue's upper bounds. Unmodelled maxima are only tolerable while no
        # order can reach a venue at all, which is precisely what live
        # authority ends. Bounded PAPER is unaffected by design: it is the
        # existing, recorded policy that unmodelled maxima are safe there
        # because nothing leaves the paper book.
        if self.live_authorized:
            unbounded = [
                symbol
                for symbol in sorted(symbols)
                if not self.instrument_rules.get(symbol).has_complete_venue_bounds
            ]

            if unbounded:
                logger.error(
                    "Live authority refused: venue upper bounds unmodelled "
                    "symbols=%s",
                    unbounded,
                )
                return False, VENUE_UPPER_BOUNDS_UNAVAILABLE

        return True, None

    @property
    def live_authorized(self) -> bool:
        """True when this runtime could actually reach a venue.

        LIVE *mode* alone is not authority: with ``live_execution_enabled``
        false, ``live_execute`` denies every request before any adapter step,
        so no venue rule - fresh or stale - can be acted on. Authority is the
        conjunction, and it is what the venue-rule freshness gate keys on.
        """
        return self.mode == self.MODE_LIVE and bool(self.live_execution_enabled)

    def assess_venue_rule_freshness(self) -> VenueRuleFreshnessReport:
        """Evaluate the current venue-rule freshness state.

        Re-evaluated on each call against the injected clock rather than
        cached at startup: rules are immutable for the life of the process
        (Block 5D owner decision 9), but their *age* is not, so a long-running
        process must be able to observe them crossing the threshold.
        """
        return self.instrument_rule_freshness.assess(self.instrument_rules)

    def start(self) -> bool:
        """
        Bring the execution service online.
        """

        with self._lock:
            if self.running:
                logger.info(
                    "Execution Manager is already online"
                )
                return True

            self.running = True

            # Block 6A: the authority this run actually started with. A live
            # dispatch re-checks venue-rule freshness only for a runtime that
            # started live-authorized and therefore passed the fail-closed
            # startup gate below; see live_execute.
            self._live_authorized_at_start = self.live_authorized

            readiness = self._assess_financial_readiness()

            durable_ready = True
            durable_reason = None
            if self.portfolio_foundation is not None:
                durable_ready, durable_reason = self._durable_financial_ready()

            if readiness.ready and durable_ready:
                self._release_orphan_reservations()

            if durable_ready:
                self._reproject_paper_book()

            instrument_rules_ready = True
            instrument_rules_reason = None
            if readiness.ready and durable_ready:
                # Position alignment can only be checked once the durable
                # book itself is known ready; a not-ready foundation already
                # halts above with its own reason.
                instrument_rules_ready, instrument_rules_reason = (
                    self._instrument_rules_startup_check()
                )

            if not readiness.ready or not durable_ready or not instrument_rules_ready:
                self.execution_halted = True
                self.recovery_required = True
                self.halt_reason = (
                    readiness.decision.reason if not readiness.ready
                    else durable_reason if not durable_ready
                    else instrument_rules_reason
                )

        logger.info(
            "Execution Manager ONLINE"
        )

        self.publish(
            "EXECUTION_MANAGER_STARTED",
            self.status(),
        )

        return True

    def _release_orphan_reservations(self) -> None:
        """F-2: free RESERVED capital whose request never reached the journal.

        ``risk_check`` reserves capital before the durable PREPARE barrier in
        ``execute``. A process killed between the two leaves a RESERVED
        reservation with no journal entry at all, which is durable proof the
        request never crossed prepare - so no paper or live side effect can
        have followed it. Nothing else ever releases such a reservation, and
        admissible capital shrinks silently by its amount on every restart.

        Deliberately narrow, so a legitimate reservation can never be taken
        for an orphan:

        - only RESERVED - INDETERMINATE is an unresolved outcome and is never
          freed here;
        - only a request with zero journal activity - an entry in any state
          means prepare happened, and that reservation belongs to the entry's
          own resolution (or to operator recovery), not to this sweep;
        - never a request this process holds in flight (claimed, or holding a
          risk admission), which is exactly the window between reserve and
          prepare in a live execution;
        - only against a journal that actually loaded, so a missing entry is
          evidence rather than a read failure.

        A release that cannot be persisted halts the runtime through
        ``_release_capital_reservation``'s own fail-closed path.
        """
        orphans = self._orphan_reservation_ids()
        if orphans is None:
            return
        released = 0
        for request_id in orphans:
            if not self._release_capital_reservation(request_id):
                break
            released += 1

        if orphans:
            logger.warning(
                "Released %s orphan capital reservation(s) with no journal "
                "entry at startup (of %s found)",
                released,
                len(orphans),
            )

    def _orphan_reservation_ids(self) -> list[str] | None:
        """F-2's orphan detection: RESERVED capital with no journal activity.

        Returns the orphaned request ids, or ``None`` when the question cannot
        be answered from evidence (ledger or journal not loaded, reservations
        unreadable). ``None`` is never "no orphans": the startup sweep releases
        nothing on it, and the automatic risk-day rollover refuses on it.
        """
        ledger = self.reservation_ledger
        journal = self.transaction_journal
        if ledger is None or not ledger.ready or not callable(getattr(ledger, "reserved", None)):
            return None
        if not bool(getattr(journal, "loaded", False)) or bool(getattr(journal, "load_failed", True)):
            return None
        entries = getattr(journal, "entries", None)
        if not isinstance(entries, Mapping):
            return None

        with self._lock:
            in_flight = set(self.pending_request_ids) | set(self._risk_admissions)

        try:
            reserved = tuple(ledger.reserved())
        except Exception as exc:
            # Not being able to list reservations is not evidence of an
            # orphan; nothing is released.
            self._record_error(phase="orphan_reservation_sweep", error=exc)
            return None

        # Only canonical ids are ever swept: the journal strips request_id,
        # so a reservation under a non-canonical (whitespace-padded) id could
        # have journal activity under its stripped key that a raw lookup
        # would miss. Such a reservation is left for the operator.
        return [
            reservation.request_id
            for reservation in reserved
            if reservation.request_id == reservation.reservation_id
            and reservation.request_id == reservation.request_id.strip()
            and reservation.request_id not in entries
            and reservation.request_id not in in_flight
        ]

    # =========================================================
    # AUTOMATIC PAPER RISK-ACCOUNTING DAY ROLLOVER
    # =========================================================

    RISK_DAY_ROLLOVER_PREPARED = "RISK_ACCOUNTING_DAY_ROLLOVER_PREPARED"
    RISK_DAY_ROLLOVER_COMMITTED = "RISK_ACCOUNTING_DAY_ROLLOVER_COMMITTED"
    RISK_DAY_ROLLOVER_REFUSED = "RISK_ACCOUNTING_DAY_ROLLOVER_REFUSED"

    def _audit_risk_day_rollover_refusal(
        self, reason: str, *, stored_day: date, today: date,
    ) -> None:
        """Record why a due rollover did not happen, alongside the WARNING log.

        Observational only: it never raises and never changes the outcome -
        the stored day stays untouched either way. A refusal is written once
        per distinct (reason, stored day, today); the same refusal on every
        following request is not re-appended. Nothing is written when audit
        is disabled (the trail the reason names does not exist), and a failed
        write is handled as any other audit failure.
        """
        if not self.audit_enabled:
            return
        key = (reason, stored_day.isoformat(), today.isoformat())
        if key == getattr(self, "_last_audited_rollover_refusal", None):
            return
        try:
            self.audit_store.append(
                event_type=self.RISK_DAY_ROLLOVER_REFUSED,
                source=self.NAME,
                aggregate_type="risk_accounting_state",
                aggregate_id=today.isoformat(),
                payload={
                    "mode": self.mode,
                    "reason": reason,
                    "from_accounting_day_utc": stored_day.isoformat(),
                    "to_accounting_day_utc": today.isoformat(),
                },
                correlation_id=today.isoformat(),
                metadata={"mode": self.mode, "manager_version": self.VERSION},
            )
            self.stats["audit_events_written"] += 1
            self._last_audited_rollover_refusal = key
        except Exception as exc:
            self.stats["audit_write_failures"] += 1
            self._record_audit_failure(
                event_type=self.RISK_DAY_ROLLOVER_REFUSED,
                request=None,
                error=exc,
                stage="RISK_ACCOUNTING",
            )
            self._record_error(phase="risk_day_rollover_refusal_audit", error=exc)

    def _risk_day_rollover_refusal(self) -> str | None:
        """Why the durable state is not clean enough to roll the day over.

        The gate is exactly: the transaction journal loaded and holds no
        unresolved entry, and F-2's detection finds no orphaned RESERVED
        reservation. An open position is deliberately not a condition -
        holding overnight is normal. The equity source must also be able to
        answer, and the rollover must be auditable, or nothing is written.

        A runtime halted for any reason never rolls: ``execute`` already
        refuses on these flags before ``risk_check``, and this gate refuses
        on them too rather than relying on that ordering.
        """
        with self._lock:
            execution_halted = bool(self.execution_halted)
            recovery_required = bool(self.recovery_required)
        if execution_halted:
            return "EXECUTION_HALTED"
        if recovery_required:
            return "RECOVERY_REQUIRED"
        journal = self.transaction_journal
        if not bool(getattr(journal, "loaded", False)) or bool(getattr(journal, "load_failed", True)):
            return "JOURNAL_NOT_LOADED"
        if journal.has_unresolved():
            return "JOURNAL_UNRESOLVED"
        orphans = self._orphan_reservation_ids()
        if orphans is None:
            return "RESERVATION_STATE_UNVERIFIABLE"
        if orphans:
            return "ORPHAN_RESERVATION_PRESENT"
        foundation = self.portfolio_foundation
        if foundation is None or not foundation.ready:
            return "EQUITY_AUTHORITY_NOT_READY"
        if not self.audit_enabled:
            return "AUDIT_DISABLED"
        return None

    def _auto_rollover_risk_accounting_day(self) -> None:
        """Roll the durable risk-accounting day forward in PAPER mode only.

        Runs at the top of ``risk_check``, the single place a ``RiskState`` is
        derived for evaluation, so both a restart on a later UTC day and an
        uninterrupted run through UTC midnight are covered by the next request
        after the date changes. Anything short of a clean, audited rollover
        leaves the stored day untouched, and ``RiskEngine.evaluate`` then
        rejects with RISK_ACCOUNTING_DAY_RECONCILIATION_REQUIRED exactly as it
        did before this path existed. A refused or equity-aborted rollover is
        also recorded as a ``RISK_ACCOUNTING_DAY_ROLLOVER_REFUSED`` audit event
        (see ``_audit_risk_day_rollover_refusal``). A missing journal lock and
        an unreadable stored state are not: neither establishes that a
        rollover is due, and the latter fails closed in ``_derive_risk_state``.

        Idempotent: once the stored day is today, every further call is a
        no-op. The gate, the equity read and the durable write all happen
        under this manager's lock and the journal's lock, so no request can
        prepare between the gate check and the write.
        """
        if self.mode != self.MODE_PAPER:
            # LIVE, or any value that is not exactly PAPER: there is no
            # automatic path. The stale day stays fail-closed, as before.
            return

        store = self.risk_state_store
        if store is None or self.risk_engine is None or not callable(getattr(store, "rollover", None)):
            return

        # The journal's own lock is what keeps a concurrent prepare() out of
        # the window between the gate and the write. Without it there is no
        # atomicity to offer, so nothing is rolled.
        journal_lock = getattr(self.transaction_journal, "_lock", None)
        if not (callable(getattr(journal_lock, "acquire", None))
                and callable(getattr(journal_lock, "release", None))):
            logger.warning(
                "Automatic PAPER risk-accounting day rollover REFUSED "
                "reason=JOURNAL_LOCK_UNAVAILABLE; execution stays fail-closed"
            )
            return

        with self._lock, journal_lock:
            today = datetime.now(UTC).date()
            try:
                restored = store.load(
                    expected_policy_version=self.risk_engine.policy.version,
                    today_utc=today,
                )
            except Exception:
                # _derive_risk_state reloads and fails closed with its own
                # reason; this path never masks that failure.
                return

            if restored.accounting_day_utc >= today:
                return

            refusal = self._risk_day_rollover_refusal()
            if refusal is not None:
                logger.warning(
                    "Automatic PAPER risk-accounting day rollover REFUSED "
                    "reason=%s stored_day=%s today=%s; execution stays "
                    "fail-closed until the state is reconciled",
                    refusal,
                    restored.accounting_day_utc.isoformat(),
                    today.isoformat(),
                )
                self._audit_risk_day_rollover_refusal(
                    refusal, stored_day=restored.accounting_day_utc, today=today,
                )
                return

            # Set once the durable equity is known to be positive, so the
            # abort below can tell an equity refusal from an audit failure.
            equity_refusal: str | None = "EQUITY_UNREADABLE"
            try:
                equity = Decimal(str(self.portfolio_foundation.snapshot()["equity"]))
                if not equity.is_finite() or equity <= 0:
                    equity_refusal = (
                        "EQUITY_NOT_FINITE" if not equity.is_finite() else "EQUITY_NOT_POSITIVE"
                    )
                    raise ValueError("durable equity is not positive")
                equity_refusal = None
                payload = {
                    "mode": self.mode,
                    "from_accounting_day_utc": restored.accounting_day_utc.isoformat(),
                    "to_accounting_day_utc": today.isoformat(),
                    "previous_state": restored.to_dict(),
                    "current_equity_source": "ExecutionPortfolioFoundation",
                    "current_equity": str(equity),
                    "gate": {
                        "journal_unresolved": False,
                        "orphan_reservations": 0,
                    },
                }
                # Write-ahead: no audit record, no rollover.
                prepared = self.audit_store.append(
                    event_type=self.RISK_DAY_ROLLOVER_PREPARED,
                    source=self.NAME,
                    aggregate_type="risk_accounting_state",
                    aggregate_id=today.isoformat(),
                    payload=payload,
                    correlation_id=today.isoformat(),
                    metadata={"mode": self.mode, "manager_version": self.VERSION},
                )
                self.stats["audit_events_written"] += 1
            except Exception as exc:
                self._record_error(phase="risk_day_rollover", error=exc)
                logger.error(
                    "Automatic PAPER risk-accounting day rollover aborted "
                    "before any write stored_day=%s today=%s error=%s",
                    restored.accounting_day_utc.isoformat(),
                    today.isoformat(),
                    type(exc).__name__,
                )
                if equity_refusal is not None:
                    self._audit_risk_day_rollover_refusal(
                        equity_refusal, stored_day=restored.accounting_day_utc, today=today,
                    )
                return

            try:
                rolled = store.rollover(restored, today_utc=today, current_equity=equity)
            except Exception as exc:
                # save() replaces the file atomically; a failure leaves the
                # previous day on disk and the next request retries.
                self._record_error(phase="risk_day_rollover", error=exc)
                logger.error(
                    "Automatic PAPER risk-accounting day rollover write failed "
                    "stored_day=%s today=%s error=%s",
                    restored.accounting_day_utc.isoformat(),
                    today.isoformat(),
                    type(exc).__name__,
                )
                return

            logger.warning(
                "Automatic PAPER risk-accounting day rollover %s -> %s "
                "realized_daily_pnl %s -> %s peak_equity %s -> %s "
                "current_equity %s -> %s",
                restored.accounting_day_utc.isoformat(),
                rolled.accounting_day_utc.isoformat(),
                restored.realized_daily_pnl,
                rolled.realized_daily_pnl,
                restored.peak_equity,
                rolled.peak_equity,
                restored.current_equity,
                rolled.current_equity,
            )

            try:
                self.audit_store.append(
                    event_type=self.RISK_DAY_ROLLOVER_COMMITTED,
                    source=self.NAME,
                    aggregate_type="risk_accounting_state",
                    aggregate_id=today.isoformat(),
                    payload={"mode": self.mode, "new_state": rolled.to_dict()},
                    correlation_id=today.isoformat(),
                    causation_id=prepared.event_id,
                    metadata={"mode": self.mode, "manager_version": self.VERSION},
                )
                self.stats["audit_events_written"] += 1
            except Exception as exc:
                # The rollover is already durable and its PREPARED record
                # carries every input that determined it. The audit runtime
                # is marked degraded exactly as any other audit failure.
                self.stats["audit_write_failures"] += 1
                self._record_audit_failure(
                    event_type=self.RISK_DAY_ROLLOVER_COMMITTED,
                    request=None,
                    error=exc,
                    stage="RISK_ACCOUNTING",
                )
                self._record_error(phase="risk_day_rollover_audit", error=exc)
                logger.error(
                    "Automatic PAPER risk-accounting day rollover COMMITTED "
                    "audit record failed day=%s error=%s",
                    today.isoformat(),
                    type(exc).__name__,
                )

    def stop(self) -> bool:
        """
        Stop accepting new execution requests.
        """

        with self._lock:
            if not self.running:
                logger.info(
                    "Execution Manager is already offline"
                )
                return True

            self.running = False

        logger.info(
            "Execution Manager OFFLINE"
        )

        self.publish(
            "EXECUTION_MANAGER_STOPPED",
            self.status(),
        )

        return True

    # =========================================================
    # MAIN PIPELINE
    # =========================================================


    # =========================================================
    # SAFE INPUT FAILURE SUPPORT
    # =========================================================

    def _safe_decision_context(
        self,
        decision: Any,
    ) -> dict[str, Any]:
        """
        Extract failure-safe context from an untrusted decision.

        This helper must never raise. It is used before a valid
        ExecutionRequest exists.
        """

        try:
            if isinstance(
                decision,
                Mapping,
            ):
                data = dict(
                    decision
                )

            elif hasattr(
                decision,
                "__dict__",
            ):
                data = dict(
                    vars(
                        decision
                    )
                )

            else:
                data = {}

        except Exception:
            data = {}

        def safe_text(
            value: Any,
            default: str,
        ) -> str:
            try:
                normalized = str(
                    value
                ).strip()

                return (
                    normalized
                    if normalized
                    else default
                )

            except Exception:
                return default

        def safe_float(
            value: Any,
            default: float = 0.0,
        ) -> float:
            try:
                result = float(
                    value
                )

                if result != result:
                    return default

                return result

            except Exception:
                return default

        symbol = safe_text(
            data.get(
                "symbol",
                "UNKNOWN",
            ),
            "UNKNOWN",
        ).upper()

        action = safe_text(
            data.get(
                "action",
                data.get(
                    "decision",
                    "UNKNOWN",
                ),
            ),
            "UNKNOWN",
        ).upper()

        request_id = safe_text(
            data.get(
                "request_id",
                data.get(
                    "id",
                    "UNAVAILABLE",
                ),
            ),
            "UNAVAILABLE",
        )

        return {
            "request_id": request_id,
            "symbol": symbol,
            "action": action,
            "price": safe_float(
                data.get(
                    "price",
                    data.get(
                        "market_price",
                        0.0,
                    ),
                )
            ),
            "amount": safe_float(
                data.get(
                    "amount",
                    data.get(
                        "allocation",
                        0.0,
                    ),
                )
            ),
            "confidence": safe_float(
                data.get(
                    "confidence",
                    0.0,
                )
            ),
            "strategy": safe_text(
                data.get(
                    "strategy",
                    "UNKNOWN",
                ),
                "UNKNOWN",
            ),
            "risk": safe_text(
                data.get(
                    "risk",
                    data.get(
                        "risk_level",
                        "UNKNOWN",
                    ),
                ),
                "UNKNOWN",
            ).upper(),
        }

    def _build_input_failure_result(
        self,
        *,
        decision: Any,
        error: Exception,
        started_at: float,
    ) -> dict[str, Any]:
        """
        Build a failure result without requiring ExecutionRequest.

        This method intentionally returns a plain dictionary so
        malformed input cannot trigger ExecutionResult validation.
        """

        context = self._safe_decision_context(
            decision
        )

        return {
            "success": False,
            "status": "FAILED",
            "message": (
                "Execution request could not be built"
            ),
            "execution_id": None,
            "position_id": None,
            "request_id": context[
                "request_id"
            ],
            "symbol": context[
                "symbol"
            ],
            "action": context[
                "action"
            ],
            "requested_price": context[
                "price"
            ],
            "requested_amount": context[
                "amount"
            ],
            "filled_price": None,
            "filled_amount": None,
            "fee": 0.0,
            "pnl": 0.0,
            "mode": self.mode,
            "error_code": (
                "EXECUTION_REQUEST_BUILD_FAILED"
            ),
            "error_details": {
                "type": type(
                    error
                ).__name__,
                "error": str(
                    error
                ),
                "phase": "build_request",
            },
            "metadata": {
                "input_failure": True,
                "strategy": context[
                    "strategy"
                ],
                "confidence": context[
                    "confidence"
                ],
                "risk": context[
                    "risk"
                ],
            },
            "timestamp": self._utc_now(),
            "latency_ms": round(
                (
                    time.perf_counter()
                    - started_at
                )
                * 1000,
                3,
            ),
            "retryable": False,
        }

    def execute(
        self,
        decision: Any,
        market_state: Any | None = None,
    ) -> dict[str, Any]:
        """Run one decision; with order_lifecycle_observe on, also check it against the order state machine.

        Stage 1 of proposals/2026-10-01_order_lifecycle_enforcement_DESIGN.md:
        observe only. The result is returned unchanged; a violation is logged
        and kept in order_lifecycle_violations, never acted on.
        """
        result = self._execute_decision(decision, market_state)
        if self.order_lifecycle_observe and isinstance(result, dict):
            try:
                from core.order_lifecycle import observe_outcome

                order_id = str(result.get("request_id") or getattr(decision, "get", lambda *_: None)("request_id") or "?")
                with self._lock:  # audit F-D: mutate under the same lock status() reads with
                    for problem in observe_outcome(order_id, result):
                        self.order_lifecycle_violations.append({"request_id": order_id, "violation": problem})
                        logger.warning("Order lifecycle violation (observe only) request_id=%s %s", order_id, problem)
                    del self.order_lifecycle_violations[:-100]
            except Exception:
                logger.warning("Order lifecycle observer failed; execution unaffected", exc_info=True)
        return result

    def _execute_decision(
        self,
        decision: Any,
        market_state: Any | None = None,
    ) -> dict[str, Any]:
        """
        Validate and execute one Atlas decision.

        Lifecycle
        ---------
        1. Build execution request
        2. Write immutable REQUEST_RECEIVED audit event
        3. Atomically claim canonical request_id
        4. Detect pending or completed duplicates
        5. Validate request structure
        6. Apply institutional risk controls
        7. Route to paper or live execution
        8. Persist terminal idempotency result
        9. Write immutable terminal audit event
        10. Publish runtime event

        Idempotency
        -----------
        - NEW requests are atomically claimed.
        - PENDING requests are skipped.
        - COMPLETED requests return the cached result.
        - FAILED and ERROR results release their claim and
          remain retryable.

        Audit Policy
        ------------
        Audit writes are non-blocking. An audit storage failure
        increases audit_write_failures but does not interrupt
        execution.

        Structure (T-0013)
        ------------------
        Each phase is one ``_decision_*`` helper, called in the order
        above; a helper returns the terminal result that ends the run or
        ``_CONTINUE`` to continue (not ``None``: a None result must end the
        run exactly as the single body's ``return`` did, never fall through
        to execution). The state the phases share - the request,
        its id, whether it is claimed and the last audit event id - is
        carried by ``_DecisionRun`` so the ``except``/``finally`` below see
        exactly what the single original body saw.
        """

        started_at = time.perf_counter()

        blocked = self._decision_preflight()

        if not isinstance(blocked, _Continue):
            return blocked

        run = _DecisionRun(started_at=started_at)

        try:
            return self._decision_pipeline(
                run,
                decision,
                market_state,
            )

        except Exception as exc:
            return self._decision_pipeline_failure(
                run,
                exc,
            )

        finally:
            # Defensive release for exceptions or unexpected
            # early exits after a successful atomic claim.
            if run.request_id:
                self._consume_execution_side_effect(
                    run.request_id
                )

                if run.request_claimed:
                    self._release_request(
                        run.request_id
                    )

    def _decision_pipeline(
        self,
        run: _DecisionRun,
        decision: Any,
        market_state: Any | None,
    ) -> dict[str, Any]:
        """Run the phases of one admitted decision in order; any exception reaches the caller's handler."""

        terminal = self._decision_build(
            run,
            decision,
        )

        if not isinstance(terminal, _Continue):
            return terminal

        terminal = self._decision_receive_and_claim(
            run,
        )

        if not isinstance(terminal, _Continue):
            return terminal

        terminal = self._decision_validate(
            run,
        )

        if not isinstance(terminal, _Continue):
            return terminal

        terminal = self._decision_risk_gate(
            run,
            market_state,
        )

        if not isinstance(terminal, _Continue):
            return terminal

        terminal = self._decision_prepare(
            run,
        )

        if not isinstance(terminal, _Continue):
            return terminal

        result, status = self._decision_route(
            run,
        )

        # =================================================
        # RETRYABLE FAILURE / NOT COMMITTED
        # =================================================
        #
        # Terminal classification is a SUCCESS allow-list, not a
        # failure allow-list. Only a status this manager itself
        # recognises as a completed execution may continue into
        # durable finalization; every other terminal status resolves
        # through the unsuccessful-execution path.
        #
        # The previous `status in FAILURE_STATUSES` test admitted
        # everything outside {FAILED, ERROR} into the durable-commit
        # branch. The statuses that actually reach this point are
        # PAPER_EXECUTED and FAILED (paper_execute), REJECTED (the
        # canonical-admission guard inside paper_execute and
        # live_execute), and LIVE_DISABLED / LIVE_NOT_IMPLEMENTED
        # (live_execute). So a correctly denied LIVE request - one
        # that provably performed no side effect at all - was
        # finalized as a confirmed execution: it failed inside
        # _finalize_durable_financial_state and left the runtime
        # halted with an unresolved journal entry, INDETERMINATE
        # capital, and an audit record asserting that an execution
        # "was confirmed" which had never occurred.
        #
        # Inverting the test is also what makes an unrecognised
        # terminal status fail closed. ExecutionResult.status
        # defaults to "UNKNOWN", and any status added in future is
        # treated as not-committed until it is deliberately declared
        # a success here, rather than being silently durable.
        #
        # This changes only how a status is classified, never how a
        # side effect is judged: _resolve_unsuccessful_execution
        # still decides deterministic rollback versus genuine
        # uncertainty from the recorded side-effect marker alone, so
        # a post-side-effect failure remains INDETERMINATE exactly
        # as before.

        if status not in self.SUCCESS_STATUSES:
            terminal = self._decision_unsuccessful(
                run,
                result,
                status,
            )

        else:
            terminal = self._decision_commit(
                run,
                result,
                status,
            )

        if not isinstance(terminal, _Continue):
            return terminal

        self.publish(
            "EXECUTION_COMPLETED",
            result,
        )

        return result

    def _decision_preflight(
        self,
    ) -> dict[str, Any] | _Continue:
        """Count the decision; refuse it while offline, halted or financially not ready."""

        with self._lock:
            self.stats[
                "received"
            ] += 1

            running = self.running

        if not running:
            return self.reject(
                reason="EXECUTION_MANAGER_OFFLINE",
            )

        with self._lock:
            execution_halted = self.execution_halted
            recovery_required = self.recovery_required
            halt_reason = (
                self.halt_reason
                or "UNRESOLVED_TRANSACTION"
            )

        readiness = self._assess_financial_readiness()
        durable_ready, durable_reason = self._durable_financial_ready()

        if (
            execution_halted
            or recovery_required
            or not readiness.ready
            or not durable_ready
        ):
            effective_halt_reason = (
                halt_reason
                if execution_halted or recovery_required
                else (
                    readiness.decision.reason if not readiness.ready else durable_reason
                )
            )
            with self._lock:
                self.execution_halted = True
                self.recovery_required = True
                self.halt_reason = effective_halt_reason

            return {
                "success": False,
                "status": "RECOVERY_REQUIRED",
                "commit_outcome": (
                    CommitOutcome
                    .COMMIT_STATUS_UNKNOWN
                    .value
                ),
                "error_code": effective_halt_reason,
                "message": (
                    "Execution is blocked until unresolved "
                    "transactions are reconciled"
                ),
                "mode": self.mode,
                "timestamp": self._utc_now(),
            }

        return _CONTINUE

    def _decision_build(
        self,
        run: _DecisionRun,
        decision: Any,
    ) -> dict[str, Any] | _Continue:
        """Build the canonical request; a build failure or an empty request id ends the run."""

        # =================================================
        # BUILD REQUEST
        # =================================================

        try:
            run.request = self.build_request(
                decision
            )

        except Exception as build_exc:
            self._record_error(
                phase="build_request",
                error=build_exc,
                request=None,
            )

            with self._lock:
                self.stats[
                    "failed"
                ] += 1

            logger.exception(
                "Execution request build failed"
            )

            failure = (
                self._build_input_failure_result(
                    decision=decision,
                    error=build_exc,
                    started_at=run.started_at,
                )
            )

            with self._lock:
                self._append_bounded(
                    self.history,
                    failure,
                    self.MAX_HISTORY,
                )

            self.publish(
                "EXECUTION_FAILED",
                failure,
            )

            return failure

        run.request_id = str(
            cast(ExecutionRequest, run.request).request_id
        ).strip()

        if not run.request_id:
            return self.reject(
                reason="INVALID_REQUEST_ID",
                request=run.request,
            )

        return _CONTINUE

    def _decision_receive_and_claim(
        self,
        run: _DecisionRun,
    ) -> dict[str, Any] | _Continue:
        """Audit the received request and claim its id; a duplicate ends the run."""

        request = cast(ExecutionRequest, run.request)

        # =================================================
        # REQUEST RECEIVED AUDIT
        # =================================================

        run.last_audit_event_id = (
            self._write_audit_event(
                event_type=(
                    "EXECUTION_REQUEST_RECEIVED"
                ),
                request=request,
                payload={
                    "symbol": request.symbol,
                    "action": request.action,
                    "price": request.price,
                    "amount": request.amount,
                    "confidence": (
                        request.confidence
                    ),
                    "strategy": request.strategy,
                    "risk": request.risk,
                    "request_mode": request.mode,
                    "order_type": (
                        request.order_type
                    ),
                    "source": request.source,
                },
            )
        )

        # =================================================
        # ATOMIC IDEMPOTENCY CLAIM
        # =================================================

        duplicate_result = self._claim_request(
            request
        )

        if duplicate_result is not None:
            duplicate_reason = str(
                duplicate_result.get(
                    "duplicate_reason",
                    duplicate_result.get(
                        "reason",
                        "DUPLICATE_REQUEST",
                    ),
                )
            ).strip().upper()

            if (
                duplicate_reason
                == "DUPLICATE_REQUEST_PENDING"
            ):
                audit_type = (
                    "DUPLICATE_REQUEST_PENDING"
                )

            elif (
                duplicate_reason
                == "DUPLICATE_REQUEST_COMPLETED"
            ):
                audit_type = (
                    "DUPLICATE_REQUEST_COMPLETED"
                )

            else:
                audit_type = (
                    "DUPLICATE_REQUEST_DETECTED"
                )

            self._write_audit_event(
                event_type=audit_type,
                request=request,
                payload={
                    "status": (
                        duplicate_result.get(
                            "status"
                        )
                    ),
                    "reason": duplicate_reason,
                    "cache_hit": bool(
                        duplicate_result.get(
                            "idempotency",
                            {},
                        ).get(
                            "cache_hit",
                            False,
                        )
                    ),
                    "duplicate": True,
                },
                causation_id=(
                    run.last_audit_event_id
                ),
            )

            return duplicate_result

        run.request_claimed = True

        return _CONTINUE

    def _decision_validate(
        self,
        run: _DecisionRun,
    ) -> dict[str, Any] | _Continue:
        """Validate the request structure; a rejection is persisted, audited and ends the run."""

        request = cast(ExecutionRequest, run.request)
        request_id = cast(str, run.request_id)

        # =================================================
        # REQUEST VALIDATION
        # =================================================

        validation = self.validate_request(
            request
        )

        if not validation[
            "approved"
        ]:
            result = self.reject(
                reason=validation[
                    "reason"
                ],
                request=request,
                details=validation.get(
                    "details"
                ),
            )

            self._complete_request(
                request_id=request_id,
                result=result,
            )

            run.request_claimed = False

            self._write_audit_event(
                event_type=(
                    "EXECUTION_REQUEST_REJECTED"
                ),
                request=request,
                payload={
                    "stage": (
                        "REQUEST_VALIDATION"
                    ),
                    "status": result.get(
                        "status"
                    ),
                    "reason": validation.get(
                        "reason"
                    ),
                    "details": validation.get(
                        "details"
                    ),
                },
                causation_id=(
                    run.last_audit_event_id
                ),
            )

            return result

        with self._lock:
            self.stats[
                "validated"
            ] += 1

        run.last_audit_event_id = (
            self._write_audit_event(
                event_type=(
                    "EXECUTION_REQUEST_VALIDATED"
                ),
                request=request,
                payload={
                    "approved": True,
                    "symbol": request.symbol,
                    "action": request.action,
                    "confidence": (
                        request.confidence
                    ),
                    "minimum_confidence": (
                        self.minimum_confidence
                    ),
                },
                causation_id=(
                    run.last_audit_event_id
                ),
            )
            or run.last_audit_event_id
        )

        return _CONTINUE

    def _decision_risk_gate(
        self,
        run: _DecisionRun,
        market_state: Any | None,
    ) -> dict[str, Any] | _Continue:
        """Apply the institutional risk controls and require a canonical admission."""

        request = cast(ExecutionRequest, run.request)
        request_id = cast(str, run.request_id)

        # =================================================
        # RISK VALIDATION
        # =================================================

        risk_validation = self.risk_check(
            request=request,
            market_state=market_state,
        )

        if not risk_validation[
            "approved"
        ]:
            result = self.reject(
                reason=risk_validation[
                    "reason"
                ],
                request=request,
                details=risk_validation.get(
                    "details"
                ),
            )

            self._complete_request(
                request_id=request_id,
                result=result,
            )

            run.request_claimed = False

            self._write_audit_event(
                event_type="RISK_REJECTED",
                request=request,
                payload={
                    "approved": False,
                    "status": result.get(
                        "status"
                    ),
                    "reason": (
                        risk_validation.get(
                            "reason"
                        )
                    ),
                    "details": (
                        risk_validation.get(
                            "details"
                        )
                    ),
                },
                causation_id=(
                    run.last_audit_event_id
                ),
            )

            return result

        if not self._has_risk_admission(request):
            return self.reject(reason="CANONICAL_RISK_ADMISSION_MISSING", request=request)

        risk_approved_event_id = self._write_audit_event(
            event_type="RISK_APPROVED",
            request=request,
            payload={
                "approved": True,
                "risk": request.risk,
                "confidence": (
                    request.confidence
                ),
                "details": (
                    risk_validation.get(
                        "details"
                    )
                ),
            },
            causation_id=(
                run.last_audit_event_id
            ),
        )

        self._close_experiment_if_unrecorded(
            risk_approved_event_id,
            risk_validation.get("details"),
        )

        run.last_audit_event_id = (
            risk_approved_event_id
            or run.last_audit_event_id
        )

        return _CONTINUE

    def _decision_prepare(
        self,
        run: _DecisionRun,
    ) -> dict[str, Any] | _Continue:
        """Durable transaction prepare barrier; nothing is executed unless it holds."""

        request = cast(ExecutionRequest, run.request)
        request_id = cast(str, run.request_id)

        # =================================================
        # DURABLE TRANSACTION PREPARE BARRIER
        # =================================================

        try:
            prepared = self.transaction_journal.prepare(
                request_id,
                request.to_dict(),
            )

        except Exception as prepare_exc:
            prepared = False

            self._record_error(
                phase="transaction_prepare",
                error=prepare_exc,
                request=request,
            )

        if not prepared:
            self._release_capital_reservation(request_id)
            self._release_request(
                request_id
            )

            run.request_claimed = False

            not_committed = {
                "success": False,
                "status": (
                    CommitOutcome
                    .NOT_COMMITTED
                    .value
                ),
                "commit_outcome": (
                    CommitOutcome
                    .NOT_COMMITTED
                    .value
                ),
                "error_code": (
                    "TRANSACTION_PREPARE_FAILED"
                ),
                "message": (
                    "Durable transaction prepare failed"
                ),
                "request_id": request_id,
                "symbol": request.symbol,
                "action": request.action,
                "mode": self.mode,
                "timestamp": self._utc_now(),
            }

            self._record_result(
                not_committed
            )

            self.publish(
                "EXECUTION_NOT_COMMITTED",
                not_committed,
            )

            return not_committed

        return _CONTINUE

    def _decision_route(
        self,
        run: _DecisionRun,
    ) -> tuple[dict[str, Any], str]:
        """Route to paper or live execution and classify the returned status."""

        request = cast(ExecutionRequest, run.request)
        request_id = cast(str, run.request_id)
        started_at = run.started_at

        # =================================================
        # EXECUTION ROUTING
        # =================================================

        if self.mode == self.MODE_PAPER:
            result = self.paper_execute(
                request
            )

        else:
            result = self.live_execute(
                request
            )

        result.setdefault(
            "request_id",
            request_id,
        )

        result.setdefault(
            "latency_ms",
            round(
                (
                    time.perf_counter()
                    - started_at
                )
                * 1000,
                3,
            ),
        )

        status = str(
            result.get(
                "status",
                "UNKNOWN",
            )
        ).strip().upper()

        return result, status

    def _decision_unsuccessful(
        self,
        run: _DecisionRun,
        result: dict[str, Any],
        status: str,
    ) -> dict[str, Any] | _Continue:
        """Resolve a non-success result; ends the run only when a side effect may have happened."""

        request = cast(ExecutionRequest, run.request)
        request_id = cast(str, run.request_id)

        # An unsuccessful result is classified by the same
        # side-effect boundary as a raised exception. A paper
        # mutation that already persisted is not undone by the
        # execution then reporting FAILED.
        side_effect_possible = (
            self._resolve_unsuccessful_execution(
                request_id=request_id,
                reason=status,
                result=result,
            )
        )

        self._release_request(
            request_id
        )

        run.request_claimed = False

        if side_effect_possible:
            # The original business failure is preserved in
            # error_code, message, and original_status; only the
            # commit classification changes, because this runtime
            # can no longer claim nothing happened.
            result[
                "original_status"
            ] = status

            result[
                "success"
            ] = False

            result[
                "status"
            ] = (
                CommitOutcome
                .COMMIT_STATUS_UNKNOWN
                .value
            )

            result[
                "commit_outcome"
            ] = (
                CommitOutcome
                .COMMIT_STATUS_UNKNOWN
                .value
            )

            result[
                "recovery_required"
            ] = True

            with self._lock:
                self.stats[
                    "failed"
                ] += 1

            self._record_result(
                result
            )

            self._write_audit_event(
                event_type=(
                    "EXECUTION_COMMIT_STATUS_UNKNOWN"
                ),
                request=request,
                payload={
                    "success": False,
                    "status": result.get(
                        "status"
                    ),
                    "original_status": status,
                    "message": result.get(
                        "message"
                    ),
                    "error_code": result.get(
                        "error_code"
                    ),
                    "latency_ms": result.get(
                        "latency_ms"
                    ),
                    "retryable": False,
                    "commit_outcome": (
                        result.get(
                            "commit_outcome"
                        )
                    ),
                },
                causation_id=(
                    run.last_audit_event_id
                ),
            )

            self.publish(
                "EXECUTION_COMMIT_STATUS_UNKNOWN",
                result,
            )

            return result

        result[
            "commit_outcome"
        ] = (
            CommitOutcome
            .NOT_COMMITTED
            .value
        )

        self._record_result(
            result
        )

        self._write_audit_event(
            event_type="EXECUTION_FAILED",
            request=request,
            payload={
                "success": bool(
                    result.get(
                        "success",
                        False,
                    )
                ),
                "status": status,
                "message": result.get(
                    "message"
                ),
                "error_code": result.get(
                    "error_code"
                ),
                "latency_ms": result.get(
                    "latency_ms"
                ),
                "retryable": True,
                "commit_outcome": (
                    result.get(
                        "commit_outcome"
                    )
                ),
            },
            causation_id=(
                run.last_audit_event_id
            ),
        )

        return _CONTINUE

    def _decision_commit(
        self,
        run: _DecisionRun,
        result: dict[str, Any],
        status: str,
    ) -> dict[str, Any] | _Continue:
        """Make a successful execution durable; any failure halts with COMMIT_STATUS_UNKNOWN."""

        # =================================================
        # TERMINAL DURABLE COMMIT
        # =================================================

        finalized, terminal = self._decision_finalize(
            run,
            result,
        )

        if not isinstance(terminal, _Continue):
            return terminal

        terminal = self._decision_commit_reservation(
            run,
            result,
        )

        if not isinstance(terminal, _Continue):
            return terminal

        terminal = self._decision_persist_terminal(
            run,
            result,
            finalized,
        )

        if not isinstance(terminal, _Continue):
            return terminal

        terminal = self._decision_journal_commit(
            run,
            result,
        )

        if not isinstance(terminal, _Continue):
            return terminal

        request = cast(ExecutionRequest, run.request)

        self._record_result(
            result
        )

        self._write_audit_event(
            event_type=(
                "EXECUTION_COMPLETED"
            ),
            request=request,
            payload={
                "success": bool(
                    result.get(
                        "success",
                        False,
                    )
                ),
                "status": status,
                "execution_id": (
                    result.get(
                        "execution_id"
                    )
                ),
                "filled_price": (
                    result.get(
                        "filled_price"
                    )
                ),
                "filled_amount": (
                    result.get(
                        "filled_amount"
                    )
                ),
                "fee": result.get(
                    "fee"
                ),
                "fee_amount": result.get(
                    "fee_amount"
                ),
                "fee_currency": result.get(
                    "fee_currency"
                ),
                "pnl": result.get(
                    "pnl"
                ),
                "latency_ms": (
                    result.get(
                        "latency_ms"
                    )
                ),
                "terminal": True,
                "commit_outcome": (
                    result.get(
                        "commit_outcome"
                    )
                ),
            },
            causation_id=(
                run.last_audit_event_id
            ),
        )

        return _CONTINUE

    def _decision_finalize(
        self,
        run: _DecisionRun,
        result: dict[str, Any],
    ) -> tuple[Any, dict[str, Any] | _Continue]:
        """Apply the confirmed execution to the durable financial authority (the side-effect boundary)."""

        request = cast(ExecutionRequest, run.request)
        request_id = cast(str, run.request_id)

        finalized = None

        try:
            if self.portfolio_foundation is not None:
                # Side-effect boundary. apply_confirmed() mutates the
                # durable financial authority, so from here an
                # interrupted request has an outcome this manager
                # cannot prove. Nothing earlier in the paper flow
                # mutates anything any more: the paper paths are
                # purely computational, and PaperTrader is projected
                # from this authority only after the commit lands.
                self._mark_execution_side_effect(request_id)

                finalized = self._finalize_durable_financial_state(
                    request=request,
                    result=result,
                )
        except Exception as finalization_exc:
            self._record_error(
                phase="durable_financial_finalization",
                error=finalization_exc,
                request=request,
            )
            self._mark_capital_indeterminate(request_id)
            try:
                self.transaction_journal.mark_unknown(
                    request_id,
                    reason="DURABLE_FINANCIAL_FINALIZATION_FAILED",
                    result=result,
                )
            except Exception:
                logger.exception("Unable to mark failed financial finalization unknown")
            with self._lock:
                self.execution_halted = True
                self.recovery_required = True
                self.halt_reason = "DURABLE_FINANCIAL_FINALIZATION_FAILED"
            # Same claim discipline as the unsuccessful-result branch
            # above: an interrupted execution must not leave its
            # request_id claimed in flight, which would outlive the
            # halt and answer EXECUTION_REQUESTS_IN_FLIGHT forever.
            self._release_request(request_id)
            run.request_claimed = False
            unknown_result = {
                "success": False,
                "status": CommitOutcome.COMMIT_STATUS_UNKNOWN.value,
                "commit_outcome": CommitOutcome.COMMIT_STATUS_UNKNOWN.value,
                "recovery_required": True,
                "error_code": "DURABLE_FINANCIAL_FINALIZATION_FAILED",
                "message": "Execution was confirmed but durable position/portfolio finalization failed",
                "request_id": request_id,
                "symbol": request.symbol,
                "action": request.action,
                "mode": self.mode,
                "timestamp": self._utc_now(),
            }
            self._record_result(unknown_result)
            self.publish("EXECUTION_COMMIT_STATUS_UNKNOWN", unknown_result)
            return finalized, unknown_result

        return finalized, _CONTINUE

    def _decision_commit_reservation(
        self,
        run: _DecisionRun,
        result: dict[str, Any],
    ) -> dict[str, Any] | _Continue:
        """Commit the capital reservation at the exact settled amount."""

        request = cast(ExecutionRequest, run.request)
        request_id = cast(str, run.request_id)

        # Block 5E: commit the reservation at the exact settled
        # amount - notional + quote fee - rather than the full
        # reservation, so the deterministic sub-quantum remainder a
        # BUY never spent stops being permanently encumbered by this
        # reservation. `None` when either figure is absent (e.g. a
        # non-paper/live result), which preserves the historical
        # full-amount commit for that case. The addition is pinned
        # to the same explicit context as the rest of the 5E
        # settlement slice (final-review MEDIUM #2), so a caller
        # thread's ambient precision can never round this sum
        # differently than `_finalize_durable_financial_state`
        # already rounded the identical `notional + fee` figure it
        # checked against the approval moments earlier - a
        # divergence here would either under-commit or spuriously
        # halt on `settled_amount exceeds reserved amount`.
        settled_amount = None
        notional_raw = result.get("filled_quote_notional")
        settled_fee_raw = result.get("fee_amount")
        if notional_raw is not None and settled_fee_raw is not None:
            try:
                with localcontext() as context:
                    context.prec = SETTLEMENT_CONTEXT_PRECISION
                    context.rounding = ROUND_HALF_EVEN
                    settled_amount = Decimal(str(notional_raw)) + Decimal(str(settled_fee_raw))
            except (InvalidOperation, ValueError, TypeError):
                settled_amount = None

        if not self._commit_capital_reservation(request_id, settled_amount):
            try:
                self.transaction_journal.mark_unknown(
                    request_id,
                    reason="CAPITAL_RESERVATION_COMMIT_FAILED",
                    result=result,
                )
            except Exception:
                logger.exception("Unable to mark reservation commit failure unknown")
            with self._lock:
                self.execution_halted = True
                self.recovery_required = True
                self.halt_reason = "CAPITAL_RESERVATION_COMMIT_FAILED"
            # F-5: the same claim discipline dac9b72 gave the
            # finalization-failure branch above. Clearing only the
            # local flag left request_id in pending_request_ids, so
            # the claim outlived the halt and reset() refused with
            # EXECUTION_REQUESTS_IN_FLIGHT until restart.
            self._release_request(request_id)
            run.request_claimed = False
            unknown_result = {
                "success": False,
                "status": CommitOutcome.COMMIT_STATUS_UNKNOWN.value,
                "commit_outcome": CommitOutcome.COMMIT_STATUS_UNKNOWN.value,
                "recovery_required": True,
                "error_code": "CAPITAL_RESERVATION_COMMIT_FAILED",
                "message": "Execution finalized but reservation commit could not be confirmed",
                "request_id": request_id,
                "symbol": request.symbol,
                "action": request.action,
                "mode": self.mode,
                "timestamp": self._utc_now(),
            }
            self._record_result(unknown_result)
            self.publish("EXECUTION_COMMIT_STATUS_UNKNOWN", unknown_result)
            return unknown_result

        return _CONTINUE

    def _decision_persist_terminal(
        self,
        run: _DecisionRun,
        result: dict[str, Any],
        finalized: Any,
    ) -> dict[str, Any] | _Continue:
        """Project the paper book, mark the result COMMITTED and persist it as the terminal idempotency record."""

        request = cast(ExecutionRequest, run.request)
        request_id = cast(str, run.request_id)

        # The durable authority is committed and the reservation is
        # settled; only now is the passive book projected from it.
        # This can neither fail nor alter the execution.
        self._mirror_paper_book(
            request=request,
            result=result,
            finalized=finalized,
        )

        result[
            "commit_outcome"
        ] = (
            CommitOutcome
            .COMMITTED
            .value
        )

        persisted = self._complete_request(
            request_id=request_id,
            result=result,
        )

        run.request_claimed = False

        if not persisted:
            self._mark_capital_indeterminate(request_id)
            try:
                self.transaction_journal.mark_unknown(
                    request_id,
                    reason="DURABLE_COMMIT_FAILED",
                    result=result,
                )

            except Exception:
                logger.exception(
                    "Unable to persist unknown "
                    "transaction outcome"
                )

            with self._lock:
                self.execution_halted = True
                self.recovery_required = True
                self.halt_reason = (
                    "UNRESOLVED_TRANSACTION"
                )

            unknown_result = {
                "success": False,
                "status": (
                    CommitOutcome
                    .COMMIT_STATUS_UNKNOWN
                    .value
                ),
                "commit_outcome": (
                    CommitOutcome
                    .COMMIT_STATUS_UNKNOWN
                    .value
                ),
                "recovery_required": True,
                "error_code": (
                    "DURABLE_COMMIT_FAILED"
                ),
                "message": (
                    "Financial side effect completed but "
                    "durable terminal persistence failed"
                ),
                "request_id": request_id,
                "symbol": request.symbol,
                "action": request.action,
                "mode": self.mode,
                "timestamp": self._utc_now(),
                "original_result": result,
            }

            self._record_result(
                unknown_result
            )

            self.publish(
                "EXECUTION_COMMIT_STATUS_UNKNOWN",
                unknown_result,
            )

            return unknown_result

        return _CONTINUE

    def _decision_journal_commit(
        self,
        run: _DecisionRun,
        result: dict[str, Any],
    ) -> dict[str, Any] | _Continue:
        """Mark the durable transaction committed in the journal."""

        request = cast(ExecutionRequest, run.request)
        request_id = cast(str, run.request_id)

        try:
            journal_committed = (
                self.transaction_journal.mark_committed(
                    request_id,
                    result,
                )
            )

        except Exception:
            journal_committed = False

            logger.exception(
                "Transaction journal commit failed"
            )

        if not journal_committed:
            self._mark_capital_indeterminate(request_id)
            try:
                self.transaction_journal.mark_unknown(
                    request_id,
                    reason=(
                        "TRANSACTION_JOURNAL_COMMIT_FAILED"
                    ),
                    result=result,
                )

            except Exception:
                logger.exception(
                    "Unable to mark transaction unknown"
                )

            with self._lock:
                self.execution_halted = True
                self.recovery_required = True
                self.halt_reason = (
                    "UNRESOLVED_TRANSACTION"
                )

            unknown_result = {
                "success": False,
                "status": (
                    CommitOutcome
                    .COMMIT_STATUS_UNKNOWN
                    .value
                ),
                "commit_outcome": (
                    CommitOutcome
                    .COMMIT_STATUS_UNKNOWN
                    .value
                ),
                "recovery_required": True,
                "error_code": (
                    "TRANSACTION_JOURNAL_COMMIT_FAILED"
                ),
                "message": (
                    "Terminal result persisted but journal "
                    "commit could not be confirmed"
                ),
                "request_id": request_id,
                "symbol": request.symbol,
                "action": request.action,
                "mode": self.mode,
                "timestamp": self._utc_now(),
            }

            self._record_result(
                unknown_result
            )

            self.publish(
                "EXECUTION_COMMIT_STATUS_UNKNOWN",
                unknown_result,
            )

            return unknown_result

        return _CONTINUE

    def _decision_pipeline_failure(
        self,
        run: _DecisionRun,
        exc: Exception,
    ) -> dict[str, Any]:
        """Handle an exception raised anywhere in the pipeline (called from the except clause)."""

        request = run.request
        request_id = run.request_id
        started_at = run.started_at

        self._record_error(
            phase="execute",
            error=exc,
            request=request,
        )

        with self._lock:
            self.stats[
                "failed"
            ] += 1

        logger.exception(
            "Execution pipeline failed"
        )

        # An exception after risk admission must not leave capital
        # reserved, an admission stale, and the runtime running.
        side_effect_possible = (
            self._resolve_unsuccessful_execution(
                request_id=request_id,
                reason="EXECUTION_PIPELINE_EXCEPTION",
            )
            if request_id
            else False
        )

        if side_effect_possible:
            failure = self._failure_result(
                request=request,
                status=(
                    CommitOutcome
                    .COMMIT_STATUS_UNKNOWN
                    .value
                ),
                message=(
                    "Execution was interrupted after a paper "
                    "execution side effect"
                ),
                error_code=(
                    "EXECUTION_PIPELINE_EXCEPTION"
                ),
                error=exc,
            )

            failure[
                "commit_outcome"
            ] = (
                CommitOutcome
                .COMMIT_STATUS_UNKNOWN
                .value
            )

            failure[
                "recovery_required"
            ] = True

        else:
            failure = self._failure_result(
                request=request,
                status="FAILED",
                message=(
                    "Execution pipeline failed"
                ),
                error_code=(
                    "EXECUTION_PIPELINE_EXCEPTION"
                ),
                error=exc,
            )

            failure[
                "commit_outcome"
            ] = (
                CommitOutcome
                .NOT_COMMITTED
                .value
            )

        if request_id:
            failure.setdefault(
                "request_id",
                request_id,
            )

        failure[
            "latency_ms"
        ] = round(
            (
                time.perf_counter()
                - started_at
            )
            * 1000,
            3,
        )

        with self._lock:
            self._append_bounded(
                self.history,
                failure,
                self.MAX_HISTORY,
            )

        if request is not None:
            self._write_audit_event(
                event_type=(
                    "EXECUTION_COMMIT_STATUS_UNKNOWN"
                    if side_effect_possible
                    else "EXECUTION_FAILED"
                ),
                request=request,
                payload={
                    "success": False,
                    "status": failure.get(
                        "status"
                    ),
                    "message": failure.get(
                        "message"
                    ),
                    "error_code": (
                        "EXECUTION_PIPELINE_EXCEPTION"
                    ),
                    "error": str(
                        exc
                    ),
                    "error_type": type(
                        exc
                    ).__name__,
                    "latency_ms": failure.get(
                        "latency_ms"
                    ),
                    "retryable": (
                        not side_effect_possible
                    ),
                    "commit_outcome": failure.get(
                        "commit_outcome"
                    ),
                },
                causation_id=(
                    run.last_audit_event_id
                ),
            )

        self.publish(
            (
                "EXECUTION_COMMIT_STATUS_UNKNOWN"
                if side_effect_possible
                else "EXECUTION_FAILED"
            ),
            failure,
        )

        return failure

    def build_request(
        self,
        decision: Any,
    ) -> ExecutionRequest:
        """
        Convert a supported decision representation to ExecutionRequest.
        """

        if isinstance(
            decision,
            ExecutionRequest,
        ):
            return decision

        data = self._decision_to_dict(
            decision
        )

        metadata = self._normalize_metadata(
            data.get(
                "metadata",
                {},
            )
        )

        request_mode = self._normalize_mode(
            data.get(
                "mode",
                self.mode,
            )
        )

        request = ExecutionRequest(
            symbol=self._normalize_symbol(
                data.get(
                    "symbol",
                    "UNKNOWN",
                )
            ),
            action=self._normalize_action(
                data.get(
                    "action",
                    data.get(
                        "decision",
                        "HOLD",
                    ),
                )
            ),
            price=self._to_float(
                data.get(
                    "price",
                    data.get(
                        "market_price",
                        0.0,
                    ),
                )
            ),
            amount=self._to_float(
                data.get(
                    "amount",
                    data.get(
                        "allocation",
                        0.0,
                    ),
                )
            ),
            strategy=str(
                data.get(
                    "strategy",
                    "Atlas",
                )
            ),
            confidence=self._normalize_confidence(
                data.get(
                    "confidence",
                    0.0,
                )
            ),
            risk=self._normalize_risk_level(
                data.get(
                    "risk",
                    data.get(
                        "risk_level",
                        "MEDIUM",
                    ),
                )
            ),
            metadata=metadata,
            mode=request_mode,
            request_id=str(
                data.get(
                    "request_id",
                    data.get(
                        "id",
                        uuid.uuid4(),
                    ),
                )
            ),
            timestamp=data.get(
                "timestamp",
                data.get(
                    "created_at",
                    self._utc_now(),
                ),
            ),
            source=str(
                data.get(
                    "source",
                    "Atlas",
                )
            ),
            order_type=str(
                data.get(
                    "order_type",
                    "MARKET",
                )
            ).strip().upper(),
            stop_loss=self._optional_float(
                data.get(
                    "stop_loss"
                )
            ),
            take_profit=self._optional_float(
                data.get(
                    "take_profit"
                )
            ),
            trailing_stop=self._optional_float(
                data.get(
                    "trailing_stop"
                )
            ),
            time_in_force=str(
                data.get(
                    "time_in_force",
                    "GTC",
                )
            ).strip().upper(),
            reduce_only=bool(
                data.get(
                    "reduce_only",
                    False,
                )
            ),
            # Preserved exactly as the caller supplied it (Block 5C B1): this
            # is the pre-admission sizing proposal, read straight from the
            # decision dict rather than through ``_to_float``, so a Decimal
            # proposal reaches ``ExecutionRequest`` losslessly.
            proposed_quote_allocation=data.get(
                "proposed_quote_allocation"
            ),
        )

        return request

    # =========================================================
    # REQUEST VALIDATION
    # =========================================================

    def validate_request(
        self,
        request: ExecutionRequest,
    ) -> dict[str, Any]:
        """
        Validate the canonical request before risk checks.
        """

        validation_method = getattr(
            request,
            "validate",
            None,
        )

        if callable(
            validation_method
        ):
            try:
                validation_method()

            except Exception as exc:
                return {
                    "approved": False,
                    "reason": "REQUEST_CONTRACT_INVALID",
                    "details": {
                        "error": str(
                            exc
                        ),
                    },
                }

        if (
            not request.symbol
            or request.symbol == "UNKNOWN"
        ):
            return {
                "approved": False,
                "reason": "INVALID_SYMBOL",
                "details": {
                    "symbol": request.symbol,
                },
            }

        if request.action in self.NON_EXECUTION_ACTIONS:
            return {
                "approved": False,
                "reason": "NON_EXECUTION_ACTION",
                "details": {
                    "action": request.action,
                },
            }

        if request.action not in self.VALID_ACTIONS:
            return {
                "approved": False,
                "reason": "INVALID_ACTION",
                "details": {
                    "action": request.action,
                    "valid_actions": sorted(
                        self.VALID_ACTIONS
                    ),
                },
            }

        if request.price <= 0:
            return {
                "approved": False,
                "reason": "INVALID_PRICE",
                "details": {
                    "price": request.price,
                },
            }

        if request.confidence < self.minimum_confidence:
            return {
                "approved": False,
                "reason": "LOW_CONFIDENCE",
                "details": {
                    "confidence": request.confidence,
                    "minimum_confidence": (
                        self.minimum_confidence
                    ),
                },
            }

        if (
            request.stop_loss is not None
            and request.stop_loss <= 0
        ):
            return {
                "approved": False,
                "reason": "INVALID_STOP_LOSS",
                "details": {
                    "stop_loss": request.stop_loss,
                },
            }

        if (
            request.take_profit is not None
            and request.take_profit <= 0
        ):
            return {
                "approved": False,
                "reason": "INVALID_TAKE_PROFIT",
                "details": {
                    "take_profit": request.take_profit,
                },
            }

        if (
            request.trailing_stop is not None
            and request.trailing_stop < 0
        ):
            return {
                "approved": False,
                "reason": "INVALID_TRAILING_STOP",
                "details": {
                    "trailing_stop": request.trailing_stop,
                },
            }

        return {
            "approved": True,
            "reason": "APPROVED",
            "details": {
                "confidence": request.confidence,
                "minimum_confidence": (
                    self.minimum_confidence
                ),
            },
        }

    # =========================================================
    # AUTHORITATIVE RISK STATE DERIVATION
    # =========================================================

    def _derived_position_exposures(self) -> tuple[PositionExposure, ...]:
        """Project the durable LONG book onto the canonical exposure contract.

        Each position is valued at the ``mark_price`` the foundation already
        holds, which is the same basis its own ``snapshot()`` reports. No new
        market-price authority is introduced here: a mark that has not been
        refreshed is carried exactly as the durable book states it, so the
        derived exposure is never fresher than the accounting it comes from.

        That mark is the single exposure basis for the whole admission-to-exit
        path. Risk admission measures a position here,
        ``_requested_quote_allocation`` resolves an unsized exit against the
        same number, and ``_resolve_reduction_quantity`` converts an approved
        reduction back into base units at the same number. Because every step
        shares one basis, a complete exit is requested as exactly the exposure
        it is compared against and can never be refused for a disagreement
        between cost basis and current execution price. The execution price
        prices the proceeds; it never decides how much is sold, and it is
        never consulted here.
        """
        positions = self.portfolio_foundation.snapshot()["positions"]

        exposures = []
        for symbol, position in sorted(positions.items()):
            base = Decimal(str(position["base_quantity"]))
            mark = Decimal(str(position["mark_price"]))
            exposures.append(
                PositionExposure(symbol, base, mark, base * mark,
                                 risk_bucket=self._recorded_risk_bucket(position.get("position_id")))
            )

        return tuple(exposures)

    def _recorded_risk_bucket(self, position_id: Any) -> str | None:
        store = self.position_risk_buckets
        if store is None:
            return None
        try:
            return store.lookup(position_id)
        except Exception:
            logger.warning("Position risk bucket unreadable; treated as UNKNOWN", exc_info=True)
            return None

    def _derive_risk_state(
        self,
        market_state: Any | None = None,
    ) -> RiskState:
        """Assemble the canonical ``RiskState`` from authoritative state.

        Contract
        --------
        Position state and committed exposure come from
        ``ExecutionPortfolioFoundation``, the durable owner of LONG position
        accounting. Realized daily P&L, peak/current equity, the UTC
        accounting day and the policy version come from the durable risk
        accounting record behind ``risk_state_store``. Nothing is inferred or
        defaulted: every field is read from one of those two authorities, and
        an authority that cannot answer raises so ``risk_check`` refuses the
        request instead of evaluating risk against a fabricated portfolio.

        ``CapitalReservationLedger`` is deliberately not consulted. There is
        no reserved-capital field on ``RiskState``; ``RiskEngine`` derives
        reserved and allocatable capital from ``RiskPolicy`` itself. The
        ledger's readiness remains a precondition ``risk_check`` enforces
        before this runs, so it still gates admission without contributing a
        value that cannot be proven from the state it owns.

        Compatibility
        -------------
        When no portfolio foundation is configured - the documented opt-out
        described in ``_durable_financial_ready`` - the caller-supplied
        ``RiskState`` remains the position authority exactly as before. A
        foundation that *is* configured but is not ready never falls back to
        caller-supplied positions: an unrecoverable book fails closed.
        """
        if self.risk_engine is None:
            raise RuntimeError("CANONICAL_RISK_SERVICE_REQUIRED")

        if self.risk_state_store is None:
            raise RuntimeError("RISK_ACCOUNTING_STATE_STORE_REQUIRED")

        foundation = self.portfolio_foundation

        if foundation is not None:
            if not foundation.ready:
                raise RuntimeError(
                    "DURABLE_FINANCIAL_FOUNDATION_NOT_READY"
                )

            positions = self._derived_position_exposures()

        else:
            supplied = (
                market_state
                if isinstance(market_state, RiskState)
                else (
                    market_state.get("risk_state")
                    if isinstance(market_state, Mapping)
                    else None
                )
            )

            if not isinstance(supplied, RiskState) or not supplied.state_ready:
                raise ValueError(
                    "authoritative position exposure state is required"
                )

            positions = supplied.positions

        restored = self.risk_state_store.load(
            expected_policy_version=self.risk_engine.policy.version,
            today_utc=datetime.now(UTC).date(),
        )

        return RiskState(
            positions=positions,
            committed_quote=sum(
                (position.quote_exposure for position in positions),
                Decimal("0"),
            ),
            realized_daily_pnl=restored.realized_daily_pnl,
            peak_equity=restored.peak_equity,
            current_equity=restored.current_equity,
            state_ready=True,
            accounting_day_utc=restored.accounting_day_utc.isoformat(),
            policy_version=restored.policy_version,
            unrealized_pnl=self._mark_to_market(positions),
        )

    # Audit finding F-4 (owner 2026-09-30): PAPER fills at the candle close are
    # idealised. With a positive value the fill moves against Atlas by this many
    # basis points (BUY higher, SELL lower), rounded to the venue price tick in
    # the adverse direction. 0 keeps the historical fill byte-identical.
    PAPER_SLIPPAGE_BPS = Decimal("0")

    def _paper_fill_price(self, request: Any) -> Any:
        bps = Decimal(str(getattr(self, "paper_slippage_bps", self.PAPER_SLIPPAGE_BPS)))
        if not bps.is_finite() or bps < 0 or bps >= 10000:  # audit A-3: never fail open
            raise ValueError("PAPER_SLIPPAGE_BPS must be finite and in [0, 10000)")
        if bps == 0:
            return request.price
        price = Decimal(str(request.price))
        buy = str(request.action).upper().endswith("BUY")
        raw = price * (1 + bps / Decimal("10000")) if buy else price * (1 - bps / Decimal("10000"))
        rules = self.instrument_rules.get(request.symbol) if self.instrument_rules is not None else None
        tick = Decimal(str(getattr(rules, "price_tick", "0") or "0"))
        if tick > 0:
            from decimal import ROUND_CEILING, ROUND_FLOOR
            raw = (raw / tick).to_integral_value(rounding=ROUND_CEILING if buy else ROUND_FLOOR) * tick
        if raw <= 0:
            raise ValueError("slipped fill price is not positive")
        return float(raw)

    def _shadow_book_fill_price(self, request: Any) -> float | None:
        """Live order book VWAP for this order (S2), rounded to the tick against Atlas; None = reject.

        BUY notional is the risk-approved quote allocation; SELL notional is the base
        quantity being sold (a partial reduction: approved / mark, capped at the holding)
        at the request price. An unknown notional is never guessed.
        """
        side = "BUY" if str(request.action).upper().endswith("BUY") else "SELL"
        try:
            if side == "BUY":
                notional = request.approved_quote_allocation
            else:
                foundation = getattr(self, "portfolio_foundation", None)
                held = ((foundation.snapshot().get("positions") or {}).get(request.symbol) or {}) if foundation else {}
                quantity = held.get("base_quantity")
                if quantity is not None:
                    quantity = Decimal(str(quantity))
                    # Audit 2026-10-02 (MEDIUM): a partial reduction sells about approved / mark
                    # base units (_resolve_reduction_quantity), not the whole holding.
                    approved, mark = request.approved_quote_allocation, held.get("mark_price")
                    if approved is not None and mark is not None and Decimal(str(mark)) > 0:
                        quantity = min(quantity, Decimal(str(approved)) / Decimal(str(mark)))
                notional = None if quantity is None else quantity * Decimal(str(request.price))
            if notional is None or not Decimal(str(notional)).is_finite() or Decimal(str(notional)) <= 0:
                return None
            price = self.paper_fill_provider(request.symbol, side, Decimal(str(notional)))
        except Exception:
            logger.exception("Shadow book fill price failed; the order is rejected")
            return None
        if not isinstance(price, Decimal) or not price.is_finite() or price <= 0:
            return None
        rules = self.instrument_rules.get(request.symbol) if self.instrument_rules is not None else None
        tick = Decimal(str(getattr(rules, "price_tick", "0") or "0"))
        if tick > 0:
            from decimal import ROUND_CEILING, ROUND_FLOOR
            price = (price / tick).to_integral_value(rounding=ROUND_CEILING if side == "BUY" else ROUND_FLOOR) * tick
        return float(price) if price > 0 else None

    def _mark_to_market(self, positions: Any) -> Decimal | None:
        """Unrealized P&L of open positions (audit F-3), or None when not fully known.

        Computed only when the risk policy counts it; any position without a
        fresh mark price makes the whole figure unknown (never zero-filled),
        which the engine turns into UNREALIZED_PNL_UNKNOWN for new risk.
        """
        if not getattr(self.risk_engine.policy, "count_unrealized_in_daily_loss", False):
            return None
        provider = getattr(self, "mark_price_provider", None)
        if provider is None:
            return None
        try:
            prices = provider() or {}
            self.unpriced_held_symbols = []
            foundation = getattr(self, "portfolio_foundation", None)
            book = (foundation.snapshot().get("positions") or {}) if foundation is not None else {}
            total = Decimal("0")
            for p in positions:
                price = prices.get(p.symbol)
                if price is None:
                    # Audit F-B: name the coin, so readiness can say why new buys stop.
                    self.unpriced_held_symbols = sorted({q.symbol for q in positions if prices.get(q.symbol) is None})
                    return None
                value = Decimal(str(price)) * p.base_quantity
                held = book.get(p.symbol)
                if held is not None:
                    # Audit F-C: measured against what the position really cost (cost
                    # basis + entry fees) and net of the fee a close would pay, so
                    # the figure can only be more conservative than before.
                    cost = Decimal(str(held["cost_quote"])) + Decimal(str(held.get("entry_fees") or "0"))
                    total += value - cost - value * Decimal(str(getattr(self, "paper_fee_rate", 0)))
                else:
                    total += value - p.quote_exposure
            return total if total.is_finite() else None
        except Exception:
            logger.warning("mark-to-market unavailable; unrealized P&L unknown", exc_info=True)
            return None

    @staticmethod
    def _derive_reduce_only(
        request: ExecutionRequest,
        state: RiskState,
    ) -> bool:
        """Derive risk-reduction intent from authoritative held-position state.

        Atlas is LONG-only, so exposure can only fall by selling a symbol that
        is actually held. A SELL against a held position is therefore handed to
        ``RiskEngine`` as reduce-only, and the engine keeps sole authority over
        whether the requested size is a *valid* reduction: an over-sized one
        still fails closed as ``INVALID_RISK_REDUCTION``. A SELL against a
        symbol that is not held is not a reduction at all: a sized one is
        refused by the engine as ``NON_RISK_REDUCING_SELL``, an unsized one by
        ``risk_check`` as ``NO_POSITION_TO_SELL``.

        A BUY can never reduce exposure, so it derives False unconditionally.
        That also stops a caller-supplied flag from waiving the capital
        reservation the BUY path requires.

        The derived value is authoritative. A contradicting caller flag is
        logged and then discarded, because held-position state - not caller
        intent - decides whether exposure is being reduced.
        """
        if str(request.action).strip().upper() != "SELL":
            return False

        symbol = str(request.symbol).strip().upper()

        return any(
            position.symbol == symbol
            for position in state.positions
        )

    # =========================================================
    # REQUESTED ALLOCATION (PRE-RISK)
    # =========================================================

    def _durable_free_quote_capital(
        self,
        *,
        exclude: str | None = None,
    ) -> Decimal | None:
        """Quote capital the durable book could actually spend right now.

        Cash comes from ``ExecutionPortfolioFoundation``, the owner of the
        durable ledger; capital already spoken for by in-flight admissions
        comes from ``CapitalReservationLedger``.  The foundation's own
        ``reserved_capital`` field is deliberately not used: it is synchronized
        during finalization, so mid-flight it lags the ledger.

        ``exclude`` names the one reservation this measurement is being taken
        *for*, and is the reservation id of the request being admitted. A
        re-evaluated request already holds its own RESERVED entry from its
        first admission, and counting that entry would charge the request for
        its own approval: near the durable bound the second verdict flips to
        INSUFFICIENT_DURABLE_CAPITAL purely because the request was approved
        once already. Every other reservation still encumbers capital, so this
        cannot fund two requests out of the same cash, and the ledger's own
        ``available`` check - which excludes nothing - remains the bound on
        what may actually be reserved.

        Returns ``None`` when no durable book is configured - the documented
        opt-out - so the caller can fall back to policy limits alone rather
        than treating an absent book as zero capital.
        """
        if self.portfolio_foundation is None or self.reservation_ledger is None:
            return None

        cash = Decimal(str(self.portfolio_foundation.snapshot()["cash"]))

        return cash - self.reservation_ledger.active_reserved_capital(
            exclude=exclude
        )

    @staticmethod
    def _is_unsized_sell_of_unheld_symbol(request: ExecutionRequest) -> bool:
        """A SELL that names no size, for a symbol ``_derive_reduce_only``
        found not held. A malformed ``amount`` (non-numeric, NaN, negative) is
        deliberately not "unsized", so its pre-existing refusal is unchanged."""

        if str(request.action).strip().upper() != "SELL" or request.reduce_only:
            return False

        if request.proposed_quote_allocation is not None:
            return False

        try:
            amount = Decimal(str(request.amount))
        except (InvalidOperation, TypeError, ValueError):
            return False

        return amount.is_finite() and amount == 0

    def _requested_quote_allocation(
        self,
        request: ExecutionRequest,
        state: RiskState,
    ) -> Decimal | None:
        """Read the allocation a request is asking for, before RiskEngine runs.

        This resolves an intent; it does not size one. Nothing here consults a
        policy ceiling, a confidence score, a CapitalManager or a constant,
        and nothing here can raise a caller's number.

        Exact sizing proposal (Block 5C B1)
            A request carrying an exact ``proposed_quote_allocation`` -
            written only by ``PositionSizingService`` - is asking for exactly
            that Decimal, and takes priority over the ``amount`` compatibility
            mirror below. This is what keeps an authoritative proposal from
            ever crossing the lossy ``amount`` float boundary on its way to
            ``RiskEngine``.

        Explicit allocation
            A request carrying a positive ``amount`` and no exact proposal is
            asking for exactly that, and gets exactly that. It is still
            subject to every admission verdict - a request above the policy
            ceiling is refused by ``RiskEngine`` as
            ``REQUEST_EXCEEDS_RISK_LIMIT``, not silently trimmed to fit.

        Unsized reduction
            A SELL against a held position that names no amount means "exit
            this position". That is the position's own size, not a sizing
            decision, so it resolves to the full held quote exposure on the
            same durable basis ``_derived_position_exposures`` reports - which
            is what lets a complete exit be approved as exactly the exposure
            it is compared against, and lets it settle on the exact held base
            quantity rather than a re-derived approximation of it.

        Unsized BUY
            Returns ``None``. New risk with no stated size is not a request
            this runtime can price, and inheriting the policy ceiling would
            turn a risk *bound* into a sizing *policy* - the largest trade
            policy allows, on every unsized decision, forever. The caller
            refuses it as ``UNSIZED_REQUEST_REJECTED``.

        Unsized non-reducing SELL
            Resolves to zero. ``risk_check`` refuses a genuinely unsized one
            (no proposal, ``amount`` exactly zero) as ``NO_POSITION_TO_SELL``
            before the engine runs (registry v5.04). A non-positive or
            malformed ``amount`` is not "unsized", so its pre-existing
            refusal is unchanged (``INVALID_FINANCIAL_INPUT`` for a negative
            or infinite amount, ``RISK_STATE_RESTORATION_FAILED`` for a
            non-numeric one).

        The result is exact ``Decimal`` and deterministic for identical
        durable state.
        """
        if request.proposed_quote_allocation is not None:
            return request.proposed_quote_allocation

        existing = Decimal(str(request.amount))
        if existing > 0:
            return existing

        symbol = str(request.symbol).strip().upper()

        if request.reduce_only:
            return sum(
                (
                    position.quote_exposure
                    for position in state.positions
                    if position.symbol == symbol
                ),
                Decimal("0"),
            )

        if str(request.action).strip().upper() == "BUY":
            return None

        return Decimal("0")

    # =========================================================
    # RISK VALIDATION
    # =========================================================

    def risk_check(
        self,
        request: ExecutionRequest,
        market_state: Any | None = None,
    ) -> dict[str, Any]:
        """Admit or refuse a request, and fix the amount it may commit.

        Admission and capital reservation happen here, in that order, and only
        here. The request's own allocation is resolved, ``RiskEngine`` returns
        the canonical verdict, the remaining reject-capable gates run, and
        capital is reserved last so that no refusal can leave a reservation or
        an admission behind.

        On approval the engine's exact ``Decimal`` verdict is written to
        ``request.approved_quote_allocation`` and sealed into the admission
        token. That field - not ``amount`` - is what every authoritative
        consumer downstream reads, which is what makes it the only amount
        execution can commit. CapitalManager takes no part in any of this.
        """

        # Any approval this request may be carrying from an earlier evaluation
        # is void the moment it is re-evaluated. Clearing first means a
        # refusal below can never leave a stale approval that a later stage
        # would read as live authority.
        request.approved_quote_allocation = None

        # Phase-3 canonical admission is evaluated before compatibility risk
        # adapters.  Its state must have been restored by the accounting owner;
        # missing state is intentionally recovery-blocking rather than inferred.
        if self.risk_engine is None:
            return {"approved": False, "reason": "CANONICAL_RISK_SERVICE_REQUIRED",
                    "status": "BLOCK_RECOVERY_REQUIRED"}
        if self.reservation_ledger is None or not self.reservation_ledger.ready:
            return {"approved": False, "reason": "CAPITAL_RESERVATION_STATE_NOT_READY",
                    "status": "BLOCK_RECOVERY_REQUIRED"}
        if self.risk_state_store is None:
            return {"approved": False, "reason": "RISK_ACCOUNTING_STATE_STORE_REQUIRED",
                    "status": "BLOCK_RECOVERY_REQUIRED"}
        try:
            # PAPER only, gated; a stale day that cannot be rolled cleanly is
            # left exactly as stored and rejected by RiskEngine below.
            self._auto_rollover_risk_accounting_day()
        except Exception as exc:
            self._record_error(phase="risk_day_rollover", error=exc, request=request)
        if self.risk_engine is not None:
            try:
                risk_state = self._derive_risk_state(market_state)

                # Risk-reduction intent is decided by the position state the
                # engine is about to evaluate against, never by the caller.
                supplied_reduce_only = bool(request.reduce_only)
                request.reduce_only = self._derive_reduce_only(
                    request,
                    risk_state,
                )

                if request.reduce_only != supplied_reduce_only:
                    logger.warning(
                        "Reduce-only intent re-derived from authoritative "
                        "position state symbol=%s action=%s supplied=%s "
                        "derived=%s",
                        request.symbol,
                        request.action,
                        supplied_reduce_only,
                        request.reduce_only,
                    )

                requested = self._requested_quote_allocation(request, risk_state)
            except Exception as exc:
                self._record_error(phase="canonical_risk", error=exc, request=request)
                return {"approved": False, "reason": "RISK_STATE_RESTORATION_FAILED",
                        "status": "BLOCK_RECOVERY_REQUIRED"}

            if requested is None:
                # New risk that names no size. This manager does not size
                # requests, and the policy ceiling is a bound rather than a
                # size, so there is nothing to evaluate. Refused before the
                # engine, before any reservation, and distinctly from a
                # request that named a size the book cannot fund.
                logger.warning(
                    "Unsized new-risk request refused symbol=%s action=%s "
                    "request_id=%s",
                    request.symbol,
                    request.action,
                    request.request_id,
                )
                return {
                    "approved": False,
                    "reason": "UNSIZED_REQUEST_REJECTED",
                    "details": {
                        "symbol": request.symbol,
                        "action": request.action,
                    },
                }

            if self._is_unsized_sell_of_unheld_symbol(request):
                # Registry v5.04: nothing is held, so there is nothing to sell.
                # Refused before the engine and before any reservation, with its
                # own reason, so it is no longer indistinguishable from
                # genuinely malformed financial input.
                logger.info(
                    "Unsized SELL of an unheld symbol refused symbol=%s "
                    "request_id=%s",
                    request.symbol,
                    request.request_id,
                )
                return {
                    "approved": False,
                    "reason": "NO_POSITION_TO_SELL",
                    "status": "REJECT",
                    "details": {
                        "symbol": request.symbol,
                        "action": request.action,
                    },
                }

            try:
                # `request.amount` is deliberately left exactly as the caller
                # set it. Writing the resolved Decimal back through `float()`
                # would make this method non-idempotent: a re-evaluated unsized
                # exit would then read its own rounded mirror as an explicit
                # allocation instead of re-resolving the durable exposure, and
                # a mirror that rounded up turns a legitimate full exit into
                # INVALID_RISK_REDUCTION - trapping the exposure it was meant
                # to release. The canonical Decimal is published on
                # `approved_quote_allocation`; the mirror stays caller input.
                canonical = self.risk_engine.evaluate(
                    RiskRequest(
                        symbol=request.symbol,
                        action=request.action,
                        confidence=Decimal(str(request.confidence)) / Decimal("100"),
                        requested_quote_allocation=requested,
                        execution_price=Decimal(str(request.price)),
                        risk_bucket=request.risk,
                        reduce_only=request.reduce_only,
                    ),
                    risk_state,
                )
                self.last_risk_decision = canonical.to_dict()
            except Exception as exc:
                self._record_error(phase="canonical_risk", error=exc, request=request)
                return {"approved": False, "reason": "RISK_STATE_RESTORATION_FAILED",
                        "status": "BLOCK_RECOVERY_REQUIRED"}
            if not canonical.approved:
                return {
                    "approved": False,
                    "reason": canonical.reason_code,
                    "status": canonical.status.value,
                    "details": self.last_risk_decision,
                }
            # The pure evaluator never silently reduces an approved request.
            # Keep this explicit assertion at the execution seam, and compare
            # the two Decimals directly - routing either side through the float
            # mirror would be the very round-trip this field exists to avoid.
            if canonical.approved_allocation != requested:
                return {"approved": False, "reason": "RISK_ALLOCATION_MISMATCH"}

        # Block 5D owner decisions 2/3/7: venue instrument precision is a
        # fail-closed admission gate for every action, not only BUY. A
        # symbol with no checked-in rule can never be admitted - there is no
        # fallback quantum - and a request price that does not land exactly
        # on the venue's price tick is refused outright rather than rounded
        # to the nearest valid one. Both run before any reservation and
        # before the BUY-only quantity checks below, and neither this
        # manager nor any caller ever writes a rounded price back.
        instrument_rules = (
            self.instrument_rules.get(request.symbol)
            if self.instrument_rules is not None
            else None
        )

        if instrument_rules is None:
            return {
                "approved": False,
                "reason": "INSTRUMENT_RULES_UNAVAILABLE",
                "details": {"symbol": request.symbol},
            }

        request_price = Decimal(str(request.price))

        if not is_aligned_to_step(request_price, instrument_rules.price_tick):
            return {
                "approved": False,
                "reason": "PRICE_TICK_MISALIGNED",
                "details": {
                    "symbol": request.symbol,
                    "price": format(request_price, "f"),
                    "price_tick": format(instrument_rules.price_tick, "f"),
                },
            }

        # Every reject-capable compatibility gate must run before capital is
        # reserved and admission is recorded, so a rejection here never
        # leaves a reservation or admission behind (Block-2 M-1).
        if request.action == "BUY":
            allowed = self._can_open_position(
                request.symbol
            )

            if not allowed:
                return {
                    "approved": False,
                    "reason": "POSITION_LIMIT",
                    "details": {
                        "symbol": request.symbol,
                    },
                }

        # CapitalManager is not consulted here. It holds no admission
        # authority over a canonical RiskDecision: it cannot veto one, cannot
        # resize one, and cannot reinterpret one. The reject-capable gates
        # that remain are the canonical engine itself, the position-limit
        # check above, and the executable-quantum and durable-capital checks
        # below - all of which run before any capital is reserved.

        if request.action == "BUY" and not request.reduce_only:
            # An approval that cannot fund one whole venue quantity_step, or
            # that floors to less than the venue's min_quantity/min_notional,
            # can never produce a valid fill, so it is refused here rather
            # than discovered after the paper book has already been mutated.
            # `_resolve_base_fill` is the same pure derivation the
            # post-component defense-in-depth check in `_execute_paper_buy`
            # uses, so the two can never drift apart on how a fill is sized -
            # only on the fee, which is not yet known at admission and is
            # taken as zero here (Block 5D owner decision: reuse the same
            # fill/step derivation for both).
            #
            # Reaching this condition past admission turns an unexecutable
            # request into EXECUTION_INTERRUPTED_AFTER_SIDE_EFFECT -
            # INDETERMINATE capital, an unresolved journal entry, a paper
            # position the durable book never receives, and a halted runtime
            # awaiting operator recovery. Refusing at admission leaves none
            # of that behind.
            #
            # This sizes nothing. It is a pure feasibility bound on the
            # amount the caller already asked for and the engine already
            # approved: no allocation is raised, lowered, or manufactured
            # (Block 5D owner decision: never raise allocation to satisfy a
            # minimum), and a request below the bound is refused rather than
            # rounded up to it.
            # Registry v5.23: the paper fee the fill will charge is known here
            # (a pure function of the allocation), so the bound uses it - a
            # fee must never push a fill below a venue minimum after the
            # side-effect boundary, which would halt the runtime.
            admission_fill = self._resolve_base_fill(
                allocation=canonical.approved_allocation,
                price=request_price,
                fee=self._paper_buy_fee(canonical.approved_allocation),
                quantity_step=instrument_rules.quantity_step,
            )

            if admission_fill is None:
                logger.warning(
                    "Approved allocation cannot fund one whole "
                    "quantity_step symbol=%s request_id=%s approved=%s "
                    "price=%s quantity_step=%s",
                    request.symbol,
                    request.request_id,
                    format(canonical.approved_allocation, "f"),
                    format(request_price, "f"),
                    format(instrument_rules.quantity_step, "f"),
                )
                return {
                    "approved": False,
                    "reason": "QUANTITY_BELOW_VENUE_MINIMUM",
                    "details": {
                        "approved_allocation": format(
                            canonical.approved_allocation, "f"
                        ),
                        "execution_price": format(request_price, "f"),
                        "quantity_step": format(
                            instrument_rules.quantity_step, "f"
                        ),
                    },
                }

            admission_base_quantity, admission_quote_notional = admission_fill

            if admission_base_quantity < instrument_rules.min_quantity:
                return {
                    "approved": False,
                    "reason": "QUANTITY_BELOW_VENUE_MINIMUM",
                    "details": {
                        "floored_base_quantity": format(
                            admission_base_quantity, "f"
                        ),
                        "min_quantity": format(
                            instrument_rules.min_quantity, "f"
                        ),
                    },
                }

            if admission_quote_notional < instrument_rules.min_notional:
                # Terminal for this request/cycle only (Block 5D owner
                # decision 6): this admission is refused outright, but it
                # halts nothing - a future independent request (a new
                # request_id, e.g. the next market-loop tick with an updated
                # price or allocation) is evaluated fresh against the same
                # rule.
                return {
                    "approved": False,
                    "reason": "NOTIONAL_BELOW_VENUE_MINIMUM",
                    "details": {
                        "floored_quote_notional": format(
                            admission_quote_notional, "f"
                        ),
                        "min_notional": format(
                            instrument_rules.min_notional, "f"
                        ),
                    },
                }

            # Block 6B (readiness gate V1): the venue's upper bounds, on the
            # same fill this gate just derived and in the same fail-closed
            # place its lower bounds are enforced - before any reservation,
            # before admission is recorded, and before any execution path can
            # run. An order above ``LOT_SIZE.maxQty``,
            # ``MARKET_LOT_SIZE.maxQty`` or ``NOTIONAL.maxNotional`` is
            # refused outright; it is never split, capped, or resized down to
            # the maximum, exactly as an undersized one is never raised to a
            # minimum. A bound the config does not model is skipped here and
            # refused at the live-authority gate instead, so a bounded PAPER
            # runtime keeps its existing behaviour unchanged.
            upper_bound = instrument_rules.upper_bound_violation(
                base_quantity=admission_base_quantity,
                quote_notional=admission_quote_notional,
                order_type=request.order_type,
            )

            if upper_bound is not None:
                reason, details = upper_bound
                logger.warning(
                    "Admission refused above venue maximum symbol=%s "
                    "request_id=%s reason=%s",
                    request.symbol,
                    request.request_id,
                    reason,
                )
                return {
                    "approved": False,
                    "reason": reason,
                    "details": {"symbol": request.symbol, **details},
                }

            # RiskEngine judges against RiskPolicy.total_capital, which is a
            # configured policy figure, not the cash the durable book actually
            # holds. An approved allocation the book cannot fund would reserve
            # capital, execute, and only then fail inside apply_confirmed as
            # INSUFFICIENT_CASH - halting the runtime with an unresolved
            # journal entry and INDETERMINATE capital. Checking it here turns
            # that into an ordinary admission refusal that leaves no
            # reservation and no admission behind, and gives capital
            # exhaustion its own reason code instead of letting it surface as
            # malformed input.
            #
            # The bound is fee-inclusive because the approved allocation is:
            # settlement debits notional + fee, and the BUY path sizes the
            # fill so that notional + fee never exceeds the approval. So
            # reserving the approval reserves the whole economic requirement.
            #
            # The request's own reservation is excluded from the funding
            # measurement, because re-evaluating a request must not be able to
            # defund it: without the exclusion a request admitted once near the
            # durable bound would refuse itself on its next evaluation, having
            # been charged for capital it already holds. It still reserves at
            # most once - `reserve` returns the identical existing entry rather
            # than adding a second - and every other request's reservation
            # continues to encumber this one's capital.
            try:
                free_capital = self._durable_free_quote_capital(
                    exclude=request.request_id
                )
            except Exception as exc:
                self._record_error(phase="durable_capital", error=exc, request=request)
                return {"approved": False, "reason": "DURABLE_CAPITAL_STATE_UNAVAILABLE",
                        "status": "BLOCK_RECOVERY_REQUIRED"}

            if (
                free_capital is not None
                and canonical.approved_allocation > free_capital
            ):
                return {
                    "approved": False,
                    "reason": "INSUFFICIENT_DURABLE_CAPITAL",
                    "details": {
                        "approved_allocation": format(
                            canonical.approved_allocation, "f"
                        ),
                        "available_quote_capital": format(free_capital, "f"),
                    },
                }

            try:
                reservation = self.reservation_ledger.reserve(
                    request.request_id, request.request_id, canonical.approved_allocation,
                )
                # F-3: admission is granted only against live encumbrance.
                # reserve() returns a RESERVED record or raises; this keeps
                # that contract structurally enforced here rather than
                # assumed.
                if reservation.status is not ReservationStatus.RESERVED:
                    raise ValueError("reservation is not RESERVED")
            except Exception as exc:
                self._record_error(phase="capital_reservation", error=exc, request=request)
                return {"approved": False, "reason": "CAPITAL_RESERVATION_FAILED",
                        "status": "BLOCK_RECOVERY_REQUIRED"}

        # The single write of the canonical allocation, made only once every
        # reject-capable gate has passed. It is the engine's own Decimal, not
        # a re-derived one, and the admission token is sealed around it below.
        request.approved_quote_allocation = canonical.approved_allocation
        self._risk_admissions[request.request_id] = self._risk_admission_key(request)

        return {
            "approved": True,
            "reason": "RISK_APPROVED",
            # Block 5D: recorded here so it reaches the RISK_APPROVED audit
            # event through the existing details pass-through, alongside the
            # fill-time evidence _execute_paper_buy/_execute_paper_sell write
            # onto result.data.
            "details": {
                "instrument_rules_digest": instrument_rules.digest,
                "instrument_rules_source_version": instrument_rules.source_version,
                # registry v5.01 EXP-001: present only when the admission needed
                # the experiment's lowered floor; counted at startup for the cap.
                **({"experiment_id": canonical.experiment_id} if canonical.experiment_id else {}),
                # registry v5.23: the paper fee rate this execution charges,
                # so recovery re-derives the fill exactly (absent -> 0, the
                # historical fee-free contract). Recorded only when nonzero.
                **({"paper_fee_rate": format(self.paper_fee_rate, "f")} if self.paper_fee_rate else {}),
            },
        }

    def _can_open_position(
        self,
        symbol: str,
    ) -> bool:
        """
        Query PositionController through known compatibility contracts.
        """

        if self.position_controller is None:
            return True

        for method_name in (
            "can_open",
            "can_open_position",
        ):
            method = getattr(
                self.position_controller,
                method_name,
                None,
            )

            if not callable(
                method
            ):
                continue

            try:
                result = method(
                    symbol
                )

            except TypeError:
                try:
                    result = method()

                except Exception as exc:
                    self._record_error(
                        phase="position_limit",
                        error=exc,
                    )
                    return False

            except Exception as exc:
                self._record_error(
                    phase="position_limit",
                    error=exc,
                )
                return False

            if isinstance(
                result,
                Mapping,
            ):
                return bool(
                    result.get(
                        "approved",
                        result.get(
                            "allowed",
                            result.get(
                                "success",
                                False,
                            ),
                        ),
                    )
                )

            return bool(
                result
            )

        exists = getattr(
            self.position_controller,
            "exists",
            None,
        )

        if callable(
            exists
        ):
            try:
                return not bool(
                    exists(
                        symbol
                    )
                )

            except Exception as exc:
                self._record_error(
                    phase="position_exists",
                    error=exc,
                )
                return False

        return True

    def _risk_admission_key(self, request: ExecutionRequest) -> tuple[str, ...]:
        """Seal the terms a request was admitted on.

        The allocation term is the canonical ``Decimal``, never the ``amount``
        mirror. Two consequences follow, and both are intended: mutating the
        approved Decimal after admission invalidates the token and the request
        cannot execute, while mutating the lossy ``amount`` mirror changes
        nothing at all - it is not one of the admitted terms and no consumer
        downstream reads it.

        An unapproved request has no allocation to seal and is keyed as such,
        so a hand-built token can never stand in for an engine verdict.

        Block 5D: the symbol's current instrument-rules digest is sealed in
        too, so a rules change between admission and execution invalidates
        the admission exactly as an altered approval would - even though
        rules are immutable for the lifetime of one process (owner decision
        9), the seal is what makes that invariant structurally enforced
        rather than merely assumed.
        """
        approved = request.approved_quote_allocation

        rules = (
            self.instrument_rules.get(request.symbol)
            if self.instrument_rules is not None
            else None
        )

        return (
            request.symbol,
            request.action,
            str(Decimal(str(request.price))),
            format(approved, "f") if approved is not None else "UNAPPROVED",
            str(Decimal(str(request.confidence))),
            request.risk,
            str(bool(request.reduce_only)),
            rules.digest if rules is not None else "NO_INSTRUMENT_RULES",
            request.mode,
        )

    def _has_risk_admission(self, request: ExecutionRequest) -> bool:
        return self._risk_admissions.get(request.request_id) == self._risk_admission_key(request)

    # Each of these three helpers ends the execution authority of one
    # request. The admission is dropped even when the ledger write fails,
    # because a request whose capital could not be resolved must never keep
    # a token that would let a later stage treat it as still authorized;
    # the failing ledger write itself is what halts the runtime.

    def _release_capital_reservation(self, request_id: str) -> bool:
        if self.reservation_ledger is None:
            return False
        try:
            if self.reservation_ledger.get(request_id) is None:
                return True
            self.reservation_ledger.release(request_id)
            return True
        except Exception as exc:
            self._record_error(phase="capital_release", error=exc)
            with self._lock:
                self.execution_halted = True
                self.recovery_required = True
                self.halt_reason = "CAPITAL_RESERVATION_RELEASE_FAILED"
            return False
        finally:
            self._risk_admissions.pop(request_id, None)

    def _commit_capital_reservation(
        self, request_id: str, settled_amount: Decimal | None = None
    ) -> bool:
        """Commit a reservation, at ``settled_amount`` when one is known.

        ``settled_amount`` (Block 5E) is ``filled_quote_notional +
        quote_fee`` - the exact economic amount durable settlement spent.
        ``None`` preserves the historical behaviour of committing at the
        full reserved amount, for a caller that has no settled figure to
        offer (e.g. a non-paper/live path).
        """
        if self.reservation_ledger is None:
            return False
        try:
            if self.reservation_ledger.get(request_id) is None:
                return True
            self.reservation_ledger.commit(request_id, settled_amount)
            return True
        except Exception as exc:
            self._record_error(phase="capital_commit", error=exc)
            return False
        finally:
            self._risk_admissions.pop(request_id, None)

    def _mark_capital_indeterminate(self, request_id: str) -> bool:
        if self.reservation_ledger is None:
            return False
        try:
            if self.reservation_ledger.get(request_id) is None:
                return True
            self.reservation_ledger.mark_indeterminate(request_id)
            return True
        except Exception as exc:
            self._record_error(phase="capital_indeterminate", error=exc)
            return False
        finally:
            self._risk_admissions.pop(request_id, None)

    def _mark_execution_side_effect(self, request_id: str) -> None:
        """Record that this request has reached the paper/live side effect.

        Called immediately before the first component mutation of an
        execution, so a later exception cannot be mistaken for a request
        that never touched anything.
        """
        canonical_id = str(request_id).strip()
        if not canonical_id:
            return
        with self._lock:
            self._execution_side_effect_ids.add(canonical_id)

    def _consume_execution_side_effect(self, request_id: str) -> bool:
        """Clear and report the side-effect marker for one request."""
        canonical_id = str(request_id).strip()
        if not canonical_id:
            return False
        with self._lock:
            crossed = canonical_id in self._execution_side_effect_ids
            self._execution_side_effect_ids.discard(canonical_id)
            return crossed

    def _resolve_unsuccessful_execution(
        self,
        *,
        request_id: str,
        reason: str,
        result: Mapping[str, Any] | None = None,
    ) -> bool:
        """Restore deterministic financial authority after a failed execution.

        This is the single resolution path for every unsuccessful terminal
        outcome after risk admission — a raised pipeline exception and an
        explicit FAILED/ERROR result alike. How a failure was reported says
        nothing about whether the paper book was already mutated, so both
        are classified by the same recorded side-effect boundary rather than
        by the shape of the failure.

        Such a failure must never leave a RESERVED reservation, a stale
        admission, and a running runtime behind at the same time.

        Two outcomes are possible, and which one applies is decided by
        recorded fact rather than inference:

        - the side-effect boundary was never crossed, so nothing external can
          have happened: the reservation is RELEASED, the journal entry is
          resolved NOT_COMMITTED, and the request stays retryable;
        - the boundary was crossed, so the execution outcome is genuinely
          unknown: the reservation is marked INDETERMINATE, the journal entry
          is left COMMIT_STATUS_UNKNOWN, and the runtime halts for operator
          recovery instead of releasing capital it cannot prove is free.

        Returns True when an execution side effect may already have occurred.
        """
        side_effect_possible = self._consume_execution_side_effect(request_id)

        if side_effect_possible:
            self._mark_capital_indeterminate(request_id)

            try:
                self.transaction_journal.mark_unknown(
                    request_id,
                    reason=reason,
                    result=result,
                )
            except Exception:
                logger.exception(
                    "Unable to mark interrupted execution unknown"
                )

            with self._lock:
                self.execution_halted = True
                self.recovery_required = True
                self.halt_reason = (
                    "EXECUTION_INTERRUPTED_AFTER_SIDE_EFFECT"
                )

        else:
            self._release_capital_reservation(request_id)

            # Only an already prepared transaction is resolved here. A
            # request that never reached the prepare barrier must not gain a
            # journal entry from its own failure.
            prepared_entries = getattr(
                self.transaction_journal,
                "entries",
                {},
            )

            if request_id in prepared_entries:
                try:
                    self.transaction_journal.mark_not_committed(
                        request_id,
                        reason=reason,
                        result=result,
                    )
                except Exception:
                    logger.exception(
                        "Unable to mark interrupted execution not committed"
                    )

        self._risk_admissions.pop(request_id, None)

        return side_effect_possible

    def _finalize_durable_financial_state(
        self,
        *,
        request: ExecutionRequest,
        result: dict[str, Any],
    ) -> dict[str, Any]:
        """Consume confirmed execution evidence without invoking an exchange."""
        foundation = self.portfolio_foundation
        if foundation is None or not foundation.ready:
            raise RuntimeError("DURABLE_FINANCIAL_FOUNDATION_NOT_READY")
        if not self._has_risk_admission(request):
            raise PermissionError("CANONICAL_RISK_ADMISSION_MISSING")
        reservation = (
            self.reservation_ledger.get(request.request_id)
            if self.reservation_ledger is not None
            else None
        )
        reservation_required = request.action == "BUY" and not request.reduce_only
        if reservation_required and (
            reservation is None or reservation.status.value != "RESERVED"
        ):
            raise PermissionError("CAPITAL_RESERVATION_NOT_CONFIRMED")
        if self.reservation_ledger is None:
            raise PermissionError("CAPITAL_RESERVATION_STATE_NOT_READY")
        foundation.set_reserved_capital(
            self.reservation_ledger.active_reserved_capital(
                exclude=request.request_id if reservation_required else None
            )
        )
        evidence = ExecutionResult.from_dict(result)
        evidence.idempotency_key = request.request_id
        evidence.provenance_ref = f"transaction-journal:{request.request_id}"

        # Last reconciliation against the canonical approval before the
        # durable book is touched. New risk settles as notional + fee, which is
        # the same economic quantity admission bounded and the reservation
        # reserved, so evidence that exceeds it must never reach the ledger -
        # whatever produced it.
        approved = self._admitted_quote_allocation(request)
        if reservation_required:
            if approved is None:
                raise PermissionError("CANONICAL_ALLOCATION_MISSING")
            # Pinned to the same explicit settlement context the commit-time
            # `notional + fee` recomputation above uses (final-review
            # MEDIUM #2), so the two can never round this identical figure
            # differently under a caller's ambient precision.
            with localcontext() as context:
                context.prec = SETTLEMENT_CONTEXT_PRECISION
                context.rounding = ROUND_HALF_EVEN
                settled = (evidence.filled_quote_notional or Decimal("0")) + evidence.fee_amount
            if settled > approved:
                raise PermissionError("SETTLEMENT_EXCEEDS_APPROVED_ALLOCATION")

        # The pre-commit snapshot, the durable apply and the risk-accounting
        # read-modify-write run under this manager's lock and the journal's
        # lock - the same pair the day rollover holds - so neither a rollover
        # nor another finalization can land between the book's before/after
        # views that this commit's realized P&L is derived from.
        # Attributes are read defensively, as ``_reset_refusal_reason`` does,
        # so a partially constructed test double finalizes exactly as before.
        manager_lock = getattr(self, "_lock", None) or nullcontext()
        journal_lock = getattr(getattr(self, "transaction_journal", None), "_lock", None)
        if not (callable(getattr(journal_lock, "acquire", None))
                and callable(getattr(journal_lock, "release", None))):
            # The manager lock alone still excludes the rollover, which holds
            # it too; refusing here would drop an already-realized result.
            journal_lock = nullcontext()
        with manager_lock, journal_lock:
            expected_version = None
            snapshot = foundation.snapshot()
            current = snapshot["positions"].get(request.symbol)
            if current is not None:
                expected_version = int(current["version"])
            finalized = foundation.apply_confirmed(
                evidence,
                risk_authorized=True,
                reservation_confirmed=True,
                expected_position_version=expected_version,
            )
            if evidence.action == "SELL" and not finalized["replayed"]:
                self._record_realized_risk_accounting(
                    request=request,
                    evidence=evidence,
                    before=snapshot,
                    after=finalized,
                )
        result["idempotency_key"] = evidence.idempotency_key
        result["provenance_ref"] = evidence.provenance_ref
        result["durable_financial_state"] = {
            "replayed": finalized["replayed"],
            "position_id": evidence.position_id,
        }
        return finalized

    # =========================================================
    # REALIZED P&L INTO RISK ACCOUNTING (PAPER)
    # =========================================================

    RISK_REALIZED_PNL_PREPARED = "RISK_ACCOUNTING_REALIZED_PNL_PREPARED"
    RISK_REALIZED_PNL_COMMITTED = "RISK_ACCOUNTING_REALIZED_PNL_COMMITTED"
    RISK_ACCOUNTING_UPDATE_FAILED = "RISK_ACCOUNTING_UPDATE_FAILED"

    def _record_realized_risk_accounting(
        self,
        *,
        request: ExecutionRequest,
        evidence: ExecutionResult,
        before: Mapping[str, Any],
        after: Mapping[str, Any],
    ) -> None:
        """Fold one committed reduction's realized P&L into risk accounting.

        Called with this manager's lock and the journal's lock held, right
        after ``ExecutionPortfolioFoundation.apply_confirmed`` durably
        committed a SELL (a full exit or a partial reduction - both realize
        P&L). Every figure comes from the foundation's own snapshots taken
        either side of that commit; nothing is computed from prices, fills or
        any other source:

        - realized P&L of the portion sold is the book's gross realized P&L
          change, less the exit fee it charged, less the entry fees it
          released with the sold cost basis. Over a complete round trip this
          equals the change in the foundation's own ``realized_net_pnl``;
        - ``current_equity`` is the post-commit ``equity``, and
          ``peak_equity`` rises to it when it is a new high.

        PAPER only. The accounting day must already be today: ``risk_check``
        rolls it forward before admission, so a mismatch means UTC midnight
        passed between admission and commit, and the realized result is not
        silently booked to the wrong day.

        The trade itself is already committed in the durable book. Any
        failure to record its result - day mismatch, unreadable store,
        invalid resulting state, PREPARED audit failure, write failure -
        raises ``RISK_ACCOUNTING_UPDATE_FAILED`` so the request resolves
        through the durable finalization-failure path (journal left
        COMMIT_STATUS_UNKNOWN, runtime halted, every restart fail-closed):
        RiskEngine's daily loss and drawdown limits would otherwise be
        evaluated against accounting that no longer matches the book.
        """
        if self.mode != self.MODE_PAPER:
            return
        store = self.risk_state_store
        if store is None or self.risk_engine is None:
            return

        today = datetime.now(UTC).date()
        try:
            restored = store.load(
                expected_policy_version=self.risk_engine.policy.version,
                today_utc=today,
            )
            if restored.accounting_day_utc != today:
                raise ValueError("RISK_ACCOUNTING_DAY_NOT_CURRENT")

            symbol = evidence.symbol
            held_before = before["positions"].get(symbol)
            held_after = after["positions"].get(symbol)
            if held_before is None:
                raise ValueError("REDUCED_POSITION_ABSENT_BEFORE_COMMIT")
            with localcontext() as context:
                context.prec = SETTLEMENT_CONTEXT_PRECISION
                context.rounding = ROUND_HALF_EVEN
                gross = (
                    Decimal(str(after["realized_gross_pnl"]))
                    - Decimal(str(before["realized_gross_pnl"]))
                )
                exit_fee = Decimal(str(after["fees"])) - Decimal(str(before["fees"]))
                released_entry_fees = Decimal(str(held_before["entry_fees"])) - (
                    Decimal(str(held_after["entry_fees"]))
                    if held_after is not None
                    else Decimal("0")
                )
                realized = gross - exit_fee - released_entry_fees
                realized_daily_pnl = restored.realized_daily_pnl + realized
            equity = Decimal(str(after["equity"]))
            if not realized.is_finite() or not equity.is_finite() or equity <= 0:
                raise ValueError("DURABLE_FIGURES_NOT_ACCOUNTABLE")
            # Constructing the state validates it (finite, positive equity,
            # peak >= current) before anything is written.
            updated = RestoredRiskState(
                today,
                realized_daily_pnl,
                max(restored.peak_equity, equity),
                equity,
                restored.policy_version,
            )

            prepared_id = None
            if self.audit_enabled:
                # Write-ahead, exactly as the day rollover: no audit record,
                # no write.
                prepared = self.audit_store.append(
                    event_type=self.RISK_REALIZED_PNL_PREPARED,
                    source=self.NAME,
                    aggregate_type="risk_accounting_state",
                    aggregate_id=today.isoformat(),
                    payload={
                        "mode": self.mode,
                        "request_id": request.request_id,
                        "execution_id": evidence.execution_id,
                        "position_id": evidence.position_id,
                        "symbol": symbol,
                        "position_closed": held_after is None,
                        "realized_pnl": str(realized),
                        "components": {
                            "gross_realized_pnl": str(gross),
                            "exit_fee": str(exit_fee),
                            "released_entry_fees": str(released_entry_fees),
                        },
                        "figures_source": "ExecutionPortfolioFoundation",
                        "previous_state": restored.to_dict(),
                        "new_state": updated.to_dict(),
                    },
                    correlation_id=str(request.request_id),
                    metadata={"mode": self.mode, "manager_version": self.VERSION},
                )
                self.stats["audit_events_written"] += 1
                prepared_id = prepared.event_id

            store.save(updated)
        except Exception as exc:
            self._record_error(
                phase="risk_accounting_realized_pnl", error=exc, request=request,
            )
            logger.error(
                "Realized P&L could not be recorded in risk accounting; the "
                "trade is committed in the durable book and the request is "
                "resolved as a durable finalization failure for operator "
                "reconciliation request_id=%s symbol=%s error=%s: %s",
                request.request_id,
                evidence.symbol,
                type(exc).__name__,
                exc,
            )
            # Raised to execute()'s post-apply finalization-failure path -
            # the same one a failed reservation commit after apply takes: the
            # journal entry is left COMMIT_STATUS_UNKNOWN on disk and the
            # runtime halts. An in-memory halt alone would end at restart and
            # resume with the loss unrecorded; an unresolved journal entry
            # keeps every restart fail-closed until an operator reconciles.
            raise RuntimeError(self.RISK_ACCOUNTING_UPDATE_FAILED) from exc

        logger.info(
            "Risk accounting realized P&L recorded request_id=%s symbol=%s "
            "realized_pnl=%s realized_daily_pnl %s -> %s current_equity %s -> %s "
            "peak_equity %s -> %s",
            request.request_id,
            evidence.symbol,
            realized,
            restored.realized_daily_pnl,
            updated.realized_daily_pnl,
            restored.current_equity,
            updated.current_equity,
            restored.peak_equity,
            updated.peak_equity,
        )

        if prepared_id is None:
            return
        try:
            self.audit_store.append(
                event_type=self.RISK_REALIZED_PNL_COMMITTED,
                source=self.NAME,
                aggregate_type="risk_accounting_state",
                aggregate_id=today.isoformat(),
                payload={"mode": self.mode, "request_id": request.request_id,
                         "new_state": updated.to_dict()},
                correlation_id=str(request.request_id),
                causation_id=prepared_id,
                metadata={"mode": self.mode, "manager_version": self.VERSION},
            )
            self.stats["audit_events_written"] += 1
        except Exception as exc:
            # The update is already durable and PREPARED carries every input
            # that determined it; the audit runtime degrades, as for the
            # rollover's COMMITTED record.
            self.stats["audit_write_failures"] += 1
            self._record_audit_failure(
                event_type=self.RISK_REALIZED_PNL_COMMITTED,
                request=request,
                error=exc,
                stage="RISK_ACCOUNTING",
            )
            self._record_error(phase="risk_accounting_realized_pnl_audit", error=exc)

    # =========================================================
    # PASSIVE PAPER BOOK MIRROR
    # =========================================================

    def _mirror_paper_book(
        self,
        *,
        request: ExecutionRequest,
        result: dict[str, Any],
        finalized: Mapping[str, Any] | None = None,
    ) -> None:
        """Project the committed durable position onto the passive paper book.

        PaperTrader holds no authority. Its record for this symbol is
        overwritten from ExecutionPortfolioFoundation's own post-commit
        snapshot - never from PaperTrader's prior contents, and never by
        replaying open/close semantics against it. That makes both
        add-to-position and partial-exit ordinary cases: the symbol is
        written to current durable truth, or dropped when the authority
        shows it flat.

        Every failure here is contained. The execution is already committed
        and the authority already holds the truth, so a mirror that could
        raise - or could turn a committed execution into a reported failure
        - would reintroduce the very veto this method exists to remove. The
        outcome is published as observability data only, under
        ``result["data"]["paper_mirror"]``.
        """

        status = "OK"

        try:
            if (
                self.paper_trader is None
                or self.portfolio_foundation is None
            ):
                return

            symbol = request.symbol

            position = self.portfolio_foundation.snapshot()[
                "positions"
            ].get(symbol)

            self.paper_trader.apply_projection(
                symbol=symbol,
                position=position,
                history_entry=self._paper_mirror_history_entry(
                    request=request,
                    result=result,
                    position=position,
                    finalized=finalized,
                ),
            )

        except Exception:
            status = "DEGRADED"

            logger.exception(
                "Paper book mirror failed; durable financial state "
                "is unaffected and the execution stands"
            )

        finally:
            self._set_paper_mirror_status(
                result,
                status,
            )

    def _reproject_paper_book(self) -> None:
        """F-4: rebuild the passive paper book from durable truth at startup.

        ``_mirror_paper_book`` only projects the symbol a commit touched, so
        without this a book that was lost, torn, or left behind by a crash
        would disagree with ExecutionPortfolioFoundation indefinitely for any
        symbol that never trades again. Runs only once the foundation is
        known ready, so it projects from a snapshot that is itself trusted.

        Contained exactly like ``_mirror_paper_book``: the book holds no
        authority, so a failure here is logged and never halts the runtime.
        """
        if self.paper_trader is None or self.portfolio_foundation is None:
            return
        reproject = getattr(self.paper_trader, "reproject_all", None)
        if not callable(reproject):
            return
        try:
            diverged = reproject(
                self.portfolio_foundation.snapshot()["positions"]
            )
        except Exception:
            logger.exception(
                "Paper book startup re-projection failed; durable financial "
                "state is unaffected"
            )
            return
        if diverged:
            logger.warning(
                "Paper book mirror diverged from durable financial state and "
                "was re-projected at startup symbols=%s",
                diverged,
            )

    def _paper_mirror_history_entry(
        self,
        *,
        request: ExecutionRequest,
        result: Mapping[str, Any],
        position: Mapping[str, Any] | None,
        finalized: Mapping[str, Any] | None,
    ) -> dict[str, Any]:
        """Describe the committed outcome for the mirrored book's history.

        Classified from the durable authority's own post-commit record: a
        surviving position's ``version`` is what distinguishes a first open
        from an add, so PaperTrader's prior contents are never consulted.
        """

        def _text(value: Any) -> str | None:
            return None if value is None else str(value)

        action = str(
            request.action or ""
        ).strip().upper()

        if position is None:
            event = "CLOSE"

        elif action == "SELL":
            event = "REDUCE"

        else:
            try:
                opened_before = int(position.get("version") or 1) > 1
            except (TypeError, ValueError):
                opened_before = False

            event = "ADD" if opened_before else "OPEN"

        entry: dict[str, Any] = {
            "type": event,
            "action": action,
            "symbol": request.symbol,
            "executed_base_quantity": _text(
                result.get("filled_base_quantity")
            ),
            "executed_quote_notional": _text(
                result.get("filled_quote_notional")
            ),
            "price": result.get("filled_price"),
            "request_id": request.request_id,
            "execution_id": result.get("execution_id"),
            "position_id": (
                None if position is None
                else _text(position.get("position_id"))
            ),
            "resulting_base_quantity": (
                None if position is None
                else _text(position.get("base_quantity"))
            ),
            "time": self._utc_now(),
        }

        if isinstance(finalized, Mapping) and "replayed" in finalized:
            entry["replayed"] = bool(
                finalized["replayed"]
            )

        return entry

    @staticmethod
    def _set_paper_mirror_status(
        result: Any,
        status: str,
    ) -> None:
        """Record the mirror outcome as observability data, nothing more."""

        try:
            if not isinstance(result, dict):
                return

            data = result.get("data")

            if not isinstance(data, dict):
                data = {}
                result["data"] = data

            data["paper_mirror"] = status

        except Exception:
            logger.exception(
                "Unable to record paper mirror status"
            )

    # =========================================================
    # PAPER EXECUTION
    # =========================================================

    def paper_execute(
        self,
        request: ExecutionRequest,
    ) -> dict[str, Any]:
        """
        Execute an approved request in paper mode.
        """

        if not self._has_risk_admission(request):
            return self.reject(reason="CANONICAL_RISK_ADMISSION_MISSING", request=request)

        # Shadow fill model (S2, owner approval 2026-10-02): with a provider the
        # fill is priced against the live order book; no price means REJECT,
        # never a fallback to the last price. Without a provider this is the
        # historical PAPER fill, byte-identical.
        if getattr(self, "paper_fill_provider", None) is not None:
            filled_price = self._shadow_book_fill_price(request)
            if filled_price is None:
                return self.reject(reason="SHADOW_BOOK_PRICE_UNAVAILABLE", request=request)
        else:
            filled_price = self._paper_fill_price(request)

        execution_id = str(
            uuid.uuid4()
        )

        logger.info(
            "[PAPER ORDER] request_id=%s execution_id=%s "
            "%s %s @ %.8f confidence=%.2f%%",
            request.request_id,
            execution_id,
            request.action,
            request.symbol,
            request.price,
            request.confidence,
        )

        result = ExecutionResult(
            success=True,
            status="PAPER_EXECUTED",
            message="Paper execution completed",
            execution_id=execution_id,
            symbol=request.symbol,
            action=request.action,
            filled_price=filled_price,
            filled_amount=0.0,
            mode=self.MODE_PAPER,
            data={
                "request_id": request.request_id,
                "confidence": request.confidence,
                "strategy": request.strategy,
                "risk": request.risk,
                "source": request.source,
                "order_type": request.order_type,
            },
            metadata={
                **self._normalize_metadata(
                    request.metadata
                ),
                "request_mode": request.mode,
            },
            timestamp=request.timestamp,
            requested_price=request.price,
            requested_amount=request.amount,
            idempotency_key=request.request_id,
            provenance_ref=f"transaction-journal:{request.request_id}",
        )

        if request.action == "BUY":
            self._execute_paper_buy(
                request=request,
                result=result,
            )

        elif request.action == "SELL":
            self._execute_paper_sell(
                request=request,
                result=result,
            )

        with self._lock:
            self.stats["paper_orders"] += 1

        return result.to_dict()

    # =========================================================
    # PAPER BUY
    # =========================================================

    def _admitted_quote_allocation(
        self,
        request: ExecutionRequest,
    ) -> Decimal | None:
        """The one quote amount execution is allowed to commit.

        This is the canonical ``RiskDecision.approved_allocation`` itself, as
        an exact ``Decimal``, read from the field ``risk_check`` wrote it to.
        It never passes through ``ExecutionRequest.amount``: that mirror is a
        ``float``, and a binary round-trip of an approved allocation is
        precisely the corruption this field exists to prevent.

        ``risk_check`` refuses to admit a request whose requested allocation
        differs from the engine's verdict (``RISK_ALLOCATION_MISMATCH``), and
        ``_risk_admission_key`` seals the Decimal into the admission token, so
        an approval altered after admission invalidates the admission rather
        than being executed. There is no second source: CapitalManager sizing,
        available-capital defaults, and the historical ``DEFAULT_ALLOCATION``
        fallback have all been removed.

        Returns ``None`` when the request carries no approval at all, which
        every caller treats as a fail-closed condition.
        """

        return request.approved_quote_allocation

    @staticmethod
    def _resolve_base_fill(
        *,
        allocation: Decimal,
        price: Decimal,
        fee: Decimal,
        quantity_step: Decimal,
    ) -> tuple[Decimal, Decimal] | None:
        """Size a new-risk fill inside an approved allocation, exactly.

        Quantity first, notional second. The largest whole venue
        ``quantity_step`` the allocation can pay for is chosen, and the quote
        notional is then *derived* from that quantity at the execution price.
        Because the notional is a product rather than the input to a
        division, the canonical identity

            execution_price * filled_base_quantity == filled_quote_notional

        holds exactly, under the same arithmetic
        ``ExecutionResult.validate_financial_evidence`` re-checks it with.
        The historical order - notional first, quantity = notional / price -
        could not hold it for any price the allocation does not divide by,
        which is nearly all of them.

        Fee inclusion
        -------------
        ``ExecutionPortfolioFoundation`` debits ``notional + fee`` at
        settlement, so the fee is taken out of the allocation here rather than
        charged on top of it. The approved allocation is therefore the whole
        economic commitment, which is exactly what admission bounded and what
        the capital reservation reserves; a fee can no longer turn an admitted
        request into an ``INSUFFICIENT_CASH`` failure at settlement.

        Remainder
        ---------
        The unspent remainder is deterministic, is strictly smaller than one
        quantum of notional, and always favours less risk: rounding is
        ``ROUND_DOWN`` on the quantity, so the executed notional can only ever
        be at or below the approval, never above it. Callers record it.

        Returns ``None`` when no positive whole ``quantity_step`` is
        affordable - an allocation consumed entirely by its fee, a
        non-positive price, or a price so high that a single step costs more
        than was approved. That is a fail-closed refusal, never a rounded-up
        fill. This is the one derivation both the pre-reservation admission
        feasibility check in ``risk_check`` and this post-component
        defense-in-depth call site use (Block 5D), so the two can never
        disagree on how a fill is sized.
        """
        if not price.is_finite() or price <= 0:
            return None
        if not allocation.is_finite() or not fee.is_finite() or fee < 0:
            return None

        spendable = allocation - fee
        if spendable <= 0:
            return None

        try:
            with localcontext() as context:
                # ROUND_DOWN on the division as well as the step flooring: a
                # quotient rounded up in its last representable digit could
                # otherwise cross a step boundary and buy one step more than
                # the allocation covers.
                context.rounding = ROUND_DOWN
                quotient = spendable / price

            base = floor_to_step(quotient, quantity_step)
            quote = price * base
        except (InvalidOperation, ZeroDivisionError, ValueError):
            return None

        if base <= 0 or quote <= 0 or quote + fee > allocation:
            return None

        return base, quote

    def _execute_paper_buy(
        self,
        *,
        request: ExecutionRequest,
        result: ExecutionResult,
    ) -> None:
        """Coordinate a paper BUY and authoritative position registration.

        The approved allocation is a *ceiling* on what the fill may cost, not
        the notional itself: the executed quantity is chosen inside it and the
        notional is derived from that quantity, so the fill is exact and can
        never exceed what risk approved. See ``_resolve_base_fill``.
        """

        prepared = self._paper_buy_preflight(
            request=request,
            result=result,
        )

        if prepared is None:
            return

        approved, instrument_rules = prepared

        # Fill-evidence seam. No paper execution adapter is configured in
        # this runtime, so this reports nothing and the fill is derived
        # from the request price below. PaperTrader is NOT consulted here:
        # it is a passive mirror of the durable authority (see
        # _mirror_paper_book) and can neither report a fill nor refuse one.
        paper_trade = self._paper_open_trade(
            request=request,
            allocation=float(approved),
        )

        if paper_trade is not None:
            result.data["paper_trade"] = paper_trade

            self._hydrate_result_from_component(
                result=result,
                payload=paper_trade,
            )

        if not result.order_id:
            result.order_id = "paper-order:" + str(
                uuid.uuid5(uuid.NAMESPACE_URL, str(request.request_id))
            )

        quote_notional = self._paper_buy_settle_fill(
            result=result,
            approved=approved,
            instrument_rules=instrument_rules,
        )

        if quote_notional is None:
            return

        self._paper_buy_register_position(
            request=request,
            result=result,
            approved=approved,
            quote_notional=quote_notional,
        )

    def _paper_buy_preflight(
        self,
        *,
        request: ExecutionRequest,
        result: ExecutionResult,
    ) -> tuple[Decimal, Any] | None:
        """Checks before the side-effect boundary (T-0003 split of _execute_paper_buy).

        Returns (approved allocation, instrument rules), or None after marking
        the result failed - exactly where the original body returned.
        """

        approved = self._admitted_quote_allocation(
            request
        )

        result.data = result.data or {}

        if approved is None or approved <= 0:
            # An admitted request always carries a positive approved Decimal.
            # Reaching here means the approval was removed after admission.
            self._mark_result_failure(
                result=result,
                message="Request carries no canonical approved allocation",
                error_code="CANONICAL_ALLOCATION_MISSING",
            )
            return None

        result.requested_quote_allocation = approved
        result.data["approved_quote_allocation"] = format(approved, "f")

        # Defense-in-depth (Block 5D): admission already required a rule for
        # this symbol, so this can only be reached if the rule disappeared
        # between admission and execution - which the admission-key seal
        # below also catches. Checked before the side-effect boundary so a
        # somehow-missing rule still refuses cleanly instead of mutating the
        # paper book first.
        instrument_rules = (
            self.instrument_rules.get(request.symbol)
            if self.instrument_rules is not None
            else None
        )

        if instrument_rules is None:
            self._mark_result_failure(
                result=result,
                message="No instrument rules for symbol",
                error_code="INSTRUMENT_RULES_UNAVAILABLE",
            )
            return None

        result.data["instrument_rules_digest"] = instrument_rules.digest
        result.data["instrument_rules_source"] = instrument_rules.source
        result.data["instrument_rules_source_version"] = (
            instrument_rules.source_version
        )

        # Block 5G: a flat-book BUY is about to mint a new lifetime identity
        # from (symbol, request_id) alone, which is decidable now rather
        # than after the fact - checked before the side-effect boundary for
        # the same reason as the instrument-rules check above, so a mint
        # failure refuses cleanly instead of opening a paper trade that
        # would then need an INDETERMINATE halt to recover from. Since
        # mint_long_position_id hashes request_id rather than embedding it,
        # request_id's own content/length can no longer make the mint fail
        # (any request_id, including MarketLoop's pipe-delimited
        # convention, always produces a valid, bounded digest) - this now
        # guards only the always-should-be-unreachable case of a
        # malformed symbol reaching this point, kept as the same
        # defense-in-depth the instrument-rules check above already
        # applies to a rule that "can only be reached if [it] disappeared
        # between admission and execution". An add-to-position BUY reuses
        # the existing live position_id and never mints, so it is exempt.
        if self.portfolio_foundation is not None:
            preflight_position = self.portfolio_foundation.snapshot()["positions"].get(request.symbol)
            if preflight_position is None:
                try:
                    mint_long_position_id(request.symbol, request.request_id)
                except ValueError:
                    self._mark_result_failure(
                        result=result,
                        message="symbol/request_id do not produce a valid composite position identity",
                        error_code="INVALID_POSITION_IDENTITY",
                    )
                    return None

        return approved, instrument_rules

    def _paper_buy_settle_fill(
        self,
        *,
        result: ExecutionResult,
        approved: Decimal,
        instrument_rules: Any,
    ) -> Decimal | None:
        """Size the fill, settle the fee and re-assert venue minimums (T-0003 split).

        Returns the executed quote notional, or None after marking the result
        failed - exactly where the original body returned.
        """

        # Sized after hydration, so the price and fee the executing component
        # actually reported are the ones the fill is derived from - not the
        # ones this manager assumed before calling it. `result.fee_amount`
        # is already the authoritative Decimal `_hydrate_result_from_component`
        # set - exact when the component reported `fee_amount` directly,
        # float-derived otherwise (Block 5E).
        try:
            execution_price = Decimal(str(result.filled_price))
        except (InvalidOperation, ValueError, TypeError):
            self._mark_result_failure(
                result=result,
                message="Paper fill quantity semantics are invalid",
                error_code="INVALID_FINANCIAL_QUANTITY",
            )
            return None

        # Registry v5.23: with no component-reported fee, paper charges the
        # governed PAPER_FEE_RATE_PER_SIDE. The fee is sized from the
        # allocation as rate*A/(1+rate), which equals rate*(A-fee) and so is
        # never below the fee on the (step-rounded, smaller) actual notional.
        ExecutionManager._apply_paper_fee_if_unreported(
            result=result,
            fee_amount=self._paper_buy_fee(approved),
            quote_asset=instrument_rules.quote_asset,
        )

        # Block 5E: only a fee this venue's quote asset can settle exactly is
        # ever allowed to reach durable settlement. A base-asset fee, a
        # third-asset fee, or an undeclared nonzero fee is refused here -
        # before `_finalize_durable_financial_state` - never inferred and
        # never converted. The only fee-rate policy is the paper rate above.
        try:
            normalized_fee = FeeNormalizer.normalize(
                fee_amount=result.fee_amount,
                fee_currency=result.fee_currency,
                instrument=instrument_rules,
            )
        except FeeRejected as exc:
            self._mark_result_failure(
                result=result,
                message="Component-reported fee cannot be settled: only this venue's quote-asset fee is supported",
                error_code=exc.reason.value,
                details={
                    "fee_amount": (
                        format(exc.fee_amount, "f") if exc.fee_amount is not None else None
                    ),
                    "fee_currency": exc.fee_currency,
                    "quote_asset": instrument_rules.quote_asset,
                    "base_asset": instrument_rules.base_asset,
                },
            )
            return None

        fee_amount = normalized_fee.quote_amount

        fill = self._resolve_base_fill(
            allocation=approved,
            price=execution_price,
            fee=fee_amount,
            quantity_step=instrument_rules.quantity_step,
        )

        if fill is None:
            self._mark_result_failure(
                result=result,
                message="Approved allocation cannot fund one whole quantity_step at the fill price",
                error_code="ALLOCATION_BELOW_EXECUTABLE_QUANTUM",
                details={
                    "approved_quote_allocation": format(approved, "f"),
                    "execution_price": format(execution_price, "f"),
                    "fee_amount": format(fee_amount, "f"),
                    "quantity_step": format(instrument_rules.quantity_step, "f"),
                },
            )
            return None

        base_quantity, quote_notional = fill

        # Block 5D owner ruling (SELL-venue-minimums remediation, M1): the
        # admission-time bound above used fee=0, because the fee is not
        # known until the executing component reports it here. A
        # component-reported fee can shrink the fee-adjusted fill enough to
        # cross below the venue's minimum even though admission cleared it
        # against a zero fee, so both minimums are re-asserted against the
        # actual fill before durable settlement - using the same
        # post-side-effect failure machinery the `fill is None` check above
        # already relies on, so a violation here halts for operator
        # recovery with capital INDETERMINATE rather than settling a
        # venue-invalid fill.
        if base_quantity < instrument_rules.min_quantity:
            self._mark_result_failure(
                result=result,
                message="Fee-adjusted fill quantity is below the venue minimum quantity",
                error_code="QUANTITY_BELOW_VENUE_MINIMUM",
                details={
                    "filled_base_quantity": format(base_quantity, "f"),
                    "fee_amount": format(fee_amount, "f"),
                    "min_quantity": format(instrument_rules.min_quantity, "f"),
                },
            )
            return None

        if quote_notional < instrument_rules.min_notional:
            self._mark_result_failure(
                result=result,
                message="Fee-adjusted fill notional is below the venue minimum notional",
                error_code="NOTIONAL_BELOW_VENUE_MINIMUM",
                details={
                    "filled_quote_notional": format(quote_notional, "f"),
                    "fee_amount": format(fee_amount, "f"),
                    "min_notional": format(instrument_rules.min_notional, "f"),
                },
            )
            return None

        result.filled_base_quantity = base_quantity
        result.filled_quote_notional = quote_notional
        result.fee_amount = fee_amount
        result.fee_currency = normalized_fee.currency

        # Historical compatibility: filled_amount stays quote capital on this
        # path.  Canonical consumers must use the explicit Decimal fields.
        result.filled_amount = float(quote_notional)

        # The unspent remainder is stated rather than absorbed silently, so a
        # reviewer can see exactly how much of the approval the quantum bound
        # left behind.
        result.data["executed_quote_notional"] = format(quote_notional, "f")
        result.data["unallocated_quote_remainder"] = format(
            approved - quote_notional - fee_amount, "f"
        )

        return quote_notional

    def _paper_buy_register_position(
        self,
        *,
        request: ExecutionRequest,
        result: ExecutionResult,
        approved: Decimal,
        quote_notional: Decimal,
    ) -> None:
        """Register the executed position and publish TRADE_OPENED (T-0003 split)."""

        # The compatibility position path is told what was executed, not what
        # was approved. They differ by the sub-quantum remainder, and a
        # position recorded at the approval would overstate the exposure the
        # book actually holds.
        executed_allocation = float(quote_notional)
        result.data["allocation"] = executed_allocation

        position_metadata = {
            **self._normalize_metadata(
                request.metadata
            ),
            "request_id": request.request_id,
            "execution_id": result.execution_id,
            "execution_mode": self.MODE_PAPER,
            "execution_timestamp": self._serialize_timestamp(
                request.timestamp
            ),
            "allocation": executed_allocation,
            "approved_quote_allocation": format(approved, "f"),
            "source": request.source,
            "order_type": request.order_type,
            "time_in_force": request.time_in_force,
            "reduce_only": request.reduce_only,
        }

        if self.portfolio_foundation is not None:
            existing = self.portfolio_foundation.snapshot()["positions"].get(request.symbol)
            result.position_id = (
                existing["position_id"] if existing is not None
                else mint_long_position_id(request.symbol, request.request_id)
            )
            position = None
            if self.position_risk_buckets is not None:
                # Recorded before the durable commit: an id whose open never
                # commits is simply never looked up. A failure here never
                # blocks the trade; the position then reads as UNKNOWN.
                try:
                    self.position_risk_buckets.record(result.position_id, str(request.risk or ""))
                except Exception:
                    logger.warning("Position risk bucket not recorded; position reads as UNKNOWN", exc_info=True)
        else:
            # Side-effect boundary for the foundation-less configuration:
            # PositionController is mutated here and there is no durable
            # finalization afterwards to carry the marker instead.
            self._mark_execution_side_effect(request.request_id)

            position = self._position_open(
                request=request,
                allocation=executed_allocation,
                metadata=position_metadata,
            )

        if position is not None:
            result.data["position"] = position

            if isinstance(
                position,
                Mapping,
            ):
                result.position_id = self._extract_nested(
                    position,
                    "position_id",
                    "id",
                )

                if not bool(
                    position.get(
                        "success",
                        True,
                    )
                ):
                    self._mark_result_failure(
                        result=result,
                        message=str(
                            position.get(
                                "reason",
                                "Position registration failed",
                            )
                        ),
                        error_code="POSITION_OPEN_REJECTED",
                        details=dict(
                            position
                        ),
                    )

        if result.success and position is not None and not result.position_id:
            self._mark_result_failure(
                result=result,
                message="Position mutation did not return authoritative position_id",
                error_code="MISSING_POSITION_IDENTITY",
            )

        self.publish(
            "TRADE_OPENED",
            result.to_dict(),
        )

    def _paper_open_trade(
        self,
        *,
        request: ExecutionRequest,
        allocation: float,
    ) -> Any | None:
        """Report a paper BUY fill from an execution adapter, if one exists.

        This is the fill-evidence seam only: whatever it returns is
        hydrated onto the result (price, fee, identifiers) before the fill
        is sized. It deliberately does NOT call PaperTrader. PaperTrader
        is a passive mirror of ExecutionPortfolioFoundation, projected
        after the durable commit by ``_mirror_paper_book``; letting it
        report a fill here would let a simulation book set the figures the
        durable authority then settles, and letting it refuse here let a
        phantom refusal halt the runtime.

        No paper execution adapter is configured in this runtime, so this
        reports nothing and the fill is derived from the request price.
        """

        return None

    def _position_open(
        self,
        *,
        request: ExecutionRequest,
        allocation: float,
        metadata: dict[str, Any],
    ) -> Any | None:
        """
        Register the complete execution context in PositionController.
        """

        if self.position_controller is None:
            return None

        open_position = getattr(
            self.position_controller,
            "open_position",
            None,
        )

        if not callable(
            open_position
        ):
            return None

        try:
            return open_position(
                symbol=request.symbol,
                price=request.price,
                side="LONG",
                amount=allocation,
                confidence=request.confidence,
                strategy=request.strategy,
                risk=request.risk,
                stop_loss=request.stop_loss,
                take_profit=request.take_profit,
                trailing_stop=request.trailing_stop,
                metadata=metadata,
                request_id=request.request_id,
                execution_id=metadata["execution_id"],
                mode=self.MODE_PAPER,
                timestamp=request.timestamp,
                source=request.source,
            )

        except TypeError:
            try:
                return open_position(
                    request.symbol,
                    request.price,
                )

            except Exception as exc:
                self._record_error(
                    phase="position_open",
                    error=exc,
                    request=request,
                )
                logger.exception(
                    "PositionController open failed"
                )
                return {
                    "success": False,
                    "status": "FAILED",
                    "reason": str(
                        exc
                    ),
                }

        except Exception as exc:
            self._record_error(
                phase="position_open",
                error=exc,
                request=request,
            )
            logger.exception(
                "PositionController open failed"
            )
            return {
                "success": False,
                "status": "FAILED",
                "reason": str(
                    exc
                ),
            }

    # =========================================================
    # PAPER SELL
    # =========================================================

    def _resolve_reduction_quantity(
        self,
        *,
        request: ExecutionRequest,
        result: ExecutionResult,
        position: Mapping[str, Any],
    ) -> Decimal | None:
        """Convert the approved quote reduction into base units to sell.

        Exposure basis
        --------------
        Both sides of this conversion use the durable position's own
        ``mark_price`` - the same basis ``_derived_position_exposures`` reports
        to RiskEngine and the same basis the approval was measured against. No
        market price is consulted and no new price authority is introduced, so
        admission and execution can never disagree about what the position is
        worth.

        The execution price affects only the proceeds - ``filled_quote_notional``
        is the fill, priced at the fill - never how much is sold.

        Full exit
        ---------
        An approval equal to the whole held exposure returns the durable
        ``base_quantity`` *itself*, byte for byte, rather than a quantity
        re-derived by dividing the approval back by the basis. That is what
        makes a full close leave nothing behind: the foundation removes a
        position only when the sold quantity equals the held quantity exactly,
        and a re-derived quantity can miss it by a rounding remainder and
        strand un-exitable dust in the book.

        Partial exit
        ------------
        The reduction is floored to a whole venue ``quantity_step`` (Block
        5D), so the exposure actually removed is at or just below what was
        approved - a deterministic remainder smaller than one step, always on
        the side of reducing less than permitted rather than more. It can
        never reach the held quantity, so a partial reduction stays partial.

        Returns ``None`` after marking ``result`` failed. Failure modes are
        fail-closed and none can under- or over-sell:

        ``INSTRUMENT_RULES_UNAVAILABLE``
            no rule for this symbol. Admission already required one, so
            reaching this is the same defense-in-depth case
            ``_execute_paper_buy`` guards against.

        ``REDUCTION_EXCEEDS_POSITION``
            more was approved than is held. RiskEngine already refuses this as
            ``INVALID_RISK_REDUCTION``, so reaching it means the durable book
            moved after admission.

        ``REDUCTION_BELOW_EXECUTABLE_QUANTUM``
            the approved reduction is smaller than one ``quantity_step`` at
            this basis, so no positive quantity can be sold for it.

        Venue minimums (Block 5D SELL-venue-minimums owner ruling)
        ------------------------------------------------------------
        Exact durable-quantity preservation on a full exit and never-round-up
        flooring on a partial exit do not exempt a SELL from the venue's own
        ``min_quantity``/``min_notional`` - a venue would refuse either order
        exactly as it would refuse an undersized BUY. Neither side is ever
        raised, floored to a minimum, or auto-upgraded to a full close:

        ``FULL_EXIT_BELOW_VENUE_MINIMUM``
            the exact durable holding itself - quantity or notional - is
            below what the venue would accept as a close order. Left for
            operator reconciliation; never floored, rounded, or written off.

        ``QUANTITY_BELOW_VENUE_MINIMUM`` / ``NOTIONAL_BELOW_VENUE_MINIMUM``
            the floored partial-reduction quantity itself, or its notional at
            the same exposure basis, is below the venue minimum - the same
            gate ``risk_check`` already applies to a new-risk BUY.

        ``REDUCTION_STRANDS_SUBMINIMUM_REMAINDER``
            the partial reduction itself is venue-valid, but the durable
            quantity it would leave behind is not - neither zero nor at or
            above the venue minimum. Rather than silently promote the
            request to a full close, the partial reduction is refused
            outright; the caller may resubmit an unsized (full) exit.
        """

        held = Decimal(str(position["base_quantity"]))
        basis = Decimal(str(position["mark_price"]))
        exposure = held * basis
        reduction = self._admitted_quote_allocation(request)

        result.data["risk_basis_price"] = format(basis, "f")
        result.data["held_base_quantity"] = format(held, "f")

        instrument_rules = (
            self.instrument_rules.get(request.symbol)
            if self.instrument_rules is not None
            else None
        )

        if instrument_rules is None:
            self._mark_result_failure(
                result=result,
                message="No instrument rules for symbol",
                error_code="INSTRUMENT_RULES_UNAVAILABLE",
            )
            return None

        result.data["instrument_rules_digest"] = instrument_rules.digest
        result.data["instrument_rules_source"] = instrument_rules.source
        result.data["instrument_rules_source_version"] = (
            instrument_rules.source_version
        )

        if reduction is None:
            self._mark_result_failure(
                result=result,
                message="Request carries no canonical approved allocation",
                error_code="CANONICAL_ALLOCATION_MISSING",
            )
            return None

        result.data["approved_quote_reduction"] = format(reduction, "f")

        if reduction <= 0 or basis <= 0 or reduction > exposure:
            self._mark_result_failure(
                result=result,
                message="Approved reduction is not covered by the held position",
                error_code="REDUCTION_EXCEEDS_POSITION",
                details={
                    "approved_quote_reduction": format(reduction, "f"),
                    "held_quote_exposure": format(exposure, "f"),
                },
            )
            return None

        if reduction == exposure:
            # Block 5D SELL-venue-minimums owner ruling: exact durable
            # quantity is preserved on a full exit, but that quantity is not
            # exempt from the venue's own minimums. A close order the venue
            # itself would refuse fails closed here, before any side effect,
            # for operator reconciliation - never floored, rounded up, or
            # written off.
            full_exit_notional = held * basis
            if (
                held < instrument_rules.min_quantity
                or full_exit_notional < instrument_rules.min_notional
            ):
                self._mark_result_failure(
                    result=result,
                    message="Full exit is below the venue minimum quantity or notional",
                    error_code="FULL_EXIT_BELOW_VENUE_MINIMUM",
                    details={
                        "held_base_quantity": format(held, "f"),
                        "held_quote_notional": format(full_exit_notional, "f"),
                        "min_quantity": format(instrument_rules.min_quantity, "f"),
                        "min_notional": format(instrument_rules.min_notional, "f"),
                    },
                )
                return None

            # Block 6B: a holding larger than the venue's maximum order is
            # not sellable in one order either. Refused for operator
            # reconciliation - never silently split into several orders, which
            # would be this manager inventing an execution plan the risk
            # authority never approved.
            full_exit_bound = instrument_rules.upper_bound_violation(
                base_quantity=held,
                quote_notional=full_exit_notional,
                order_type=request.order_type,
            )

            if full_exit_bound is not None:
                bound_reason, bound_details = full_exit_bound
                self._mark_result_failure(
                    result=result,
                    message="Full exit is above the venue maximum quantity or notional",
                    error_code=FULL_EXIT_ABOVE_VENUE_MAXIMUM,
                    details={"exceeded_bound": bound_reason, **bound_details},
                )
                return None

            result.data["executed_quote_reduction"] = format(exposure, "f")
            result.data["unreduced_quote_remainder"] = "0"
            return held

        try:
            with localcontext() as context:
                context.rounding = ROUND_DOWN
                quotient = reduction / basis
            base_quantity = floor_to_step(quotient, instrument_rules.quantity_step)
        except (InvalidOperation, ZeroDivisionError, ValueError):
            base_quantity = None

        if base_quantity is None or base_quantity <= 0 or base_quantity >= held:
            self._mark_result_failure(
                result=result,
                message="Approved reduction is smaller than one executable base quantum",
                error_code="REDUCTION_BELOW_EXECUTABLE_QUANTUM",
                details={
                    "approved_quote_reduction": format(reduction, "f"),
                    "risk_basis_price": format(basis, "f"),
                },
            )
            return None

        # Block 5D SELL-venue-minimums owner ruling: the floored quantity
        # actually being submitted must itself clear the venue minimums -
        # the same gate `risk_check` already applies to a new-risk BUY - and
        # the durable quantity this reduction would leave behind must remain
        # itself either exactly zero or venue-sellable. Neither side is ever
        # rounded up, and a reduction that would strand an unsellable
        # remainder is refused rather than silently promoted to a full
        # close.
        submitted_notional = base_quantity * basis

        if base_quantity < instrument_rules.min_quantity:
            self._mark_result_failure(
                result=result,
                message="Reduction quantity is below the venue minimum quantity",
                error_code="QUANTITY_BELOW_VENUE_MINIMUM",
                details={
                    "floored_base_quantity": format(base_quantity, "f"),
                    "min_quantity": format(instrument_rules.min_quantity, "f"),
                },
            )
            return None

        if submitted_notional < instrument_rules.min_notional:
            self._mark_result_failure(
                result=result,
                message="Reduction notional is below the venue minimum notional",
                error_code="NOTIONAL_BELOW_VENUE_MINIMUM",
                details={
                    "floored_quote_notional": format(submitted_notional, "f"),
                    "min_notional": format(instrument_rules.min_notional, "f"),
                },
            )
            return None

        # Block 6B: the same upper bounds the BUY admission gate applies, on
        # the reduction actually being submitted. A partial exit above the
        # venue maximum is refused rather than clipped down to it: the size is
        # the risk-approved reduction, and this path prices it, never revises
        # it.
        reduction_bound = instrument_rules.upper_bound_violation(
            base_quantity=base_quantity,
            quote_notional=submitted_notional,
            order_type=request.order_type,
        )

        if reduction_bound is not None:
            bound_reason, bound_details = reduction_bound
            self._mark_result_failure(
                result=result,
                message="Reduction is above the venue maximum quantity or notional",
                error_code=bound_reason,
                details=bound_details,
            )
            return None

        remainder_base = held - base_quantity
        remainder_notional = remainder_base * basis

        if remainder_base > 0 and (
            remainder_base < instrument_rules.min_quantity
            or remainder_notional < instrument_rules.min_notional
        ):
            self._mark_result_failure(
                result=result,
                message=(
                    "Partial reduction would strand a durable remainder "
                    "below the venue minimum quantity or notional"
                ),
                error_code="REDUCTION_STRANDS_SUBMINIMUM_REMAINDER",
                details={
                    "remainder_base_quantity": format(remainder_base, "f"),
                    "remainder_quote_notional": format(remainder_notional, "f"),
                    "min_quantity": format(instrument_rules.min_quantity, "f"),
                    "min_notional": format(instrument_rules.min_notional, "f"),
                },
            )
            return None

        result.data["executed_quote_reduction"] = format(submitted_notional, "f")
        result.data["unreduced_quote_remainder"] = format(
            reduction - submitted_notional, "f"
        )

        return base_quantity

    def _execute_paper_sell(
        self,
        *,
        request: ExecutionRequest,
        result: ExecutionResult,
    ) -> None:
        """Coordinate a paper SELL and the authoritative position reduction.

        The size sold is the risk-approved reduction, converted to base units
        at the durable risk basis - never the whole holding. A reduction
        smaller than the position reduces it; a reduction equal to it closes
        it; a reduction larger than it fails closed. The approved size is
        never revised here, only priced.
        """

        result.data = result.data or {}
        partial_reduction = False

        if self.portfolio_foundation is not None:
            position = self.portfolio_foundation.snapshot()["positions"].get(request.symbol)
            if position is None:
                self._mark_result_failure(
                    result=result,
                    message="Durable LONG position was not found",
                    error_code="POSITION_NOT_FOUND",
                )
                return

            base_quantity = self._resolve_reduction_quantity(
                request=request,
                result=result,
                position=position,
            )

            if base_quantity is None:
                return

            partial_reduction = base_quantity != Decimal(str(position["base_quantity"]))
            result.data["partial_reduction"] = partial_reduction

            result.position_id = position["position_id"]
            result.filled_base_quantity = base_quantity

        # Fill-evidence seam, mirroring the BUY path: no paper execution
        # adapter is configured, so nothing is reported and nothing is
        # mutated here. A partial reduction still skips the seam entirely,
        # because a full-exit-only component cannot describe one.
        # PaperTrader itself is projected from the durable authority after
        # the commit instead (see _mirror_paper_book).
        paper_trade = (
            None
            if partial_reduction
            else self._paper_close_trade(
                request
            )
        )

        if partial_reduction:
            result.data["paper_book_mutated"] = False

        if paper_trade is not None:
            result.data["paper_trade"] = paper_trade

            self._hydrate_result_from_component(
                result=result,
                payload=paper_trade,
            )

        # Proceeds are priced after hydration, so the fill price the paper
        # book reported - not the price this manager assumed - is the one the
        # notional is derived from. The quantity sold is already fixed and is
        # never revised here: only the price of that quantity is.
        if result.filled_base_quantity is not None:
            try:
                execution_price = Decimal(str(result.filled_price))
                if execution_price <= 0:
                    raise ValueError("non-positive paper fill price")
                result.filled_quote_notional = (
                    result.filled_base_quantity * execution_price
                )
                result.filled_amount = float(result.filled_quote_notional)
            except (InvalidOperation, ValueError, TypeError):
                self._mark_result_failure(
                    result=result,
                    message="Paper fill quantity semantics are invalid",
                    error_code="INVALID_FINANCIAL_QUANTITY",
                )
                return

            # Block 5E: the same quote-asset-only fee gate `_execute_paper_buy`
            # applies. Admission already required an instrument rule to
            # exist for this symbol, so re-fetching it here can only miss if
            # it disappeared between admission and execution - the same
            # defense-in-depth case `_execute_paper_buy` guards against.
            instrument_rules = (
                self.instrument_rules.get(request.symbol)
                if self.instrument_rules is not None
                else None
            )

            if instrument_rules is None:
                self._mark_result_failure(
                    result=result,
                    message="No instrument rules for symbol",
                    error_code="INSTRUMENT_RULES_UNAVAILABLE",
                )
                return

            # Registry v5.23: paper exit fee on the exact exit notional.
            ExecutionManager._apply_paper_fee_if_unreported(
                result=result,
                fee_amount=result.filled_quote_notional * self.paper_fee_rate,
                quote_asset=instrument_rules.quote_asset,
            )

            try:
                normalized_fee = FeeNormalizer.normalize(
                    fee_amount=result.fee_amount,
                    fee_currency=result.fee_currency,
                    instrument=instrument_rules,
                )
            except FeeRejected as exc:
                self._mark_result_failure(
                    result=result,
                    message="Component-reported fee cannot be settled: only this venue's quote-asset fee is supported",
                    error_code=exc.reason.value,
                    details={
                        "fee_amount": (
                            format(exc.fee_amount, "f") if exc.fee_amount is not None else None
                        ),
                        "fee_currency": exc.fee_currency,
                        "quote_asset": instrument_rules.quote_asset,
                        "base_asset": instrument_rules.base_asset,
                    },
                )
                return

            result.fee_amount = normalized_fee.quote_amount
            result.fee_currency = normalized_fee.currency

        close_metadata = {
            **self._normalize_metadata(
                request.metadata
            ),
            "request_id": request.request_id,
            "execution_id": result.execution_id,
            "execution_mode": self.MODE_PAPER,
            "execution_timestamp": self._serialize_timestamp(
                request.timestamp
            ),
            "source": request.source,
            "reduce_only": request.reduce_only,
        }

        if self.portfolio_foundation is not None:
            position = None
        else:
            # Side-effect boundary for the foundation-less configuration,
            # matching the BUY path: PositionController is mutated here and
            # no durable finalization follows to carry the marker instead.
            self._mark_execution_side_effect(request.request_id)

            position = self._position_close(
                request=request,
                metadata=close_metadata,
            )

        if position is not None:
            result.data["position"] = position

            if isinstance(
                position,
                Mapping,
            ):
                closed_position = position.get(
                    "position",
                    position,
                )

                if isinstance(
                    closed_position,
                    Mapping,
                ):
                    result.position_id = (
                        result.position_id
                        or self._extract_nested(
                            closed_position,
                            "position_id",
                            "id",
                        )
                    )

                    result.pnl = self._to_float(
                        closed_position.get(
                            "realized_pnl_amount",
                            closed_position.get(
                                "pnl",
                                result.pnl,
                            ),
                        )
                    )

                    result.filled_amount = self._to_float(
                        closed_position.get(
                            "amount",
                            result.filled_amount,
                        )
                    )

                if not bool(
                    position.get(
                        "success",
                        True,
                    )
                ):
                    self._mark_result_failure(
                        result=result,
                        message=str(
                            position.get(
                                "reason",
                                "Position close failed",
                            )
                        ),
                        error_code="POSITION_CLOSE_REJECTED",
                        details=dict(
                            position
                        ),
                    )

        self.publish(
            "TRADE_CLOSED",
            result.to_dict(),
        )

    def _paper_close_trade(
        self,
        request: ExecutionRequest,
    ) -> Any | None:
        """Report a paper SELL fill from an execution adapter, if one exists.

        The SELL counterpart of ``_paper_open_trade``, with the same
        contract: fill evidence only, never PaperTrader, which is
        projected from the durable authority after the commit instead.
        """

        return None

    def _position_close(
        self,
        *,
        request: ExecutionRequest,
        metadata: dict[str, Any],
    ) -> Any | None:
        """
        Close PositionController state using the execution price.
        """

        if self.position_controller is None:
            return None

        close_position = getattr(
            self.position_controller,
            "close_position",
            None,
        )

        if not callable(
            close_position
        ):
            return None

        try:
            return close_position(
                symbol=request.symbol,
                price=request.price,
                metadata=metadata,
                request_id=request.request_id,
                execution_id=metadata["execution_id"],
                mode=self.MODE_PAPER,
                timestamp=request.timestamp,
                source=request.source,
            )

        except TypeError:
            try:
                return close_position(
                    request.symbol,
                    request.price,
                )

            except TypeError:
                try:
                    return close_position(
                        request.symbol
                    )

                except Exception as exc:
                    self._record_error(
                        phase="position_close",
                        error=exc,
                        request=request,
                    )
                    logger.exception(
                        "PositionController close failed"
                    )
                    return {
                        "success": False,
                        "status": "FAILED",
                        "reason": str(
                            exc
                        ),
                    }

            except Exception as exc:
                self._record_error(
                    phase="position_close",
                    error=exc,
                    request=request,
                )
                logger.exception(
                    "PositionController close failed"
                )
                return {
                    "success": False,
                    "status": "FAILED",
                    "reason": str(
                        exc
                    ),
                }

        except Exception as exc:
            self._record_error(
                phase="position_close",
                error=exc,
                request=request,
            )
            logger.exception(
                "PositionController close failed"
            )
            return {
                "success": False,
                "status": "FAILED",
                "reason": str(
                    exc
                ),
            }

    # =========================================================
    # LIVE EXECUTION
    # =========================================================

    def _block_live_dispatch(
        self,
        request: ExecutionRequest,
        *,
        status: str,
        message: str,
        error_code: str | None,
        data: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Refuse one live dispatch at a venue-readiness gate.

        The shared shape of every pre-adapter refusal: counted as blocked,
        published on the same channel the other live denials use, and carrying
        a status outside ``SUCCESS_STATUSES`` so the terminal classifier
        resolves it as not-committed with no durable consequence.
        """
        with self._lock:
            self.stats["live_blocked"] += 1

        blocked = ExecutionResult(
            success=False,
            status=status,
            message=message,
            symbol=request.symbol,
            action=request.action,
            mode=self.MODE_LIVE,
            data={"request_id": request.request_id, **(data or {})},
            metadata=self._normalize_metadata(
                request.metadata
            ),
            timestamp=request.timestamp,
            error_code=error_code,
            requested_price=request.price,
            requested_amount=request.amount,
        )

        payload = blocked.to_dict()

        self.publish(
            "LIVE_EXECUTION_BLOCKED",
            payload,
        )

        return payload

    def live_execute(
        self,
        request: ExecutionRequest,
    ) -> dict[str, Any]:
        """
        Deny live execution unless explicitly enabled.

        Even when enabled, a concrete live execution adapter is required.

        Block 6A adds one further denial ahead of the adapter step, for a
        runtime that came online holding live authority: venue rules that
        were FRESH at startup can age past the threshold during a long run,
        and a dispatch is where that must be caught. The re-check is scoped
        to ``_live_authorized_at_start`` deliberately - a runtime that had
        its live flag flipped after startup never passed the live startup
        gate at all and is already denied below for want of an approved
        adapter, so nothing reaches a venue either way.

        Block 6B adds the second half of the same pre-adapter check: the
        venue's upper bounds must be modelled for the symbol being
        dispatched. Both refusals happen before the adapter step, which is
        the last place either can be caught.
        """

        if not self._has_risk_admission(request):
            return self.reject(reason="CANONICAL_RISK_ADMISSION_MISSING", request=request)
        if not self.live_execution_enabled:
            with self._lock:
                self.stats["live_blocked"] += 1

            logger.warning(
                "LIVE execution requested but disabled"
            )

            result = ExecutionResult(
                success=False,
                status="LIVE_DISABLED",
                message=(
                    "Live trading is disabled by the "
                    "execution safety policy"
                ),
                symbol=request.symbol,
                action=request.action,
                mode=self.MODE_LIVE,
                data={
                    "request_id": request.request_id,
                    "confidence": request.confidence,
                },
                metadata=self._normalize_metadata(
                    request.metadata
                ),
                timestamp=request.timestamp,
                error_code="LIVE_EXECUTION_DISABLED",
                requested_price=request.price,
                requested_amount=request.amount,
            )

            payload = result.to_dict()

            self.publish(
                "LIVE_EXECUTION_BLOCKED",
                payload,
            )

            return payload

        if self._live_authorized_at_start:
            freshness = self.instrument_rule_freshness.evaluate_gate(
                self.instrument_rules,
                live_authorized=True,
            )

            if not freshness.allowed:
                logger.error(
                    "LIVE execution blocked: venue rules %s "
                    "age_seconds=%s maximum_age_seconds=%s",
                    freshness.report.status.value,
                    freshness.report.age_seconds,
                    freshness.report.maximum_age_seconds,
                )

                return self._block_live_dispatch(
                    request,
                    status="VENUE_RULES_NOT_FRESH",
                    message=(
                        "Live execution requires fresh venue instrument "
                        "rules"
                    ),
                    error_code=freshness.reason,
                    data={"venue_rules": freshness.report.to_dict()},
                )

            # Block 6B: the venue's upper bounds must be modelled for the
            # symbol being dispatched, checked here - the last point before
            # the adapter seam - and not only at startup, so a ruleset
            # replaced in a running process cannot open an unbounded live
            # path. The numeric bounds themselves were already enforced at
            # admission, which no request can reach this line without having
            # passed.
            dispatch_rules = (
                self.instrument_rules.get(request.symbol)
                if self.instrument_rules is not None
                else None
            )

            if dispatch_rules is None or not dispatch_rules.has_complete_venue_bounds:
                logger.error(
                    "LIVE execution blocked: venue upper bounds unmodelled "
                    "symbol=%s",
                    request.symbol,
                )

                return self._block_live_dispatch(
                    request,
                    status=VENUE_UPPER_BOUNDS_UNAVAILABLE,
                    message=(
                        "Live execution requires modelled venue upper bounds"
                    ),
                    error_code=VENUE_UPPER_BOUNDS_UNAVAILABLE,
                    data={"symbol": request.symbol},
                )

        with self._lock:
            self.stats["live_blocked"] += 1

        result = ExecutionResult(
            success=False,
            status="LIVE_NOT_IMPLEMENTED",
            message=(
                "Live execution was enabled, but no approved "
                "live execution adapter is configured"
            ),
            symbol=request.symbol,
            action=request.action,
            mode=self.MODE_LIVE,
            data={
                "request_id": request.request_id,
            },
            metadata=self._normalize_metadata(
                request.metadata
            ),
            timestamp=request.timestamp,
            error_code="LIVE_ADAPTER_NOT_IMPLEMENTED",
            requested_price=request.price,
            requested_amount=request.amount,
        )

        payload = result.to_dict()

        self.publish(
            "LIVE_EXECUTION_BLOCKED",
            payload,
        )

        return payload

    # =========================================================
    # RESULT MANAGEMENT
    # =========================================================

    def _record_result(
        self,
        result: dict[str, Any],
    ) -> None:
        """
        Update counters and bounded execution history.
        """

        status = str(
            result.get(
                "status",
                "UNKNOWN",
            )
        ).upper()

        success = bool(
            result.get(
                "success",
                status in self.SUCCESS_STATUSES,
            )
        )

        with self._lock:
            if success and status not in self.FAILURE_STATUSES:
                self.stats["executed"] += 1

            elif status in self.FAILURE_STATUSES:
                self.stats["failed"] += 1

            self._append_bounded(
                self.history,
                result,
                self.MAX_HISTORY,
            )

    def _paper_buy_fee(self, allocation: Decimal) -> Decimal:
        """The paper BUY fee for an allocation: ceil8(A*r/(1+r)) (registry v5.23)."""

        rate = self.paper_fee_rate
        if rate == 0:
            return Decimal("0")
        return (Decimal(allocation) * rate / (1 + rate)).quantize(PAPER_FEE_QUANTUM, rounding=ROUND_UP)

    @staticmethod
    def _apply_paper_fee_if_unreported(*, result: Any, fee_amount: Decimal, quote_asset: str) -> None:
        """Charge the paper fee unless an executing component reported one.

        Rounded up to 8 decimals so the paper fee never under-charges. Only
        the paper paths call this; the fee is in the venue quote asset, the
        one currency FeeNormalizer settles.
        """

        reported = result.fee_amount
        if reported is not None and Decimal(str(reported)) != 0:
            return
        if fee_amount == 0:
            return
        result.fee_amount = Decimal(fee_amount).quantize(PAPER_FEE_QUANTUM, rounding=ROUND_UP)
        result.fee = float(result.fee_amount)
        result.fee_currency = quote_asset

    @staticmethod
    def _hydrate_result_from_component(
        *,
        result: ExecutionResult,
        payload: Any,
    ) -> None:
        """
        Copy common execution fields from a dependency response.
        """

        if not isinstance(
            payload,
            Mapping,
        ):
            return

        result.order_id = (
            result.order_id
            or ExecutionManager._extract_nested(
                payload,
                "order_id",
            )
        )

        result.trade_id = (
            result.trade_id
            or ExecutionManager._extract_nested(
                payload,
                "trade_id",
                "execution_id",
            )
        )

        result.position_id = (
            result.position_id
            or ExecutionManager._extract_nested(
                payload,
                "position_id",
            )
        )

        filled_price = ExecutionManager._extract_numeric_value(
            payload,
            keys=(
                "filled_price",
                "price",
                "execution_price",
            ),
        )

        if filled_price > 0:
            result.filled_price = filled_price

        # `filled_amount` and `allocation` are not hydrated at all. Their unit
        # is not declared by the payload, so a component reporting a base
        # quantity under either key would have been copied straight onto a
        # field the paper paths otherwise carry quote capital in. The canonical
        # Decimal fields - filled_base_quantity and filled_quote_notional - are
        # owned by the execution paths that derive them from the risk-approved
        # allocation, and they remain the only financially material quantities.

        # Block 5E exact fee ingress: a component may report `fee_amount`
        # directly as a Decimal or decimal string, taken verbatim and never
        # routed through the lossy float `fee` mirror below. Only when the
        # key itself is absent does hydration fall back to the historical
        # `fee`/`commission` float keys - a present-but-invalid `fee_amount`
        # (negative, non-finite, or unparseable) still comes back from
        # `_extract_exact_decimal` as a `Decimal`, so it is carried through
        # here and left for the `FeeNormalizer` gate below to refuse; it
        # never falls back to `fee`/`commission` (final-review MEDIUM #1).
        exact_fee = ExecutionManager._extract_exact_decimal(
            payload,
            keys=("fee_amount",),
        )

        if exact_fee is not None:
            result.fee_amount = exact_fee
            result.fee = float(exact_fee) if exact_fee.is_finite() else 0.0

            # The currency comes from the component that charged the fee,
            # and from nowhere else. `InstrumentRules.base_asset`/
            # `quote_asset` (Block 5D) let `FeeNormalizer` (Block 5E)
            # classify a stated currency against the venue; a fee whose
            # currency nobody stated is still rejected rather than assumed
            # to be quote currency.
            result.fee_currency = (
                result.fee_currency
                or ExecutionManager._extract_nested(
                    payload,
                    "fee_currency",
                    "commission_asset",
                )
            )
        else:
            fee = ExecutionManager._extract_numeric_value(
                payload,
                keys=(
                    "fee",
                    "commission",
                ),
            )

            if fee != 0:
                result.fee = fee
                result.fee_amount = Decimal(str(fee))

                result.fee_currency = (
                    result.fee_currency
                    or ExecutionManager._extract_nested(
                        payload,
                        "fee_currency",
                        "commission_asset",
                    )
                )

        pnl = ExecutionManager._extract_numeric_value(
            payload,
            keys=(
                "pnl",
                "realized_pnl",
                "realized_pnl_amount",
            ),
        )

        if pnl != 0:
            result.pnl = pnl

    @staticmethod
    def _mark_result_failure(
        *,
        result: ExecutionResult,
        message: str,
        error_code: str,
        details: dict[str, Any] | None = None,
    ) -> None:
        """
        Mutate ExecutionResult into a structured failure.
        """

        result.success = False
        result.status = "FAILED"
        result.message = message
        result.error_code = error_code
        result.error_details = details or {}

    def _failure_result(
        self,
        *,
        request: ExecutionRequest | None,
        status: str,
        message: str,
        error_code: str,
        error: Exception | None = None,
    ) -> dict[str, Any]:
        """
        Build a canonical ExecutionResult failure payload.
        """

        result = ExecutionResult(
            success=False,
            status=status,
            message=message,
            symbol=(
                request.symbol
                if request is not None
                else ""
            ),
            action=(
                request.action
                if request is not None
                else ""
            ),
            mode=self.mode,
            data={
                "request_id": (
                    request.request_id
                    if request is not None
                    else None
                ),
            },
            metadata=(
                self._normalize_metadata(
                    request.metadata
                )
                if request is not None
                else {}
            ),
            timestamp=(
                request.timestamp
                if request is not None
                else self._utc_now()
            ),
            error_code=error_code,
            error_details={
                "type": (
                    type(
                        error
                    ).__name__
                    if error is not None
                    else None
                ),
                "error": (
                    str(
                        error
                    )
                    if error is not None
                    else None
                ),
            },
            requested_price=(
                request.price
                if request is not None
                else 0.0
            ),
            requested_amount=(
                request.amount
                if request is not None
                else 0.0
            ),
        )

        return result.to_dict()

    # =========================================================
    # REJECTION
    # =========================================================

    def reject(
        self,
        reason: str,
        request: ExecutionRequest | None = None,
        details: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """
        Return, retain, and publish a structured rejection.
        """

        result: dict[str, Any] = {
            "success": False,
            "status": "REJECTED",
            "reason": reason,
            "message": reason,
            "timestamp": self._utc_now(),
            "mode": self.mode,
        }

        if request is not None:
            result.update(
                {
                    "request_id": request.request_id,
                    "symbol": request.symbol,
                    "action": request.action,
                    "price": request.price,
                    "amount": request.amount,
                    "confidence": request.confidence,
                    "strategy": request.strategy,
                    "risk": request.risk,
                }
            )

        if details:
            result["details"] = details

        with self._lock:
            self.stats["rejected"] += 1

            self._append_bounded(
                self.rejections,
                result,
                self.MAX_REJECTIONS,
            )

        logger.warning(
            "[EXECUTION REJECTED] reason=%s symbol=%s action=%s",
            reason,
            (
                request.symbol
                if request is not None
                else "-"
            ),
            (
                request.action
                if request is not None
                else "-"
            ),
        )

        self.publish(
            "EXECUTION_REJECTED",
            result,
        )

        return result

    # =========================================================
    # EVENT BUS
    # =========================================================

    def publish(
        self,
        event_name: str,
        payload: Any,
    ) -> bool:
        """Publish a sanitized event through current and legacy contracts."""

        if self.event_bus is None:
            return False

        publish_method = getattr(
            self.event_bus,
            "publish",
            None,
        )

        if not callable(
            publish_method
        ):
            return False

        sanitized_payload = sanitize_sensitive_data(
            payload
        )

        event_payload = {
            "event": event_name,
            "payload": sanitized_payload,
            "timestamp": self._utc_now(),
            "source": self.NAME,
            "version": self.VERSION,
        }

        try:
            publish_method(
                event_payload
            )
            return True

        except TypeError:
            try:
                publish_method(
                    event_name,
                    sanitized_payload,
                )
                return True

            except Exception as exc:
                self._record_error(
                    phase="event_publish_legacy",
                    error=exc,
                )
                logger.exception(
                    "Legacy EventBus publish failed"
                )
                return False

        except Exception as exc:
            self._record_error(
                phase="event_publish",
                error=exc,
            )
            logger.exception(
                "EventBus publish failed"
            )
            return False

    # =========================================================
    # NORMALIZATION
    # =========================================================

    @staticmethod
    def _decision_to_dict(
        decision: Any,
    ) -> dict[str, Any]:
        """
        Convert supported decision representations to a dictionary.
        """

        if isinstance(
            decision,
            Mapping,
        ):
            return dict(
                decision
            )

        to_dict = getattr(
            decision,
            "to_dict",
            None,
        )

        if callable(
            to_dict
        ):
            result = to_dict()

            if isinstance(
                result,
                Mapping,
            ):
                return dict(
                    result
                )

        if hasattr(
            decision,
            "__dict__",
        ):
            return dict(
                vars(
                    decision
                )
            )

        raise TypeError(
            "Unsupported execution decision type: "
            f"{type(decision).__name__}"
        )

    @staticmethod
    def _normalize_symbol(
        value: Any,
    ) -> str:
        return str(
            value
        ).strip().upper()

    @classmethod
    def _normalize_action(
        cls,
        value: Any,
    ) -> str:
        """
        Normalize action strings and Enum values.
        """

        if isinstance(
            value,
            Enum,
        ):
            value = (
                value.value
                if isinstance(
                    value.value,
                    str,
                )
                else value.name
            )

        action = str(
            value
        ).strip().upper()

        if "." in action:
            action = action.rsplit(
                ".",
                maxsplit=1,
            )[-1]

        aliases = {
            "LONG": "BUY",
            "OPEN_LONG": "BUY",
            "CLOSE_SHORT": "BUY",
            "SHORT": "SELL",
            "OPEN_SHORT": "SELL",
            "CLOSE_LONG": "SELL",
            "WAIT": "HOLD",
            "NEUTRAL": "HOLD",
        }

        return aliases.get(
            action,
            action,
        )

    @classmethod
    def _normalize_mode(
        cls,
        value: Any,
    ) -> str:
        mode = str(
            value
        ).strip().upper()

        if mode not in {
            cls.MODE_PAPER,
            cls.MODE_LIVE,
        }:
            return cls.MODE_PAPER

        return mode

    @staticmethod
    def _normalize_confidence(
        value: Any,
    ) -> float:
        """
        Normalize confidence to the percentage range 0..100.
        """

        if isinstance(
            value,
            str,
        ):
            value = value.strip().replace(
                "%",
                "",
            )

        confidence = ExecutionManager._to_float(
            value
        )

        if 0 <= confidence <= 1:
            confidence *= 100

        return round(
            ExecutionManager._clamp(
                confidence,
                minimum=0.0,
                maximum=100.0,
            ),
            2,
        )

    @staticmethod
    def _normalize_risk_level(
        value: Any,
    ) -> str:
        """
        Normalize a decision risk value onto the canonical vocabulary.

        Delegates to the same normalizer ``ExecutionRequest`` applies, so a
        request built here and a request constructed directly cannot carry
        different risk semantics.  Absence still defaults to ``MEDIUM``; a
        present but unsupported value becomes ``UNKNOWN`` and is never
        promoted into an executable bucket.  Admission is decided later, by
        ``RiskEngine.evaluate``.
        """

        return normalize_risk(
            value
        )

    @staticmethod
    def _normalize_metadata(
        value: Any,
    ) -> dict[str, Any]:
        if isinstance(
            value,
            Mapping,
        ):
            return dict(
                value
            )

        if value is None:
            return {}

        return {
            "original_metadata": repr(
                value
            )
        }

    @staticmethod
    def _extract_numeric_value(
        value: Any,
        *,
        keys: tuple[str, ...],
    ) -> float:
        if isinstance(
            value,
            Mapping,
        ):
            for key in keys:
                if key in value:
                    return ExecutionManager._to_float(
                        value[key]
                    )

            data = value.get(
                "data"
            )

            if isinstance(
                data,
                Mapping,
            ):
                for key in keys:
                    if key in data:
                        return ExecutionManager._to_float(
                            data[key]
                        )

            return 0.0

        return ExecutionManager._to_float(
            value
        )

    @staticmethod
    def _extract_exact_decimal(
        value: Any,
        *,
        keys: tuple[str, ...],
    ) -> Decimal | None:
        """Read an exact ``Decimal`` straight from a payload, never through float.

        Mirrors ``_extract_numeric_value``'s key/``data``-fallback lookup,
        but for a field a component may report as an exact ``Decimal`` or
        decimal string (Block 5E ``fee_amount`` ingress) - so an exact
        component-reported figure never has to round-trip through a float
        mirror to become authoritative. Returns ``None`` only when the key
        itself is absent (or explicitly ``None``) - that is the one case
        the caller is allowed to fall back to the legacy ``fee``/
        ``commission`` mirror for.

        A key that *is* present but cannot stand as an authoritative fee -
        negative, non-finite, or not parseable as a ``Decimal`` at all - is
        never silently discarded into that same ``None``/fallback path
        (final-review MEDIUM #1): it comes back as a ``Decimal`` regardless,
        valid or not, so the caller's existing ``FeeNormalizer`` gate is the
        one place that decides whether it may settle. A value ``Decimal()``
        itself cannot represent - unparseable garbage - is poisoned as
        ``NaN``, which that same gate already refuses via its
        ``is_finite()`` check, so the failure reason a caller sees is
        identical whether the fee was unparseable, negative, or already
        non-finite.
        """
        if not isinstance(value, Mapping):
            return None

        candidate = None
        for key in keys:
            if key in value:
                candidate = value[key]
                break

        if candidate is None:
            data = value.get("data")
            if isinstance(data, Mapping):
                for key in keys:
                    if key in data:
                        candidate = data[key]
                        break

        if candidate is None:
            return None

        try:
            return Decimal(str(candidate))
        except (InvalidOperation, ValueError, TypeError):
            return Decimal("NaN")

    @staticmethod
    def _extract_nested(
        value: Mapping[str, Any],
        *keys: str,
    ) -> str | None:
        for key in keys:
            candidate = value.get(
                key
            )

            if candidate not in {
                None,
                "",
            }:
                return str(
                    candidate
                )

        nested = value.get(
            "position"
        )

        if isinstance(
            nested,
            Mapping,
        ):
            for key in keys:
                candidate = nested.get(
                    key
                )

                if candidate not in {
                    None,
                    "",
                }:
                    return str(
                        candidate
                    )

        return None

    @staticmethod
    def _to_float(
        value: Any,
    ) -> float:
        try:
            return float(
                value
            )

        except (
            TypeError,
            ValueError,
        ):
            return 0.0

    @staticmethod
    def _optional_float(
        value: Any,
    ) -> float | None:
        if value in {
            None,
            "",
        }:
            return None

        try:
            return float(
                value
            )

        except (
            TypeError,
            ValueError,
        ):
            return None

    @staticmethod
    def _clamp(
        value: float,
        *,
        minimum: float,
        maximum: float,
    ) -> float:
        return max(
            minimum,
            min(
                value,
                maximum,
            ),
        )

    @staticmethod
    def _serialize_timestamp(
        value: Any,
    ) -> str:
        if isinstance(
            value,
            datetime,
        ):
            return value.isoformat()

        return str(
            value
        )

    @staticmethod
    def _utc_now() -> str:
        return datetime.now(
            UTC
        ).isoformat()

    # =========================================================
    # ERROR MANAGEMENT
    # =========================================================

    def _record_error(
        self,
        *,
        phase: str,
        error: Exception,
        request: ExecutionRequest | None = None,
    ) -> None:
        record = {
            "timestamp": self._utc_now(),
            "phase": phase,
            "type": type(
                error
            ).__name__,
            "error": str(
                error
            ),
            "request_id": (
                request.request_id
                if request is not None
                else None
            ),
            "symbol": (
                request.symbol
                if request is not None
                else None
            ),
            "action": (
                request.action
                if request is not None
                else None
            ),
        }

        with self._lock:
            self._append_bounded(
                self.errors,
                record,
                self.MAX_ERRORS,
            )

    @staticmethod
    def _append_bounded(
        collection: list[Any],
        value: Any,
        maximum: int,
    ) -> None:
        collection.append(
            value
        )

        if len(
            collection
        ) > maximum:
            del collection[
                :-maximum
            ]

    @staticmethod
    def _new_stats() -> dict[str, int]:
        return {
            "received": 0,
            "validated": 0,
            "executed": 0,
            "rejected": 0,
            "failed": 0,
            "paper_orders": 0,
            "live_blocked": 0,
            "requests_claimed": 0,
            "requests_completed": 0,
            "requests_released": 0,
            "duplicate_requests": 0,
            "duplicate_requests_pending": 0,
            "duplicate_requests_completed": 0,
            "cached_results_returned": 0,
            "persistent_records_loaded": 0,
            "persistent_records_saved": 0,
            "persistent_save_failures": 0,
            "audit_events_written": 0,
            "audit_write_failures": 0,
        }

    # =========================================================
    # HISTORY / DIAGNOSTICS
    # =========================================================

    def get_history(
        self,
    ) -> list[dict[str, Any]]:
        with self._lock:
            return [
                dict(
                    item
                )
                for item in self.history
            ]

    def get_rejections(
        self,
    ) -> list[dict[str, Any]]:
        with self._lock:
            return [
                dict(
                    item
                )
                for item in self.rejections
            ]

    def get_errors(
        self,
    ) -> list[dict[str, Any]]:
        with self._lock:
            return [
                dict(
                    item
                )
                for item in self.errors
            ]


    # =========================================================
    # AUDIT
    # =========================================================

    def _claim_request(
        self,
        request: ExecutionRequest,
    ) -> dict[str, Any] | None:
        """
        Atomically claim a request_id.

        Returns None when the caller owns the request.
        Returns a structured duplicate response otherwise.
        """

        request_id = str(
            request.request_id
        ).strip()

        with self._lock:
            if request_id in self.pending_request_ids:
                self.stats[
                    "duplicate_requests"
                ] += 1

                self.stats[
                    "duplicate_requests_pending"
                ] += 1

                logger.warning(
                    "[DUPLICATE REQUEST] pending "
                    "request_id=%s symbol=%s action=%s",
                    request_id,
                    request.symbol,
                    request.action,
                )

                return {
                    "success": False,
                    "status": "SKIPPED",
                    "reason": (
                        "DUPLICATE_REQUEST_PENDING"
                    ),
                    "message": (
                        "Request is already being processed"
                    ),
                    "request_id": request_id,
                    "symbol": request.symbol,
                    "action": request.action,
                    "mode": self.mode,
                    "timestamp": self._utc_now(),
                }

            cached_result = (
                self.completed_request_results.get(
                    request_id
                )
            )

            if cached_result is not None:
                self.stats[
                    "duplicate_requests"
                ] += 1

                self.stats[
                    "duplicate_requests_completed"
                ] += 1

                self.stats[
                    "cached_results_returned"
                ] += 1

                logger.warning(
                    "[DUPLICATE REQUEST] completed "
                    "request_id=%s symbol=%s action=%s",
                    request_id,
                    request.symbol,
                    request.action,
                )

                duplicate_response = dict(
                    cached_result
                )

                duplicate_response[
                    "idempotency"
                ] = {
                    "duplicate": True,
                    "cache_hit": True,
                    "original_status": (
                        cached_result.get(
                            "status",
                            "UNKNOWN",
                        )
                    ),
                }

                duplicate_response[
                    "duplicate_reason"
                ] = (
                    "DUPLICATE_REQUEST_COMPLETED"
                )

                return duplicate_response

            self.pending_request_ids.add(
                request_id
            )

            self.stats[
                "requests_claimed"
            ] += 1

            return None

    def _complete_request(
        self,
        *,
        request_id: str,
        result: dict[str, Any],
    ) -> bool:
        """
        Persist a terminal result before exposing it as completed.

        The in-memory completed cache is updated only after the
        persistent idempotency record succeeds.
        """

        canonical_id = str(
            request_id
        ).strip()

        if not canonical_id:
            return False

        cached_result = dict(
            result
        )

        cached_result.setdefault(
            "request_id",
            canonical_id,
        )

        persisted = self.idempotency_store.record(
            canonical_id,
            cached_result,
            save=True,
        )

        with self._lock:
            self.pending_request_ids.discard(
                canonical_id
            )

            if not persisted:
                self.stats[
                    "persistent_save_failures"
                ] += 1

                self.completed_request_results.pop(
                    canonical_id,
                    None,
                )

                return False

            self.completed_request_results[
                canonical_id
            ] = cached_result

            self.stats[
                "requests_completed"
            ] += 1

            self.stats[
                "persistent_records_saved"
            ] += 1

        return True

    def _release_request(
        self,
        request_id: str,
    ) -> None:
        """
        Release a claimed request so it may be retried.
        """

        canonical_id = str(
            request_id
        ).strip()

        if not canonical_id:
            return

        with self._lock:
            existed = (
                canonical_id
                in self.pending_request_ids
            )

            self.pending_request_ids.discard(
                canonical_id
            )

            if existed:
                self.stats[
                    "requests_released"
                ] += 1

    # =========================================================
    # REQUEST BUILDER
    # =========================================================

    def _classify_audit_stage(
        self,
        event_type: str,
    ) -> str:
        """
        Classify an execution audit event by lifecycle stage.

        Classification is intentionally independent from the
        audit storage implementation. It prepares Atlas for
        stage-aware failure policy without changing the current
        execution flow.
        """

        normalized_event_type = str(
            event_type
        ).strip().upper()

        pre_execution_events = {
            "EXECUTION_REQUEST_RECEIVED",
            "EXECUTION_REQUEST_VALIDATED",
            "RISK_APPROVED",
        }

        post_execution_events = {
            "EXECUTION_COMPLETED",
            "EXECUTION_FAILED",
        }

        terminal_decision_events = {
            "EXECUTION_REQUEST_REJECTED",
            "RISK_REJECTED",
        }

        observational_events = {
            "DUPLICATE_REQUEST_PENDING",
            "DUPLICATE_REQUEST_COMPLETED",
            "DUPLICATE_REQUEST_DETECTED",
        }

        if normalized_event_type in pre_execution_events:
            return "PRE_EXECUTION"

        if normalized_event_type in post_execution_events:
            return "POST_EXECUTION"

        if normalized_event_type in terminal_decision_events:
            return "TERMINAL_DECISION"

        if normalized_event_type in observational_events:
            return "OBSERVATIONAL"

        return "UNKNOWN"

    def _record_audit_failure(
        self,
        *,
        event_type: str,
        request: ExecutionRequest | None,
        error: Exception,
        stage: str | None = None,
    ) -> None:
        """
        Record one runtime audit storage incident.

        This method extends the existing audit system without
        replacing audit persistence, execution routing, risk,
        idempotency, or result handling.

        The v31.2 policy is observational:
        - mark audit runtime as degraded
        - retain incident details
        - expose state through health() and status()
        - do not yet halt execution
        """

        request_id = str(
            getattr(
                request,
                "request_id",
                "",
            )
        ).strip() or None

        resolved_stage = (
            str(
                stage
            ).strip().upper()
            if stage
            else self._classify_audit_stage(
                event_type
            )
        )

        failure = {
            "stage": resolved_stage,
            "event_type": str(
                event_type
            ).strip().upper(),
            "request_id": request_id,
            "error_type": type(
                error
            ).__name__,
            "error": str(
                error
            ),
            "manager_version": self.VERSION,
            "mode": self.mode,
            "criticality": (
                "CRITICAL"
                if resolved_stage
                in {
                    "PRE_EXECUTION",
                    "POST_EXECUTION",
                }
                else "WARNING"
            ),
        }

        with self._lock:
            self.audit_runtime_state = (
                "AUDIT_DEGRADED"
            )

            self.audit_incident_count += 1

            self.last_audit_failure = dict(
                failure
            )

    def _close_experiment_if_unrecorded(
        self,
        event_id: str | None,
        approval_details: Any,
    ) -> None:
        """registry v5.01 EXP-001: the sample cap is restored from RISK_APPROVED
        events at startup, so an experiment admission whose event could not be
        recorded closes the experiment for this process (fail-closed)."""

        if (
            event_id is None
            and isinstance(approval_details, Mapping)
            and approval_details.get("experiment_id")
            and self.risk_engine is not None
        ):
            self.risk_engine.close_experiment("AUDIT_WRITE_FAILED")

    def _write_audit_event(
        self,
        *,
        event_type: str,
        request: ExecutionRequest,
        payload: Mapping[str, Any],
        causation_id: str | None = None,
    ) -> str | None:
        """
        Write a non-blocking immutable execution audit event.
        """

        if not self.audit_enabled:
            return None

        try:
            event = self.audit_store.append(
                event_type=event_type,
                source=self.NAME,
                aggregate_type="execution_request",
                aggregate_id=str(
                    request.request_id
                ),
                payload=payload,
                correlation_id=str(
                    request.request_id
                ),
                causation_id=causation_id,
                metadata={
                    "mode": self.mode,
                    "manager_version": self.VERSION,
                },
            )

            with self._lock:
                self.stats[
                    "audit_events_written"
                ] += 1

            return event.event_id

        except Exception as exc:
            with self._lock:
                self.stats[
                    "audit_write_failures"
                ] += 1

            self._record_audit_failure(
                event_type=event_type,
                request=request,
                error=exc,
            )

            logger.exception(
                "Execution audit event write failed "
                "type=%s request_id=%s error=%s",
                event_type,
                getattr(
                    request,
                    "request_id",
                    None,
                ),
                exc,
            )

            return None


    def _reset_refusal_reason(self) -> str | None:
        """Return a fixed refusal token, or ``None`` when reset is provably safe.

        Called with ``self._lock`` held. Attributes are read defensively
        (``getattr`` with the same conventions
        ``FinancialRuntimeSafetyService._base_evidence`` uses) so an injected
        test double cannot make the guard raise instead of refuse.
        """

        idempotency_loaded = bool(
            getattr(
                self.idempotency_store,
                "loaded",
                False,
            )
        )

        journal_loaded = bool(
            getattr(
                self.transaction_journal,
                "loaded",
                False,
            )
        ) and not bool(
            getattr(
                self.transaction_journal,
                "load_failed",
                False,
            )
        )

        if not idempotency_loaded or not journal_loaded:
            # An authority that did not load reports zero records, which is
            # indistinguishable from "no history" - and is exactly the state
            # in which erasing the other half is most damaging.
            return "EXECUTION_HISTORY_INDETERMINATE"

        if self.pending_request_ids or self._execution_side_effect_ids:
            return "EXECUTION_REQUESTS_IN_FLIGHT"

        completed = getattr(
            self.idempotency_store,
            "completed_requests",
            None,
        )

        entries = getattr(
            self.transaction_journal,
            "entries",
            None,
        )

        if not isinstance(completed, dict) or not isinstance(entries, dict):
            return "EXECUTION_HISTORY_INDETERMINATE"

        if completed or entries or self.completed_request_results:
            return "EXECUTION_HISTORY_PRESENT"

        return None

    def reset(self) -> None:
        """Clear in-memory runtime diagnostics only.

        Block 5J (finding B5H-0-9). This operation used to call
        ``idempotency_store.reset()``, erasing the durable terminal-result
        authority while leaving every COMMITTED transaction-journal entry in
        place. That is precisely the state
        ``FinancialRuntimeSafetyService._authorities_agree`` classifies as
        ``SOURCE_DISAGREEMENT``, so a single reset could halt the next start
        of an otherwise healthy runtime - and, because ``_claim_request``
        answers duplicates from ``completed_request_results`` alone, could
        also let an already-executed request execute a second time in the
        current process.

        The durable erase is gone: this method now writes no state file at
        all. It refuses outright (``ExecutionResetRefusedError``) whenever
        durable execution history exists, whenever either authority failed to
        load, and whenever a request is still in flight - so it can no longer
        manufacture divergence, and it can no longer discard committed
        financial evidence for convenience. Deliberately destructive
        maintenance is an explicit operator action against the state files
        themselves (see ADR-0005 and
        ``tools/reconcile_execution_authorities.py``), never a runtime call.

        The single-authority ``ExecutionIdempotencyStore.reset()`` /
        ``ExecutionTransactionJournal.reset()`` primitives are deliberately
        left as they are: neither store can see its counterpart, so the
        pairing invariant can only be enforced here, where both are held.
        """

        with self._lock:
            refusal = self._reset_refusal_reason()

            if refusal is not None:
                logger.warning(
                    "Execution Manager reset refused reason=%s",
                    refusal,
                )

                raise ExecutionResetRefusedError(refusal)

            self.history.clear()
            self.rejections.clear()
            self.errors.clear()

            self.stats = self._new_stats()

        logger.info(
            "Execution Manager reset"
        )

    def health(self) -> dict[str, Any]:
        with self._lock:
            latest_error = (
                dict(
                    self.errors[-1]
                )
                if self.errors
                else None
            )

            healthy = (
                self.running
                and not self.execution_halted
                and not self.recovery_required
                and self.audit_runtime_state == "HEALTHY"
                and not (
                    self.mode == self.MODE_LIVE
                    and not self.live_execution_enabled
                )
            )

            return {
                "healthy": healthy,
                "running": self.running,
                "version": self.VERSION,
                "mode": self.mode,
                "minimum_confidence": (
                    self.minimum_confidence
                ),
                "live_execution_enabled": (
                    self.live_execution_enabled
                ),
                "operational_state": {
                    "audit_runtime_state": (
                        self.audit_runtime_state
                    ),
                    "execution_halted": (
                        self.execution_halted
                    ),
                    "recovery_required": (
                        self.recovery_required
                    ),
                    "halt_reason": (
                        self.halt_reason
                    ),
                    "audit_incident_count": (
                        self.audit_incident_count
                    ),
                    "last_audit_failure": (
                        dict(
                            self.last_audit_failure
                        )
                        if self.last_audit_failure
                        else None
                    ),
                },
                # Block 6A: venue rule age is operational state a monitor must
                # be able to see without inferring it from a halt reason.
                "venue_rules": (
                    self.assess_venue_rule_freshness().to_dict()
                ),
                "statistics": dict(
                    self.stats
                ),
                "errors": {
                    "count": len(
                        self.errors
                    ),
                    "latest": latest_error,
                },
            }

    def status(self) -> dict[str, Any]:
        with self._lock:
            return {
                # S1 re-audit R-2: a corrupt bucket sidecar is visible, not only logged.
                "position_risk_buckets": {
                    "attached": self.position_risk_buckets is not None,
                    "corrupt": bool(getattr(self.position_risk_buckets, "corrupt", False)),
                },
                "unpriced_held_symbols": list(self.unpriced_held_symbols),
                "order_lifecycle": {
                    "observe": self.order_lifecycle_observe,
                    "violations": len(self.order_lifecycle_violations),
                    "latest": list(self.order_lifecycle_violations[-3:]),
                },
                "name": self.NAME,
                "version": self.VERSION,
                "mode": self.mode,
                "running": self.running,
                "minimum_confidence": (
                    self.minimum_confidence
                ),
                "live_execution_enabled": (
                    self.live_execution_enabled
                ),
                "operational_state": {
                    "audit_runtime_state": (
                        self.audit_runtime_state
                    ),
                    "execution_halted": (
                        self.execution_halted
                    ),
                    "recovery_required": (
                        self.recovery_required
                    ),
                    "halt_reason": (
                        self.halt_reason
                    ),
                    "audit_incident_count": (
                        self.audit_incident_count
                    ),
                    "last_audit_failure": (
                        dict(
                            self.last_audit_failure
                        )
                        if self.last_audit_failure
                        else None
                    ),
                },
                "venue_rules": (
                    self.assess_venue_rule_freshness().to_dict()
                ),
                "transaction_journal": (
                    self.transaction_journal.status()
                ),
                "durable_financial_state": (
                    self.portfolio_foundation.diagnostics()
                    if self.portfolio_foundation is not None
                    else {
                        "ready": False,
                        "recovery_required": True,
                        "reason": "DURABLE_FINANCIAL_FOUNDATION_REQUIRED",
                    }
                ),
                "history": len(
                    self.history
                ),
                "rejections": len(
                    self.rejections
                ),
                "errors": {
                    "count": len(
                        self.errors
                    ),
                    "latest": (
                        dict(
                            self.errors[-1]
                        )
                        if self.errors
                        else None
                    ),
                },
                "statistics": dict(
                    self.stats
                ),
                "dependencies": {
                    "capital_manager": (
                        self.capital_manager
                        is not None
                    ),
                    "position_controller": (
                        self.position_controller
                        is not None
                    ),
                    "paper_trader": (
                        self.paper_trader
                        is not None
                    ),
                    "event_bus": (
                        self.event_bus
                        is not None
                    ),
                },
            }

    def __repr__(
        self,
    ) -> str:
        return (
            f"<{self.NAME} "
            f"version={self.VERSION} "
            f"mode={self.mode} "
            f"running={self.running}>"
        )
