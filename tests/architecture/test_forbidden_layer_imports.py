"""D2: no forbidden dependency edge exists between architecture layers."""

from __future__ import annotations

from tools.build_architecture_inventory import (
    REPOSITORY_ROOT,
    ENTRY_POINTS,
    compute_module_layers,
    compute_runtime_closure,
    find_forbidden_edges,
    load_architecture_map,
)


def test_forbidden_layer_imports() -> None:
    architecture_map = load_architecture_map()
    closure = compute_runtime_closure(REPOSITORY_ROOT, ENTRY_POINTS)

    assigned, unassigned = compute_module_layers(closure, architecture_map["layer_rules"])
    assert unassigned == [], f"cannot check forbidden edges: unassigned modules {unassigned}"

    violations = find_forbidden_edges(
        REPOSITORY_ROOT,
        closure,
        assigned,
        architecture_map["forbidden_edges"],
        architecture_map.get("permitted_exceptions", []),
    )

    assert violations == [], (
        "forbidden dependency edges detected (see packaging/atlas_architecture_map.json "
        f"forbidden_edges / permitted_exceptions): {violations}"
    )
