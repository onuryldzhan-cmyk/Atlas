"""
============================================================
ATLAS SECRET CONTRACT AUDITOR & TEST VALIDATOR v1.0
============================================================

Purpose
-------
- Detect environment variables referenced through Atlas custom
  secret-binding/configuration mechanisms.
- Exclude archives, backups, reports, quarantine and generated files.
- Classify test-only and runtime integration secrets.
- Run the known infrastructure test with a process-local placeholder
  value only.

Safety
------
- Never prints secret values
- Never writes .env
- Never persists environment variables
- Never enables live trading
- No source modification
============================================================
"""

from __future__ import annotations

import ast
import csv
import json
import os
import re
import subprocess
import sys
from collections import defaultdict
from dataclasses import asdict, dataclass
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent.parent
OUTPUT_DIR = PROJECT_ROOT / "reports" / "phase4_secret_contract_validation"

EXCLUDED_EXACT = {
    ".git", ".venv", "venv", "__pycache__", ".pytest_cache",
    "reports", "_quarantine", "archive_unused_2026-07-22",
}

EXCLUDED_PREFIXES = (
    "archive", "backup", "phase1_backup", "phase2_backup",
    "phase3", "phase4", "_archive", "_backup",
)

ENV_NAME_PATTERN = re.compile(r"\b[A-Z][A-Z0-9_]{4,}\b")
SECRET_MARKERS = (
    "SECRET", "TOKEN", "PASSWORD", "API_KEY", "PRIVATE_KEY",
    "ACCESS_KEY", "SIGNING_KEY",
)


@dataclass
class SecretContract:
    variable: str
    files: list[str]
    lines: list[int]
    evidence: list[str]
    classification: str
    currently_set: bool
    recommendation: str


def normalize(path: Path) -> str:
    return str(path).replace("\\", "/")


def is_excluded(path: Path) -> bool:
    try:
        rel = path.relative_to(PROJECT_ROOT)
    except ValueError:
        return True

    for part in rel.parts:
        lower = part.lower()

        if lower in EXCLUDED_EXACT:
            return True

        if any(lower.startswith(prefix) for prefix in EXCLUDED_PREFIXES):
            return True

    return False


def classify(name: str, files: set[str]) -> tuple[str, str]:
    upper = name.upper()

    if "_TEST_" in upper or upper.endswith("_TEST_SECRET"):
        return (
            "TEST_ONLY_SECRET",
            "Inject only into the test process; never persist or reuse as a real credential.",
        )

    if upper.startswith("BINANCE_TR_"):
        return (
            "OPTIONAL_LIVE_INTEGRATION_SECRET",
            "Keep unset until the Binance TR live integration is explicitly approved.",
        )

    if upper.startswith("BINANCE_"):
        return (
            "OPTIONAL_LIVE_INTEGRATION_SECRET",
            "Keep unset for paper mode; inject only for an approved live exchange session.",
        )

    if any(marker in upper for marker in SECRET_MARKERS):
        return (
            "RUNTIME_SECRET_REVIEW",
            "Document ownership and inject through the secret manager when required.",
        )

    return (
        "CONFIGURATION_REVIEW",
        "Review whether this value belongs in configuration rather than secret storage.",
    )


def scan_contracts() -> list[SecretContract]:
    found: dict[str, dict[str, set]] = defaultdict(
        lambda: {"files": set(), "lines": set(), "evidence": set()}
    )

    for path in PROJECT_ROOT.rglob("*.py"):
        if is_excluded(path):
            continue

        try:
            text = path.read_text(encoding="utf-8", errors="replace")
            tree = ast.parse(text, filename=str(path))
        except (OSError, SyntaxError):
            continue

        rel = normalize(path.relative_to(PROJECT_ROOT))

        for node in ast.walk(tree):
            if not isinstance(node, ast.Constant) or not isinstance(node.value, str):
                continue

            value = node.value.strip()

            if not ENV_NAME_PATTERN.fullmatch(value):
                continue

            upper = value.upper()

            if not (
                upper.startswith("ATLAS_")
                or upper.startswith("BINANCE_")
                or any(marker in upper for marker in SECRET_MARKERS)
            ):
                continue

            parent_line = text.splitlines()[node.lineno - 1].strip() if node.lineno else ""
            record = found[value]
            record["files"].add(rel)
            record["lines"].add(int(node.lineno or 0))
            record["evidence"].add(parent_line[:240])

    contracts: list[SecretContract] = []

    for variable, record in sorted(found.items()):
        classification, recommendation = classify(
            variable,
            record["files"],
        )

        contracts.append(
            SecretContract(
                variable=variable,
                files=sorted(record["files"]),
                lines=sorted(record["lines"]),
                evidence=sorted(record["evidence"]),
                classification=classification,
                currently_set=os.environ.get(variable) is not None,
                recommendation=recommendation,
            )
        )

    return contracts


def run_test_with_local_secret() -> dict:
    test_file = PROJECT_ROOT / "test_atlas_infrastructure.py"

    if not test_file.exists():
        return {
            "status": "SKIPPED",
            "reason": "test_atlas_infrastructure.py not found",
            "returncode": None,
            "stdout_tail": [],
            "stderr_tail": [],
        }

    env = os.environ.copy()
    env["ATLAS_INFRASTRUCTURE_TEST_SECRET"] = (
        "atlas-test-only-placeholder-not-a-real-secret"
    )

    completed = subprocess.run(
        [sys.executable, str(test_file)],
        cwd=PROJECT_ROOT,
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=120,
    )

    return {
        "status": "PASSED" if completed.returncode == 0 else "FAILED",
        "returncode": completed.returncode,
        "stdout_tail": completed.stdout.splitlines()[-80:],
        "stderr_tail": completed.stderr.splitlines()[-80:],
        "secret_scope": "CHILD_PROCESS_ONLY",
        "secret_persisted": False,
    }


def main() -> int:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    contracts = scan_contracts()
    test_result = run_test_with_local_secret()

    counts: dict[str, int] = defaultdict(int)
    for contract in contracts:
        counts[contract.classification] += 1

    summary = {
        "project_root": str(PROJECT_ROOT),
        "contracts_found": len(contracts),
        "classification_counts": dict(sorted(counts.items())),
        "contracts": [asdict(item) for item in contracts],
        "infrastructure_test": test_result,
        "safety": {
            "secret_values_printed": False,
            "env_files_modified": False,
            "environment_persisted": False,
            "live_trading_enabled": False,
        },
    }

    (OUTPUT_DIR / "secret_contract_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    with (OUTPUT_DIR / "secret_contract_entries.csv").open(
        "w", encoding="utf-8-sig", newline=""
    ) as file:
        writer = csv.writer(file)
        writer.writerow([
            "variable", "classification", "currently_set",
            "files", "lines", "recommendation",
        ])

        for item in contracts:
            writer.writerow([
                item.variable,
                item.classification,
                item.currently_set,
                " | ".join(item.files),
                " | ".join(str(line) for line in item.lines),
                item.recommendation,
            ])

    print("=" * 72)
    print("ATLAS SECRET CONTRACT AUDITOR & TEST VALIDATOR v1.0")
    print("=" * 72)
    print(f"Project          : {PROJECT_ROOT}")
    print(f"Contracts found  : {len(contracts)}")
    print()

    for key, value in sorted(counts.items()):
        print(f"{key:<34}: {value}")

    print()
    print("Infrastructure test")
    print(f"Status           : {test_result['status']}")
    print(f"Secret scope     : {test_result.get('secret_scope', 'N/A')}")
    print(f"Secret persisted : {test_result.get('secret_persisted', False)}")
    print()
    print(f"Reports          : {OUTPUT_DIR}")
    print()

    if test_result["status"] == "FAILED":
        print("TEST FAILED — REVIEW REPORT")
        return 1

    print("PHASE 4B COMPLETED — NO SECRET WAS PERSISTED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
