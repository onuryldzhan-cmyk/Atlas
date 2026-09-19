"""Static guard for the ``research/`` boundary invariant (ADR-0009).

``research/__init__.py`` promises that the package "contains no strategy, no
signal, no data acquisition, and no connection to the Atlas runtime". That is
strictly stronger than the L4 layer rule, which would permit ``research/`` to
import any L0 or L1 module. ADR-0009 settles the stronger reading: ``research/``
imports nothing first-party outside ``research/`` at all -- not even
``data_layer/contracts.py``, whose ``ClaimSource`` the L4 module
``ai/core/atlas_brain.py`` legitimately imports.

This file is the only thing that enforces that invariant today.
``tools/build_architecture_inventory.py`` cannot: ``compute_module_layers``
iterates the runtime closure, ``research/**`` is reachable from no entry point,
and ``find_forbidden_edges`` skips any module with no layer assignment. A green
architecture check is therefore silence about ``research/``, not approval of it.

Three deliberate differences from ``find_forbidden_edges``:

* ``TYPE_CHECKING``-guarded imports are **not** exempt here. The invariant is
  about declared coupling, not only about what executes at runtime.
* Constant-string dynamic imports (``importlib.import_module("x")``,
  ``__import__("x")``) are checked too. They remain invisible to
  ``find_forbidden_edges``; here they are cheap to catch and would otherwise be
  the obvious way around this guard.
* Ancestor-package edges are irrelevant, because no first-party package outside
  ``research/`` may be named at all. This is why ADR-0009 chose this boundary:
  it keeps ``research/`` out of the still-open ancestor-edge gap recorded in
  commit 1ac3a64, rather than growing it.

A dynamic import built from a computed (non-constant) string is still invisible,
as it is to every static checker in this repository. That residual gap is
recorded in ADR-0009 rather than papered over.
"""

from __future__ import annotations

import ast
import json
from pathlib import Path

import pytest

from tools.build_architecture_inventory import classify_module

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
RESEARCH_ROOT = REPOSITORY_ROOT / "research"
RESEARCH_PACKAGE = "research"

#: Directories at the repository root that never hold first-party source.
_NON_SOURCE_DIRECTORIES = frozenset({"__pycache__", "node_modules"})

#: Reported instead of a module name when a relative import would climb above
#: the package the importing file lives in.
_ESCAPES = "<escapes-package>"


def _first_party_root_names() -> frozenset[str]:
    """Top-level importable names that belong to this repository.

    Detected from the working-tree filesystem rather than hard-coded, so a newly
    added package is covered automatically. Two deliberate choices:

    * A directory counts whether or not it holds a ``.py`` file and whether or
      not it has an ``__init__.py``. ``ai/`` is a namespace package with no
      ``__init__.py``; ``config/``, ``database/`` and ``learning/`` are named in
      CLAUDE.md's directory map but currently hold only data, and under PEP 420
      ``import config`` still succeeds. Requiring Python content would let those
      names through.
    * The working tree is used rather than ``git ls-files`` (which
      ``tools/build_architecture_inventory.py`` uses for its own purposes), so
      untracked scratch directories are included too.

    Both choices only ever *add* names to the forbidden set, so they can make
    this guard stricter and never weaker. ``research/`` is entitled to import no
    first-party name at all, so over-inclusion costs nothing.
    """

    names: set[str] = set()
    for entry in REPOSITORY_ROOT.iterdir():
        if entry.name.startswith("."):
            continue
        if entry.is_file() and entry.suffix == ".py":
            names.add(entry.stem)
        elif entry.is_dir() and entry.name not in _NON_SOURCE_DIRECTORIES:
            names.add(entry.name)
    return frozenset(names)


def _research_modules() -> list[Path]:
    return sorted(
        path
        for path in RESEARCH_ROOT.rglob("*.py")
        if "__pycache__" not in path.parts
    )


def _imported_root_names(relative_path: str, source: str) -> list[tuple[str, int]]:
    """Return ``(root_module_name, lineno)`` for every import in ``source``.

    Relative imports resolve to the package the importing file lives in. One
    that would climb above that package is reported under ``_ESCAPES`` so it
    can never pass silently.
    """

    package_parts = Path(relative_path).parts[:-1]
    tree = ast.parse(source, filename=relative_path)
    found: list[tuple[str, int]] = []

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                found.append((alias.name.split(".")[0], node.lineno))
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                if node.level > len(package_parts):
                    found.append((_ESCAPES, node.lineno))
                else:
                    base = package_parts[: len(package_parts) - (node.level - 1)]
                    found.append((base[0] if base else _ESCAPES, node.lineno))
            elif node.module:
                found.append((node.module.split(".")[0], node.lineno))
        elif isinstance(node, ast.Call):
            dynamic = _dynamic_import_target(node)
            if dynamic is not None:
                found.append((dynamic.split(".")[0], node.lineno))

    return found


def _dynamic_import_target(node: ast.Call) -> str | None:
    """The module name of ``import_module("x")`` / ``__import__("x")``, if any.

    Only a constant first argument can be resolved. A name built at runtime is
    beyond any static checker here, and ADR-0009 records that residual gap.
    """

    func = node.func
    is_import_call = (
        isinstance(func, ast.Attribute) and func.attr == "import_module"
    ) or (isinstance(func, ast.Name) and func.id in {"import_module", "__import__"})
    if not is_import_call or not node.args:
        return None

    first = node.args[0]
    if isinstance(first, ast.Constant) and isinstance(first.value, str):
        return first.value
    return None


def _violations(relative_path: str, source: str) -> list[str]:
    first_party = _first_party_root_names()
    out: list[str] = []
    for root, lineno in _imported_root_names(relative_path, source):
        if root == RESEARCH_PACKAGE:
            continue
        if root == _ESCAPES or root in first_party:
            out.append(f"{relative_path}:{lineno} imports first-party {root!r}")
    return out


# ---------------------------------------------------------------------------
# The invariant
# ---------------------------------------------------------------------------


def test_research_modules_exist_to_be_checked() -> None:
    """Guard against the suite passing because it found nothing to inspect."""

    modules = _research_modules()
    assert len(modules) >= 5, modules
    names = {path.name for path in modules}
    assert {
        "__init__.py",
        "hypothesis_registry.py",
        "lifecycle.py",
        "multiple_testing.py",
        "splitting.py",
    } <= names


@pytest.mark.parametrize(
    "module_path",
    _research_modules(),
    ids=lambda path: path.name,
)
def test_research_module_imports_nothing_first_party_outside_research(
    module_path: Path,
) -> None:
    relative_path = module_path.relative_to(REPOSITORY_ROOT).as_posix()
    source = module_path.read_text(encoding="utf-8-sig")

    violations = _violations(relative_path, source)

    assert not violations, (
        "research/ must import nothing first-party outside research/ "
        "(ADR-0009). Offending imports:\n  " + "\n  ".join(violations)
    )


def test_detector_flags_a_forbidden_import() -> None:
    """The detector must be able to fail, or the guard above proves nothing."""

    contracts = _violations(
        "research/hypothesis_registry.py",
        "from data_layer.contracts import ClaimSource\n",
    )
    assert contracts and "data_layer" in contracts[0]

    store = _violations(
        "research/hypothesis_registry.py",
        "import data_layer.evidence_store\n",
    )
    assert store and "data_layer" in store[0]

    type_checked = _violations(
        "research/hypothesis_registry.py",
        "from typing import TYPE_CHECKING\n"
        "if TYPE_CHECKING:\n"
        "    from core.application import AtlasApplication\n",
    )
    assert type_checked and "core" in type_checked[0], (
        "TYPE_CHECKING-guarded first-party imports are deliberately not exempt"
    )

    escaping = _violations(
        "research/hypothesis_registry.py",
        "from .. import core\n",
    )
    assert escaping and _ESCAPES in escaping[0]

    dynamic = _violations(
        "research/hypothesis_registry.py",
        "import importlib\n"
        'store = importlib.import_module("data_layer.evidence_store")\n',
    )
    assert dynamic and "data_layer" in dynamic[0], (
        "a constant-string dynamic import is the obvious way around this guard"
    )

    builtin_dynamic = _violations(
        "research/hypothesis_registry.py",
        '__import__("core.application")\n',
    )
    assert builtin_dynamic and "core" in builtin_dynamic[0]

    data_only_package = _violations(
        "research/hypothesis_registry.py",
        "import config\n",
    )
    assert data_only_package and "config" in data_only_package[0], (
        "config/ holds no .py today but is importable under PEP 420"
    )

    allowed = _violations(
        "research/hypothesis_registry.py",
        "import json\n"
        "from research.lifecycle import HypothesisState\n"
        "from .splitting import SplitSpec\n",
    )
    assert allowed == []


def test_first_party_detection_covers_namespace_and_data_only_packages() -> None:
    """Neither an ``__init__.py`` nor any ``.py`` may be required for detection.

    ``ai/`` is a namespace package with no ``__init__.py``. ``config/``,
    ``database/`` and ``learning/`` are in CLAUDE.md's directory map and hold
    only data today, yet remain importable under PEP 420.
    """

    first_party = _first_party_root_names()
    for expected in (
        "ai",
        "core",
        "data_layer",
        "research",
        "analysis",
        "config",
        "database",
        "learning",
    ):
        assert expected in first_party, expected
    assert "json" not in first_party
    assert "pytest" not in first_party


# ---------------------------------------------------------------------------
# The two compensating controls this decision rests on (ADR-0009)
# ---------------------------------------------------------------------------


def test_architecture_map_classifies_research_as_l4() -> None:
    """C1: the classification is recorded before research/ is ever wired in."""

    architecture_map = json.loads(
        (REPOSITORY_ROOT / "packaging" / "atlas_architecture_map.json").read_text(
            encoding="utf-8"
        )
    )
    rules = [
        rule
        for rule in architecture_map["layer_rules"]
        if rule["pattern"] == "research/*"
    ]
    assert len(rules) == 1, "exactly one research/* layer rule is expected"
    assert rules[0]["layer"] == "L4"

    # Pin the resolved classification, not merely the rule's presence:
    # classify_module is first-match-wins, so a rule inserted ahead of this one
    # could change the effective layer while the assertions above stayed green.
    for module in (
        "research/__init__.py",
        "research/hypothesis_registry.py",
        "research/sub/deep/module.py",
    ):
        assert classify_module(module, architecture_map["layer_rules"]) == "L4", module


def test_research_is_absent_from_the_runtime_closure() -> None:
    """W1: research/ is deliberately not reachable from any entry point.

    Wiring it in is the W2 decision ADR-0009 defers. Doing so makes this fail,
    which is the intent: it forces the architecture artifacts to be regenerated
    and the wiring decision to be taken explicitly rather than by drift.
    """

    closure = json.loads(
        (REPOSITORY_ROOT / "packaging" / "atlas_runtime_closure.json").read_text(
            encoding="utf-8"
        )
    )
    reachable = [
        module
        for module in closure["modules"]
        if module.split("/")[0] == RESEARCH_PACKAGE
    ]
    assert reachable == [], (
        "research/ entered the runtime closure. That is the W2 step deferred by "
        "ADR-0009: regenerate the architecture artifacts and take the wiring "
        f"decision explicitly. Reachable: {reachable}"
    )
