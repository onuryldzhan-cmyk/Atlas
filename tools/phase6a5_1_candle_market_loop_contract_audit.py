"""
============================================================
ATLAS PHASE 6A5.1 — CANDLE / MARKET LOOP CONTRACT AUDIT
============================================================

Purpose
-------
Read the actual integration contract among:
- exchange.market_feed.MarketFeed
- core.candle_processor.CandleProcessor
- core.market_loop.MarketLoop
- core.technical_analyzer.TechnicalAnalyzer

Safety
------
- Read-only
- No Atlas imports
- No exchange connection
- No source modification
============================================================
"""

from __future__ import annotations

import ast
import json
from datetime import UTC, datetime
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
REPORT_DIR = ROOT / "reports" / "phase6_candle_market_loop_contract"

TARGETS = {
    "market_feed": ROOT / "exchange" / "market_feed.py",
    "candle_processor": ROOT / "core" / "candle_processor.py",
    "market_loop": ROOT / "core" / "market_loop.py",
    "technical_analyzer": ROOT / "core" / "technical_analyzer.py",
}

FOCUS = {
    "market_feed": {"candles", "get_candles"},
    "candle_processor": {
        "__init__",
        "process",
        "process_candles",
        "build",
        "normalize",
        "convert",
        "latest",
        "statistics",
        "health",
    },
    "market_loop": {
        "__init__",
        "start",
        "stop",
        "run",
        "_run",
        "_loop",
        "_process_symbol",
        "process_symbol",
        "scan_symbol",
        "statistics",
        "health",
    },
    "technical_analyzer": {
        "__init__",
        "analyze",
        "analyze_candles",
        "statistics",
        "health",
    },
}


def signature(node):
    args = []
    positional = list(node.args.posonlyargs) + list(node.args.args)
    defaults = [None] * (len(positional) - len(node.args.defaults)) + list(node.args.defaults)

    for arg, default in zip(positional, defaults):
        text = arg.arg
        if arg.annotation is not None:
            text += f": {ast.unparse(arg.annotation)}"
        if default is not None:
            text += f" = {ast.unparse(default)}"
        args.append(text)

    if node.args.vararg:
        text = f"*{node.args.vararg.arg}"
        if node.args.vararg.annotation is not None:
            text += f": {ast.unparse(node.args.vararg.annotation)}"
        args.append(text)
    elif node.args.kwonlyargs:
        args.append("*")

    for arg, default in zip(node.args.kwonlyargs, node.args.kw_defaults):
        text = arg.arg
        if arg.annotation is not None:
            text += f": {ast.unparse(arg.annotation)}"
        if default is not None:
            text += f" = {ast.unparse(default)}"
        args.append(text)

    if node.args.kwarg:
        text = f"**{node.args.kwarg.arg}"
        if node.args.kwarg.annotation is not None:
            text += f": {ast.unparse(node.args.kwarg.annotation)}"
        args.append(text)

    result = f"{node.name}({', '.join(args)})"
    if node.returns is not None:
        result += f" -> {ast.unparse(node.returns)}"
    return result


class CallVisitor(ast.NodeVisitor):
    def __init__(self):
        self.calls = []

    def visit_Call(self, node):
        try:
            value = ast.unparse(node.func)
        except Exception:
            value = "<unparseable>"
        self.calls.append({
            "call": value,
            "line": node.lineno,
            "arguments": [ast.unparse(arg) for arg in node.args],
            "keywords": {
                kw.arg or "**": ast.unparse(kw.value)
                for kw in node.keywords
            },
        })
        self.generic_visit(node)


def extract(label, path):
    if not path.exists():
        return {
            "label": label,
            "path": str(path.relative_to(ROOT)),
            "exists": False,
        }

    source = path.read_text(encoding="utf-8", errors="replace")
    lines = source.splitlines()
    tree = ast.parse(source, filename=str(path))

    classes = []
    imports = []

    for node in tree.body:
        if isinstance(node, ast.Import):
            imports.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            imports.append(
                f"{node.module}:{','.join(alias.name for alias in node.names)}"
            )
        elif isinstance(node, ast.ClassDef):
            methods = []
            for item in node.body:
                if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    visitor = CallVisitor()
                    visitor.visit(item)
                    relevant_calls = [
                        call for call in visitor.calls
                        if any(
                            token in call["call"].lower()
                            for token in (
                                "candle",
                                "market_feed",
                                "analy",
                                "brain",
                                "decision",
                            )
                        )
                    ]

                    if item.name in FOCUS[label] or relevant_calls:
                        start = item.lineno
                        end = getattr(item, "end_lineno", item.lineno)
                        methods.append({
                            "name": item.name,
                            "signature": signature(item),
                            "line_start": start,
                            "line_end": end,
                            "source": "\n".join(lines[start - 1:end]),
                            "relevant_calls": relevant_calls,
                        })

            classes.append({
                "name": node.name,
                "bases": [ast.unparse(base) for base in node.bases],
                "line_start": node.lineno,
                "line_end": getattr(node, "end_lineno", node.lineno),
                "methods": methods,
            })

    return {
        "label": label,
        "path": str(path.relative_to(ROOT)),
        "exists": True,
        "imports": imports,
        "classes": classes,
    }


def main():
    REPORT_DIR.mkdir(parents=True, exist_ok=True)

    data = {
        label: extract(label, path)
        for label, path in TARGETS.items()
    }

    report = {
        "phase": "6A5.1",
        "generated_utc": datetime.now(UTC).isoformat(),
        "targets": data,
        "safety": {
            "source_files_modified": False,
            "atlas_modules_imported": False,
            "exchange_connections_opened": False,
        },
    }

    json_path = REPORT_DIR / "phase6a5_1_candle_market_loop_contract.json"
    json_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    summary = [
        "ATLAS PHASE 6A5.1 — CANDLE / MARKET LOOP CONTRACT SUMMARY",
        "",
    ]

    detailed = [
        "=" * 78,
        "ATLAS PHASE 6A5.1 — CANDLE / MARKET LOOP CONTRACT AUDIT",
        "=" * 78,
        "",
    ]

    for label, item in data.items():
        summary.append(f"[{label}] {item['path']}")
        detailed.append(f"[{label.upper()}] {item['path']}")
        detailed.append("-" * 78)

        if not item.get("exists"):
            summary.append("  FILE NOT FOUND")
            detailed.append("FILE NOT FOUND")
            detailed.append("")
            continue

        for cls in item.get("classes", []):
            summary.append(
                f"  class {cls['name']} bases={cls['bases']}"
            )
            detailed.append(
                f"CLASS {cls['name']}({', '.join(cls['bases'])})"
            )

            for method in cls.get("methods", []):
                summary.append(
                    f"    {method['signature']} "
                    f"[{method['line_start']}-{method['line_end']}]"
                )

                for call in method.get("relevant_calls", []):
                    summary.append(
                        f"      CALL line {call['line']}: "
                        f"{call['call']} args={call['arguments']} "
                        f"kwargs={call['keywords']}"
                    )

                detailed.append("")
                detailed.append(
                    f"METHOD {method['signature']} "
                    f"[{method['line_start']}-{method['line_end']}]"
                )
                detailed.append(method["source"])

            detailed.append("")

    summary_path = REPORT_DIR / "phase6a5_1_contract_summary.txt"
    summary_path.write_text("\n".join(summary), encoding="utf-8")

    text_path = REPORT_DIR / "phase6a5_1_contract_details.txt"
    text_path.write_text("\n".join(detailed), encoding="utf-8")

    print("=" * 72)
    print("ATLAS PHASE 6A5.1 - CANDLE / MARKET LOOP CONTRACT AUDIT")
    print("=" * 72)

    for label, item in data.items():
        status = "FOUND" if item.get("exists") else "MISSING"
        method_count = sum(
            len(cls.get("methods", []))
            for cls in item.get("classes", [])
        )
        print(f"{label:<20}: {status} | extracted methods={method_count}")

    print()
    print(f"JSON report : {json_path}")
    print(f"Summary     : {summary_path}")
    print(f"Details     : {text_path}")
    print()
    print("PHASE 6A5.1 COMPLETED - READ-ONLY AUDIT")


if __name__ == "__main__":
    main()
