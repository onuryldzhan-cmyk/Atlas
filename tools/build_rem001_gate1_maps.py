"""REM-001 Gate 1 deliverables 4 and 5: construction paths and state authority.

Generates, by static AST analysis over the runtime closure:

- ``packaging/REM-001_RUNTIME_CONSTRUCTION_PATHS.md`` (deliverable 4) --
  instantiation evidence, i.e. which module *constructs* which first-party
  class, at which line, inside which enclosing scope. This is strictly
  stronger than the import evidence in deliverable 3: a module can import a
  class without ever constructing it, and can construct one it never imported
  by plain name (attribute access, re-export).

- ``packaging/REM-001_STATE_AUTHORITY_MAP.md`` (deliverable 5) -- persistence
  evidence, i.e. which module performs which durable write operation against
  which state-file literal.

Authorization: REM-001-GATE1-MECHANICAL, granted by registry v4.32. This tool
is read-only with respect to everything it analyses: it parses source and
writes only its two artifacts under ``packaging/``. It constructs no Atlas
runtime object and opens no state directory, so it cannot touch durable
runtime state.

Both artifacts deliberately omit the classification fields ARCH-001.2.1
reserves for human architecture review. In particular deliverable 5 records
*observed persistence sites* and never assigns ``state_ownership``: which
module writes a file is an observation, which authority owns a piece of state
is an approval-shaped judgment reserved by the carve-out in registry v4.32.
"""

from __future__ import annotations

import argparse
import ast
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any

from tools.build_architecture_inventory import (
    ENTRY_POINTS,
    REPOSITORY_ROOT,
    _git_identity,
    compute_runtime_closure,
)

CONSTRUCTION_PATHS_PATH = (
    REPOSITORY_ROOT / "packaging" / "REM-001_RUNTIME_CONSTRUCTION_PATHS.md"
)
STATE_AUTHORITY_MAP_PATH = (
    REPOSITORY_ROOT / "packaging" / "REM-001_STATE_AUTHORITY_MAP.md"
)

COMPOSITION_ROOT = "core/application.py"

# ARCH-001.2.1 reserves these for human architecture review; scanner evidence
# may propose but never approve them. Registry v4.32 carve-out (i) lists the
# first six as `reserved_fields` and the last two as `reserved_by_extension`.
RESERVED_CLASSIFICATION_FIELDS = (
    "source_scope",
    "current_responsibility",
    "intended_responsibility",
    "domain",
    "owner",
    "lifecycle",
    "criticality",
    "state_ownership",
)

# Attribute calls that durably write. Kept as an explicit allowlist rather
# than a heuristic so the artifact asserts only what it can name.
_WRITE_ATTRIBUTES = {
    "write_text": "PATH_WRITE_TEXT",
    "write_bytes": "PATH_WRITE_BYTES",
    "dump": "JSON_DUMP",
    "replace": "ATOMIC_REPLACE",
    "fsync": "FSYNC",
    "rename": "RENAME",
    "unlink": "UNLINK",
    "writelines": "WRITELINES",
}

_STATE_FILE_SUFFIXES = (".json", ".jsonl", ".db", ".sqlite", ".sqlite3")


def _read_source(repository_root: Path, relative_path: str) -> str:
    return (repository_root / relative_path).read_text(encoding="utf-8-sig")


class _ScopedCallVisitor(ast.NodeVisitor):
    """Collects call sites and string literals with their enclosing scope."""

    def __init__(self) -> None:
        self._scope: list[str] = []
        self.calls: list[dict[str, Any]] = []
        self.string_literals: list[dict[str, Any]] = []

    def _scope_path(self) -> str:
        return "::".join(self._scope) if self._scope else "<module>"

    def _visit_scoped(self, node: ast.AST) -> None:
        self._scope.append(node.name)  # type: ignore[attr-defined]
        self.generic_visit(node)
        self._scope.pop()

    visit_FunctionDef = _visit_scoped
    visit_AsyncFunctionDef = _visit_scoped
    visit_ClassDef = _visit_scoped

    def visit_Call(self, node: ast.Call) -> None:
        func = node.func
        if isinstance(func, ast.Name):
            name, form = func.id, "NAME"
        elif isinstance(func, ast.Attribute):
            name, form = func.attr, "ATTRIBUTE"
        else:
            name, form = None, None

        if name is not None:
            keywords = {kw.arg for kw in node.keywords if kw.arg}
            positional = [
                arg.value
                for arg in node.args
                if isinstance(arg, ast.Constant) and isinstance(arg.value, str)
            ]
            self.calls.append(
                {
                    "name": name,
                    "form": form,
                    "line": node.lineno,
                    "scope": self._scope_path(),
                    "string_args": positional,
                    "keywords": sorted(keywords),
                }
            )
        self.generic_visit(node)

    def visit_Constant(self, node: ast.Constant) -> None:
        if isinstance(node.value, str) and node.value.endswith(_STATE_FILE_SUFFIXES):
            self.string_literals.append(
                {
                    "value": node.value,
                    "line": node.lineno,
                    "scope": self._scope_path(),
                }
            )
        self.generic_visit(node)


def _parse_closure(
    repository_root: Path, closure: list[str]
) -> tuple[dict[str, _ScopedCallVisitor], list[dict[str, str]]]:
    """Parse every closure module once. Returns visitors and parse failures."""
    visitors: dict[str, _ScopedCallVisitor] = {}
    failures: list[dict[str, str]] = []
    for relative_path in closure:
        try:
            tree = ast.parse(
                _read_source(repository_root, relative_path), filename=relative_path
            )
        except SyntaxError as exc:  # pragma: no cover - closure is known-parseable
            failures.append(
                {
                    "file_path": relative_path,
                    "error_type": type(exc).__name__,
                    "detail": str(exc),
                }
            )
            continue
        visitor = _ScopedCallVisitor()
        visitor.visit(tree)
        visitors[relative_path] = visitor
    return visitors, failures


def _class_definitions(
    repository_root: Path, closure: list[str]
) -> tuple[dict[str, list[str]], list[str]]:
    """Map class name -> defining module(s) across the closure.

    A name defined in more than one module is ambiguous; the caller records it
    as UNKNOWN rather than picking a winner.
    """
    definitions: dict[str, set[str]] = defaultdict(set)
    for relative_path in closure:
        try:
            tree = ast.parse(
                _read_source(repository_root, relative_path), filename=relative_path
            )
        except SyntaxError:  # pragma: no cover
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef):
                definitions[node.name].add(relative_path)

    resolved = {name: sorted(mods) for name, mods in definitions.items()}
    ambiguous = sorted(name for name, mods in resolved.items() if len(mods) > 1)
    return resolved, ambiguous


def compute_construction_map(
    repository_root: Path = REPOSITORY_ROOT,
    entry_points: tuple[str, ...] = ENTRY_POINTS,
) -> dict[str, Any]:
    """Deliverable 4: instantiation sites of first-party classes."""
    closure = sorted(compute_runtime_closure(repository_root, entry_points))
    class_defs, ambiguous = _class_definitions(repository_root, closure)
    visitors, parse_failures = _parse_closure(repository_root, closure)

    sites: list[dict[str, Any]] = []
    for relative_path in closure:
        visitor = visitors.get(relative_path)
        if visitor is None:
            continue
        for call in visitor.calls:
            name = call["name"]
            defining = class_defs.get(name)
            if not defining:
                continue
            # A class's own module is never counted as its constructor: the
            # defining file references its own name in ways that are not
            # construction. Same convention as
            # tests/architecture/test_composition_root_is_unique.py.
            if relative_path in defining:
                continue
            sites.append(
                {
                    "constructing_module": relative_path,
                    "class_name": name,
                    "defining_module": defining[0] if len(defining) == 1 else "UNKNOWN",
                    "defining_module_candidates": defining,
                    "line": call["line"],
                    "enclosing_scope": call["scope"],
                    "call_form": call["form"],
                }
            )

    sites.sort(
        key=lambda s: (s["constructing_module"], s["class_name"], s["line"])
    )

    constructors_by_class: dict[str, list[str]] = defaultdict(list)
    for site in sites:
        module = site["constructing_module"]
        if module not in constructors_by_class[site["class_name"]]:
            constructors_by_class[site["class_name"]].append(module)

    edges = sorted(
        {
            (site["constructing_module"], site["defining_module"])
            for site in sites
            if site["defining_module"] != "UNKNOWN"
        }
    )

    return {
        "closure": closure,
        "class_definitions": class_defs,
        "ambiguous_class_names": ambiguous,
        "sites": sites,
        "constructors_by_class": {k: sorted(v) for k, v in constructors_by_class.items()},
        "edges": [list(edge) for edge in edges],
        "parse_failures": parse_failures,
        "modules_constructing": sorted({s["constructing_module"] for s in sites}),
        "classes_constructed": sorted({s["class_name"] for s in sites}),
    }


def _declared_state_files(repository_root: Path) -> dict[str, str]:
    """Module-level state-file constants declared by the composition root."""
    tree = ast.parse(
        _read_source(repository_root, COMPOSITION_ROOT), filename=COMPOSITION_ROOT
    )
    declared: dict[str, str] = {}
    for node in tree.body:
        if not isinstance(node, ast.Assign):
            continue
        if not (
            isinstance(node.value, ast.Constant) and isinstance(node.value.value, str)
        ):
            continue
        if not node.value.value.endswith(_STATE_FILE_SUFFIXES):
            continue
        for target in node.targets:
            if isinstance(target, ast.Name) and target.id.isupper():
                declared[target.id] = node.value.value
    return dict(sorted(declared.items()))


def compute_state_authority_map(
    repository_root: Path = REPOSITORY_ROOT,
    entry_points: tuple[str, ...] = ENTRY_POINTS,
) -> dict[str, Any]:
    """Deliverable 5: observed persistence sites. Never assigns ownership."""
    closure = sorted(compute_runtime_closure(repository_root, entry_points))
    visitors, parse_failures = _parse_closure(repository_root, closure)
    declared = _declared_state_files(repository_root)

    persistence_sites: list[dict[str, Any]] = []
    literals_by_module: dict[str, list[dict[str, Any]]] = {}

    for relative_path in closure:
        visitor = visitors.get(relative_path)
        if visitor is None:
            continue

        for call in visitor.calls:
            name = call["name"]
            operation: str | None = None

            if name == "open" and call["form"] == "NAME":
                modes = [a for a in call["string_args"] if set(a) & {"w", "a", "x", "+"}]
                if modes or "mode" in call["keywords"]:
                    operation = "OPEN_WRITE_MODE"
            elif name in _WRITE_ATTRIBUTES:
                operation = _WRITE_ATTRIBUTES[name]

            if operation is None:
                continue

            persistence_sites.append(
                {
                    "module": relative_path,
                    "operation": operation,
                    "line": call["line"],
                    "enclosing_scope": call["scope"],
                }
            )

        if visitor.string_literals:
            literals_by_module[relative_path] = sorted(
                visitor.string_literals, key=lambda lit: (lit["value"], lit["line"])
            )

    persistence_sites.sort(key=lambda s: (s["module"], s["line"], s["operation"]))

    observed_literals: dict[str, list[str]] = defaultdict(list)
    for module, literals in literals_by_module.items():
        for literal in literals:
            if module not in observed_literals[literal["value"]]:
                observed_literals[literal["value"]].append(module)

    declared_values = set(declared.values())
    declared_observed_outside_root = {
        value: sorted(m for m in observed_literals.get(value, []) if m != COMPOSITION_ROOT)
        for value in sorted(declared_values)
    }

    return {
        "closure": closure,
        "declared_state_files": declared,
        "persistence_sites": persistence_sites,
        "modules_with_persistence_sites": sorted(
            {s["module"] for s in persistence_sites}
        ),
        "observed_state_file_literals": {
            k: sorted(v) for k, v in sorted(observed_literals.items())
        },
        "declared_observed_outside_composition_root": declared_observed_outside_root,
        "parse_failures": parse_failures,
    }


def _authorization_block(extra_rows: tuple[str, ...] = ()) -> list[str]:
    return [
        "## Authorization",
        "",
        "| field | value |",
        "| --- | --- |",
        "| authorization_id | REM-001-GATE1-MECHANICAL |",
        "| granted_by_registry | `governance/current/ATLAS_MILESTONE_REGISTRY_v4.32.json` |",
        "| decision_record | `governance/ATLAS_BASELINE_IDENTITY_AND_GATE1_SCOPE_DECISION_v1.0.md` |",
        *extra_rows,
        "| finding | GOV-DRIFT-005 (not resolved by this artifact; its current status "
        "is recorded in the latest governance registry) |",
        "| scope | Read-only analysis and artifact emission. This file is not a "
        "certification, does not advance `gate_1_state`, and carries no approval. |",
        "",
    ]


def _reserved_fields_block(extra_note: str) -> list[str]:
    lines = [
        "## Classification fields deliberately absent",
        "",
        "ARCH-001.2.1 reserves the following for human architecture review, where",
        "scanner evidence may propose but never approve. Asserting any of them from",
        "static evidence alone would convert UNKNOWN into inferred truth, so this",
        "artifact omits them entirely:",
        "",
    ]
    lines += [f"- `{field}`" for field in RESERVED_CLASSIFICATION_FIELDS]
    lines += ["", extra_note, ""]
    return lines


def _identity_block(identity: dict[str, Any]) -> list[str]:
    modified = identity["modified_tracked_paths_at_generation"]
    return [
        "## Source identity",
        "",
        "| field | value |",
        "| --- | --- |",
        f"| generated_from_commit | `{identity['generated_from_commit']}` |",
        f"| generated_from_tree | `{identity['generated_from_tree']}` |",
        f"| tracked_working_tree_clean | {identity['tracked_working_tree_clean']} |",
        f"| modified_tracked_paths_at_generation | {modified if modified else 'none'} |",
        "",
    ]


def render_construction_paths(data: dict[str, Any], identity: dict[str, Any]) -> str:
    lines: list[str] = [
        "# REM-001_RUNTIME_CONSTRUCTION_PATHS",
        "",
        "REM-001 GATE_1 CANONICAL_COMPONENT_MAPPING — deliverable 4 of 9.",
        "",
        "Generated by `tools/build_rem001_gate1_maps.py construction`.",
        "Command: `python -m tools.build_rem001_gate1_maps construction --write`",
        "",
    ]
    # This generator was recovered from dangling stash commit 59229fd, and D4
    # was regenerated at a current commit under a separate owner authorization.
    lines += _authorization_block(
        (
            "| regeneration_recorded_by | "
            "`governance/current/ATLAS_MILESTONE_REGISTRY_v4.93.json` "
            "(`rem001_d4_generator_recovery_and_regeneration`) |",
        )
    )
    lines += _identity_block(identity)

    lines += [
        "## Analysis",
        "",
        "Static AST call-site resolution over the runtime closure. For every",
        "module reachable from the entry points, each `ast.Call` whose callee",
        "resolves by name to a class defined somewhere in the closure is recorded",
        "as a construction site, with its line and enclosing scope.",
        "",
        "This is deliberately stronger than the import evidence in deliverable 3.",
        "A module can import a class and never construct it, and can construct one",
        "it never imported by plain name. Import edges therefore over- and",
        "under-count instantiation in opposite directions; these are the call sites",
        "themselves.",
        "",
        "A class's own defining module is never counted as its own constructor,",
        "matching the convention already used by",
        "`tests/architecture/test_composition_root_is_unique.py`.",
        "",
        "### Supersedes",
        "",
        "This artifact supersedes the figure `runtime_entrypoint_pattern_matches: 529`",
        "recorded in `architecture_execution_program.phase_2_2`, which was a textual",
        "pattern-match count against the superseded 691-file baseline, not",
        "construction evidence. The old figure is preserved in the registry as the",
        "true account of what was measured then. It is not comparable to the counts",
        "below: it counted pattern hits, these count resolved call sites.",
        "",
        "## Scope",
        "",
        "| field | value |",
        "| --- | --- |",
        f"| entry_points | {', '.join(f'`{e}`' for e in ENTRY_POINTS)} |",
        f"| composition_root_canonical | `{COMPOSITION_ROOT}` (ADR-0001) |",
        f"| modules_in_runtime_closure | {len(data['closure'])} |",
        f"| classes_defined_in_closure | {len(data['class_definitions'])} |",
        f"| construction_sites | {len(data['sites'])} |",
        f"| modules_constructing | {len(data['modules_constructing'])} |",
        f"| classes_constructed | {len(data['classes_constructed'])} |",
        f"| construction_edges | {len(data['edges'])} |",
        f"| ambiguous_class_names | {len(data['ambiguous_class_names'])} |",
        f"| parse_failures | {len(data['parse_failures'])} |",
        "",
    ]

    if data["ambiguous_class_names"]:
        lines += [
            "### Ambiguous class names",
            "",
            "Defined in more than one closure module. Their `defining_module` is",
            "recorded as `UNKNOWN` rather than resolved to a guess, and they",
            "contribute no construction edge.",
            "",
        ]
        for name in data["ambiguous_class_names"]:
            mods = ", ".join(f"`{m}`" for m in data["class_definitions"][name])
            lines.append(f"- `{name}` — {mods}")
        lines.append("")

    lines += [
        "## Canonical construction chain (ADR-0001)",
        "",
        "ADR-0001 fixes the chain as `main.py` -> `core/application.py`",
        "(`AtlasApplication`) -> `core/runtime.py` (`AtlasRuntime`). The authoritative",
        "classes and their observed constructors:",
        "",
        "| class | defining module | constructed by |",
        "| --- | --- | --- |",
    ]
    for class_name in ("AtlasApplication", "AtlasBrain", "MarketLoop", "ExecutionManager"):
        defining = data["class_definitions"].get(class_name, [])
        constructors = data["constructors_by_class"].get(class_name, [])
        lines.append(
            "| `{cls}` | {defn} | {ctors} |".format(
                cls=class_name,
                defn=", ".join(f"`{m}`" for m in defining) or "NOT_DEFINED_IN_CLOSURE",
                ctors=", ".join(f"`{m}`" for m in constructors) or "NONE_OBSERVED",
            )
        )
    lines.append("")

    lines += [
        "## Construction sites",
        "",
        "| constructing module | class | defining module | line | enclosing scope |",
        "| --- | --- | --- | --- | --- |",
    ]
    for site in data["sites"]:
        lines.append(
            "| `{cm}` | `{cls}` | `{dm}` | {line} | `{scope}` |".format(
                cm=site["constructing_module"],
                cls=site["class_name"],
                dm=site["defining_module"],
                line=site["line"],
                scope=site["enclosing_scope"],
            )
        )
    lines.append("")

    lines += _reserved_fields_block(
        "A construction site proves that module A instantiates class B at line L. "
        "It does not establish who *should* own B, what domain B belongs to, or "
        "whether B is critical. Those remain for Gate 1 deliverable 1."
    )

    lines += [
        "## Regression gates",
        "",
        "Enforced by `tests/architecture/test_rem001_construction_paths.py` against",
        "independently computed references, not against this file's own numbers.",
        "",
        "| gate | reference | result |",
        "| --- | --- | --- |",
        "| Authoritative classes constructed only by the composition root | "
        "`tests/architecture/test_composition_root_is_unique.py` (independent, "
        "simpler call-name scan) | see test |",
        "| Every constructing module lies inside the runtime closure | "
        "`packaging/atlas_runtime_closure.json` | see test |",
        "| Regeneration is byte-identical | rerun of this generator | see test |",
        "",
    ]
    return "\n".join(lines) + "\n"


def render_state_authority_map(data: dict[str, Any], identity: dict[str, Any]) -> str:
    lines: list[str] = [
        "# REM-001_STATE_AUTHORITY_MAP",
        "",
        "REM-001 GATE_1 CANONICAL_COMPONENT_MAPPING — deliverable 5 of 9.",
        "",
        "Generated by `tools/build_rem001_gate1_maps.py state`.",
        "Command: `python -m tools.build_rem001_gate1_maps state --write`",
        "",
    ]
    lines += _authorization_block()
    lines += _identity_block(identity)

    lines += [
        "## What this artifact is, and what it is not",
        "",
        "**It is** a map of *observed persistence sites*: which closure module",
        "performs which durable write operation, at which line, in which scope, and",
        "which state-file literals appear where.",
        "",
        "**It is not** an assignment of state ownership. Registry v4.32 carve-out (i)",
        "reserves `state_ownership` by extension, and lists `persistence` as",
        "explicitly inside the authorization, on the stated ground that persistence",
        "is an observation — an array of paths — while ownership is an",
        "approval-shaped enumeration. This artifact therefore records where writes",
        "happen and stops there. Which authority *owns* a piece of state remains",
        "UNKNOWN here and is reserved for human architecture review.",
        "",
        "This serves CLAUDE.md rule 7 (protect critical state) by making the durable",
        "write surface explicit and enumerable, not by ratifying it.",
        "",
        "## Analysis",
        "",
        "Static AST scan over the runtime closure for an explicit allowlist of",
        "durable write operations — `open()` in a write mode, `Path.write_text` /",
        "`write_bytes` / `writelines`, `json.dump`, `os.replace` / `rename` /",
        "`unlink`, and `fsync` — plus every string literal ending in a state-file",
        "suffix. An allowlist is used rather than a heuristic so the artifact",
        "asserts only operations it can name.",
        "",
        "Callee resolution is by attribute name, so an operation is attributed to",
        "the module containing the call, not to a receiver type. Receiver types are",
        "not inferred; doing so from static evidence would be a judgment, not an",
        "observation.",
        "",
        "## Scope",
        "",
        "| field | value |",
        "| --- | --- |",
        f"| entry_points | {', '.join(f'`{e}`' for e in ENTRY_POINTS)} |",
        f"| modules_in_runtime_closure | {len(data['closure'])} |",
        f"| declared_state_file_constants | {len(data['declared_state_files'])} |",
        f"| persistence_sites | {len(data['persistence_sites'])} |",
        f"| modules_with_persistence_sites | {len(data['modules_with_persistence_sites'])} |",
        f"| distinct_state_file_literals | {len(data['observed_state_file_literals'])} |",
        f"| parse_failures | {len(data['parse_failures'])} |",
        "",
        "## Declared durable state surface",
        "",
        f"Module-level state-file constants declared by `{COMPOSITION_ROOT}`. This is",
        "the composition root's own declaration of the durable surface, parsed from",
        "its AST rather than transcribed, and is the independent reference the",
        "regression gate checks the scan against.",
        "",
        "| constant | file | observed as a literal outside the composition root |",
        "| --- | --- | --- |",
    ]
    for constant, value in data["declared_state_files"].items():
        elsewhere = data["declared_observed_outside_composition_root"].get(value, [])
        lines.append(
            "| `{c}` | `{v}` | {e} |".format(
                c=constant,
                v=value,
                e=", ".join(f"`{m}`" for m in elsewhere) if elsewhere else "not observed",
            )
        )
    lines += [
        "",
        "A constant not observed elsewhere is not a defect: the composition root",
        "passes these values to the stores as arguments, so the store module never",
        "needs to name the file itself. This column records what was observed, and",
        "nothing is inferred from an absence.",
        "",
        "## Observed state-file literals",
        "",
        "| literal | modules naming it |",
        "| --- | --- |",
    ]
    for literal, modules in data["observed_state_file_literals"].items():
        lines.append(
            "| `{lit}` | {mods} |".format(
                lit=literal, mods=", ".join(f"`{m}`" for m in modules)
            )
        )
    lines.append("")

    lines += [
        "## Persistence sites",
        "",
        "| module | operation | line | enclosing scope |",
        "| --- | --- | --- | --- |",
    ]
    for site in data["persistence_sites"]:
        lines.append(
            "| `{m}` | {op} | {line} | `{scope}` |".format(
                m=site["module"],
                op=site["operation"],
                line=site["line"],
                scope=site["enclosing_scope"],
            )
        )
    lines.append("")

    lines += _reserved_fields_block(
        "`state_ownership` is the one that matters most here, and is the one this "
        "artifact most conspicuously does not answer. A persistence site proves a "
        "module writes bytes; it does not establish that the module is the "
        "authority for that state."
    )

    lines += [
        "## Regression gates",
        "",
        "Enforced by `tests/architecture/test_rem001_state_authority_map.py` against",
        "independently computed references, not against this file's own numbers.",
        "",
        "| gate | reference | result |",
        "| --- | --- | --- |",
        "| Every state-file constant declared by the composition root is accounted "
        "for | AST of `core/application.py`, parsed independently of the scan | "
        "see test |",
        "| Every persistence-site module lies inside the runtime closure | "
        "`packaging/atlas_runtime_closure.json` | see test |",
        "| The durable execution authorities named in ADR-0003 and "
        "`docs/evidence/block5j_execution_authority_recovery.md` are present in the "
        "declared surface | those documents | see test |",
        "| Regeneration is byte-identical | rerun of this generator | see test |",
        "",
    ]
    return "\n".join(lines) + "\n"


def cmd_construction(args: argparse.Namespace) -> int:
    data = compute_construction_map(REPOSITORY_ROOT)
    rendered = render_construction_paths(data, _git_identity(REPOSITORY_ROOT))
    if args.write:
        CONSTRUCTION_PATHS_PATH.write_text(rendered, encoding="utf-8")
        print(f"wrote {CONSTRUCTION_PATHS_PATH.relative_to(REPOSITORY_ROOT).as_posix()}")
    else:
        sys.stdout.write(rendered)
    print(
        f"construction_sites={len(data['sites'])} "
        f"modules_constructing={len(data['modules_constructing'])} "
        f"classes_constructed={len(data['classes_constructed'])}",
        file=sys.stderr,
    )
    return 0


def cmd_state(args: argparse.Namespace) -> int:
    data = compute_state_authority_map(REPOSITORY_ROOT)
    rendered = render_state_authority_map(data, _git_identity(REPOSITORY_ROOT))
    if args.write:
        STATE_AUTHORITY_MAP_PATH.write_text(rendered, encoding="utf-8")
        print(f"wrote {STATE_AUTHORITY_MAP_PATH.relative_to(REPOSITORY_ROOT).as_posix()}")
    else:
        sys.stdout.write(rendered)
    print(
        f"persistence_sites={len(data['persistence_sites'])} "
        f"declared_state_files={len(data['declared_state_files'])} "
        f"modules_with_persistence_sites={len(data['modules_with_persistence_sites'])}",
        file=sys.stderr,
    )
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    construction = subparsers.add_parser(
        "construction", help="emit REM-001_RUNTIME_CONSTRUCTION_PATHS.md (deliverable 4)"
    )
    construction.add_argument("--write", action="store_true")
    construction.set_defaults(func=cmd_construction)

    state = subparsers.add_parser(
        "state", help="emit REM-001_STATE_AUTHORITY_MAP.md (deliverable 5)"
    )
    state.add_argument("--write", action="store_true")
    state.set_defaults(func=cmd_state)

    args = parser.parse_args()
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
