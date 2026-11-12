"""Regression gates for REM-001 Gate 1 deliverable 4.

`packaging/REM-001_RUNTIME_CONSTRUCTION_PATHS.md` is checked against
independently computed references, never against its own numbers:

1. Its constructor sets reproduce what
   `tests/architecture/test_composition_root_is_unique.py` asserts by a
   simpler, separately written call-name scan.
2. Every constructing module lies inside the runtime closure recorded in
   `packaging/atlas_runtime_closure.json`.
3. Regenerating from current source reproduces the committed artifact
   byte-for-byte, so a stale artifact fails rather than passing silently.
"""

from __future__ import annotations

import ast
import re

from tools.build_architecture_inventory import (
    REPOSITORY_ROOT,
    load_runtime_closure,
)
from tools.build_rem001_gate1_maps import (
    CONSTRUCTION_PATHS_PATH,
    compute_construction_map,
    render_construction_paths,
)

# The claims test_composition_root_is_unique.py enforces, restated here as an
# independent reference. If that test's expectations ever change, this gate
# must be updated deliberately rather than drifting.
_EXPECTED_CONSTRUCTORS = {
    "AtlasApplication": ["main.py"],
    "AtlasBrain": ["core/application.py"],
    "MarketLoop": ["core/application.py"],
    "ExecutionManager": ["core/application.py"],
}


def _identity_from_artifact(text: str) -> dict[str, object]:
    """Read back the artifact's own source-identity stamp.

    Rendering with the stamp the artifact already carries keeps this gate
    about whether the *analysis* still reproduces, rather than about whether
    the working tree happens to be clean while the suite runs.
    """

    def field(name: str) -> str:
        match = re.search(rf"^\| {name} \| (.+) \|$", text, re.MULTILINE)
        assert match is not None, f"artifact is missing source-identity field {name}"
        return match.group(1).strip()

    modified = field("modified_tracked_paths_at_generation")
    return {
        "generated_from_commit": field("generated_from_commit").strip("`"),
        "generated_from_tree": field("generated_from_tree").strip("`"),
        "tracked_working_tree_clean": field("tracked_working_tree_clean") == "True",
        "modified_tracked_paths_at_generation": (
            [] if modified == "none" else ast.literal_eval(modified)
        ),
    }


def test_construction_map_reproduces_composition_root_uniqueness() -> None:
    """Gate 1: independent agreement with the composition-root test."""
    data = compute_construction_map(REPOSITORY_ROOT)

    for class_name, expected in _EXPECTED_CONSTRUCTORS.items():
        observed = data["constructors_by_class"].get(class_name)
        assert observed == expected, (
            f"{class_name} is constructed by {observed}, but "
            f"tests/architecture/test_composition_root_is_unique.py requires "
            f"exactly {expected}"
        )


def test_canonical_construction_chain_is_observed() -> None:
    """ADR-0001's chain main.py -> AtlasApplication -> AtlasRuntime holds."""
    data = compute_construction_map(REPOSITORY_ROOT)

    assert data["constructors_by_class"].get("AtlasApplication") == ["main.py"]
    assert data["constructors_by_class"].get("AtlasRuntime") == ["core/application.py"]


def test_every_constructing_module_is_inside_the_runtime_closure() -> None:
    """Gate 2: independent reference is the committed closure artifact."""
    data = compute_construction_map(REPOSITORY_ROOT)
    closure = set(load_runtime_closure()["modules"])

    outside = sorted(set(data["modules_constructing"]) - closure)
    assert outside == [], (
        f"construction sites found outside packaging/atlas_runtime_closure.json: {outside}"
    )


def test_ambiguous_class_names_are_not_resolved_to_a_guess() -> None:
    """Duplicate class names stay UNKNOWN instead of being inferred."""
    data = compute_construction_map(REPOSITORY_ROOT)

    for name in data["ambiguous_class_names"]:
        assert len(data["class_definitions"][name]) > 1

    for site in data["sites"]:
        if site["class_name"] in data["ambiguous_class_names"]:
            assert site["defining_module"] == "UNKNOWN", (
                f"{site['class_name']} is defined in multiple modules and must not "
                f"be resolved to {site['defining_module']}"
            )
        else:
            assert site["defining_module"] != "UNKNOWN"


def test_committed_artifact_matches_current_source() -> None:
    """Gate 3: a stale artifact fails rather than passing silently."""
    committed = CONSTRUCTION_PATHS_PATH.read_text(encoding="utf-8")
    regenerated = render_construction_paths(
        compute_construction_map(REPOSITORY_ROOT), _identity_from_artifact(committed)
    )

    assert regenerated == committed, (
        "packaging/REM-001_RUNTIME_CONSTRUCTION_PATHS.md is out of date; "
        "regenerate with: python -m tools.build_rem001_gate1_maps construction --write"
    )
