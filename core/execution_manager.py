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

import logging
from decimal import Decimal, InvalidOperation
import threading
import time
import uuid

from datetime import UTC, datetime
from enum import Enum
from typing import Any, Mapping

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
from core.execution_portfolio_foundation import ExecutionPortfolioFoundation

from core.risk_engine import (
    RiskEngine,
    RiskRequest,
    RiskState,
)
from core.capital_reservation import CapitalReservationLedger

from data_layer.runtime_safety import (
    FinancialRuntimeSafetyService,
)


logger = logging.getLogger(
    "AtlasAI.ExecutionManager"
)


class ExecutionManager:
    """
    Validate, route, execute, and observe Atlas execution requests.

    The manager accepts dictionaries, dataclasses, model objects, or any object
    exposing ``to_dict()``. All inputs are converted into the canonical
    ``ExecutionRequest`` contract before validation.

    Notes
    -----
    ``amount`` is treated as allocated quote-currency capital in the current
    paper-trading pipeline. The same value is passed to PaperTrader and
    PositionController so both components describe the same position size.
    """

    VERSION = "31.3"

    NAME = "ExecutionManager"

    MODE_PAPER = "PAPER"
    MODE_LIVE = "LIVE"

    MIN_CONFIDENCE = 60.0

    DEFAULT_ALLOCATION = 100.0

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
    ) -> None:
        self.capital_manager = capital_manager
        self.position_controller = position_controller
        self.paper_trader = paper_trader
        self.event_bus = event_bus
        self.risk_engine = risk_engine
        self.reservation_ledger = reservation_ledger
        self.risk_state_store = risk_state_store
        self.portfolio_foundation = portfolio_foundation
        self.last_risk_decision: dict[str, Any] | None = None
        self._risk_admissions: dict[str, tuple[str, ...]] = {}

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

            readiness = self._assess_financial_readiness()

            durable_ready = True
            durable_reason = None
            if self.portfolio_foundation is not None:
                durable_ready, durable_reason = self._durable_financial_ready()

            if not readiness.ready or not durable_ready:
                self.execution_halted = True
                self.recovery_required = True
                self.halt_reason = (
                    readiness.decision.reason if not readiness.ready else durable_reason
                )

        logger.info(
            "Execution Manager ONLINE"
        )

        self.publish(
            "EXECUTION_MANAGER_STARTED",
            self.status(),
        )

        return True

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
        """

        started_at = time.perf_counter()

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

        request: ExecutionRequest | None = None

        request_id: str | None = None

        request_claimed = False

        last_audit_event_id: str | None = None

        try:
            # =================================================
            # BUILD REQUEST
            # =================================================

            try:
                request = self.build_request(
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
                        started_at=started_at,
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

            request_id = str(
                request.request_id
            ).strip()

            if not request_id:
                return self.reject(
                    reason="INVALID_REQUEST_ID",
                    request=request,
                )

            # =================================================
            # REQUEST RECEIVED AUDIT
            # =================================================

            last_audit_event_id = (
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
                        last_audit_event_id
                    ),
                )

                return duplicate_result

            request_claimed = True

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

                request_claimed = False

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
                        last_audit_event_id
                    ),
                )

                return result

            with self._lock:
                self.stats[
                    "validated"
                ] += 1

            last_audit_event_id = (
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
                        last_audit_event_id
                    ),
                )
                or last_audit_event_id
            )

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

                request_claimed = False

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
                        last_audit_event_id
                    ),
                )

                return result

            if not self._has_risk_admission(request):
                return self.reject(reason="CANONICAL_RISK_ADMISSION_MISSING", request=request)

            last_audit_event_id = (
                self._write_audit_event(
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
                        last_audit_event_id
                    ),
                )
                or last_audit_event_id
            )

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

                request_claimed = False

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

            # =================================================
            # RETRYABLE FAILURE / NOT COMMITTED
            # =================================================

            if status in self.FAILURE_STATUSES:
                self._release_capital_reservation(request_id)
                result[
                    "commit_outcome"
                ] = (
                    CommitOutcome
                    .NOT_COMMITTED
                    .value
                )

                mark_not_committed = getattr(
                    self.transaction_journal,
                    "mark_not_committed",
                    None,
                )

                if callable(
                    mark_not_committed
                ):
                    try:
                        mark_not_committed(
                            request_id,
                            reason=status,
                            result=result,
                        )

                    except Exception:
                        logger.exception(
                            "Transaction NOT_COMMITTED "
                            "journal update failed"
                        )

                self._release_request(
                    request_id
                )

                request_claimed = False

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
                        last_audit_event_id
                    ),
                )

            # =================================================
            # TERMINAL DURABLE COMMIT
            # =================================================

            else:
                try:
                    if self.portfolio_foundation is not None:
                        self._finalize_durable_financial_state(
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
                    request_claimed = False
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
                    return unknown_result

                if not self._commit_capital_reservation(request_id):
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
                    request_claimed = False
                    return {
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

                request_claimed = False

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
                        last_audit_event_id
                    ),
                )

            self.publish(
                "EXECUTION_COMPLETED",
                result,
            )

            return result

        except Exception as exc:
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
                    event_type="EXECUTION_FAILED",
                    request=request,
                    payload={
                        "success": False,
                        "status": "FAILED",
                        "message": (
                            "Execution pipeline failed"
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
                        "retryable": True,
                    },
                    causation_id=(
                        last_audit_event_id
                    ),
                )

            self.publish(
                "EXECUTION_FAILED",
                failure,
            )

            return failure

        finally:
            # Defensive release for exceptions or unexpected
            # early exits after a successful atomic claim.
            if (
                request_claimed
                and request_id
            ):
                self._release_request(
                    request_id
                )

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
    # RISK VALIDATION
    # =========================================================

    def risk_check(
        self,
        request: ExecutionRequest,
        market_state: Any | None = None,
    ) -> dict[str, Any]:
        """
        Apply position and optional CapitalManager risk gates.
        """

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
        if self.risk_engine is not None:
            risk_state = (
                market_state
                if isinstance(market_state, RiskState)
                else (
                    market_state.get("risk_state")
                    if isinstance(market_state, Mapping)
                    else None
                )
            )
            try:
                if not isinstance(risk_state, RiskState) or not risk_state.state_ready:
                    raise ValueError("authoritative position exposure state is required")
                restored = self.risk_state_store.load(
                    expected_policy_version=self.risk_engine.policy.version,
                    today_utc=datetime.now(UTC).date(),
                )
                risk_state = RiskState(
                    positions=risk_state.positions,
                    committed_quote=risk_state.committed_quote,
                    realized_daily_pnl=restored.realized_daily_pnl,
                    peak_equity=restored.peak_equity,
                    current_equity=restored.current_equity,
                    state_ready=True,
                    accounting_day_utc=restored.accounting_day_utc.isoformat(),
                    policy_version=restored.policy_version,
                )
                canonical = self.risk_engine.evaluate(
                    RiskRequest(
                        symbol=request.symbol,
                        action=request.action,
                        confidence=Decimal(str(request.confidence)) / Decimal("100"),
                        requested_quote_allocation=Decimal(str(request.amount)),
                        execution_price=Decimal(str(request.price)),
                        risk_bucket=request.risk,
                        reduce_only=request.reduce_only,
                    ),
                    risk_state if isinstance(risk_state, RiskState) else RiskState(),
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
            # Keep this explicit assertion at the execution seam.
            if canonical.approved_allocation != Decimal(str(request.amount)):
                return {"approved": False, "reason": "RISK_ALLOCATION_MISMATCH"}

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

        capital_result = self._capital_risk_check(
            request=request,
            market_state=market_state,
        )

        if not capital_result["approved"]:
            return capital_result

        if request.action == "BUY" and not request.reduce_only:
            try:
                self.reservation_ledger.reserve(request.request_id, request.request_id,
                                                canonical.approved_allocation)
            except Exception as exc:
                self._record_error(phase="capital_reservation", error=exc, request=request)
                return {"approved": False, "reason": "CAPITAL_RESERVATION_FAILED",
                        "status": "BLOCK_RECOVERY_REQUIRED"}
        self._risk_admissions[request.request_id] = self._risk_admission_key(request)

        return {
            "approved": True,
            "reason": "RISK_APPROVED",
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

    @staticmethod
    def _risk_admission_key(request: ExecutionRequest) -> tuple[str, ...]:
        return (
            request.symbol,
            request.action,
            str(Decimal(str(request.price))),
            str(Decimal(str(request.amount))),
            str(Decimal(str(request.confidence))),
            request.risk,
            str(bool(request.reduce_only)),
            request.mode,
        )

    def _has_risk_admission(self, request: ExecutionRequest) -> bool:
        return self._risk_admissions.get(request.request_id) == self._risk_admission_key(request)

    def _release_capital_reservation(self, request_id: str) -> bool:
        if self.reservation_ledger is None:
            return False
        if self.reservation_ledger.get(request_id) is None:
            self._risk_admissions.pop(request_id, None)
            return True
        try:
            self.reservation_ledger.release(request_id)
            self._risk_admissions.pop(request_id, None)
            return True
        except Exception as exc:
            self._record_error(phase="capital_release", error=exc)
            with self._lock:
                self.execution_halted = True
                self.recovery_required = True
                self.halt_reason = "CAPITAL_RESERVATION_RELEASE_FAILED"
            return False

    def _commit_capital_reservation(self, request_id: str) -> bool:
        if self.reservation_ledger is None:
            return False
        if self.reservation_ledger.get(request_id) is None:
            self._risk_admissions.pop(request_id, None)
            return True
        try:
            self.reservation_ledger.commit(request_id)
            self._risk_admissions.pop(request_id, None)
            return True
        except Exception as exc:
            self._record_error(phase="capital_commit", error=exc)
            return False

    def _mark_capital_indeterminate(self, request_id: str) -> bool:
        if self.reservation_ledger is None:
            return False
        if self.reservation_ledger.get(request_id) is None:
            self._risk_admissions.pop(request_id, None)
            return True
        try:
            self.reservation_ledger.mark_indeterminate(request_id)
            self._risk_admissions.pop(request_id, None)
            return True
        except Exception as exc:
            self._record_error(phase="capital_indeterminate", error=exc)
            return False

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
        result["idempotency_key"] = evidence.idempotency_key
        result["provenance_ref"] = evidence.provenance_ref
        result["durable_financial_state"] = {
            "replayed": finalized["replayed"],
            "position_id": evidence.position_id,
        }
        return finalized

    def _capital_risk_check(
        self,
        *,
        request: ExecutionRequest,
        market_state: Any | None,
    ) -> dict[str, Any]:
        """
        Use CapitalManager validation when it exposes a compatible method.
        """

        if self.capital_manager is None:
            return {
                "approved": True,
                "reason": "CAPITAL_MANAGER_NOT_CONFIGURED",
            }

        for method_name in (
            "validate_execution",
            "validate_request",
            "risk_check",
            "approve",
        ):
            method = getattr(
                self.capital_manager,
                method_name,
                None,
            )

            if not callable(
                method
            ):
                continue

            try:
                result = method(
                    request.to_dict(),
                    market_state,
                )

            except TypeError:
                try:
                    result = method(
                        request.to_dict()
                    )

                except TypeError:
                    try:
                        result = method(
                            request
                        )

                    except Exception as exc:
                        self._record_error(
                            phase="capital_risk",
                            error=exc,
                            request=request,
                        )
                        return {
                            "approved": False,
                            "reason": "CAPITAL_RISK_CHECK_FAILED",
                            "details": {
                                "error": str(
                                    exc
                                ),
                            },
                        }

                except Exception as exc:
                    self._record_error(
                        phase="capital_risk",
                        error=exc,
                        request=request,
                    )
                    return {
                        "approved": False,
                        "reason": "CAPITAL_RISK_CHECK_FAILED",
                        "details": {
                            "error": str(
                                exc
                            ),
                        },
                    }

            except Exception as exc:
                self._record_error(
                    phase="capital_risk",
                    error=exc,
                    request=request,
                )
                return {
                    "approved": False,
                    "reason": "CAPITAL_RISK_CHECK_FAILED",
                    "details": {
                        "error": str(
                            exc
                        ),
                    },
                }

            return self._normalize_approval_result(
                result,
                default_reason="CAPITAL_RISK_REJECTED",
            )

        return {
            "approved": True,
            "reason": "CAPITAL_RISK_NOT_EXPOSED",
        }

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
            filled_price=request.price,
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

    def _execute_paper_buy(
        self,
        *,
        request: ExecutionRequest,
        result: ExecutionResult,
    ) -> None:
        """
        Coordinate paper BUY and authoritative position registration.
        """

        allocation = self.allocate_capital(
            request
        )

        # Historical compatibility: filled_amount remains the quote allocation
        # on this path.  Canonical consumers must use the explicit Decimal fields.
        result.filled_amount = allocation
        quote_notional = Decimal(str(allocation))
        result.requested_quote_allocation = Decimal(str(request.amount))
        result.filled_quote_notional = quote_notional
        result.data = result.data or {}
        result.data["allocation"] = allocation

        if allocation <= 0:
            self._mark_result_failure(
                result=result,
                message="Capital allocation returned zero",
                error_code="ZERO_ALLOCATION",
            )
            return

        paper_trade = self._paper_open_trade(
            request=request,
            allocation=allocation,
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

        try:
            execution_price = Decimal(str(result.filled_price))
            if quote_notional <= 0 or execution_price <= 0:
                raise ValueError("non-positive paper fill inputs")
            result.filled_base_quantity = quote_notional / execution_price
            result.fee_amount = Decimal(str(result.fee))
        except (InvalidOperation, ValueError, TypeError, ZeroDivisionError):
            self._mark_result_failure(
                result=result,
                message="Paper fill quantity semantics are invalid",
                error_code="INVALID_FINANCIAL_QUANTITY",
            )
            return

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
            "allocation": allocation,
            "source": request.source,
            "order_type": request.order_type,
            "time_in_force": request.time_in_force,
            "reduce_only": request.reduce_only,
        }

        if self.portfolio_foundation is not None:
            existing = self.portfolio_foundation.snapshot()["positions"].get(request.symbol)
            result.position_id = (
                existing["position_id"] if existing is not None
                else "long:" + request.symbol
            )
            position = None
        else:
            position = self._position_open(
                request=request,
                allocation=allocation,
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
        """
        Call PaperTrader.open_trade through supported contracts.
        """

        if self.paper_trader is None:
            return None

        open_trade = getattr(
            self.paper_trader,
            "open_trade",
            None,
        )

        if not callable(
            open_trade
        ):
            return None

        try:
            return open_trade(
                request.symbol,
                request.price,
                allocation,
            )

        except TypeError:
            try:
                return open_trade(
                    symbol=request.symbol,
                    price=request.price,
                    amount=allocation,
                    strategy=request.strategy,
                    confidence=request.confidence,
                    risk=request.risk,
                    metadata=self._normalize_metadata(
                        request.metadata
                    ),
                )

            except Exception as exc:
                self._record_error(
                    phase="paper_buy",
                    error=exc,
                    request=request,
                )
                logger.exception(
                    "PaperTrader BUY failed"
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
                phase="paper_buy",
                error=exc,
                request=request,
            )
            logger.exception(
                "PaperTrader BUY failed"
            )
            return {
                "success": False,
                "status": "FAILED",
                "reason": str(
                    exc
                ),
            }

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

    def _execute_paper_sell(
        self,
        *,
        request: ExecutionRequest,
        result: ExecutionResult,
    ) -> None:
        """
        Coordinate paper SELL and authoritative position closure.
        """

        result.data = result.data or {}

        if self.portfolio_foundation is not None:
            position = self.portfolio_foundation.snapshot()["positions"].get(request.symbol)
            if position is None:
                self._mark_result_failure(
                    result=result,
                    message="Durable LONG position was not found",
                    error_code="POSITION_NOT_FOUND",
                )
                return
            result.position_id = position["position_id"]
            result.filled_base_quantity = Decimal(position["base_quantity"])
            result.filled_quote_notional = (
                result.filled_base_quantity * Decimal(str(result.filled_price))
            )
            result.filled_amount = float(result.filled_quote_notional)
            result.fee_amount = Decimal(str(result.fee))

        paper_trade = self._paper_close_trade(
            request
        )

        if paper_trade is not None:
            result.data["paper_trade"] = paper_trade

            self._hydrate_result_from_component(
                result=result,
                payload=paper_trade,
            )

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

        position = (
            None if self.portfolio_foundation is not None
            else self._position_close(request=request, metadata=close_metadata)
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
        """
        Call PaperTrader.close_trade through supported contracts.
        """

        if self.paper_trader is None:
            return None

        close_trade = getattr(
            self.paper_trader,
            "close_trade",
            None,
        )

        if not callable(
            close_trade
        ):
            return None

        try:
            return close_trade(
                request.symbol
            )

        except TypeError:
            try:
                return close_trade(
                    symbol=request.symbol,
                    price=request.price,
                    metadata=self._normalize_metadata(
                        request.metadata
                    ),
                )

            except Exception as exc:
                self._record_error(
                    phase="paper_sell",
                    error=exc,
                    request=request,
                )
                logger.exception(
                    "PaperTrader SELL failed"
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
                phase="paper_sell",
                error=exc,
                request=request,
            )
            logger.exception(
                "PaperTrader SELL failed"
            )
            return {
                "success": False,
                "status": "FAILED",
                "reason": str(
                    exc
                ),
            }

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
    # CAPITAL ALLOCATION
    # =========================================================

    def allocate_capital(
        self,
        request: ExecutionRequest,
    ) -> float:
        """
        Calculate quote-currency capital allocated to a paper position.

        Priority
        --------
        1. CapitalManager position-sizing method
        2. Explicit request.amount
        3. Available-capital bounded default
        4. DEFAULT_ALLOCATION
        """

        manager_value = self._calculate_manager_position_size(
            request
        )

        if manager_value > 0:
            return manager_value

        if request.amount > 0:
            return request.amount

        available_capital = self._available_capital()

        if available_capital is not None:
            return max(
                0.0,
                min(
                    self.DEFAULT_ALLOCATION,
                    available_capital,
                ),
            )

        return self.DEFAULT_ALLOCATION

    def _calculate_manager_position_size(
        self,
        request: ExecutionRequest,
    ) -> float:
        """
        Query CapitalManager position-sizing contracts.
        """

        if self.capital_manager is None:
            return 0.0

        for method_name in (
            "calculate_position_size",
            "allocate",
            "allocate_capital",
        ):
            method = getattr(
                self.capital_manager,
                method_name,
                None,
            )

            if not callable(
                method
            ):
                continue

            try:
                value = method(
                    request.to_dict()
                )

            except TypeError:
                try:
                    value = method(
                        confidence=request.confidence,
                        risk_level=request.risk,
                        price=request.price,
                        symbol=request.symbol,
                    )

                except TypeError:
                    try:
                        value = method(
                            request
                        )

                    except Exception as exc:
                        self._record_error(
                            phase="capital_allocation",
                            error=exc,
                            request=request,
                        )
                        continue

                except Exception as exc:
                    self._record_error(
                        phase="capital_allocation",
                        error=exc,
                        request=request,
                    )
                    continue

            except Exception as exc:
                self._record_error(
                    phase="capital_allocation",
                    error=exc,
                    request=request,
                )
                continue

            normalized = self._extract_numeric_value(
                value,
                keys=(
                    "amount",
                    "allocation",
                    "position_size",
                    "capital",
                    "approved_amount",
                ),
            )

            if normalized > 0:
                return normalized

        return 0.0

    def _available_capital(
        self,
    ) -> float | None:
        """
        Read available capital from attribute or method contracts.
        """

        if self.capital_manager is None:
            return None

        value = getattr(
            self.capital_manager,
            "available_capital",
            None,
        )

        if callable(
            value
        ):
            try:
                value = value()

            except Exception as exc:
                self._record_error(
                    phase="available_capital",
                    error=exc,
                )
                return None

        if value is None:
            method = getattr(
                self.capital_manager,
                "get_available_capital",
                None,
            )

            if callable(
                method
            ):
                try:
                    value = method()

                except Exception as exc:
                    self._record_error(
                        phase="available_capital",
                        error=exc,
                    )
                    return None

        normalized = self._extract_numeric_value(
            value,
            keys=(
                "available_capital",
                "available",
                "cash",
                "balance",
            ),
        )

        return (
            normalized
            if normalized >= 0
            else None
        )

    # =========================================================
    # LIVE EXECUTION
    # =========================================================

    def live_execute(
        self,
        request: ExecutionRequest,
    ) -> dict[str, Any]:
        """
        Deny live execution unless explicitly enabled.

        Even when enabled, a concrete live execution adapter is required.
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

        # Do not hydrate canonical base quantity from ambiguous legacy keys.
        filled_amount = ExecutionManager._extract_numeric_value(
            payload,
            keys=(
                "filled_amount",
                "allocation",
            ),
        )

        if filled_amount > 0:
            result.filled_amount = filled_amount

        fee = ExecutionManager._extract_numeric_value(
            payload,
            keys=(
                "fee",
                "commission",
            ),
        )

        if fee != 0:
            result.fee = fee

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
    def _normalize_approval_result(
        result: Any,
        *,
        default_reason: str,
    ) -> dict[str, Any]:
        if isinstance(
            result,
            Mapping,
        ):
            approved = bool(
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

            return {
                "approved": approved,
                "reason": str(
                    result.get(
                        "reason",
                        (
                            "APPROVED"
                            if approved
                            else default_reason
                        ),
                    )
                ),
                "details": dict(
                    result
                ),
            }

        approved = bool(
            result
        )

        return {
            "approved": approved,
            "reason": (
                "APPROVED"
                if approved
                else default_reason
            ),
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
        request: ExecutionRequest,
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


    def reset(self) -> None:
        with self._lock:
            self.history.clear()
            self.rejections.clear()
            self.errors.clear()

            self.pending_request_ids.clear()
            self.completed_request_results.clear()

            self.idempotency_store.reset(
                delete_file=False
            )

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
