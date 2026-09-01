"""Build and validate the Atlas Block-2 architecture inventory.

Computes the statically-reachable first-party runtime closure from the
canonical entry points (main.py, web_app.py) via AST import analysis, and
validates it against the checked-in architecture map and runtime closure
artifacts under packaging/. This tool does not mutate repository source; it
only reads tracked files and writes the two inventory JSON artifacts when
explicitly asked to (--write).
"""

from __future__ import annotations

import argparse
import ast
import fnmatch
import json
import subprocess
from pathlib import Path, PurePosixPath
from typing import Any, Iterable


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
ARCHITECTURE_MAP_PATH = REPOSITORY_ROOT / "packaging" / "atlas_architecture_map.json"
RUNTIME_CLOSURE_PATH = REPOSITORY_ROOT / "packaging" / "atlas_runtime_closure.json"
IMPORT_GRAPH_PATH = REPOSITORY_ROOT / "packaging" / "REM-001_IMPORT_GRAPH.json"
ENTRY_POINTS = ("main.py", "web_app.py")


class ArchitectureInventoryError(RuntimeError):
    """Raised when the architecture inventory is malformed or violated."""


# ---------------------------------------------------------------------------
# Repository / tracked-file helpers
# ---------------------------------------------------------------------------


def _normalize_relative_path(value: str) -> str:
    raw_candidate = str(value).replace("\\", "/")
    candidate = raw_candidate.strip("/")
    path = PurePosixPath(candidate)
    if (
        not candidate
        or raw_candidate.startswith("/")
        or path.is_absolute()
        or ".." in path.parts
        or (path.parts and ":" in path.parts[0])
    ):
        raise ArchitectureInventoryError(f"unsafe repository-relative path: {value!r}")
    return path.as_posix()


def _tracked_python_files(repository_root: Path) -> list[str]:
    completed = subprocess.run(
        [
            "git",
            "-c",
            f"safe.directory={repository_root.as_posix()}",
            "-c",
            "core.quotepath=false",
            "ls-files",
            "-z",
            "--",
            "*.py",
        ],
        cwd=repository_root,
        check=True,
        capture_output=True,
    )
    return sorted(
        _normalize_relative_path(item.decode("utf-8"))
        for item in completed.stdout.split(b"\0")
        if item
    )


# ---------------------------------------------------------------------------
# Dotted-module <-> file-path mapping
# ---------------------------------------------------------------------------


def _module_name_for_path(relative_path: str) -> str:
    path = PurePosixPath(relative_path)
    if path.name == "__init__.py":
        parts = path.parts[:-1]
    else:
        parts = path.with_suffix("").parts
    return ".".join(parts)


def _build_module_index(tracked_files: Iterable[str]) -> dict[str, str]:
    index: dict[str, str] = {}
    for relative_path in tracked_files:
        module_name = _module_name_for_path(relative_path)
        if module_name:
            index[module_name] = relative_path
    return index


def _package_parts(relative_path: str) -> list[str]:
    path = PurePosixPath(relative_path)
    if path.name == "__init__.py":
        return list(path.parts[:-1])
    return list(path.with_suffix("").parts[:-1])


def _ancestor_package_files(module_name: str, module_index: dict[str, str]) -> list[str]:
    ancestors: list[str] = []
    parts = module_name.split(".")
    for depth in range(1, len(parts)):
        ancestor_name = ".".join(parts[:depth])
        ancestor_file = module_index.get(ancestor_name + ".__init__")
        if ancestor_file is None:
            ancestor_file = module_index.get(ancestor_name)
            if ancestor_file is not None and not ancestor_file.endswith("__init__.py"):
                ancestor_file = None
        if ancestor_file is not None:
            ancestors.append(ancestor_file)
    return ancestors


def _is_type_checking_test(test: ast.expr) -> bool:
    """True if an ``if`` test is ``TYPE_CHECKING`` or ``typing.TYPE_CHECKING``."""

    if isinstance(test, ast.Name):
        return test.id == "TYPE_CHECKING"
    if isinstance(test, ast.Attribute):
        return test.attr == "TYPE_CHECKING"
    return False


def _type_checking_guarded_node_ids(tree: ast.AST) -> set[int]:
    """Node ids of statements nested inside an ``if TYPE_CHECKING:`` block.

    Such imports never execute at runtime (the branch is only true for static
    type checkers), so they carry no real dependency edge and must not be
    treated as one.
    """

    guarded: set[int] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.If) and _is_type_checking_test(node.test):
            for child in node.body:
                for sub in ast.walk(child):
                    guarded.add(id(sub))
    return guarded


def _resolve_imports(relative_path: str, tree: ast.AST) -> list[str]:
    """Return the list of dotted module names this file's import statements reference.

    Imports guarded by ``if TYPE_CHECKING:`` are excluded: they never execute
    and therefore never produce a real runtime dependency edge.
    """

    resolved: list[str] = []
    package_parts = _package_parts(relative_path)
    guarded_ids = _type_checking_guarded_node_ids(tree)

    for node in ast.walk(tree):
        if id(node) in guarded_ids:
            continue
        if isinstance(node, ast.Import):
            for alias in node.names:
                resolved.append(alias.name)
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                trim = max(node.level - 1, 0)
                base = package_parts[: len(package_parts) - trim] if trim else package_parts
                module_parts = node.module.split(".") if node.module else []
                base_module = ".".join(base + module_parts)
            else:
                base_module = node.module or ""

            if base_module:
                resolved.append(base_module)

            for alias in node.names:
                if alias.name == "*":
                    continue
                resolved.append(f"{base_module}.{alias.name}" if base_module else alias.name)

    return resolved


# ---------------------------------------------------------------------------
# Runtime closure computation
# ---------------------------------------------------------------------------


def compute_runtime_closure(
    repository_root: Path = REPOSITORY_ROOT,
    entry_points: Iterable[str] = ENTRY_POINTS,
) -> list[str]:
    tracked_files = _tracked_python_files(repository_root)
    module_index = _build_module_index(tracked_files)

    visited: set[str] = set()
    queue: list[str] = []

    for entry in entry_points:
        entry = _normalize_relative_path(entry)
        if entry not in set(tracked_files):
            raise ArchitectureInventoryError(f"entry point is not a tracked file: {entry}")
        if entry not in visited:
            visited.add(entry)
            queue.append(entry)

    while queue:
        current = queue.pop(0)
        source = (repository_root / current).read_text(encoding="utf-8-sig")
        tree = ast.parse(source, filename=current)

        for dotted in _resolve_imports(current, tree):
            candidate_files: list[str] = []

            direct_file = module_index.get(dotted)
            if direct_file is not None:
                candidate_files.append(direct_file)

            init_file = module_index.get(dotted + ".__init__")
            if init_file is not None:
                candidate_files.append(init_file)

            for candidate in candidate_files:
                for ancestor in _ancestor_package_files(_module_name_for_path(candidate), module_index):
                    if ancestor not in visited:
                        visited.add(ancestor)
                        queue.append(ancestor)
                if candidate not in visited:
                    visited.add(candidate)
                    queue.append(candidate)

    return sorted(visited)


# ---------------------------------------------------------------------------
# Import graph emission (REM-001 Gate 1 deliverable 3 of 9)
#
# Authorized by GOV-DRIFT-005 / registry v4.30, authorization
# REM-001-GATE1-D3-EMISSION: read-only emission of the graph this module
# already traverses. The functions below add no analysis rule of their own.
# They reuse _tracked_python_files, _build_module_index, _resolve_imports and
# _ancestor_package_files unchanged, and compose them into an edge list.
#
# compute_runtime_closure is deliberately left untouched so that its BFS
# remains an independent reference: cmd_graph's regression gate checks the
# emitted edge set against it rather than against itself.
# ---------------------------------------------------------------------------


def _first_party_targets(dotted: str, module_index: dict[str, str]) -> list[str]:
    """Tracked files a dotted import name resolves to.

    Same resolution the runtime-closure BFS performs: a direct module match and
    a package ``__init__`` match. Names that resolve to nothing are third-party
    or stdlib and carry no first-party edge.
    """

    candidates: list[str] = []
    direct_file = module_index.get(dotted)
    if direct_file is not None:
        candidates.append(direct_file)
    init_file = module_index.get(dotted + ".__init__")
    if init_file is not None:
        candidates.append(init_file)
    return candidates


def compute_import_graph(
    repository_root: Path = REPOSITORY_ROOT,
) -> dict[str, Any]:
    """First-party import edges over every tracked Python file.

    Returns sorted, de-duplicated edges plus any files that could not be
    parsed. Parse failures are retained rather than silently dropped, so the
    graph never presents itself as more complete than it is.

    Two edge kinds are emitted, both of which are real runtime dependencies:

    ``import``
        the importer references the target module directly.
    ``package_init``
        the importer references a submodule, which makes Python execute the
        ancestor package's ``__init__.py``. The runtime-closure BFS follows
        these too, so omitting them would make the graph unable to reproduce
        the closure.
    """

    tracked_files = _tracked_python_files(repository_root)
    module_index = _build_module_index(tracked_files)

    edges: set[tuple[str, str, str]] = set()
    parse_failures: list[dict[str, str]] = []

    for relative_path in tracked_files:
        try:
            source = (repository_root / relative_path).read_text(encoding="utf-8-sig")
            tree = ast.parse(source, filename=relative_path)
        except (SyntaxError, ValueError, UnicodeDecodeError) as exc:
            parse_failures.append(
                {
                    "file_path": relative_path,
                    "error_type": type(exc).__name__,
                    "detail": str(exc),
                }
            )
            continue

        for dotted in _resolve_imports(relative_path, tree):
            for candidate in _first_party_targets(dotted, module_index):
                candidate_module = _module_name_for_path(candidate)
                for ancestor in _ancestor_package_files(candidate_module, module_index):
                    if ancestor != relative_path:
                        edges.add((relative_path, ancestor, "package_init"))
                if candidate != relative_path:
                    edges.add((relative_path, candidate, "import"))

    return {
        "modules": tracked_files,
        "edges": sorted(edges),
        "parse_failures": sorted(parse_failures, key=lambda item: item["file_path"]),
    }


def reachable_over_edges(
    edges: Iterable[tuple[str, str, str]],
    entry_points: Iterable[str] = ENTRY_POINTS,
) -> list[str]:
    """Modules reachable from the entry points by following emitted edges."""

    adjacency: dict[str, list[str]] = {}
    for importer, imported, _kind in edges:
        adjacency.setdefault(importer, []).append(imported)

    visited: set[str] = set()
    queue: list[str] = []
    for entry in entry_points:
        entry = _normalize_relative_path(entry)
        if entry not in visited:
            visited.add(entry)
            queue.append(entry)

    while queue:
        current = queue.pop(0)
        for target in adjacency.get(current, ()):
            if target not in visited:
                visited.add(target)
                queue.append(target)

    return sorted(visited)


# ---------------------------------------------------------------------------
# Architecture map I/O and validation
# ---------------------------------------------------------------------------


def _load_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise ArchitectureInventoryError(f"missing required artifact: {path}")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ArchitectureInventoryError(f"malformed JSON in {path}: {exc}") from exc
    if not isinstance(data, dict):
        raise ArchitectureInventoryError(f"{path} must contain a JSON object")
    return data


def load_architecture_map(path: Path = ARCHITECTURE_MAP_PATH) -> dict[str, Any]:
    data = _load_json(path)
    for required_key in ("schema_version", "layers", "layer_rules", "module_layers", "forbidden_edges"):
        if required_key not in data:
            raise ArchitectureInventoryError(f"architecture map missing required key: {required_key}")
    return data


def load_runtime_closure(path: Path = RUNTIME_CLOSURE_PATH) -> dict[str, Any]:
    data = _load_json(path)
    for required_key in ("schema_version", "entry_points", "modules"):
        if required_key not in data:
            raise ArchitectureInventoryError(f"runtime closure missing required key: {required_key}")
    return data


def classify_module(relative_path: str, layer_rules: Iterable[dict[str, Any]]) -> str | None:
    """Return the layer for a module by applying layer_rules in order (first match wins)."""

    for rule in layer_rules:
        pattern = rule["pattern"]
        if relative_path == pattern or fnmatch.fnmatchcase(relative_path, pattern):
            return rule["layer"]
    return None


def compute_module_layers(
    modules: Iterable[str],
    layer_rules: Iterable[dict[str, Any]],
) -> tuple[dict[str, str], list[str]]:
    assigned: dict[str, str] = {}
    unassigned: list[str] = []
    for module in sorted(modules):
        layer = classify_module(module, layer_rules)
        if layer is None:
            unassigned.append(module)
        else:
            assigned[module] = layer
    return assigned, unassigned


LAYER_ORDER = ("L0", "L1", "L2", "L3", "L4", "L5")


def find_forbidden_edges(
    repository_root: Path,
    modules: Iterable[str],
    module_layers: dict[str, str],
    forbidden_edges: Iterable[dict[str, Any]],
    permitted_exceptions: Iterable[dict[str, Any]],
) -> list[str]:
    """Return a sorted list of 'importer -> imported' strings violating forbidden edges."""

    tracked_files = list(modules)
    module_index = _build_module_index(tracked_files)
    exceptions = {
        (exc["from"], exc["to"]) for exc in permitted_exceptions
    }

    violations: list[str] = []

    for relative_path in tracked_files:
        importer_layer = module_layers.get(relative_path)
        if importer_layer is None:
            continue

        source = (repository_root / relative_path).read_text(encoding="utf-8-sig")
        tree = ast.parse(source, filename=relative_path)

        for dotted in _resolve_imports(relative_path, tree):
            target_file = module_index.get(dotted) or module_index.get(dotted + ".__init__")
            if target_file is None or target_file == relative_path:
                continue

            imported_layer = module_layers.get(target_file)
            if imported_layer is None:
                continue

            if (relative_path, target_file) in exceptions:
                continue

            for rule in forbidden_edges:
                from_pattern = rule["from"]
                to_pattern = rule["to"]
                if fnmatch.fnmatchcase(importer_layer, from_pattern) and fnmatch.fnmatchcase(
                    imported_layer, to_pattern
                ):
                    violations.append(f"{relative_path} -> {target_file} ({rule.get('reason', 'forbidden edge')})")
                    break

    return sorted(set(violations))


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _write_json(path: Path, data: dict[str, Any]) -> None:
    path.write_text(json.dumps(data, indent=2, sort_keys=False) + "\n", encoding="utf-8")


def cmd_closure(args: argparse.Namespace) -> int:
    computed = compute_runtime_closure(REPOSITORY_ROOT, ENTRY_POINTS)

    if args.write:
        data = {
            "schema_version": "1.0",
            "entry_points": list(ENTRY_POINTS),
            "modules": computed,
        }
        _write_json(RUNTIME_CLOSURE_PATH, data)
        print(f"wrote {len(computed)} modules to {RUNTIME_CLOSURE_PATH}")
        return 0

    checked_in = load_runtime_closure()
    checked_in_modules = list(checked_in["modules"])
    if checked_in_modules != computed:
        missing = sorted(set(computed) - set(checked_in_modules))
        extra = sorted(set(checked_in_modules) - set(computed))
        print("runtime closure mismatch")
        if missing:
            print("  missing from checked-in closure (newly reachable):")
            for m in missing:
                print(f"    + {m}")
        if extra:
            print("  present in checked-in closure but no longer reachable:")
            for m in extra:
                print(f"    - {m}")
        return 1

    print(f"runtime closure matches checked-in artifact ({len(computed)} modules)")
    return 0


def cmd_map(args: argparse.Namespace) -> int:
    architecture_map = load_architecture_map()
    closure = load_runtime_closure()
    modules = closure["modules"]

    assigned, unassigned = compute_module_layers(modules, architecture_map["layer_rules"])

    if unassigned:
        print("modules with no matching layer rule (totality violation):")
        for m in unassigned:
            print(f"  ? {m}")
        return 1

    if args.write:
        architecture_map["module_layers"] = assigned
        _write_json(ARCHITECTURE_MAP_PATH, architecture_map)
        print(f"wrote layer assignment for {len(assigned)} modules to {ARCHITECTURE_MAP_PATH}")
        return 0

    checked_in = architecture_map.get("module_layers", {})
    if checked_in != assigned:
        print("module_layers in architecture map is stale relative to layer_rules/closure")
        return 1

    print(f"architecture map module_layers is consistent ({len(assigned)} modules)")
    return 0


def _git_identity(repository_root: Path) -> dict[str, Any]:
    """Commit and tree the graph is being generated from.

    The artifact is generated from the working tree before its own commit
    exists, so the stamped commit is the parent of the commit that will carry
    it. ``tracked_working_tree_clean`` records whether the tree matched that
    commit at generation time; when it is false the stamped commit does not
    fully describe what was analysed.
    """

    def run(*args: str) -> str:
        return subprocess.run(
            ["git", "-c", f"safe.directory={repository_root.as_posix()}", *args],
            cwd=repository_root,
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()

    dirty = run("status", "--porcelain", "--untracked-files=no")
    return {
        "generated_from_commit": run("rev-parse", "HEAD"),
        "generated_from_tree": run("rev-parse", "HEAD^{tree}"),
        "tracked_working_tree_clean": dirty == "",
        "modified_tracked_paths_at_generation": sorted(
            line[3:] for line in dirty.splitlines() if line
        ),
    }


def cmd_graph(args: argparse.Namespace) -> int:
    graph = compute_import_graph(REPOSITORY_ROOT)
    edges = [tuple(edge) for edge in graph["edges"]]

    # Regression gate (registry v4.30, REM-001-GATE1-D3-EMISSION condition 5):
    # traversing the emitted edges from the entry points must reproduce the
    # checked-in runtime closure exactly. compute_runtime_closure is not used
    # to build the edges, so this compares two independent computations.
    reachable = reachable_over_edges(edges, ENTRY_POINTS)
    checked_in = list(load_runtime_closure()["modules"])

    if reachable != checked_in:
        missing = sorted(set(checked_in) - set(reachable))
        extra = sorted(set(reachable) - set(checked_in))
        print("FAIL: import graph does not reproduce the checked-in runtime closure")
        print(f"  reachable over emitted edges: {len(reachable)}")
        print(f"  checked-in closure:           {len(checked_in)}")
        for m in missing:
            print(f"    - unreachable but in closure: {m}")
        for m in extra:
            print(f"    + reachable but not in closure: {m}")
        return 1

    print(
        "OK: BFS over emitted edges reproduces "
        f"packaging/atlas_runtime_closure.json exactly ({len(reachable)} modules)"
    )

    if not args.write:
        if not IMPORT_GRAPH_PATH.exists():
            print(f"note: {IMPORT_GRAPH_PATH.name} not written (pass --write to emit)")
        return 0

    reachable_set = set(reachable)
    data = {
        "schema_version": "1.0",
        "artifact": "REM-001_IMPORT_GRAPH",
        "gate": "REM-001 GATE_1 CANONICAL_COMPONENT_MAPPING",
        "deliverable": "3 of 9",
        "authorization": {
            "authorization_id": "REM-001-GATE1-D3-EMISSION",
            "finding": "GOV-DRIFT-005",
            "registry": "governance/current/ATLAS_MILESTONE_REGISTRY_v4.30.json",
            "conflict_record": (
                "governance/ATLAS_REM001_SPECIFICATION_ARTIFACT_INTEGRITY_v1.0.md"
            ),
            "scope": (
                "Read-only emission of this one artifact. This file is not a "
                "certification, does not advance gate_1_state, and carries no "
                "authority of any kind."
            ),
        },
        "generator": {
            "tool": "tools/build_architecture_inventory.py",
            "command": "python tools/build_architecture_inventory.py graph --write",
            "analysis": (
                "Static AST import resolution over git-tracked Python files, "
                "excluding imports guarded by if TYPE_CHECKING:. Third-party and "
                "stdlib targets resolve to nothing and carry no edge."
            ),
        },
        "source_identity": _git_identity(REPOSITORY_ROOT),
        "scope": {
            "universe": "ALL_GIT_TRACKED_PYTHON_FILES",
            "universe_note": (
                "The tool's existing tracked-file definition, used unchanged. No "
                "source-scope classification (ACTIVE_CANDIDATE / TEST / TOOL / "
                "ARCHIVE / BACKUP / QUARANTINE / REPORT_COPY) is applied or "
                "implied: that classification requires the human review gate "
                "ARCH-001.2.1 reserves and belongs to Gate 1 deliverable 1."
            ),
            "modules_total": len(graph["modules"]),
            "modules_runtime_reachable": len(reachable),
            "modules_outside_runtime_closure": len(graph["modules"]) - len(reachable),
            "edges_total": len(edges),
            "edges_import": sum(1 for _f, _t, k in edges if k == "import"),
            "edges_package_init": sum(1 for _f, _t, k in edges if k == "package_init"),
            "parse_failures": len(graph["parse_failures"]),
        },
        "entry_points": list(ENTRY_POINTS),
        "runtime_closure_reference": {
            "artifact": "packaging/atlas_runtime_closure.json",
            "modules": len(checked_in),
            "regression_gate": (
                "BFS from entry_points over edges reproduces the referenced "
                "artifact exactly"
            ),
            "regression_gate_result": "PASS",
        },
        "classification_fields_deliberately_absent": [
            "source_scope",
            "domain",
            "owner",
            "current_responsibility",
            "intended_responsibility",
            "state_ownership",
            "lifecycle",
            "criticality",
        ],
        "classification_note": (
            "Asserting any of the above from static import evidence alone would "
            "convert UNKNOWN into inferred truth, which ARCH-001.2.1 forbids: "
            "scanner evidence may propose but never approve those values."
        ),
        "parse_failures": graph["parse_failures"],
        "parse_failure_note": (
            "Retained, not dropped. None is in the runtime closure, so none "
            "affects the regression gate. Their edges are absent from this graph."
        ),
        "nodes": [
            {"module": module, "runtime_reachable": module in reachable_set}
            for module in graph["modules"]
        ],
        "edges": [
            {"from": importer, "to": imported, "kind": kind}
            for importer, imported, kind in edges
        ],
    }

    _write_json(IMPORT_GRAPH_PATH, data)
    print(
        f"wrote {len(data['nodes'])} nodes and {len(edges)} edges to "
        f"{IMPORT_GRAPH_PATH}"
    )
    return 0


def cmd_check(args: argparse.Namespace) -> int:
    exit_code = 0

    architecture_map = load_architecture_map()
    closure = load_runtime_closure()

    computed_closure = compute_runtime_closure(REPOSITORY_ROOT, ENTRY_POINTS)
    if computed_closure != list(closure["modules"]):
        print("FAIL: runtime closure does not match packaging/atlas_runtime_closure.json")
        exit_code = 1
    else:
        print(f"OK: runtime closure matches ({len(computed_closure)} modules)")

    assigned, unassigned = compute_module_layers(computed_closure, architecture_map["layer_rules"])
    if unassigned:
        print("FAIL: modules with no layer assignment:")
        for m in unassigned:
            print(f"  ? {m}")
        exit_code = 1
    elif assigned != architecture_map.get("module_layers", {}):
        print("FAIL: architecture map module_layers is stale")
        exit_code = 1
    else:
        print(f"OK: architecture map assigns every live module a layer ({len(assigned)} modules)")

    if exit_code == 0:
        violations = find_forbidden_edges(
            REPOSITORY_ROOT,
            computed_closure,
            assigned,
            architecture_map["forbidden_edges"],
            architecture_map.get("permitted_exceptions", []),
        )
        if violations:
            print("FAIL: forbidden dependency edges detected:")
            for v in violations:
                print(f"  ! {v}")
            exit_code = 1
        else:
            print("OK: no forbidden dependency edges")

    return exit_code


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    closure_parser = subparsers.add_parser("closure", help="compute/validate the runtime closure")
    closure_parser.add_argument("--write", action="store_true")
    closure_parser.set_defaults(func=cmd_closure)

    map_parser = subparsers.add_parser("map", help="compute/validate the architecture map module_layers")
    map_parser.add_argument("--write", action="store_true")
    map_parser.set_defaults(func=cmd_map)

    graph_parser = subparsers.add_parser(
        "graph", help="validate/emit the REM-001 import graph (Gate 1 deliverable 3)"
    )
    graph_parser.add_argument("--write", action="store_true")
    graph_parser.set_defaults(func=cmd_graph)

    check_parser = subparsers.add_parser("check", help="run all inventory checks (read-only)")
    check_parser.set_defaults(func=cmd_check)

    args = parser.parse_args()
    try:
        return args.func(args)
    except ArchitectureInventoryError as exc:
        print(f"ERROR: {exc}")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
