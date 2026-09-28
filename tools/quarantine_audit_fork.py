"""Quarantine the short branch of a forked audit event chain.

Two Atlas processes on one state root can append to the same audit log and
fork its hash chain (2026-09-28 incident, registry v5.05). This tool moves
the named fork-branch lines, byte for byte, out of the live log into a
quarantine file - it never edits, rehashes or deletes an event.

It refuses unless ALL of these hold (and it never moves an experiment
admission - a RISK_APPROVED event carrying an experiment_id - because the
experiment cap is restored by counting those):
- no Atlas instance holds the state-root lock (main.AtlasProcess lock);
- the live chain is currently broken at exactly one point;
- the named lines are contiguous, the first chains from the line before
  them, and every event in them has a valid hash;
- with those lines removed, the whole chain verifies.

Default is a dry run that prints the plan. ``--apply`` then writes:
- ``<log>.pre_quarantine_<ts>.jsonl``   untouched copy of the original;
- ``<log>.quarantine_<ts>.jsonl``       the moved lines, unchanged;
- ``<log>.quarantine_<ts>.manifest.json`` what moved, from where, why;
and atomically replaces the live log, then re-verifies it through
AuditEventStore's own load-time verification.

Usage:
  python -m tools.quarantine_audit_fork <log> --lines 343-344 [--apply]
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import sys
from datetime import UTC, datetime
from collections.abc import Mapping
from pathlib import Path

from core.audit_event_store import GENESIS_HASH, AuditEvent, AuditEventStore


class QuarantineRefused(Exception):
    """A precondition failed; nothing was written."""


def _parse_range(text: str) -> tuple[int, int]:
    first, _, last = text.partition("-")
    start, end = int(first), int(last or first)
    if start < 1 or end < start:
        raise argparse.ArgumentTypeError(f"bad line range {text!r}")
    return start, end


def _events(raw_lines: list[bytes]) -> list[AuditEvent | None]:
    return [
        AuditEvent.from_dict(json.loads(line)) if line.strip() else None
        for line in raw_lines
    ]


def _breaks(events: list[AuditEvent | None]) -> list[int]:
    """1-based numbers of lines whose link or own hash is invalid."""

    found = []
    previous = GENESIS_HASH
    for number, event in enumerate(events, start=1):
        if event is None:
            continue
        if event.previous_hash != previous or not event.verify_hash():
            found.append(number)
        previous = event.event_hash
    return found


def plan(path: Path, start: int, end: int) -> dict:
    raw = path.read_bytes().splitlines(keepends=True)
    events = _events(raw)

    if end > len(raw):
        raise QuarantineRefused(f"file has {len(raw)} lines, range ends at {end}")

    breaks = _breaks(events)
    if len(breaks) != 1:
        raise QuarantineRefused(f"expected exactly one chain break, found {breaks}")

    branch = events[start - 1:end]
    if any(event is None for event in branch):
        raise QuarantineRefused("range contains blank lines")
    for number, event in zip(range(start, end + 1), branch):
        payload = event.payload if isinstance(event.payload, Mapping) else {}
        details = payload.get("details")
        if (
            event.event_type == "RISK_APPROVED"
            and isinstance(details, Mapping)
            and details.get("experiment_id")
        ):
            # The experiment cap (EXP-001) is restored by counting these
            # events; moving one out would silently re-open admissions.
            raise QuarantineRefused(
                f"line {number} is an experiment admission "
                f"({details['experiment_id']}); quarantining it would lower "
                "the experiment's admission count - owner decision required"
            )
    if not all(event.verify_hash() for event in branch):
        raise QuarantineRefused("an event in the range has an invalid own hash")

    before = events[start - 2].event_hash if start > 1 else GENESIS_HASH
    if branch[0].previous_hash != before:
        raise QuarantineRefused(
            f"line {start} does not chain from line {start - 1}; "
            "not the start of a fork branch"
        )
    for earlier, later in zip(branch, branch[1:]):
        if later.previous_hash != earlier.event_hash:
            raise QuarantineRefused("range is not one contiguous chain")

    kept_raw = raw[:start - 1] + raw[end:]
    remaining = _breaks(_events(kept_raw))
    if remaining:
        raise QuarantineRefused(
            f"chain would still be broken at kept lines {remaining}"
        )

    return {
        "raw": raw,
        "kept_raw": kept_raw,
        "moved": [
            {
                "original_line": number,
                "event_id": event.event_id,
                "event_type": event.event_type,
                "aggregate_id": event.aggregate_id,
                "timestamp": event.timestamp,
            }
            for number, event in zip(range(start, end + 1), branch)
        ],
    }


def apply(path: Path, start: int, end: int, reason: str) -> dict:
    result = plan(path, start, end)
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    base = path.with_suffix("")

    original = Path(f"{base}.pre_quarantine_{stamp}.jsonl")
    quarantine = Path(f"{base}.quarantine_{stamp}.jsonl")
    manifest = Path(f"{base}.quarantine_{stamp}.manifest.json")
    staging = Path(f"{base}.quarantine_{stamp}.staging")

    shutil.copy2(path, original)
    if hashlib.sha256(original.read_bytes()).digest() != hashlib.sha256(
        b"".join(result["raw"])
    ).digest():
        raise QuarantineRefused("backup copy does not match the read file")

    quarantine.write_bytes(b"".join(result["raw"][start - 1:end]))
    manifest.write_text(
        json.dumps(
            {
                "reason": reason,
                "live_log": str(path),
                "original_copy": str(original),
                "original_sha256": hashlib.sha256(b"".join(result["raw"])).hexdigest(),
                "original_line_count": len(result["raw"]),
                "moved": result["moved"],
                "applied_at": stamp,
            },
            indent=2,
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    staging.write_bytes(b"".join(result["kept_raw"]))
    os.replace(staging, path)

    AuditEventStore(path)  # load-time verification; raises if still broken

    result.update(original=original, quarantine=quarantine, manifest=manifest)
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("log", type=Path)
    parser.add_argument("--lines", type=_parse_range, required=True)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument(
        "--reason",
        default="Fork branch from a concurrent second Atlas instance "
        "(2026-09-28 incident, registry v5.05)",
    )
    args = parser.parse_args(argv)
    start, end = args.lines

    from main import AtlasProcess

    guard = AtlasProcess()
    if not guard._acquire_instance_lock():
        print(f"REFUSED: {guard.shutdown_reason}")
        return 2

    try:
        if args.apply:
            result = apply(args.log, start, end, args.reason)
        else:
            result = plan(args.log, start, end)
    except QuarantineRefused as exc:
        print(f"REFUSED: {exc}")
        return 2
    finally:
        guard._release_instance_lock()

    for moved in result["moved"]:
        print(f"{'MOVED' if args.apply else 'WOULD MOVE'}: {moved}")
    print(
        f"lines {len(result['raw'])} -> {len(result['kept_raw'])}; "
        "remaining chain verifies"
    )
    if args.apply:
        print(f"original copy: {result['original']}")
        print(f"quarantine:    {result['quarantine']}")
        print(f"manifest:      {result['manifest']}")
    else:
        print("DRY RUN - nothing written. Re-run with --apply to perform it.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
