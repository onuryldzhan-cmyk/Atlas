from __future__ import annotations

import ast
import fnmatch
import hashlib
import json
from pathlib import Path

import pytest

from tools.build_runtime_distribution import (
    DEFAULT_MANIFEST,
    DistributionBoundaryError,
    _load_manifest,
    _normalize_relative_path,
    build_distribution,
    select_distribution_files,
    validate_import_boundaries,
)


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]


def test_canonical_distribution_includes_required_and_excludes_legacy() -> None:
    manifest = _load_manifest(DEFAULT_MANIFEST)
    selected = select_distribution_files(
        REPOSITORY_ROOT,
        manifest,
        include_tests=False,
    )

    assert "main.py" in selected
    assert "web_app.py" in selected
    assert ".env.example" in selected
    assert "core/application.py" in selected
    assert "core/execution_manager.py" in selected
    assert "requirements/locks/windows-py314-runtime.txt" in selected

    assert "dashboard/app.py" not in selected
    assert "core/execution_state.py" not in selected
    assert not any(path.startswith("archive_unused_") for path in selected)
    assert not any(path.startswith("_quarantine/") for path in selected)
    assert not any(path.startswith("reports/") for path in selected)
    assert not any(path.startswith("database/") for path in selected)
    assert not any(Path(path).name.startswith("test_") for path in selected)
    assert not any("backup" in path.lower() for path in selected)


# Historical-variant naming conventions observed in this repository that a bare
# "backup" substring check does not catch (e.g. "*_before_*" snapshots taken by
# one-shot patch scripts). Matched against each selected file's basename.
_HISTORICAL_VARIANT_PATTERNS = (
    "*_before_*",
    "*.bak",
    "*.backup_*",
    "*_backup*.py",
)


def test_canonical_distribution_excludes_historical_variant_patterns() -> None:
    manifest = _load_manifest(DEFAULT_MANIFEST)
    selected = select_distribution_files(
        REPOSITORY_ROOT,
        manifest,
        include_tests=False,
    )

    violations = [
        path
        for path in selected
        if any(
            fnmatch.fnmatch(Path(path).name, pattern)
            for pattern in _HISTORICAL_VARIANT_PATTERNS
        )
    ]
    assert violations == []


def test_canonical_distribution_has_single_execution_manager_authority() -> None:
    # Narrow semantic guard: at most one selected core/*.py file may define a
    # `class ExecutionManager` carrying a `VERSION` attribute. This catches
    # duplicate-authority leaks (e.g. a historical snapshot with a different
    # filename) that path-pattern matching alone cannot anticipate.
    manifest = _load_manifest(DEFAULT_MANIFEST)
    selected = select_distribution_files(
        REPOSITORY_ROOT,
        manifest,
        include_tests=False,
    )

    authorities = []
    for path in selected:
        if not path.startswith("core/") or not path.endswith(".py"):
            continue
        tree = ast.parse(
            (REPOSITORY_ROOT / path).read_text(encoding="utf-8-sig"),
            filename=path,
        )
        for node in ast.walk(tree):
            if not (isinstance(node, ast.ClassDef) and node.name == "ExecutionManager"):
                continue
            has_version_attribute = any(
                isinstance(stmt, ast.Assign)
                and any(
                    isinstance(target, ast.Name) and target.id == "VERSION"
                    for target in stmt.targets
                )
                for stmt in node.body
            )
            if has_version_attribute:
                authorities.append(path)

    assert authorities == ["core/execution_manager.py"]


def test_canonical_distribution_capital_manager_authority() -> None:
    manifest = _load_manifest(DEFAULT_MANIFEST)
    selected = select_distribution_files(
        REPOSITORY_ROOT,
        manifest,
        include_tests=False,
    )

    assert "portfolio/capital_manager.py" in selected
    assert "core/capital_manager.py" not in selected


def test_distribution_path_normalization_rejects_escape() -> None:
    for value in ("../secret", "core/../../secret", "/absolute/path"):
        with pytest.raises(DistributionBoundaryError):
            _normalize_relative_path(value)


def test_distribution_output_is_deterministic(tmp_path: Path) -> None:
    first = tmp_path / "first.zip"
    second = tmp_path / "second.zip"

    first_result = build_distribution(first)
    second_result = build_distribution(second)

    assert first_result["file_count"] == second_result["file_count"]
    assert first.read_bytes() == second.read_bytes()
    assert first_result["sha256"] == hashlib.sha256(
        first.read_bytes()
    ).hexdigest().upper()


def test_optional_canonical_tests_do_not_include_root_legacy_scripts() -> None:
    manifest = _load_manifest(DEFAULT_MANIFEST)
    selected = select_distribution_files(
        REPOSITORY_ROOT,
        manifest,
        include_tests=True,
    )

    assert "tests/test_durable_transaction_state.py" in selected
    assert not any(
        "/" not in path and path.startswith("test_")
        for path in selected
    )


def test_canonical_sources_do_not_import_excluded_modules() -> None:
    manifest = _load_manifest(DEFAULT_MANIFEST)
    selected = select_distribution_files(
        REPOSITORY_ROOT,
        manifest,
        include_tests=False,
    )
    assert validate_import_boundaries(
        REPOSITORY_ROOT,
        selected,
        manifest,
    ) == []


def test_import_boundary_detects_legacy_import(tmp_path: Path) -> None:
    source = tmp_path / "canonical.py"
    source.write_text("import dashboard.app\n", encoding="utf-8")
    manifest = {"excluded_module_patterns": ["dashboard.*"]}

    assert validate_import_boundaries(
        tmp_path,
        ["canonical.py"],
        manifest,
    ) == ["canonical.py: dashboard.app"]


def test_import_boundary_detects_relative_legacy_import(tmp_path: Path) -> None:
    package = tmp_path / "core"
    package.mkdir()
    source = package / "canonical.py"
    source.write_text("from . import execution_state\n", encoding="utf-8")
    manifest = {"excluded_module_patterns": ["core.execution_state"]}

    assert validate_import_boundaries(
        tmp_path,
        ["core/canonical.py"],
        manifest,
    ) == ["core/canonical.py: core.execution_state"]


def test_legacy_inventory_covers_every_root_test_script() -> None:
    inventory = json.loads(
        (REPOSITORY_ROOT / "tests" / "legacy_test_inventory.json").read_text(
            encoding="utf-8"
        )
    )
    recorded = {entry["path"] for entry in inventory["entries"]}
    actual = {path.name for path in REPOSITORY_ROOT.glob("test_*.py")}

    assert recorded == actual
    assert all(
        entry["safe_for_pytest_collection"] is False
        for entry in inventory["entries"]
    )


def test_canonical_launchers_never_route_to_legacy_dashboard() -> None:
    """No launcher may start the legacy dashboard package.

    Each launcher must also actually start a canonical surface. Which one
    differs since the Core/Dashboard process merge: atlas.ps1 now launches
    the merged entry point atlas_service.py, which serves the canonical web
    application in-process with the runtime attached, while
    run_dashboard.ps1 still serves web_app:app standalone. Asserting the
    literal "web_app:app" against atlas.ps1 would now only be satisfiable
    by a comment, which would test nothing.
    """

    canonical_route = {
        "atlas.ps1": "atlas_service.py",
        "run_dashboard.ps1": "web_app:app",
    }

    for relative_path, expected_route in canonical_route.items():
        content = (REPOSITORY_ROOT / relative_path).read_text(encoding="utf-8-sig")
        assert expected_route in content, relative_path
        assert "dashboard.app" not in content, relative_path
        assert "dashboard/app.py" not in content, relative_path


def test_merged_entry_point_is_in_the_canonical_distribution() -> None:
    """The launcher's target and everything it imports must ship.

    web_app.py imports observability/ at module scope, so a distribution
    without it cannot start the web surface at all.
    """

    manifest = _load_manifest(DEFAULT_MANIFEST)
    selected = select_distribution_files(
        REPOSITORY_ROOT,
        manifest,
        include_tests=False,
    )

    assert "atlas_service.py" in selected
    assert "observability/panel_router.py" in selected
    assert "observability/panel_sources.py" in selected


def test_legacy_dashboard_is_machine_marked_and_default_disabled() -> None:
    source = (REPOSITORY_ROOT / "dashboard" / "app.py").read_text(
        encoding="utf-8-sig"
    )
    assert "ATLAS_COMPONENT_STATUS = 'LEGACY_NON_CANONICAL'" in source
    assert "CANONICAL_WEB_ENTRY_POINT = 'web_app:app'" in source
    assert "ATLAS_ENABLE_LEGACY_DASHBOARD" in source
    assert "atlas-ai-secret-key-2026-v2" not in source
    assert "ATLAS_LEGACY_DASHBOARD_SECRET" in source
    assert "app.run(host='127.0.0.1'" in source
    assert "app.run(host='0.0.0.0'" not in source
