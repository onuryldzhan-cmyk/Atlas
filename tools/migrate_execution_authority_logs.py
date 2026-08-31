"""
============================================================
ATLAS OPERATOR EXECUTION-AUTHORITY LOG MIGRATION (v1 -> v2)
============================================================

Convert the two whole-file v1 execution authorities into the Block 5K
append-only logs, verify-first and fail-closed.

What changed
------------
Before Block 5K both authorities persisted one JSON object that was
rewritten in full on every write:

    execution_transaction_journal.json   {"version":"1.0","entries":{...}}
    execution_idempotency.json           {"version":"1.0","completed_requests":{...}}

They are now versioned append-only JSON-Lines logs:

    execution_transaction_journal.jsonl
    execution_idempotency.jsonl

The runtime never reinterprets a v1 file. If one is present while its v2 log
is absent, the store reports ``migration_required``, refuses to load, and
Atlas halts rather than treating real history as an empty authority - which
would let every already-completed request execute a second time. This tool
is the only supported path across that boundary, and it is deliberately
operator-invoked: nothing migrates automatically.

What it does, in order, per authority
-------------------------------------
1. Read the v1 file through exactly the normalization the v1 loader applied,
   so the migrated log holds precisely the authority the v1 runtime held in
   memory - no more, no less.
2. Refuse if the v1 file is unreadable, or holds a state the v2 authority
   would reject rather than silently repair.
3. If the v2 log already exists, require it to be exactly this run's
   deterministic output. An equal log means a previous run was interrupted
   after writing it, so this run resumes; anything else is a conflict and
   nothing is written.
4. Write the v2 log atomically (temporary file, fsync, replace).
5. Reload it through the runtime's own store and require the reconstructed
   authority to equal the v1 authority exactly. The v1 file is still
   untouched at this point and remains the rollback source.
6. Only then retire the v1 file by renaming it to ``<name>.migrated``. It is
   never deleted, truncated, or overwritten.

Re-running after a completed migration reports ``ALREADY_ON_V2`` and writes
nothing. Re-running after an interruption resumes from whichever step was
reached.

Output safety (ADR-0005)
------------------------
Reason codes are fixed tokens. No request_id, execution_id, order payload,
state-file content, or raw exception text ever reaches stdout - only
outcomes, fixed tokens, counts, and sanitized paths.

Exit codes
----------
0  nothing to migrate, already migrated, a dry run completed, or a
   migration completed and verified
1  CLI usage error
2  action required: legacy state this tool refuses to convert, or a
   conflicting destination. Nothing was written.
3  a migration was attempted and failed. The v1 file is intact.
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

from atlas_security import sanitize_sensitive_data, sanitize_sensitive_text  # noqa: E402
from core.durable_append_log import (  # noqa: E402
    DurableAppendLog,
    DurableAppendLogCorruptError,
)
from core.execution_idempotency_store import ExecutionIdempotencyStore  # noqa: E402
from core.execution_transaction_journal import (  # noqa: E402
    ExecutionTransactionJournal,
)

EXIT_OK = 0
EXIT_USAGE = 1
EXIT_REFUSED = 2
EXIT_FAILED = 3

IDEMPOTENCY_AUTHORITY = "idempotency"
JOURNAL_AUTHORITY = "transaction_journal"

LEGACY_ARCHIVE_SUFFIX = ".migrated"


class AuthorityOutcome(str, Enum):
    NOTHING_TO_MIGRATE = "NOTHING_TO_MIGRATE"
    ALREADY_MIGRATED = "ALREADY_MIGRATED"
    WOULD_MIGRATE = "WOULD_MIGRATE"
    MIGRATED = "MIGRATED"
    REFUSED = "REFUSED"
    FAILED = "FAILED"


_REFUSED_OUTCOMES = frozenset((AuthorityOutcome.REFUSED,))
_FAILED_OUTCOMES = frozenset((AuthorityOutcome.FAILED,))


@dataclass(frozen=True, slots=True)
class AuthorityMigrationResult:
    authority: str
    outcome: AuthorityOutcome
    reason_code: str
    legacy_path: str
    log_path: str
    records: int = 0
    filtered: int = 0


class _LegacySourceInvalid(ValueError):
    """The v1 file holds state the v2 authority would refuse to load."""


# ---------------------------------------------------------------------------
# Legacy readers - the v1 loaders' normalization, restated once and only here
# ---------------------------------------------------------------------------


def _read_legacy_object(path: Path, container: str) -> Mapping[str, Any]:
    with path.open("r", encoding="utf-8") as stream:
        payload = json.load(stream)
    if not isinstance(payload, Mapping):
        raise _LegacySourceInvalid("legacy file is not an object")
    records = payload.get(container, {})
    if not isinstance(records, Mapping):
        raise _LegacySourceInvalid("legacy container is not a mapping")
    return records


def _legacy_idempotency_records(path: Path) -> tuple[list[dict[str, Any]], int]:
    """v1 ``completed_requests`` as deterministic v2 payloads.

    Mirrors ``ExecutionIdempotencyStore`` v1.0's own load(): blank ids and
    non-mapping results are skipped, payloads are sanitized, FAILED/ERROR
    results are dropped, and ``request_id`` is defaulted. Those records were
    never part of the v1 runtime's authority, so carrying them over would
    migrate more than the store actually held.
    """
    raw_records = _read_legacy_object(path, "completed_requests")
    payloads: list[dict[str, Any]] = []
    filtered = 0

    for raw_request_id in sorted(str(key) for key in raw_records):
        request_id = raw_request_id.strip()
        raw_result = raw_records[raw_request_id]
        if not request_id or not isinstance(raw_result, Mapping):
            filtered += 1
            continue
        result = sanitize_sensitive_data(raw_result)
        if not isinstance(result, Mapping):
            filtered += 1
            continue
        result = dict(result)
        status = str(result.get("status", "UNKNOWN")).strip().upper()
        if status in ExecutionIdempotencyStore.FAILURE_STATUSES:
            filtered += 1
            continue
        result.setdefault("request_id", request_id)
        payloads.append({"request_id": request_id, "result": result})

    return payloads, filtered


def _legacy_journal_records(path: Path) -> tuple[list[dict[str, Any]], int]:
    """v1 ``entries`` as deterministic v2 lifecycle events.

    Each surviving entry becomes one event at the state it already held, so
    replaying the migrated log reconstructs exactly the v1 entry map. An
    entry whose state is not one this journal's lifecycle defines is refused
    rather than normalized: a v2 log holding it would fail closed on every
    subsequent load, and guessing which state was meant would invent
    commit-outcome evidence.
    """
    raw_entries = _read_legacy_object(path, "entries")
    payloads: list[dict[str, Any]] = []
    filtered = 0

    for raw_request_id in sorted(str(key) for key in raw_entries):
        request_id = raw_request_id.strip()
        raw_entry = raw_entries[raw_request_id]
        if not request_id or not isinstance(raw_entry, Mapping):
            filtered += 1
            continue
        entry = sanitize_sensitive_data(raw_entry)
        if not isinstance(entry, Mapping):
            filtered += 1
            continue
        entry = dict(entry)
        state = str(entry.get("state", "")).strip().upper()
        if state not in ExecutionTransactionJournal.LIFECYCLE_STATES:
            raise _LegacySourceInvalid("legacy journal entry has an unknown state")
        payloads.append(
            {"request_id": request_id, "state": state, "entry": entry}
        )

    return payloads, filtered


# ---------------------------------------------------------------------------
# Verification
# ---------------------------------------------------------------------------


def _expected_idempotency_map(payloads: list[dict[str, Any]]) -> dict[str, Any]:
    """What the v2 store must hold in memory after reloading these payloads."""
    expected: dict[str, Any] = {}
    for payload in payloads:
        result = sanitize_sensitive_data(payload["result"])
        result = dict(result)
        result.setdefault("request_id", payload["request_id"])
        expected[payload["request_id"]] = result
    return expected


def _expected_journal_map(payloads: list[dict[str, Any]]) -> dict[str, Any]:
    expected: dict[str, Any] = {}
    for payload in payloads:
        entry = sanitize_sensitive_data(payload["entry"])
        expected[payload["request_id"]] = dict(entry)
    return expected


def _verify_idempotency(log_path: Path, payloads: list[dict[str, Any]]) -> bool:
    store = ExecutionIdempotencyStore(log_path)
    if not store.loaded or store.migration_required:
        return False
    return store.completed_requests == _expected_idempotency_map(payloads)


def _verify_journal(log_path: Path, payloads: list[dict[str, Any]]) -> bool:
    journal = ExecutionTransactionJournal(log_path)
    if not journal.loaded or journal.load_failed or journal.migration_required:
        return False
    return journal.entries == _expected_journal_map(payloads)


# ---------------------------------------------------------------------------
# Migration
# ---------------------------------------------------------------------------


_AUTHORITY_SPECS = {
    IDEMPOTENCY_AUTHORITY: (
        "execution_idempotency",
        ExecutionIdempotencyStore.LOG_NAME,
        ExecutionIdempotencyStore.LOG_VERSION,
        False,
        _legacy_idempotency_records,
        _verify_idempotency,
    ),
    JOURNAL_AUTHORITY: (
        "execution_transaction_journal",
        ExecutionTransactionJournal.LOG_NAME,
        ExecutionTransactionJournal.LOG_VERSION,
        True,
        _legacy_journal_records,
        _verify_journal,
    ),
}


def migrate_authority(
    state_directory: str | Path,
    authority: str,
    *,
    apply: bool = False,
) -> AuthorityMigrationResult:
    """Migrate one authority's v1 file to its v2 log, or explain why not."""
    stem, log_name, log_version, default_str, read_legacy, verify = _AUTHORITY_SPECS[
        authority
    ]

    directory = Path(state_directory)
    legacy_path = directory / f"{stem}.json"
    log_path = directory / f"{stem}.jsonl"
    archive_path = legacy_path.with_name(legacy_path.name + LEGACY_ARCHIVE_SUFFIX)

    def _result(
        outcome: AuthorityOutcome, reason: str, *, records: int = 0, filtered: int = 0,
    ) -> AuthorityMigrationResult:
        return AuthorityMigrationResult(
            authority, outcome, reason, str(legacy_path), str(log_path),
            records=records, filtered=filtered,
        )

    if not legacy_path.is_file():
        if log_path.exists():
            return _result(AuthorityOutcome.ALREADY_MIGRATED, "ALREADY_ON_V2")
        return _result(AuthorityOutcome.NOTHING_TO_MIGRATE, "NO_LEGACY_STATE")

    if archive_path.exists():
        # Both a live v1 file and a retired one. Which is authority is an
        # operator question, not one this tool may answer by picking.
        return _result(AuthorityOutcome.REFUSED, "LEGACY_ARCHIVE_EXISTS")

    try:
        payloads, filtered = read_legacy(legacy_path)
    except _LegacySourceInvalid:
        return _result(AuthorityOutcome.REFUSED, "LEGACY_SOURCE_INVALID")
    except Exception:
        return _result(AuthorityOutcome.REFUSED, "LEGACY_SOURCE_UNREADABLE")

    log = DurableAppendLog(
        log_path, log_name=log_name, version=log_version, json_default_str=default_str,
    )

    destination_ready = False
    if log_path.exists():
        try:
            existing = log.read()
        except DurableAppendLogCorruptError:
            return _result(
                AuthorityOutcome.REFUSED, "DESTINATION_UNREADABLE",
                records=len(payloads), filtered=filtered,
            )
        if existing != payloads:
            # Not this source's deterministic output, so it is not an
            # interrupted run of this migration. The v1 file stays intact.
            return _result(
                AuthorityOutcome.REFUSED, "DESTINATION_CONFLICT",
                records=len(payloads), filtered=filtered,
            )
        destination_ready = True

    if not apply:
        return _result(
            AuthorityOutcome.WOULD_MIGRATE, "DRY_RUN",
            records=len(payloads), filtered=filtered,
        )

    if not destination_ready:
        try:
            log.rewrite(payloads)
        except Exception:
            return _result(
                AuthorityOutcome.FAILED, "DESTINATION_WRITE_FAILED",
                records=len(payloads), filtered=filtered,
            )

    # Hard gate: the destination must reconstruct the v1 authority exactly,
    # read back through the runtime's own store. The v1 file is still the
    # sole retired-nothing rollback source until this passes.
    try:
        verified = verify(log_path, payloads)
    except Exception:
        verified = False

    if not verified:
        return _result(
            AuthorityOutcome.FAILED, "POST_WRITE_VERIFICATION_FAILED",
            records=len(payloads), filtered=filtered,
        )

    try:
        os.replace(legacy_path, archive_path)
    except OSError:
        return _result(
            AuthorityOutcome.FAILED, "LEGACY_RETIREMENT_FAILED",
            records=len(payloads), filtered=filtered,
        )

    return _result(
        AuthorityOutcome.MIGRATED, "MIGRATION_COMPLETE",
        records=len(payloads), filtered=filtered,
    )


def migrate(
    state_directory: str | Path,
    *,
    apply: bool = False,
) -> list[AuthorityMigrationResult]:
    """Migrate both execution authorities in one state directory."""
    directory = Path(state_directory)

    if not directory.is_dir():
        return [
            AuthorityMigrationResult(
                authority, AuthorityOutcome.REFUSED, "STATE_DIRECTORY_ABSENT",
                str(directory), str(directory),
            )
            for authority in _AUTHORITY_SPECS
        ]

    return [
        migrate_authority(directory, authority, apply=apply)
        for authority in _AUTHORITY_SPECS
    ]


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


class _UsageExitParser(argparse.ArgumentParser):
    """argparse exits 2 on usage errors, which would collide with this tool's
    exit code 2 (action required) and make a mistyped flag look like legacy
    state the tool refused to convert."""

    def error(self, message: str) -> None:  # type: ignore[override]
        self.print_usage(sys.stderr)
        self.exit(EXIT_USAGE, f"{self.prog}: error: {message}\n")


def build_parser() -> argparse.ArgumentParser:
    parser = _UsageExitParser(
        prog="migrate_execution_authority_logs",
        description=(
            "Convert the v1 execution transaction journal and idempotency "
            "store into the Block 5K append-only logs. Reports only, unless "
            "--apply is given; even then the v2 log is written and verified "
            "before the v1 file is retired, and the v1 file is renamed rather "
            "than deleted."
        ),
    )
    parser.add_argument(
        "--state-directory", required=True, type=Path,
        help="Directory holding the execution state files. Required; there is "
             "no default and it is never resolved against the CWD.",
    )
    parser.add_argument(
        "--apply", action="store_true",
        help="Perform the migration. Without this flag the tool is a dry run "
             "and writes nothing.",
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Explicitly request the default behaviour: report only, write "
             "nothing. Cannot be combined with --apply.",
    )
    parser.add_argument(
        "--json", action="store_true", dest="as_json",
        help="Emit a structured JSON result instead of the human lines.",
    )
    return parser


def _exit_code(results: list[AuthorityMigrationResult]) -> int:
    if any(result.outcome in _FAILED_OUTCOMES for result in results):
        return EXIT_FAILED
    if any(result.outcome in _REFUSED_OUTCOMES for result in results):
        return EXIT_REFUSED
    return EXIT_OK


def _render_human(results: list[AuthorityMigrationResult], exit_code: int) -> str:
    lines = [
        f"authority: {result.authority} | "
        f"outcome: {result.outcome.value} | "
        f"reason: {sanitize_sensitive_text(result.reason_code)} | "
        f"log: {sanitize_sensitive_text(result.log_path)} | "
        f"records: {result.records} | filtered: {result.filtered}"
        for result in results
    ]
    verdict = "OK" if exit_code == EXIT_OK else "ACTION_REQUIRED"
    lines.append(f"verdict: {verdict} (exit {exit_code})")
    return "\n".join(lines)


def _render_json(results: list[AuthorityMigrationResult], exit_code: int) -> str:
    return json.dumps(
        {
            "exit_code": exit_code,
            "authorities": [
                {
                    "authority": result.authority,
                    "outcome": result.outcome.value,
                    "reason_code": sanitize_sensitive_text(result.reason_code),
                    "legacy_path": sanitize_sensitive_text(result.legacy_path),
                    "log_path": sanitize_sensitive_text(result.log_path),
                    "records": result.records,
                    "filtered": result.filtered,
                }
                for result in results
            ],
        },
        indent=2, sort_keys=True,
    )


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    arguments = parser.parse_args(argv)

    if arguments.apply and arguments.dry_run:
        parser.error("--apply and --dry-run are mutually exclusive")

    results = migrate(arguments.state_directory, apply=arguments.apply)
    exit_code = _exit_code(results)
    rendered = (
        _render_json(results, exit_code) if arguments.as_json
        else _render_human(results, exit_code)
    )
    print(rendered)
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
