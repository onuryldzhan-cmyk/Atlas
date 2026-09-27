"""CI build-status gate for the permanently-accepted GRANT-B2-PERMANENT-CLOSURE case.

Registry v4.63's GRANT-B2-PERMANENT-CLOSURE
(governance/findings/ARCH-EDGE-001_ANCESTOR_PACKAGE_FORBIDDEN_EDGES.md) is a
final owner decision: the two atlas_finance ancestor-package forbidden edges
below stay open and RED, permanently, by design. No test file, xfail/skip
marker, or ``permitted_exceptions`` entry may make the architecture gate
report them as passing, without a new owner decision that explicitly
supersedes that one.

Hosted CI (F-006, .github/workflows/atlas_ci_cd.yml) otherwise treats any
pytest failure as a build failure, which would make the CI build
permanently red for a condition already, deliberately, permanently
accepted. This script is the narrow CI-side carve-out registry v4.90
authorizes: the aggregate build is reported PASSING only when the suite's
sole failing/erroring testcase is exactly
``tests/architecture/test_forbidden_layer_imports.py::test_forbidden_layer_imports``
and that test's own re-derived violation set is exactly the two known
edges below - nothing more, nothing less, and no other test failing.

This does not touch the test itself, does not add a ``permitted_exceptions``
entry, and does not add an xfail/skip marker anywhere. The test's own
output (and the JUnit XML this script reads) is unmodified and still
reports the failure; only this script's independent PASS/FAIL verdict
about the *aggregate build* accounts for the known-accepted case.

Usage
-----
    python tools/ci_check_known_accepted_b2_failure.py --junit-xml reports/observability/test_results.junit.xml

Exits 0 (PASS) when the suite is fully green, or when the only
failure/error is exactly the known GRANT-B2-PERMANENT-CLOSURE case. Exits 1
(FAIL) for anything else - a different test failing, more than one failing
testcase, the same test failing for a different reason (e.g. an unassigned
module), or the re-derived edge set differing from the known two edges in
any way.
"""

from __future__ import annotations

import argparse
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

from tools.build_architecture_inventory import (  # noqa: E402
    ENTRY_POINTS,
    REPOSITORY_ROOT as INVENTORY_REPOSITORY_ROOT,
    compute_module_layers,
    compute_runtime_closure,
    find_forbidden_edges,
    load_architecture_map,
)

TARGET_TEST_NAME = "test_forbidden_layer_imports"
TARGET_TEST_FILE_SUFFIX = "test_forbidden_layer_imports"

# The exact, and only, (importer, imported) edges GRANT-B2-PERMANENT-CLOSURE
# (registry v4.63) accepts as permanently red. Any edge not in this set, or
# any edge in this set that fails to appear, means the situation has moved
# and this carve-out no longer describes the repository - a new owner
# decision would be required, not a widening of this script.
KNOWN_ACCEPTED_EDGES = frozenset(
    {
        ("atlas_finance/market_data/contracts.py", "atlas_finance/__init__.py"),
        (
            "atlas_finance/market_data/contracts.py",
            "atlas_finance/market_data/__init__.py",
        ),
    }
)


def parse_violation(violation: str) -> tuple[str, str]:
    """Split a ``find_forbidden_edges`` violation string into (from, to).

    The detector emits ``"{from} -> {to} ({reason})"``
    (``tools/build_architecture_inventory.py``'s ``find_forbidden_edges``).
    Parsing structurally rather than matching the reason text keeps this
    check unaffected by future edits to a rule's ``reason`` wording.
    """

    left, _, remainder = violation.partition(" -> ")
    to_part, _, _reason = remainder.partition(" (")
    return left.strip(), to_part.strip()


def parse_junit_failed_testcases(xml_text: str) -> list[tuple[str, str]]:
    """Return (classname, name) for every testcase with a failure or error."""

    root = ET.fromstring(xml_text)
    failed: list[tuple[str, str]] = []
    for testcase in root.iter("testcase"):
        if testcase.find("failure") is not None or testcase.find("error") is not None:
            failed.append((testcase.get("classname", ""), testcase.get("name", "")))
    return failed


def evaluate_build_status(
    failed_testcases: list[tuple[str, str]],
    *,
    unassigned: list[str],
    violations: list[str],
) -> tuple[bool, str]:
    """Decide the aggregate CI build verdict.

    Pure decision function - deliberately takes plain values (parsed JUnit
    results, plus the independently re-derived unassigned/violations sets)
    rather than reading any file itself, so every input is visible in one
    signature and the decision is exhaustively testable without a real
    pytest run or a real architecture-map mutation.
    """

    if not failed_testcases:
        return True, "JUnit XML reports zero failing/erroring testcases."

    if len(failed_testcases) != 1:
        return False, (
            "expected at most the one known GRANT-B2-PERMANENT-CLOSURE failure, "
            f"found {len(failed_testcases)} failing/erroring testcases: {failed_testcases}"
        )

    classname, name = failed_testcases[0]
    if name != TARGET_TEST_NAME or not classname.endswith(TARGET_TEST_FILE_SUFFIX):
        return False, (
            "the one failing testcase is not the known GRANT-B2-PERMANENT-CLOSURE "
            f"case: classname={classname!r} name={name!r}"
        )

    if unassigned:
        return False, (
            "test_forbidden_layer_imports failed for a different reason than "
            f"GRANT-B2-PERMANENT-CLOSURE: unassigned modules {unassigned}"
        )

    observed_edges = {parse_violation(v) for v in violations}

    if observed_edges != KNOWN_ACCEPTED_EDGES:
        missing = KNOWN_ACCEPTED_EDGES - observed_edges
        unexpected = observed_edges - KNOWN_ACCEPTED_EDGES
        return False, (
            "the forbidden-edge set no longer matches GRANT-B2-PERMANENT-CLOSURE's "
            f"known-accepted set. missing={sorted(missing)} unexpected={sorted(unexpected)}"
        )

    return True, (
        "the only failure is test_forbidden_layer_imports, reporting exactly "
        "the two edges GRANT-B2-PERMANENT-CLOSURE (registry v4.63) permanently "
        "accepts as red."
    )


def _recompute_unassigned_and_violations() -> tuple[list[str], list[str]]:
    """Re-run the same detector tests/architecture/test_forbidden_layer_imports.py
    calls, independently of pytest's own JUnit failure text."""

    architecture_map = load_architecture_map()
    closure = compute_runtime_closure(INVENTORY_REPOSITORY_ROOT, ENTRY_POINTS)
    assigned, unassigned = compute_module_layers(closure, architecture_map["layer_rules"])

    if unassigned:
        return unassigned, []

    violations = find_forbidden_edges(
        INVENTORY_REPOSITORY_ROOT,
        closure,
        assigned,
        architecture_map["forbidden_edges"],
        architecture_map.get("permitted_exceptions", []),
    )
    return unassigned, violations


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--junit-xml", required=True, type=Path)
    args = parser.parse_args(argv)

    if not args.junit_xml.is_file():
        print(f"FAIL: JUnit XML artifact not found: {args.junit_xml}", file=sys.stderr)
        return 1

    xml_text = args.junit_xml.read_text(encoding="utf-8")
    failed_testcases = parse_junit_failed_testcases(xml_text)

    unassigned: list[str] = []
    violations: list[str] = []
    if failed_testcases:
        unassigned, violations = _recompute_unassigned_and_violations()

    ok, message = evaluate_build_status(
        failed_testcases,
        unassigned=unassigned,
        violations=violations,
    )

    if ok:
        print(f"PASS: {message}")
        return 0

    print(f"FAIL: {message}", file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())
