"""Block 2C Part D: deterministic build provenance record.

Covers H7-H9 / P6-P7 from the Block 2C work order: the generator is
deterministic (except the explicitly time-varying build_timestamp),
contains current git/runtime hashes, never claims LIVE authority, and
never records a secret value.
"""

from __future__ import annotations

import subprocess

import pytest

from tools.build_provenance_record import (
    REPOSITORY_ROOT,
    ProvenanceError,
    _sha256_file,
    build_provenance_record,
)


def _actual_git_commit() -> str:
    completed = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=REPOSITORY_ROOT,
        check=True, capture_output=True, text=True,
    )
    return completed.stdout.strip()


def test_provenance_record_deterministic_except_timestamp():
    first = build_provenance_record()
    second = build_provenance_record()

    first_without_timestamp = {k: v for k, v in first.items() if k != "build_timestamp"}
    second_without_timestamp = {k: v for k, v in second.items() if k != "build_timestamp"}
    assert first_without_timestamp == second_without_timestamp


def test_provenance_contains_current_git_and_manifest_hashes():
    record = build_provenance_record()
    assert record["git_commit"] == _actual_git_commit()
    assert record["artifact_id"] == f"atlas-{_actual_git_commit()[:12]}"
    assert len(record["dependency_manifest_hash"]) == 64
    assert len(record["runtime_manifest_hash"]) == 64
    assert len(record["architecture_map_hash"]) == 64
    assert isinstance(record["dirty_worktree"], bool)


def test_provenance_schema_version_and_test_result_field():
    record = build_provenance_record(test_result="1166 passed")
    assert record["schema_version"] == "1.0"
    assert record["test_result"] == "1166 passed"


def test_provenance_rejects_live_build_mode():
    with pytest.raises(ProvenanceError, match="LIVE"):
        build_provenance_record(build_mode="LIVE")


def test_provenance_never_claims_live_authority():
    record = build_provenance_record(build_mode="PAPER")
    assert record["paper_only"] is True
    assert record["live_authority"] is False
    assert record["build_mode"] == "PAPER"


def test_provenance_record_never_contains_secret_markers():
    record = build_provenance_record()
    serialized = str(record).lower()
    for marker in ("api_key", "password", "secret_key", "bearer "):
        assert marker not in serialized


def test_sha256_file_raises_on_missing_input(tmp_path):
    with pytest.raises(ProvenanceError, match="required input missing"):
        _sha256_file(tmp_path / "does-not-exist.json")
