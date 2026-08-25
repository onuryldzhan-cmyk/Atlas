"""
============================================================
ATLAS OPERATOR EXECUTION FINANCIAL-STATE MIGRATION (v1 -> v2 + sidecars)
============================================================

Explicit, operator-invoked, one-time migration of the legacy single-file
execution financial state (schema_version 1, holding ``closed_positions``
and ``applied_executions`` inline) into the Block 5I working-file-plus-two-
sidecars layout:

- the same path, rewritten in place as schema_version 2, holding only
  current operational state (cash, reserved_capital, realized_gross_pnl,
  fees, positions) plus ``applied_checkpoint`` / ``closed_checkpoint``
- an immutable, append-only JSON-Lines applied-execution authority
  (execution_applied_executions.jsonl)
- an immutable, append-only JSON-Lines closed-position archive
  (execution_closed_positions.jsonl)

This tool is never invoked by AtlasApplication or by
core/financial_state_bootstrap.py. A v1 file left in place is refused by the
runtime with an explicit migration-required condition
(core/execution_portfolio_foundation.py: FinancialStateMigrationRequiredError,
and core/financial_state_bootstrap.py: FINANCIAL_MIGRATION_REQUIRED). Running
this tool against a given state directory is a deliberate, one-time operator
action; there is no flag that invokes it automatically.

Migration sequence is deterministic archive order only: v1's
``closed_positions`` / ``applied_executions`` were unordered JSON maps, so
this tool assigns sequence by sorting each map's keys. It is NOT a
reconstruction of execution chronology - do not derive financial meaning
from it. Every position/execution is preserved exactly, by validating
through the same canonical record shape ``core/execution_portfolio_foundation.py``
uses at runtime, never a hand-rolled parser.

Idempotent and resumable:

- Running this tool again after a fully completed migration (the source is
  already v2) is a no-op reported as ALREADY_MIGRATED - it still validates
  both sidecars, if present, rather than assuming they are healthy.
- Running it again after a migration that durably appended some or all
  sidecar records but never reached the final working-file rewrite (a crash
  mid-migration; the source is still v1) resumes safely: it appends only the
  sidecar records not already durably present, then completes the
  working-file rewrite - provided each existing sidecar record agrees with
  what this exact source would produce at that record's own sequence
  (applied-execution identity is ``(sequence, execution_id,
  idempotency_key)``; closed-position identity is ``(sequence, canonical
  closed-position payload)`` - see ``_applied_identity`` / ``_closed_identity``).
  ``applied_at`` is deliberately excluded from applied identity: it is a
  migration-time stamp, not source data, so two independent migration runs
  are not expected to agree on it for a record already durably recorded by
  an earlier run. Because each sidecar's own ``load_index()`` already
  requires a gapless, zero-based sequence, requiring every pre-existing
  record to match this source's record at that same sequence is exactly
  equivalent to requiring the pre-existing sidecar be a valid prefix of this
  run's deterministic output - a pre-existing record at the wrong sequence,
  or one with no matching source record at all, refuses
  (REFUSED_SIDECAR_CONFLICT) before anything is written, and no existing
  archive line is ever renumbered or rewritten.
- After every pending sidecar record is appended and fsynced, both sidecars
  are reloaded from disk through their own public ``load_index()`` - never
  compared only to the in-memory records that produced the appends - and
  required to exactly reproduce this run's complete deterministic output.
  Only if that hard gate passes does the tool rewrite the working file from
  v1 to v2. If it fails, the tool returns FAILED and leaves the v1 working
  file untouched.
- The existing v1 working file remains the authoritative rollback source
  until both sidecars are durably complete, the post-append verification
  gate above passes, and the working-file rewrite (the final step)
  succeeds. A crash - or a verification failure - before that rewrite
  leaves v1 intact.
============================================================
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from enum import Enum
from pathlib import Path

_REPOSITORY_ROOT = Path(__file__).resolve().parent.parent
if str(_REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPOSITORY_ROOT))

from atlas_security import sanitize_sensitive_text  # noqa: E402
from core.execution_portfolio_foundation import (  # noqa: E402
    SCHEMA_VERSION,
    AppliedExecutionArchiveConflictError,
    AppliedExecutionArchiveCorruptError,
    AppliedExecutionArchiveStore,
    AppliedExecutionRecord,
    ClosedPositionArchiveConflictError,
    ClosedPositionArchiveCorruptError,
    ClosedPositionArchiveStore,
    FinancialStateStore,
    validate_closed_position_record,
)

EXIT_OK = 0
EXIT_USAGE = 1
EXIT_REFUSED = 2
EXIT_FAILED = 3

DEFAULT_WORKING_FILE = "execution_financial_state.json"
DEFAULT_APPLIED_FILE = "execution_applied_executions.jsonl"
DEFAULT_CLOSED_FILE = "execution_closed_positions.jsonl"

_V1_SCHEMA_VERSION = 1
_FINANCIAL_DECIMAL_FIELDS = ("cash", "reserved_capital", "realized_gross_pnl", "fees")
_POSITION_DECIMAL_FIELDS = ("base_quantity", "cost_quote", "entry_fees", "average_entry_price", "mark_price")


class MigrationOutcome(str, Enum):
    MIGRATED = "MIGRATED"
    ALREADY_MIGRATED = "ALREADY_MIGRATED"
    WOULD_MIGRATE = "WOULD_MIGRATE"
    SOURCE_ABSENT = "SOURCE_ABSENT"
    SOURCE_INVALID = "SOURCE_INVALID"
    SIDECAR_INVALID = "SIDECAR_INVALID"
    REFUSED_SIDECAR_CONFLICT = "REFUSED_SIDECAR_CONFLICT"
    FAILED = "FAILED"


_REFUSED_OUTCOMES = frozenset((
    MigrationOutcome.SOURCE_ABSENT,
    MigrationOutcome.SOURCE_INVALID,
    MigrationOutcome.SIDECAR_INVALID,
    MigrationOutcome.REFUSED_SIDECAR_CONFLICT,
))


@dataclass(frozen=True, slots=True)
class MigrationResult:
    outcome: MigrationOutcome
    reason_code: str
    working_path: str
    applied_path: str
    closed_path: str
    applied_count: int = 0
    closed_count: int = 0
    applied_appended: int = 0
    closed_appended: int = 0


def _validate_v1_financial_fields(raw: dict) -> bool:
    """Validate cash/reserved_capital/realized_gross_pnl/fees and positions.

    The same invariants ``ExecutionPortfolioFoundation._validate_state``
    checks for the current v2 shape, applied here to the v1 fields that mean
    the same thing (this module does not import the v2 validator directly
    since it no longer matches the v1 shape - ``closed_positions`` and
    ``applied_executions`` are validated separately, through the canonical
    closed-position record validator and a light shape check respectively).
    """
    try:
        for name in _FINANCIAL_DECIMAL_FIELDS:
            value = Decimal(str(raw[name]))
            if not value.is_finite() or (name != "realized_gross_pnl" and value < 0):
                return False
        positions = raw["positions"]
        if not isinstance(positions, dict):
            return False
        seen: set[str] = set()
        for symbol, item in positions.items():
            if symbol in seen or item["symbol"] != symbol or item["position_id"] in seen:
                return False
            seen.update((symbol, item["position_id"]))
            for name in _POSITION_DECIMAL_FIELDS:
                value = Decimal(str(item[name]))
                allow_zero = name == "entry_fees"
                if not value.is_finite() or value < 0 or (not allow_zero and value == 0):
                    return False
        return True
    except (InvalidOperation, ValueError, KeyError, TypeError, AttributeError):
        return False


def _applied_identity(record: AppliedExecutionRecord) -> tuple[int, str, str]:
    """Identity fields two independent migration runs must agree on.

    Excludes ``applied_at`` deliberately: v1 never recorded when an
    execution was originally applied, so this tool stamps the migration's
    own timestamp. That stamp legitimately differs between two otherwise-
    identical migration attempts and must not be treated as a conflict for
    a record an earlier run already durably archived.
    """
    return (record.sequence, record.execution_id, record.idempotency_key)


def _closed_identity(sequence: int, record: dict) -> tuple[int, dict]:
    """Identity fields two independent migration runs must agree on for a
    closed-position archive entry: sequence AND the full canonical payload.

    Mirrors ``_applied_identity`` for the closed sidecar. Unlike an applied
    record, a closed-position record has no migration-time-only field to
    exclude, so the full record participates - two records with identical
    content but different sequence are NOT the same identity, since a
    closed-position record's sequence is the only thing that fixes its
    position in the immutable archive (``ClosedPositionIndex.by_position_id``
    itself strips sequence, which is exactly why comparing that view alone
    previously let a wrong-sequence pre-existing record through undetected).
    """
    return (sequence, record)


def migrate(
    state_directory: str | Path,
    *,
    working_file: str = DEFAULT_WORKING_FILE,
    applied_file: str = DEFAULT_APPLIED_FILE,
    closed_file: str = DEFAULT_CLOSED_FILE,
    dry_run: bool = False,
) -> MigrationResult:
    """Migrate one state directory's legacy v1 financial-state file in place.

    Touches no file unless the outcome is MIGRATED (``dry_run=True`` never
    touches any file at all, regardless of outcome).
    """
    directory = Path(state_directory)
    working_path = directory / working_file
    applied_path = directory / applied_file
    closed_path = directory / closed_file

    if not working_path.exists():
        return MigrationResult(
            MigrationOutcome.SOURCE_ABSENT, "SOURCE_ABSENT",
            str(working_path), str(applied_path), str(closed_path),
        )

    try:
        raw = json.loads(working_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return MigrationResult(
            MigrationOutcome.SOURCE_INVALID, "SOURCE_UNREADABLE",
            str(working_path), str(applied_path), str(closed_path),
        )
    if not isinstance(raw, dict):
        return MigrationResult(
            MigrationOutcome.SOURCE_INVALID, "SOURCE_CORRUPT",
            str(working_path), str(applied_path), str(closed_path),
        )

    schema = raw.get("schema_version")
    if schema == SCHEMA_VERSION:
        return _verify_already_migrated(working_path, applied_path, closed_path)
    if schema != _V1_SCHEMA_VERSION:
        return MigrationResult(
            MigrationOutcome.SOURCE_INVALID, "SOURCE_UNRECOGNIZED_SCHEMA",
            str(working_path), str(applied_path), str(closed_path),
        )

    required_top_level = {
        "schema_version", "transition", "cash", "reserved_capital",
        "realized_gross_pnl", "fees", "positions", "closed_positions", "applied_executions",
    }
    if not required_top_level.issubset(raw):
        return MigrationResult(
            MigrationOutcome.SOURCE_INVALID, "SOURCE_CORRUPT",
            str(working_path), str(applied_path), str(closed_path),
        )
    if not _validate_v1_financial_fields(raw):
        return MigrationResult(
            MigrationOutcome.SOURCE_INVALID, "SOURCE_CORRUPT",
            str(working_path), str(applied_path), str(closed_path),
        )

    # Refuse a source mid-transition: step 2 of the migration ordering. A
    # pending transition means the last confirmed execution's durability is
    # itself unresolved - migrating around it could silently drop or
    # misplace that execution's evidence.
    if raw.get("transition") is not None:
        return MigrationResult(
            MigrationOutcome.SOURCE_INVALID, "SOURCE_TRANSITION_PENDING",
            str(working_path), str(applied_path), str(closed_path),
        )

    closed_positions = raw["closed_positions"]
    applied_executions = raw["applied_executions"]
    if not isinstance(closed_positions, dict) or not isinstance(applied_executions, dict):
        return MigrationResult(
            MigrationOutcome.SOURCE_INVALID, "SOURCE_CORRUPT",
            str(working_path), str(applied_path), str(closed_path),
        )
    try:
        for position_id, record in closed_positions.items():
            if not isinstance(record, dict) or record.get("position_id") != position_id:
                raise ValueError("closed position key/identity mismatch")
            validate_closed_position_record(record)
        for execution_id, idempotency_key in applied_executions.items():
            if not isinstance(execution_id, str) or not execution_id:
                raise ValueError("invalid execution_id")
            if not isinstance(idempotency_key, str) or not idempotency_key:
                raise ValueError("invalid idempotency_key")
    except (ValueError, TypeError, AttributeError):
        return MigrationResult(
            MigrationOutcome.SOURCE_INVALID, "SOURCE_CORRUPT",
            str(working_path), str(applied_path), str(closed_path),
        )

    # Step 3: construct canonical applied records. Deterministic archive
    # sequence only (sorted by key) - see the module docstring.
    closed_items = sorted(closed_positions.items(), key=lambda kv: kv[0])
    migration_timestamp = datetime.now(UTC).isoformat()
    applied_records = [
        AppliedExecutionRecord(sequence, execution_id, idempotency_key, migration_timestamp)
        for sequence, (execution_id, idempotency_key) in
        enumerate(sorted(applied_executions.items(), key=lambda kv: kv[0]))
    ]

    applied_store = AppliedExecutionArchiveStore(applied_path)
    already_applied: dict[str, AppliedExecutionRecord] = {}
    if applied_path.exists():
        try:
            already_applied = applied_store.load_index().by_execution_id
        except AppliedExecutionArchiveCorruptError:
            return MigrationResult(
                MigrationOutcome.SIDECAR_INVALID, "APPLIED_SIDECAR_CORRUPT",
                str(working_path), str(applied_path), str(closed_path),
            )
        except AppliedExecutionArchiveConflictError:
            return MigrationResult(
                MigrationOutcome.SIDECAR_INVALID, "APPLIED_SIDECAR_CONFLICT",
                str(working_path), str(applied_path), str(closed_path),
            )
        expected_by_execution_id = {record.execution_id: record for record in applied_records}
        for execution_id, existing_record in already_applied.items():
            expected_record = expected_by_execution_id.get(execution_id)
            if expected_record is None or _applied_identity(expected_record) != _applied_identity(existing_record):
                return MigrationResult(
                    MigrationOutcome.REFUSED_SIDECAR_CONFLICT, "APPLIED_SIDECAR_DOES_NOT_MATCH_SOURCE",
                    str(working_path), str(applied_path), str(closed_path),
                )

    closed_store = ClosedPositionArchiveStore(closed_path)
    already_closed: dict[str, dict] = {}
    if closed_path.exists():
        try:
            closed_index = closed_store.load_index()
        except ClosedPositionArchiveCorruptError:
            return MigrationResult(
                MigrationOutcome.SIDECAR_INVALID, "CLOSED_SIDECAR_CORRUPT",
                str(working_path), str(applied_path), str(closed_path),
            )
        except ClosedPositionArchiveConflictError:
            return MigrationResult(
                MigrationOutcome.SIDECAR_INVALID, "CLOSED_SIDECAR_CONFLICT",
                str(working_path), str(applied_path), str(closed_path),
            )
        already_closed = closed_index.by_position_id
        # Identity includes sequence (see _closed_identity) - NOT just
        # closed_index.by_position_id, which strips it. Comparing content
        # alone would accept a pre-existing record whose sequence disagrees
        # with this source, and the append loop below would then durably
        # write a second, colliding record at that record's true sequence:
        # a non-monotonic, corrupt archive committed as if migration
        # succeeded. Requiring each pre-existing record to match this
        # source's record at that record's own sequence is exactly
        # "the pre-existing archive is a valid prefix of this run's
        # deterministic output" - see the module docstring.
        expected_identity_by_position_id = {
            position_id: _closed_identity(sequence, record)
            for sequence, (position_id, record) in enumerate(closed_items)
        }
        for position_id, existing_record in already_closed.items():
            existing_sequence = closed_index.sequence_by_position_id[position_id]
            existing_identity = _closed_identity(existing_sequence, existing_record)
            if expected_identity_by_position_id.get(position_id) != existing_identity:
                return MigrationResult(
                    MigrationOutcome.REFUSED_SIDECAR_CONFLICT, "CLOSED_SIDECAR_DOES_NOT_MATCH_SOURCE",
                    str(working_path), str(applied_path), str(closed_path),
                )

    if dry_run:
        return MigrationResult(
            MigrationOutcome.WOULD_MIGRATE, "DRY_RUN",
            str(working_path), str(applied_path), str(closed_path),
            applied_count=len(applied_records), closed_count=len(closed_items),
        )

    # Steps 4-5: append each sidecar's missing records, fsync both (append()
    # fsyncs per-line). The v1 working file is untouched so far - it remains
    # the authoritative rollback source if anything below fails.
    closed_appended = 0
    applied_appended = 0
    try:
        for sequence, (position_id, record) in enumerate(closed_items):
            if position_id not in already_closed:
                closed_store.append(sequence, record)
                closed_appended += 1
        for record in applied_records:
            if record.execution_id not in already_applied:
                applied_store.append(record)
                applied_appended += 1
    except Exception:
        # ADR-0005: the reason code an operator sees is a fixed token. The
        # underlying exception's text can carry an execution_id, an
        # idempotency_key, a position_id, or a raw filesystem path, none of
        # which may reach this tool's output; the phase is what the operator
        # actually needs, and truncating the prose would not make it safe.
        return MigrationResult(
            MigrationOutcome.FAILED, "MIGRATION_WRITE_FAILED:SIDECAR_APPEND",
            str(working_path), str(applied_path), str(closed_path),
            applied_count=len(applied_records), closed_count=len(closed_items),
            applied_appended=applied_appended, closed_appended=closed_appended,
        )

    # Step 6 (hard gate): reload BOTH sidecars from disk through their own
    # public load_index() - never trust the in-memory records that produced
    # the appends above - and require them to exactly reproduce this run's
    # complete deterministic output. The v1 source is rewritten only if this
    # passes; on failure it is left untouched and nothing is claimed migrated.
    verification_failure = _verify_post_append(applied_path, closed_path, applied_records, closed_items)
    if verification_failure is not None:
        return MigrationResult(
            MigrationOutcome.FAILED, verification_failure,
            str(working_path), str(applied_path), str(closed_path),
            applied_count=len(applied_records), closed_count=len(closed_items),
            applied_appended=applied_appended, closed_appended=closed_appended,
        )

    try:
        # Step 7: rewrite the working state LAST, as v2, with checkpoints
        # pointing at the exact tail each sidecar now holds. This is the
        # single commit point - a crash before this line leaves v1 intact
        # with both sidecars durably resumable and verified; a crash after
        # it leaves a fully migrated v2 book.
        working_payload = {
            "schema_version": SCHEMA_VERSION, "transition": None,
            "cash": raw["cash"], "reserved_capital": raw["reserved_capital"],
            "realized_gross_pnl": raw["realized_gross_pnl"], "fees": raw["fees"],
            "positions": raw["positions"],
            "applied_checkpoint": (
                {"sequence": applied_records[-1].sequence, "execution_id": applied_records[-1].execution_id,
                 "idempotency_key": applied_records[-1].idempotency_key}
                if applied_records else None
            ),
            "closed_checkpoint": (
                {"sequence": len(closed_items) - 1, "position_id": closed_items[-1][0]}
                if closed_items else None
            ),
        }
        FinancialStateStore(working_path).save(working_payload)
    except Exception:
        # Fixed token for the same reason as the sidecar-append failure
        # above: no exception prose, identifier, or path-dependent state
        # content ever becomes an operator-visible reason code.
        return MigrationResult(
            MigrationOutcome.FAILED, "MIGRATION_WRITE_FAILED:WORKING_STATE_REWRITE",
            str(working_path), str(applied_path), str(closed_path),
            applied_count=len(applied_records), closed_count=len(closed_items),
            applied_appended=applied_appended, closed_appended=closed_appended,
        )

    return MigrationResult(
        MigrationOutcome.MIGRATED, "MIGRATION_COMPLETE",
        str(working_path), str(applied_path), str(closed_path),
        applied_count=len(applied_records), closed_count=len(closed_items),
        applied_appended=applied_appended, closed_appended=closed_appended,
    )


def _verify_post_append(
    applied_path: Path, closed_path: Path,
    applied_records: list[AppliedExecutionRecord], closed_items: list[tuple[str, dict]],
) -> str | None:
    """Reload both sidecars from disk and require an exact match to the
    complete deterministic migration output. Returns a fixed reason code if
    verification fails, else ``None``. Never embeds raw exception text: the
    caller uses this reason_code as an operator-visible token.
    """
    try:
        verified_applied = AppliedExecutionArchiveStore(applied_path).load_index()
    except (AppliedExecutionArchiveCorruptError, AppliedExecutionArchiveConflictError):
        return "POST_APPEND_VERIFICATION_FAILED:APPLIED_SIDECAR"
    expected_applied = {record.execution_id: _applied_identity(record) for record in applied_records}
    actual_applied = {
        execution_id: _applied_identity(record)
        for execution_id, record in verified_applied.by_execution_id.items()
    }
    if actual_applied != expected_applied:
        return "POST_APPEND_VERIFICATION_FAILED:APPLIED_SIDECAR"

    try:
        verified_closed = ClosedPositionArchiveStore(closed_path).load_index()
    except (ClosedPositionArchiveCorruptError, ClosedPositionArchiveConflictError):
        return "POST_APPEND_VERIFICATION_FAILED:CLOSED_SIDECAR"
    expected_closed = {
        position_id: _closed_identity(sequence, record)
        for sequence, (position_id, record) in enumerate(closed_items)
    }
    actual_closed = {
        position_id: _closed_identity(verified_closed.sequence_by_position_id[position_id], record)
        for position_id, record in verified_closed.by_position_id.items()
    }
    if actual_closed != expected_closed:
        return "POST_APPEND_VERIFICATION_FAILED:CLOSED_SIDECAR"
    return None


def _verify_already_migrated(working_path: Path, applied_path: Path, closed_path: Path) -> MigrationResult:
    """The working file is already v2 - confirm both sidecars, if any, are healthy."""
    if applied_path.exists():
        try:
            AppliedExecutionArchiveStore(applied_path).load_index()
        except AppliedExecutionArchiveCorruptError:
            return MigrationResult(
                MigrationOutcome.SIDECAR_INVALID, "APPLIED_SIDECAR_CORRUPT",
                str(working_path), str(applied_path), str(closed_path),
            )
        except AppliedExecutionArchiveConflictError:
            return MigrationResult(
                MigrationOutcome.SIDECAR_INVALID, "APPLIED_SIDECAR_CONFLICT",
                str(working_path), str(applied_path), str(closed_path),
            )
    if closed_path.exists():
        try:
            ClosedPositionArchiveStore(closed_path).load_index()
        except ClosedPositionArchiveCorruptError:
            return MigrationResult(
                MigrationOutcome.SIDECAR_INVALID, "CLOSED_SIDECAR_CORRUPT",
                str(working_path), str(applied_path), str(closed_path),
            )
        except ClosedPositionArchiveConflictError:
            return MigrationResult(
                MigrationOutcome.SIDECAR_INVALID, "CLOSED_SIDECAR_CONFLICT",
                str(working_path), str(applied_path), str(closed_path),
            )
    return MigrationResult(
        MigrationOutcome.ALREADY_MIGRATED, "SOURCE_ALREADY_V2",
        str(working_path), str(applied_path), str(closed_path),
    )


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


class _UsageExitParser(argparse.ArgumentParser):
    """argparse exits 2 on usage errors, which would collide with this
    tool's exit code 2 (refused/action-required) and make a mistyped flag
    look like a migration conflict."""

    def error(self, message: str) -> None:  # type: ignore[override]
        self.print_usage(sys.stderr)
        self.exit(EXIT_USAGE, f"{self.prog}: error: {message}\n")


def build_parser() -> argparse.ArgumentParser:
    parser = _UsageExitParser(
        prog="migrate_execution_financial_state",
        description=(
            "One-time operator migration of a legacy v1 execution financial-"
            "state file to the Block 5I v2 working file + immutable applied-"
            "execution / closed-position sidecars. Never invoked "
            "automatically; never overwrites an existing sidecar unless it "
            "provably matches this exact migration."
        ),
    )
    parser.add_argument(
        "--state-directory", required=True, type=Path,
        help="Directory containing execution_financial_state.json. Required; "
             "there is no default.",
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Report what the migration would do. Creates and modifies nothing.",
    )
    parser.add_argument(
        "--json", action="store_true", dest="as_json",
        help="Emit a structured JSON result instead of the human line.",
    )
    return parser


def _exit_code(result: MigrationResult) -> int:
    if result.outcome is MigrationOutcome.FAILED:
        return EXIT_FAILED
    if result.outcome in _REFUSED_OUTCOMES:
        return EXIT_REFUSED
    return EXIT_OK


def _render_human(result: MigrationResult, exit_code: int) -> str:
    verdict = "OK" if exit_code == EXIT_OK else "ACTION_REQUIRED"
    return (
        f"outcome: {result.outcome.value} | reason: {sanitize_sensitive_text(result.reason_code)} | "
        f"working: {sanitize_sensitive_text(result.working_path)} | "
        f"applied: {sanitize_sensitive_text(result.applied_path)} "
        f"(total={result.applied_count}, appended_this_run={result.applied_appended}) | "
        f"closed: {sanitize_sensitive_text(result.closed_path)} "
        f"(total={result.closed_count}, appended_this_run={result.closed_appended}) | "
        f"verdict: {verdict} (exit {exit_code})"
    )


def _render_json(result: MigrationResult, exit_code: int) -> str:
    return json.dumps(
        {
            "outcome": result.outcome.value,
            "reason_code": sanitize_sensitive_text(result.reason_code),
            "exit_code": exit_code,
            "working_path": sanitize_sensitive_text(result.working_path),
            "applied_path": sanitize_sensitive_text(result.applied_path),
            "closed_path": sanitize_sensitive_text(result.closed_path),
            "applied_count": result.applied_count,
            "closed_count": result.closed_count,
            "applied_appended": result.applied_appended,
            "closed_appended": result.closed_appended,
        },
        indent=2, sort_keys=True,
    )


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    arguments = parser.parse_args(argv)

    result = migrate(arguments.state_directory, dry_run=arguments.dry_run)
    exit_code = _exit_code(result)
    rendered = (
        _render_json(result, exit_code) if arguments.as_json
        else _render_human(result, exit_code)
    )
    print(rendered)
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
