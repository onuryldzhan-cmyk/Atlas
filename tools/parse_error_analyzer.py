"""
============================================================
ATLAS PARSE ERROR ANALYZER v1.0
============================================================

Purpose
-------
Analyzes Python files that failed AST parsing during Phase 3.

Safety
------
- Read-only
- No source modification
- No file move
- No deletion

Outputs
-------
- Exact syntax error location
- Error type and message
- Import/reference evidence
- Backup/archive classification
- Suggested disposition
============================================================
"""

from __future__ import annotations

import ast
import csv
import json
import re
from collections import defaultdict
from dataclasses import asdict, dataclass
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent.parent
INPUT_REPORT = (
    PROJECT_ROOT
    / "reports"
    / "phase3_cleanup_candidates"
    / "cleanup_candidates.csv"
)
OUTPUT_DIR = PROJECT_ROOT / "reports" / "phase3_parse_error_analysis"

EXCLUDED_DIRS = {
    ".git",
    ".venv",
    "venv",
    "__pycache__",
    ".pytest_cache",
    "reports",
    "_quarantine",
}

BACKUP_PATTERNS = (
    r"(^|/)phase\d+[a-z]*_backup[^/]*/",
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
)


@dataclass
class ParseErrorEntry:
    path: str
    exists: bool
    syntax_error_type: str
    syntax_error_message: str
    line: int
    column: int
    source_line: str
    imported_by: list[str]
    text_mentions: list[str]
    is_backup_or_archive: bool
    is_test: bool
    is_tool: bool
    classification: str
    recommended_action: str
    confidence: str


def normalize(value: str) -> str:
    return value.replace("\\", "/").strip()


def pattern_match(path: str, patterns: tuple[str, ...]) -> bool:
    return any(re.search(pattern, path, re.IGNORECASE) for pattern in patterns)


def excluded(path: Path) -> bool:
    try:
        relative = path.relative_to(PROJECT_ROOT)
    except ValueError:
        return True

    return any(part in EXCLUDED_DIRS for part in relative.parts)


def module_name_from_path(relative_path: str) -> str:
    path = Path(relative_path)

    if path.suffix != ".py":
        return ""

    parts = list(path.with_suffix("").parts)

    if parts and parts[-1] == "__init__":
        parts = parts[:-1]

    return ".".join(parts)


def read_candidates() -> list[dict[str, str]]:
    if not INPUT_REPORT.exists():
        raise FileNotFoundError(
            f"Missing Phase 3B report: {INPUT_REPORT}"
        )

    with INPUT_REPORT.open(
        "r",
        encoding="utf-8-sig",
        newline="",
    ) as file:
        return [
            row
            for row in csv.DictReader(file)
            if row.get("status") == "PARSE_ERROR_REVIEW"
        ]


def import_references(target_module: str, target_path: str) -> list[str]:
    references: set[str] = set()
    target_absolute = (PROJECT_ROOT / target_path).resolve()

    for source in PROJECT_ROOT.rglob("*.py"):
        if excluded(source):
            continue

        try:
            if source.resolve() == target_absolute:
                continue

            text = source.read_text(
                encoding="utf-8",
                errors="replace",
            )
            tree = ast.parse(text, filename=str(source))
        except (OSError, SyntaxError):
            continue

        imported_modules: set[str] = set()

        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported_modules.update(
                    alias.name for alias in node.names
                )

            elif isinstance(node, ast.ImportFrom) and node.module:
                imported_modules.add(node.module)

        for imported in imported_modules:
            if (
                imported == target_module
                or imported.startswith(target_module + ".")
                or target_module.startswith(imported + ".")
            ):
                references.add(
                    normalize(str(source.relative_to(PROJECT_ROOT)))
                )

    return sorted(references)


def text_mentions(target_path: str) -> list[str]:
    target_name = Path(target_path).name
    target_stem = Path(target_path).stem
    mentions: set[str] = set()

    for pattern in ("*.md", "*.txt", "*.ps1", "*.bat", "*.json"):
        for source in PROJECT_ROOT.rglob(pattern):
            if excluded(source):
                continue

            try:
                text = source.read_text(
                    encoding="utf-8",
                    errors="replace",
                )
            except OSError:
                continue

            if (
                target_path in text
                or target_name in text
                or target_stem in text
            ):
                mentions.add(
                    normalize(str(source.relative_to(PROJECT_ROOT)))
                )

    return sorted(mentions)


def analyze_syntax(path: Path) -> tuple[str, str, int, int, str]:
    try:
        text = path.read_text(
            encoding="utf-8",
            errors="replace",
        )
    except OSError as error:
        return (
            type(error).__name__,
            str(error),
            0,
            0,
            "",
        )

    try:
        ast.parse(text, filename=str(path))
    except SyntaxError as error:
        line_number = int(error.lineno or 0)
        column = int(error.offset or 0)
        lines = text.splitlines()
        source_line = ""

        if 1 <= line_number <= len(lines):
            source_line = lines[line_number - 1].strip()

        return (
            type(error).__name__,
            error.msg,
            line_number,
            column,
            source_line,
        )

    return (
        "",
        "",
        0,
        0,
        "",
    )


def classify(
    relative: str,
    imported_by: list[str],
    is_backup: bool,
    is_test: bool,
    is_tool: bool,
) -> tuple[str, str, str]:
    if is_backup and not imported_by:
        return (
            "BACKUP_QUARANTINE",
            "Move to reversible quarantine after review.",
            "HIGH",
        )

    if imported_by:
        return (
            "ACTIVE_CODE_REPAIR",
            "Repair syntax before further cleanup; real imports exist.",
            "HIGH",
        )

    if is_test:
        return (
            "TEST_CODE_REPAIR",
            "Repair or retire test after checking current test coverage.",
            "MEDIUM",
        )

    if is_tool:
        return (
            "TOOL_REPAIR_OR_RETIRE",
            "Inspect whether tool is still needed; repair or quarantine.",
            "MEDIUM",
        )

    return (
        "SYNTAX_ERROR_REVIEW",
        "Manual review required before repair or quarantine.",
        "MEDIUM",
    )


def main() -> int:
    rows = read_candidates()
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    entries: list[ParseErrorEntry] = []

    for row in rows:
        relative = normalize(row["path"])
        path = PROJECT_ROOT / relative
        exists = path.exists()
        module = module_name_from_path(relative)

        imported_by = (
            import_references(module, relative)
            if exists and module
            else []
        )
        mentions = text_mentions(relative) if exists else []

        error_type, message, line, column, source_line = (
            analyze_syntax(path)
            if exists
            else ("FileNotFoundError", "File does not exist.", 0, 0, "")
        )

        is_backup = pattern_match(relative, BACKUP_PATTERNS)
        is_test = pattern_match(relative, TEST_PATTERNS)
        is_tool = pattern_match(relative, TOOL_PATTERNS)

        classification, action, confidence = classify(
            relative,
            imported_by,
            is_backup,
            is_test,
            is_tool,
        )

        entries.append(
            ParseErrorEntry(
                path=relative,
                exists=exists,
                syntax_error_type=error_type,
                syntax_error_message=message,
                line=line,
                column=column,
                source_line=source_line,
                imported_by=imported_by,
                text_mentions=mentions,
                is_backup_or_archive=is_backup,
                is_test=is_test,
                is_tool=is_tool,
                classification=classification,
                recommended_action=action,
                confidence=confidence,
            )
        )

    counts: dict[str, int] = defaultdict(int)

    for entry in entries:
        counts[entry.classification] += 1

    summary = {
        "project_root": str(PROJECT_ROOT),
        "files_analyzed": len(entries),
        "classification_counts": dict(sorted(counts.items())),
        "entries": [asdict(entry) for entry in entries],
        "safety": "No files were modified, moved, or deleted.",
    }

    (OUTPUT_DIR / "parse_error_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    csv_path = OUTPUT_DIR / "parse_error_entries.csv"

    with csv_path.open(
        "w",
        encoding="utf-8-sig",
        newline="",
    ) as file:
        fieldnames = list(asdict(entries[0]).keys()) if entries else []
        writer = csv.DictWriter(file, fieldnames=fieldnames)
        writer.writeheader()

        for entry in entries:
            data = asdict(entry)
            data["imported_by"] = " | ".join(entry.imported_by)
            data["text_mentions"] = " | ".join(entry.text_mentions)
            writer.writerow(data)

    markdown = [
        "# Atlas Phase 3E Parse Error Analysis",
        "",
        "No files were modified, moved, or deleted.",
        "",
        "## Classification counts",
        "",
    ]

    for key, value in sorted(counts.items()):
        markdown.append(f"- `{key}`: {value}")

    markdown.extend([
        "",
        "## Files",
        "",
    ])

    for entry in entries:
        markdown.extend([
            f"### `{entry.path}`",
            "",
            f"- Classification: `{entry.classification}`",
            f"- Error: `{entry.syntax_error_message}`",
            f"- Location: line {entry.line}, column {entry.column}",
            f"- Imported by: {len(entry.imported_by)} file(s)",
            f"- Recommendation: {entry.recommended_action}",
            "",
        ])

    (OUTPUT_DIR / "README.md").write_text(
        "\n".join(markdown),
        encoding="utf-8",
    )

    print("=" * 72)
    print("ATLAS PARSE ERROR ANALYZER v1.0")
    print("=" * 72)
    print(f"Project        : {PROJECT_ROOT}")
    print(f"Files analyzed : {len(entries)}")
    print()

    for key, value in sorted(counts.items()):
        print(f"{key:<28}: {value}")

    print()
    print(f"Reports: {OUTPUT_DIR}")
    print()
    print("PARSE ERROR ANALYSIS COMPLETED — NO FILES WERE MODIFIED")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
