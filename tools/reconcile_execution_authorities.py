"""
============================================================
ATLAS OPERATOR EXECUTION-AUTHORITY RECONCILIATION
============================================================

Verify-first, fail-closed operator inspection of the paired execution
authorities in one state directory, with one narrowly-proven repair.

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

What it will never do
---------------------
- Guess which authority is right when two disagree.
- Reconstruct a journal entry from an idempotency record. The journal owns
  commit-outcome and lifecycle semantics (``prepared_at``, the prepared
  request payload) that a terminal result simply does not contain, and
  fabricating them would fabricate evidence.
- Repair anything while any unresolved journal entry (PREPARED /
  COMMIT_STATUS_UNKNOWN) exists. An unresolved transaction is a live
  question about whether money moved; reconciling around it could bury it.
- Repair anything when any other disagreement class is present anywhere in
  the book. The tool refuses wholesale, so an operator resolves the conflict
  before any write happens.
- Write the journal, either sidecar, the financial state file, or the audit
  log. The idempotency store is the only file this tool can ever modify.
- Delete, prune, truncate, or reset anything.

Output safety (ADR-0005)
------------------------
Reason codes are fixed tokens. No request_id, execution_id, position_id,
order_id, state-file content, or raw exception text ever reaches stdout -
only outcomes, fixed tokens, counts, and the sanitized state-directory path.

Exit codes
----------
0  authorities agree, a dry run completed, or a repair completed and
   verified
1  CLI usage error
2  action required: a genuine disagreement this tool refuses to resolve, or
   an unreadable/corrupt authority. Nothing was written.
3  a repair was attempted and failed. The idempotency file was restored
   byte-for-byte to its pre-run contents.
============================================================
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any, Mapping

_REPOSITORY_ROOT = Path(__file__).resolve().parent.parent
if str(_REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPOSITORY_ROOT))

from atlas_security import sanitize_sensitive_text  # noqa: E402
from core.execution_idempotency_store import ExecutionIdempotencyStore  # noqa: E402
from core.execution_manager import ExecutionManager  # noqa: E402
from core.execution_portfolio_foundation import (  # noqa: E402
    AppliedExecutionArchiveConflictError,
    AppliedExecutionArchiveCorruptError,
    AppliedExecutionArchiveStore,
    ClosedPositionArchiveStore,
    ExecutionPortfolioFoundation,
    FinancialStateStore,
)
from core.execution_transaction_journal import (  # noqa: E402
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
    RECONCILIATION_REQUIRED = "RECONCILIATION_REQUIRED"
    STATE_INVALID = "STATE_INVALID"
    FAILED = "FAILED"


_REFUSED_OUTCOMES = frozenset((
    ReconciliationOutcome.RECONCILIATION_REQUIRED,
    ReconciliationOutcome.STATE_INVALID,
))


# Refusal classes, most severe first. The order is fixed so a book holding
# several disagreement classes always reports the same reason code.
_REFUSAL_PRIORITY = (
    "JOURNAL_UNRESOLVED",
    "JOURNAL_ENTRY_MALFORMED",
    "AUTHORITY_RESULT_CONFLICT",
    "JOURNAL_ENTRY_ABSENT",
    "FINANCIAL_APPLICATION_UNPROVEN",
)


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
) -> ReconciliationResult:
    """Inspect one state directory's execution authorities; repair only if proven.

    Writes nothing unless ``apply`` is true AND every candidate is proven by
    all three independent durable authorities AND no other disagreement class
    exists anywhere in the book. Even then, only the idempotency file is
    written, and it is restored byte-for-byte if any post-write check fails.
    """
    directory = Path(state_directory)
    rendered_directory = str(directory)

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
    ) -> ReconciliationResult:
        return ReconciliationResult(
            outcome, reason, rendered_directory,
            journal_entries=counts["journal_entries"],
            idempotency_records=counts["idempotency_records"],
            repairable=repairable, repaired=repaired, refused=refused,
        )

    # -- Classification. Sorted so the outcome never depends on file order. --
    refusals: dict[str, int] = {}
    candidates: list[tuple[str, Mapping[str, Any]]] = []

    def _refuse(reason: str) -> None:
        refusals[reason] = refusals.get(reason, 0) + 1

    for request_id in sorted(entries):
        entry = entries[request_id]
        if not isinstance(entry, Mapping):
            _refuse("JOURNAL_ENTRY_MALFORMED")
            continue

        state = str(entry.get("state", "")).strip().upper()
        if state in ExecutionTransactionJournal.UNRESOLVED_STATES:
            _refuse("JOURNAL_UNRESOLVED")
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
    committed_actions = {
        str((entry.get("result") or {}).get("action", "")).strip().upper()
        for entry in verified_journal.entries.values()
        if isinstance(entry, Mapping)
        and str(entry.get("state", "")).strip().upper() == CommitOutcome.COMMITTED.value
    }
    if committed_actions <= {"BUY"}:
        try:
            CanonicalExecutionEvidenceAdapter(verified_journal, verified)()
        except IntegrityViolation:
            return "POST_REPAIR_EVIDENCE_INVALID"

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
        f"refused: {result.refused} | verdict: {verdict} (exit {exit_code})"
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
        },
        indent=2, sort_keys=True,
    )


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    arguments = parser.parse_args(argv)

    if arguments.apply and arguments.dry_run:
        parser.error("--apply and --dry-run are mutually exclusive")

    result = reconcile(arguments.state_directory, apply=arguments.apply)
    exit_code = _exit_code(result)
    rendered = (
        _render_json(result, exit_code) if arguments.as_json
        else _render_human(result, exit_code)
    )
    print(rendered)
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
