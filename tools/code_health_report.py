"""Read-only code-health report over the runtime closure (CODE-001 baseline).

Registry v5.26. Measures what the CODE-001 ratchet test pins: bare
``except:`` handlers, TODO/FIXME markers, ``print()`` calls and functions
longer than LONG_FUNCTION_LINES, over every module in
packaging/atlas_runtime_closure.json. Writes nothing.

Usage:
  python -m tools.code_health_report
"""

from __future__ import annotations

import ast
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CLOSURE = ROOT / "packaging" / "atlas_runtime_closure.json"
LONG_FUNCTION_LINES = 300


def measure(root: Path = ROOT) -> dict:
    modules = json.loads((root / "packaging" / "atlas_runtime_closure.json").read_text(encoding="utf-8"))["modules"]
    result = {"modules": len(modules), "lines": 0, "bare_except": [], "todo_fixme": [],
              "print_calls": 0, "long_functions": []}
    for module in modules:
        source = (root / module).read_text(encoding="utf-8-sig")
        result["lines"] += source.count("\n")
        for number, line in enumerate(source.splitlines(), 1):
            if "TODO" in line or "FIXME" in line:
                result["todo_fixme"].append(f"{module}:{number}")
        for node in ast.walk(ast.parse(source)):
            if isinstance(node, ast.ExceptHandler) and node.type is None:
                result["bare_except"].append(f"{module}:{node.lineno}")
            elif isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "print":
                result["print_calls"] += 1
            elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                length = (node.end_lineno or node.lineno) - node.lineno
                if length > LONG_FUNCTION_LINES:
                    result["long_functions"].append(f"{module}::{node.name}")
    return result


def main() -> int:
    r = measure()
    print(f"runtime closure: {r['modules']} modules, {r['lines']} lines")
    print(f"bare except: {len(r['bare_except'])}  TODO/FIXME: {len(r['todo_fixme'])}  "
          f"print(): {r['print_calls']}  functions > {LONG_FUNCTION_LINES} lines: {len(r['long_functions'])}")
    for name in r["long_functions"]:
        print(f"  long: {name}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
