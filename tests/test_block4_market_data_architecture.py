"""Block 4 / Package 1: architecture placement of the market-data contracts.

`tools/build_architecture_inventory.py check` validates only the runtime
closure -- the modules reachable from the composition root. The Package-1
market-data modules are deliberately unwired, exactly like the Package-3
capability contracts were before them, so they are invisible to that check
and a layer-rule regression would not be caught by it.

These tests close that blind spot: the explicit L1 rules must exist, must
win over the generic `data_layer/*` -> L2 default, must actually resolve
both modules to L1, and the modules must stay outside the runtime closure
with no upward dependency.
"""

from __future__ import annotations

import ast
import json
from pathlib import Path

from tools.build_architecture_inventory import (
    ENTRY_POINTS,
    REPOSITORY_ROOT,
    classify_module,
    compute_runtime_closure,
    load_architecture_map,
)

PACKAGE_1_MODULES = (
    "data_layer/market_data_models.py",
    "data_layer/market_data_contracts.py",
)

GENERIC_DATA_LAYER_RULE = "data_layer/*"

# The only first-party modules the Package-1 contracts may depend on: the
# two L1 execution-domain contract modules they deliberately reuse, plus
# each other. Anything else would be an upward dependency out of L1.
ALLOWED_FIRST_PARTY_IMPORTS = {
    "data_layer.contracts",
    "data_layer.models",
    "data_layer.market_data_models",
}


def layer_rules() -> list[dict]:
    return load_architecture_map()["layer_rules"]


def rule_index(pattern: str) -> int:
    for index, rule in enumerate(layer_rules()):
        if rule["pattern"] == pattern:
            return index
    raise AssertionError(f"no layer rule declared for pattern {pattern!r}")


def imported_first_party(relative_path: str) -> set[str]:
    """First-party dotted modules a Package-1 module imports.

    Relative imports are resolved against the module's own package so
    `from .contracts import ...` is scored as `data_layer.contracts` rather
    than being silently skipped.
    """

    package = Path(relative_path).parent.as_posix().replace("/", ".")
    tree = ast.parse((REPOSITORY_ROOT / relative_path).read_text(encoding="utf-8"))
    modules: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            if node.level:
                modules.add(f"{package}.{node.module}" if node.module else package)
            elif node.module:
                modules.add(node.module)
        elif isinstance(node, ast.Import):
            for alias in node.names:
                modules.add(alias.name)

    top_level = {
        entry.name.removesuffix(".py")
        for entry in REPOSITORY_ROOT.iterdir()
        if entry.is_dir() or entry.suffix == ".py"
    }
    return {module for module in modules if module.split(".")[0] in top_level}


def test_package_1_modules_have_explicit_l1_layer_rules():
    declared = {rule["pattern"]: rule for rule in layer_rules()}
    for relative_path in PACKAGE_1_MODULES:
        assert relative_path in declared, f"{relative_path} has no explicit layer rule"
        assert declared[relative_path]["layer"] == "L1"
        assert declared[relative_path]["reason"].strip()


def test_explicit_rules_precede_the_generic_data_layer_default():
    # classify_module is first-match-wins, so an explicit rule placed after
    # `data_layer/*` would never fire and both modules would silently
    # become L2 infrastructure.
    generic = rule_index(GENERIC_DATA_LAYER_RULE)
    for relative_path in PACKAGE_1_MODULES:
        assert rule_index(relative_path) < generic


def test_package_1_modules_actually_resolve_to_l1():
    rules = layer_rules()
    for relative_path in PACKAGE_1_MODULES:
        assert classify_module(relative_path, rules) == "L1"


def test_generic_data_layer_default_is_still_l2_for_unlisted_modules():
    # Guards the inverse mistake: widening the new rules into a pattern that
    # promotes the whole data_layer package to L1.
    assert classify_module("data_layer/sqlite.py", layer_rules()) == "L2"
    assert classify_module("data_layer/some_future_backend.py", layer_rules()) == "L2"


def test_package_1_modules_stay_outside_the_runtime_closure():
    closure = set(compute_runtime_closure(REPOSITORY_ROOT, ENTRY_POINTS))
    for relative_path in PACKAGE_1_MODULES:
        assert relative_path not in closure, (
            f"{relative_path} became reachable from the composition root; Package 1 is "
            "contract-only and must not be wired"
        )


def test_declared_module_layers_still_cover_exactly_the_runtime_closure():
    # Adding layer rules for unwired modules must not add them to the
    # generated module_layers map, which is closure-scoped.
    architecture_map = load_architecture_map()
    closure = set(compute_runtime_closure(REPOSITORY_ROOT, ENTRY_POINTS))
    assert set(architecture_map["module_layers"]) == closure


def test_package_1_modules_have_no_upward_dependency():
    for relative_path in PACKAGE_1_MODULES:
        offenders = imported_first_party(relative_path) - ALLOWED_FIRST_PARTY_IMPORTS
        assert not offenders, f"{relative_path} gained an upward dependency: {offenders}"


def test_architecture_map_remains_valid_json_with_the_expected_shape():
    raw = json.loads((REPOSITORY_ROOT / "packaging" / "atlas_architecture_map.json").read_text(encoding="utf-8"))
    assert raw["schema_version"] == "1.0"
    for rule in raw["layer_rules"]:
        assert set(rule) == {"pattern", "layer", "reason"}
        assert rule["layer"] in raw["layers"]
