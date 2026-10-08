"""Architecture boundary for Knowledge Manager v1 (GRANT-KNOWLEDGE-MANAGER-V1-RESEARCH-ONLY, v5.87).

* allowed:   knowledge_manager -> research/* and the standard library.
* forbidden: knowledge_manager -> atlas_org (v5.87 D1), data_layer (ADR-0009),
             RiskEngine, ExecutionManager, application, market loop, capital /
             portfolio / order / exchange / broker paths -- directly or
             transitively.
* forbidden: any runtime module -> knowledge_manager (C-2: not wired into
             web_app, observability, tools, runtime or any W2 path).
* forbidden: I/O and dynamic-loading names in its source (in-memory only;
             closes the computed-string dynamic-import gap for this module).

The import-graph helpers are the Experiment Manager boundary test's, reused.
"""

from __future__ import annotations

import ast
import json
import subprocess
import sys

from tests.architecture.test_experiment_manager_isolation import (
    REPOSITORY_ROOT,
    _first_party_imports,
    _forbidden,
    _transitive_closure,
)

MODULE = "research.knowledge_manager"
MODULE_PATH = REPOSITORY_ROOT / "research" / "knowledge_manager.py"

#: Names that would give an in-memory research module I/O, process,
#: network or dynamic-loading reach.
FORBIDDEN_NAMES = frozenset({
    "open", "os", "sys", "io", "pathlib", "shutil", "tempfile", "subprocess", "socket",
    "importlib", "__import__", "builtins", "eval", "exec", "compile", "globals",
    "locals", "getattr", "setattr", "pickle", "marshal", "ctypes", "sqlite3",
    "urllib", "http", "requests",
})


def test_module_exists() -> None:
    assert MODULE_PATH.is_file()


def test_transitive_import_graph_stays_inside_research() -> None:
    closure = _transitive_closure(MODULE)
    assert MODULE in closure
    outside = sorted(m for m in closure if m.split(".")[0] != "research")
    assert outside == [], f"knowledge manager reaches outside research/: {outside}"
    assert not [m for m in closure if _forbidden(m)]
    assert not [m for m in closure if m == "atlas_org" or m.startswith("atlas_org.")]


def test_live_import_loads_only_research() -> None:
    code = f"import json, sys\nimport {MODULE}\nprint(json.dumps(sorted(sys.modules)))\n"
    out = subprocess.run([sys.executable, "-c", code], cwd=REPOSITORY_ROOT,
                         capture_output=True, text=True, check=True)
    loaded = json.loads(out.stdout.strip().splitlines()[-1])
    roots = {e.name if e.is_dir() else e.stem for e in REPOSITORY_ROOT.iterdir()
             if not e.name.startswith(".") and (e.is_dir() or e.suffix == ".py")}
    outside = [m for m in loaded if m.split(".")[0] in roots and m.split(".")[0] != "research"]
    assert outside == [], f"live import pulled in first-party modules outside research/: {outside}"


def test_source_uses_no_io_or_dynamic_loading_names() -> None:
    tree = ast.parse(MODULE_PATH.read_text(encoding="utf-8"))
    used: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Name):
            used.add(node.id)
        elif isinstance(node, ast.Import):
            used.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            used.add(node.module.split(".")[0])
    assert not used & FORBIDDEN_NAMES, sorted(used & FORBIDDEN_NAMES)


def test_no_module_outside_research_and_tests_imports_it() -> None:
    offenders: list[str] = []
    skip = {"research", "tests", "__pycache__", "node_modules", "venv"}
    for path in REPOSITORY_ROOT.rglob("*.py"):
        rel = path.relative_to(REPOSITORY_ROOT)
        if rel.parts[0] in skip or rel.parts[0].startswith("archive_unused_") or any(
            part.startswith(".") or part in skip for part in rel.parts
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
    assert offenders == [], f"code outside research/ imports {MODULE}: {offenders}"


def test_absent_from_runtime_closure() -> None:
    closure = json.loads((REPOSITORY_ROOT / "packaging" / "atlas_runtime_closure.json")
                         .read_text(encoding="utf-8"))
    assert not [m for m in closure["modules"] if "knowledge_manager" in m]


def test_forbidden_name_detector_can_fail() -> None:
    tree = ast.parse("import importlib\nimportlib.import_module('co' + 're.risk_engine')\nopen('x')")
    used = {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)} | {"importlib"}
    assert {"importlib", "open"} <= used & FORBIDDEN_NAMES
