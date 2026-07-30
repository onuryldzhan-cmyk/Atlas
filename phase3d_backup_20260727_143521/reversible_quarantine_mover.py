"""
============================================================
ATLAS REVERSIBLE QUARANTINE MOVER v1.0
============================================================

Moves only approved Phase 3C.2 candidates into a reversible
quarantine directory.

Safety
------
- Moves, never deletes
- Verifies SHA-256 before moving
- Refuses unapproved candidates
- Preserves relative paths
- Writes restore manifest and PowerShell restore script
============================================================
"""

from __future__ import annotations

import hashlib
import json
import shutil
import sys
from datetime import datetime, UTC
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent.parent
INPUT_REPORT = (
    PROJECT_ROOT
    / "reports"
    / "phase3_semantic_reference_audit"
    / "semantic_audit_summary.json"
)
QUARANTINE_ROOT = PROJECT_ROOT / "_quarantine" / "phase3"
REPORT_DIR = PROJECT_ROOT / "reports" / "phase3_quarantine_execution"

APPROVED_DECISIONS = {
    "APPROVE_QUARANTINE",
    "APPROVE_WITH_DOC_MENTIONS",
}


def normalize(value: str) -> str:
    return value.replace("\\", "/").strip()


def calculate_sha256(path: Path) -> str:
    digest = hashlib.sha256()

    with path.open("rb") as file:
        for block in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(block)

    return digest.hexdigest()


def load_summary() -> dict:
    if not INPUT_REPORT.exists():
        raise FileNotFoundError(
            f"Semantic audit summary not found: {INPUT_REPORT}"
        )

    return json.loads(
        INPUT_REPORT.read_text(encoding="utf-8")
    )


def validate_candidate(candidate: dict) -> tuple[Path, Path]:
    decision = candidate.get("decision", "")

    if decision not in APPROVED_DECISIONS:
        raise RuntimeError(
            f"Candidate is not approved: {candidate.get('source_path')}"
        )

    relative = normalize(candidate["source_path"])
    source = PROJECT_ROOT / relative
    destination = QUARANTINE_ROOT / relative

    if not source.exists():
        raise FileNotFoundError(
            f"Source file not found: {source}"
        )

    expected_hash = candidate.get("sha256", "")
    actual_hash = calculate_sha256(source)

    if expected_hash and actual_hash != expected_hash:
        raise RuntimeError(
            f"Hash changed after approval: {relative}"
        )

    if destination.exists():
        raise FileExistsError(
            f"Quarantine destination already exists: {destination}"
        )

    return source, destination


def write_restore_script(records: list[dict]) -> Path:
    path = REPORT_DIR / "restore_phase3_quarantine.ps1"

    lines = [
        '$ErrorActionPreference = "Stop"',
        "",
        "$ProjectRoot = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)",
        "",
    ]

    for record in records:
        source = record["quarantine_path"].replace("/", "\\")
        destination = record["original_path"].replace("/", "\\")

        lines.extend([
            f'$Source = Join-Path $ProjectRoot "{source}"',
            f'$Destination = Join-Path $ProjectRoot "{destination}"',
            "",
            "if (Test-Path $Source) {",
            "    $DestinationDir = Split-Path -Parent $Destination",
            "    New-Item -ItemType Directory -Force -Path $DestinationDir | Out-Null",
            "    Move-Item -Path $Source -Destination $Destination -Force",
            '    Write-Host "Restored: $Destination"',
            "} else {",
            '    Write-Host "Skipped missing quarantine file: $Source"',
            "}",
            "",
        ])

    lines.append('Write-Host "Phase 3 quarantine restore completed."')

    path.write_text(
        "\n".join(lines),
        encoding="utf-8",
    )

    return path


def main() -> int:
    print("=" * 72)
    print("ATLAS REVERSIBLE QUARANTINE MOVER v1.0")
    print("=" * 72)
    print(f"Project     : {PROJECT_ROOT}")
    print(f"Quarantine  : {QUARANTINE_ROOT}")
    print("Mode        : MOVE ONLY — NO DELETE")
    print()

    summary = load_summary()
    approved = summary.get("approved_candidates", [])

    if not approved:
        print("No approved candidates found.")
        return 1

    validations: list[tuple[dict, Path, Path]] = []

    for candidate in approved:
        source, destination = validate_candidate(candidate)
        validations.append((candidate, source, destination))

    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    QUARANTINE_ROOT.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.now(UTC).isoformat()
    records: list[dict] = []

    for candidate, source, destination in validations:
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(source), str(destination))

        record = {
            "original_path": normalize(
                str(source.relative_to(PROJECT_ROOT))
            ),
            "quarantine_path": normalize(
                str(destination.relative_to(PROJECT_ROOT))
            ),
            "sha256": candidate.get("sha256", ""),
            "decision": candidate.get("decision", ""),
            "moved_at_utc": timestamp,
        }
        records.append(record)

        print(f"MOVED: {record['original_path']}")

    manifest = {
        "project_root": str(PROJECT_ROOT),
        "quarantine_root": str(QUARANTINE_ROOT),
        "moved_count": len(records),
        "moved_at_utc": timestamp,
        "records": records,
        "safety": "No file was deleted.",
    }

    manifest_path = REPORT_DIR / "quarantine_execution_manifest.json"
    manifest_path.write_text(
        json.dumps(
            manifest,
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    restore_script = write_restore_script(records)

    print()
    print(f"Moved files : {len(records)}")
    print(f"Manifest    : {manifest_path}")
    print(f"Restore     : {restore_script}")
    print()
    print("QUARANTINE COMPLETED — NO FILES WERE DELETED")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
