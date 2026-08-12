"""D1: every live first-party module has exactly one declared architecture layer."""

from __future__ import annotations

from tools.build_architecture_inventory import (
    REPOSITORY_ROOT,
    ENTRY_POINTS,
    compute_module_layers,
    compute_runtime_closure,
    load_architecture_map,
)


def test_layer_assignment_is_total() -> None:
    architecture_map = load_architecture_map()
    closure = compute_runtime_closure(REPOSITORY_ROOT, ENTRY_POINTS)

    assigned, unassigned = compute_module_layers(closure, architecture_map["layer_rules"])

    assert unassigned == [], (
        "the following live modules have no matching layer_rules entry in "
        f"packaging/atlas_architecture_map.json: {unassigned}"
    )
    assert set(assigned) == set(closure)

    valid_layers = set(architecture_map["layers"])
    for module, layer in assigned.items():
        assert layer in valid_layers, f"{module} assigned unknown layer {layer!r}"

    # Every module gets exactly one layer: compute_module_layers uses
    # first-match-wins over an ordered rule list, so a dict result already
    # guarantees this, but assert the checked-in map agrees.
    assert architecture_map["module_layers"] == assigned, (
        "packaging/atlas_architecture_map.json module_layers is stale; "
        "regenerate with: python tools/build_architecture_inventory.py map --write"
    )
