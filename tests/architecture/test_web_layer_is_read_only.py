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
    # audit MEDIUM-3: widened
    # (dict methods update/clear/pop are excluded: they are used on local
    # payload dicts; runtime objects are only reached through getattr,
    # which is checked by name below.)
    "process_symbol", "reset", "unlink",
    "write_text", "write_bytes", "shutdown", "quarantine", "append_event",
    "emergency_stop", "resume", "set_mode", "submit", "cancel",
}

# getattr proxies: helpers whose own getattr takes a parameter name. Every
# call site of a proxy is checked instead (its name argument must be a
# literal that is not a state-changing method).
GETATTR_PROXIES = {"_resolve_attr"}

# Attribute stores are allowed only on FastAPI's own app state.
ALLOWED_STORE_ROOTS = {"application"}


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


def _getattr_names(call: ast.Call, parents: dict) -> list[str] | None:
    """Names a getattr(obj, NAME) call can resolve to, or None if unknowable."""

    if len(call.args) < 2:
        return None
    name = call.args[1]
    if isinstance(name, ast.Constant) and isinstance(name.value, str):
        return [name.value]
    if isinstance(name, ast.Name):
        node = call
        while node in parents:
            node = parents[node]
            if (
                isinstance(node, ast.For)
                and isinstance(node.target, ast.Name)
                and node.target.id == name.id
                and isinstance(node.iter, (ast.Tuple, ast.List))
                and all(isinstance(e, ast.Constant) and isinstance(e.value, str) for e in node.iter.elts)
            ):
                return [e.value for e in node.iter.elts]
    return None


def _inside_proxy(node, parents) -> bool:
    while node in parents:
        node = parents[node]
        if isinstance(node, ast.FunctionDef) and node.name in GETATTR_PROXIES:
            return True
    return False


def test_web_layer_mutates_nothing_indirectly():
    """audit MEDIUM-3: setattr/delattr, stores on injected objects, and
    getattr lookups that could reach a state-changing method."""

    offenders = []
    for path in WEB_FILES:
        tree = _tree(path)
        parents = {child: node for node in ast.walk(tree) for child in ast.iter_child_nodes(node)}
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
                if node.func.id in {"setattr", "delattr"}:
                    offenders.append(f"{path.name}:{node.lineno} {node.func.id}()")
                if node.func.id in GETATTR_PROXIES:
                    name = node.args[1] if len(node.args) > 1 else None
                    if not (isinstance(name, ast.Constant) and isinstance(name.value, str)):
                        offenders.append(f"{path.name}:{node.lineno} {node.func.id} with non-literal name")
                    elif name.value in MUTATING_METHODS:
                        offenders.append(f"{path.name}:{node.lineno} {node.func.id} -> {name.value}")
                if node.func.id == "getattr" and not _inside_proxy(node, parents):
                    names = _getattr_names(node, parents)
                    if names is None:
                        offenders.append(f"{path.name}:{node.lineno} getattr with unknowable name")
                    elif set(names) & MUTATING_METHODS:
                        offenders.append(f"{path.name}:{node.lineno} getattr -> {sorted(set(names) & MUTATING_METHODS)}")
            if isinstance(node, (ast.Assign, ast.AugAssign, ast.AnnAssign, ast.Delete)):
                targets = node.targets if isinstance(node, (ast.Assign, ast.Delete)) else [node.target]
                for target in targets:
                    if isinstance(target, ast.Attribute):
                        root = target
                        while isinstance(root, ast.Attribute):
                            root = root.value
                        if not (isinstance(root, ast.Name) and root.id in ALLOWED_STORE_ROOTS):
                            offenders.append(f"{path.name}:{node.lineno} attribute store")
    assert offenders == [], offenders
