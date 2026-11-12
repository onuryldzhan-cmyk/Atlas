"""Architecture boundary for Experiment Manager v1 (GRANT-EXPMGR-V1-RESEARCH-ONLY).

Registry v5.86 grants the Experiment Manager research-only scope:

* allowed:   experiment_manager -> research/* (hypothesis registry, lifecycle,
             multiple testing). Evidence arrives as plain data; under ADR-0009
             research/ may not import ``data_layer`` (evidence_store) at all.
* forbidden: experiment_manager -> RiskEngine, ExecutionManager, capital /
             portfolio state, order path, runtime decision path -- directly
             or through any chain of first-party imports.
* forbidden: any runtime module -> experiment_manager (one-way dependency;
             no runtime module reads its output, and research/ stays out of
             the runtime closure -- W2 is not applied).

Three independent checks: a static transitive import graph, a live import in
a clean interpreter (catches what static parsing misses), and the reverse
edge scan.
"""

from __future__ import annotations

import ast
import json
import subprocess
import sys
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
MODULE = "research.experiment_manager"
MODULE_PATH = REPOSITORY_ROOT / "research" / "experiment_manager.py"

#: First-party module prefixes the manager may never reach, directly or
#: transitively. Named for the authorities v5.86 places out of scope.
FORBIDDEN_PREFIXES: tuple[str, ...] = (
    "core.risk_engine",  # RiskEngine
    "core.execution_manager",  # ExecutionManager
    "core.application",  # runtime composition root
    "core.market_loop",  # runtime decision / order loop
    "core.research_evidence_bridge",  # W2 bridge (not applied)
    "core.experiment_ledger",  # runtime EXP-00x admission ledger
    "ai",  # runtime brain / decision path
    "execution",  # order path
    "risk",  # risk package
    "data_layer",  # ADR-0009: research/ imports no data_layer
    "database",
    "memory",  # old JSON memory systems
    "learning",
    "events",
)

#: Substrings that mark capital / portfolio / order modules wherever they live.
FORBIDDEN_SUBSTRINGS: tuple[str, ...] = (
    "portfolio",
    "capital",
    "order",
    "execution",
    "risk_engine",
    "broker",
    "exchange",
)


def _module_file(dotted: str) -> Path | None:
    base = REPOSITORY_ROOT.joinpath(*dotted.split("."))
    for candidate in (base.with_suffix(".py"), base / "__init__.py"):
        if candidate.is_file():
            return candidate
    return None


def _first_party_imports(path: Path, dotted: str) -> set[str]:
    """Every first-party dotted name ``path`` imports, TYPE_CHECKING included."""

    is_package = path.name == "__init__.py"
    package = dotted if is_package else dotted.rpartition(".")[0]
    tree = ast.parse(path.read_text(encoding="utf-8-sig"), filename=str(path))
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                parts = package.split(".")
                base = ".".join(parts[: len(parts) - (node.level - 1)])
                target = f"{base}.{node.module}" if node.module else base
            else:
                target = node.module or ""
            names.add(target)
            for alias in node.names:
                names.add(f"{target}.{alias.name}")
        elif isinstance(node, ast.Call):
            func = node.func
            dynamic = (
                isinstance(func, ast.Attribute) and func.attr == "import_module"
            ) or (isinstance(func, ast.Name) and func.id in {"import_module", "__import__"})
            if dynamic and node.args and isinstance(node.args[0], ast.Constant):
                names.add(str(node.args[0].value))
    return {name for name in names if name and _module_file(name) is not None}


def _transitive_closure(root: str) -> set[str]:
    seen: set[str] = set()
    stack = [root]
    while stack:
        dotted = stack.pop()
        if dotted in seen:
            continue
        path = _module_file(dotted)
        if path is None:
            continue
        seen.add(dotted)
        # Importing a submodule executes its parent packages' __init__.
        parts = dotted.split(".")
        for i in range(1, len(parts)):
            stack.append(".".join(parts[:i]))
        stack.extend(_first_party_imports(path, dotted))
    return seen


def _forbidden(dotted: str) -> bool:
    if any(dotted == p or dotted.startswith(p + ".") for p in FORBIDDEN_PREFIXES):
        return True
    return any(token in dotted for token in FORBIDDEN_SUBSTRINGS)


def test_experiment_manager_module_exists() -> None:
    assert MODULE_PATH.is_file(), "research/experiment_manager.py is the granted boundary"


def test_transitive_import_graph_stays_inside_research() -> None:
    closure = _transitive_closure(MODULE)
    assert MODULE in closure
    outside = sorted(m for m in closure if m.split(".")[0] != "research")
    assert outside == [], f"experiment manager reaches outside research/: {outside}"
    hits = sorted(m for m in closure if _forbidden(m))
    assert hits == [], f"experiment manager reaches forbidden modules: {hits}"


def test_live_import_loads_no_runtime_authority() -> None:
    """Import in a clean interpreter and inspect what actually got loaded."""

    code = (
        "import json, sys\n"
        f"import {MODULE}\n"
        "print(json.dumps(sorted(sys.modules)))\n"
    )
    out = subprocess.run(
        [sys.executable, "-c", code],
        cwd=REPOSITORY_ROOT,
        capture_output=True,
        text=True,
        check=True,
    )
    loaded = json.loads(out.stdout.strip().splitlines()[-1])
    first_party_roots = {
        entry.name if entry.is_dir() else entry.stem
        for entry in REPOSITORY_ROOT.iterdir()
        if not entry.name.startswith(".")
        and (entry.is_dir() or entry.suffix == ".py")
    }
    first_party_loaded = sorted(
        m for m in loaded if m.split(".")[0] in first_party_roots
    )
    outside = [m for m in first_party_loaded if m.split(".")[0] != "research"]
    assert outside == [], f"live import pulled in runtime modules: {outside}"


def test_no_runtime_module_imports_the_experiment_manager() -> None:
    """One-way dependency: no first-party module outside research/ and tests/
    imports it.

    Checked on the import graph, not on text: the string "experiment_manager"
    already names an org-model agent role (atlas_org/permissions.py,
    observability/, tools/agent_cycle.py). That label is unrelated to this
    module and is reported, not treated as an edge.
    """

    offenders: list[str] = []
    skip_dirs = {"research", "tests", "__pycache__", "node_modules", "venv"}
    for path in REPOSITORY_ROOT.rglob("*.py"):
        rel = path.relative_to(REPOSITORY_ROOT)
        if rel.parts[0] in skip_dirs or rel.parts[0].startswith("archive_unused_") or any(
            part.startswith(".") or part in skip_dirs for part in rel.parts
        ):
            continue
        dotted = ".".join(rel.with_suffix("").parts)
        if dotted.endswith(".__init__"):
            dotted = dotted[: -len(".__init__")]
        try:
            imports = _first_party_imports(path, dotted)
        except (SyntaxError, UnicodeDecodeError, OSError) as exc:
            offenders.append(f"{rel.as_posix()}: unparseable ({type(exc).__name__})")
            continue
        if any(name == MODULE or name.startswith(MODULE + ".") for name in imports):
            offenders.append(rel.as_posix())
    assert offenders == [], f"runtime code imports {MODULE}: {offenders}"


def test_experiment_manager_absent_from_runtime_closure() -> None:
    closure = json.loads(
        (REPOSITORY_ROOT / "packaging" / "atlas_runtime_closure.json").read_text(
            encoding="utf-8"
        )
    )
    assert not [m for m in closure["modules"] if "experiment_manager" in m]


def test_detector_can_fail() -> None:
    """The forbidden-module predicate must recognise each named authority."""

    for dotted in (
        "core.risk_engine",
        "core.execution_manager",
        "core.application",
        "core.market_loop",
        "core.research_evidence_bridge",
        "data_layer.evidence_store",
        "ai.core.atlas_brain",
        "core.portfolio_state",
        "core.capital_reservation",
        "core.order_router",
    ):
        assert _forbidden(dotted), dotted
    for dotted in ("research.hypothesis_registry", "research.lifecycle"):
        assert not _forbidden(dotted), dotted
    # The real runtime root must be visibly outside research/ by this walker.
    assert any(
        m.split(".")[0] != "research" for m in _transitive_closure("core.application")
    )
