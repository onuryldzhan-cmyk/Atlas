"""Regression gates for REM-001 Gate 1 deliverable 5.

`packaging/REM-001_STATE_AUTHORITY_MAP.md` is checked against independently
computed references, never against its own numbers:

1. The durable authorities named in ADR-0003 and
   `docs/evidence/block5j_execution_authority_recovery.md` all appear in the
   composition root's declared state surface.
2. Every persistence-site module lies inside the runtime closure recorded in
   `packaging/atlas_runtime_closure.json`.
3. The artifact assigns no `state_ownership` -- the field registry v4.32
   reserves by extension.
4. Regenerating from current source reproduces the committed artifact
   byte-for-byte.

Nothing here constructs an Atlas runtime object or opens a state directory,
so the suite cannot touch durable runtime state.
"""

from __future__ import annotations

import ast
import re

from tools.build_architecture_inventory import (
    REPOSITORY_ROOT,
    load_runtime_closure,
)
from tools.build_rem001_gate1_maps import (
    RESERVED_CLASSIFICATION_FIELDS,
    STATE_AUTHORITY_MAP_PATH,
    compute_state_authority_map,
    render_state_authority_map,
)

# Durable authorities established by ADR-0003 (the three bootstrap stores) and
# by docs/evidence/block5j_execution_authority_recovery.md (the three execution
# authorities). Matched on stem, not full filename: Block 5K converted the two
# execution logs from .json to append-only .jsonl, so the evidence documents
# name the same authorities under their pre-5K extension.
_REQUIRED_AUTHORITY_STEMS = {
    # ADR-0003 bootstrap stores
    "risk_accounting_state",
    "capital_reservations",
    "execution_financial_state",
    # Block 5J execution authorities
    "execution_transaction_journal",
    "execution_idempotency",
    "execution_applied_executions",
}


def _identity_from_artifact(text: str) -> dict[str, object]:
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


def test_documented_durable_authorities_are_all_declared() -> None:
    """Gate 1: reference is ADR-0003 plus the Block 5J evidence document."""
    data = compute_state_authority_map(REPOSITORY_ROOT)

    declared_stems = {
        value.rsplit("/", 1)[-1].split(".", 1)[0]
        for value in data["declared_state_files"].values()
    }

    missing = sorted(_REQUIRED_AUTHORITY_STEMS - declared_stems)
    assert missing == [], (
        "durable authorities named in ADR-0003 / block5j are absent from the "
        f"composition root's declared state surface: {missing}"
    )


def test_every_persistence_site_is_inside_the_runtime_closure() -> None:
    """Gate 2: independent reference is the committed closure artifact."""
    data = compute_state_authority_map(REPOSITORY_ROOT)
    closure = set(load_runtime_closure()["modules"])

    outside = sorted(set(data["modules_with_persistence_sites"]) - closure)
    assert outside == [], (
        f"persistence sites found outside packaging/atlas_runtime_closure.json: {outside}"
    )


def test_artifact_assigns_no_state_ownership() -> None:
    """Gate 3: the reserved fields are declared absent, not populated."""
    text = STATE_AUTHORITY_MAP_PATH.read_text(encoding="utf-8")

    assert "state_ownership" in RESERVED_CLASSIFICATION_FIELDS

    absent_section = text.split("## Classification fields deliberately absent", 1)
    assert len(absent_section) == 2, "artifact must declare its absent fields"

    for field in RESERVED_CLASSIFICATION_FIELDS:
        assert f"- `{field}`" in absent_section[1], (
            f"reserved field {field} is not declared deliberately absent"
        )


def test_declared_surface_is_parsed_not_transcribed() -> None:
    """Every declared constant resolves to a real state-file suffix."""
    data = compute_state_authority_map(REPOSITORY_ROOT)

    assert data["declared_state_files"], "composition root declares no state files"
    for constant, value in data["declared_state_files"].items():
        assert constant.isupper()
        assert value.endswith((".json", ".jsonl"))


def test_committed_artifact_matches_current_source() -> None:
    """Gate 4: a stale artifact fails rather than passing silently."""
    committed = STATE_AUTHORITY_MAP_PATH.read_text(encoding="utf-8")
    regenerated = render_state_authority_map(
        compute_state_authority_map(REPOSITORY_ROOT), _identity_from_artifact(committed)
    )

    assert regenerated == committed, (
        "packaging/REM-001_STATE_AUTHORITY_MAP.md is out of date; "
        "regenerate with: python -m tools.build_rem001_gate1_maps state --write"
    )
