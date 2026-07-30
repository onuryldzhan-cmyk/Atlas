"""
============================================================
ATLAS QUARANTINE MANIFEST BUILDER v1.0
============================================================

Builds a reversible quarantine plan from Phase 3B results.

Safety
------
- Does not move files
- Does not delete files
- Searches project source for import/reference evidence
- Produces approved and blocked candidate lists
============================================================
"""

from __future__ import annotations

import ast
import csv
import hashlib
import json
import re

from collections import defaultdict
from dataclasses import asdict, dataclass
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent.parent
INPUT_DIR = PROJECT_ROOT / "reports" / "phase3_cleanup_candidates"
OUTPUT_DIR = PROJECT_ROOT / "reports" / "phase3_quarantine_manifest"

SOURCE_EXTENSIONS = {
    ".py",
    ".toml",
    ".ini",
    ".cfg",
    ".json",
    ".yaml",
    ".yml",
    ".md",
    ".txt",
    ".ps1",
    ".bat",
}

EXCLUDED_DIRS = {
    ".git",
    ".venv",
    "venv",
    "__pycache__",
    ".pytest_cache",
    "reports",
    "_quarantine",
}

TARGET_STATUSES = {
    "QUARANTINE_SAFE",
    "DUPLICATE_REMOVE_CANDIDATE",
}


@dataclass
class ManifestEntry:
    source_path: str
    quarantine_path: str
    original_status: str
    confidence: str
    sha256: str
    reference_count: int
    references: list[str]
    decision: str
    reason: str


def normalize(value: str) -> str:
    return value.replace("\\", "/").strip()


def calculate_sha256(path: Path) -> str:
    digest = hashlib.sha256()

    with path.open("rb") as file:
        for block in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(block)

    return digest.hexdigest()


def candidate_module_names(relative_path: str) -> set[str]:
    normalized = normalize(relative_path)
    path = Path(normalized)

    names = {
        normalized,
        path.name,
        path.stem,
    }

    if path.suffix == ".py":
        module_parts = list(path.with_suffix("").parts)

        if module_parts and module_parts[-1] == "__init__":
            module_parts = module_parts[:-1]

        if module_parts:
            module = ".".join(module_parts)
            names.add(module)
            names.add(module_parts[-1])

    return {
        value
        for value in names
        if value and len(value) >= 3
    }


def iter_search_files():
    for path in PROJECT_ROOT.rglob("*"):
        if not path.is_file():
            continue

        relative = path.relative_to(PROJECT_ROOT)

        if any(part in EXCLUDED_DIRS for part in relative.parts):
            continue

        if path.suffix.lower() not in SOURCE_EXTENSIONS:
            continue

        yield path


def textual_references(
    candidate_path: str,
    search_files: list[Path],
) -> list[str]:
    terms = candidate_module_names(candidate_path)
    candidate_absolute = (PROJECT_ROOT / candidate_path).resolve()
    matches: set[str] = set()

    for source_path in search_files:
        try:
            if source_path.resolve() == candidate_absolute:
                continue

            text = source_path.read_text(
                encoding="utf-8",
                errors="replace",
            )
        except OSError:
            continue

        for term in terms:
            if term.endswith(".py"):
                pattern = re.escape(term)
            elif "." in term:
                pattern = rf"(?<![\w.]){re.escape(term)}(?![\w.])"
            else:
                pattern = rf"(?<![\w]){re.escape(term)}(?![\w])"

            if re.search(pattern, text):
                matches.add(
                    normalize(
                        str(source_path.relative_to(PROJECT_ROOT))
                    )
                )
                break

    return sorted(matches)


def read_candidates() -> list[dict[str, str]]:
    path = INPUT_DIR / "cleanup_candidates.csv"

    if not path.exists():
        raise FileNotFoundError(
            f"Missing Phase 3B report: {path}"
        )

    with path.open(
        "r",
        encoding="utf-8-sig",
        newline="",
    ) as file:
        return list(csv.DictReader(file))


def build_manifest() -> list[ManifestEntry]:
    rows = read_candidates()
    search_files = list(iter_search_files())
    entries: list[ManifestEntry] = []

    for row in rows:
        status = row.get("status", "")

        if status not in TARGET_STATUSES:
            continue

        relative = normalize(row["path"])
        source = PROJECT_ROOT / relative
        references = textual_references(
            relative,
            search_files,
        )

        if not source.exists():
            decision = "BLOCK_MISSING"
            reason = "Candidate file no longer exists."
            actual_sha256 = ""

        else:
            actual_sha256 = calculate_sha256(source)
            expected_sha256 = row.get("sha256", "")

            if expected_sha256 and actual_sha256 != expected_sha256:
                decision = "BLOCK_CHANGED"
                reason = (
                    "File content changed after Phase 3B analysis; "
                    "re-audit required."
                )

            elif references:
                decision = "BLOCK_REFERENCED"
                reason = (
                    "Project text contains possible references; "
                    "manual inspection required."
                )

            else:
                decision = "APPROVE_QUARANTINE"
                reason = (
                    "High-confidence cleanup candidate, unchanged, "
                    "and no textual references found."
                )

        entries.append(
            ManifestEntry(
                source_path=relative,
                quarantine_path=normalize(
                    str(
                        Path("_quarantine")
                        / "phase3"
                        / relative
                    )
                ),
                original_status=status,
                confidence=row.get("confidence", ""),
                sha256=actual_sha256,
                reference_count=len(references),
                references=references,
                decision=decision,
                reason=reason,
            )
        )

    return entries


def write_outputs(entries: list[ManifestEntry]) -> dict[str, object]:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    counts: dict[str, int] = defaultdict(int)

    for entry in entries:
        counts[entry.decision] += 1

    manifest_json = OUTPUT_DIR / "quarantine_manifest.json"
    manifest_json.write_text(
        json.dumps(
            [asdict(entry) for entry in entries],
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    csv_path = OUTPUT_DIR / "quarantine_manifest.csv"

    with csv_path.open(
        "w",
        encoding="utf-8-sig",
        newline="",
    ) as file:
        writer = csv.writer(file)
        writer.writerow([
            "source_path",
            "quarantine_path",
            "original_status",
            "confidence",
            "sha256",
            "reference_count",
            "references",
            "decision",
            "reason",
        ])

        for entry in entries:
            writer.writerow([
                entry.source_path,
                entry.quarantine_path,
                entry.original_status,
                entry.confidence,
                entry.sha256,
                entry.reference_count,
                " | ".join(entry.references),
                entry.decision,
                entry.reason,
            ])

    approved = [
        asdict(entry)
        for entry in entries
        if entry.decision == "APPROVE_QUARANTINE"
    ]

    blocked = [
        asdict(entry)
        for entry in entries
        if entry.decision != "APPROVE_QUARANTINE"
    ]

    summary = {
        "project_root": str(PROJECT_ROOT),
        "total_candidates": len(entries),
        "decision_counts": dict(sorted(counts.items())),
        "approved_count": len(approved),
        "blocked_count": len(blocked),
        "approved_candidates": approved,
        "blocked_candidates": blocked,
        "safety": (
            "This stage created a plan only. "
            "No file was moved or deleted."
        ),
    }

    (OUTPUT_DIR / "manifest_summary.json").write_text(
        json.dumps(
            summary,
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    restore_lines = [
        "# Atlas quarantine restore map",
        "# Generated before any move operation.",
        "",
    ]

    for entry in approved:
        restore_lines.append(
            f"{entry['quarantine_path']} -> {entry['source_path']}"
        )

    (OUTPUT_DIR / "restore_map.txt").write_text(
        "\n".join(restore_lines),
        encoding="utf-8",
    )

    return summary


def main() -> int:
    print("=" * 72)
    print("ATLAS QUARANTINE MANIFEST BUILDER v1.0")
    print("=" * 72)
    print(f"Project: {PROJECT_ROOT}")
    print("Mode   : PLAN ONLY")
    print()

    entries = build_manifest()
    summary = write_outputs(entries)

    print(f"Candidates checked : {summary['total_candidates']}")
    print(f"Approved           : {summary['approved_count']}")
    print(f"Blocked            : {summary['blocked_count']}")

    for decision, count in summary["decision_counts"].items():
        print(f"{decision:<20}: {count}")

    print()
    print(f"Reports: {OUTPUT_DIR}")
    print()
    print("MANIFEST COMPLETED — NO FILES WERE MOVED OR DELETED")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
