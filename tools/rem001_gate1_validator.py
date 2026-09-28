"""
REM-001 Gate 1 validator - Deliverable 9 CANDIDATE (Python).

Read-only. Checks the nine Gate 1 deliverables for presence, parseability,
internal consistency, and freshness against the repository as it is now,
and prints a JSON report. Exit code 0 only when no check reports an ERROR.

Status and limits (governance/ATLAS_REM001_GATE1_COMPLETION_PLAN_v1.0.md, S4):

- The registry names Deliverable 9 ``REM-001_GATE1_VALIDATOR.ps1``. This is
  a Python candidate produced pending an owner decision on language and on
  the check list; it does not replace the registered deliverable.
- A passing run is evidence for review, never Gate 1 certification. Gate 1
  closure authority stays OWNER_ACCEPTANCE_REQUIRED.
- It repairs nothing and regenerates nothing; the only file it can write is
  the report named by --output.

Usage:
    python tools/rem001_gate1_validator.py [--root PATH] [--output FILE]
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]

RUNTIME_CLOSURE_PATH = "packaging/atlas_runtime_closure.json"


@dataclass(frozen=True)
class Deliverable:
    key: str
    path: str
    kind: str
    path_basis: str


# Paths of D1-D6 are where the registry's latest Gate 1 count record
# (d6_production_catchup_d7_closure_and_gate1_count_update) places them. D7 and
# D8 have never been produced; their location is assumed to follow D1, D2
# and D6 (repository root). D9 is the registered name.
DELIVERABLES = (
    Deliverable("D1", "REM-001_CANONICAL_COMPONENT_MATRIX.json", "json", "registry gate_1_deliverable_count_after_this_record"),
    Deliverable("D2", "REM-001_CANONICAL_COMPONENT_MATRIX.md", "text", "registry gate_1_deliverable_count_after_this_record"),
    Deliverable("D3", "packaging/REM-001_IMPORT_GRAPH.json", "json", "registry gate_1_deliverable_count_after_this_record"),
    Deliverable("D4", "packaging/REM-001_RUNTIME_CONSTRUCTION_PATHS.md", "text", "registry gate_1_deliverable_count_after_this_record"),
    Deliverable("D5", "packaging/REM-001_STATE_AUTHORITY_MAP.md", "text", "registry gate_1_deliverable_count_after_this_record"),
    Deliverable("D6", "REM-001_OVERLAP_REGISTER.json", "json", "registry gate_1_deliverable_count_after_this_record"),
    Deliverable("D7", "REM-001_LEGACY_RETIREMENT_REGISTER.json", "json", "ASSUMED_REPOSITORY_ROOT"),
    Deliverable("D8", "REM-001_SPECIFICATION_RECONCILIATION_MATRIX.md", "text", "ASSUMED_REPOSITORY_ROOT"),
    Deliverable("D9", "REM-001_GATE1_VALIDATOR.ps1", "text", "registered name"),
)

ERROR = "ERROR"
WARNING = "WARNING"


@dataclass
class Report:
    findings: list[dict[str, Any]]

    def add(self, check: str, severity: str, message: str, **detail: Any) -> None:
        entry: dict[str, Any] = {"check": check, "severity": severity, "message": message}
        if detail:
            entry["detail"] = detail
        self.findings.append(entry)

    @property
    def error_count(self) -> int:
        return sum(1 for finding in self.findings if finding["severity"] == ERROR)


def _sha256_matches(data: bytes, expected: str) -> bool:
    """True when the bytes, or their LF-normalized form, hash to expected.

    D1 recorded LF hashes; a Windows checkout with autocrlf holds CRLF bytes
    for the same committed content. Either form counts as unchanged.
    """

    expected = expected.upper()
    if hashlib.sha256(data).hexdigest().upper() == expected:
        return True
    normalized = data.replace(b"\r\n", b"\n")
    return normalized != data and hashlib.sha256(normalized).hexdigest().upper() == expected


def _load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def _check_presence(root: Path, report: Report) -> dict[str, Any]:
    loaded: dict[str, Any] = {}

    for deliverable in DELIVERABLES:
        path = root / deliverable.path

        if not path.is_file():
            report.add(
                "presence",
                ERROR,
                f"{deliverable.key} not produced",
                path=deliverable.path,
                path_basis=deliverable.path_basis,
            )
            continue

        if deliverable.kind == "json":
            try:
                loaded[deliverable.key] = _load_json(path)
            except (ValueError, UnicodeDecodeError) as exc:
                report.add("parse", ERROR, f"{deliverable.key} is not valid JSON", path=deliverable.path, error=str(exc))
                continue
        else:
            try:
                loaded[deliverable.key] = path.read_text(encoding="utf-8-sig")
            except UnicodeDecodeError as exc:
                report.add("parse", ERROR, f"{deliverable.key} is not UTF-8 text", path=deliverable.path, error=str(exc))
                continue

    return loaded


def _d1_modules(d1: Any, report: Report) -> list[dict[str, Any]] | None:
    modules = d1.get("modules") if isinstance(d1, dict) else None

    if not isinstance(modules, list) or not all(isinstance(m, dict) for m in modules):
        report.add("d1_structure", ERROR, "D1 has no modules list of objects")
        return None

    ids = [m.get("module_id") for m in modules]
    paths = [m.get("file_path") for m in modules]

    if any(not isinstance(value, str) or not value for value in ids + paths):
        report.add("d1_structure", ERROR, "D1 module without a string module_id or file_path")
        return None

    for label, values in (("module_id", ids), ("file_path", paths)):
        duplicates = sorted({value for value in values if values.count(value) > 1})
        if duplicates:
            report.add("d1_structure", ERROR, f"D1 has duplicate {label} values", duplicates=duplicates)

    counts = d1.get("counts")
    declared = counts.get("total_modules") if isinstance(counts, dict) else None
    if declared != len(modules):
        report.add("d1_structure", ERROR, "D1 counts.total_modules disagrees with its modules list", declared=declared, actual=len(modules))

    return modules


def _check_d1_freshness(root: Path, modules: list[dict[str, Any]], closure: list[str] | None, report: Report) -> None:
    population = {m["file_path"] for m in modules}

    if closure is not None:
        added = sorted(set(closure) - population)
        removed = sorted(population - set(closure))
        if added or removed:
            report.add(
                "d1_population",
                ERROR,
                "D1 population differs from the current runtime closure",
                in_closure_not_in_d1=added,
                in_d1_not_in_closure=removed,
            )

    stale: list[str] = []
    missing: list[str] = []
    unhashed: list[str] = []

    for module in modules:
        evidence = module.get("evidence")
        expected = evidence.get("source_sha256") if isinstance(evidence, dict) else None
        path = root / module["file_path"]

        if not path.is_file():
            missing.append(module["file_path"])
        elif not isinstance(expected, str) or not expected:
            unhashed.append(module["file_path"])
        elif not _sha256_matches(path.read_bytes(), expected):
            stale.append(module["file_path"])

    if missing:
        report.add("d1_sources", ERROR, "D1 modules whose source file no longer exists", modules=sorted(missing))
    if unhashed:
        report.add("d1_sources", ERROR, "D1 modules without a source_sha256", modules=sorted(unhashed))
    if stale:
        report.add(
            "d1_sources",
            ERROR,
            "D1 modules whose source changed since D1 was generated",
            count=len(stale),
            modules=sorted(stale),
        )


def _check_d2(d2: str, modules: list[dict[str, Any]], report: Report) -> None:
    absent = sorted(m["file_path"] for m in modules if m["file_path"] not in d2)
    if absent:
        report.add("d2_transcription", ERROR, "D2 does not mention every D1 module", modules=absent)


def _check_d3(d3: Any, modules: list[dict[str, Any]], closure: list[str] | None, report: Report) -> None:
    nodes = d3.get("nodes") if isinstance(d3, dict) else None

    if not isinstance(nodes, list):
        report.add("d3_structure", ERROR, "D3 has no nodes list")
        return

    reachable = {
        node.get("module")
        for node in nodes
        if isinstance(node, dict) and node.get("runtime_reachable") is True
    }
    population = {m["file_path"] for m in modules}

    if reachable != population:
        report.add(
            "d3_consistency",
            ERROR,
            "D3 runtime-reachable nodes differ from the D1 population",
            reachable_not_in_d1=sorted(reachable - population),
            d1_not_reachable_in_d3=sorted(population - reachable),
        )

    if closure is not None and reachable != set(closure):
        report.add(
            "d3_population",
            ERROR,
            "D3 runtime-reachable nodes differ from the current runtime closure",
            in_closure_not_in_d3=sorted(set(closure) - reachable),
            in_d3_not_in_closure=sorted(reachable - set(closure)),
        )


def _check_d6(d6: Any, modules: list[dict[str, Any]], closure: list[str] | None, report: Report) -> None:
    entries = d6.get("overlap_entries") if isinstance(d6, dict) else None

    if not isinstance(entries, list):
        report.add("d6_structure", ERROR, "D6 has no overlap_entries list")
        return

    population = {m["file_path"] for m in modules}
    ids = {m["module_id"] for m in modules}

    for entry in entries:
        if not isinstance(entry, dict):
            report.add("d6_structure", ERROR, "D6 overlap entry is not an object")
            continue

        overlap_id = entry.get("overlap_id")
        components = entry.get("components")

        if not isinstance(components, list) or not components:
            report.add("d6_structure", ERROR, "D6 overlap entry has no components", overlap_id=overlap_id)
            continue

        for component in components:
            path = component.get("file_path") if isinstance(component, dict) else None
            module_id = component.get("module_id") if isinstance(component, dict) else None

            if path not in population or module_id not in ids:
                report.add(
                    "d6_consistency",
                    ERROR,
                    "D6 component is not a D1 module",
                    overlap_id=overlap_id,
                    file_path=path,
                    module_id=module_id,
                )
            elif closure is not None and path not in closure:
                report.add(
                    "d6_population",
                    WARNING,
                    "D6 component is no longer in the current runtime closure",
                    overlap_id=overlap_id,
                    file_path=path,
                )


def _check_d7(d7: Any, modules: list[dict[str, Any]], report: Report) -> None:
    ids = {m["module_id"] for m in modules}
    referenced: set[str] = set()

    def walk(value: Any) -> None:
        if isinstance(value, dict):
            for key, item in value.items():
                if key == "module_id" and isinstance(item, str):
                    referenced.add(item)
                walk(item)
        elif isinstance(value, list):
            for item in value:
                walk(item)

    walk(d7)
    unknown = sorted(referenced - ids)
    if unknown:
        report.add("d7_consistency", ERROR, "D7 references module_ids absent from D1", module_ids=unknown)


def validate(root: Path) -> dict[str, Any]:
    report = Report(findings=[])
    loaded = _check_presence(root, report)

    closure: list[str] | None = None
    closure_path = root / RUNTIME_CLOSURE_PATH
    try:
        closure_data = _load_json(closure_path)
        closure = list(closure_data["modules"])
    except (OSError, ValueError, KeyError, TypeError) as exc:
        report.add("runtime_closure", ERROR, "current runtime closure unreadable", path=RUNTIME_CLOSURE_PATH, error=str(exc))

    modules = _d1_modules(loaded["D1"], report) if "D1" in loaded else None

    if modules is not None:
        _check_d1_freshness(root, modules, closure, report)
        if "D2" in loaded:
            _check_d2(loaded["D2"], modules, report)
        if "D3" in loaded:
            _check_d3(loaded["D3"], modules, closure, report)
        if "D6" in loaded:
            _check_d6(loaded["D6"], modules, closure, report)
        if "D7" in loaded:
            _check_d7(loaded["D7"], modules, report)

    produced = [d.key for d in DELIVERABLES if (root / d.path).is_file()]

    return {
        "validator": "tools/rem001_gate1_validator.py",
        "validator_status": "D9_CANDIDATE_PENDING_OWNER_DECISION",
        "result": "NO_ERRORS" if report.error_count == 0 else "ERRORS_PRESENT",
        "certification_effect": "NONE - evidence for owner review only; Gate 1 closure requires owner acceptance",
        "deliverables_present": produced,
        "deliverables_present_count": len(produced),
        "deliverables_expected_count": len(DELIVERABLES),
        "error_count": report.error_count,
        "warning_count": sum(1 for f in report.findings if f["severity"] == WARNING),
        "findings": report.findings,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="REM-001 Gate 1 validator (D9 candidate, read-only).")
    parser.add_argument("--root", type=Path, default=REPOSITORY_ROOT)
    parser.add_argument("--output", type=Path, default=None, help="also write the JSON report to this file")
    args = parser.parse_args(argv)

    result = validate(args.root.resolve())
    text = json.dumps(result, indent=2, ensure_ascii=False)
    print(text)

    if args.output is not None:
        args.output.write_text(text + "\n", encoding="utf-8")

    return 0 if result["error_count"] == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
