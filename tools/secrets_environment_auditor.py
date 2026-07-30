"""
============================================================
ATLAS SECRETS & ENVIRONMENT AUDITOR v1.0
============================================================

Purpose
-------
Scans the Atlas codebase for environment-variable usage and
classifies configuration/secrets requirements.

Safety
------
- Read-only
- Does not print secret values
- Does not modify .env
- Does not persist environment variables
- Does not move or delete files
============================================================
"""

from __future__ import annotations

import ast
import csv
import json
import os
import re
from collections import defaultdict
from dataclasses import asdict, dataclass
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent.parent
OUTPUT_DIR = PROJECT_ROOT / "reports" / "phase4_secrets_audit"

EXCLUDED_DIRS = {
    ".git",
    ".venv",
    "venv",
    "__pycache__",
    ".pytest_cache",
    "reports",
    "_quarantine",
}

EXCLUDED_PREFIXES = (
    "phase1_backup",
    "phase2_backup",
    "phase3_backup",
    "phase3b_backup",
    "phase3c_backup",
    "phase3c2_backup",
    "phase3d_backup",
    "phase3e_backup",
    "phase3f_bom_backup",
)

SECRET_HINTS = (
    "SECRET",
    "TOKEN",
    "PASSWORD",
    "PASS",
    "PRIVATE",
    "API_KEY",
    "ACCESS_KEY",
    "SIGNING_KEY",
)

CONFIG_HINTS = (
    "URL",
    "HOST",
    "PORT",
    "MODE",
    "ENV",
    "TIMEOUT",
    "LEVEL",
    "SYMBOL",
    "INTERVAL",
)


@dataclass
class EnvUsage:
    variable: str
    files: list[str]
    line_numbers: list[int]
    access_methods: list[str]
    default_values: list[str]
    current_status: str
    classification: str
    required_guess: str
    recommendation: str


def normalize(value: str) -> str:
    return value.replace("\\", "/")


def excluded(path: Path) -> bool:
    try:
        relative = path.relative_to(PROJECT_ROOT)
    except ValueError:
        return True

    for part in relative.parts:
        lower = part.lower()

        if lower in EXCLUDED_DIRS:
            return True

        if any(lower.startswith(prefix) for prefix in EXCLUDED_PREFIXES):
            return True

    return False


def safe_literal(node: ast.AST | None) -> str:
    if node is None:
        return ""

    if isinstance(node, ast.Constant):
        if node.value is None:
            return "None"

        if isinstance(node.value, (str, int, float, bool)):
            value = str(node.value)

            if len(value) > 120:
                value = value[:117] + "..."

            return value

    return "<dynamic>"


def variable_classification(name: str) -> str:
    upper = name.upper()

    if any(hint in upper for hint in SECRET_HINTS):
        return "SECRET"

    if any(hint in upper for hint in CONFIG_HINTS):
        return "CONFIGURATION"

    return "UNKNOWN"


def required_guess(
    methods: set[str],
    defaults: set[str],
) -> str:
    if "os.environ[]" in methods:
        return "LIKELY_REQUIRED"

    if defaults and defaults != {"None"}:
        return "LIKELY_OPTIONAL"

    if "os.getenv" in methods or "os.environ.get" in methods:
        return "CONDITIONAL_OR_OPTIONAL"

    return "REVIEW"


def recommendation(
    name: str,
    classification: str,
    required: str,
) -> str:
    if name.endswith("_TEST_SECRET") or "_TEST_" in name:
        return (
            "Inject only for test process; do not persist a real credential."
        )

    if classification == "SECRET":
        if required == "LIKELY_REQUIRED":
            return (
                "Provide through environment or secret manager; never commit."
            )

        return (
            "Keep unset by default; inject only when the related integration runs."
        )

    if classification == "CONFIGURATION":
        return (
            "Document in .env.example with a safe non-secret default where possible."
        )

    return "Review usage and document ownership."


def collect_usages() -> list[EnvUsage]:
    records: dict[str, dict[str, set]] = defaultdict(
        lambda: {
            "files": set(),
            "line_numbers": set(),
            "access_methods": set(),
            "default_values": set(),
        }
    )

    for path in PROJECT_ROOT.rglob("*.py"):
        if excluded(path):
            continue

        try:
            text = path.read_text(
                encoding="utf-8",
                errors="replace",
            )
            tree = ast.parse(text, filename=str(path))
        except (OSError, SyntaxError):
            continue

        relative = normalize(str(path.relative_to(PROJECT_ROOT)))

        for node in ast.walk(tree):
            variable = None
            method = None
            default = ""

            if isinstance(node, ast.Call):
                if (
                    isinstance(node.func, ast.Attribute)
                    and isinstance(node.func.value, ast.Name)
                    and node.func.value.id == "os"
                    and node.func.attr == "getenv"
                    and node.args
                    and isinstance(node.args[0], ast.Constant)
                    and isinstance(node.args[0].value, str)
                ):
                    variable = node.args[0].value
                    method = "os.getenv"
                    default = safe_literal(
                        node.args[1] if len(node.args) > 1 else None
                    )

                elif (
                    isinstance(node.func, ast.Attribute)
                    and isinstance(node.func.value, ast.Attribute)
                    and isinstance(node.func.value.value, ast.Name)
                    and node.func.value.value.id == "os"
                    and node.func.value.attr == "environ"
                    and node.func.attr == "get"
                    and node.args
                    and isinstance(node.args[0], ast.Constant)
                    and isinstance(node.args[0].value, str)
                ):
                    variable = node.args[0].value
                    method = "os.environ.get"
                    default = safe_literal(
                        node.args[1] if len(node.args) > 1 else None
                    )

            elif (
                isinstance(node, ast.Subscript)
                and isinstance(node.value, ast.Attribute)
                and isinstance(node.value.value, ast.Name)
                and node.value.value.id == "os"
                and node.value.attr == "environ"
            ):
                slice_node = node.slice

                if (
                    isinstance(slice_node, ast.Constant)
                    and isinstance(slice_node.value, str)
                ):
                    variable = slice_node.value
                    method = "os.environ[]"

            if not variable or not method:
                continue

            record = records[variable]
            record["files"].add(relative)
            record["line_numbers"].add(int(getattr(node, "lineno", 0)))
            record["access_methods"].add(method)

            if default:
                record["default_values"].add(default)

    usages: list[EnvUsage] = []

    for name, record in sorted(records.items()):
        methods = record["access_methods"]
        defaults = record["default_values"]
        classification = variable_classification(name)
        required = required_guess(methods, defaults)

        usages.append(
            EnvUsage(
                variable=name,
                files=sorted(record["files"]),
                line_numbers=sorted(record["line_numbers"]),
                access_methods=sorted(methods),
                default_values=sorted(defaults),
                current_status=(
                    "SET"
                    if os.environ.get(name) is not None
                    else "UNSET"
                ),
                classification=classification,
                required_guess=required,
                recommendation=recommendation(
                    name,
                    classification,
                    required,
                ),
            )
        )

    return usages


def write_env_example(usages: list[EnvUsage]) -> None:
    lines = [
        "# Atlas AI environment template",
        "# Generated by Phase 4A audit",
        "# Never place real secrets in this file.",
        "",
    ]

    for usage in usages:
        lines.append(
            f"# {usage.classification} | {usage.required_guess}"
        )
        lines.append(f"# Used by: {', '.join(usage.files)}")
        lines.append(f"# {usage.recommendation}")

        if usage.variable.endswith("_TEST_SECRET"):
            lines.append(f"{usage.variable}=test-only-placeholder")
        elif usage.classification == "SECRET":
            lines.append(f"{usage.variable}=")
        elif usage.default_values:
            safe_default = next(
                (
                    value
                    for value in usage.default_values
                    if value not in {"None", "<dynamic>"}
                ),
                "",
            )
            lines.append(f"{usage.variable}={safe_default}")
        else:
            lines.append(f"{usage.variable}=")

        lines.append("")

    (OUTPUT_DIR / ".env.example.generated").write_text(
        "\n".join(lines),
        encoding="utf-8",
    )


def main() -> int:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    usages = collect_usages()

    counts: dict[str, int] = defaultdict(int)

    for usage in usages:
        counts[usage.classification] += 1

    summary = {
        "project_root": str(PROJECT_ROOT),
        "variables_found": len(usages),
        "classification_counts": dict(sorted(counts.items())),
        "variables": [asdict(usage) for usage in usages],
        "safety": (
            "No secret values were printed or stored. "
            "No source files were modified."
        ),
    }

    (OUTPUT_DIR / "secrets_audit_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    csv_path = OUTPUT_DIR / "secrets_audit_entries.csv"

    with csv_path.open(
        "w",
        encoding="utf-8-sig",
        newline="",
    ) as file:
        writer = csv.writer(file)
        writer.writerow([
            "variable",
            "classification",
            "required_guess",
            "current_status",
            "access_methods",
            "default_values",
            "files",
            "line_numbers",
            "recommendation",
        ])

        for usage in usages:
            writer.writerow([
                usage.variable,
                usage.classification,
                usage.required_guess,
                usage.current_status,
                " | ".join(usage.access_methods),
                " | ".join(usage.default_values),
                " | ".join(usage.files),
                " | ".join(str(value) for value in usage.line_numbers),
                usage.recommendation,
            ])

    write_env_example(usages)

    print("=" * 72)
    print("ATLAS SECRETS & ENVIRONMENT AUDITOR v1.0")
    print("=" * 72)
    print(f"Project         : {PROJECT_ROOT}")
    print(f"Variables found : {len(usages)}")
    print()

    for key, value in sorted(counts.items()):
        print(f"{key:<20}: {value}")

    print()
    print("Current status:")
    print(f"SET   : {sum(1 for usage in usages if usage.current_status == 'SET')}")
    print(f"UNSET : {sum(1 for usage in usages if usage.current_status == 'UNSET')}")
    print()
    print(f"Reports: {OUTPUT_DIR}")
    print()
    print("SECRETS AUDIT COMPLETED — NO VALUES WERE EXPOSED")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
