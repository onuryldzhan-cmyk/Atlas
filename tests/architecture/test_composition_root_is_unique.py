"""D5 / S2: exactly one canonical module constructs the authoritative runtime.

core/application.py must be the only live module that constructs
AtlasBrain, MarketLoop, and ExecutionManager (the composition-root
authority). This is checked structurally (AST call-site scan across every
live module) rather than by import-only analysis, since a file could import
a class without ever constructing it, or construct it via an attribute
access without a plain top-level import.
"""

from __future__ import annotations

import ast

from tools.build_architecture_inventory import (
    REPOSITORY_ROOT,
    ENTRY_POINTS,
    compute_runtime_closure,
)

_AUTHORITATIVE_CLASSES = {
    "AtlasBrain": "core/brain.py",
    "MarketLoop": "core/market_loop.py",
    "ExecutionManager": "core/execution_manager.py",
}

_CANONICAL_COMPOSITION_ROOT = "core/application.py"


def _call_target_names(tree: ast.AST) -> set[str]:
    names: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if isinstance(func, ast.Name):
            names.add(func.id)
        elif isinstance(func, ast.Attribute):
            names.add(func.attr)
    return names


def test_composition_root_is_unique() -> None:
    closure = compute_runtime_closure(REPOSITORY_ROOT, ENTRY_POINTS)

    constructors: dict[str, list[str]] = {name: [] for name in _AUTHORITATIVE_CLASSES}

    for relative_path in closure:
        source = (REPOSITORY_ROOT / relative_path).read_text(encoding="utf-8-sig")
        tree = ast.parse(source, filename=relative_path)
        called_names = _call_target_names(tree)

        for class_name, defining_file in _AUTHORITATIVE_CLASSES.items():
            if relative_path == defining_file:
                # A class's own module may reference its name in ways that
                # are not construction (e.g. type aliases); the defining
                # file is never itself a "constructor" of the class.
                continue
            if class_name in called_names:
                constructors[class_name].append(relative_path)

    for class_name, callers in constructors.items():
        assert callers == [_CANONICAL_COMPOSITION_ROOT], (
            f"{class_name} must be constructed only by {_CANONICAL_COMPOSITION_ROOT}, "
            f"but found construction call(s) in: {callers}"
        )


def test_main_is_the_only_atlas_application_constructor() -> None:
    closure = compute_runtime_closure(REPOSITORY_ROOT, ENTRY_POINTS)

    constructors: list[str] = []
    for relative_path in closure:
        if relative_path == "core/application.py":
            continue
        source = (REPOSITORY_ROOT / relative_path).read_text(encoding="utf-8-sig")
        tree = ast.parse(source, filename=relative_path)
        if "AtlasApplication" in _call_target_names(tree):
            constructors.append(relative_path)

    assert constructors == ["main.py"], (
        f"AtlasApplication must be constructed only by main.py, found: {constructors}"
    )
