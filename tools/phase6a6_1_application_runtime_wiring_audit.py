"""
============================================================
ATLAS PHASE 6A6.1 — APPLICATION RUNTIME WIRING AUDIT
============================================================

Purpose
-------
Extract the real application wiring and lifecycle contract for:
- core.application.AtlasApplication
- main.py startup path
- MarketFeed creation
- MarketLoop creation
- start / stop ordering

Safety
------
- Read-only
- Does not import Atlas modules
- Does not start services
- Does not connect to Binance
- Does not modify source files
============================================================
"""

from __future__ import annotations

import ast
import json
from datetime import UTC, datetime
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
REPORT_DIR = ROOT / "reports" / "phase6_application_runtime_wiring"

TARGETS = {
    "main": ROOT / "main.py",
    "application": ROOT / "core" / "application.py",
    "market_loop": ROOT / "core" / "market_loop.py",
    "market_feed": ROOT / "exchange" / "market_feed.py",
}

TOKENS = (
    "MarketFeed",
    "MarketLoop",
    "AtlasApplication",
    ".start",
    ".stop",
    "market_feed",
    "market_loop",
)


def signature(node):
    parts = []
    positional = list(node.args.posonlyargs) + list(node.args.args)
    defaults = [None] * (len(positional) - len(node.args.defaults)) + list(node.args.defaults)

    for arg, default in zip(positional, defaults):
        text = arg.arg
        if arg.annotation is not None:
            text += f": {ast.unparse(arg.annotation)}"
        if default is not None:
            text += f" = {ast.unparse(default)}"
        parts.append(text)

    if node.args.vararg:
        parts.append(f"*{node.args.vararg.arg}")
    elif node.args.kwonlyargs:
        parts.append("*")

    for arg, default in zip(node.args.kwonlyargs, node.args.kw_defaults):
        text = arg.arg
        if arg.annotation is not None:
            text += f": {ast.unparse(arg.annotation)}"
        if default is not None:
            text += f" = {ast.unparse(default)}"
        parts.append(text)

    if node.args.kwarg:
        parts.append(f"**{node.args.kwarg.arg}")

    result = f"{node.name}({', '.join(parts)})"
    if node.returns is not None:
        result += f" -> {ast.unparse(node.returns)}"
    return result


class CallVisitor(ast.NodeVisitor):
    def __init__(self):
        self.calls = []

    def visit_Call(self, node):
        try:
            func = ast.unparse(node.func)
        except Exception:
            func = "<unparseable>"

        if any(token.lower() in func.lower() for token in TOKENS):
            self.calls.append({
                "line": node.lineno,
                "call": func,
                "args": [ast.unparse(arg) for arg in node.args],
                "kwargs": {
                    kw.arg or "**": ast.unparse(kw.value)
                    for kw in node.keywords
                },
            })

        self.generic_visit(node)


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

    records = []

    for node in tree.body:
        if isinstance(node, ast.ClassDef):
            methods = []
            for item in node.body:
                if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    visitor = CallVisitor()
                    visitor.visit(item)

                    source = "\n".join(
                        lines[item.lineno - 1:getattr(item, "end_lineno", item.lineno)]
                    )

                    if visitor.calls or item.name in {
                        "__init__",
                        "start",
                        "stop",
                        "run",
                        "bootstrap",
                        "shutdown",
                        "build",
                        "create",
                    }:
                        methods.append({
                            "name": item.name,
                            "signature": signature(item),
                            "line_start": item.lineno,
                            "line_end": getattr(item, "end_lineno", item.lineno),
                            "calls": visitor.calls,
                            "source": source,
                        })

            records.append({
                "kind": "class",
                "name": node.name,
                "bases": [ast.unparse(base) for base in node.bases],
                "line_start": node.lineno,
                "line_end": getattr(node, "end_lineno", node.lineno),
                "methods": methods,
            })

        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            visitor = CallVisitor()
            visitor.visit(node)

            if visitor.calls or node.name in {
                "main",
                "run",
                "bootstrap",
                "shutdown",
                "build_application",
                "create_application",
            }:
                records.append({
                    "kind": "function",
                    "name": node.name,
                    "signature": signature(node),
                    "line_start": node.lineno,
                    "line_end": getattr(node, "end_lineno", node.lineno),
                    "calls": visitor.calls,
                    "source": "\n".join(
                        lines[node.lineno - 1:getattr(node, "end_lineno", node.lineno)]
                    ),
                })

    return {
        "label": label,
        "path": str(path.relative_to(ROOT)),
        "exists": True,
        "records": records,
    }


def main():
    REPORT_DIR.mkdir(parents=True, exist_ok=True)

    extracted = {
        label: extract_file(label, path)
        for label, path in TARGETS.items()
    }

    report = {
        "phase": "6A6.1",
        "generated_utc": datetime.now(UTC).isoformat(),
        "targets": extracted,
        "safety": {
            "source_files_modified": False,
            "atlas_modules_imported": False,
            "services_started": False,
            "network_used": False,
        },
    }

    json_path = REPORT_DIR / "phase6a6_1_application_runtime_wiring.json"
    json_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    summary = [
        "ATLAS PHASE 6A6.1 — APPLICATION RUNTIME WIRING SUMMARY",
        "",
    ]

    details = [
        "=" * 78,
        "ATLAS PHASE 6A6.1 — APPLICATION RUNTIME WIRING AUDIT",
        "=" * 78,
        "",
    ]

    for label, item in extracted.items():
        summary.append(f"[{label}] {item['path']}")
        details.append(f"[{label.upper()}] {item['path']}")
        details.append("-" * 78)

        if not item.get("exists"):
            summary.append("  FILE NOT FOUND")
            details.append("FILE NOT FOUND")
            details.append("")
            continue

        for record in item.get("records", []):
            if record["kind"] == "class":
                summary.append(
                    f"  class {record['name']} bases={record['bases']}"
                )
                details.append(
                    f"CLASS {record['name']}({', '.join(record['bases'])})"
                )
                for method in record.get("methods", []):
                    summary.append(
                        f"    {method['signature']} "
                        f"[{method['line_start']}-{method['line_end']}]"
                    )
                    for call in method.get("calls", []):
                        summary.append(
                            f"      CALL line {call['line']}: "
                            f"{call['call']} args={call['args']} kwargs={call['kwargs']}"
                        )
                    details.append("")
                    details.append(
                        f"METHOD {method['signature']} "
                        f"[{method['line_start']}-{method['line_end']}]"
                    )
                    details.append(method["source"])
            else:
                summary.append(
                    f"  function {record['signature']} "
                    f"[{record['line_start']}-{record['line_end']}]"
                )
                for call in record.get("calls", []):
                    summary.append(
                        f"    CALL line {call['line']}: "
                        f"{call['call']} args={call['args']} kwargs={call['kwargs']}"
                    )
                details.append(
                    f"FUNCTION {record['signature']} "
                    f"[{record['line_start']}-{record['line_end']}]"
                )
                details.append(record["source"])

            details.append("")

    summary_path = REPORT_DIR / "phase6a6_1_wiring_summary.txt"
    summary_path.write_text("\n".join(summary), encoding="utf-8")

    details_path = REPORT_DIR / "phase6a6_1_wiring_details.txt"
    details_path.write_text("\n".join(details), encoding="utf-8")

    print("=" * 72)
    print("ATLAS PHASE 6A6.1 - APPLICATION RUNTIME WIRING AUDIT")
    print("=" * 72)

    for label, item in extracted.items():
        status = "FOUND" if item.get("exists") else "MISSING"
        record_count = len(item.get("records", []))
        print(f"{label:<14}: {status} | extracted records={record_count}")

    print()
    print(f"JSON report : {json_path}")
    print(f"Summary     : {summary_path}")
    print(f"Details     : {details_path}")
    print()
    print("PHASE 6A6.1 COMPLETED - READ-ONLY AUDIT")


if __name__ == "__main__":
    main()
