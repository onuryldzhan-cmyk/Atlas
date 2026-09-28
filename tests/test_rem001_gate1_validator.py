"""Tests for tools/rem001_gate1_validator.py (REM-001 Gate 1, D9 candidate).

Every test builds a throwaway repository under tmp_path, except the last,
which runs read-only against the real repository.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from tools import rem001_gate1_validator as validator


SOURCES = {
    "main.py": b"import core.a\n",
    "core/a.py": b"VALUE = 1\n",
}


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest().upper()


def _write(root: Path, relative: str, content: str | bytes) -> None:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(content, bytes):
        path.write_bytes(content)
    else:
        path.write_text(content, encoding="utf-8")


def _module(path: str) -> dict:
    return {
        "module_id": "MOD-" + path.replace("/", ".").removesuffix(".py").upper(),
        "file_path": path,
        "evidence": {"source_sha256": _sha(SOURCES[path])},
    }


def _build(root: Path, *, all_nine: bool = True) -> None:
    for path, data in SOURCES.items():
        _write(root, path, data)

    modules = [_module(path) for path in SOURCES]
    _write(root, validator.RUNTIME_CLOSURE_PATH, json.dumps({"modules": list(SOURCES)}))
    _write(root, "REM-001_CANONICAL_COMPONENT_MATRIX.json", json.dumps({"modules": modules, "counts": {"total_modules": len(modules)}}))
    _write(root, "REM-001_CANONICAL_COMPONENT_MATRIX.md", "\n".join(m["file_path"] for m in modules))
    _write(
        root,
        "packaging/REM-001_IMPORT_GRAPH.json",
        json.dumps({"nodes": [{"module": p, "runtime_reachable": True} for p in SOURCES] + [{"module": "tools/x.py", "runtime_reachable": False}]}),
    )
    _write(root, "packaging/REM-001_RUNTIME_CONSTRUCTION_PATHS.md", "d4")
    _write(root, "packaging/REM-001_STATE_AUTHORITY_MAP.md", "d5")
    _write(
        root,
        "REM-001_OVERLAP_REGISTER.json",
        json.dumps({"overlap_entries": [{"overlap_id": "OVL-001", "components": [{"module_id": modules[1]["module_id"], "file_path": "core/a.py"}]}]}),
    )

    if all_nine:
        _write(root, "REM-001_LEGACY_RETIREMENT_REGISTER.json", json.dumps({"entries": [{"module_id": modules[0]["module_id"]}]}))
        _write(root, "REM-001_SPECIFICATION_RECONCILIATION_MATRIX.md", "d8")
        _write(root, "REM-001_GATE1_VALIDATOR.ps1", "d9")


def _checks(result: dict, severity: str = validator.ERROR) -> list[str]:
    return [f["check"] for f in result["findings"] if f["severity"] == severity]


def _d1(root: Path) -> dict:
    return json.loads((root / "REM-001_CANONICAL_COMPONENT_MATRIX.json").read_text(encoding="utf-8"))


def _save_d1(root: Path, data: dict) -> None:
    _write(root, "REM-001_CANONICAL_COMPONENT_MATRIX.json", json.dumps(data))


def test_consistent_complete_set_has_no_errors(tmp_path: Path) -> None:
    _build(tmp_path)
    result = validator.validate(tmp_path)

    assert result["result"] == "NO_ERRORS", result["findings"]
    assert result["deliverables_present_count"] == 9
    assert result["certification_effect"].startswith("NONE")
    assert validator.main(["--root", str(tmp_path)]) == 0


@pytest.mark.parametrize("key", ["D7", "D8", "D9"])
def test_each_missing_deliverable_is_an_error(tmp_path: Path, key: str) -> None:
    _build(tmp_path)
    target = next(d for d in validator.DELIVERABLES if d.key == key)
    (tmp_path / target.path).unlink()

    result = validator.validate(tmp_path)

    assert any(f["check"] == "presence" and key in f["message"] for f in result["findings"])
    assert validator.main(["--root", str(tmp_path)]) == 1


def test_missing_d1_skips_cross_checks_but_fails(tmp_path: Path) -> None:
    _build(tmp_path)
    (tmp_path / "REM-001_CANONICAL_COMPONENT_MATRIX.json").unlink()

    result = validator.validate(tmp_path)

    assert _checks(result) == ["presence"]


def test_invalid_json_is_a_parse_error(tmp_path: Path) -> None:
    _build(tmp_path)
    _write(tmp_path, "REM-001_OVERLAP_REGISTER.json", "{not json")

    assert "parse" in _checks(validator.validate(tmp_path))


def test_population_drift_is_reported_both_ways(tmp_path: Path) -> None:
    _build(tmp_path)
    _write(tmp_path, validator.RUNTIME_CLOSURE_PATH, json.dumps({"modules": ["main.py", "core/b.py"]}))

    finding = next(f for f in validator.validate(tmp_path)["findings"] if f["check"] == "d1_population")

    assert finding["detail"] == {"in_closure_not_in_d1": ["core/b.py"], "in_d1_not_in_closure": ["core/a.py"]}


def test_population_drift_in_one_direction_only_is_reported(tmp_path: Path) -> None:
    _build(tmp_path)
    _write(tmp_path, validator.RUNTIME_CLOSURE_PATH, json.dumps({"modules": [*SOURCES, "core/b.py"]}))

    finding = next(f for f in validator.validate(tmp_path)["findings"] if f["check"] == "d1_population")

    assert finding["detail"] == {"in_closure_not_in_d1": ["core/b.py"], "in_d1_not_in_closure": []}


def test_changed_source_is_stale(tmp_path: Path) -> None:
    _build(tmp_path)
    _write(tmp_path, "core/a.py", b"VALUE = 2\n")

    finding = next(f for f in validator.validate(tmp_path)["findings"] if f["check"] == "d1_sources")

    assert finding["detail"]["modules"] == ["core/a.py"]


def test_crlf_checkout_of_unchanged_source_is_not_stale(tmp_path: Path) -> None:
    _build(tmp_path)
    _write(tmp_path, "core/a.py", SOURCES["core/a.py"].replace(b"\n", b"\r\n"))

    assert "d1_sources" not in _checks(validator.validate(tmp_path))


def test_deleted_source_is_reported(tmp_path: Path) -> None:
    _build(tmp_path)
    (tmp_path / "core/a.py").unlink()

    finding = next(f for f in validator.validate(tmp_path)["findings"] if f["check"] == "d1_sources")

    assert "no longer exists" in finding["message"]


def test_duplicate_module_id_and_bad_count_are_structure_errors(tmp_path: Path) -> None:
    _build(tmp_path)
    data = _d1(tmp_path)
    data["modules"][1]["module_id"] = data["modules"][0]["module_id"]
    data["counts"]["total_modules"] = 7
    _save_d1(tmp_path, data)

    messages = [f["message"] for f in validator.validate(tmp_path)["findings"] if f["check"] == "d1_structure"]

    assert any("duplicate module_id" in m for m in messages)
    assert any("total_modules" in m for m in messages)


def test_module_without_hash_is_an_error(tmp_path: Path) -> None:
    _build(tmp_path)
    data = _d1(tmp_path)
    del data["modules"][0]["evidence"]
    _save_d1(tmp_path, data)

    finding = next(f for f in validator.validate(tmp_path)["findings"] if f["check"] == "d1_sources")

    assert "source_sha256" in finding["message"]


def test_d2_missing_a_module_is_an_error(tmp_path: Path) -> None:
    _build(tmp_path)
    _write(tmp_path, "REM-001_CANONICAL_COMPONENT_MATRIX.md", "main.py only")

    assert "d2_transcription" in _checks(validator.validate(tmp_path))


def test_d3_disagreeing_with_d1_is_an_error(tmp_path: Path) -> None:
    _build(tmp_path)
    _write(tmp_path, "packaging/REM-001_IMPORT_GRAPH.json", json.dumps({"nodes": [{"module": "main.py", "runtime_reachable": True}]}))

    checks = _checks(validator.validate(tmp_path))

    assert "d3_consistency" in checks and "d3_population" in checks


def test_d6_component_outside_d1_is_an_error(tmp_path: Path) -> None:
    _build(tmp_path)
    _write(
        tmp_path,
        "REM-001_OVERLAP_REGISTER.json",
        json.dumps({"overlap_entries": [{"overlap_id": "OVL-9", "components": [{"module_id": "MOD-X", "file_path": "x.py"}]}]}),
    )

    assert "d6_consistency" in _checks(validator.validate(tmp_path))


def test_d6_component_with_mismatched_module_id_is_an_error(tmp_path: Path) -> None:
    _build(tmp_path)
    _write(
        tmp_path,
        "REM-001_OVERLAP_REGISTER.json",
        json.dumps({"overlap_entries": [{"overlap_id": "OVL-1", "components": [{"module_id": "MOD-WRONG", "file_path": "core/a.py"}]}]}),
    )

    assert "d6_consistency" in _checks(validator.validate(tmp_path))


def test_d6_component_left_the_closure_is_a_warning_only(tmp_path: Path) -> None:
    _build(tmp_path)
    _write(tmp_path, validator.RUNTIME_CLOSURE_PATH, json.dumps({"modules": ["main.py"]}))

    result = validator.validate(tmp_path)

    assert "d6_population" in _checks(result, validator.WARNING)
    assert "d6_population" not in _checks(result)


def test_d7_referencing_unknown_module_is_an_error(tmp_path: Path) -> None:
    _build(tmp_path)
    _write(tmp_path, "REM-001_LEGACY_RETIREMENT_REGISTER.json", json.dumps({"entries": [{"nested": {"module_id": "MOD-NOPE"}}]}))

    assert "d7_consistency" in _checks(validator.validate(tmp_path))


def test_unreadable_closure_is_an_error(tmp_path: Path) -> None:
    _build(tmp_path)
    (tmp_path / validator.RUNTIME_CLOSURE_PATH).unlink()

    assert "runtime_closure" in _checks(validator.validate(tmp_path))


def test_output_file_receives_the_report(tmp_path: Path) -> None:
    _build(tmp_path)
    out = tmp_path / "report.json"

    validator.main(["--root", str(tmp_path), "--output", str(out)])

    assert json.loads(out.read_text(encoding="utf-8"))["result"] == "NO_ERRORS"


def test_real_repository_run_is_read_only_and_fails_closed() -> None:
    root = validator.REPOSITORY_ROOT
    before = {d.path: (root / d.path).read_bytes() for d in validator.DELIVERABLES if (root / d.path).is_file()}

    result = validator.validate(root)

    after = {d.path: (root / d.path).read_bytes() for d in validator.DELIVERABLES if (root / d.path).is_file()}
    assert before == after
    # Gate 1 is open (registry: OPEN_NOT_CERTIFIED) and D7-D9 are not
    # produced, so the real run must never report NO_ERRORS today.
    assert result["result"] == "ERRORS_PRESENT"
