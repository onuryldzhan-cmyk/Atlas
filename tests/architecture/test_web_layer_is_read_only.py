"""The web layer only reads the runtime (Phase 2-3 item 5).

web_app.py and observability/* may not import execution, risk, capital or
state-store modules, and may not call a state-changing method on anything.
"""

from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
WEB_FILES = [ROOT / "web_app.py", *sorted((ROOT / "observability").glob("*.py"))]

FORBIDDEN_IMPORT_PREFIXES = ("core", "ai", "risk", "execution", "database", "data_layer", "main")
ALLOWED_FIRST_PARTY = ("observability",)

MUTATING_METHODS = {
    "stop", "start", "execute", "risk_check", "paper_execute", "open_trade",
    "close_trade", "save", "initialize", "commit", "release", "reserve",
    "attach_experiment", "close_experiment", "halt", "record", "apply",
}


def _tree(path: Path) -> ast.AST:
    return ast.parse(path.read_text(encoding="utf-8-sig"), filename=str(path))


def test_web_layer_imports_no_core_module():
    offenders = []
    for path in WEB_FILES:
        for node in ast.walk(_tree(path)):
            if isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
                names = [node.module]
            elif isinstance(node, ast.Import):
                names = [alias.name for alias in node.names]
            else:
                continue
            for name in names:
                top = name.split(".")[0]
                if top in FORBIDDEN_IMPORT_PREFIXES and top not in ALLOWED_FIRST_PARTY:
                    offenders.append(f"{path.name}: {name}")
    assert offenders == []


def test_web_layer_calls_no_state_changing_method():
    offenders = []
    for path in WEB_FILES:
        for node in ast.walk(_tree(path)):
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr in MUTATING_METHODS
            ):
                offenders.append(f"{path.name}:{node.lineno} .{node.func.attr}()")
    assert offenders == []
