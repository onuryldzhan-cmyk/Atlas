"""
============================================================
ATLAS PHASE 5C1 — OBSERVABILITY SOURCE COLLECTOR v1.0
============================================================

Collects only the seven files identified by Phase 5B so they can
be reviewed and patched safely.

Safety:
- Read-only
- Does not import Atlas modules
- Does not modify source files
- Does not start services
- Does not connect to exchanges
- Does not read environment secrets
============================================================
"""

from __future__ import annotations

import ast
import json
import shutil
import zipfile
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent.parent
OUTPUT_DIR = PROJECT_ROOT / "reports" / "phase5_observability_sources"
SOURCE_DIR = OUTPUT_DIR / "sources"

TARGETS = [
    "atlas_os/observability/metrics.py",
    "core/brain_analyzer.py",
    "core/code_cleanup_analyzer.py",
    "core/database.py",
    "core/execution_contracts.py",
    "core/intelligence/loop/intelligence_loop.py",
    "core/project_snapshot.py",
]


def normalize(path: Path) -> str:
    return str(path).replace("\\", "/")


def inspect_file(path: Path) -> dict:
    relative = normalize(path.relative_to(PROJECT_ROOT))

    try:
        source = path.read_text(encoding="utf-8", errors="replace")
        tree = ast.parse(source, filename=str(path))
    except (OSError, SyntaxError) as exc:
        return {
            "file": relative,
            "status": "FAILED",
            "error": str(exc),
        }

    imports = []
    classes = []

    for node in tree.body:
        if isinstance(node, ast.Import):
            imports.extend(alias.name for alias in node.names)

        elif isinstance(node, ast.ImportFrom):
            module = node.module or ""
            imports.extend(
                f"{module}.{alias.name}" if module else alias.name
                for alias in node.names
            )

        elif isinstance(node, ast.ClassDef):
            methods = [
                child.name
                for child in node.body
                if isinstance(
                    child,
                    (ast.FunctionDef, ast.AsyncFunctionDef),
                )
            ]

            classes.append({
                "name": node.name,
                "line": node.lineno,
                "methods": methods,
            })

    lower = source.lower()

    return {
        "file": relative,
        "status": "OK",
        "line_count": len(source.splitlines()),
        "imports": sorted(set(imports)),
        "classes": classes,
        "logging_detected": any(
            token in lower
            for token in (
                "import logging",
                "from logging",
                "logging.getlogger",
                "logger.",
                "structlog",
            )
        ),
    }


def main() -> int:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    if SOURCE_DIR.exists():
        shutil.rmtree(SOURCE_DIR)

    SOURCE_DIR.mkdir(parents=True, exist_ok=True)

    manifest = {
        "project_root": str(PROJECT_ROOT),
        "targets": [],
        "safety": {
            "source_files_modified": False,
            "atlas_modules_imported": False,
            "services_started": False,
            "exchange_connections_opened": False,
            "secret_values_read": False,
        },
    }

    missing = []

    for relative in TARGETS:
        source_path = PROJECT_ROOT / Path(relative)

        if not source_path.exists():
            missing.append(relative)
            manifest["targets"].append({
                "file": relative,
                "status": "MISSING",
            })
            continue

        destination = SOURCE_DIR / Path(relative)
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source_path, destination)

        manifest["targets"].append(
            inspect_file(source_path)
        )

    manifest["missing_files"] = missing
    manifest["collected_files"] = sum(
        item.get("status") == "OK"
        for item in manifest["targets"]
    )

    manifest_path = OUTPUT_DIR / "source_manifest.json"
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    package_path = OUTPUT_DIR / "Atlas_Phase5C1_Observability_Sources.zip"

    with zipfile.ZipFile(
        package_path,
        "w",
        zipfile.ZIP_DEFLATED,
    ) as archive:
        archive.write(
            manifest_path,
            manifest_path.relative_to(OUTPUT_DIR),
        )

        for file in SOURCE_DIR.rglob("*.py"):
            archive.write(
                file,
                file.relative_to(OUTPUT_DIR),
            )

    print("=" * 72)
    print("ATLAS PHASE 5C1 - OBSERVABILITY SOURCE COLLECTION")
    print("=" * 72)
    print(f"Target files    : {len(TARGETS)}")
    print(f"Collected files : {manifest['collected_files']}")
    print(f"Missing files   : {len(missing)}")
    print()
    print(f"Package         : {package_path}")
    print()
    print("PHASE 5C1 COMPLETED - READ-ONLY COLLECTION")

    return 1 if missing else 0


if __name__ == "__main__":
    raise SystemExit(main())
