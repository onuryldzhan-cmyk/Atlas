"""
============================================================
ATLAS OPERATOR CAPITAL RESERVATION MIGRATION (v1 -> v2 + archive)
============================================================

Explicit, operator-invoked, one-time migration of the legacy single-file
reservation store (schema ``atlas-capital-reservations-v1``) into the
Block 5H two-part store:

- the same path, rewritten in place under schema
  ``atlas-capital-reservations-v2``, holding only the RESERVED /
  INDETERMINATE (live) reservations
- an immutable, append-only JSON-Lines archive holding every COMMITTED or
  RELEASED reservation the v1 file contained

This tool is never invoked by AtlasApplication or by
core/financial_state_bootstrap.py. A v1 file left in place is refused by
the runtime with an explicit migration-required condition
(core/capital_reservation.py: ReservationSchemaMigrationRequiredError, and
core/financial_state_bootstrap.py: RESERVATION_MIGRATION_REQUIRED). Running
this tool against a given state directory is a deliberate, one-time
operator action; there is no flag that invokes it automatically.

Every reservation is preserved exactly - id, request_id, Decimal amount,
status, version - by parsing and re-serializing through the same
``CapitalReservation.from_dict()`` / ``to_dict()`` the rest of the
reservation subsystem uses, never through a hand-rolled parser.

Idempotent and resumable:

- Running this tool again after a fully completed migration (the source is
  already v2) is a no-op reported as ALREADY_MIGRATED - it still validates
  the archive, if one is present, rather than assuming it is healthy.
- Running it again after a migration that durably appended some or all
  archive records but never reached the final working-file rewrite (a
  crash mid-migration; the source is still v1) resumes safely: it appends
  only the archive records not already durably present, then completes the
  working-file rewrite - provided the existing archive agrees
  field-for-field with what this exact source produces. If it disagrees,
  the tool refuses (REFUSED_ARCHIVE_CONFLICT) and touches nothing.
============================================================
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from enum import Enum
from pathlib import Path

_REPOSITORY_ROOT = Path(__file__).resolve().parent.parent
if str(_REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPOSITORY_ROOT))

from atlas_security import sanitize_sensitive_text  # noqa: E402
from core.capital_reservation import (  # noqa: E402
    CapitalReservation,
    JsonReservationStore,
    ReservationArchiveConflictError,
    ReservationArchiveCorruptError,
    ReservationArchiveStore,
    ReservationStatus,
)

EXIT_OK = 0
EXIT_USAGE = 1
EXIT_REFUSED = 2
EXIT_FAILED = 3

DEFAULT_WORKING_FILE = "capital_reservations.json"
DEFAULT_ARCHIVE_FILE = "capital_reservations_archive.jsonl"

_WORKING_STATUSES = (ReservationStatus.RESERVED, ReservationStatus.INDETERMINATE)
_ARCHIVE_STATUSES = (ReservationStatus.COMMITTED, ReservationStatus.RELEASED)


class MigrationOutcome(str, Enum):
    MIGRATED = "MIGRATED"
    ALREADY_MIGRATED = "ALREADY_MIGRATED"
    WOULD_MIGRATE = "WOULD_MIGRATE"
    SOURCE_ABSENT = "SOURCE_ABSENT"
    SOURCE_INVALID = "SOURCE_INVALID"
    ARCHIVE_INVALID = "ARCHIVE_INVALID"
    REFUSED_ARCHIVE_CONFLICT = "REFUSED_ARCHIVE_CONFLICT"
    FAILED = "FAILED"


_REFUSED_OUTCOMES = frozenset((
    MigrationOutcome.SOURCE_ABSENT,
    MigrationOutcome.SOURCE_INVALID,
    MigrationOutcome.ARCHIVE_INVALID,
    MigrationOutcome.REFUSED_ARCHIVE_CONFLICT,
))


@dataclass(frozen=True, slots=True)
class MigrationResult:
    outcome: MigrationOutcome
    reason_code: str
    working_path: str
    archive_path: str
    working_count: int = 0
    archive_count: int = 0
    archive_appended: int = 0


def migrate(
    state_directory: str | Path,
    *,
    working_file: str = DEFAULT_WORKING_FILE,
    archive_file: str = DEFAULT_ARCHIVE_FILE,
    dry_run: bool = False,
) -> MigrationResult:
    """Migrate one state directory's legacy v1 reservation file in place.

    Touches no file unless the outcome is MIGRATED (``dry_run=True`` never
    touches any file at all, regardless of outcome).
    """
    directory = Path(state_directory)
    working_path = directory / working_file
    archive_path = directory / archive_file

    if not working_path.exists():
        return MigrationResult(
            MigrationOutcome.SOURCE_ABSENT, "SOURCE_ABSENT",
            str(working_path), str(archive_path),
        )

    try:
        raw = json.loads(working_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return MigrationResult(
            MigrationOutcome.SOURCE_INVALID, "SOURCE_UNREADABLE",
            str(working_path), str(archive_path),
        )

    schema = raw.get("schema") if isinstance(raw, dict) else None

    if schema == JsonReservationStore.SCHEMA_V2:
        return _verify_already_migrated(working_path, archive_path)

    if schema != JsonReservationStore.SCHEMA_V1:
        return MigrationResult(
            MigrationOutcome.SOURCE_INVALID, "SOURCE_UNRECOGNIZED_SCHEMA",
            str(working_path), str(archive_path),
        )

    try:
        raw_records = raw["reservations"]
        if not isinstance(raw_records, list):
            raise ValueError("reservations must be a list")
        reservations = tuple(CapitalReservation.from_dict(item) for item in raw_records)
    except Exception:
        return MigrationResult(
            MigrationOutcome.SOURCE_INVALID, "SOURCE_CORRUPT",
            str(working_path), str(archive_path),
        )

    ids = [item.reservation_id for item in reservations]
    if len(set(ids)) != len(ids):
        return MigrationResult(
            MigrationOutcome.SOURCE_INVALID, "SOURCE_DUPLICATE_ID",
            str(working_path), str(archive_path),
        )

    working_records = tuple(sorted(
        (item for item in reservations if item.status in _WORKING_STATUSES),
        key=lambda item: item.reservation_id,
    ))
    archive_records = tuple(sorted(
        (item for item in reservations if item.status in _ARCHIVE_STATUSES),
        key=lambda item: item.reservation_id,
    ))

    archive_store = ReservationArchiveStore(archive_path)
    already_archived: dict[str, CapitalReservation] = {}
    if archive_path.exists():
        try:
            already_archived = archive_store.load_index()
        except OSError:
            return MigrationResult(
                MigrationOutcome.ARCHIVE_INVALID, "ARCHIVE_UNREADABLE",
                str(working_path), str(archive_path),
            )
        except ReservationArchiveCorruptError:
            return MigrationResult(
                MigrationOutcome.ARCHIVE_INVALID, "ARCHIVE_CORRUPT",
                str(working_path), str(archive_path),
            )
        except ReservationArchiveConflictError:
            return MigrationResult(
                MigrationOutcome.ARCHIVE_INVALID, "ARCHIVE_CONFLICT",
                str(working_path), str(archive_path),
            )

        # Never silently overwrite: an existing archive must be exactly
        # this source's archive portion, record for record, or the tool
        # refuses rather than guess which side is authoritative.
        expected = {item.reservation_id: item for item in archive_records}
        for reservation_id, existing_item in already_archived.items():
            expected_item = expected.get(reservation_id)
            if expected_item is None or expected_item != existing_item:
                return MigrationResult(
                    MigrationOutcome.REFUSED_ARCHIVE_CONFLICT,
                    "ARCHIVE_TARGET_DOES_NOT_MATCH_SOURCE",
                    str(working_path), str(archive_path),
                )

    if dry_run:
        return MigrationResult(
            MigrationOutcome.WOULD_MIGRATE, "DRY_RUN",
            str(working_path), str(archive_path),
            working_count=len(working_records), archive_count=len(archive_records),
        )

    appended = 0
    try:
        for record in archive_records:
            if record.reservation_id not in already_archived:
                archive_store.append(record)
                appended += 1
        JsonReservationStore(working_path).save(working_records)
    except Exception as exc:
        return MigrationResult(
            MigrationOutcome.FAILED, f"MIGRATION_WRITE_FAILED:{str(exc)[:200]}",
            str(working_path), str(archive_path),
            archive_count=len(archive_records), archive_appended=appended,
        )

    return MigrationResult(
        MigrationOutcome.MIGRATED, "MIGRATION_COMPLETE",
        str(working_path), str(archive_path),
        working_count=len(working_records), archive_count=len(archive_records),
        archive_appended=appended,
    )


def _verify_already_migrated(working_path: Path, archive_path: Path) -> MigrationResult:
    """The working file is already v2 - confirm the archive, if any, is healthy."""
    if not archive_path.exists():
        return MigrationResult(
            MigrationOutcome.ALREADY_MIGRATED, "SOURCE_ALREADY_V2",
            str(working_path), str(archive_path),
        )
    try:
        ReservationArchiveStore(archive_path).load_index()
    except OSError:
        return MigrationResult(
            MigrationOutcome.ARCHIVE_INVALID, "ARCHIVE_UNREADABLE",
            str(working_path), str(archive_path),
        )
    except ReservationArchiveCorruptError:
        return MigrationResult(
            MigrationOutcome.ARCHIVE_INVALID, "ARCHIVE_CORRUPT",
            str(working_path), str(archive_path),
        )
    except ReservationArchiveConflictError:
        return MigrationResult(
            MigrationOutcome.ARCHIVE_INVALID, "ARCHIVE_CONFLICT",
            str(working_path), str(archive_path),
        )
    return MigrationResult(
        MigrationOutcome.ALREADY_MIGRATED, "SOURCE_ALREADY_V2",
        str(working_path), str(archive_path),
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
        prog="migrate_capital_reservations",
        description=(
            "One-time operator migration of a legacy v1 capital-reservation "
            "file to the Block 5H v2 working file + immutable archive. "
            "Never invoked automatically; never overwrites an existing "
            "archive unless it provably matches this exact migration."
        ),
    )
    parser.add_argument(
        "--state-directory", required=True, type=Path,
        help="Directory containing capital_reservations.json. Required; "
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
        f"working: {sanitize_sensitive_text(result.working_path)} (live={result.working_count}) | "
        f"archive: {sanitize_sensitive_text(result.archive_path)} "
        f"(terminal={result.archive_count}, appended_this_run={result.archive_appended}) | "
        f"verdict: {verdict} (exit {exit_code})"
    )


def _render_json(result: MigrationResult, exit_code: int) -> str:
    return json.dumps(
        {
            "outcome": result.outcome.value,
            "reason_code": sanitize_sensitive_text(result.reason_code),
            "exit_code": exit_code,
            "working_path": sanitize_sensitive_text(result.working_path),
            "archive_path": sanitize_sensitive_text(result.archive_path),
            "working_count": result.working_count,
            "archive_count": result.archive_count,
            "archive_appended": result.archive_appended,
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
