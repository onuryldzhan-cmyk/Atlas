"""
============================================================
ATLAS PHASE 5C2 — PRODUCTION OBSERVABILITY PATCH v1.0
============================================================

Targets
-------
- atlas_os/observability/metrics.py :: MetricsService
- core/database.py :: DatabaseManager
- core/intelligence/loop/intelligence_loop.py :: IntelligenceLoop

Guarantees
----------
- Validates target class and methods with AST
- Creates timestamped backups
- Adds component-level logging without importing Atlas modules
- Compiles all modified files
- Automatically restores backups if validation fails
- Writes a machine-readable report
============================================================
"""

from __future__ import annotations

import ast
import hashlib
import json
import py_compile
import re
import shutil
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Iterable


ROOT = Path(__file__).resolve().parent.parent
REPORT_DIR = ROOT / "reports" / "phase5_observability_patch"
BACKUP_ROOT = ROOT / "backups" / "phase5c2_observability"

TARGETS = {
    "atlas_os/observability/metrics.py": {
        "class": "MetricsService",
        "required_methods": {"__init__", "_on_start", "_on_stop"},
        "logger_name": "AtlasAI.MetricsService",
        "method_logs": {
            "__init__": (
                "debug",
                "MetricsService initialization started.",
            ),
            "_on_start": (
                "info",
                "MetricsService starting.",
            ),
            "_on_stop": (
                "info",
                "MetricsService stopping.",
            ),
        },
    },
    "core/database.py": {
        "class": "DatabaseManager",
        "required_methods": {
            "__init__",
            "_ensure_file",
            "save_trade",
            "get_trades",
            "update_trade",
            "get_open_trades",
            "_write",
        },
        "logger_name": "AtlasAI.DatabaseManager",
        "method_logs": {
            "__init__": (
                "debug",
                "DatabaseManager initialization started.",
            ),
            "_ensure_file": (
                "debug",
                "Trade database file verification started.",
            ),
            "save_trade": (
                "info",
                "Trade persistence requested.",
            ),
            "get_trades": (
                "debug",
                "Trade database read requested.",
            ),
            "update_trade": (
                "info",
                "Trade update requested.",
            ),
            "get_open_trades": (
                "debug",
                "Open-trade query requested.",
            ),
            "_write": (
                "debug",
                "Trade database write requested.",
            ),
        },
    },
    "core/intelligence/loop/intelligence_loop.py": {
        "class": "IntelligenceLoop",
        "required_methods": {"__init__", "run_cycle", "start", "stop"},
        "logger_name": "AtlasAI.IntelligenceLoop",
        "method_logs": {
            "__init__": (
                "debug",
                "IntelligenceLoop initialization started.",
            ),
            "run_cycle": (
                "debug",
                "Intelligence cycle started.",
            ),
            "start": (
                "info",
                "IntelligenceLoop start requested.",
            ),
            "stop": (
                "info",
                "IntelligenceLoop stop requested.",
            ),
        },
    },
}


class PatchError(RuntimeError):
    """Raised when the Phase 5C2 patch cannot be applied safely."""


def sha256(path: Path) -> str:
    digest = hashlib.sha256()

    with path.open("rb") as file:
        for chunk in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(chunk)

    return digest.hexdigest()


def detect_newline(text: str) -> str:
    return "\r\n" if "\r\n" in text else "\n"


def parse_source(path: Path, text: str) -> ast.Module:
    try:
        return ast.parse(text, filename=str(path))
    except SyntaxError as exc:
        raise PatchError(
            f"Syntax error before patch in {path}: {exc}"
        ) from exc


def class_node(
    tree: ast.Module,
    class_name: str,
) -> ast.ClassDef:
    matches = [
        node
        for node in tree.body
        if isinstance(node, ast.ClassDef)
        and node.name == class_name
    ]

    if len(matches) != 1:
        raise PatchError(
            f"Expected exactly one {class_name} class; found {len(matches)}."
        )

    return matches[0]


def method_nodes(
    node: ast.ClassDef,
) -> dict[str, ast.FunctionDef | ast.AsyncFunctionDef]:
    return {
        child.name: child
        for child in node.body
        if isinstance(
            child,
            (ast.FunctionDef, ast.AsyncFunctionDef),
        )
    }


def has_logging_import(tree: ast.Module) -> bool:
    for node in tree.body:
        if isinstance(node, ast.Import):
            if any(alias.name == "logging" for alias in node.names):
                return True

        if (
            isinstance(node, ast.ImportFrom)
            and node.module == "logging"
        ):
            return True

    return False


def has_module_logger(text: str) -> bool:
    pattern = re.compile(
        r"(?m)^\s*logger\s*=\s*logging\.getLogger\s*\("
    )
    return bool(pattern.search(text))


def import_insertion_line(tree: ast.Module) -> int:
    index = 0

    if (
        tree.body
        and isinstance(tree.body[0], ast.Expr)
        and isinstance(tree.body[0].value, ast.Constant)
        and isinstance(tree.body[0].value.value, str)
    ):
        index = tree.body[0].end_lineno or tree.body[0].lineno

    for node in tree.body:
        if isinstance(node, ast.ImportFrom) and node.module == "__future__":
            index = max(index, node.end_lineno or node.lineno)

    return index


def imports_end_line(tree: ast.Module) -> int:
    import_lines = [
        node.end_lineno or node.lineno
        for node in tree.body
        if isinstance(node, (ast.Import, ast.ImportFrom))
    ]

    return max(import_lines, default=import_insertion_line(tree))


def indentation_for_body(
    lines: list[str],
    node: ast.FunctionDef | ast.AsyncFunctionDef,
) -> str:
    if not node.body:
        return " " * (node.col_offset + 4)

    first_statement = node.body[0]
    source_line = lines[first_statement.lineno - 1]
    return source_line[: len(source_line) - len(source_line.lstrip())]


def method_already_logged(
    text: str,
    node: ast.FunctionDef | ast.AsyncFunctionDef,
) -> bool:
    start = node.lineno - 1
    end = node.end_lineno or node.lineno
    fragment = "\n".join(text.splitlines()[start:end])
    return bool(re.search(r"\blogger\.(debug|info|warning|error|exception|critical)\s*\(", fragment))


def insert_lines(
    lines: list[str],
    insertions: Iterable[tuple[int, list[str]]],
) -> list[str]:
    result = list(lines)

    for index, new_lines in sorted(
        insertions,
        key=lambda item: item[0],
        reverse=True,
    ):
        result[index:index] = new_lines

    return result


def patch_source(
    path: Path,
    config: dict,
) -> tuple[str, dict]:
    original = path.read_text(encoding="utf-8")
    newline = detect_newline(original)
    tree = parse_source(path, original)

    class_name = config["class"]
    target_class = class_node(tree, class_name)
    methods = method_nodes(target_class)

    missing_methods = sorted(
        config["required_methods"] - set(methods)
    )

    if missing_methods:
        raise PatchError(
            f"{path}: missing required methods: {missing_methods}"
        )

    lines = original.splitlines()
    insertions: list[tuple[int, list[str]]] = []
    changes = []

    if not has_logging_import(tree):
        line = import_insertion_line(tree)
        insertions.append((line, ["", "import logging"]))
        changes.append("logging_import")

    if not has_module_logger(original):
        line = imports_end_line(tree)
        insertions.append(
            (
                line,
                [
                    "",
                    "",
                    f'logger = logging.getLogger("{config["logger_name"]}")',
                ],
            )
        )
        changes.append("module_logger")

    for method_name, (level, message) in config["method_logs"].items():
        node = methods[method_name]

        if method_already_logged(original, node):
            continue

        indent = indentation_for_body(lines, node)
        statement = f'{indent}logger.{level}("{message}")'

        if (
            node.body
            and isinstance(node.body[0], ast.Expr)
            and isinstance(node.body[0].value, ast.Constant)
            and isinstance(node.body[0].value.value, str)
        ):
            insertion_line = node.body[0].end_lineno or node.body[0].lineno
        else:
            insertion_line = node.body[0].lineno - 1

        insertions.append(
            (
                insertion_line,
                ["", statement],
            )
        )
        changes.append(f"log:{method_name}")

    patched_lines = insert_lines(lines, insertions)
    patched = newline.join(patched_lines)

    if original.endswith(("\n", "\r\n")):
        patched += newline

    parse_source(path, patched)

    return patched, {
        "class": class_name,
        "changes": changes,
        "changed": patched != original,
    }


def compile_files(paths: list[Path]) -> None:
    for path in paths:
        py_compile.compile(
            str(path),
            doraise=True,
        )


def restore(
    backups: dict[Path, Path],
) -> None:
    for target, backup in backups.items():
        if backup.exists():
            shutil.copy2(backup, target)


def main() -> int:
    timestamp = datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
    backup_dir = BACKUP_ROOT / timestamp
    backup_dir.mkdir(parents=True, exist_ok=True)
    REPORT_DIR.mkdir(parents=True, exist_ok=True)

    report = {
        "phase": "5C2",
        "timestamp_utc": datetime.now(UTC).isoformat(),
        "status": "STARTED",
        "targets": [],
        "backup_dir": str(backup_dir),
    }

    backups: dict[Path, Path] = {}
    modified: list[Path] = []

    try:
        for relative, config in TARGETS.items():
            target = ROOT / Path(relative)

            if not target.exists():
                raise PatchError(
                    f"Target file not found: {relative}"
                )

            before_hash = sha256(target)
            backup = backup_dir / Path(relative)
            backup.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(target, backup)
            backups[target] = backup

            patched, details = patch_source(
                target,
                config,
            )

            if details["changed"]:
                target.write_text(
                    patched,
                    encoding="utf-8",
                    newline="",
                )
                modified.append(target)

            after_hash = sha256(target)

            report["targets"].append({
                "file": relative,
                "class": config["class"],
                "before_sha256": before_hash,
                "after_sha256": after_hash,
                "changed": details["changed"],
                "changes": details["changes"],
                "backup": str(backup),
            })

        compile_files(
            [ROOT / Path(relative) for relative in TARGETS]
        )

        for relative, config in TARGETS.items():
            target = ROOT / Path(relative)
            text = target.read_text(
                encoding="utf-8",
                errors="replace",
            )
            tree = parse_source(target, text)
            node = class_node(tree, config["class"])
            methods = method_nodes(node)

            if not has_logging_import(tree):
                raise PatchError(
                    f"Validation failed: no logging import in {relative}"
                )

            if not has_module_logger(text):
                raise PatchError(
                    f"Validation failed: no module logger in {relative}"
                )

            if not config["required_methods"].issubset(methods):
                raise PatchError(
                    f"Validation failed: method structure changed in {relative}"
                )

        report["status"] = "COMPLETED"
        report["modified_files"] = [
            str(path.relative_to(ROOT))
            for path in modified
        ]

    except Exception as exc:
        restore(backups)
        report["status"] = "ROLLED_BACK"
        report["error"] = f"{type(exc).__name__}: {exc}"

        report_path = (
            REPORT_DIR
            / f"phase5c2_patch_{timestamp}.json"
        )
        report_path.write_text(
            json.dumps(report, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

        print("=" * 72)
        print("ATLAS PHASE 5C2 - PATCH FAILED")
        print("=" * 72)
        print(report["error"])
        print()
        print("All modified source files were restored from backup.")
        print(f"Report : {report_path}")
        return 1

    report_path = (
        REPORT_DIR
        / f"phase5c2_patch_{timestamp}.json"
    )
    report_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    print("=" * 72)
    print("ATLAS PHASE 5C2 - PRODUCTION OBSERVABILITY PATCH")
    print("=" * 72)
    print(f"Modified files : {len(modified)}")

    for item in report["targets"]:
        status = "UPDATED" if item["changed"] else "ALREADY COMPLIANT"
        print(f"[{status}] {item['file']}")
        for change in item["changes"]:
            print(f"  - {change}")

    print()
    print("Compilation     : PASSED")
    print("AST validation  : PASSED")
    print(f"Backup          : {backup_dir}")
    print(f"Report          : {report_path}")
    print()
    print("PHASE 5C2 COMPLETED")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
