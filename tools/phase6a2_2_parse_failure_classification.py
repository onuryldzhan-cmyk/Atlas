"""
============================================================
ATLAS PHASE 6A2.2 — PARSE FAILURE CLASSIFICATION v1.0
============================================================

Purpose
-------
Classify all Python parse failures before market-data migration.

Classifies each failure by:
- location
- likely activity level
- architecture relevance
- syntax error type
- whether imported by active composition roots
- whether it blocks Phase 6A migration

Safety
------
- Read-only
- Does not import Atlas modules
- Does not modify source files
- Does not connect to exchanges
============================================================
"""

from __future__ import annotations

import ast
import json
from collections import defaultdict, deque
from datetime import UTC, datetime
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
REPORT_DIR = ROOT / "reports" / "phase6_parse_failure_classification"

HARD_EXCLUDED = {
    ".git", ".idea", ".vscode", "__pycache__", "venv", ".venv",
    "env", "site-packages", "node_modules", "reports", "backups",
}

LOW_PRIORITY_MARKERS = {
    "archive", "archives", "backup", "backups", "old", "legacy",
    "deprecated", "unused", "trash", "temp", "tmp", "examples",
    "example", "prototype", "experimental",
}

MARKET_RELEVANT_PARTS = {
    "market", "feed", "exchange", "candle", "price", "binance",
    "application", "runtime", "main", "intelligence", "analysis",
}

ENTRYPOINTS = [
    "main.py",
    "core/application.py",
    "core/runtime.py",
    "atlas_os/kernel/kernel.py",
]


def norm(path: Path) -> str:
    return str(path).replace("\\", "/")


def hard_excluded(path: Path) -> bool:
    parts = {part.lower() for part in path.relative_to(ROOT).parts}
    return bool(parts & HARD_EXCLUDED)


def low_priority_path(relative: str) -> bool:
    parts = {part.lower() for part in Path(relative).parts}
    return bool(parts & LOW_PRIORITY_MARKERS)


def module_name(relative: str) -> str:
    path = Path(relative)
    parts = list(path.with_suffix("").parts)

    if parts and parts[-1] == "__init__":
        parts = parts[:-1]

    return ".".join(parts)


def parse_imports(tree: ast.Module) -> set[str]:
    imports = set()

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.update(alias.name for alias in node.names)

        elif isinstance(node, ast.ImportFrom):
            module = node.module or ""
            if module:
                imports.add(module)

    return imports


def build_module_index(paths: list[Path]) -> dict[str, str]:
    index = {}

    for path in paths:
        relative = norm(path.relative_to(ROOT))
        name = module_name(relative)

        if name:
            index[name] = relative

    return index


def resolve_import(import_name: str, module_index: dict[str, str]) -> str | None:
    candidate = import_name

    while candidate:
        if candidate in module_index:
            return module_index[candidate]

        if "." not in candidate:
            break

        candidate = candidate.rsplit(".", 1)[0]

    return None


def classify_error(exc: SyntaxError, context: str) -> str:
    message = (exc.msg or "").lower()
    line = context.strip()

    if "unexpected indent" in message:
        return "INDENTATION_UNEXPECTED"

    if "expected an indented block" in message:
        return "INDENTATION_MISSING_BLOCK"

    if "unindent does not match" in message:
        return "INDENTATION_MISMATCH"

    if "unterminated string" in message:
        return "UNTERMINATED_STRING"

    if "was never closed" in message:
        return "UNCLOSED_DELIMITER"

    if "invalid syntax" in message:
        if line.startswith("<<<<<<<") or line.startswith("=======") or line.startswith(">>>>>>>"):
            return "MERGE_CONFLICT_MARKER"

        if line.startswith("PS ") or line.startswith("Traceback"):
            return "TERMINAL_OUTPUT_IN_SOURCE"

        return "INVALID_SYNTAX"

    if "invalid character" in message:
        return "INVALID_CHARACTER"

    return "OTHER_SYNTAX_ERROR"


def market_relevant(relative: str) -> bool:
    lower = relative.lower()
    return any(part in lower for part in MARKET_RELEVANT_PARTS)


def main() -> int:
    REPORT_DIR.mkdir(parents=True, exist_ok=True)

    paths = [
        path
        for path in ROOT.rglob("*.py")
        if path.is_file() and not hard_excluded(path)
    ]

    module_index = build_module_index(paths)

    parse_ok = {}
    failures = []

    for path in sorted(paths):
        relative = norm(path.relative_to(ROOT))
        lines = path.read_text(
            encoding="utf-8",
            errors="replace",
        ).splitlines()
        source = "\n".join(lines)

        try:
            tree = ast.parse(source, filename=str(path))
            parse_ok[relative] = {
                "imports": parse_imports(tree),
            }
        except SyntaxError as exc:
            context = ""
            if exc.lineno and 1 <= exc.lineno <= len(lines):
                context = lines[exc.lineno - 1].strip()

            failures.append({
                "file": relative,
                "line": exc.lineno,
                "offset": exc.offset,
                "message": exc.msg,
                "context": context[:300],
                "error_type": classify_error(exc, context),
                "low_priority_path": low_priority_path(relative),
                "market_relevant_path": market_relevant(relative),
            })

    graph = defaultdict(set)
    reverse_graph = defaultdict(set)

    for relative, data in parse_ok.items():
        for imported in data["imports"]:
            target = resolve_import(imported, module_index)
            if target:
                graph[relative].add(target)
                reverse_graph[target].add(relative)

    reachable = set()
    queue = deque(
        entry
        for entry in ENTRYPOINTS
        if entry in parse_ok
    )

    while queue:
        current = queue.popleft()

        if current in reachable:
            continue

        reachable.add(current)

        for target in graph.get(current, set()):
            if target not in reachable:
                queue.append(target)

    failure_files = {item["file"] for item in failures}

    for item in failures:
        importers = sorted(reverse_graph.get(item["file"], set()))
        reachable_importers = sorted(
            importer
            for importer in importers
            if importer in reachable
        )

        item["imported_by"] = importers
        item["imported_by_reachable_module"] = reachable_importers
        item["reachable_from_entrypoint"] = bool(reachable_importers)

        if item["reachable_from_entrypoint"] and item["market_relevant_path"]:
            severity = "CRITICAL"
            blocks_migration = True
        elif item["reachable_from_entrypoint"]:
            severity = "HIGH"
            blocks_migration = True
        elif item["market_relevant_path"] and not item["low_priority_path"]:
            severity = "HIGH"
            blocks_migration = True
        elif not item["low_priority_path"]:
            severity = "MEDIUM"
            blocks_migration = False
        else:
            severity = "LOW"
            blocks_migration = False

        item["severity"] = severity
        item["blocks_phase6a_migration"] = blocks_migration

    counts = {
        "total": len(failures),
        "critical": sum(item["severity"] == "CRITICAL" for item in failures),
        "high": sum(item["severity"] == "HIGH" for item in failures),
        "medium": sum(item["severity"] == "MEDIUM" for item in failures),
        "low": sum(item["severity"] == "LOW" for item in failures),
        "blocking": sum(item["blocks_phase6a_migration"] for item in failures),
        "reachable": sum(item["reachable_from_entrypoint"] for item in failures),
        "market_relevant": sum(item["market_relevant_path"] for item in failures),
    }

    report = {
        "phase": "6A2.2",
        "generated_utc": datetime.now(UTC).isoformat(),
        "summary": {
            "python_files_scanned": len(paths),
            "parse_success": len(parse_ok),
            "parse_failures": counts,
            "entrypoints_found": [
                item for item in ENTRYPOINTS if item in parse_ok
            ],
            "reachable_parseable_modules": len(reachable),
        },
        "failures": sorted(
            failures,
            key=lambda item: (
                {"CRITICAL": 0, "HIGH": 1, "MEDIUM": 2, "LOW": 3}[item["severity"]],
                item["file"],
            ),
        ),
        "safety": {
            "source_files_modified": False,
            "atlas_modules_imported": False,
            "exchange_connections_opened": False,
        },
    }

    json_path = REPORT_DIR / "phase6a2_2_parse_failure_classification.json"
    json_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    lines = [
        "=" * 78,
        "ATLAS PHASE 6A2.2 — PARSE FAILURE CLASSIFICATION",
        "=" * 78,
        "",
        f"Python files scanned : {len(paths)}",
        f"Parse success        : {len(parse_ok)}",
        f"Parse failures       : {counts['total']}",
        f"CRITICAL             : {counts['critical']}",
        f"HIGH                 : {counts['high']}",
        f"MEDIUM               : {counts['medium']}",
        f"LOW                  : {counts['low']}",
        f"Blocking Phase 6A    : {counts['blocking']}",
        f"Reachable failures   : {counts['reachable']}",
        f"Market relevant      : {counts['market_relevant']}",
        "",
        "FAILURES",
        "-" * 78,
    ]

    for item in report["failures"]:
        lines.append(
            f"[{item['severity']}] {item['file']}:{item.get('line')} "
            f"({item['error_type']})"
        )
        lines.append(f"  Message : {item.get('message')}")
        lines.append(f"  Context : {item.get('context')}")
        lines.append(
            f"  Blocks  : {item['blocks_phase6a_migration']}"
        )

        if item["imported_by_reachable_module"]:
            lines.append(
                "  Active importers: "
                + ", ".join(item["imported_by_reachable_module"])
            )
        elif item["imported_by"]:
            lines.append(
                "  Importers: "
                + ", ".join(item["imported_by"])
            )

        lines.append("")

    text_path = REPORT_DIR / "phase6a2_2_parse_failure_classification.txt"
    text_path.write_text(
        "\n".join(lines),
        encoding="utf-8",
    )

    blocking_path = REPORT_DIR / "phase6a2_2_blocking_failures.txt"
    blocking_lines = [
        item
        for item in report["failures"]
        if item["blocks_phase6a_migration"]
    ]

    blocking_path.write_text(
        "\n".join(
            [
                f"[{item['severity']}] {item['file']}:{item.get('line')} "
                f"{item.get('message')} | {item.get('context')}"
                for item in blocking_lines
            ]
        ) + ("\n" if blocking_lines else "No blocking parse failures.\n"),
        encoding="utf-8",
    )

    print("=" * 72)
    print("ATLAS PHASE 6A2.2 - PARSE FAILURE CLASSIFICATION")
    print("=" * 72)
    print(f"Python files scanned : {len(paths)}")
    print(f"Parse success        : {len(parse_ok)}")
    print(f"Parse failures       : {counts['total']}")
    print(f"CRITICAL             : {counts['critical']}")
    print(f"HIGH                 : {counts['high']}")
    print(f"MEDIUM               : {counts['medium']}")
    print(f"LOW                  : {counts['low']}")
    print(f"Blocking Phase 6A    : {counts['blocking']}")
    print(f"Reachable failures   : {counts['reachable']}")
    print(f"Market relevant      : {counts['market_relevant']}")
    print()

    for item in report["failures"]:
        if item["severity"] in {"CRITICAL", "HIGH"}:
            print(
                f"[{item['severity']}] "
                f"{item['file']}:{item.get('line')} "
                f"-> {item['error_type']}"
            )

    print()
    print(f"JSON report    : {json_path}")
    print(f"Text report    : {text_path}")
    print(f"Blocking list  : {blocking_path}")
    print()
    print("PHASE 6A2.2 COMPLETED - READ-ONLY AUDIT")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
