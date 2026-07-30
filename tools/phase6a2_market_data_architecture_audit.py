"""
============================================================
ATLAS PHASE 6A2 — MARKET DATA ARCHITECTURE AUDIT v1.0
============================================================

Read-only audit for:
- active market-data composition
- legacy provider usage
- duplicate feed/provider paths
- direct exchange access
- canonical MarketFeedService readiness
- application migration prerequisites

Does not import Atlas modules or connect to exchanges.
============================================================
"""

from __future__ import annotations

import ast
import json
import re
from collections import defaultdict
from datetime import UTC, datetime
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
REPORT_DIR = ROOT / "reports" / "phase6_market_data_architecture"

EXCLUDED = {
    ".git", ".idea", ".vscode", "__pycache__", "venv", ".venv",
    "env", "site-packages", "node_modules", "reports", "backups",
    "archive", "archives",
}

CANONICAL_MODULES = {
    "atlas_finance.market_data.market_feed_service": "MarketFeedService",
    "atlas_finance.market_data.binance_public_provider": "BinancePublicDataProvider",
}

LEGACY_MODULES = {
    "exchange.market_feed": "MarketFeed",
    "exchange.exchange_manager": "ExchangeManager",
    "data.binance_provider": "BinanceProvider",
    "data.candle_manager": "CandleManager",
    "core.data.price_provider": "PriceProvider",
    "core.market_feed": "MarketFeed",
}

COMPOSITION_CANDIDATES = [
    "main.py",
    "core/application.py",
    "core/runtime.py",
    "atlas_os/kernel/kernel.py",
]

DIRECT_EXCHANGE_MARKERS = (
    "requests.get(",
    "requests.post(",
    "client.get_",
    "get_klines(",
    "get_ticker(",
    "futures_",
    "api.binance.com",
)


def normalize(path: Path) -> str:
    return str(path).replace("\\", "/")


def is_excluded(path: Path) -> bool:
    parts = {
        part.lower()
        for part in path.relative_to(ROOT).parts
    }
    return bool(parts & EXCLUDED)


def python_files() -> list[Path]:
    return [
        path
        for path in ROOT.rglob("*.py")
        if path.is_file() and not is_excluded(path)
    ]


def imports_of(tree: ast.Module) -> list[tuple[str, str | None, int]]:
    result = []

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                result.append((alias.name, alias.asname, node.lineno))

        elif isinstance(node, ast.ImportFrom):
            module = node.module or ""
            for alias in node.names:
                result.append(
                    (
                        f"{module}.{alias.name}" if module else alias.name,
                        alias.asname,
                        node.lineno,
                    )
                )

    return result


def classes_of(tree: ast.Module) -> list[dict]:
    classes = []

    for node in tree.body:
        if isinstance(node, ast.ClassDef):
            classes.append({
                "name": node.name,
                "line": node.lineno,
                "methods": [
                    child.name
                    for child in node.body
                    if isinstance(
                        child,
                        (ast.FunctionDef, ast.AsyncFunctionDef),
                    )
                ],
            })

    return classes


def scan_file(path: Path) -> dict:
    relative = normalize(path.relative_to(ROOT))

    try:
        text = path.read_text(encoding="utf-8", errors="replace")
        tree = ast.parse(text, filename=str(path))
    except (OSError, SyntaxError) as exc:
        return {
            "file": relative,
            "status": "FAILED",
            "error": str(exc),
        }

    imports = imports_of(tree)
    imported_names = [item[0] for item in imports]

    legacy_refs = []
    canonical_refs = []

    for module, class_name in LEGACY_MODULES.items():
        if any(
            imported == module
            or imported == f"{module}.{class_name}"
            or imported.startswith(module + ".")
            for imported in imported_names
        ):
            legacy_refs.append({
                "module": module,
                "class": class_name,
                "lines": sorted({
                    line
                    for imported, _, line in imports
                    if imported == module
                    or imported == f"{module}.{class_name}"
                    or imported.startswith(module + ".")
                }),
            })

    for module, class_name in CANONICAL_MODULES.items():
        if any(
            imported == module
            or imported == f"{module}.{class_name}"
            or imported.startswith(module + ".")
            for imported in imported_names
        ):
            canonical_refs.append({
                "module": module,
                "class": class_name,
                "lines": sorted({
                    line
                    for imported, _, line in imports
                    if imported == module
                    or imported == f"{module}.{class_name}"
                    or imported.startswith(module + ".")
                }),
            })

    direct_markers = [
        marker
        for marker in DIRECT_EXCHANGE_MARKERS
        if marker.lower() in text.lower()
    ]

    return {
        "file": relative,
        "status": "OK",
        "line_count": len(text.splitlines()),
        "classes": classes_of(tree),
        "legacy_references": legacy_refs,
        "canonical_references": canonical_refs,
        "direct_exchange_markers": direct_markers,
        "event_bus_reference": any(
            marker in text
            for marker in ("event_bus", "EventBus", "publish_event", ".publish(")
        ),
        "health_reference": "health" in text.lower(),
        "logging_reference": (
            "logging.getLogger" in text
            or "logger." in text
        ),
    }


def find_class_definitions(files: list[dict]) -> dict[str, list[dict]]:
    names = defaultdict(list)

    for item in files:
        if item.get("status") != "OK":
            continue

        for cls in item["classes"]:
            if cls["name"] in {
                "MarketFeed",
                "MarketFeedService",
                "ExchangeManager",
                "BinanceProvider",
                "BinancePublicDataProvider",
                "CandleManager",
                "PriceProvider",
            }:
                names[cls["name"]].append({
                    "file": item["file"],
                    "line": cls["line"],
                    "methods": cls["methods"],
                })

    return dict(names)


def severity_findings(
    scanned: list[dict],
    definitions: dict[str, list[dict]],
) -> list[dict]:
    findings = []

    application = next(
        (
            item for item in scanned
            if item.get("file") == "core/application.py"
        ),
        None,
    )

    if application:
        legacy = {
            ref["module"]
            for ref in application.get("legacy_references", [])
        }
        canonical = {
            ref["module"]
            for ref in application.get("canonical_references", [])
        }

        if "exchange.market_feed" in legacy and not canonical:
            findings.append({
                "severity": "HIGH",
                "code": "LEGACY_COMPOSITION_ROOT",
                "title": "Application still constructs legacy MarketFeed",
                "evidence": "core/application.py imports exchange.market_feed.MarketFeed",
                "recommendation": (
                    "Introduce a compatibility adapter or migrate the composition "
                    "root to AtlasFinance MarketFeedService after contract tests."
                ),
            })

    core_feed = ROOT / "core" / "market_feed.py"
    if core_feed.exists() and core_feed.stat().st_size == 0:
        findings.append({
            "severity": "MEDIUM",
            "code": "EMPTY_CORE_MARKET_FEED",
            "title": "core/market_feed.py is empty",
            "evidence": "The expected core feed module has zero bytes.",
            "recommendation": (
                "Keep it unused, remove references, or convert it into a deliberate "
                "compatibility export only after import analysis."
            ),
        })

    feed_defs = (
        definitions.get("MarketFeed", [])
        + definitions.get("MarketFeedService", [])
    )

    if len(feed_defs) >= 3:
        findings.append({
            "severity": "MEDIUM",
            "code": "MULTIPLE_FEED_IMPLEMENTATIONS",
            "title": "Multiple market feed implementations exist",
            "evidence": [item["file"] for item in feed_defs],
            "recommendation": (
                "Select MarketFeedService as canonical and phase out legacy feed "
                "classes through adapters and deprecation tests."
            ),
        })

    direct_active = [
        item
        for item in scanned
        if item.get("status") == "OK"
        and item.get("direct_exchange_markers")
        and not item["file"].startswith("atlas_finance/market_data/")
        and not item["file"].startswith("exchange/adapters/")
        and not item["file"].startswith("tools/")
        and not item["file"].startswith("test")
    ]

    if direct_active:
        findings.append({
            "severity": "MEDIUM",
            "code": "DIRECT_EXCHANGE_ACCESS",
            "title": "Active modules contain direct exchange access markers",
            "evidence": [
                {
                    "file": item["file"],
                    "markers": item["direct_exchange_markers"],
                }
                for item in direct_active
            ],
            "recommendation": (
                "Restrict external market requests to provider/adapter modules."
            ),
        })

    canonical_defs = definitions.get("MarketFeedService", [])
    if canonical_defs:
        methods = set(canonical_defs[0].get("methods", []))
        required = {
            "_on_start",
            "_on_stop",
            "get_price",
            "get_candles",
            "statistics",
            "market_feed_snapshot",
            "_health_details",
        }
        missing = sorted(required - methods)

        if missing:
            findings.append({
                "severity": "HIGH",
                "code": "CANONICAL_SERVICE_CONTRACT_GAP",
                "title": "MarketFeedService is missing required production methods",
                "evidence": missing,
                "recommendation": "Complete canonical service before migration.",
            })
        else:
            findings.append({
                "severity": "INFO",
                "code": "CANONICAL_SERVICE_READY",
                "title": "MarketFeedService exposes production service capabilities",
                "evidence": sorted(required),
                "recommendation": (
                    "Proceed with adapter and composition migration tests."
                ),
            })

    return findings


def main() -> int:
    REPORT_DIR.mkdir(parents=True, exist_ok=True)

    scanned = [
        scan_file(path)
        for path in python_files()
    ]

    definitions = find_class_definitions(scanned)
    findings = severity_findings(scanned, definitions)

    usage = {
        "legacy": [
            item
            for item in scanned
            if item.get("legacy_references")
        ],
        "canonical": [
            item
            for item in scanned
            if item.get("canonical_references")
        ],
    }

    report = {
        "phase": "6A2",
        "generated_utc": datetime.now(UTC).isoformat(),
        "project_root": str(ROOT),
        "summary": {
            "python_files_scanned": len(scanned),
            "parse_failures": sum(
                item.get("status") == "FAILED"
                for item in scanned
            ),
            "high_findings": sum(
                item["severity"] == "HIGH"
                for item in findings
            ),
            "medium_findings": sum(
                item["severity"] == "MEDIUM"
                for item in findings
            ),
            "info_findings": sum(
                item["severity"] == "INFO"
                for item in findings
            ),
            "legacy_usage_files": len(usage["legacy"]),
            "canonical_usage_files": len(usage["canonical"]),
        },
        "class_definitions": definitions,
        "findings": findings,
        "usage": usage,
        "composition_candidates": [
            item
            for item in scanned
            if item.get("file") in COMPOSITION_CANDIDATES
        ],
        "safety": {
            "source_files_modified": False,
            "atlas_modules_imported": False,
            "exchange_connections_opened": False,
            "secret_values_read": False,
        },
    }

    json_path = REPORT_DIR / "phase6a2_market_data_architecture.json"
    json_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    lines = [
        "=" * 78,
        "ATLAS PHASE 6A2 — MARKET DATA ARCHITECTURE AUDIT",
        "=" * 78,
        "",
        f"Python files scanned : {report['summary']['python_files_scanned']}",
        f"Parse failures       : {report['summary']['parse_failures']}",
        f"HIGH findings        : {report['summary']['high_findings']}",
        f"MEDIUM findings      : {report['summary']['medium_findings']}",
        f"Legacy usage files   : {report['summary']['legacy_usage_files']}",
        f"Canonical usage files: {report['summary']['canonical_usage_files']}",
        "",
        "FINDINGS",
        "-" * 78,
    ]

    for finding in findings:
        lines.append(
            f"[{finding['severity']}] {finding['code']} — {finding['title']}"
        )
        lines.append(f"  Evidence: {finding['evidence']}")
        lines.append(f"  Action  : {finding['recommendation']}")
        lines.append("")

    text_path = REPORT_DIR / "phase6a2_market_data_architecture.txt"
    text_path.write_text(
        "\n".join(lines),
        encoding="utf-8",
    )

    print("=" * 72)
    print("ATLAS PHASE 6A2 - MARKET DATA ARCHITECTURE AUDIT")
    print("=" * 72)
    print(f"Python files scanned : {report['summary']['python_files_scanned']}")
    print(f"Parse failures       : {report['summary']['parse_failures']}")
    print(f"HIGH findings        : {report['summary']['high_findings']}")
    print(f"MEDIUM findings      : {report['summary']['medium_findings']}")
    print(f"Legacy usage files   : {report['summary']['legacy_usage_files']}")
    print(f"Canonical usage files: {report['summary']['canonical_usage_files']}")
    print()

    for finding in findings:
        print(
            f"[{finding['severity']}] "
            f"{finding['code']} -> {finding['title']}"
        )

    print()
    print(f"JSON report : {json_path}")
    print(f"Text report : {text_path}")
    print()
    print("PHASE 6A2 COMPLETED - READ-ONLY AUDIT")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
