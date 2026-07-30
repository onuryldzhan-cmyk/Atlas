"""
============================================================
ATLAS PHASE 6A1 — MARKET DATA SOURCE COLLECTOR v1.0
============================================================

Purpose
-------
Collect and inspect the current Atlas market-data pipeline without
importing or executing Atlas runtime modules.

Primary targets
---------------
- Market feed/provider implementations
- Market loop/orchestrator
- Candle processor
- Technical analyzer
- World analysis engine
- Intelligence loop
- Event bus integration points
- Market-related configuration files

Safety
------
- Read-only
- Does not import Atlas modules
- Does not start services
- Does not connect to exchanges
- Does not read secret values
- Does not modify production source files
============================================================
"""

from __future__ import annotations

import ast
import hashlib
import json
import shutil
import zipfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Iterable


PROJECT_ROOT = Path(__file__).resolve().parent.parent
OUTPUT_ROOT = PROJECT_ROOT / "reports" / "phase6_market_data_sources"
SOURCE_ROOT = OUTPUT_ROOT / "sources"

EXACT_TARGETS = [
    "core/market_feed.py",
    "core/market_loop.py",
    "core/candle_processor.py",
    "core/technical_analyzer.py",
    "analysis/world_analysis_engine.py",
    "core/intelligence/loop/intelligence_loop.py",
    "core/event_bus.py",
    "core/events.py",
    "config/settings.py",
    "config/config.py",
]

SEARCH_PATTERNS = [
    "*market*feed*.py",
    "*market*data*.py",
    "*candle*.py",
    "*exchange*.py",
    "*binance*.py",
    "*price*provider*.py",
    "*websocket*.py",
    "*data*validator*.py",
    "*data*normalizer*.py",
    "*market*cache*.py",
]

EXCLUDED_PARTS = {
    ".git",
    ".idea",
    ".vscode",
    "__pycache__",
    "archive",
    "archives",
    "backup",
    "backups",
    "venv",
    ".venv",
    "env",
    "site-packages",
    "node_modules",
    "reports",
}


def normalize(path: Path) -> str:
    return str(path).replace("\\", "/")


def sha256(path: Path) -> str:
    digest = hashlib.sha256()

    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)

    return digest.hexdigest()


def excluded(path: Path) -> bool:
    relative_parts = {
        part.lower()
        for part in path.relative_to(PROJECT_ROOT).parts
    }
    return bool(relative_parts & EXCLUDED_PARTS)


def discover_targets() -> list[Path]:
    discovered: dict[str, Path] = {}

    for relative in EXACT_TARGETS:
        path = PROJECT_ROOT / relative
        if path.exists() and path.is_file():
            discovered[normalize(path.relative_to(PROJECT_ROOT))] = path

    for pattern in SEARCH_PATTERNS:
        for path in PROJECT_ROOT.rglob(pattern):
            if not path.is_file() or excluded(path):
                continue

            relative = normalize(path.relative_to(PROJECT_ROOT))
            discovered.setdefault(relative, path)

    return [
        discovered[key]
        for key in sorted(discovered)
    ]


def decorator_name(node: ast.expr) -> str:
    if isinstance(node, ast.Name):
        return node.id

    if isinstance(node, ast.Attribute):
        parts = []
        current = node

        while isinstance(current, ast.Attribute):
            parts.append(current.attr)
            current = current.value

        if isinstance(current, ast.Name):
            parts.append(current.id)

        return ".".join(reversed(parts))

    if isinstance(node, ast.Call):
        return decorator_name(node.func)

    return type(node).__name__


def inspect_file(path: Path) -> dict:
    relative = normalize(path.relative_to(PROJECT_ROOT))

    try:
        source = path.read_text(
            encoding="utf-8",
            errors="replace",
        )
        tree = ast.parse(source, filename=str(path))
    except (OSError, SyntaxError) as exc:
        return {
            "file": relative,
            "status": "FAILED",
            "error": str(exc),
        }

    imports = []
    classes = []
    functions = []
    calls = set()
    string_markers = set()

    for node in ast.walk(tree):
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
                "bases": [
                    decorator_name(base)
                    for base in node.bases
                ],
                "methods": methods,
                "decorators": [
                    decorator_name(item)
                    for item in node.decorator_list
                ],
            })

        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if isinstance(
                getattr(node, "parent", None),
                ast.ClassDef,
            ):
                continue

            functions.append({
                "name": node.name,
                "line": node.lineno,
                "async": isinstance(node, ast.AsyncFunctionDef),
            })

        elif isinstance(node, ast.Call):
            calls.add(decorator_name(node.func))

        elif isinstance(node, ast.Constant) and isinstance(node.value, str):
            lower = node.value.lower()
            for marker in (
                "binance",
                "websocket",
                "ticker",
                "kline",
                "candle",
                "market",
                "price",
                "event",
                "reconnect",
                "retry",
                "cache",
                "health",
            ):
                if marker in lower:
                    string_markers.add(marker)

    lower_source = source.lower()

    return {
        "file": relative,
        "status": "OK",
        "line_count": len(source.splitlines()),
        "sha256": sha256(path),
        "imports": sorted(set(imports)),
        "classes": classes,
        "functions": functions,
        "signals": {
            "logging_detected": any(
                token in lower_source
                for token in (
                    "import logging",
                    "logging.getlogger",
                    "logger.",
                    "structlog",
                )
            ),
            "threading_detected": any(
                token in lower_source
                for token in (
                    "threading",
                    "thread(",
                    "rlock(",
                    "lock(",
                )
            ),
            "async_detected": any(
                isinstance(
                    node,
                    (ast.AsyncFunctionDef, ast.Await),
                )
                for node in ast.walk(tree)
            ),
            "requests_detected": (
                "requests" in imports
                or "requests.get" in calls
                or "requests.post" in calls
            ),
            "websocket_detected": (
                any("websocket" in item.lower() for item in imports)
                or any("websocket" in item.lower() for item in calls)
                or "websocket" in string_markers
            ),
            "exchange_reference_detected": any(
                keyword in lower_source
                for keyword in (
                    "binance",
                    "exchange",
                    "client.get_",
                    "futures_",
                )
            ),
            "event_bus_reference_detected": any(
                keyword in lower_source
                for keyword in (
                    "event_bus",
                    "eventbus",
                    "publish(",
                    "emit(",
                )
            ),
            "retry_or_reconnect_detected": any(
                keyword in lower_source
                for keyword in (
                    "retry",
                    "reconnect",
                    "backoff",
                    "max_attempt",
                )
            ),
            "cache_detected": "cache" in lower_source,
            "health_detected": "health" in lower_source,
            "timestamp_detected": any(
                keyword in lower_source
                for keyword in (
                    "timestamp",
                    "datetime",
                    "time.time",
                )
            ),
        },
        "interesting_calls": sorted(
            call
            for call in calls
            if any(
                marker in call.lower()
                for marker in (
                    "request",
                    "client",
                    "ticker",
                    "kline",
                    "candle",
                    "publish",
                    "emit",
                    "sleep",
                    "thread",
                    "lock",
                    "connect",
                    "close",
                )
            )
        ),
        "string_markers": sorted(string_markers),
    }


def write_architecture_summary(
    manifest: dict,
    output: Path,
) -> None:
    lines = [
        "=" * 78,
        "ATLAS PHASE 6A1 — MARKET DATA SOURCE SUMMARY",
        "=" * 78,
        "",
        f"Generated UTC : {manifest['generated_utc']}",
        f"Collected     : {manifest['collected_files']}",
        f"Missing exact : {len(manifest['missing_exact_targets'])}",
        "",
        "FILES",
        "-" * 78,
    ]

    for item in manifest["files"]:
        status = item.get("status", "UNKNOWN")
        lines.append(
            f"[{status}] {item['file']}"
        )

        if status != "OK":
            lines.append(f"  Error: {item.get('error', '')}")
            continue

        lines.append(
            f"  Lines: {item['line_count']} | "
            f"Classes: {len(item['classes'])} | "
            f"Imports: {len(item['imports'])}"
        )

        signals = [
            key.replace("_detected", "")
            for key, value in item["signals"].items()
            if value
        ]

        if signals:
            lines.append(
                "  Signals: " + ", ".join(signals)
            )

    if manifest["missing_exact_targets"]:
        lines.extend([
            "",
            "MISSING EXACT TARGETS",
            "-" * 78,
            *[
                f"- {item}"
                for item in manifest["missing_exact_targets"]
            ],
        ])

    output.write_text(
        "\n".join(lines) + "\n",
        encoding="utf-8",
    )


def main() -> int:
    OUTPUT_ROOT.mkdir(parents=True, exist_ok=True)

    if SOURCE_ROOT.exists():
        shutil.rmtree(SOURCE_ROOT)

    SOURCE_ROOT.mkdir(parents=True, exist_ok=True)

    targets = discover_targets()

    missing_exact = [
        relative
        for relative in EXACT_TARGETS
        if not (PROJECT_ROOT / relative).exists()
    ]

    manifest = {
        "phase": "6A1",
        "generated_utc": datetime.now(UTC).isoformat(),
        "project_root": str(PROJECT_ROOT),
        "exact_targets": EXACT_TARGETS,
        "search_patterns": SEARCH_PATTERNS,
        "missing_exact_targets": missing_exact,
        "files": [],
        "safety": {
            "source_files_modified": False,
            "atlas_modules_imported": False,
            "services_started": False,
            "exchange_connections_opened": False,
            "secret_values_read": False,
        },
    }

    for source in targets:
        relative = source.relative_to(PROJECT_ROOT)
        destination = SOURCE_ROOT / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)

        manifest["files"].append(
            inspect_file(source)
        )

    manifest["collected_files"] = sum(
        item.get("status") == "OK"
        for item in manifest["files"]
    )

    manifest_path = OUTPUT_ROOT / "market_data_source_manifest.json"
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    summary_path = OUTPUT_ROOT / "market_data_source_summary.txt"
    write_architecture_summary(
        manifest,
        summary_path,
    )

    package_path = (
        OUTPUT_ROOT
        / "Atlas_Phase6A1_Market_Data_Sources.zip"
    )

    with zipfile.ZipFile(
        package_path,
        "w",
        zipfile.ZIP_DEFLATED,
    ) as archive:
        archive.write(
            manifest_path,
            manifest_path.relative_to(OUTPUT_ROOT),
        )
        archive.write(
            summary_path,
            summary_path.relative_to(OUTPUT_ROOT),
        )

        for file in SOURCE_ROOT.rglob("*"):
            if file.is_file():
                archive.write(
                    file,
                    file.relative_to(OUTPUT_ROOT),
                )

    print("=" * 72)
    print("ATLAS PHASE 6A1 - MARKET DATA SOURCE COLLECTION")
    print("=" * 72)
    print(f"Collected files : {manifest['collected_files']}")
    print(f"Missing exact   : {len(missing_exact)}")

    if missing_exact:
        print()
        print("Missing exact targets:")
        for relative in missing_exact:
            print(f"  - {relative}")

    print()
    print(f"Package         : {package_path}")
    print(f"Manifest        : {manifest_path}")
    print(f"Summary         : {summary_path}")
    print()
    print("PHASE 6A1 COMPLETED - READ-ONLY COLLECTION")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
