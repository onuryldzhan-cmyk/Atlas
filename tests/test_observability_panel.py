"""Contract tests for the read-only observability panel sources and router.

These tests never run pytest recursively and never read the repository's
runtime state: every case builds an isolated fixture root under tmp_path.
Two tests deliberately read the real repository (governance registries and
web_app.py source) because that is the contract being asserted.
"""

from __future__ import annotations

import ast
import json

from pathlib import Path

import pytest

from observability import panel_sources
from observability.panel_router import build_observability_router

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]

VALID_SUITES_XML = """<?xml version="1.0" encoding="utf-8"?>
<testsuites>
  <testsuite name="pytest" errors="1" failures="2" skipped="3" tests="100"
             time="12.5" timestamp="2026-08-29T10:00:00.000000">
  </testsuite>
</testsuites>
"""

SINGLE_SUITE_XML = """<?xml version="1.0" encoding="utf-8"?>
<testsuite name="pytest" errors="0" failures="0" skipped="0" tests="7"
           time="1.25" timestamp="2026-08-29T10:00:00.000000">
</testsuite>
"""

HEAD_COMMIT = "0123456789abcdef0123456789abcdef01234567"


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _make_git(root: Path, commit: str = HEAD_COMMIT) -> None:
    _write(root / ".git" / "HEAD", "ref: refs/heads/work\n")
    _write(root / ".git" / "refs" / "heads" / "work", f"{commit}\n")


def _write_artifact(root: Path, xml: str = VALID_SUITES_XML) -> None:
    _write(root / panel_sources.TEST_RESULTS_ARTIFACT_RELPATH, xml)


def _write_meta(root: Path, commit: str | None = HEAD_COMMIT) -> None:
    _write(
        root / panel_sources.TEST_RESULTS_META_RELPATH,
        json.dumps(
            {
                "commit": commit,
                "generated_at": "2026-08-29T10:00:00+00:00",
                "command": ["python", "-m", "pytest"],
                "pytest_exit_code": 0,
                "target": "tests",
            }
        ),
    )


def _registry(version: str, supersedes: str | None, **extra: object) -> str:
    payload: dict[str, object] = {
        "schema_version": version,
        "registry_status": "CANONICAL",
    }

    if supersedes is not None:
        payload["supersedes"] = f"governance/current/{supersedes}"

    payload["governance_reconciliation"] = {
        "id": "GOV-DRIFT-001",
        "status": "RECONCILED_BY_VERSIONED_SUCCESSOR",
        "severity": "P1",
    }
    payload.update(extra)

    return json.dumps(payload)


def _write_registry(root: Path, name: str, content: str) -> None:
    _write(root / panel_sources.GOVERNANCE_CURRENT_RELPATH / name, content)


def _write_registry_chain(root: Path) -> None:
    _write_registry(root, "R_v1.0.json", _registry("1.0", "R_v0.9.json"))
    _write_registry(root, "R_v1.1.json", _registry("1.1", "R_v1.0.json"))


# ---------------------------------------------------------------------------
# Panel (b): test results artifact
# ---------------------------------------------------------------------------


def test_valid_artifact_reports_derived_counts(tmp_path: Path) -> None:
    _make_git(tmp_path)
    _write_artifact(tmp_path)
    _write_meta(tmp_path)

    panel = panel_sources.read_test_results_panel(tmp_path)

    assert panel["available"] is True
    assert panel["totals"] == {
        "tests": 100,
        "passed": 94,
        "failed": 2,
        "errors": 1,
        "skipped": 3,
    }
    assert panel["duration_seconds"] == 12.5
    assert panel["suite_timestamp"] == "2026-08-29T10:00:00.000000"
    assert panel["provenance"]["available"] is True
    assert panel["commit_alignment"] == {
        "state": "MATCH",
        "artifact_commit": HEAD_COMMIT,
        "head_commit": HEAD_COMMIT,
    }


def test_single_testsuite_root_is_supported(tmp_path: Path) -> None:
    _write_artifact(tmp_path, SINGLE_SUITE_XML)

    panel = panel_sources.read_test_results_panel(tmp_path)

    assert panel["available"] is True
    assert panel["totals"]["tests"] == 7
    assert panel["totals"]["passed"] == 7


def test_missing_artifact_is_unavailable_not_invented(tmp_path: Path) -> None:
    panel = panel_sources.read_test_results_panel(tmp_path)

    assert panel["available"] is False
    assert panel["reason"] == "ARTIFACT_MISSING"
    assert "totals" not in panel


def test_malformed_artifact_is_unavailable(tmp_path: Path) -> None:
    _write_artifact(tmp_path, "<testsuites><testsuite tests='1'>")

    panel = panel_sources.read_test_results_panel(tmp_path)

    assert panel["available"] is False
    assert panel["reason"] == "ARTIFACT_MALFORMED"
    assert "totals" not in panel


def test_artifact_with_unexpected_root_is_unavailable(tmp_path: Path) -> None:
    _write_artifact(tmp_path, "<report tests='4'></report>")

    panel = panel_sources.read_test_results_panel(tmp_path)

    assert panel["available"] is False
    assert panel["reason"] == "ARTIFACT_MALFORMED"


def test_artifact_without_tests_attribute_is_unavailable(tmp_path: Path) -> None:
    _write_artifact(tmp_path, "<testsuite name='pytest' failures='0'></testsuite>")

    panel = panel_sources.read_test_results_panel(tmp_path)

    assert panel["available"] is False
    assert panel["reason"] == "ARTIFACT_MALFORMED"


def test_artifact_with_doctype_is_rejected(tmp_path: Path) -> None:
    _write_artifact(
        tmp_path,
        "<!DOCTYPE testsuite [ <!ENTITY a 'x'> ]>\n"
        "<testsuite tests='1' failures='0' errors='0' skipped='0'></testsuite>",
    )

    panel = panel_sources.read_test_results_panel(tmp_path)

    assert panel["available"] is False
    assert panel["reason"] == "ARTIFACT_REJECTED_DOCTYPE"


def test_inconsistent_counts_are_rejected(tmp_path: Path) -> None:
    _write_artifact(
        tmp_path,
        "<testsuite tests='2' failures='5' errors='0' skipped='0'></testsuite>",
    )

    panel = panel_sources.read_test_results_panel(tmp_path)

    assert panel["available"] is False
    assert panel["reason"] == "ARTIFACT_INCONSISTENT"


def test_missing_sidecar_leaves_commit_alignment_unknown(tmp_path: Path) -> None:
    _make_git(tmp_path)
    _write_artifact(tmp_path)

    panel = panel_sources.read_test_results_panel(tmp_path)

    assert panel["available"] is True
    assert panel["provenance"] == {"available": False, "reason": "META_MISSING"}
    assert panel["commit_alignment"]["state"] == "UNKNOWN"
    assert panel["commit_alignment"]["artifact_commit"] is None


def test_incomplete_sidecar_is_reported(tmp_path: Path) -> None:
    _write_artifact(tmp_path)
    _write(
        tmp_path / panel_sources.TEST_RESULTS_META_RELPATH,
        json.dumps({"commit": HEAD_COMMIT}),
    )

    panel = panel_sources.read_test_results_panel(tmp_path)

    assert panel["provenance"]["available"] is False
    assert panel["provenance"]["reason"] == "META_INCOMPLETE"


def test_stale_artifact_commit_is_surfaced(tmp_path: Path) -> None:
    _make_git(tmp_path, commit="f" * 40)
    _write_artifact(tmp_path)
    _write_meta(tmp_path, commit=HEAD_COMMIT)

    panel = panel_sources.read_test_results_panel(tmp_path)

    assert panel["available"] is True
    assert panel["commit_alignment"]["state"] == "STALE"
    assert panel["commit_alignment"]["head_commit"] == "f" * 40


def test_head_commit_resolves_from_packed_refs(tmp_path: Path) -> None:
    _write(tmp_path / ".git" / "HEAD", "ref: refs/heads/work\n")
    _write(
        tmp_path / ".git" / "packed-refs",
        "# pack-refs with: peeled fully-peeled sorted\n"
        f"{HEAD_COMMIT} refs/heads/work\n",
    )

    assert panel_sources.read_head_commit(tmp_path) == HEAD_COMMIT


def test_head_commit_is_none_without_git(tmp_path: Path) -> None:
    assert panel_sources.read_head_commit(tmp_path) is None


# ---------------------------------------------------------------------------
# Panel (c): governance reconciliation
# ---------------------------------------------------------------------------


def test_governance_panel_resolves_chain_head(tmp_path: Path) -> None:
    _write_registry_chain(tmp_path)

    panel = panel_sources.read_governance_panel(tmp_path)

    assert panel["available"] is True
    assert panel["registry_file"].endswith("R_v1.1.json")
    assert panel["schema_version"] == "1.1"
    assert panel["chain_depth"] == 2
    assert panel["reconciliation"]["id"] == "GOV-DRIFT-001"
    assert panel["reconciliation"]["status"] == "RECONCILED_BY_VERSIONED_SUCCESSOR"


def test_governance_head_is_not_chosen_by_filename_order(tmp_path: Path) -> None:
    # The head sorts first by name; only the supersedes chain identifies it.
    _write_registry(tmp_path, "A_head.json", _registry("2.0", "Z_older.json"))
    _write_registry(tmp_path, "Z_older.json", _registry("1.0", None))

    panel = panel_sources.read_governance_panel(tmp_path)

    assert panel["available"] is True
    assert panel["registry_file"].endswith("A_head.json")


def test_ambiguous_head_is_unavailable(tmp_path: Path) -> None:
    _write_registry(tmp_path, "R_v1.0.json", _registry("1.0", None))
    _write_registry(tmp_path, "R_v2.0.json", _registry("2.0", None))

    panel = panel_sources.read_governance_panel(tmp_path)

    assert panel["available"] is False
    assert panel["reason"] == "REGISTRY_HEAD_AMBIGUOUS"
    assert sorted(panel["candidate_heads"]) == ["R_v1.0.json", "R_v2.0.json"]


def test_detached_registry_makes_the_head_ambiguous(tmp_path: Path) -> None:
    # A registry nothing supersedes is a second head, not a silent orphan.
    _write_registry_chain(tmp_path)
    _write_registry(tmp_path, "R_detached.json", _registry("0.5", "R_gone.json"))

    panel = panel_sources.read_governance_panel(tmp_path)

    assert panel["available"] is False
    assert panel["reason"] == "REGISTRY_HEAD_AMBIGUOUS"
    assert "R_detached.json" in panel["candidate_heads"]


def test_unreachable_registry_cycle_breaks_the_chain(tmp_path: Path) -> None:
    # A detached cycle produces no extra head, so only the reachability walk
    # can catch it.
    _write_registry_chain(tmp_path)
    _write_registry(tmp_path, "R_x.json", _registry("0.4", "R_y.json"))
    _write_registry(tmp_path, "R_y.json", _registry("0.5", "R_x.json"))

    panel = panel_sources.read_governance_panel(tmp_path)

    assert panel["available"] is False
    assert panel["reason"] == "REGISTRY_CHAIN_BROKEN"
    assert panel["unreachable_files"] == ["R_x.json", "R_y.json"]


def test_cyclic_chain_is_unavailable(tmp_path: Path) -> None:
    _write_registry(tmp_path, "R_a.json", _registry("1.0", "R_b.json"))
    _write_registry(tmp_path, "R_b.json", _registry("1.1", "R_a.json"))

    panel = panel_sources.read_governance_panel(tmp_path)

    assert panel["available"] is False
    assert panel["reason"] == "REGISTRY_CHAIN_CYCLIC"


def test_malformed_registry_is_unavailable(tmp_path: Path) -> None:
    _write_registry_chain(tmp_path)
    _write_registry(tmp_path, "R_broken.json", "{not json")

    panel = panel_sources.read_governance_panel(tmp_path)

    assert panel["available"] is False
    assert panel["reason"] == "REGISTRY_MALFORMED"
    assert panel["unparseable_files"] == ["R_broken.json"]


def test_missing_registry_directory_is_unavailable(tmp_path: Path) -> None:
    panel = panel_sources.read_governance_panel(tmp_path)

    assert panel["available"] is False
    assert panel["reason"] == "REGISTRY_DIRECTORY_MISSING"


def test_missing_reconciliation_record_is_not_invented(tmp_path: Path) -> None:
    _write_registry(
        tmp_path,
        "R_v1.0.json",
        json.dumps({"schema_version": "1.0", "registry_status": "CANONICAL"}),
    )

    panel = panel_sources.read_governance_panel(tmp_path)

    assert panel["available"] is False
    assert panel["reason"] == "GOVERNANCE_RECONCILIATION_MISSING"
    assert "reconciliation" not in panel


def test_governance_panel_reads_the_real_repository() -> None:
    panel = panel_sources.read_governance_panel(REPOSITORY_ROOT)

    assert panel["available"] is True, panel
    assert panel["registry_file"].startswith("governance/current/")
    assert isinstance(panel["reconciliation"]["status"], str)
    assert panel["reconciliation"]["status"]


# ---------------------------------------------------------------------------
# Router
# ---------------------------------------------------------------------------


@pytest.fixture()
def client_factory():
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    def build(root: Path, *, client: tuple[str, int] | None = None):
        application = FastAPI()
        application.include_router(
            build_observability_router(repository_root=root)
        )

        if client is None:
            return TestClient(application)

        return TestClient(application, client=client)

    return build


def test_router_serves_available_panels(tmp_path: Path, client_factory) -> None:
    _make_git(tmp_path)
    _write_artifact(tmp_path)
    _write_meta(tmp_path)
    _write_registry_chain(tmp_path)

    client = client_factory(tmp_path)

    results = client.get("/api/observability/test-results")
    governance = client.get("/api/observability/governance")

    assert results.status_code == 200
    assert results.json()["totals"]["passed"] == 94
    assert governance.status_code == 200
    assert governance.json()["reconciliation"]["id"] == "GOV-DRIFT-001"


def test_router_fails_closed_when_sources_unavailable(
    tmp_path: Path,
    client_factory,
) -> None:
    client = client_factory(tmp_path)

    results = client.get("/api/observability/test-results")
    governance = client.get("/api/observability/governance")

    assert results.status_code == 503
    assert results.json()["available"] is False
    assert governance.status_code == 503
    assert governance.json()["available"] is False


def test_router_refuses_non_loopback_clients(
    tmp_path: Path,
    client_factory,
) -> None:
    _write_artifact(tmp_path)
    _write_registry_chain(tmp_path)

    client = client_factory(tmp_path, client=("203.0.113.7", 44321))

    for route in ("test-results", "governance"):
        response = client.get(f"/api/observability/{route}")

        assert response.status_code == 403
        assert response.json()["reason"] == "OBSERVABILITY_PANEL_IS_LOCALHOST_ONLY"


def test_router_never_triggers_a_test_run() -> None:
    source = (
        REPOSITORY_ROOT / "observability" / "panel_router.py"
    ).read_text(encoding="utf-8")
    sources = (
        REPOSITORY_ROOT / "observability" / "panel_sources.py"
    ).read_text(encoding="utf-8")

    for text in (source, sources):
        tree = ast.parse(text)
        imported = {
            alias.name.split(".")[0]
            for node in ast.walk(tree)
            if isinstance(node, ast.Import)
            for alias in node.names
        } | {
            node.module.split(".")[0]
            for node in ast.walk(tree)
            if isinstance(node, ast.ImportFrom) and node.module
        }

        assert "subprocess" not in imported
        assert "pytest" not in imported


def test_panel_sources_imports_no_web_framework() -> None:
    tree = ast.parse(
        (REPOSITORY_ROOT / "observability" / "panel_sources.py").read_text(
            encoding="utf-8"
        )
    )

    modules = {
        alias.name.split(".")[0]
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
        for alias in node.names
    } | {
        node.module.split(".")[0]
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module
    }

    assert modules.isdisjoint({"fastapi", "flask", "starlette"})


def test_create_app_performs_no_file_io() -> None:
    tree = ast.parse(
        (REPOSITORY_ROOT / "web_app.py").read_text(encoding="utf-8-sig")
    )

    create_app = next(
        node
        for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name == "create_app"
    )

    forbidden = {
        "open",
        "read_text",
        "read_bytes",
        "write_text",
        "glob",
        "iterdir",
        "load",
        "loads",
    }

    violations = [
        f"{node.func.attr if isinstance(node.func, ast.Attribute) else node.func.id}"
        f" at line {node.lineno}"
        for node in ast.walk(create_app)
        if isinstance(node, ast.Call)
        and (
            (isinstance(node.func, ast.Name) and node.func.id in forbidden)
            or (isinstance(node.func, ast.Attribute) and node.func.attr in forbidden)
        )
    ]

    assert violations == []
