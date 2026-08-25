"""Canonical financial-runtime recovery orchestration.

The service consumes specialized execution authorities and an optional source of
already-confirmed projection evidence.  It never contacts an exchange and never
claims external-execution authority for the relational database.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass
from typing import Any

from .contracts import StorageBackend
from .canonical_evidence import CanonicalExecutionEvidenceAdapter
from .projection_replay import ConfirmedExecutionEvidence, replay_confirmed_execution
from .recovery import RecoveryDecision, RecoveryDisposition, RecoveryEvidence, assess_recovery


@dataclass(frozen=True, slots=True)
class FinancialReadiness:
    ready: bool
    decision: RecoveryDecision
    replayed: int = 0


EvidenceSource = Callable[[], Iterable[ConfirmedExecutionEvidence]]


class FinancialRuntimeSafetyService:
    """Fail-closed readiness gate for storage-dependent financial operations."""

    def __init__(
        self,
        *,
        transaction_journal: Any,
        idempotency_store: Any,
        storage: StorageBackend | None = None,
        confirmed_evidence_source: EvidenceSource | None = None,
        relational_state_valid: Callable[[], bool] | None = None,
        schema_valid: Callable[[], bool] | None = None,
        sources_agree: Callable[[], bool] | None = None,
    ) -> None:
        if storage is None and confirmed_evidence_source is not None:
            raise ValueError("confirmed_evidence_source requires storage")
        self._journal = transaction_journal
        self._idempotency = idempotency_store
        self._storage = storage
        self._evidence_source = confirmed_evidence_source or (
            CanonicalExecutionEvidenceAdapter(transaction_journal, idempotency_store)
            if storage is not None else None
        )
        self._relational_state_valid = relational_state_valid
        self._schema_valid = schema_valid
        self._sources_agree = sources_agree
        self._last = FinancialReadiness(
            False,
            RecoveryDecision(RecoveryDisposition.FAIL_CLOSED, False, "NOT_ASSESSED"),
        )

    @property
    def readiness(self) -> FinancialReadiness:
        return self._last

    @staticmethod
    def _safe_check(check: Callable[[], bool] | None, default: bool = True) -> bool:
        if check is None:
            return default
        try:
            return bool(check())
        except Exception:
            return False

    def _authorities_agree(self) -> bool:
        if not self._safe_check(self._sources_agree):
            return False
        entries = getattr(self._journal, "entries", {})
        completed = getattr(self._idempotency, "completed_requests", {})
        if not isinstance(entries, dict) or not isinstance(completed, dict):
            return False
        for request_id, entry in entries.items():
            if not isinstance(entry, dict):
                return False
            if str(entry.get("state", "")).upper() == "COMMITTED" and request_id not in completed:
                return False
        return True

    def _migration_required(self) -> bool:
        """Whether either authority holds legacy state it refuses to reinterpret.

        Block 5K moved both authorities to versioned append-only logs. A
        legacy v1 file is real history, so the store reports it rather than
        loading an empty log in its place; the runtime must treat that as
        the schema/migration failure it is and never as a clean new store.
        """
        return any(
            bool(getattr(authority, "migration_required", False))
            for authority in (self._journal, self._idempotency)
        )

    def _base_evidence(self) -> RecoveryEvidence:
        migration_required = self._migration_required()
        journal_valid = bool(getattr(self._journal, "loaded", True)) and not bool(
            getattr(self._journal, "load_failed", False)
        )
        idempotency_valid = bool(
            getattr(self._idempotency, "loaded", True)
        ) and not bool(getattr(self._idempotency, "migration_required", False))
        if not idempotency_valid and not migration_required:
            # A deliberately non-loaded, not-yet-created store is a clean new
            # authority. A present file that was not loaded is never trusted,
            # and neither is an absent log whose legacy predecessor is still
            # sitting beside it awaiting migration.
            file_path = getattr(self._idempotency, "file_path", None)
            try:
                idempotency_valid = file_path is not None and not file_path.exists()
            except Exception:
                idempotency_valid = False
        try:
            journal_unresolved = bool(self._journal.has_unresolved())
        except Exception:
            journal_valid = False
            journal_unresolved = True
        entries = getattr(self._journal, "entries", {})
        indeterminate = any(
            isinstance(item, dict)
            and str(item.get("state", "")).upper() == "COMMIT_STATUS_UNKNOWN"
            for item in entries.values()
        ) if isinstance(entries, dict) else True
        return RecoveryEvidence(
            journal_valid=journal_valid,
            journal_unresolved=journal_unresolved,
            external_outcome="INDETERMINATE" if indeterminate else "NONE",
            idempotency_valid=idempotency_valid,
            relational_valid=self._safe_check(self._relational_state_valid),
            sources_agree=self._authorities_agree(),
            schema_valid=(
                self._safe_check(self._schema_valid) and not migration_required
            ),
        )

    def assess(self) -> FinancialReadiness:
        """Assess authorities, replay confirmed evidence, then verify readiness."""
        decision = assess_recovery(self._base_evidence())
        if not decision.ready:
            self._last = FinancialReadiness(False, decision)
            return self._last

        replayed = 0
        if self._evidence_source is not None:
            try:
                evidence_items = tuple(self._evidence_source())
                for evidence in evidence_items:
                    result = replay_confirmed_execution(self._storage, evidence)  # type: ignore[arg-type]
                    replayed += result.writes
            except Exception:
                decision = RecoveryDecision(
                    RecoveryDisposition.PROJECTION_REPLAY_REQUIRED,
                    False,
                    "PROJECTION_REPLAY_FAILED",
                )
                self._last = FinancialReadiness(False, decision, replayed)
                return self._last

            # Verification is a second idempotent pass. Any missing/partial or
            # disagreeing state fails here; it cannot become financially READY.
            try:
                if any(
                    replay_confirmed_execution(self._storage, evidence).state != "ALREADY_PROJECTED"  # type: ignore[arg-type]
                    for evidence in evidence_items
                ):
                    raise RuntimeError("projection verification was not idempotent")
            except Exception:
                decision = RecoveryDecision(
                    RecoveryDisposition.PROJECTION_REPLAY_REQUIRED,
                    False,
                    "PROJECTION_REPLAY_VERIFICATION_FAILED",
                )
                self._last = FinancialReadiness(False, decision, replayed)
                return self._last

        decision = assess_recovery(self._base_evidence())
        self._last = FinancialReadiness(decision.ready, decision, replayed)
        return self._last
