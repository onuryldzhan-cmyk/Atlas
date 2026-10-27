"""
============================================================
ATLAS OPERATOR EXECUTION-AUTHORITY RECONCILIATION
============================================================

Verify-first, fail-closed operator inspection of the paired execution
authorities in one state directory, with one narrowly-proven repair and one
PAPER-only recovery of an interrupted execution.

Authority model (established by Block 5H-0 / 5I, not redefined here):

- ``execution_transaction_journal.jsonl`` is the permanent commit-outcome
  authority. A COMMITTED entry means the financial side effect actually
  happened.
- ``execution_idempotency.jsonl`` is the permanent terminal-result / replay
  authority. Its record is what a replayed request_id is answered with, so a
  missing record is what lets an already-executed request execute twice.
- ``execution_applied_executions.jsonl`` (plus the ``applied_checkpoint`` in
  ``execution_financial_state.json``) is the permanent financial-application
  authority: an immutable, append-only record of every execution that was
  durably applied to the book, keyed by ``execution_id`` and by
  ``idempotency_key`` - which is the request_id.

``FinancialRuntimeSafetyService`` refuses to start a runtime whose journal
holds a COMMITTED entry with no idempotency counterpart
(``SOURCE_DISAGREEMENT``). Before Block 5J there was no supported way out of
that state: the only tooling that touched these files was a runtime reset
that could create it. This tool is that way out, and it is deliberately
narrow.

What it will repair
-------------------
Exactly one class, and only when three independent durable authorities agree
on one unique terminal truth:

  journal COMMITTED with a complete successful result
  + an applied-execution record proving that same request_id/execution_id
    was financially applied
  + a financial book that loads cleanly and whose checkpoints agree with
    both sidecars (``ExecutionPortfolioFoundation.ready``)
  + no idempotency record

  -> recreate the idempotency terminal result from the journal's own
     result, field for field.

Nothing is reconstructed or inferred: the repaired record is a copy of an
existing authority's payload, not a derivation from partial evidence. The
only field this tool does not copy is ``idempotency_recorded_at``, which
``ExecutionIdempotencyStore.record()`` stamps itself and which carries no
financial meaning.

What it will recover (F-1, PAPER only)
--------------------------------------
A process killed between the journal PREPARE and the journal COMMITTED event
leaves one PREPARED entry, and the runtime refuses to start until it is
resolved. When - and only when - the operator states the runtime's execution
mode with ``execution_mode="PAPER"`` (``--execution-mode PAPER``), that entry
is resolved from durable evidence, ground truth first:

- ``ABORT_NOT_APPLIED``: the applied-execution authority holds no record for
  the request, no terminal result exists, and the financial book either
  loads cleanly or holds only this request's transition marker with nothing
  appended beyond either sidecar checkpoint. Nothing happened: the marker (if
  any) is cleared, a RESERVED reservation is released, and the entry is
  resolved NOT_COMMITTED.
- ``COMMIT_APPLIED_EVIDENCE``: the applied-execution authority holds the
  request's record and the book loads cleanly around it. It happened: a
  RESERVED reservation is committed, a missing terminal result is recorded,
  and the entry is resolved COMMITTED. The result is the idempotency record
  when one exists; otherwise it carries only what the authorities prove
  (execution_id, request identity, symbol, action, mode) and says so under
  ``recovery`` - fill figures are never recomputed or invented for it.
- ``COMMIT_PAPER_REDERIVATION``: the only inconclusive window - the
  transition marker is still on disk but a sidecar record was already
  appended, which can never be removed. The fill is re-derived with
  ExecutionManager's own paper-fill logic from the prepared request (the
  price that was live at the time) against the pre-transition book, and only
  when the durable RISK_APPROVED audit event proves the request was admitted
  in PAPER mode under the exact instrument-rules digest in force now. Every
  record already on disk must equal the re-derived settlement, or nothing is
  written. The interrupted application is then completed and the entry
  resolved COMMITTED.

Risk accounting (MEDIUM-1, registry v4.84). A recovered COMMITTED SELL's
realized P&L and equity are booked into ``risk_accounting_state.json`` exactly
once, through the runtime's own hook -
``ExecutionManager._record_realized_risk_accounting``, the one normal
execution calls right after ``apply_confirmed`` - never through a calculation
of this tool's. A BUY books nothing, exactly as in normal execution. Whether
the hook already ran is established from its own write-ahead record, the
``RISK_ACCOUNTING_REALIZED_PNL_PREPARED`` audit event, against the stored
state:

- the latest PREPARED's ``new_state`` is the stored state: the runtime booked
  it before the crash (every kill after ``_finalize_durable_financial_state``
  returned - K3..K6 - is this case) and nothing is written again;
- the latest PREPARED's ``previous_state`` is the stored state: the write
  never landed. The hook is re-run on the current book, with the pre-commit
  view restored from that record's components, and must reproduce the
  record's ``new_state`` exactly;
- no PREPARED: a re-derivation (K2) books through the hook with the genuine
  pre-transition and completed views; an applied-evidence recovery has no
  durable figures to book from and is refused
  (``RISK_ACCOUNTING_EVIDENCE_UNAVAILABLE``) rather than resolved without
  them.

Anything a booking needs that is not true now - the stored accounting day is
not today (``RISK_ACCOUNTING_DAY_NOT_CURRENT``), the store or audit log does
not load, or the stored state matches neither side of the record - refuses
before anything is written. A recovery never resolves a SELL COMMITTED while
its realized result is unbooked.

One accepted window (v4.84 independent audit MEDIUM-A): if this tool itself
is killed after it completed a re-derived SELL's book but before the hook's
PREPARED record landed, the rerun sees an applied-evidence SELL with no
PREPARED and refuses ``RISK_ACCOUNTING_EVIDENCE_UNAVAILABLE`` on every run -
fail-closed, nothing misbooked, but only operator reconciliation resolves it.

Anything else - a LIVE mode, no mode stated, more than one unresolved entry,
COMMIT_STATUS_UNKNOWN, a prepared request that is not provably PAPER, or
evidence matching none of the three classes - is refused exactly as before.
A real venue's fill cannot be recomputed from local state, so no LIVE path
exists and none is reachable by falling through.

What it will never do
---------------------
- Guess which authority is right when two disagree.
- Reconstruct a journal entry from an idempotency record. The journal owns
  commit-outcome and lifecycle semantics (``prepared_at``, the prepared
  request payload) that a terminal result simply does not contain, and
  fabricating them would fabricate evidence.
- Repair anything while any unresolved journal entry (PREPARED /
  COMMIT_STATUS_UNKNOWN) exists, except through the PAPER recovery above,
  which runs alone. An unresolved transaction is a live question about
  whether money moved; reconciling around it could bury it.
- Repair or recover anything when any other disagreement class is present
  anywhere in the book. The tool refuses wholesale, so an operator resolves
  the conflict before any write happens.
- Write the journal, the sidecars, the financial state file, the
  reservation ledger, the risk-accounting state or the audit log outside a
  PAPER recovery; the audit log only ever receives the risk-accounting hook's
  own PREPARED/COMMITTED pair, stamped with ``metadata.origin`` =
  ``tools.reconcile_execution_authorities`` (the runtime never sets it), and
  after a rolled-back booking one ``RISK_ACCOUNTING_RECOVERY_BOOKING_ROLLED_BACK``
  event naming those events. A repair writes only the idempotency store.
- Delete, prune, or reset anything. A failed repair or recovery restores
  every file it touched to its exact pre-run bytes - except the append-only,
  hash-chained audit log, which is never rewritten. A PREPARED left behind by
  a rolled-back booking is harmless: the restored state equals its
  ``previous_state``, so a rerun books again; the marker event says it was
  rolled back.

Output safety (ADR-0005)
------------------------
Reason codes are fixed tokens. No request_id, execution_id, position_id,
order_id, state-file content, or raw exception text ever reaches stdout -
only outcomes, fixed tokens, counts, and the sanitized state-directory path.

Exit codes
----------
0  authorities agree, a dry run completed, or a repair or recovery completed
   and verified
1  CLI usage error
2  action required: a genuine disagreement this tool refuses to resolve, or
   an unreadable/corrupt authority. Nothing was written.
3  a repair or recovery was attempted and failed. Every file it touched was
   restored byte-for-byte to its pre-run contents.
============================================================
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import tempfile
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import ROUND_HALF_EVEN, Decimal, localcontext
from enum import Enum
from pathlib import Path
from typing import Any, Mapping

_REPOSITORY_ROOT = Path(__file__).resolve().parent.parent
if str(_REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPOSITORY_ROOT))

from atlas_security import sanitize_sensitive_text  # noqa: E402
from core.audit_event_store import AuditEventStore  # noqa: E402
from core.capital_reservation import (  # noqa: E402
    CapitalReservation,
    CapitalReservationLedger,
    JsonReservationStore,
    ReservationArchiveStore,
    ReservationStatus,
)
from core.execution_idempotency_store import ExecutionIdempotencyStore  # noqa: E402
from core.execution_manager import ExecutionManager  # noqa: E402
from core.execution_models import ExecutionRequest, ExecutionResult  # noqa: E402
from core.execution_portfolio_foundation import (  # noqa: E402
    SETTLEMENT_CONTEXT_PRECISION,
    AppliedExecutionArchiveConflictError,
    AppliedExecutionArchiveCorruptError,
    AppliedExecutionArchiveStore,
    ClosedPositionArchiveStore,
    ExecutionPortfolioFoundation,
    FinancialStateStore,
    InterruptedTransition,
    InterruptedTransitionError,
    abandon_interrupted_transition,
    complete_interrupted_transition,
    inspect_interrupted_transition,
)
from core.instrument_rules import InstrumentRuleset  # noqa: E402
from core.risk_engine import RiskEngine, RiskPolicy  # noqa: E402
from core.risk_state_store import JsonRiskStateStore, RestoredRiskState  # noqa: E402
from core.execution_transaction_journal import (  # noqa: E402
    PREPARED_STATE,
    CommitOutcome,
    ExecutionTransactionJournal,
)
from data_layer.canonical_evidence import CanonicalExecutionEvidenceAdapter  # noqa: E402
from data_layer.contracts import IntegrityViolation  # noqa: E402
from data_layer.runtime_safety import FinancialRuntimeSafetyService  # noqa: E402

EXIT_OK = 0
EXIT_USAGE = 1
EXIT_REFUSED = 2
EXIT_FAILED = 3

DEFAULT_JOURNAL_FILE = "execution_transaction_journal.jsonl"
DEFAULT_IDEMPOTENCY_FILE = "execution_idempotency.jsonl"
DEFAULT_FINANCIAL_STATE_FILE = "execution_financial_state.json"
DEFAULT_APPLIED_FILE = "execution_applied_executions.jsonl"
DEFAULT_CLOSED_FILE = "execution_closed_positions.jsonl"
DEFAULT_RESERVATION_FILE = "capital_reservations.json"
DEFAULT_RESERVATION_ARCHIVE_FILE = "capital_reservations_archive.jsonl"
DEFAULT_AUDIT_FILE = "audit/atlas_audit_events.jsonl"
DEFAULT_RISK_STATE_FILE = "risk_accounting_state.json"

# The runtime's own success authority, imported rather than restated so this
# tool cannot drift from what ExecutionManager treats as an executed order.
_CONFIRMED_STATUSES = frozenset(ExecutionManager.SUCCESS_STATUSES)

# ExecutionIdempotencyStore.record() stamps this itself; it is repair
# provenance, never financial evidence, and is the one field a recreated
# record is not required to match the journal result on.
_RECORD_STAMP_FIELD = "idempotency_recorded_at"

# The only keys an idempotency record may hold beyond the journal result it
# must otherwise mirror exactly: record() sets both itself.
_RECORD_ONLY_FIELDS = frozenset({_RECORD_STAMP_FIELD, "request_id"})


class ReconciliationOutcome(str, Enum):
    AUTHORITIES_AGREE = "AUTHORITIES_AGREE"
    WOULD_RECONCILE = "WOULD_RECONCILE"
    RECONCILED = "RECONCILED"
    WOULD_RECOVER = "WOULD_RECOVER"
    RECOVERED = "RECOVERED"
    RECONCILIATION_REQUIRED = "RECONCILIATION_REQUIRED"
    STATE_INVALID = "STATE_INVALID"
    FAILED = "FAILED"


class ExecutionMode(str, Enum):
    """The runtime execution mode the operator states for this state directory."""

    PAPER = "PAPER"
    LIVE = "LIVE"


class RecoveryClass(str, Enum):
    ABORT_NOT_APPLIED = "ABORT_NOT_APPLIED"
    COMMIT_APPLIED_EVIDENCE = "COMMIT_APPLIED_EVIDENCE"
    COMMIT_PAPER_REDERIVATION = "COMMIT_PAPER_REDERIVATION"


class RiskAccounting(str, Enum):
    """What a recovery does with the recovered request's realized result."""

    NOT_APPLICABLE = "NOT_APPLICABLE"  # a BUY or an abort: nothing is realized
    ALREADY_RECORDED = "ALREADY_RECORDED"  # the runtime's hook booked it pre-crash
    RECORD = "RECORD"  # this recovery books it through the runtime's hook


_REFUSED_OUTCOMES = frozenset((
    ReconciliationOutcome.RECONCILIATION_REQUIRED,
    ReconciliationOutcome.STATE_INVALID,
))


# Refusal classes, most severe first. The order is fixed so a book holding
# several disagreement classes always reports the same reason code.
_REFUSAL_PRIORITY = (
    "JOURNAL_UNRESOLVED",
    "RECOVERY_MODE_UNPROVEN",
    "RECOVERY_AUTHORITY_UNREADABLE",
    "RECOVERY_EVIDENCE_AMBIGUOUS",
    "RECOVERY_DERIVATION_UNAVAILABLE",
    "RISK_ACCOUNTING_EVIDENCE_UNAVAILABLE",
    "RISK_ACCOUNTING_DAY_NOT_CURRENT",
    "JOURNAL_ENTRY_MALFORMED",
    "AUTHORITY_RESULT_CONFLICT",
    "JOURNAL_ENTRY_ABSENT",
    "FINANCIAL_APPLICATION_UNPROVEN",
)

# The journal reason a recovered abort is resolved with, and the key under
# which a recovered COMMITTED result states how it was established.
RECOVERED_NOT_APPLIED_REASON = "RECOVERED_NOT_APPLIED"
RECOVERY_RESULT_FIELD = "recovery"

# Every audit event this tool causes carries this metadata marker; the
# runtime's own events never do. A booking this tool then rolls back is
# followed by one RECOVERY_BOOKING_ROLLED_BACK event naming the events it
# leaves behind in the append-only log.
AUDIT_ORIGIN_FIELD = "origin"
AUDIT_ORIGIN = "tools.reconcile_execution_authorities"
RECOVERY_BOOKING_ROLLED_BACK = "RISK_ACCOUNTING_RECOVERY_BOOKING_ROLLED_BACK"


@dataclass(frozen=True, slots=True)
class ReconciliationResult:
    outcome: ReconciliationOutcome
    reason_code: str
    state_directory: str
    journal_entries: int = 0
    idempotency_records: int = 0
    repairable: int = 0
    repaired: int = 0
    refused: int = 0
    recoverable: int = 0
    recovered: int = 0
    recovery_class: str | None = None
    risk_accounting: str | None = None


def _journal_result(entry: Mapping[str, Any]) -> Mapping[str, Any] | None:
    result = entry.get("result")
    return result if isinstance(result, Mapping) else None


def _result_is_confirmed_success(request_id: str, result: Mapping[str, Any]) -> bool:
    """Whether a journal result is a complete, self-consistent COMMITTED success.

    Deliberately strict: this is the payload a repair would copy into the
    replay authority, so anything ambiguous about it disqualifies the repair
    rather than being normalized into shape.
    """
    if result.get("success") is not True:
        return False
    if str(result.get("status", "")).strip().upper() not in _CONFIRMED_STATUSES:
        return False
    if str(result.get("commit_outcome", "")).strip().upper() != CommitOutcome.COMMITTED.value:
        return False
    if str(result.get("request_id", "")).strip() != request_id:
        return False
    return bool(str(result.get("execution_id", "")).strip())


def _results_agree(result: Mapping[str, Any], record: Mapping[str, Any]) -> bool:
    """Whether an idempotency record still mirrors its journal result.

    Every field the journal holds must be present and equal in the record.
    The record may additionally carry only the two fields
    ``ExecutionIdempotencyStore.record()`` sets itself.
    """
    for field, value in result.items():
        if field not in record or record[field] != value:
            return False
    extra = set(record) - set(result)
    return extra <= _RECORD_ONLY_FIELDS


def _repaired_record_matches(result: Mapping[str, Any], record: Mapping[str, Any]) -> bool:
    """Post-write gate: a recreated record must be the journal result plus a stamp."""
    if not _results_agree(result, record):
        return False
    return _RECORD_STAMP_FIELD in record


def reconcile(
    state_directory: str | Path,
    *,
    apply: bool = False,
    journal_file: str = DEFAULT_JOURNAL_FILE,
    idempotency_file: str = DEFAULT_IDEMPOTENCY_FILE,
    financial_state_file: str = DEFAULT_FINANCIAL_STATE_FILE,
    applied_file: str = DEFAULT_APPLIED_FILE,
    closed_file: str = DEFAULT_CLOSED_FILE,
    reservation_file: str = DEFAULT_RESERVATION_FILE,
    reservation_archive_file: str = DEFAULT_RESERVATION_ARCHIVE_FILE,
    audit_file: str = DEFAULT_AUDIT_FILE,
    risk_state_file: str = DEFAULT_RISK_STATE_FILE,
    execution_mode: str | None = None,
    instrument_rules: InstrumentRuleset | None = None,
) -> ReconciliationResult:
    """Inspect one state directory's execution authorities; repair only if proven.

    Writes nothing unless ``apply`` is true AND every candidate is proven by
    all three independent durable authorities AND no other disagreement class
    exists anywhere in the book. Even then, only the idempotency file is
    written, and it is restored byte-for-byte if any post-write check fails.

    ``execution_mode`` is the runtime mode the operator states for this
    directory. Only ``"PAPER"`` enables the F-1 recovery of an interrupted
    PREPARED entry (see the module docstring); ``None`` and ``"LIVE"`` refuse
    every unresolved entry exactly as before. ``instrument_rules`` overrides
    the checked-in config for the re-derivation class only (tests).
    """
    directory = Path(state_directory)
    rendered_directory = str(directory)

    mode: ExecutionMode | None = None
    if execution_mode is not None:
        try:
            mode = ExecutionMode(str(execution_mode).strip().upper())
        except ValueError:
            return ReconciliationResult(
                ReconciliationOutcome.STATE_INVALID, "EXECUTION_MODE_INVALID", rendered_directory,
            )

    if not directory.is_dir():
        return ReconciliationResult(
            ReconciliationOutcome.STATE_INVALID, "STATE_DIRECTORY_ABSENT", rendered_directory,
        )

    journal_path = directory / journal_file
    idempotency_path = directory / idempotency_file

    journal = ExecutionTransactionJournal(journal_path)
    # Legacy v1 state is reported before unreadability so the operator is
    # sent to the migration tool rather than to a corruption investigation.
    if journal.migration_required:
        return ReconciliationResult(
            ReconciliationOutcome.STATE_INVALID, "JOURNAL_MIGRATION_REQUIRED",
            rendered_directory,
        )
    if not journal.loaded or journal.load_failed:
        return ReconciliationResult(
            ReconciliationOutcome.STATE_INVALID, "JOURNAL_UNREADABLE", rendered_directory,
        )

    idempotency = ExecutionIdempotencyStore(idempotency_path)
    if idempotency.migration_required:
        return ReconciliationResult(
            ReconciliationOutcome.STATE_INVALID, "IDEMPOTENCY_MIGRATION_REQUIRED",
            rendered_directory,
        )
    if not idempotency.loaded:
        return ReconciliationResult(
            ReconciliationOutcome.STATE_INVALID, "IDEMPOTENCY_UNREADABLE", rendered_directory,
        )

    entries = journal.entries
    completed = idempotency.completed_requests
    # Counts as found at inspection, fixed here and reported unchanged by
    # every outcome: after a repair the store holds
    # ``idempotency_records + repaired`` records.
    counts = {
        "journal_entries": len(entries),
        "idempotency_records": len(completed),
    }

    def _result(
        outcome: ReconciliationOutcome, reason: str, *,
        repairable: int = 0, repaired: int = 0, refused: int = 0,
        recoverable: int = 0, recovered: int = 0, recovery_class: str | None = None,
        risk_accounting: str | None = None,
    ) -> ReconciliationResult:
        return ReconciliationResult(
            outcome, reason, rendered_directory,
            journal_entries=counts["journal_entries"],
            idempotency_records=counts["idempotency_records"],
            repairable=repairable, repaired=repaired, refused=refused,
            recoverable=recoverable, recovered=recovered, recovery_class=recovery_class,
            risk_accounting=risk_accounting,
        )

    # -- Classification. Sorted so the outcome never depends on file order. --
    refusals: dict[str, int] = {}
    candidates: list[tuple[str, Mapping[str, Any]]] = []
    unresolved: list[str] = []

    def _refuse(reason: str) -> None:
        refusals[reason] = refusals.get(reason, 0) + 1

    for request_id in sorted(entries):
        entry = entries[request_id]
        if not isinstance(entry, Mapping):
            _refuse("JOURNAL_ENTRY_MALFORMED")
            continue

        state = str(entry.get("state", "")).strip().upper()
        if state in ExecutionTransactionJournal.UNRESOLVED_STATES:
            unresolved.append(request_id)
            continue
        if state not in {CommitOutcome.COMMITTED.value, CommitOutcome.NOT_COMMITTED.value}:
            _refuse("JOURNAL_ENTRY_MALFORMED")
            continue

        record = completed.get(request_id)

        if state == CommitOutcome.NOT_COMMITTED.value:
            # No side effect crossed the boundary, so no terminal result is
            # required. One that claims a commit contradicts the journal.
            if isinstance(record, Mapping) and str(
                record.get("commit_outcome", "")
            ).strip().upper() == CommitOutcome.COMMITTED.value:
                _refuse("AUTHORITY_RESULT_CONFLICT")
            continue

        result = _journal_result(entry)
        if result is None or not _result_is_confirmed_success(request_id, result):
            _refuse("JOURNAL_ENTRY_MALFORMED")
            continue

        if record is None:
            candidates.append((request_id, result))
            continue

        if not isinstance(record, Mapping) or not _results_agree(result, record):
            _refuse("AUTHORITY_RESULT_CONFLICT")

    # A terminal result with no journal entry at all. The journal is written
    # last in the commit sequence, so this is not a crash state - and a
    # journal entry cannot be reconstructed from a terminal result without
    # inventing the lifecycle fields it never carried.
    orphan_records = len(set(completed) - set(entries))
    if orphan_records:
        refusals["JOURNAL_ENTRY_ABSENT"] = (
            refusals.get("JOURNAL_ENTRY_ABSENT", 0) + orphan_records
        )

    # -- Unresolved entries (F-1). Only an explicitly stated PAPER mode can
    # reach the recovery planner; every other value - LIVE, or no statement
    # at all - takes the else branch and refuses exactly as this tool always
    # has. A book already refused on other grounds is never planned for: the
    # run writes nothing either way. --
    recovery_plan: _RecoveryPlan | None = None
    if unresolved:
        if mode is ExecutionMode.PAPER and not refusals:
            planned = _plan_paper_recovery(
                directory=directory, entries=entries, unresolved=unresolved,
                completed=completed,
                financial_state_file=financial_state_file, applied_file=applied_file,
                closed_file=closed_file, reservation_file=reservation_file,
                reservation_archive_file=reservation_archive_file, audit_file=audit_file,
                risk_state_file=risk_state_file, instrument_rules=instrument_rules,
            )
            if isinstance(planned, _RecoveryPlan):
                recovery_plan = planned
            else:
                _refuse(planned)
        else:
            # LIVE: a real venue's fill outcome cannot be recomputed from
            # local state. No mode: nothing proves PAPER. Already refused:
            # nothing will be written. All fail closed, as before F-1.
            for _ in unresolved:
                _refuse("JOURNAL_UNRESOLVED")

    # -- Financial-application proof for every candidate. --
    if candidates:
        applied_store = AppliedExecutionArchiveStore(directory / applied_file)
        try:
            applied_index = applied_store.load_index()
        except AppliedExecutionArchiveCorruptError:
            return _result(ReconciliationOutcome.STATE_INVALID, "APPLIED_AUTHORITY_CORRUPT")
        except AppliedExecutionArchiveConflictError:
            return _result(ReconciliationOutcome.STATE_INVALID, "APPLIED_AUTHORITY_CONFLICT")

        # ExecutionPortfolioFoundation.ready is the proof that the book's
        # applied_checkpoint agrees with this sidecar's durable tail and that
        # no transition is pending - i.e. that every applied record up to the
        # tail is confirmed committed financial state. It is the runtime's own
        # loader, never a parser written here.
        foundation = ExecutionPortfolioFoundation(
            FinancialStateStore(directory / financial_state_file),
            applied_archive=applied_store,
            closed_archive=ClosedPositionArchiveStore(directory / closed_file),
            leverage=None,   # Task 025: operator recovery keeps the book's own leverage (schema 2 or 3)
        )
        book_ready = foundation.ready

        proven: list[tuple[str, Mapping[str, Any]]] = []
        for request_id, result in candidates:
            applied = applied_index.by_idempotency_key.get(request_id)
            if (
                not book_ready
                or applied is None
                or applied.execution_id != str(result.get("execution_id", "")).strip()
            ):
                _refuse("FINANCIAL_APPLICATION_UNPROVEN")
                continue
            proven.append((request_id, result))
        candidates = proven

    if refusals:
        # Wholesale refusal: nothing is written while any class of genuine
        # disagreement remains anywhere in the book.
        reason = next(
            (name for name in _REFUSAL_PRIORITY if name in refusals),
            "RECONCILIATION_REQUIRED",
        )
        return _result(
            ReconciliationOutcome.RECONCILIATION_REQUIRED, reason,
            repairable=len(candidates), refused=sum(refusals.values()),
        )

    if recovery_plan is not None:
        # A recovery runs alone. Any idempotency repair candidates are
        # reported and left for the next run, which will see a resolved
        # journal and classify them against the recovered book.
        recovery_class = recovery_plan.recovery_class.value
        risk_accounting = recovery_plan.risk_accounting.value
        if not apply:
            return _result(
                ReconciliationOutcome.WOULD_RECOVER, "DRY_RUN",
                repairable=len(candidates), recoverable=1, recovery_class=recovery_class,
                risk_accounting=risk_accounting,
            )
        failure = _execute_recovery(
            recovery_plan, journal=journal, directory=directory,
            journal_file=journal_file, idempotency_file=idempotency_file,
            financial_state_file=financial_state_file, applied_file=applied_file,
            closed_file=closed_file, reservation_file=reservation_file,
            reservation_archive_file=reservation_archive_file,
            audit_file=audit_file, risk_state_file=risk_state_file,
        )
        if failure is not None:
            return _result(
                ReconciliationOutcome.FAILED, failure,
                repairable=len(candidates), recoverable=1, recovery_class=recovery_class,
                risk_accounting=risk_accounting,
            )
        return _result(
            ReconciliationOutcome.RECOVERED, "RECOVERY_COMPLETE",
            repairable=len(candidates), recoverable=1, recovered=1,
            recovery_class=recovery_class, risk_accounting=risk_accounting,
        )

    if not candidates:
        return _result(ReconciliationOutcome.AUTHORITIES_AGREE, "AUTHORITIES_ALREADY_AGREE")

    if not apply:
        return _result(
            ReconciliationOutcome.WOULD_RECONCILE, "DRY_RUN", repairable=len(candidates),
        )

    # -- Repair. The idempotency file is the only file written, and its exact
    # pre-run bytes are held so a failed verification restores them. --
    original_bytes = idempotency_path.read_bytes() if idempotency_path.exists() else None
    preexisting = {
        request_id: dict(record) for request_id, record in completed.items()
    }

    for request_id, result in candidates:
        if not idempotency.record(request_id, dict(result), save=False):
            _restore(idempotency_path, original_bytes)
            return _result(
                ReconciliationOutcome.FAILED, "IDEMPOTENCY_WRITE_FAILED",
                repairable=len(candidates),
            )

    if not idempotency.save():
        _restore(idempotency_path, original_bytes)
        return _result(
            ReconciliationOutcome.FAILED, "IDEMPOTENCY_WRITE_FAILED", repairable=len(candidates),
        )

    failure = _verify_repair(
        journal_path=journal_path, idempotency_path=idempotency_path,
        candidates=candidates, preexisting=preexisting,
    )
    if failure is not None:
        _restore(idempotency_path, original_bytes)
        return _result(
            ReconciliationOutcome.FAILED, failure, repairable=len(candidates),
        )

    return _result(
        ReconciliationOutcome.RECONCILED, "RECONCILIATION_COMPLETE",
        repairable=len(candidates), repaired=len(candidates),
    )


def _restore(path: Path, original_bytes: bytes | None) -> None:
    """Put the idempotency file back exactly as this run found it.

    Restoration is atomic (temp file + replace) so a failure here cannot
    leave a half-written authority behind, and a file this run created from
    nothing is removed rather than left as an empty authority.
    """
    try:
        if original_bytes is None:
            path.unlink(missing_ok=True)
            return
        temporary = path.with_suffix(path.suffix + ".restore.tmp")
        with temporary.open("wb") as stream:
            stream.write(original_bytes)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    except OSError:
        # Nothing further is safe to attempt here; the caller already returns
        # a non-zero outcome, and the operator's own backup remains the
        # authority of last resort.
        pass


def _verify_repair(
    *,
    journal_path: Path,
    idempotency_path: Path,
    candidates: list[tuple[str, Mapping[str, Any]]],
    preexisting: dict[str, dict[str, Any]],
) -> str | None:
    """Reload every authority from disk and re-run the runtime's own gates.

    Returns a fixed reason code on failure, ``None`` when the repair is
    proven good. Never trusts the in-memory objects that produced the write.
    """
    verified = ExecutionIdempotencyStore(idempotency_path)
    if not verified.loaded:
        return "POST_REPAIR_VERIFICATION_FAILED"

    for request_id, result in candidates:
        record = verified.completed_requests.get(request_id)
        if not isinstance(record, Mapping) or not _repaired_record_matches(result, record):
            return "POST_REPAIR_VERIFICATION_FAILED"

    # No record this run did not repair may have changed, and no record may
    # have disappeared: a repair must be purely additive.
    for request_id, record in preexisting.items():
        if verified.completed_requests.get(request_id) != record:
            return "POST_REPAIR_VERIFICATION_FAILED"

    verified_journal = ExecutionTransactionJournal(journal_path)
    if not verified_journal.loaded or verified_journal.load_failed:
        return "POST_REPAIR_VERIFICATION_FAILED"

    readiness = FinancialRuntimeSafetyService(
        transaction_journal=verified_journal, idempotency_store=verified,
    ).assess()
    if not readiness.ready:
        return "POST_REPAIR_RUNTIME_NOT_READY"

    # CanonicalExecutionEvidenceAdapter is the projection-replay contract for
    # evidenced LONG *opening* executions: it raises on any COMMITTED SELL by
    # design, and the runtime only wires it when a relational storage backend
    # exists. Running it over a book that holds a committed SELL would
    # therefore fail a perfectly healthy repair, so it is applied exactly
    # within its own declared domain - a book whose committed executions are
    # all BUYs - and skipped, not faked, outside it.
    committed_results = [
        entry.get("result") or {}
        for entry in verified_journal.entries.values()
        if isinstance(entry, Mapping)
        and str(entry.get("state", "")).strip().upper() == CommitOutcome.COMMITTED.value
    ]
    committed_actions = {
        str(result.get("action", "")).strip().upper() for result in committed_results
    }
    # A result recovered from applied-execution evidence (F-1) deliberately
    # carries no fill figures - they were never durably recorded and are not
    # recomputed - so it is outside the adapter's domain exactly as a SELL is.
    recovered_present = any(
        isinstance(result, Mapping)
        and isinstance(result.get(RECOVERY_RESULT_FIELD), Mapping)
        and result[RECOVERY_RESULT_FIELD].get("method")
        == RecoveryClass.COMMIT_APPLIED_EVIDENCE.value
        for result in committed_results
    )
    if committed_actions <= {"BUY"} and not recovered_present:
        try:
            CanonicalExecutionEvidenceAdapter(verified_journal, verified)()
        except IntegrityViolation:
            return "POST_REPAIR_EVIDENCE_INVALID"

    return None


# ---------------------------------------------------------------------------
# F-1 - PAPER recovery of one interrupted PREPARED entry
# ---------------------------------------------------------------------------


class _RecoveryRefused(Exception):
    """Classification stopped on a fixed refusal reason code."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


@dataclass(frozen=True)
class _RecoveryPlan:
    recovery_class: RecoveryClass
    request_id: str
    reservation_action: str | None = None  # "RELEASE" | "COMMIT"
    settled_amount: Decimal | None = None
    abandon_transition: bool = False
    evidence: ExecutionResult | None = None  # completes an interrupted apply
    result: Mapping[str, Any] | None = None  # the COMMITTED terminal result
    record_idempotency: bool = False
    risk_accounting: RiskAccounting = RiskAccounting.NOT_APPLICABLE
    request: Mapping[str, Any] | None = None  # the prepared request payload
    # RECORD by re-derivation: the pre-transition book view that is the
    # hook's ``before``, exactly as ``apply_confirmed`` saw it.
    accounting_before: Mapping[str, Any] | None = None
    # RECORD by redo: the payload of the hook's own PREPARED record whose
    # write never landed; the hook must reproduce its ``new_state``.
    accounting_redo: Mapping[str, Any] | None = None


class _PreTransitionBook:
    """Read-only book the derivation-only ExecutionManager prices against.

    The paper paths read only ``snapshot()["positions"]`` from the durable
    foundation; this supplies the pre-transition positions and nothing else,
    so the derivation cannot reach, let alone write, the real book.
    """

    ready = True

    def __init__(self, state: Mapping[str, Any]) -> None:
        self._positions = json.loads(json.dumps(state["positions"]))

    def snapshot(self) -> dict[str, Any]:
        return {"positions": json.loads(json.dumps(self._positions))}


def _reservation_ledger(
    directory: Path, reservation_file: str, reservation_archive_file: str,
) -> CapitalReservationLedger | None:
    path = directory / reservation_file
    if not path.exists():
        return None
    store = JsonReservationStore(path)
    try:
        loaded = store.load()
    except Exception as exc:
        raise _RecoveryRefused("RECOVERY_AUTHORITY_UNREADABLE") from exc
    # The allocatable bound is a runtime admission policy this tool never
    # exercises: recovery only releases or commits one existing reservation,
    # and both strictly reduce live encumbrance. The bound is therefore set to
    # exactly the encumbrance already on disk, so readiness here means "the
    # working set and its archive load and agree" and nothing more; the
    # runtime re-checks the real bound against its own policy at startup.
    live = sum(
        (item.amount for item in loaded
         if item.status in (ReservationStatus.RESERVED, ReservationStatus.INDETERMINATE)),
        Decimal("0"),
    )
    ledger = CapitalReservationLedger(
        store, live if live > 0 else Decimal("1"),
        archive=ReservationArchiveStore(directory / reservation_archive_file),
    )
    if not ledger.ready:
        raise _RecoveryRefused("RECOVERY_AUTHORITY_UNREADABLE")
    return ledger


def _require_reservation(
    reservation: CapitalReservation | None, *, required: bool,
    allowed: frozenset[ReservationStatus],
) -> None:
    """A new-risk BUY is always reserved before PREPARE; nothing else ever is."""
    if required:
        if reservation is None or reservation.status not in allowed:
            raise _RecoveryRefused("RECOVERY_EVIDENCE_AMBIGUOUS")
    elif reservation is not None:
        raise _RecoveryRefused("RECOVERY_EVIDENCE_AMBIGUOUS")


def _plan_paper_recovery(**kwargs: Any) -> _RecoveryPlan | str:
    """Classify the one unresolved entry, or return a fixed refusal reason."""
    try:
        return _classify_paper_recovery(**kwargs)
    except _RecoveryRefused as refusal:
        return refusal.reason


def _classify_paper_recovery(
    *,
    directory: Path,
    entries: Mapping[str, Any],
    unresolved: list[str],
    completed: Mapping[str, Any],
    financial_state_file: str,
    applied_file: str,
    closed_file: str,
    reservation_file: str,
    reservation_archive_file: str,
    audit_file: str,
    risk_state_file: str,
    instrument_rules: InstrumentRuleset | None,
) -> _RecoveryPlan:
    # The runtime halts on the first unresolved entry, so a crash leaves one.
    # Several at once is not a state this recovery can reason about.
    if len(unresolved) != 1:
        raise _RecoveryRefused("RECOVERY_EVIDENCE_AMBIGUOUS")
    request_id = unresolved[0]
    entry = entries[request_id]
    if str(entry.get("state", "")).strip().upper() != PREPARED_STATE:
        # COMMIT_STATUS_UNKNOWN was classified in-process as a possible side
        # effect; it is outside this recovery and refused exactly as before.
        raise _RecoveryRefused("JOURNAL_UNRESOLVED")

    request = entry.get("request")
    if not isinstance(request, Mapping) or str(request.get("request_id", "")).strip() != request_id:
        raise _RecoveryRefused("RECOVERY_EVIDENCE_AMBIGUOUS")

    # Mode proof. The operator's PAPER statement must be corroborated by the
    # prepared request itself (ExecutionManager stamps its own mode there
    # unless a decision overrides it) and contradicted by no result anywhere
    # in the journal.
    if str(request.get("mode", "")).strip().upper() != ExecutionMode.PAPER.value:
        raise _RecoveryRefused("RECOVERY_MODE_UNPROVEN")
    for other in entries.values():
        other_result = other.get("result") if isinstance(other, Mapping) else None
        if isinstance(other_result, Mapping) and other_result.get("mode") is not None:
            if str(other_result["mode"]).strip().upper() != ExecutionMode.PAPER.value:
                raise _RecoveryRefused("RECOVERY_MODE_UNPROVEN")

    action = str(request.get("action", "")).strip().upper()
    symbol = str(request.get("symbol", "")).strip().upper()
    if action not in ("BUY", "SELL") or not symbol:
        raise _RecoveryRefused("RECOVERY_EVIDENCE_AMBIGUOUS")
    reservation_required = action == "BUY" and not bool(request.get("reduce_only"))

    ledger = _reservation_ledger(directory, reservation_file, reservation_archive_file)
    reservation = ledger.get(request_id) if ledger is not None else None
    record = completed.get(request_id)

    store = FinancialStateStore(directory / financial_state_file)
    applied_store = AppliedExecutionArchiveStore(directory / applied_file)
    closed_store = ClosedPositionArchiveStore(directory / closed_file)
    try:
        transition = inspect_interrupted_transition(
            store, applied_archive=applied_store, closed_archive=closed_store,
        )
    except InterruptedTransitionError as exc:
        raise _RecoveryRefused("RECOVERY_EVIDENCE_AMBIGUOUS") from exc
    except Exception as exc:
        raise _RecoveryRefused("RECOVERY_AUTHORITY_UNREADABLE") from exc

    if transition is None:
        # The book is not mid-transition: whether this request was applied
        # is answered by the applied-execution authority directly.
        foundation = ExecutionPortfolioFoundation(
            store, applied_archive=applied_store, closed_archive=closed_store, leverage=None,
        )
        if not foundation.ready:
            raise _RecoveryRefused("RECOVERY_AUTHORITY_UNREADABLE")
        applied = applied_store.load_index().by_idempotency_key.get(request_id)

        if applied is None:
            if record is not None:
                raise _RecoveryRefused("RECOVERY_EVIDENCE_AMBIGUOUS")
            _require_reservation(
                reservation, required=reservation_required,
                allowed=frozenset((ReservationStatus.RESERVED, ReservationStatus.RELEASED)),
            )
            return _RecoveryPlan(
                RecoveryClass.ABORT_NOT_APPLIED, request_id,
                reservation_action=(
                    "RELEASE" if reservation is not None
                    and reservation.status is ReservationStatus.RESERVED else None
                ),
            )

        _require_reservation(
            reservation, required=reservation_required,
            allowed=frozenset((ReservationStatus.RESERVED, ReservationStatus.COMMITTED)),
        )
        reservation_action = (
            "COMMIT" if reservation is not None
            and reservation.status is ReservationStatus.RESERVED else None
        )
        if record is not None:
            # The terminal result was durably recorded before the crash: it is
            # the genuine result, copied, never rebuilt.
            result = {key: value for key, value in record.items() if key != _RECORD_STAMP_FIELD}
            if (
                not _result_is_confirmed_success(request_id, result)
                or str(result.get("execution_id", "")).strip() != applied.execution_id
                or str(result.get("symbol", "")).strip().upper() != symbol
                or str(result.get("action", "")).strip().upper() != action
            ):
                raise _RecoveryRefused("RECOVERY_EVIDENCE_AMBIGUOUS")
            accounting, redo = _plan_risk_accounting(
                directory=directory, audit_file=audit_file, risk_state_file=risk_state_file,
                request_id=request_id, action=action, symbol=symbol,
                execution_id=applied.execution_id, rederivation=False,
            )
            _require_redo_book(foundation, applied_store, request_id, redo)
            return _RecoveryPlan(
                RecoveryClass.COMMIT_APPLIED_EVIDENCE, request_id,
                reservation_action=reservation_action, result=result,
                risk_accounting=accounting, request=request, accounting_redo=redo,
            )
        # No terminal result survived. The result states only what the
        # authorities prove, and says how it was established; fill figures
        # were never durably recorded and are not recomputed here.
        result = {
            "success": True,
            "status": "PAPER_EXECUTED",
            "commit_outcome": CommitOutcome.COMMITTED.value,
            "message": "Recovered from durable applied-execution evidence",
            "request_id": request_id,
            "execution_id": applied.execution_id,
            "idempotency_key": request_id,
            "provenance_ref": f"transaction-journal:{request_id}",
            "symbol": symbol,
            "action": action,
            "mode": ExecutionMode.PAPER.value,
            RECOVERY_RESULT_FIELD: {
                "method": RecoveryClass.COMMIT_APPLIED_EVIDENCE.value,
                "applied_sequence": applied.sequence,
                "applied_at": applied.applied_at,
            },
        }
        accounting, redo = _plan_risk_accounting(
            directory=directory, audit_file=audit_file, risk_state_file=risk_state_file,
            request_id=request_id, action=action, symbol=symbol,
            execution_id=applied.execution_id, rederivation=False,
        )
        _require_redo_book(foundation, applied_store, request_id, redo)
        return _RecoveryPlan(
            RecoveryClass.COMMIT_APPLIED_EVIDENCE, request_id,
            reservation_action=reservation_action, result=result, record_idempotency=True,
            risk_accounting=accounting, request=request, accounting_redo=redo,
        )

    # The book holds a transition marker. It must be this request's, and a
    # terminal result cannot exist for an application that never finished.
    if transition.idempotency_key != request_id or record is not None:
        raise _RecoveryRefused("RECOVERY_EVIDENCE_AMBIGUOUS")

    if transition.applied_orphan is None and transition.closed_orphan is None:
        # Nothing was appended beyond either checkpoint: the working state
        # under the marker is the untouched pre-call book.
        _require_reservation(
            reservation, required=reservation_required,
            allowed=frozenset((ReservationStatus.RESERVED, ReservationStatus.RELEASED)),
        )
        return _RecoveryPlan(
            RecoveryClass.ABORT_NOT_APPLIED, request_id,
            reservation_action=(
                "RELEASE" if reservation is not None
                and reservation.status is ReservationStatus.RESERVED else None
            ),
            abandon_transition=True,
        )

    # The inconclusive window: a sidecar record the append-only authorities
    # can never drop exists, but the working state never committed it. The
    # only consistent resolution is to finish the application, which needs the
    # fill - re-derived, then proven against everything already on disk.
    _require_reservation(
        reservation, required=reservation_required,
        allowed=frozenset((ReservationStatus.RESERVED,)),
    )
    evidence, result = _derive_paper_result(
        directory=directory, request_payload=request, request_id=request_id,
        prepared_at=entry.get("prepared_at"),
        symbol=symbol, transition=transition, audit_file=audit_file,
        instrument_rules=instrument_rules,
    )
    settled_amount = None
    if reservation_required:
        with localcontext() as context:
            context.prec = SETTLEMENT_CONTEXT_PRECISION
            context.rounding = ROUND_HALF_EVEN
            settled_amount = (evidence.filled_quote_notional or Decimal("0")) + evidence.fee_amount
        if reservation is None or settled_amount > reservation.amount:
            raise _RecoveryRefused("RECOVERY_DERIVATION_UNAVAILABLE")
    try:
        complete_interrupted_transition(
            store, applied_archive=applied_store, closed_archive=closed_store,
            evidence=evidence, verify_only=True,
        )
    except InterruptedTransitionError as exc:
        raise _RecoveryRefused("RECOVERY_DERIVATION_UNAVAILABLE") from exc
    accounting, _ = _plan_risk_accounting(
        directory=directory, audit_file=audit_file, risk_state_file=risk_state_file,
        request_id=request_id, action=action, symbol=symbol,
        execution_id=transition.execution_id, rederivation=True,
    )
    accounting_before = None
    if accounting is RiskAccounting.RECORD:
        try:
            accounting_before = ExecutionPortfolioFoundation._pre_transition_view(
                transition
            ).snapshot()
        except Exception as exc:
            raise _RecoveryRefused("RECOVERY_DERIVATION_UNAVAILABLE") from exc
    return _RecoveryPlan(
        RecoveryClass.COMMIT_PAPER_REDERIVATION, request_id,
        reservation_action="COMMIT" if reservation_required else None,
        settled_amount=settled_amount, evidence=evidence, result=result,
        record_idempotency=True, risk_accounting=accounting, request=request,
        accounting_before=accounting_before,
    )


def _load_checked_in_instrument_rules() -> InstrumentRuleset:
    # Imported lazily: the composition root owns the canonical path, and only
    # the re-derivation class ever needs it.
    from core.application import DEFAULT_INSTRUMENT_RULES_PATH
    from core.instrument_rules import load_instrument_ruleset

    return load_instrument_ruleset(DEFAULT_INSTRUMENT_RULES_PATH)


def _derive_paper_result(
    *,
    directory: Path,
    request_payload: Mapping[str, Any],
    request_id: str,
    prepared_at: Any,
    symbol: str,
    transition: InterruptedTransition,
    audit_file: str,
    instrument_rules: InstrumentRuleset | None,
) -> tuple[ExecutionResult, dict[str, Any]]:
    """Re-derive the paper fill an interrupted application was settling.

    Uses ExecutionManager's own ``paper_execute`` - the same paper-fill logic
    - on the prepared request (whose price is the one that was live at the
    time) against the pre-transition book. Refuses unless the durable
    RISK_APPROVED audit event of the attempt that was actually prepared
    proves the request was admitted in PAPER mode under the exact
    instrument-rules digest available now, since a changed rule would change
    the fill.

    Audit writes are best-effort, so "the attempt that was prepared" is
    established, not assumed: the approval used is the latest one no later
    than the journal's ``prepared_at``, and any audit activity for the
    request between that approval and the PREPARE means a newer attempt
    began whose own approval is not on record - which refuses.
    """
    unavailable = _RecoveryRefused("RECOVERY_DERIVATION_UNAVAILABLE")
    try:
        ruleset = instrument_rules if instrument_rules is not None else _load_checked_in_instrument_rules()
        rules = ruleset.get(symbol)
    except Exception as exc:
        raise unavailable from exc
    if rules is None:
        raise unavailable

    audit_path = directory / audit_file
    if not audit_path.is_file():
        raise unavailable
    try:
        prepared_moment = datetime.fromisoformat(str(prepared_at))
        audit = AuditEventStore(audit_path, verify_on_load=True)
        history = [
            (datetime.fromisoformat(str(event.timestamp)), event)
            for event in audit.query(aggregate_id=request_id)
        ]
    except Exception as exc:
        raise unavailable from exc
    if not audit.loaded:
        raise unavailable
    try:
        approvals = [
            (moment, event) for moment, event in history
            if event.event_type == "RISK_APPROVED" and moment <= prepared_moment
        ]
        if not approvals:
            raise unavailable
        approved_moment, approval = approvals[-1]
        if any(approved_moment < moment <= prepared_moment for moment, _ in history):
            raise unavailable
    except TypeError as exc:  # naive/aware timestamp mix: not comparable
        raise unavailable from exc
    approval_mode = str((approval.metadata or {}).get("mode", "")).strip().upper()
    details = (approval.payload or {}).get("details")
    if (
        approval_mode != ExecutionMode.PAPER.value
        or not isinstance(details, Mapping)
        or details.get("instrument_rules_digest") != rules.digest
    ):
        raise unavailable

    # Registry v5.23: re-derive with the paper fee rate the original
    # execution recorded on its approval; absent means the historical
    # fee-free contract. A malformed rate makes derivation unavailable.
    try:
        paper_fee_rate = Decimal(str(details.get("paper_fee_rate", "0")))
    except Exception as exc:
        raise unavailable from exc
    if not paper_fee_rate.is_finite() or not Decimal("0") <= paper_fee_rate < Decimal("1"):
        raise unavailable

    try:
        request = ExecutionRequest.from_dict(dict(request_payload))
    except Exception as exc:
        raise unavailable from exc
    if request.request_id != request_id or request.approved_quote_allocation is None:
        raise unavailable

    try:
        with tempfile.TemporaryDirectory(prefix="atlas-recovery-derivation-") as scratch:
            scratch_path = Path(scratch)
            manager = ExecutionManager(
                mode=ExecutionManager.MODE_PAPER,
                paper_fee_rate=paper_fee_rate,
                idempotency_store=ExecutionIdempotencyStore(scratch_path / "idempotency.jsonl"),
                transaction_journal=ExecutionTransactionJournal(scratch_path / "journal.jsonl"),
                audit_store=AuditEventStore(scratch_path / "audit.jsonl"),
                audit_enabled=False,
                portfolio_foundation=_PreTransitionBook(transition.pre_state),  # type: ignore[arg-type]
                instrument_rules=ruleset,
            )
            # The durable PREPARED entry is itself the proof of admission:
            # execute() prepares only after risk_check approved the request.
            # This manager prices that one request and nothing else; its
            # stores live in this scratch directory and are discarded.
            manager._risk_admissions[request_id] = manager._risk_admission_key(request)
            derived = manager.paper_execute(request)
    except Exception as exc:
        raise unavailable from exc

    if (
        not isinstance(derived, Mapping)
        or derived.get("success") is not True
        or str(derived.get("status", "")).strip().upper() != "PAPER_EXECUTED"
    ):
        raise unavailable

    result = json.loads(json.dumps(dict(derived), default=str))
    result["execution_id"] = transition.execution_id
    result["request_id"] = request_id
    result["idempotency_key"] = request_id
    result["provenance_ref"] = f"transaction-journal:{request_id}"
    try:
        evidence = ExecutionResult.from_dict(dict(result))
    except Exception as exc:
        raise unavailable from exc
    evidence.idempotency_key = request_id
    evidence.provenance_ref = result["provenance_ref"]

    result["commit_outcome"] = CommitOutcome.COMMITTED.value
    result[RECOVERY_RESULT_FIELD] = {
        "method": RecoveryClass.COMMIT_PAPER_REDERIVATION.value,
        "instrument_rules_digest": rules.digest,
    }
    return evidence, result


# ---------------------------------------------------------------------------
# MEDIUM-1 - booking a recovered SELL's realized result into risk accounting
# ---------------------------------------------------------------------------


class _AccountingFailed(Exception):
    """The runtime's risk-accounting hook did not durably book the result."""


def _accounting_risk_engine() -> RiskEngine:
    # The hook reads exactly one thing from the engine: ``policy.version``,
    # the version the durable accounting state must carry. The composition
    # root configures only ``total_capital`` on its RiskPolicy, so the default
    # version is the one the runtime checks against. No threshold or capital
    # figure of this engine is ever consulted; ``total_capital`` is a
    # placeholder the dataclass requires.
    return RiskEngine(RiskPolicy(total_capital=Decimal("1")))


def _risk_state_key(value: Mapping[str, Any]) -> tuple[Any, ...]:
    """A stored or audited accounting state, compared numerically."""
    state = RestoredRiskState(
        datetime.fromisoformat(str(value["accounting_day_utc"])).date(),
        Decimal(str(value["realized_daily_pnl"])), Decimal(str(value["peak_equity"])),
        Decimal(str(value["current_equity"])), str(value["policy_version"]),
    )
    return (state.accounting_day_utc, state.realized_daily_pnl, state.peak_equity,
            state.current_equity, state.policy_version)


def _latest_accounting_prepared(audit: AuditEventStore, request_id: str) -> Any | None:
    prepared = [
        event for event in audit.query(correlation_id=request_id)
        if event.event_type == ExecutionManager.RISK_REALIZED_PNL_PREPARED
    ]
    return prepared[-1] if prepared else None


def _plan_risk_accounting(
    *,
    directory: Path,
    audit_file: str,
    risk_state_file: str,
    request_id: str,
    action: str,
    symbol: str,
    execution_id: str,
    rederivation: bool,
) -> tuple[RiskAccounting, Mapping[str, Any] | None]:
    """Whether a recovered COMMITTED request's realized result is booked.

    Returns the accounting action and, for a redo of a PREPARED write that
    never landed, that record's payload. Normal execution books a SELL only,
    right after ``apply_confirmed`` and before anything else durable, so a
    BUY needs nothing and a SELL is established from the hook's own
    write-ahead record against the stored state (see the module docstring).
    Refuses rather than guessing, and before anything is written.
    """
    if action != "SELL":
        return RiskAccounting.NOT_APPLICABLE, None

    audit_path = directory / audit_file
    if not audit_path.is_file():
        raise _RecoveryRefused("RISK_ACCOUNTING_EVIDENCE_UNAVAILABLE")
    today = datetime.now(UTC).date()
    try:
        audit = AuditEventStore(audit_path, verify_on_load=True)
        if not audit.loaded:
            raise ValueError("audit log not loaded")
        latest = _latest_accounting_prepared(audit, request_id)
        stored = JsonRiskStateStore(directory / risk_state_file).load(
            expected_policy_version=RiskPolicy.version, today_utc=today,
        )
    except Exception as exc:
        raise _RecoveryRefused("RECOVERY_AUTHORITY_UNREADABLE") from exc
    current = _risk_state_key(stored.to_dict())

    redo: Mapping[str, Any] | None = None
    if latest is not None:
        payload = latest.payload or {}
        try:
            previous_state = _risk_state_key(payload["previous_state"])
            new_state = _risk_state_key(payload["new_state"])
            components = payload["components"]
            for name in ("gross_realized_pnl", "exit_fee", "released_entry_fees"):
                Decimal(str(components[name]))
        except Exception as exc:
            raise _RecoveryRefused("RECOVERY_EVIDENCE_AMBIGUOUS") from exc
        if (
            str(payload.get("request_id", "")) != request_id
            or str(payload.get("execution_id", "")) != execution_id
            or str(payload.get("symbol", "")).strip().upper() != symbol
            or str(payload.get("mode", "")).strip().upper() != ExecutionMode.PAPER.value
        ):
            raise _RecoveryRefused("RECOVERY_EVIDENCE_AMBIGUOUS")
        if current == new_state and new_state != previous_state:
            # The runtime's write landed. A re-derivation completes an apply
            # that never finished, whose result can never have been booked.
            if rederivation:
                raise _RecoveryRefused("RECOVERY_EVIDENCE_AMBIGUOUS")
            return RiskAccounting.ALREADY_RECORDED, None
        if current != previous_state:
            raise _RecoveryRefused("RECOVERY_EVIDENCE_AMBIGUOUS")
        redo = None if rederivation else payload
    elif not rederivation:
        # Applied, never booked, and no durable record of the figures: the
        # book already moved, so its pre-commit view cannot be recovered.
        raise _RecoveryRefused("RISK_ACCOUNTING_EVIDENCE_UNAVAILABLE")

    # The hook books only onto today's accounting day, and a recovery never
    # rolls the day itself.
    if stored.accounting_day_utc != today:
        raise _RecoveryRefused("RISK_ACCOUNTING_DAY_NOT_CURRENT")
    return RiskAccounting.RECORD, redo


def _require_redo_book(
    foundation: ExecutionPortfolioFoundation,
    applied_store: AppliedExecutionArchiveStore,
    request_id: str,
    redo: Mapping[str, Any] | None,
) -> None:
    """A redo books against the current book as the hook's ``after``.

    That is the commit's own post-apply view only while nothing was applied
    after it and the book still holds the equity the PREPARED record saw.
    """
    if redo is None:
        return
    try:
        tail = applied_store.load_index().tail
        equity = foundation.snapshot()["equity"]
        recorded_equity = Decimal(str(redo["new_state"]["current_equity"]))
    except Exception as exc:
        raise _RecoveryRefused("RECOVERY_AUTHORITY_UNREADABLE") from exc
    if tail is None or tail.idempotency_key != request_id or equity != recorded_equity:
        raise _RecoveryRefused("RECOVERY_EVIDENCE_AMBIGUOUS")


def _redo_before(
    after: Mapping[str, Any], redo: Mapping[str, Any], symbol: str,
) -> dict[str, Any]:
    """The pre-commit view the hook's PREPARED record was derived from.

    Exactly the three figures the hook reads from ``before``, restored from
    the current book and that record's own components - the inverse of the
    hook's subtraction, so re-running the hook reproduces the recorded
    realized P&L, which ``_book_risk_accounting`` then requires.
    """
    components = redo["components"]
    held_after = after["positions"].get(symbol)
    if bool(redo.get("position_closed")) != (held_after is None):
        raise ValueError("REDO_POSITION_STATE_MISMATCH")
    with localcontext() as context:
        context.prec = SETTLEMENT_CONTEXT_PRECISION
        context.rounding = ROUND_HALF_EVEN
        entry_after = (
            Decimal(str(held_after["entry_fees"])) if held_after is not None else Decimal("0")
        )
        return {
            "realized_gross_pnl": (
                Decimal(str(after["realized_gross_pnl"]))
                - Decimal(str(components["gross_realized_pnl"]))
            ),
            "fees": Decimal(str(after["fees"])) - Decimal(str(components["exit_fee"])),
            "positions": {symbol: {"entry_fees": format(
                entry_after + Decimal(str(components["released_entry_fees"])), "f",
            )}},
        }


class _ToolOriginAuditStore(AuditEventStore):
    """The real audit log, with this tool's origin stamped on every append.

    The hook's own event types, payloads and order are untouched; only its
    metadata gains ``AUDIT_ORIGIN_FIELD``. Each appended event is also
    collected into ``written`` so a later rollback can name it.
    """

    def __init__(self, file_path: Path, *, written: list[Any], **kwargs: Any) -> None:
        super().__init__(file_path, **kwargs)
        self._written = written

    def append(self, *, metadata: Mapping[str, Any] | None = None, **kwargs: Any) -> Any:
        event = super().append(
            metadata={**dict(metadata or {}), AUDIT_ORIGIN_FIELD: AUDIT_ORIGIN}, **kwargs,
        )
        self._written.append(event)
        return event


def _record_booking_rolled_back(
    *, directory: Path, audit_file: str, risk_state_file: str, request_id: str,
    written: list[Any], original_risk_state: bytes | None, reason: str,
) -> None:
    """Append one marker naming the audit events a rolled-back booking left.

    The log is append-only and hash-chained, so those events stay; this
    event is what distinguishes them afterwards. Whether the risk-accounting
    state is back at its pre-run bytes is observed from disk, not assumed.
    Best effort: a failure here changes neither the rollback nor the result.
    """
    if not written:
        return
    try:
        path = directory / risk_state_file
        current = path.read_bytes() if path.exists() else None
        AuditEventStore(directory / audit_file, verify_on_load=True).append(
            event_type=RECOVERY_BOOKING_ROLLED_BACK,
            source=AUDIT_ORIGIN,
            aggregate_type=str(written[0].aggregate_type),
            aggregate_id=str(written[0].aggregate_id),
            payload={
                "mode": ExecutionMode.PAPER.value,
                "request_id": request_id,
                "reason": reason,
                "rolled_back_event_ids": [str(event.event_id) for event in written],
                "rolled_back_event_types": [str(event.event_type) for event in written],
                "risk_accounting_state_restored": current == original_risk_state,
            },
            correlation_id=request_id,
            causation_id=str(written[-1].event_id),
            metadata={"mode": ExecutionMode.PAPER.value, AUDIT_ORIGIN_FIELD: AUDIT_ORIGIN},
        )
    except Exception:
        pass


def _book_risk_accounting(
    plan: _RecoveryPlan, *, journal: ExecutionTransactionJournal, directory: Path,
    audit_file: str, risk_state_file: str, after: Mapping[str, Any],
    written: list[Any] | None = None,
) -> None:
    """Book the recovered SELL through ``_record_realized_risk_accounting``.

    The runtime's own hook, on a PAPER manager wired to this directory's real
    risk-accounting store and audit log, under that manager's lock and the
    journal's lock - the pair ``_finalize_durable_financial_state`` holds.
    Its idempotency and journal stores are scratch and discarded: the hook
    never touches them. Every audit event it writes is marked as this tool's
    and collected into ``written``. Any failure raises ``_AccountingFailed``.
    """
    if written is None:
        written = []
    try:
        request = ExecutionRequest.from_dict(dict(plan.request or {}))
        redo = plan.accounting_redo
        if plan.evidence is not None:
            evidence = plan.evidence
            before = plan.accounting_before
        elif redo is not None:
            evidence = ExecutionResult(
                success=True, status="PAPER_EXECUTED",
                execution_id=str(redo["execution_id"]),
                position_id=str(redo["position_id"]),
                symbol=request.symbol, action="SELL",
            )
            before = _redo_before(after, redo, request.symbol)
        else:
            raise ValueError("NO_ACCOUNTING_INPUTS")
        if before is None:
            raise ValueError("NO_ACCOUNTING_INPUTS")
        store = JsonRiskStateStore(directory / risk_state_file)
        with tempfile.TemporaryDirectory(prefix="atlas-recovery-accounting-") as scratch:
            scratch_path = Path(scratch)
            manager = ExecutionManager(
                mode=ExecutionManager.MODE_PAPER,
                idempotency_store=ExecutionIdempotencyStore(scratch_path / "idempotency.jsonl"),
                transaction_journal=ExecutionTransactionJournal(scratch_path / "journal.jsonl"),
                audit_store=_ToolOriginAuditStore(
                    directory / audit_file, written=written, verify_on_load=True,
                ),
                audit_enabled=True,
                risk_engine=_accounting_risk_engine(),
                risk_state_store=store,
            )
            with manager._lock, journal._lock:
                manager._record_realized_risk_accounting(
                    request=request, evidence=evidence, before=before, after=after,
                )
        if redo is not None:
            booked = store.load(
                expected_policy_version=RiskPolicy.version,
                today_utc=datetime.now(UTC).date(),
            )
            if _risk_state_key(booked.to_dict()) != _risk_state_key(redo["new_state"]):
                raise ValueError("REDO_DID_NOT_REPRODUCE_THE_PREPARED_STATE")
    except Exception as exc:
        raise _AccountingFailed() from exc


def _execute_recovery(
    plan: _RecoveryPlan, *, journal: ExecutionTransactionJournal, directory: Path,
    journal_file: str, idempotency_file: str, financial_state_file: str,
    applied_file: str, closed_file: str, reservation_file: str,
    reservation_archive_file: str, audit_file: str, risk_state_file: str,
) -> str | None:
    """Apply one recovery plan in the runtime's own commit order, then verify.

    Order: the financial book first, then its risk accounting (as
    ``_finalize_durable_financial_state`` books it right after
    ``apply_confirmed``), then the reservation, then the terminal result, and
    the journal resolution last - so an interruption of this tool itself
    leaves the entry still PREPARED and a rerun classifies it again from what
    did land. The one exception is a SELL re-derivation killed between its
    book completion and the hook's PREPARED record, which the rerun refuses
    (see the module docstring). Every touched file except the append-only audit log is held and
    restored to its exact pre-run bytes on any failure.
    """
    paths = [
        directory / name for name in (
            journal_file, idempotency_file, financial_state_file, applied_file,
            closed_file, reservation_file, risk_state_file,
        )
    ]
    originals = {path: (path.read_bytes() if path.exists() else None) for path in paths}

    written: list[Any] = []

    def _rollback(reason: str) -> None:
        for path, original in originals.items():
            _restore(path, original)
        _record_booking_rolled_back(
            directory=directory, audit_file=audit_file, risk_state_file=risk_state_file,
            request_id=request_id, written=written,
            original_risk_state=originals[directory / risk_state_file], reason=reason,
        )

    request_id = plan.request_id
    try:
        store = FinancialStateStore(directory / financial_state_file)
        applied_store = AppliedExecutionArchiveStore(directory / applied_file)
        closed_store = ClosedPositionArchiveStore(directory / closed_file)
        if plan.abandon_transition:
            abandon_interrupted_transition(
                store, applied_archive=applied_store, closed_archive=closed_store,
                idempotency_key=request_id,
            )
        completed = None
        if plan.evidence is not None:
            completed = complete_interrupted_transition(
                store, applied_archive=applied_store, closed_archive=closed_store,
                evidence=plan.evidence,
            )
        if plan.risk_accounting is RiskAccounting.RECORD:
            after = completed if completed is not None else ExecutionPortfolioFoundation(
                store, applied_archive=applied_store, closed_archive=closed_store, leverage=None,
            ).snapshot()
            _book_risk_accounting(
                plan, journal=journal, directory=directory, audit_file=audit_file,
                risk_state_file=risk_state_file, after=after, written=written,
            )
        if plan.reservation_action is not None:
            ledger = _reservation_ledger(directory, reservation_file, reservation_archive_file)
            if ledger is None:
                raise RuntimeError("reservation ledger absent")
            if plan.reservation_action == "RELEASE":
                ledger.release(request_id)
            else:
                ledger.commit(request_id, plan.settled_amount)
        if plan.record_idempotency:
            idempotency = ExecutionIdempotencyStore(directory / idempotency_file)
            if not idempotency.loaded or not idempotency.record(
                request_id, dict(plan.result or {}), save=True,
            ):
                raise RuntimeError("idempotency record failed")
        if plan.recovery_class is RecoveryClass.ABORT_NOT_APPLIED:
            resolved = journal.mark_not_committed(
                request_id, reason=RECOVERED_NOT_APPLIED_REASON,
            )
        else:
            resolved = journal.mark_committed(request_id, dict(plan.result or {}))
        if not resolved:
            raise RuntimeError("journal resolution failed")
    except _AccountingFailed:
        _rollback("RISK_ACCOUNTING_UPDATE_FAILED")
        return "RISK_ACCOUNTING_UPDATE_FAILED"
    except Exception:
        _rollback("RECOVERY_WRITE_FAILED")
        return "RECOVERY_WRITE_FAILED"

    failure = _verify_recovery(
        plan, directory=directory, journal_file=journal_file,
        idempotency_file=idempotency_file, financial_state_file=financial_state_file,
        applied_file=applied_file, closed_file=closed_file,
        reservation_file=reservation_file, reservation_archive_file=reservation_archive_file,
        audit_file=audit_file, risk_state_file=risk_state_file,
    )
    if failure is not None:
        _rollback(failure)
    return failure


def _verify_recovery(
    plan: _RecoveryPlan, *, directory: Path, journal_file: str, idempotency_file: str,
    financial_state_file: str, applied_file: str, closed_file: str,
    reservation_file: str, reservation_archive_file: str,
    audit_file: str, risk_state_file: str,
) -> str | None:
    """Reload every authority from disk and require the planned end state."""
    failed = "POST_RECOVERY_VERIFICATION_FAILED"
    request_id = plan.request_id
    try:
        journal = ExecutionTransactionJournal(directory / journal_file)
        if not journal.loaded or journal.load_failed or journal.has_unresolved():
            return failed
        entry = journal.entries.get(request_id) or {}
        state = str(entry.get("state", "")).strip().upper()

        idempotency = ExecutionIdempotencyStore(directory / idempotency_file)
        if not idempotency.loaded:
            return failed
        record = idempotency.completed_requests.get(request_id)

        applied_store = AppliedExecutionArchiveStore(directory / applied_file)
        foundation = ExecutionPortfolioFoundation(
            FinancialStateStore(directory / financial_state_file),
            applied_archive=applied_store,
            closed_archive=ClosedPositionArchiveStore(directory / closed_file),
            leverage=None,   # Task 025: operator recovery keeps the book's own leverage (schema 2 or 3)
        )
        if not foundation.ready:
            return failed
        applied = applied_store.load_index().by_idempotency_key.get(request_id)

        ledger = _reservation_ledger(directory, reservation_file, reservation_archive_file)
        reservation = ledger.get(request_id) if ledger is not None else None

        if plan.recovery_class is RecoveryClass.ABORT_NOT_APPLIED:
            if state != CommitOutcome.NOT_COMMITTED.value or record is not None or applied is not None:
                return failed
            if reservation is not None and reservation.status is not ReservationStatus.RELEASED:
                return failed
        else:
            result = entry.get("result")
            if (
                state != CommitOutcome.COMMITTED.value
                or not isinstance(result, Mapping)
                or not _result_is_confirmed_success(request_id, result)
                or not isinstance(record, Mapping)
                or not _results_agree(result, record)
                or applied is None
                or applied.execution_id != str(result.get("execution_id", "")).strip()
            ):
                return failed
            if reservation is not None and reservation.status is not ReservationStatus.COMMITTED:
                return failed
            if plan.risk_accounting is not RiskAccounting.NOT_APPLICABLE:
                # A COMMITTED SELL: the stored state is the one the hook's
                # latest write-ahead record for it says was written.
                latest = _latest_accounting_prepared(
                    AuditEventStore(directory / audit_file, verify_on_load=True), request_id,
                )
                stored = JsonRiskStateStore(directory / risk_state_file).load(
                    expected_policy_version=RiskPolicy.version,
                    today_utc=datetime.now(UTC).date(),
                )
                if latest is None or _risk_state_key(stored.to_dict()) != _risk_state_key(
                    (latest.payload or {})["new_state"]
                ):
                    return failed
    except Exception:
        return failed

    readiness = FinancialRuntimeSafetyService(
        transaction_journal=journal, idempotency_store=idempotency,
    ).assess()
    if not readiness.ready:
        return "POST_RECOVERY_RUNTIME_NOT_READY"
    return None


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


class _UsageExitParser(argparse.ArgumentParser):
    """argparse exits 2 on usage errors, which would collide with this tool's
    exit code 2 (action required) and make a mistyped flag look like a
    genuine authority disagreement."""

    def error(self, message: str) -> None:  # type: ignore[override]
        self.print_usage(sys.stderr)
        self.exit(EXIT_USAGE, f"{self.prog}: error: {message}\n")


def build_parser() -> argparse.ArgumentParser:
    parser = _UsageExitParser(
        prog="reconcile_execution_authorities",
        description=(
            "Verify the execution transaction journal against the execution "
            "idempotency store and the immutable applied-execution authority. "
            "Reports only, unless --apply is given; even then it repairs a "
            "missing idempotency terminal result only when all three durable "
            "authorities prove one unique terminal truth, and never writes any "
            "file other than the idempotency store."
        ),
    )
    parser.add_argument(
        "--state-directory", required=True, type=Path,
        help="Directory holding the execution state files. Required; there is "
             "no default and it is never resolved against the CWD.",
    )
    parser.add_argument(
        "--apply", action="store_true",
        help="Perform a proven repair. Without this flag the tool is a dry run "
             "and writes nothing.",
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Explicitly request the default behaviour: report only, write "
             "nothing. Cannot be combined with --apply.",
    )
    parser.add_argument(
        "--execution-mode", choices=[mode.value for mode in ExecutionMode],
        type=str.upper, default=None,
        help="The runtime execution mode of this state directory. Only PAPER "
             "enables recovery of an interrupted PREPARED journal entry from "
             "durable evidence; omitted or LIVE, unresolved entries are refused.",
    )
    parser.add_argument(
        "--json", action="store_true", dest="as_json",
        help="Emit a structured JSON result instead of the human line.",
    )
    return parser


def _exit_code(result: ReconciliationResult) -> int:
    if result.outcome is ReconciliationOutcome.FAILED:
        return EXIT_FAILED
    if result.outcome in _REFUSED_OUTCOMES:
        return EXIT_REFUSED
    return EXIT_OK


def _render_human(result: ReconciliationResult, exit_code: int) -> str:
    verdict = "OK" if exit_code == EXIT_OK else "ACTION_REQUIRED"
    return (
        f"outcome: {result.outcome.value} | "
        f"reason: {sanitize_sensitive_text(result.reason_code)} | "
        f"state_directory: {sanitize_sensitive_text(result.state_directory)} | "
        f"journal_entries: {result.journal_entries} | "
        f"idempotency_records: {result.idempotency_records} | "
        f"repairable: {result.repairable} | repaired: {result.repaired} | "
        f"refused: {result.refused} | recoverable: {result.recoverable} | "
        f"recovered: {result.recovered} | "
        f"recovery_class: {result.recovery_class or 'NONE'} | "
        f"risk_accounting: {result.risk_accounting or 'NONE'} | "
        f"verdict: {verdict} (exit {exit_code})"
    )


def _render_json(result: ReconciliationResult, exit_code: int) -> str:
    return json.dumps(
        {
            "outcome": result.outcome.value,
            "reason_code": sanitize_sensitive_text(result.reason_code),
            "exit_code": exit_code,
            "state_directory": sanitize_sensitive_text(result.state_directory),
            "journal_entries": result.journal_entries,
            "idempotency_records": result.idempotency_records,
            "repairable": result.repairable,
            "repaired": result.repaired,
            "refused": result.refused,
            "recoverable": result.recoverable,
            "recovered": result.recovered,
            "recovery_class": result.recovery_class,
            "risk_accounting": result.risk_accounting,
        },
        indent=2, sort_keys=True,
    )


def main(argv: list[str] | None = None) -> int:
    # The runtime components this tool reuses log identifiers and raw
    # exception text (the risk-accounting hook's failure line included). With
    # no handler configured, Python's last-resort handler would print them to
    # stderr, so the CLI discards them: its only output is the fixed-token
    # result below (ADR-0005).
    logging.getLogger("AtlasAI").addHandler(logging.NullHandler())
    parser = build_parser()
    arguments = parser.parse_args(argv)

    if arguments.apply and arguments.dry_run:
        parser.error("--apply and --dry-run are mutually exclusive")

    result = reconcile(
        arguments.state_directory, apply=arguments.apply,
        execution_mode=arguments.execution_mode,
    )
    exit_code = _exit_code(result)
    rendered = (
        _render_json(result, exit_code) if arguments.as_json
        else _render_human(result, exit_code)
    )
    print(rendered)
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
