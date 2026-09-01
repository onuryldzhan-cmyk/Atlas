"""REM-001 Gate 1 deliverable 3: the emitted import graph must stay faithful.

The graph is composed from the same import-resolution primitives the runtime
closure uses, but by a separate function. That makes the reproduction check
below a real comparison of two independent computations rather than a
tautology, and it is the regression gate registry v4.30 attaches to
authorization REM-001-GATE1-D3-EMISSION.

These tests exercise the pure computation only. They never write
packaging/REM-001_IMPORT_GRAPH.json and never assert that the checked-in
artifact is current: keeping the artifact fresh is not an obligation the
narrow emission authorization created.
"""

from __future__ import annotations

from tools.build_architecture_inventory import (
    ENTRY_POINTS,
    REPOSITORY_ROOT,
    compute_import_graph,
    compute_runtime_closure,
    load_runtime_closure,
    reachable_over_edges,
)


def test_import_graph_reproduces_checked_in_runtime_closure() -> None:
    graph = compute_import_graph(REPOSITORY_ROOT)
    edges = [tuple(edge) for edge in graph["edges"]]

    reachable = reachable_over_edges(edges, ENTRY_POINTS)
    checked_in = list(load_runtime_closure()["modules"])

    missing = sorted(set(checked_in) - set(reachable))
    extra = sorted(set(reachable) - set(checked_in))

    assert reachable == checked_in, (
        "the import graph's runtime-reachable subgraph no longer reproduces "
        "packaging/atlas_runtime_closure.json. "
        f"in the closure but unreachable over emitted edges: {missing}; "
        f"reachable over emitted edges but not in the closure: {extra}. "
        "An edge kind is probably being dropped during emission."
    )


def test_import_graph_agrees_with_independent_closure_computation() -> None:
    """The two BFS implementations must not diverge from each other either."""

    graph = compute_import_graph(REPOSITORY_ROOT)
    edges = [tuple(edge) for edge in graph["edges"]]

    assert reachable_over_edges(edges, ENTRY_POINTS) == compute_runtime_closure(
        REPOSITORY_ROOT, ENTRY_POINTS
    )


def test_import_graph_computation_is_deterministic() -> None:
    first = compute_import_graph(REPOSITORY_ROOT)
    second = compute_import_graph(REPOSITORY_ROOT)
    assert first == second


def test_import_graph_encodes_no_classification_judgment() -> None:
    """Authorization condition 3: static evidence may not assert these values.

    ARCH-001.2.1 reserves source_scope, domain, owner, responsibility,
    state_ownership, lifecycle and criticality for a human review gate --
    scanner evidence may propose but never approve them. Emitting any of them
    here would convert UNKNOWN into inferred truth.
    """

    graph = compute_import_graph(REPOSITORY_ROOT)

    assert set(graph) == {"modules", "edges", "parse_failures"}

    forbidden = {
        "source_scope",
        "domain",
        "owner",
        "current_responsibility",
        "intended_responsibility",
        "state_ownership",
        "lifecycle",
        "criticality",
    }
    for failure in graph["parse_failures"]:
        assert not forbidden & set(failure)


def test_import_graph_retains_parse_failures_rather_than_dropping_them() -> None:
    """A file the parser cannot read must be recorded, not silently omitted.

    Silently skipping unparseable files would make the graph look more
    complete than it is, which is the failure mode ARCH-001.2.1's
    "parse failures are retained" invariant exists to prevent.
    """

    graph = compute_import_graph(REPOSITORY_ROOT)
    closure = set(load_runtime_closure()["modules"])

    for failure in graph["parse_failures"]:
        assert set(failure) == {"file_path", "error_type", "detail"}
        assert failure["file_path"] not in closure, (
            "a runtime-closure module failed to parse, which would silently "
            f"hole the graph: {failure['file_path']}"
        )

    failed_paths = {failure["file_path"] for failure in graph["parse_failures"]}
    assert not failed_paths & {importer for importer, _to, _kind in graph["edges"]}
