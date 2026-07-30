"""
============================================================
ATLAS ARCHITECTURE AUDIT v1.0
============================================================

Read-only architecture audit.

Produces
--------
- JSON report
- CSV file inventory
- CSV exact duplicate groups
- CSV duplicate class names
- Reachability summary from main.py

Safety
------
- Does not modify source files
- Does not move files
- Does not delete files
============================================================
"""

from __future__ import annotations

import ast
import csv
import hashlib
import json
import sys

from collections import defaultdict, deque
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterable


PROJECT_ROOT = Path(__file__).resolve().parent.parent

EXCLUDED_DIRS = {
    ".git",
    ".idea",
    ".pytest_cache",
    ".venv",
    "venv",
    "__pycache__",
    "archive_unused_2026-07-22",
    "runtime_data",
    "logs",
}

REPORT_DIR = PROJECT_ROOT / "reports" / "phase3_architecture_audit"


@dataclass
class FileRecord:
    path: str
    module: str
    loc: int
    sha256: str
    parse_ok: bool
    classes: list[str]
    functions: list[str]
    imports: list[str]
    reachable_from_main: bool = False


def is_excluded(path: Path) -> bool:
    return any(part in EXCLUDED_DIRS for part in path.parts)


def iter_python_files() -> Iterable[Path]:
    for path in PROJECT_ROOT.rglob("*.py"):
        if not is_excluded(path.relative_to(PROJECT_ROOT)):
            yield path


def module_name(path: Path) -> str:
    relative = path.relative_to(PROJECT_ROOT).with_suffix("")
    parts = list(relative.parts)

    if parts[-1] == "__init__":
        parts = parts[:-1]

    return ".".join(parts)


def calculate_sha256(path: Path) -> str:
    digest = hashlib.sha256()

    with path.open("rb") as file:
        for block in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(block)

    return digest.hexdigest()


def resolve_import(
    current_module: str,
    imported_module: str,
    level: int,
) -> str:
    if level <= 0:
        return imported_module

    current_parts = current_module.split(".")

    if current_parts:
        current_parts = current_parts[:-1]

    keep = max(0, len(current_parts) - level + 1)
    base_parts = current_parts[:keep]

    if imported_module:
        base_parts.extend(imported_module.split("."))

    return ".".join(part for part in base_parts if part)


def parse_file(path: Path) -> FileRecord:
    text = path.read_text(encoding="utf-8", errors="replace")
    module = module_name(path)

    classes: list[str] = []
    functions: list[str] = []
    imports: list[str] = []
    parse_ok = True

    try:
        tree = ast.parse(text, filename=str(path))

        for node in ast.walk(tree):
            if isinstance(node, (ast.ClassDef,)):
                classes.append(node.name)

            elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                functions.append(node.name)

            elif isinstance(node, ast.Import):
                for alias in node.names:
                    imports.append(alias.name)

            elif isinstance(node, ast.ImportFrom):
                resolved = resolve_import(
                    current_module=module,
                    imported_module=node.module or "",
                    level=node.level,
                )

                if resolved:
                    imports.append(resolved)

    except SyntaxError:
        parse_ok = False

    return FileRecord(
        path=str(path.relative_to(PROJECT_ROOT)),
        module=module,
        loc=len(text.splitlines()),
        sha256=calculate_sha256(path),
        parse_ok=parse_ok,
        classes=sorted(set(classes)),
        functions=sorted(set(functions)),
        imports=sorted(set(imports)),
    )


def build_module_lookup(records: list[FileRecord]) -> dict[str, FileRecord]:
    return {
        record.module: record
        for record in records
        if record.module
    }


def local_import_target(
    imported: str,
    module_lookup: dict[str, FileRecord],
) -> str | None:
    candidate = imported

    while candidate:
        if candidate in module_lookup:
            return candidate

        if "." not in candidate:
            break

        candidate = candidate.rsplit(".", 1)[0]

    return None


def mark_reachable(records: list[FileRecord]) -> set[str]:
    module_lookup = build_module_lookup(records)

    if "main" not in module_lookup:
        return set()

    graph: dict[str, set[str]] = defaultdict(set)

    for record in records:
        for imported in record.imports:
            target = local_import_target(imported, module_lookup)

            if target:
                graph[record.module].add(target)

    reachable: set[str] = set()
    queue: deque[str] = deque(["main"])

    while queue:
        current = queue.popleft()

        if current in reachable:
            continue

        reachable.add(current)

        for neighbor in graph.get(current, set()):
            if neighbor not in reachable:
                queue.append(neighbor)

    for record in records:
        record.reachable_from_main = record.module in reachable

    return reachable


def write_inventory(records: list[FileRecord]) -> None:
    path = REPORT_DIR / "file_inventory.csv"

    with path.open("w", newline="", encoding="utf-8-sig") as file:
        writer = csv.writer(file)
        writer.writerow([
            "path",
            "module",
            "loc",
            "sha256",
            "parse_ok",
            "reachable_from_main",
            "classes",
            "functions",
            "imports",
        ])

        for record in sorted(records, key=lambda item: item.path.lower()):
            writer.writerow([
                record.path,
                record.module,
                record.loc,
                record.sha256,
                record.parse_ok,
                record.reachable_from_main,
                " | ".join(record.classes),
                " | ".join(record.functions),
                " | ".join(record.imports),
            ])


def exact_duplicate_groups(
    records: list[FileRecord],
) -> list[list[FileRecord]]:
    by_hash: dict[str, list[FileRecord]] = defaultdict(list)

    for record in records:
        by_hash[record.sha256].append(record)

    return [
        group
        for group in by_hash.values()
        if len(group) > 1
    ]


def write_exact_duplicates(
    groups: list[list[FileRecord]],
) -> None:
    path = REPORT_DIR / "exact_duplicate_files.csv"

    with path.open("w", newline="", encoding="utf-8-sig") as file:
        writer = csv.writer(file)
        writer.writerow([
            "group_id",
            "sha256",
            "file_count",
            "path",
            "reachable_from_main",
        ])

        for group_id, group in enumerate(groups, start=1):
            for record in sorted(group, key=lambda item: item.path.lower()):
                writer.writerow([
                    group_id,
                    record.sha256,
                    len(group),
                    record.path,
                    record.reachable_from_main,
                ])


def duplicate_class_groups(
    records: list[FileRecord],
) -> dict[str, list[FileRecord]]:
    mapping: dict[str, list[FileRecord]] = defaultdict(list)

    for record in records:
        for class_name in record.classes:
            mapping[class_name].append(record)

    return {
        class_name: files
        for class_name, files in mapping.items()
        if len(files) > 1
    }


def write_duplicate_classes(
    groups: dict[str, list[FileRecord]],
) -> None:
    path = REPORT_DIR / "duplicate_class_names.csv"

    with path.open("w", newline="", encoding="utf-8-sig") as file:
        writer = csv.writer(file)
        writer.writerow([
            "class_name",
            "file_count",
            "path",
            "module",
            "reachable_from_main",
        ])

        for class_name in sorted(groups):
            files = groups[class_name]

            for record in sorted(files, key=lambda item: item.path.lower()):
                writer.writerow([
                    class_name,
                    len(files),
                    record.path,
                    record.module,
                    record.reachable_from_main,
                ])


def create_summary(
    records: list[FileRecord],
    reachable: set[str],
    duplicate_files: list[list[FileRecord]],
    duplicate_classes: dict[str, list[FileRecord]],
) -> dict:
    return {
        "project_root": str(PROJECT_ROOT),
        "python_version": sys.version,
        "total_python_files": len(records),
        "parse_success": sum(record.parse_ok for record in records),
        "parse_failures": sum(not record.parse_ok for record in records),
        "reachable_modules_from_main": len(reachable),
        "unreachable_modules_from_main": sum(
            bool(record.module)
            and not record.reachable_from_main
            for record in records
        ),
        "exact_duplicate_groups": len(duplicate_files),
        "exact_duplicate_files": sum(
            len(group)
            for group in duplicate_files
        ),
        "duplicate_class_names": len(duplicate_classes),
        "largest_files": [
            {
                "path": record.path,
                "loc": record.loc,
                "reachable_from_main": record.reachable_from_main,
            }
            for record in sorted(
                records,
                key=lambda item: item.loc,
                reverse=True,
            )[:25]
        ],
        "reachable_files": [
            record.path
            for record in sorted(
                records,
                key=lambda item: item.path.lower(),
            )
            if record.reachable_from_main
        ],
    }


def main() -> int:
    print("=" * 72)
    print("ATLAS ARCHITECTURE AUDIT v1.0")
    print("=" * 72)
    print(f"Project: {PROJECT_ROOT}")
    print("Mode   : READ-ONLY")
    print()

    REPORT_DIR.mkdir(parents=True, exist_ok=True)

    records = [
        parse_file(path)
        for path in sorted(iter_python_files())
    ]

    reachable = mark_reachable(records)
    duplicate_files = exact_duplicate_groups(records)
    duplicate_classes = duplicate_class_groups(records)

    write_inventory(records)
    write_exact_duplicates(duplicate_files)
    write_duplicate_classes(duplicate_classes)

    summary = create_summary(
        records=records,
        reachable=reachable,
        duplicate_files=duplicate_files,
        duplicate_classes=duplicate_classes,
    )

    summary_path = REPORT_DIR / "architecture_summary.json"
    summary_path.write_text(
        json.dumps(
            summary,
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    print(f"Python files            : {summary['total_python_files']}")
    print(f"AST parse success       : {summary['parse_success']}")
    print(f"AST parse failures      : {summary['parse_failures']}")
    print(f"Reachable from main.py  : {summary['reachable_modules_from_main']}")
    print(f"Not proven reachable    : {summary['unreachable_modules_from_main']}")
    print(f"Exact duplicate groups  : {summary['exact_duplicate_groups']}")
    print(f"Exact duplicate files   : {summary['exact_duplicate_files']}")
    print(f"Duplicate class names   : {summary['duplicate_class_names']}")
    print()
    print(f"Reports: {REPORT_DIR}")
    print()
    print("AUDIT COMPLETED — NO SOURCE FILES WERE MODIFIED")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
