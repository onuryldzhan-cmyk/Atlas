"""
============================================================
ATLAS SEMANTIC REFERENCE AUDIT v1.1
============================================================

Refines Phase 3C reference checks.

Improvements
------------
- Separates real Python imports from generic text mentions
- Ignores backup, archive, quarantine, report, and generated folders
- Does not treat a filename mention as an import dependency
- Produces APPROVE / REVIEW / BLOCK decisions
- Never moves or deletes files
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
OUTPUT_DIR = PROJECT_ROOT / "reports" / "phase3_semantic_reference_audit"

EXCLUDED_DIR_NAMES = {
    ".git",
    ".venv",
    "venv",
    "__pycache__",
    ".pytest_cache",
    "reports",
    "_quarantine",
    "archive_unused_2026-07-22",
}

EXCLUDED_DIR_PREFIXES = (
    "phase1_backup",
    "phase2_backup",
    "phase3_backup",
    "phase3b_backup",
    "phase3c_backup",
    "backup_",
)

TARGET_STATUSES = {
    "QUARANTINE_SAFE",
    "DUPLICATE_REMOVE_CANDIDATE",
}


@dataclass
class AuditEntry:
    source_path: str
    original_status: str
    module_name: str
    sha256: str
    python_import_references: list[str]
    runtime_string_references: list[str]
    documentation_mentions: list[str]
    decision: str
    reason: str


def normalize(value: str) -> str:
    return value.replace("\\", "/").strip()


def excluded_path(path: Path) -> bool:
    relative = path.relative_to(PROJECT_ROOT)

    for part in relative.parts:
        lower = part.lower()

        if lower in EXCLUDED_DIR_NAMES:
            return True

        if any(lower.startswith(prefix) for prefix in EXCLUDED_DIR_PREFIXES):
            return True

    return False


def module_name_from_path(relative_path: str) -> str:
    path = Path(normalize(relative_path))

    if path.suffix != ".py":
        return ""

    parts = list(path.with_suffix("").parts)

    if parts and parts[-1] == "__init__":
        parts = parts[:-1]

    return ".".join(parts)


def read_candidates() -> list[dict[str, str]]:
    path = INPUT_DIR / "cleanup_candidates.csv"

    if not path.exists():
        raise FileNotFoundError(f"Missing report: {path}")

    with path.open("r", encoding="utf-8-sig", newline="") as file:
        return list(csv.DictReader(file))


def calculate_sha256(path: Path) -> str:
    digest = hashlib.sha256()

    with path.open("rb") as file:
        for block in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(block)

    return digest.hexdigest()


def imported_modules(path: Path) -> set[str]:
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
        tree = ast.parse(text, filename=str(path))
    except (OSError, SyntaxError):
        return set()

    results: set[str] = set()

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                results.add(alias.name)

        elif isinstance(node, ast.ImportFrom):
            if node.module:
                results.add(node.module)

    return results


def runtime_strings(path: Path) -> set[str]:
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
        tree = ast.parse(text, filename=str(path))
    except (OSError, SyntaxError):
        return set()

    results: set[str] = set()

    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue

        function_name = ""

        if isinstance(node.func, ast.Name):
            function_name = node.func.id

        elif isinstance(node.func, ast.Attribute):
            function_name = node.func.attr

        if function_name not in {
            "__import__",
            "import_module",
            "spec_from_file_location",
            "run_path",
            "run_module",
        }:
            continue

        for argument in node.args[:2]:
            if (
                isinstance(argument, ast.Constant)
                and isinstance(argument.value, str)
            ):
                results.add(argument.value)

    return results


def matches_module(imported: str, target: str) -> bool:
    return (
        imported == target
        or imported.startswith(target + ".")
        or target.startswith(imported + ".")
    )


def scan_python_references(
    candidate_relative: str,
    target_module: str,
) -> tuple[list[str], list[str]]:
    candidate_absolute = (PROJECT_ROOT / candidate_relative).resolve()

    import_refs: set[str] = set()
    runtime_refs: set[str] = set()

    for path in PROJECT_ROOT.rglob("*.py"):
        if excluded_path(path):
            continue

        try:
            if path.resolve() == candidate_absolute:
                continue
        except OSError:
            continue

        relative = normalize(str(path.relative_to(PROJECT_ROOT)))

        for imported in imported_modules(path):
            if target_module and matches_module(imported, target_module):
                import_refs.add(relative)

        for value in runtime_strings(path):
            normalized_value = normalize(value)
            target_path = normalize(candidate_relative)

            if (
                target_module
                and matches_module(normalized_value, target_module)
            ) or normalized_value == target_path:
                runtime_refs.add(relative)

    return sorted(import_refs), sorted(runtime_refs)


def documentation_mentions(
    candidate_relative: str,
    target_module: str,
) -> list[str]:
    candidate_name = Path(candidate_relative).name
    candidate_stem = Path(candidate_relative).stem

    mentions: set[str] = set()

    for extension in ("*.md", "*.txt", "*.ps1", "*.bat"):
        for path in PROJECT_ROOT.rglob(extension):
            if excluded_path(path):
                continue

            try:
                text = path.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue

            terms = {
                candidate_relative,
                normalize(candidate_relative),
                candidate_name,
            }

            if target_module:
                terms.add(target_module)

            if any(term and term in text for term in terms):
                mentions.add(
                    normalize(str(path.relative_to(PROJECT_ROOT)))
                )

    return sorted(mentions)


def build_entries() -> list[AuditEntry]:
    entries: list[AuditEntry] = []

    for row in read_candidates():
        status = row.get("status", "")

        if status not in TARGET_STATUSES:
            continue

        relative = normalize(row["path"])
        source = PROJECT_ROOT / relative
        module = module_name_from_path(relative)

        if not source.exists():
            entries.append(
                AuditEntry(
                    source_path=relative,
                    original_status=status,
                    module_name=module,
                    sha256="",
                    python_import_references=[],
                    runtime_string_references=[],
                    documentation_mentions=[],
                    decision="BLOCK_MISSING",
                    reason="Candidate file no longer exists.",
                )
            )
            continue

        actual_hash = calculate_sha256(source)
        expected_hash = row.get("sha256", "")

        import_refs, runtime_refs = scan_python_references(
            candidate_relative=relative,
            target_module=module,
        )

        docs = documentation_mentions(
            candidate_relative=relative,
            target_module=module,
        )

        if expected_hash and expected_hash != actual_hash:
            decision = "BLOCK_CHANGED"
            reason = "File changed after Phase 3B analysis."

        elif import_refs:
            decision = "BLOCK_IMPORTED"
            reason = "Candidate has real Python import references."

        elif runtime_refs:
            decision = "BLOCK_DYNAMIC_REFERENCE"
            reason = "Candidate is referenced by a dynamic import or runtime loader."

        elif docs:
            decision = "APPROVE_WITH_DOC_MENTIONS"
            reason = (
                "No code dependency found. Only documentation or script "
                "mentions remain; safe for reversible quarantine."
            )

        else:
            decision = "APPROVE_QUARANTINE"
            reason = (
                "No Python imports, dynamic loading, or external references found."
            )

        entries.append(
            AuditEntry(
                source_path=relative,
                original_status=status,
                module_name=module,
                sha256=actual_hash,
                python_import_references=import_refs,
                runtime_string_references=runtime_refs,
                documentation_mentions=docs,
                decision=decision,
                reason=reason,
            )
        )

    return entries


def write_outputs(entries: list[AuditEntry]) -> dict[str, object]:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    counts: dict[str, int] = defaultdict(int)

    for entry in entries:
        counts[entry.decision] += 1

    approved_decisions = {
        "APPROVE_QUARANTINE",
        "APPROVE_WITH_DOC_MENTIONS",
    }

    approved = [
        asdict(entry)
        for entry in entries
        if entry.decision in approved_decisions
    ]

    blocked = [
        asdict(entry)
        for entry in entries
        if entry.decision not in approved_decisions
    ]

    summary = {
        "project_root": str(PROJECT_ROOT),
        "total_candidates": len(entries),
        "decision_counts": dict(sorted(counts.items())),
        "approved_count": len(approved),
        "blocked_count": len(blocked),
        "approved_candidates": approved,
        "blocked_candidates": blocked,
        "safety": "No file was moved or deleted.",
    }

    (OUTPUT_DIR / "semantic_audit_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    (OUTPUT_DIR / "semantic_audit_entries.json").write_text(
        json.dumps(
            [asdict(entry) for entry in entries],
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    csv_path = OUTPUT_DIR / "semantic_audit_entries.csv"

    with csv_path.open("w", encoding="utf-8-sig", newline="") as file:
        writer = csv.writer(file)
        writer.writerow([
            "source_path",
            "original_status",
            "module_name",
            "sha256",
            "python_import_references",
            "runtime_string_references",
            "documentation_mentions",
            "decision",
            "reason",
        ])

        for entry in entries:
            writer.writerow([
                entry.source_path,
                entry.original_status,
                entry.module_name,
                entry.sha256,
                " | ".join(entry.python_import_references),
                " | ".join(entry.runtime_string_references),
                " | ".join(entry.documentation_mentions),
                entry.decision,
                entry.reason,
            ])

    return summary


def main() -> int:
    print("=" * 72)
    print("ATLAS SEMANTIC REFERENCE AUDIT v1.1")
    print("=" * 72)
    print(f"Project: {PROJECT_ROOT}")
    print("Mode   : READ-ONLY")
    print()

    entries = build_entries()
    summary = write_outputs(entries)

    print(f"Candidates checked : {summary['total_candidates']}")
    print(f"Approved           : {summary['approved_count']}")
    print(f"Blocked            : {summary['blocked_count']}")

    for decision, count in summary["decision_counts"].items():
        print(f"{decision:<28}: {count}")

    print()
    print(f"Reports: {OUTPUT_DIR}")
    print()
    print("SEMANTIC AUDIT COMPLETED — NO FILES WERE MOVED OR DELETED")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
