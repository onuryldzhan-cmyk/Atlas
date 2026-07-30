"""
============================================================
ATLAS CLEANUP CANDIDATE ANALYZER v1.0
============================================================

Purpose
-------
Classifies cleanup candidates without deleting or moving files.

Safety
------
- Read-only
- No source modification
- No file deletion
- No quarantine movement
============================================================
"""

from __future__ import annotations

import ast
import csv
import hashlib
import json
import re
import sys

from collections import defaultdict
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterable


PROJECT_ROOT = Path(__file__).resolve().parent.parent
AUDIT_DIR = PROJECT_ROOT / "reports" / "phase3_architecture_audit"
OUTPUT_DIR = PROJECT_ROOT / "reports" / "phase3_cleanup_candidates"

CANONICAL_PATHS = {
    "main.py",
    "ai/core/atlas_brain.py",
    "ai/core/atlas_memory_core.py",
    "ai/core/atlas_reasoning_engine.py",
    "ai/core/atlas_world_model.py",
    "ai/core/intelligence/agent_fusion.py",
    "ai/core/intelligence/confidence/confidence_engine.py",
    "ai/core/intelligence/decision_builder.py",
    "ai/core/intelligence/memory_adapter.py",
    "ai/core/intelligence/reasoning_adapter.py",
    "ai/core/intelligence/risk_engine.py",
    "analysis/world_analysis_engine.py",
    "core/application.py",
    "core/brain.py",
    "core/candle_processor.py",
    "core/controller/atlas_controller.py",
    "core/decision.py",
    "core/decision_adapter.py",
    "core/event_bus.py",
    "core/execution_manager.py",
    "core/execution_models.py",
    "core/lifecycle.py",
    "core/logger.py",
    "core/market_loop.py",
    "core/paper_trader.py",
    "core/position_controller.py",
    "core/runtime.py",
    "core/scheduler.py",
    "core/service_container.py",
    "core/technical_analyzer.py",
    "exchange/adapters/binance_global.py",
    "exchange/adapters/binance_tr.py",
    "exchange/base_exchange.py",
    "exchange/exchange_manager.py",
    "exchange/market_feed.py",
    "portfolio/capital_manager.py",
}

BACKUP_PATTERNS = (
    r"(^|/)(phase\d+_backup[^/]*)/",
    r"(^|/)archive[^/]*/",
    r"(^|/)_archive/",
    r"(^|/)_backup/",
    r"(^|/)backup/",
    r"(^|/).*_backup(?:_v?\d+)?\.py$",
    r"(^|/).*_old(?:_v?\d+)?\.py$",
    r"(^|/).*_copy(?:_\d+)?\.py$",
)

TEST_PATTERNS = (
    r"(^|/)tests?/",
    r"(^|/)test_[^/]+\.py$",
    r"(^|/)[^/]+_test\.py$",
)

TOOL_PATTERNS = (
    r"(^|/)tools?/",
    r"(^|/)scripts?/",
    r"(^|/)inspect_[^/]+\.py$",
    r"(^|/)check_[^/]+\.py$",
)


@dataclass
class Candidate:
    path: str
    status: str
    confidence: str
    reason: str
    loc: int
    parse_ok: bool
    reachable_from_main: bool
    sha256: str
    duplicate_group: str = ""


def normalize_path(value: str) -> str:
    return value.replace("\\", "/").strip()


def to_bool(value: object) -> bool:
    return str(value).strip().lower() in {"true", "1", "yes"}


def pattern_match(path: str, patterns: tuple[str, ...]) -> bool:
    return any(re.search(pattern, path, re.IGNORECASE) for pattern in patterns)


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as file:
        return list(csv.DictReader(file))


def source_is_effectively_empty(path: Path) -> bool:
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return False

    stripped_lines = []

    for line in text.splitlines():
        value = line.strip()

        if not value or value.startswith("#"):
            continue

        stripped_lines.append(value)

    if not stripped_lines:
        return True

    try:
        tree = ast.parse(text)
    except SyntaxError:
        return False

    meaningful = []

    for node in tree.body:
        if isinstance(node, ast.Expr):
            value = getattr(node, "value", None)

            if isinstance(value, ast.Constant) and isinstance(value.value, str):
                continue

        if isinstance(node, ast.Pass):
            continue

        meaningful.append(node)

    return not meaningful


def classify(
    row: dict[str, str],
    duplicate_groups: dict[str, list[dict[str, str]]],
) -> Candidate:
    raw_path = row["path"]
    path = normalize_path(raw_path)
    project_file = PROJECT_ROOT / raw_path

    loc = int(row.get("loc") or 0)
    parse_ok = to_bool(row.get("parse_ok"))
    reachable = to_bool(row.get("reachable_from_main"))
    sha256 = row.get("sha256", "")

    is_init = path.endswith("/__init__.py") or path == "__init__.py"
    is_test = pattern_match(path, TEST_PATTERNS)
    is_tool = pattern_match(path, TOOL_PATTERNS)
    is_backup = pattern_match(path, BACKUP_PATTERNS)
    is_empty = source_is_effectively_empty(project_file)

    duplicate_group = ""
    duplicate_members = duplicate_groups.get(sha256, [])

    if len(duplicate_members) > 1:
        duplicate_group = sha256[:12]

    if path in CANONICAL_PATHS or reachable:
        return Candidate(
            path=path,
            status="KEEP_CANONICAL",
            confidence="HIGH",
            reason="Active main.py dependency chain or canonical runtime file.",
            loc=loc,
            parse_ok=parse_ok,
            reachable_from_main=reachable,
            sha256=sha256,
            duplicate_group=duplicate_group,
        )

    if not parse_ok:
        return Candidate(
            path=path,
            status="PARSE_ERROR_REVIEW",
            confidence="HIGH",
            reason="Python AST parsing failed; inspect before any cleanup action.",
            loc=loc,
            parse_ok=parse_ok,
            reachable_from_main=reachable,
            sha256=sha256,
            duplicate_group=duplicate_group,
        )

    if is_init and is_empty:
        return Candidate(
            path=path,
            status="KEEP_PACKAGE_MARKER",
            confidence="HIGH",
            reason="Empty __init__.py may define a regular Python package; do not delete automatically.",
            loc=loc,
            parse_ok=parse_ok,
            reachable_from_main=reachable,
            sha256=sha256,
            duplicate_group=duplicate_group,
        )

    if is_test:
        return Candidate(
            path=path,
            status="KEEP_TEST_REVIEW",
            confidence="HIGH",
            reason="Test file; main.py reachability is not a valid deletion criterion.",
            loc=loc,
            parse_ok=parse_ok,
            reachable_from_main=reachable,
            sha256=sha256,
            duplicate_group=duplicate_group,
        )

    if is_tool:
        return Candidate(
            path=path,
            status="KEEP_TOOL_REVIEW",
            confidence="MEDIUM",
            reason="Development/diagnostic tool; may be intentionally outside runtime imports.",
            loc=loc,
            parse_ok=parse_ok,
            reachable_from_main=reachable,
            sha256=sha256,
            duplicate_group=duplicate_group,
        )

    if is_backup:
        return Candidate(
            path=path,
            status="QUARANTINE_SAFE",
            confidence="HIGH",
            reason="Backup/archive/old-copy naming and not reachable from main.py.",
            loc=loc,
            parse_ok=parse_ok,
            reachable_from_main=reachable,
            sha256=sha256,
            duplicate_group=duplicate_group,
        )

    if is_empty:
        return Candidate(
            path=path,
            status="EMPTY_REMOVE_CANDIDATE",
            confidence="MEDIUM",
            reason="Effectively empty non-package Python module and not reachable from main.py.",
            loc=loc,
            parse_ok=parse_ok,
            reachable_from_main=reachable,
            sha256=sha256,
            duplicate_group=duplicate_group,
        )

    if len(duplicate_members) > 1:
        reachable_members = [
            member
            for member in duplicate_members
            if to_bool(member.get("reachable_from_main"))
        ]

        if reachable_members:
            canonical_paths = {
                normalize_path(member["path"])
                for member in reachable_members
            }

            if path not in canonical_paths:
                return Candidate(
                    path=path,
                    status="DUPLICATE_REMOVE_CANDIDATE",
                    confidence="HIGH",
                    reason="Exact duplicate of a main.py-reachable file.",
                    loc=loc,
                    parse_ok=parse_ok,
                    reachable_from_main=reachable,
                    sha256=sha256,
                    duplicate_group=duplicate_group,
                )

        return Candidate(
            path=path,
            status="DUPLICATE_REVIEW",
            confidence="MEDIUM",
            reason="Exact duplicate exists, but canonical ownership requires review.",
            loc=loc,
            parse_ok=parse_ok,
            reachable_from_main=reachable,
            sha256=sha256,
            duplicate_group=duplicate_group,
        )

    return Candidate(
        path=path,
        status="KEEP_REVIEW",
        confidence="LOW",
        reason="Not proven reachable from main.py, but may be used by tests, scripts, plugins, future subsystems, or alternate entry points.",
        loc=loc,
        parse_ok=parse_ok,
        reachable_from_main=reachable,
        sha256=sha256,
        duplicate_group=duplicate_group,
    )


def write_candidates(candidates: list[Candidate]) -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    csv_path = OUTPUT_DIR / "cleanup_candidates.csv"

    with csv_path.open("w", encoding="utf-8-sig", newline="") as file:
        writer = csv.DictWriter(
            file,
            fieldnames=list(asdict(candidates[0]).keys()),
        )
        writer.writeheader()

        for candidate in candidates:
            writer.writerow(asdict(candidate))

    json_path = OUTPUT_DIR / "cleanup_candidates.json"
    json_path.write_text(
        json.dumps(
            [asdict(candidate) for candidate in candidates],
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )


def write_summary(candidates: list[Candidate]) -> dict[str, object]:
    counts: dict[str, int] = defaultdict(int)

    for candidate in candidates:
        counts[candidate.status] += 1

    actionable = [
        candidate
        for candidate in candidates
        if candidate.status in {
            "QUARANTINE_SAFE",
            "DUPLICATE_REMOVE_CANDIDATE",
            "EMPTY_REMOVE_CANDIDATE",
            "PARSE_ERROR_REVIEW",
        }
    ]

    summary = {
        "project_root": str(PROJECT_ROOT),
        "total_files_classified": len(candidates),
        "status_counts": dict(sorted(counts.items())),
        "safe_quarantine_count": counts["QUARANTINE_SAFE"],
        "exact_duplicate_removal_candidates": counts["DUPLICATE_REMOVE_CANDIDATE"],
        "empty_module_candidates": counts["EMPTY_REMOVE_CANDIDATE"],
        "parse_error_review_count": counts["PARSE_ERROR_REVIEW"],
        "important_rule": (
            "No file may be deleted solely because it is not reachable from main.py."
        ),
        "next_stage": (
            "Review only HIGH-confidence quarantine and duplicate candidates, "
            "then generate a reversible move manifest."
        ),
        "actionable_candidates": [
            {
                "path": candidate.path,
                "status": candidate.status,
                "confidence": candidate.confidence,
                "reason": candidate.reason,
            }
            for candidate in actionable
        ],
    }

    summary_path = OUTPUT_DIR / "cleanup_summary.json"
    summary_path.write_text(
        json.dumps(summary, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    return summary


def write_markdown(summary: dict[str, object]) -> None:
    counts = summary["status_counts"]

    lines = [
        "# Atlas Phase 3B Cleanup Candidate Report",
        "",
        "This report is read-only. No source file was moved or deleted.",
        "",
        "## Classification counts",
        "",
    ]

    for status, count in counts.items():
        lines.append(f"- `{status}`: {count}")

    lines.extend([
        "",
        "## Safety rule",
        "",
        "A file is never deleted only because it is not reachable from `main.py`.",
        "",
        "## Next action",
        "",
        "Only high-confidence backup/archive and exact-duplicate candidates "
        "will be considered for reversible quarantine.",
    ])

    (OUTPUT_DIR / "README.md").write_text(
        "\n".join(lines),
        encoding="utf-8",
    )


def main() -> int:
    inventory_path = AUDIT_DIR / "file_inventory.csv"
    duplicates_path = AUDIT_DIR / "exact_duplicate_files.csv"

    if not inventory_path.exists():
        print(f"Missing report: {inventory_path}")
        return 1

    inventory = read_csv(inventory_path)

    duplicate_groups: dict[str, list[dict[str, str]]] = defaultdict(list)

    if duplicates_path.exists():
        for row in read_csv(duplicates_path):
            duplicate_groups[row["sha256"]].append(row)

    candidates = [
        classify(row, duplicate_groups)
        for row in inventory
    ]

    candidates.sort(
        key=lambda item: (
            item.status,
            item.path.lower(),
        )
    )

    write_candidates(candidates)
    summary = write_summary(candidates)
    write_markdown(summary)

    print("=" * 72)
    print("ATLAS CLEANUP CANDIDATE ANALYZER v1.0")
    print("=" * 72)
    print(f"Project              : {PROJECT_ROOT}")
    print(f"Files classified     : {summary['total_files_classified']}")
    print()

    for status, count in summary["status_counts"].items():
        print(f"{status:<30}: {count}")

    print()
    print(f"Reports: {OUTPUT_DIR}")
    print()
    print("ANALYSIS COMPLETED — NO FILES WERE MOVED OR DELETED")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
