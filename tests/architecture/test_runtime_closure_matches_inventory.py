"""D4 / S6: recompute the static runtime closure and compare it to the
checked-in artifact.

A module entering or leaving the live runtime must require an explicit,
reviewed update to packaging/atlas_runtime_closure.json (via
``python tools/build_architecture_inventory.py closure --write``); it must
never happen silently.
"""

from __future__ import annotations

from tools.build_architecture_inventory import (
    REPOSITORY_ROOT,
    ENTRY_POINTS,
    compute_runtime_closure,
    load_runtime_closure,
)


def test_runtime_closure_matches_inventory() -> None:
    checked_in = load_runtime_closure()
    assert list(checked_in["entry_points"]) == list(ENTRY_POINTS)

    computed = compute_runtime_closure(REPOSITORY_ROOT, ENTRY_POINTS)
    checked_in_modules = list(checked_in["modules"])

    missing = sorted(set(computed) - set(checked_in_modules))
    extra = sorted(set(checked_in_modules) - set(computed))

    assert computed == checked_in_modules, (
        "runtime closure drifted from packaging/atlas_runtime_closure.json. "
        f"newly reachable (missing from checked-in file): {missing}; "
        f"no longer reachable (stale in checked-in file): {extra}. "
        "Regenerate with: python tools/build_architecture_inventory.py closure --write"
    )


def test_runtime_closure_recomputation_is_deterministic() -> None:
    first = compute_runtime_closure(REPOSITORY_ROOT, ENTRY_POINTS)
    second = compute_runtime_closure(REPOSITORY_ROOT, ENTRY_POINTS)
    assert first == second
