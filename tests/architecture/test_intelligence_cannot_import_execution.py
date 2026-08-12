"""D3: freeze the currently-clean research/execution boundary.

Explicitly names the high-value execution-authority targets research code
must never reach, on top of the general layer-based D2 check. Research
(``ai/**``) proposes; it must never own or directly reach execution.
"""

from __future__ import annotations

import ast

from tools.build_architecture_inventory import (
    REPOSITORY_ROOT,
    ENTRY_POINTS,
    _build_module_index,
    _resolve_imports,
    _tracked_python_files,
    compute_runtime_closure,
)

_FORBIDDEN_EXECUTION_TARGETS = (
    "core.execution_manager",
    "core.position_controller",
    "portfolio.capital_manager",
    "exchange",
    "data_layer.sqlite",
    "atlas_os.kernel",
    "atlas_os.services",
    "atlas_os.events",
    "atlas_os.observability",
    "atlas_os.audit",
    "atlas_os.scheduling",
    "atlas_os.secrets",
    "atlas_os.configuration",
    "atlas_os.integration",
    "atlas_os.integrations",
)


def _is_forbidden(dotted: str) -> bool:
    return any(dotted == target or dotted.startswith(target + ".") for target in _FORBIDDEN_EXECUTION_TARGETS)


def test_intelligence_cannot_import_execution() -> None:
    closure = compute_runtime_closure(REPOSITORY_ROOT, ENTRY_POINTS)
    ai_modules = [m for m in closure if m.startswith("ai/")]
    assert ai_modules, "expected at least one live ai/** module in the runtime closure"

    tracked_files = _tracked_python_files(REPOSITORY_ROOT)
    module_index = _build_module_index(tracked_files)

    violations: list[str] = []
    for relative_path in ai_modules:
        source = (REPOSITORY_ROOT / relative_path).read_text(encoding="utf-8-sig")
        tree = ast.parse(source, filename=relative_path)
        for dotted in _resolve_imports(relative_path, tree):
            if not _is_forbidden(dotted):
                continue
            target_file = module_index.get(dotted) or module_index.get(dotted + ".__init__")
            if target_file is None:
                continue
            violations.append(f"{relative_path} -> {dotted} ({target_file})")

    assert violations == [], (
        "research/intelligence code (ai/**) must never import execution "
        f"internals (research cannot trade): {sorted(violations)}"
    )
