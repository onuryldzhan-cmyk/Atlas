"""Runtime guard: ``data_layer/__init__.py`` must not load L2 infrastructure.

Registry v4.39 (GRANT-ANCESTOR-INIT-RECLASSIFICATION) reclassifies
``data_layer/__init__.py`` from L2 to L1 on the evidence that its re-exports are
PEP 562 lazy, so importing the package - or any L1 submodule of it, which
executes the package ``__init__`` first - loads no L2 module at all.

That reclassification is **not self-enforcing**, which is why this file is a
binding condition of the grant rather than an optional extra. The static
forbidden-edge detector in ``tools/build_architecture_inventory`` resolves
imports by walking ``ast.Import`` and ``ast.ImportFrom`` nodes. The lazy
re-exports here go through ``importlib.import_module`` on *string* module names,
which is neither node type, so the detector is structurally blind to them. A
future change that reached ``data_layer.sqlite`` through an importlib string at
import time would restore real L1 -> L2 coupling - and, through
``ai/core/atlas_brain.py``, real L4 -> L2 coupling across the
research-cannot-trade boundary - while the architecture gate kept reporting
green.

The compensating check therefore has to observe what the interpreter actually
loads, not what the source text appears to say. Every assertion below is taken
from a **clean subprocess interpreter**, diffing ``sys.modules`` against that
subprocess's own baseline, so that modules already imported by the pytest
process cannot mask or pre-satisfy the result.

The forbidden set is derived from ``packaging/atlas_architecture_map.json`` at
test time rather than hardcoded, so an L2 module added to ``data_layer/``
tomorrow is covered without anyone remembering to update this file.
"""

from __future__ import annotations

import json
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

from tools.build_architecture_inventory import (
    REPOSITORY_ROOT,
    classify_module,
    load_architecture_map,
)

# Layers whose infrastructure an L1 package marker must not pull in. L3+ is
# included for completeness: nothing under data_layer/ is classified there
# today, but the guard should not quietly stop covering it if something is.
FORBIDDEN_LAYERS = frozenset({"L2", "L3", "L4", "L5"})

# Probe script for the clean-interpreter measurement. json and importlib are
# imported *before* the baseline snapshot so they do not appear in the diff.
_PROBE = textwrap.dedent(
    """
    import importlib
    import json
    import sys

    sys.path.insert(0, sys.argv[1])
    baseline = set(sys.modules)
    importlib.import_module(sys.argv[2])
    print(json.dumps(sorted(set(sys.modules) - baseline)))
    """
)


def _modules_loaded_by_importing(sys_path_entry: Path, dotted: str) -> set[str]:
    """Return the module names importing ``dotted`` adds, in a fresh interpreter."""

    completed = subprocess.run(
        [sys.executable, "-c", _PROBE, str(sys_path_entry), dotted],
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    assert completed.returncode == 0, (
        f"probe interpreter failed importing {dotted!r}\n"
        f"stdout: {completed.stdout}\nstderr: {completed.stderr}"
    )
    return set(json.loads(completed.stdout))


def _forbidden_data_layer_modules() -> set[str]:
    """Dotted names of every ``data_layer`` module the architecture map puts at L2+.

    Derived by applying ``layer_rules`` to the files actually on disk rather
    than by reading ``module_layers``: that table covers only the runtime
    closure, and ``data_layer/config.py`` and ``data_layer/sqlite.py`` - the two
    L2 modules the lazy ``__getattr__`` references - are outside it. Reading the
    table would therefore have produced a guard that was blind to exactly the
    modules it exists to guard against.
    """

    layer_rules = load_architecture_map()["layer_rules"]
    forbidden: set[str] = set()

    for path in sorted((REPOSITORY_ROOT / "data_layer").rglob("*.py")):
        relative = path.relative_to(REPOSITORY_ROOT).as_posix()
        if relative.endswith("/__init__.py") or relative == "data_layer/__init__.py":
            continue
        if classify_module(relative, layer_rules) in FORBIDDEN_LAYERS:
            forbidden.add(relative[: -len(".py")].replace("/", "."))

    return forbidden


# ---------------------------------------------------------------------------
# The guard's own premise
# ---------------------------------------------------------------------------


def test_forbidden_module_set_is_not_vacuous() -> None:
    """A guard that forbids nothing passes for free. Prove the set has teeth."""

    forbidden = _forbidden_data_layer_modules()

    assert forbidden, (
        "no data_layer module classified L2 or higher was derived from the "
        "architecture map; every assertion in this file would pass vacuously"
    )
    # These three are the L2 targets data_layer/__init__.py's own
    # _LAZY_ATTRIBUTES table names. If the derivation stops covering them the
    # guard has silently stopped guarding the thing it was written for.
    for expected in ("data_layer.config", "data_layer.models", "data_layer.sqlite"):
        if expected == "data_layer.models":
            # models.py is an explicit L1 exception in the map, so it is
            # legitimately absent. Asserting its absence pins that fact.
            assert expected not in forbidden, (
                "data_layer.models is classified L1 in the architecture map; "
                "if it is now L2 this guard's premise has changed"
            )
        else:
            assert expected in forbidden, (
                f"{expected} is an L2 target of the lazy __getattr__ table but was "
                f"not derived as forbidden; derived set was {sorted(forbidden)}"
            )


# ---------------------------------------------------------------------------
# The real invariant
# ---------------------------------------------------------------------------


def test_importing_data_layer_package_loads_no_l2_module() -> None:
    loaded = _modules_loaded_by_importing(REPOSITORY_ROOT, "data_layer")
    leaked = loaded & _forbidden_data_layer_modules()

    assert leaked == set(), (
        "importing data_layer eagerly loaded L2 infrastructure: "
        f"{sorted(leaked)}. data_layer/__init__.py is classified L1 in "
        "packaging/atlas_architecture_map.json on the evidence that its "
        "re-exports are PEP 562 lazy; that classification is now false."
    )


def _permitted_targets_for(importer_dotted: str) -> set[str]:
    """Dotted targets ``importer_dotted`` is allowed to reach by the map's own exceptions.

    ``data_layer/canonical_evidence.py`` legitimately imports
    ``data_layer/projection_replay.py``; that edge is a pre-existing entry in
    ``permitted_exceptions`` and predates this guard entirely. Subtracting it
    here keeps the guard measuring what it claims to measure - whether
    ``data_layer/__init__.py`` drags L2 in as a side effect - rather than
    re-litigating an edge the architecture map has already disposed of. The set
    is read from the map, so revoking that exception tightens this guard
    automatically.
    """

    permitted: set[str] = set()
    for exception in load_architecture_map().get("permitted_exceptions", []):
        source = exception["from"]
        if source[: -len(".py")].replace("/", ".") == importer_dotted:
            permitted.add(exception["to"][: -len(".py")].replace("/", "."))
    return permitted


@pytest.mark.parametrize(
    "l1_submodule",
    ["data_layer.contracts", "data_layer.models", "data_layer.canonical_evidence"],
)
def test_importing_an_l1_submodule_loads_no_l2_module(l1_submodule: str) -> None:
    """Importing an L1 submodule executes the package __init__ on the way in."""

    loaded = _modules_loaded_by_importing(REPOSITORY_ROOT, l1_submodule)
    allowed = {l1_submodule} | _permitted_targets_for(l1_submodule)
    leaked = loaded & (_forbidden_data_layer_modules() - allowed)

    assert leaked == set(), (
        f"importing the L1 module {l1_submodule} pulled in L2 infrastructure "
        f"{sorted(leaked)} that neither the module itself nor any "
        "permitted_exception accounts for, so it arrived as a side effect of "
        "executing data_layer/__init__.py"
    )


def test_lazy_attribute_access_still_resolves() -> None:
    """Laziness must defer the import, not break it.

    Without this, the guard above could be satisfied by a __init__.py that had
    stopped re-exporting anything at all, which would pass the layering check by
    removing the feature rather than by keeping it lazy.
    """

    probe = textwrap.dedent(
        """
        import json, sys
        sys.path.insert(0, sys.argv[1])
        import data_layer
        loaded_before = "data_layer.sqlite" in sys.modules
        resolved = data_layer.SQLiteStorage
        print(json.dumps({
            "loaded_before_access": loaded_before,
            "loaded_after_access": "data_layer.sqlite" in sys.modules,
            "resolved": resolved is not None,
        }))
        """
    )
    completed = subprocess.run(
        [sys.executable, "-c", probe, str(REPOSITORY_ROOT)],
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    assert completed.returncode == 0, completed.stderr
    result = json.loads(completed.stdout)

    assert result["loaded_before_access"] is False, "data_layer.sqlite was loaded eagerly"
    assert result["loaded_after_access"] is True, "attribute access did not import the backend"
    assert result["resolved"] is True, "lazy re-export resolved to nothing"


# ---------------------------------------------------------------------------
# Discrimination proof
#
# A passing test is not evidence until it has been shown to fail against the
# behaviour it forbids. These build the regressed shapes as synthetic packages
# in tmp_path and run the *same* measurement against them. The real
# data_layer/__init__.py is never modified: it is the evidence the
# reclassification rests on, and mutating it to manufacture a failure would be a
# worse instrument than the gap being closed.
# ---------------------------------------------------------------------------

_FIXTURE_SQLITE = "VALUE = 'l2 backend loaded'\n"

_FIXTURE_LAZY_INIT = textwrap.dedent(
    """
    import importlib
    from typing import Any

    _LAZY = {"Storage": ("__PKG__.sqlite", "VALUE")}

    def __getattr__(name: str) -> Any:
        target = _LAZY.get(name)
        if target is None:
            raise AttributeError(name)
        module_name, attribute_name = target
        return getattr(importlib.import_module(module_name), attribute_name)
    """
)

_FIXTURE_EAGER_INIT = "from __PKG__.sqlite import VALUE as Storage\n"

_FIXTURE_IMPORTLIB_STRING_INIT = textwrap.dedent(
    """
    import importlib

    # The detector-blind regression: a string module name resolved at import
    # time. No ast.Import or ast.ImportFrom node exists for this.
    Storage = getattr(importlib.import_module("__PKG__.sqlite"), "VALUE")
    """
)


def _build_fixture_package(tmp_path: Path, name: str, init_source: str) -> Path:
    package = tmp_path / name
    package.mkdir()
    (package / "__init__.py").write_text(
        init_source.replace("__PKG__", name), encoding="utf-8"
    )
    (package / "sqlite.py").write_text(_FIXTURE_SQLITE, encoding="utf-8")
    (package / "contracts.py").write_text("CONTRACT = object()\n", encoding="utf-8")
    return package


@pytest.mark.parametrize(
    ("label", "init_source"),
    [
        ("eager_from_import", _FIXTURE_EAGER_INIT),
        ("dynamic_importlib_string", _FIXTURE_IMPORTLIB_STRING_INIT),
    ],
)
def test_check_fails_against_a_regressed_init(
    tmp_path: Path, label: str, init_source: str
) -> None:
    """The measurement must actually catch both regression shapes.

    ``dynamic_importlib_string`` is the case that motivates this whole file: it
    is invisible to the static detector, so if the runtime measurement did not
    catch it, nothing in the repository would.
    """

    package_name = f"fixture_{label}"
    _build_fixture_package(tmp_path, package_name, init_source)

    loaded = _modules_loaded_by_importing(tmp_path, f"{package_name}.contracts")

    assert f"{package_name}.sqlite" in loaded, (
        f"the {label} regression was NOT detected: importing "
        f"{package_name}.contracts did not report {package_name}.sqlite as "
        "loaded, so this guard would not catch the equivalent regression in "
        "the real data_layer package"
    )


def test_check_passes_against_a_faithful_lazy_replica(tmp_path: Path) -> None:
    """The control: the same measurement must clear a correctly lazy package.

    Without this, a measurement that reported everything as a violation would
    pass the two discrimination cases above while being useless.
    """

    package_name = "fixture_lazy_control"
    _build_fixture_package(tmp_path, package_name, _FIXTURE_LAZY_INIT)

    loaded = _modules_loaded_by_importing(tmp_path, f"{package_name}.contracts")

    assert f"{package_name}.sqlite" not in loaded, (
        "the measurement reported a violation against a correctly lazy package, "
        "so it does not discriminate - it just always fails"
    )
