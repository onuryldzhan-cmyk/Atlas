"""
============================================================
ATLAS PHASE 6A3.1 — MARKET DATA LIFECYCLE CONTRACT AUDIT
============================================================

Purpose
-------
Extract the real runtime contract for:
- MarketDataProviderProtocol
- BinancePublicDataProvider
- MarketFeedService
- BaseAtlasService

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
from datetime import UTC, datetime
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
REPORT_DIR = ROOT / "reports" / "phase6_market_data_lifecycle_contract"

TARGETS = {
    "contracts": ROOT / "atlas_finance" / "market_data" / "contracts.py",
    "provider": ROOT / "atlas_finance" / "market_data" / "binance_public_provider.py",
    "service": ROOT / "atlas_finance" / "market_data" / "market_feed_service.py",
    "base_service": ROOT / "atlas_os" / "services" / "base_service.py",
}

FOCUS_METHODS = {
    "contracts": {
        "__init__",
        "connect",
        "disconnect",
        "get_price",
        "get_candles",
        "health",
    },
    "provider": {
        "__init__",
        "connect",
        "disconnect",
        "get_price",
        "get_candles",
        "health",
    },
    "service": {
        "__init__",
        "_on_start",
        "_on_stop",
        "get_price",
        "get_candles",
        "health",
    },
    "base_service": {
        "__init__",
        "start",
        "stop",
        "health",
    },
}


def annotation_text(node):
    if node is None:
        return None
    return ast.unparse(node)


def signature(node):
    args = []

    positional = list(node.args.posonlyargs) + list(node.args.args)
    defaults = [None] * (len(positional) - len(node.args.defaults)) + list(node.args.defaults)

    for arg, default in zip(positional, defaults):
        text = arg.arg
        if arg.annotation is not None:
            text += f": {annotation_text(arg.annotation)}"
        if default is not None:
            text += f" = {ast.unparse(default)}"
        args.append(text)

    if node.args.vararg:
        text = f"*{node.args.vararg.arg}"
        if node.args.vararg.annotation is not None:
            text += f": {annotation_text(node.args.vararg.annotation)}"
        args.append(text)
    elif node.args.kwonlyargs:
        args.append("*")

    for arg, default in zip(node.args.kwonlyargs, node.args.kw_defaults):
        text = arg.arg
        if arg.annotation is not None:
            text += f": {annotation_text(arg.annotation)}"
        if default is not None:
            text += f" = {ast.unparse(default)}"
        args.append(text)

    if node.args.kwarg:
        text = f"**{node.args.kwarg.arg}"
        if node.args.kwarg.annotation is not None:
            text += f": {annotation_text(node.args.kwarg.annotation)}"
        args.append(text)

    ret = annotation_text(node.returns)
    return f"{node.name}({', '.join(args)})" + (f" -> {ret}" if ret else "")


def source_segment(lines, node):
    start = max(1, node.lineno)
    end = getattr(node, "end_lineno", node.lineno)
    return "\n".join(lines[start - 1:end])


def extract_file(label, path):
    if not path.exists():
        return {
            "label": label,
            "path": str(path.relative_to(ROOT)),
            "exists": False,
        }

    text = path.read_text(encoding="utf-8", errors="replace")
    lines = text.splitlines()
    tree = ast.parse(text, filename=str(path))

    classes = []
    functions = []

    for node in tree.body:
        if isinstance(node, ast.ClassDef):
            methods = []
            for item in node.body:
                if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    if item.name in FOCUS_METHODS[label]:
                        methods.append({
                            "name": item.name,
                            "signature": signature(item),
                            "line_start": item.lineno,
                            "line_end": getattr(item, "end_lineno", item.lineno),
                            "source": source_segment(lines, item),
                            "docstring": ast.get_docstring(item),
                        })

            classes.append({
                "name": node.name,
                "bases": [ast.unparse(base) for base in node.bases],
                "line_start": node.lineno,
                "line_end": getattr(node, "end_lineno", node.lineno),
                "methods": methods,
                "docstring": ast.get_docstring(node),
            })

        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if node.name in FOCUS_METHODS[label]:
                functions.append({
                    "name": node.name,
                    "signature": signature(node),
                    "line_start": node.lineno,
                    "line_end": getattr(node, "end_lineno", node.lineno),
                    "source": source_segment(lines, node),
                    "docstring": ast.get_docstring(node),
                })

    return {
        "label": label,
        "path": str(path.relative_to(ROOT)),
        "exists": True,
        "classes": classes,
        "functions": functions,
    }


def main():
    REPORT_DIR.mkdir(parents=True, exist_ok=True)

    extracted = {
        label: extract_file(label, path)
        for label, path in TARGETS.items()
    }

    report = {
        "phase": "6A3.1",
        "generated_utc": datetime.now(UTC).isoformat(),
        "targets": extracted,
        "safety": {
            "source_files_modified": False,
            "atlas_modules_imported": False,
            "exchange_connections_opened": False,
        },
    }

    json_path = REPORT_DIR / "phase6a3_1_lifecycle_contract.json"
    json_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    text_lines = [
        "=" * 78,
        "ATLAS PHASE 6A3.1 — MARKET DATA LIFECYCLE CONTRACT AUDIT",
        "=" * 78,
        "",
    ]

    for label, data in extracted.items():
        text_lines.append(f"[{label.upper()}] {data['path']}")
        text_lines.append("-" * 78)

        if not data.get("exists"):
            text_lines.append("FILE NOT FOUND")
            text_lines.append("")
            continue

        for cls in data.get("classes", []):
            text_lines.append(
                f"CLASS {cls['name']}({', '.join(cls['bases'])}) "
                f"lines {cls['line_start']}-{cls['line_end']}"
            )
            if cls.get("docstring"):
                text_lines.append(f"DOC: {cls['docstring']}")

            for method in cls.get("methods", []):
                text_lines.append("")
                text_lines.append(
                    f"METHOD {method['signature']} "
                    f"lines {method['line_start']}-{method['line_end']}"
                )
                text_lines.append(method["source"])

            text_lines.append("")

        for fn in data.get("functions", []):
            text_lines.append(
                f"FUNCTION {fn['signature']} "
                f"lines {fn['line_start']}-{fn['line_end']}"
            )
            text_lines.append(fn["source"])
            text_lines.append("")

    text_path = REPORT_DIR / "phase6a3_1_lifecycle_contract.txt"
    text_path.write_text("\n".join(text_lines), encoding="utf-8")

    summary_path = REPORT_DIR / "phase6a3_1_contract_summary.txt"
    summary = [
        "ATLAS PHASE 6A3.1 CONTRACT SUMMARY",
        "",
    ]

    for label, data in extracted.items():
        summary.append(f"[{label}] {data['path']}")
        if not data.get("exists"):
            summary.append("  FILE NOT FOUND")
            continue

        for cls in data.get("classes", []):
            summary.append(
                f"  class {cls['name']} bases={cls['bases']}"
            )
            for method in cls.get("methods", []):
                summary.append(
                    f"    {method['signature']} "
                    f"[{method['line_start']}-{method['line_end']}]"
                )

    summary_path.write_text("\n".join(summary), encoding="utf-8")

    print("=" * 72)
    print("ATLAS PHASE 6A3.1 - MARKET DATA LIFECYCLE CONTRACT AUDIT")
    print("=" * 72)

    for label, data in extracted.items():
        status = "FOUND" if data.get("exists") else "MISSING"
        method_count = sum(
            len(cls.get("methods", []))
            for cls in data.get("classes", [])
        )
        print(
            f"{label:<14}: {status} | focused methods={method_count}"
        )

    print()
    print(f"JSON report   : {json_path}")
    print(f"Text report   : {text_path}")
    print(f"Summary       : {summary_path}")
    print()
    print("PHASE 6A3.1 COMPLETED - READ-ONLY AUDIT")


if __name__ == "__main__":
    main()
