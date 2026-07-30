"""
============================================================
ATLAS PHASE 6A2.1 — MARKET DATA MIGRATION READINESS v1.0
============================================================

Purpose
-------
Produce a precise, read-only migration inventory before changing
the Atlas market-data composition root.

Checks
------
- Exact legacy MarketFeed import/instantiation locations
- Exact canonical MarketFeedService usage locations
- Direct exchange/API access locations with line numbers
- Syntax/parse failures classified by active vs excluded-like paths
- Constructor and public-method contracts of legacy and canonical feeds
- core/application.py wiring and method expectations
- Candidate compatibility gaps

Safety
------
- Read-only
- Does not import Atlas modules
- Does not connect to exchanges
- Does not modify source files
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
REPORT_DIR = ROOT / "reports" / "phase6_market_data_migration_readiness"

HARD_EXCLUDED = {
    ".git", ".idea", ".vscode", "__pycache__", "venv", ".venv",
    "env", "site-packages", "node_modules", "reports", "backups",
}

SOFT_ARCHIVE_MARKERS = {
    "archive", "archives", "backup", "backups", "old", "legacy",
    "deprecated", "unused", "trash", "temp", "tmp",
}

TARGET_MODULES = {
    "exchange.market_feed": "MarketFeed",
    "atlas_finance.market_data.market_feed_service": "MarketFeedService",
    "atlas_finance.market_data.binance_public_provider": "BinancePublicDataProvider",
    "exchange.exchange_manager": "ExchangeManager",
    "data.binance_provider": "BinanceProvider",
    "data.candle_manager": "CandleManager",
    "core.data.price_provider": "PriceProvider",
}

DIRECT_MARKERS = (
    "requests.get",
    "requests.post",
    "httpx.get",
    "httpx.post",
    "urllib.request",
    "get_klines",
    "get_ticker",
    "get_symbol_ticker",
    "futures_",
    "api.binance.com",
    "api.binance.us",
    "api.binance.me",
)

KEY_FILES = {
    "core/application.py",
    "exchange/market_feed.py",
    "atlas_finance/market_data/market_feed_service.py",
    "atlas_finance/market_data/binance_public_provider.py",
    "core/market_loop.py",
    "core/candle_processor.py",
}


def norm(path: Path) -> str:
    return str(path).replace("\\", "/")


def hard_excluded(path: Path) -> bool:
    parts = {part.lower() for part in path.relative_to(ROOT).parts}
    return bool(parts & HARD_EXCLUDED)


def soft_archived(path: Path) -> bool:
    parts = {part.lower() for part in path.relative_to(ROOT).parts}
    return bool(parts & SOFT_ARCHIVE_MARKERS)


def dotted_name(node: ast.AST | None) -> str:
    if node is None:
        return ""

    if isinstance(node, ast.Name):
        return node.id

    if isinstance(node, ast.Attribute):
        base = dotted_name(node.value)
        return f"{base}.{node.attr}" if base else node.attr

    if isinstance(node, ast.Call):
        return dotted_name(node.func)

    if isinstance(node, ast.Subscript):
        return dotted_name(node.value)

    return type(node).__name__


def signature_of(node: ast.FunctionDef | ast.AsyncFunctionDef) -> dict:
    args = node.args
    positional = [
        arg.arg
        for arg in [*args.posonlyargs, *args.args]
    ]
    defaults_offset = len(positional) - len(args.defaults)

    parameters = []
    for index, name in enumerate(positional):
        default = None
        if index >= defaults_offset:
            default_node = args.defaults[index - defaults_offset]
            try:
                default = ast.unparse(default_node)
            except Exception:
                default = "<default>"

        parameters.append({
            "name": name,
            "default": default,
        })

    if args.vararg:
        parameters.append({
            "name": f"*{args.vararg.arg}",
            "default": None,
        })

    for arg, default_node in zip(args.kwonlyargs, args.kw_defaults):
        default = None
        if default_node is not None:
            try:
                default = ast.unparse(default_node)
            except Exception:
                default = "<default>"

        parameters.append({
            "name": arg.arg,
            "default": default,
        })

    if args.kwarg:
        parameters.append({
            "name": f"**{args.kwarg.arg}",
            "default": None,
        })

    return {
        "name": node.name,
        "line": node.lineno,
        "async": isinstance(node, ast.AsyncFunctionDef),
        "parameters": parameters,
    }


def import_records(tree: ast.Module) -> list[dict]:
    records = []

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                records.append({
                    "module": alias.name,
                    "symbol": None,
                    "local_name": alias.asname or alias.name.split(".")[0],
                    "line": node.lineno,
                })

        elif isinstance(node, ast.ImportFrom):
            module = node.module or ""
            for alias in node.names:
                records.append({
                    "module": module,
                    "symbol": alias.name,
                    "local_name": alias.asname or alias.name,
                    "line": node.lineno,
                })

    return records


def class_records(tree: ast.Module) -> list[dict]:
    result = []

    for node in tree.body:
        if not isinstance(node, ast.ClassDef):
            continue

        methods = [
            signature_of(child)
            for child in node.body
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef))
        ]

        result.append({
            "name": node.name,
            "line": node.lineno,
            "bases": [dotted_name(base) for base in node.bases],
            "methods": methods,
        })

    return result


def source_lines(path: Path) -> list[str]:
    return path.read_text(
        encoding="utf-8",
        errors="replace",
    ).splitlines()


def scan(path: Path) -> dict:
    relative = norm(path.relative_to(ROOT))
    lines = source_lines(path)
    source = "\n".join(lines)

    try:
        tree = ast.parse(source, filename=str(path))
    except SyntaxError as exc:
        context = ""
        if exc.lineno and 1 <= exc.lineno <= len(lines):
            context = lines[exc.lineno - 1].strip()

        return {
            "file": relative,
            "status": "PARSE_FAILED",
            "soft_archived": soft_archived(path),
            "line": exc.lineno,
            "offset": exc.offset,
            "message": exc.msg,
            "context": context,
        }

    imports = import_records(tree)
    classes = class_records(tree)

    target_imports = []
    local_target_names = {}

    for record in imports:
        module = record["module"]
        symbol = record["symbol"]

        for target_module, target_class in TARGET_MODULES.items():
            match = (
                module == target_module
                and (symbol is None or symbol == target_class)
            )

            if match:
                target_imports.append({
                    **record,
                    "target_module": target_module,
                    "target_class": target_class,
                })
                local_target_names[
                    record["local_name"]
                ] = {
                    "module": target_module,
                    "class": target_class,
                }

    instantiations = []
    method_calls = []
    direct_access = []

    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue

        called = dotted_name(node.func)
        root_name = called.split(".")[0] if called else ""

        if root_name in local_target_names:
            target = local_target_names[root_name]

            if called == root_name:
                instantiations.append({
                    "line": node.lineno,
                    "called": called,
                    "target_module": target["module"],
                    "target_class": target["class"],
                    "args": [
                        ast.unparse(arg)
                        for arg in node.args
                    ],
                    "keywords": {
                        keyword.arg or "**":
                        ast.unparse(keyword.value)
                        for keyword in node.keywords
                    },
                })
            else:
                method_calls.append({
                    "line": node.lineno,
                    "called": called,
                    "target_module": target["module"],
                    "target_class": target["class"],
                })

        lower_called = called.lower()
        matched = [
            marker
            for marker in DIRECT_MARKERS
            if marker.lower() in lower_called
        ]

        if matched:
            direct_access.append({
                "line": node.lineno,
                "called": called,
                "markers": matched,
            })

    for line_number, line in enumerate(lines, start=1):
        lower = line.lower()

        for marker in DIRECT_MARKERS:
            if marker.lower() in lower and not any(
                item["line"] == line_number
                and marker in item["markers"]
                for item in direct_access
            ):
                direct_access.append({
                    "line": line_number,
                    "called": line.strip()[:240],
                    "markers": [marker],
                })

    self_calls = defaultdict(set)

    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            name = dotted_name(node.func)
            if name.startswith("self."):
                self_calls[name.split(".", 1)[1]].add(node.lineno)

    return {
        "file": relative,
        "status": "OK",
        "soft_archived": soft_archived(path),
        "line_count": len(lines),
        "target_imports": target_imports,
        "instantiations": instantiations,
        "method_calls": method_calls,
        "direct_exchange_access": sorted(
            direct_access,
            key=lambda item: item["line"],
        ),
        "classes": classes,
        "self_method_calls": {
            key: sorted(value)
            for key, value in sorted(self_calls.items())
        },
    }


def contract_for(scanned: list[dict], file_name: str, class_name: str) -> dict | None:
    item = next(
        (
            entry for entry in scanned
            if entry.get("file") == file_name
            and entry.get("status") == "OK"
        ),
        None,
    )

    if not item:
        return None

    cls = next(
        (
            entry for entry in item["classes"]
            if entry["name"] == class_name
        ),
        None,
    )

    if not cls:
        return None

    return {
        "file": file_name,
        "class": class_name,
        "bases": cls["bases"],
        "constructor": next(
            (
                method for method in cls["methods"]
                if method["name"] == "__init__"
            ),
            None,
        ),
        "public_methods": [
            method
            for method in cls["methods"]
            if not method["name"].startswith("_")
        ],
        "lifecycle_methods": [
            method
            for method in cls["methods"]
            if method["name"] in {
                "start", "stop", "_on_start", "_on_stop",
                "health", "_health_details", "statistics",
                "snapshot", "market_feed_snapshot",
            }
        ],
    }


def migration_gap_analysis(
    legacy: dict | None,
    canonical: dict | None,
    application: dict | None,
) -> list[dict]:
    findings = []

    if not legacy:
        findings.append({
            "severity": "HIGH",
            "code": "LEGACY_CONTRACT_NOT_FOUND",
            "message": "Could not inspect exchange.market_feed.MarketFeed.",
        })

    if not canonical:
        findings.append({
            "severity": "HIGH",
            "code": "CANONICAL_CONTRACT_NOT_FOUND",
            "message": "Could not inspect MarketFeedService.",
        })

    if not legacy or not canonical:
        return findings

    legacy_methods = {
        item["name"]
        for item in legacy["public_methods"]
    }
    canonical_methods = {
        item["name"]
        for item in canonical["public_methods"]
    }

    missing_in_canonical = sorted(
        legacy_methods - canonical_methods
    )

    if missing_in_canonical:
        findings.append({
            "severity": "HIGH",
            "code": "PUBLIC_METHOD_COMPATIBILITY_GAP",
            "message": (
                "Canonical service does not expose every public legacy method."
            ),
            "methods": missing_in_canonical,
        })
    else:
        findings.append({
            "severity": "INFO",
            "code": "PUBLIC_METHODS_COMPATIBLE",
            "message": (
                "Canonical service covers all public legacy method names."
            ),
        })

    if application:
        app_calls = {
            call["called"].split(".")[-1]
            for call in application.get("method_calls", [])
            if call.get("target_class") == "MarketFeed"
        }

        missing_app_calls = sorted(
            app_calls - canonical_methods
        )

        if missing_app_calls:
            findings.append({
                "severity": "HIGH",
                "code": "APPLICATION_CALL_COMPATIBILITY_GAP",
                "message": (
                    "core/application.py calls legacy methods unavailable "
                    "on MarketFeedService."
                ),
                "methods": missing_app_calls,
            })
        else:
            findings.append({
                "severity": "INFO",
                "code": "APPLICATION_CALLS_COMPATIBLE",
                "message": (
                    "Detected application calls are available on canonical service."
                ),
            })

    findings.append({
        "severity": "INFO",
        "code": "MIGRATION_STRATEGY",
        "message": (
            "Prefer an explicit compatibility adapter and contract tests before "
            "changing core/application.py."
        ),
    })

    return findings


def main() -> int:
    REPORT_DIR.mkdir(parents=True, exist_ok=True)

    paths = [
        path
        for path in ROOT.rglob("*.py")
        if path.is_file() and not hard_excluded(path)
    ]

    scanned = [
        scan(path)
        for path in sorted(paths)
    ]

    parse_failures = [
        item
        for item in scanned
        if item["status"] == "PARSE_FAILED"
    ]

    active_parse_failures = [
        item
        for item in parse_failures
        if not item["soft_archived"]
    ]

    archived_parse_failures = [
        item
        for item in parse_failures
        if item["soft_archived"]
    ]

    legacy_usage = [
        item
        for item in scanned
        if item.get("status") == "OK"
        and any(
            entry["target_module"] == "exchange.market_feed"
            for entry in item["target_imports"]
        )
    ]

    canonical_usage = [
        item
        for item in scanned
        if item.get("status") == "OK"
        and any(
            entry["target_module"] ==
            "atlas_finance.market_data.market_feed_service"
            for entry in item["target_imports"]
        )
    ]

    direct_access = [
        {
            "file": item["file"],
            "soft_archived": item["soft_archived"],
            "locations": item["direct_exchange_access"],
        }
        for item in scanned
        if item.get("status") == "OK"
        and item["direct_exchange_access"]
    ]

    legacy_contract = contract_for(
        scanned,
        "exchange/market_feed.py",
        "MarketFeed",
    )
    canonical_contract = contract_for(
        scanned,
        "atlas_finance/market_data/market_feed_service.py",
        "MarketFeedService",
    )
    provider_contract = contract_for(
        scanned,
        "atlas_finance/market_data/binance_public_provider.py",
        "BinancePublicDataProvider",
    )

    application = next(
        (
            item for item in scanned
            if item.get("file") == "core/application.py"
            and item.get("status") == "OK"
        ),
        None,
    )

    findings = migration_gap_analysis(
        legacy_contract,
        canonical_contract,
        application,
    )

    report = {
        "phase": "6A2.1",
        "generated_utc": datetime.now(UTC).isoformat(),
        "summary": {
            "python_files_scanned": len(scanned),
            "parse_failures_total": len(parse_failures),
            "parse_failures_active": len(active_parse_failures),
            "parse_failures_archived_like": len(archived_parse_failures),
            "legacy_usage_files": len(legacy_usage),
            "canonical_usage_files": len(canonical_usage),
            "direct_access_files": len(direct_access),
            "high_findings": sum(
                item["severity"] == "HIGH"
                for item in findings
            ),
        },
        "contracts": {
            "legacy_market_feed": legacy_contract,
            "canonical_market_feed_service": canonical_contract,
            "canonical_provider": provider_contract,
        },
        "core_application": application,
        "legacy_usage": legacy_usage,
        "canonical_usage": canonical_usage,
        "direct_exchange_access": direct_access,
        "parse_failures": {
            "active": active_parse_failures,
            "archived_like": archived_parse_failures,
        },
        "findings": findings,
        "safety": {
            "source_files_modified": False,
            "atlas_modules_imported": False,
            "exchange_connections_opened": False,
            "secret_values_read": False,
        },
    }

    json_path = REPORT_DIR / "phase6a2_1_migration_readiness.json"
    json_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    lines = [
        "=" * 78,
        "ATLAS PHASE 6A2.1 — MARKET DATA MIGRATION READINESS",
        "=" * 78,
        "",
        f"Python files scanned       : {report['summary']['python_files_scanned']}",
        f"Parse failures total       : {report['summary']['parse_failures_total']}",
        f"Active parse failures      : {report['summary']['parse_failures_active']}",
        f"Archived-like failures     : {report['summary']['parse_failures_archived_like']}",
        f"Legacy usage files         : {report['summary']['legacy_usage_files']}",
        f"Canonical usage files      : {report['summary']['canonical_usage_files']}",
        f"Direct exchange files      : {report['summary']['direct_access_files']}",
        f"HIGH migration findings    : {report['summary']['high_findings']}",
        "",
        "MIGRATION FINDINGS",
        "-" * 78,
    ]

    for finding in findings:
        lines.append(
            f"[{finding['severity']}] {finding['code']}"
        )
        lines.append(f"  {finding['message']}")
        if finding.get("methods"):
            lines.append(
                "  Methods: " + ", ".join(finding["methods"])
            )
        lines.append("")

    lines.extend([
        "LEGACY MARKET FEED USAGE",
        "-" * 78,
    ])

    for item in legacy_usage:
        lines.append(f"- {item['file']}")
        for usage in item["target_imports"]:
            if usage["target_module"] == "exchange.market_feed":
                lines.append(
                    f"  import line {usage['line']}: "
                    f"{usage['target_module']}.{usage['target_class']}"
                )
        for instance in item["instantiations"]:
            if instance["target_class"] == "MarketFeed":
                lines.append(
                    f"  construct line {instance['line']}: "
                    f"args={instance['args']} kwargs={instance['keywords']}"
                )

    lines.extend([
        "",
        "ACTIVE PARSE FAILURES",
        "-" * 78,
    ])

    if active_parse_failures:
        for item in active_parse_failures:
            lines.append(
                f"- {item['file']}:{item.get('line')} "
                f"{item.get('message')} | {item.get('context')}"
            )
    else:
        lines.append("- None")

    lines.extend([
        "",
        "DIRECT EXCHANGE ACCESS",
        "-" * 78,
    ])

    for item in direct_access:
        state = "ARCHIVED-LIKE" if item["soft_archived"] else "ACTIVE"
        lines.append(f"- [{state}] {item['file']}")
        for location in item["locations"]:
            lines.append(
                f"  line {location['line']}: "
                f"{location['called']}"
            )

    text_path = REPORT_DIR / "phase6a2_1_migration_readiness.txt"
    text_path.write_text(
        "\n".join(lines) + "\n",
        encoding="utf-8",
    )

    print("=" * 72)
    print("ATLAS PHASE 6A2.1 - MARKET DATA MIGRATION READINESS")
    print("=" * 72)
    print(f"Python files scanned    : {report['summary']['python_files_scanned']}")
    print(f"Parse failures total    : {report['summary']['parse_failures_total']}")
    print(f"Active parse failures   : {report['summary']['parse_failures_active']}")
    print(f"Archived-like failures  : {report['summary']['parse_failures_archived_like']}")
    print(f"Legacy usage files      : {report['summary']['legacy_usage_files']}")
    print(f"Canonical usage files   : {report['summary']['canonical_usage_files']}")
    print(f"Direct exchange files   : {report['summary']['direct_access_files']}")
    print(f"HIGH migration findings : {report['summary']['high_findings']}")
    print()

    for finding in findings:
        print(
            f"[{finding['severity']}] "
            f"{finding['code']} -> {finding['message']}"
        )
        if finding.get("methods"):
            print(
                "  Methods: " + ", ".join(finding["methods"])
            )

    print()
    print(f"JSON report : {json_path}")
    print(f"Text report : {text_path}")
    print()
    print("PHASE 6A2.1 COMPLETED - READ-ONLY AUDIT")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
