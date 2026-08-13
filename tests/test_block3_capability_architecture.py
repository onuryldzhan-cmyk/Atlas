"""Block 3 / Package 3: architecture, bypass, and interlock guards.

Covers test classes G (no provider/tool bypass), H (research/intelligence
cannot import concrete adapters), I (M-2 third-provider interlock still
green), and J (PAPER/LIVE boundary unchanged).

Why these tests exist rather than relying on the architecture inventory
----------------------------------------------------------------------
`tools/build_architecture_inventory.py check` validates only the *runtime
closure*: the modules reachable from the composition root. The Package-3
contract modules are deliberately not imported by anything live yet, exactly
like `core/operational_contracts.py` and `core/secret_provider.py` before
them. They are therefore invisible to that check, and a forbidden import
added to one of them would not be caught by it.

These tests close that blind spot directly, by walking the imports of the
new modules themselves.
"""

from __future__ import annotations

import ast
import json
from pathlib import Path

import core.model_provider_contracts as model_contracts
import core.tool_gateway_contracts as tool_contracts

REPOSITORY_ROOT = Path(__file__).resolve().parent.parent
ARCHITECTURE_MAP = REPOSITORY_ROOT / "packaging" / "atlas_architecture_map.json"

PACKAGE_3_MODULES = (
    "core/model_provider_contracts.py",
    "core/tool_gateway_contracts.py",
)

# L1 contract modules the Package-3 modules are allowed to depend on, plus the
# L0 sanitization package. Anything else would be an upward dependency.
ALLOWED_FIRST_PARTY_IMPORTS = {
    "atlas_security",
    "core.operational_contracts",
    "core.model_provider_contracts",
}


def imported_modules(relative_path: str) -> set[str]:
    tree = ast.parse((REPOSITORY_ROOT / relative_path).read_text(encoding="utf-8"))
    modules: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            modules.add(node.module)
        elif isinstance(node, ast.Import):
            for alias in node.names:
                modules.add(alias.name)
    return modules


def first_party(modules: set[str]) -> set[str]:
    top_level = {
        entry.name.removesuffix(".py")
        for entry in REPOSITORY_ROOT.iterdir()
        if entry.is_dir() or entry.suffix == ".py"
    }
    return {module for module in modules if module.split(".")[0] in top_level}


def code_references(path: Path) -> set[str]:
    """Symbols a module actually references in code.

    Deliberately AST-based rather than a text search: these modules
    document in prose exactly which evidence/fusion symbols they avoid, and
    a substring scan would flag that documentation as a violation.
    """
    tree = ast.parse(path.read_text(encoding="utf-8", errors="ignore"))
    references: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            references.add(node.module)
            for alias in node.names:
                references.add(alias.name)
                references.add(f"{node.module}.{alias.name}")
        elif isinstance(node, ast.Import):
            for alias in node.names:
                references.add(alias.name)
        elif isinstance(node, ast.Name):
            references.add(node.id)
        elif isinstance(node, ast.Attribute):
            references.add(node.attr)
    return references


def architecture_map() -> dict:
    return json.loads(ARCHITECTURE_MAP.read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------
# G. layer discipline / no upward dependency (inventory blind spot)
# ---------------------------------------------------------------------------


def test_package_3_modules_import_only_l0_and_l1_contracts():
    for relative_path in PACKAGE_3_MODULES:
        offenders = first_party(imported_modules(relative_path)) - ALLOWED_FIRST_PARTY_IMPORTS
        assert not offenders, f"{relative_path} gained an upward dependency: {offenders}"


def test_package_3_modules_do_not_import_infrastructure_or_application():
    forbidden_prefixes = (
        "core.application", "core.execution", "core.capital_reservation",
        "core.risk_engine", "core.risk_state_store", "portfolio", "ai", "analysis",
        "atlas_os", "data_layer", "atlas_finance",
    )
    for relative_path in PACKAGE_3_MODULES:
        for module in imported_modules(relative_path):
            assert not module.startswith(forbidden_prefixes), (
                f"{relative_path} imports {module}"
            )


def test_package_3_modules_perform_no_io_or_network():
    """Contracts must not open sockets, files, or subprocesses."""
    banned = {"socket", "http", "urllib", "requests", "httpx", "subprocess", "ssl", "ftplib"}
    for relative_path in PACKAGE_3_MODULES:
        modules = {module.split(".")[0] for module in imported_modules(relative_path)}
        assert not (modules & banned), f"{relative_path} imports {modules & banned}"


def test_no_mcp_dependency_is_introduced():
    for relative_path in PACKAGE_3_MODULES:
        modules = {module.lower() for module in imported_modules(relative_path)}
        assert not any(module.startswith("mcp") for module in modules)


def test_no_provider_sdk_dependency_is_introduced():
    sdk_names = {"openai", "anthropic", "google", "cohere", "mistralai", "ollama",
                 "langchain", "transformers", "torch", "boto3"}
    for relative_path in PACKAGE_3_MODULES:
        modules = {module.split(".")[0].lower() for module in imported_modules(relative_path)}
        assert not (modules & sdk_names)


# ---------------------------------------------------------------------------
# H. intelligence cannot reach concrete adapters
# ---------------------------------------------------------------------------


def test_forbidden_edge_from_intelligence_to_infrastructure_still_exists():
    """The structural guarantee that L4 cannot import a concrete adapter.

    Concrete provider/tool adapters belong at L2. If this edge is ever
    removed, intelligence could import one directly and bypass the gateway.
    """
    edges = {(edge["from"], edge["to"]) for edge in architecture_map()["forbidden_edges"]}
    assert ("L4", "L2") in edges
    assert ("L4", "L3") in edges
    assert ("L1", "L2") in edges


def test_intelligence_layer_may_only_depend_on_stdlib_l0_and_l1():
    layers = architecture_map()["layers"]
    assert set(layers["L4"]["allowed_dependencies"]) == {"stdlib", "L0", "L1"}


def test_no_intelligence_module_imports_the_package_3_contracts_yet():
    """Foundation only: nothing consumes these contracts in this package."""
    for package in ("ai", "analysis"):
        directory = REPOSITORY_ROOT / package
        if not directory.exists():
            continue
        for path in directory.rglob("*.py"):
            text = path.read_text(encoding="utf-8", errors="ignore")
            assert "model_provider_contracts" not in text
            assert "tool_gateway_contracts" not in text


def test_no_concrete_adapter_module_exists_yet():
    """This package ships contracts only; an adapter would need L2 placement."""
    for path in (REPOSITORY_ROOT / "core").glob("*.py"):
        text = path.read_text(encoding="utf-8", errors="ignore")
        if "ToolAdapter" in text or "ModelProviderAdapter" in text:
            assert path.name in {
                "model_provider_contracts.py", "tool_gateway_contracts.py",
            }, f"{path.name} references an adapter contract outside the L1 seam"


# ---------------------------------------------------------------------------
# I. M-2 third-evidence-provider interlock
# ---------------------------------------------------------------------------


def test_package_3_produces_no_evidence_and_touches_no_fusion():
    """A governed model call must not become a third evidence source."""
    for relative_path in PACKAGE_3_MODULES:
        references = code_references(REPOSITORY_ROOT / relative_path)
        for forbidden in (
            "Evidence", "core.decision_intelligence", "decision_intelligence",
            "agent_fusion", "AgentFusion", "ConfidenceEngine",
            "model_response_to_evidence", "WorldAnalysisEngine",
        ):
            assert forbidden not in references, f"{relative_path} references {forbidden}"


def test_min_participating_agents_floor_is_untouched():
    from ai.core.intelligence.agent_fusion import AgentFusion

    assert AgentFusion.MIN_PARTICIPATING_AGENTS == 3


def test_third_evidence_providers_remain_unavailable():
    """macro/sentiment/market_risk must still have no live provider."""
    from analysis.world_analysis_engine import WorldAnalysisEngine

    engine = WorldAnalysisEngine()
    source = type(engine).__module__
    assert "world_analysis_engine" in source
    # The Package-3 contracts are not wired into the evidence path at all.
    assert not hasattr(engine, "model_gateway")
    assert not hasattr(engine, "tool_gateway")


def test_decision_intelligence_model_provider_remains_seam_only():
    """The pre-existing evidence-producing model seam gains no live caller."""
    hits = []
    for package in ("core", "ai", "analysis", "portfolio"):
        directory = REPOSITORY_ROOT / package
        if not directory.exists():
            continue
        for path in directory.rglob("*.py"):
            if path.name == "decision_intelligence.py":
                continue
            if "model_response_to_evidence" in code_references(path):
                hits.append(path.name)
    assert hits == [], f"model_response_to_evidence gained a caller: {hits}"


# ---------------------------------------------------------------------------
# J. PAPER / LIVE boundary
# ---------------------------------------------------------------------------


def test_package_3_grants_no_live_or_execution_authority():
    for relative_path in PACKAGE_3_MODULES:
        tree = ast.parse((REPOSITORY_ROOT / relative_path).read_text(encoding="utf-8"))
        names = {node.id for node in ast.walk(tree) if isinstance(node, ast.Name)} | {
            node.attr for node in ast.walk(tree) if isinstance(node, ast.Attribute)
        }
        for forbidden in (
            "AtlasApplication", "ExecutionManager", "execution_mode",
            "PaperTrader", "place_order", "submit_order",
        ):
            assert forbidden not in names, f"{relative_path} references {forbidden}"


def test_package_3_does_not_alter_execution_or_application_modules():
    """The contracts are additive; nothing in the execution path imports them."""
    for relative_path in ("core/application.py", "core/execution_manager.py"):
        text = (REPOSITORY_ROOT / relative_path).read_text(encoding="utf-8")
        assert "model_provider_contracts" not in text
        assert "tool_gateway_contracts" not in text
        assert "CapabilityGateway" not in text


def test_financial_side_effect_is_representable_but_denied_by_default():
    """FINANCIAL exists as a classification, not as an enabled capability."""
    from core.tool_gateway_contracts import (
        DEFAULT_ALLOWED_SIDE_EFFECTS,
        SideEffectClass,
    )

    assert SideEffectClass.FINANCIAL not in DEFAULT_ALLOWED_SIDE_EFFECTS
    assert SideEffectClass.SECURITY_SENSITIVE not in DEFAULT_ALLOWED_SIDE_EFFECTS
    assert SideEffectClass.EXTERNAL_WRITE not in DEFAULT_ALLOWED_SIDE_EFFECTS
    assert DEFAULT_ALLOWED_SIDE_EFFECTS == frozenset({SideEffectClass.READ_ONLY})


def test_contract_modules_are_importable_without_side_effects():
    """Importing a contract module must not construct or start anything."""
    assert model_contracts.CapabilityClass.LOCAL.value == "LOCAL"
    assert tool_contracts.SideEffectClass.READ_ONLY.value == "READ_ONLY"
