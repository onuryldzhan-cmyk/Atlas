"""A-1: find_forbidden_edges resolves ancestor-package edges, not just direct ones.

Importing ``pkg.sub`` executes ``pkg/__init__.py``, so the ancestor package is a
real runtime dependency even though it never appears as a dotted name of its
own. ``compute_runtime_closure`` and ``compute_import_graph`` both already
follow those edges; ``find_forbidden_edges`` did not, which let a forbidden
L4->L2 edge reached solely through a package ``__init__`` pass the architecture
gate undetected. Commit 1ac3a64 hit this in production shape: an L4 module
importing the L1 ``data_layer/contracts.py`` silently executed the L2
``data_layer/__init__.py``.

The fixtures below reproduce that shape synthetically rather than asserting
against the live repository, so the three cases stay stable as the real
layering changes.
"""

from __future__ import annotations

from pathlib import Path

from tools.build_architecture_inventory import find_forbidden_edges

# An L4 -> L2 edge is forbidden; L4 -> L1 is not. This mirrors the real map's
# shape closely enough to exercise the resolver without depending on it.
FORBIDDEN_EDGES = [{"from": "L4", "to": "L2", "reason": "L4 must not reach L2"}]


def _write(root: Path, relative_path: str, source: str) -> None:
    target = root / relative_path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(source, encoding="utf-8")


def _build_fixture(root: Path) -> dict[str, str]:
    """Create the synthetic tree and return its module -> layer assignment.

    ``pkg`` is a split-layer package, exactly like the real ``data_layer``:
    its ``__init__.py`` is L2, but ``pkg/contracts.py`` inside it is L1. That
    split is what makes the ancestor edge distinguishable from the direct one.
    """

    _write(root, "pkg/__init__.py", "from . import backend\n")
    _write(root, "pkg/backend.py", "VALUE = 1\n")
    _write(root, "pkg/contracts.py", "CONTRACT = 1\n")

    # L1-only package: both the __init__ and its submodule are L1, so an
    # ancestor edge to it is legitimate and must not be reported.
    _write(root, "safe/__init__.py", "")
    _write(root, "safe/types.py", "TYPE = 1\n")

    # Imports pkg.backend directly: the direct target itself is L2.
    _write(root, "app/direct.py", "from pkg.backend import VALUE\n")

    # Imports pkg.contracts: the direct target is L1 and allowed, but importing
    # it executes pkg/__init__.py, which is L2 and forbidden.
    _write(root, "app/via_ancestor.py", "from pkg.contracts import CONTRACT\n")

    # Imports safe.types: ancestor safe/__init__.py is L1, so no violation.
    _write(root, "app/legitimate.py", "from safe.types import TYPE\n")

    return {
        "pkg/__init__.py": "L2",
        "pkg/backend.py": "L2",
        "pkg/contracts.py": "L1",
        "safe/__init__.py": "L1",
        "safe/types.py": "L1",
        "app/direct.py": "L4",
        "app/via_ancestor.py": "L4",
        "app/legitimate.py": "L4",
    }


def _violations(root: Path, layers: dict[str, str], permitted=()) -> list[str]:
    return find_forbidden_edges(
        root,
        list(layers),
        layers,
        FORBIDDEN_EDGES,
        list(permitted),
    )


def test_direct_forbidden_import_is_still_caught(tmp_path: Path) -> None:
    """No regression: an L4 module importing an L2 module directly still fails."""

    layers = _build_fixture(tmp_path)
    violations = _violations(tmp_path, layers)

    assert any(
        v.startswith("app/direct.py -> pkg/backend.py") for v in violations
    ), f"direct L4 -> L2 edge no longer detected: {violations}"


def test_forbidden_import_through_ancestor_init_is_caught(tmp_path: Path) -> None:
    """The A-1 gap: the edge exists only because importing pkg.contracts runs pkg/__init__.py."""

    layers = _build_fixture(tmp_path)
    violations = _violations(tmp_path, layers)

    assert any(
        v.startswith("app/via_ancestor.py -> pkg/__init__.py") for v in violations
    ), f"ancestor-package L4 -> L2 edge not detected: {violations}"

    # The direct target of that same import is L1 and must not be reported,
    # which is precisely why the old resolver saw nothing wrong here.
    assert not any(
        "app/via_ancestor.py -> pkg/contracts.py" in v for v in violations
    ), f"the allowed L4 -> L1 direct edge was wrongly reported: {violations}"


def test_legitimate_ancestor_import_is_not_flagged(tmp_path: Path) -> None:
    """An ancestor package that is not on a forbidden layer must not be reported."""

    layers = _build_fixture(tmp_path)
    violations = _violations(tmp_path, layers)

    assert not any(
        v.startswith("app/legitimate.py") for v in violations
    ), f"legitimate L4 -> L1 ancestor import was false-flagged: {violations}"


def test_permitted_exception_still_suppresses_an_ancestor_edge(tmp_path: Path) -> None:
    """Ancestor edges honour permitted_exceptions the same way direct edges do.

    Without this, widening the resolver would have made the exception list
    unable to express a decision about the very edges the widening surfaces.
    """

    layers = _build_fixture(tmp_path)
    violations = _violations(
        tmp_path,
        layers,
        permitted=[{"from": "app/via_ancestor.py", "to": "pkg/__init__.py"}],
    )

    assert not any(
        v.startswith("app/via_ancestor.py") for v in violations
    ), f"permitted exception did not suppress the ancestor edge: {violations}"

    # Suppressing one edge must not suppress the unrelated direct violation.
    assert any(
        v.startswith("app/direct.py -> pkg/backend.py") for v in violations
    ), f"unrelated direct violation was lost: {violations}"
