"""J: generalized, table-driven authority guard for duplicate class names.

For each tracked symbol, the table below records every file in the
repository that defines a class of that name, and classifies each
definition as one of:

- ``canonical``: the single authorized live implementation.
- ``distinct_semantic_type``: a class that happens to share the bare name
  but is a deliberately different type living in a different domain (e.g.
  intelligence-layer FusionResult vs. Phase-5 decision-layer FusionResult
  were exactly this before Package 2A's E2 rename removed the ambiguity by
  renaming the baseline type to AgentFusionResult).
- ``non_canonical_deferred``: a known duplicate that is not wired into the
  live runtime but is intentionally left in place (not quarantined) because
  removing it would break real test coverage that has not been reviewed for
  retargeting (see docs/adr/0002-atlas-os-contract-authority.md).
- ``dead_unreachable``: not part of the live runtime closure and not
  quarantined, but has zero importers reachable from main.py/web_app.py.

This test does not ban identical class names outright; it bans *undeclared*
ones (a new file defining one of these symbols must update this table, an
explicit reviewed action) and it bans more than one *live* (runtime-closure-
reachable) definition of a given symbol unless that definition is the one
marked canonical.
"""

from __future__ import annotations

import ast
import subprocess
from pathlib import Path

from tools.build_architecture_inventory import (
    REPOSITORY_ROOT,
    ENTRY_POINTS,
    compute_runtime_closure,
)

_EXCLUDED_PATH_PREFIXES = (
    "archive_unused_",
    "backups/",
    "phase1_backup_",
    "phase2_backup_",
    "phase3d_backup_",
    "phase3f_bom_backup_",
    "phase6a2_tool_backup_",
    "phase6a3_tool_backup_",
    "reports/",
)

# symbol -> {relative_path: status}
# status in {"canonical", "distinct_semantic_type", "non_canonical_deferred", "dead_unreachable"}
SYMBOL_AUTHORITIES: dict[str, dict[str, str]] = {
    "RiskEngine": {
        "core/risk_engine.py": "canonical",
    },
    "EventBus": {
        "core/event_bus.py": "canonical",
    },
    "ServiceRegistry": {
        "atlas_os/services/registry.py": "canonical",
        "atlas_os/core/service_registry.py": "non_canonical_deferred",
        "_quarantine/block2/core/service_registry.py": "dead_unreachable",
    },
    "AtlasRuntime": {
        "core/runtime.py": "canonical",
        "_quarantine/block2/atlas_runtime/runtime.py": "dead_unreachable",
    },
    "PortfolioManager": {
        "core/portfolio_manager.py": "dead_unreachable",
        "portfolio/portfolio_manager.py": "dead_unreachable",
    },
    "FusionResult": {
        "core/decision_intelligence.py": "canonical",
    },
    "AgentFusionResult": {
        "ai/core/intelligence/agent_fusion.py": "distinct_semantic_type",
    },
    "AtlasEvent": {
        "atlas_os/events/event_bus.py": "canonical",
        "core/events.py": "dead_unreachable",
    },
    "AtlasService": {
        "atlas_os/contracts.py": "canonical",
        "atlas_os/core/contracts.py": "non_canonical_deferred",
    },
    "ExecutionManager": {
        "core/execution_manager.py": "canonical",
        "_quarantine/phase1/core/execution_manager_phase6a9_4a_backup.py": "dead_unreachable",
        "_quarantine/phase1/core/execution_manager_phase6a9_4b_backup.py": "dead_unreachable",
        "_quarantine/phase1/core/execution_manager_phase7a2_backup.py": "dead_unreachable",
        "_quarantine/phase1/core/execution_manager_v30_backup.py": "dead_unreachable",
        "_quarantine/phase1/core/execution_manager_v31_0_backup.py": "dead_unreachable",
        "_quarantine/phase1/core/execution_manager_v31_1_backup.py": "dead_unreachable",
        "_quarantine/phase1/core/execution_manager_v31_1_before_runtime_state.py": "dead_unreachable",
        "_quarantine/phase1/core/execution_manager_v31_2a_backup.py": "dead_unreachable",
        "_quarantine/phase1/core/execution_manager_v31_2b_backup.py": "dead_unreachable",
        "_quarantine/phase1/core/execution_manager_v31_before_idempotency_hotfix.py": "dead_unreachable",
        "_quarantine/phase3/core/execution_manager_backup.py": "dead_unreachable",
        "_quarantine/phase3/core/execution_manager_v1_backup.py": "dead_unreachable",
        "_quarantine/phase3/core/execution_manager_v28_backup.py": "dead_unreachable",
        "_quarantine/phase3/core/execution_manager_v7_backup.py": "dead_unreachable",
        "_quarantine/phase3/core/execution_manager_v9_backup.py": "dead_unreachable",
        "_quarantine/phase3/execution_manager.py": "dead_unreachable",
    },
}


def _tracked_files() -> list[str]:
    completed = subprocess.run(
        ["git", "ls-files", "-z", "--", "*.py"],
        cwd=REPOSITORY_ROOT,
        check=True,
        capture_output=True,
    )
    return sorted(
        item.decode("utf-8").replace("\\", "/")
        for item in completed.stdout.split(b"\0")
        if item
    )


def _in_scope(relative_path: str) -> bool:
    return not any(relative_path.startswith(prefix) for prefix in _EXCLUDED_PATH_PREFIXES)


def _find_class_definitions(symbol: str, tracked_files: list[str]) -> list[str]:
    found: list[str] = []
    for relative_path in tracked_files:
        if not _in_scope(relative_path):
            continue
        source = (REPOSITORY_ROOT / relative_path).read_text(encoding="utf-8-sig")
        tree = ast.parse(source, filename=relative_path)
        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef) and node.name == symbol:
                found.append(relative_path)
                break
    return sorted(found)


def test_authority_table_matches_actual_definitions() -> None:
    tracked_files = _tracked_files()

    for symbol, table in SYMBOL_AUTHORITIES.items():
        actual = _find_class_definitions(symbol, tracked_files)
        expected = sorted(table)
        assert actual == expected, (
            f"class {symbol} definitions drifted from the authority table in "
            f"tests/architecture/test_authority_guard.py. actual={actual} "
            f"expected={expected}. A new/removed definition requires an explicit, "
            "reviewed update to this table."
        )


def test_at_most_one_canonical_definition_per_symbol() -> None:
    for symbol, table in SYMBOL_AUTHORITIES.items():
        canonical = [path for path, status in table.items() if status == "canonical"]
        assert len(canonical) <= 1, f"{symbol} has more than one canonical definition: {canonical}"


def test_only_canonical_definitions_are_live() -> None:
    closure = set(compute_runtime_closure(REPOSITORY_ROOT, ENTRY_POINTS))

    for symbol, table in SYMBOL_AUTHORITIES.items():
        live_definitions = [path for path in table if path in closure]
        non_canonical_live = [
            path for path in live_definitions if table[path] not in ("canonical", "distinct_semantic_type")
        ]
        assert non_canonical_live == [], (
            f"{symbol} has a non-canonical/deferred/dead definition that is "
            f"reachable from the live runtime: {non_canonical_live}. Either the "
            "table classification is stale or this is a live authority collision."
        )
