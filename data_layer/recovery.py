"""Fail-closed Phase-2 recovery assessment and startup admission gate."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class RecoveryDisposition(str, Enum):
    READY = "READY"
    PROJECTION_REPLAY_REQUIRED = "PROJECTION_REPLAY_REQUIRED"
    RECONCILIATION_REQUIRED = "RECONCILIATION_REQUIRED"
    FAIL_CLOSED = "FAIL_CLOSED"


@dataclass(frozen=True, slots=True)
class RecoveryEvidence:
    journal_valid: bool = True
    journal_unresolved: bool = False
    external_outcome: str = "NONE"
    idempotency_valid: bool = True
    relational_valid: bool = True
    sources_agree: bool = True
    projection_present: bool = True
    replay_complete: bool = True
    schema_valid: bool = True


@dataclass(frozen=True, slots=True)
class RecoveryDecision:
    disposition: RecoveryDisposition
    ready: bool
    reason: str
    blind_retry_allowed: bool = False


def assess_recovery(evidence: RecoveryEvidence) -> RecoveryDecision:
    """Classify authoritative evidence without repairing or retrying anything."""
    if not evidence.schema_valid:
        return RecoveryDecision(RecoveryDisposition.FAIL_CLOSED, False, "SCHEMA_OR_MIGRATION_INVALID")
    if not evidence.journal_valid or not evidence.idempotency_valid or not evidence.relational_valid:
        return RecoveryDecision(RecoveryDisposition.FAIL_CLOSED, False, "PERSISTED_STATE_CORRUPT")
    if not evidence.sources_agree:
        return RecoveryDecision(RecoveryDisposition.RECONCILIATION_REQUIRED, False, "SOURCE_DISAGREEMENT")
    outcome = evidence.external_outcome.upper()
    if outcome == "INDETERMINATE":
        return RecoveryDecision(RecoveryDisposition.RECONCILIATION_REQUIRED, False, "EXTERNAL_OUTCOME_INDETERMINATE")
    if evidence.journal_unresolved:
        return RecoveryDecision(RecoveryDisposition.RECONCILIATION_REQUIRED, False, "UNRESOLVED_JOURNAL")
    if outcome == "CONFIRMED" and (not evidence.projection_present or not evidence.replay_complete):
        return RecoveryDecision(RecoveryDisposition.PROJECTION_REPLAY_REQUIRED, False, "CONFIRMED_PROJECTION_INCOMPLETE")
    return RecoveryDecision(RecoveryDisposition.READY, True, "CLEAN")


def startup_ready(evidence: RecoveryEvidence) -> bool:
    return assess_recovery(evidence).ready
