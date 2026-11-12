"""CI build-status gate for permanently/durably accepted known test failures.

This script currently recognizes exactly two known-accepted failure cases,
each backed by its own independent owner decision. It was originally written
(commit 3159500) to recognize only B2 and was extended (this change) to also
recognize D5, without weakening either case's narrow-match discipline: a
test failing for a reason other than its own established one still fails the
build, exactly as before.

Case B2 - GRANT-B2-PERMANENT-CLOSURE (registry v4.63,
governance/findings/ARCH-EDGE-001_ANCESTOR_PACKAGE_FORBIDDEN_EDGES.md):
the two atlas_finance ancestor-package forbidden edges below stay open and
RED, permanently, by design. No test file, xfail/skip marker, or
``permitted_exceptions`` entry may make the architecture gate report them as
passing, without a new owner decision that explicitly supersedes that one.
The build is accepted only when
``tests/architecture/test_forbidden_layer_imports.py::test_forbidden_layer_imports``
is the failing testcase AND that test's own re-derived violation set is
exactly the two known edges below - nothing more, nothing less.

Case D5 - registry v4.97's closure of REM-001 Gate 1's certification path
(citing GOV-DRIFT-005's permanent specification loss) explicitly preserves
``tests/architecture/test_rem001_state_authority_map.py::test_committed_artifact_matches_current_source``
and its committed artifact (``packaging/REM-001_STATE_AUTHORITY_MAP.md``) as
an unedited historical artifact - not something to regenerate or retire.
Registry v4.99 established this as part of the authoritative 2-failure
baseline (``test_baseline_reconciliation_2026_09_28``). Unlike B2, the
artifact's exact diff against current source drifts with ordinary,
unrelated commits (line numbers, new persistence sites, entry points), so
there is no fixed reference content to re-derive and compare, the way B2's
forbidden-edge set is re-derived. What *is* stable is the test's own assertion message: it always fails via
an ``AssertionError`` whose first line is the literal string passed to its
own ``assert regenerated == committed, (...)`` statement
(``tests/architecture/test_rem001_state_authority_map.py``); pytest's own
assertion-rewrite machinery appends the (legitimately drifting, sometimes
truncated-by-verbosity) diff explanation as further lines after that first
one, which this script deliberately does not match. The build is accepted
only when that exact testcase (matched by its full classname, not merely by
test name - a second, unrelated test,
``tests/architecture/test_rem001_construction_paths.py``, defines a test of
the identical name for a different artifact and must never be conflated
with this one) fails with a message whose first line is exactly that known
string. A different first line (a parse failure, a different assertion, an
unrelated exception) still fails the build.

Hosted CI (F-006, .github/workflows/atlas_ci_cd.yml) otherwise treats any
pytest failure as a build failure, which would make the CI build
permanently red for two conditions already, deliberately, permanently
accepted. This script is the narrow CI-side carve-out registry v4.90
(B2) and this change (D5) authorize.

This does not touch either test itself, does not add a
``permitted_exceptions`` entry, and does not add an xfail/skip marker
anywhere. Each test's own output (and the JUnit XML this script reads) is
unmodified and still reports the failure; only this script's independent
PASS/FAIL verdict about the *aggregate build* accounts for the
known-accepted cases.

Usage
-----
    python tools/ci_check_known_accepted_failures.py --junit-xml reports/observability/test_results.junit.xml

Exits 0 (PASS) when the suite is fully green, or when every failing/erroring
testcase is one of the known-accepted B2/D5 cases (either alone, or both
together). Exits 1 (FAIL) for anything else - a different test failing, a
known test appearing more than once, the same test failing for a different
reason (a different message for D5; an unassigned module or a differing
edge set for B2), or any additional failing testcase alongside a known one.
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

B2_TEST_NAME = "test_forbidden_layer_imports"
B2_TEST_FILE_SUFFIX = "test_forbidden_layer_imports"

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

D5_TEST_NAME = "test_committed_artifact_matches_current_source"
# Exact classname, not a suffix: a second test of the identical name exists
# in tests/architecture/test_rem001_construction_paths.py (Gate 3, a
# different artifact) and must never be accepted under this D5 carve-out.
D5_TEST_CLASSNAME = "tests.architecture.test_rem001_state_authority_map"

# The exact, stable FIRST LINE of the JUnit failure message
# tests/architecture/test_rem001_state_authority_map.py's own
# ``assert regenerated == committed, (...)`` statement always raises, verified
# against this repository's actual generated JUnit XML. Pytest's assertion
# rewrite appends its own diff explanation as further lines after this one;
# that part legitimately drifts with unrelated commits (and its exact
# truncation point can vary with verbosity/terminal width) and is
# deliberately not matched - only the first line, matching this script's
# reason string, is.
D5_KNOWN_FAILURE_MESSAGE = (
    "AssertionError: packaging/REM-001_STATE_AUTHORITY_MAP.md is out of date; "
    "regenerate with: python -m tools.build_rem001_gate1_maps state --write"
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


def parse_junit_failed_testcases(xml_text: str) -> list[tuple[str, str, str | None]]:
    """Return (classname, name, message) for every testcase with a failure or error.

    ``message`` is the failing element's own ``message`` attribute (pytest's
    JUnit writer sets this to the exception's own first-line representation,
    e.g. ``"AssertionError: ..."``), independent of the much longer
    diff/traceback text in the element body. ``None`` if the element carries
    no message attribute at all.
    """

    root = ET.fromstring(xml_text)
    failed: list[tuple[str, str, str | None]] = []
    for testcase in root.iter("testcase"):
        node = testcase.find("failure")
        if node is None:
            node = testcase.find("error")
        if node is not None:
            failed.append(
                (testcase.get("classname", ""), testcase.get("name", ""), node.get("message"))
            )
    return failed


def _is_b2_testcase(testcase: tuple[str, str, str | None]) -> bool:
    classname, name, _message = testcase
    return name == B2_TEST_NAME and classname.endswith(B2_TEST_FILE_SUFFIX)


def _is_d5_testcase(testcase: tuple[str, str, str | None]) -> bool:
    classname, name, _message = testcase
    return classname == D5_TEST_CLASSNAME and name == D5_TEST_NAME


def _evaluate_b2(*, unassigned: list[str], violations: list[str]) -> tuple[bool, str]:
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
        "test_forbidden_layer_imports is reporting exactly the two edges "
        "GRANT-B2-PERMANENT-CLOSURE (registry v4.63) permanently accepts as red."
    )


def _evaluate_d5(testcase: tuple[str, str, str | None]) -> tuple[bool, str]:
    _classname, _name, message = testcase
    first_line = message.split("\n", 1)[0] if message is not None else None
    if first_line != D5_KNOWN_FAILURE_MESSAGE:
        return False, (
            "test_committed_artifact_matches_current_source "
            "(tests/architecture/test_rem001_state_authority_map.py) failed for a "
            f"different reason than the known D5 stale-artifact case: message={message!r}"
        )

    return True, (
        "test_committed_artifact_matches_current_source "
        "(tests/architecture/test_rem001_state_authority_map.py) is reporting exactly "
        "the known stale-artifact assertion registry v4.97/v4.99 accept as a permanent "
        "historical artifact (D5)."
    )


def evaluate_build_status(
    failed_testcases: list[tuple[str, str, str | None]],
    *,
    unassigned: list[str],
    violations: list[str],
) -> tuple[bool, str]:
    """Decide the aggregate CI build verdict.

    Pure decision function - deliberately takes plain values (parsed JUnit
    results, plus the independently re-derived B2 unassigned/violations
    sets) rather than reading any file itself, so every input is visible in
    one signature and the decision is exhaustively testable without a real
    pytest run or a real architecture-map mutation.
    """

    if not failed_testcases:
        return True, "JUnit XML reports zero failing/erroring testcases."

    b2_matches = [tc for tc in failed_testcases if _is_b2_testcase(tc)]
    d5_matches = [tc for tc in failed_testcases if _is_d5_testcase(tc)]
    unexplained = [tc for tc in failed_testcases if tc not in b2_matches and tc not in d5_matches]

    if unexplained:
        return False, (
            "found failing/erroring testcase(s) that are not one of the known-accepted "
            f"B2/D5 cases: {[(c, n) for c, n, _m in unexplained]} "
            f"(total failing/erroring testcases: {len(failed_testcases)})"
        )

    if len(b2_matches) > 1 or len(d5_matches) > 1:
        return False, (
            "a known-accepted B2/D5 testcase appeared more than once in the JUnit "
            f"report: b2={len(b2_matches)} d5={len(d5_matches)}"
        )

    verdict_messages: list[str] = []

    if b2_matches:
        ok, message = _evaluate_b2(unassigned=unassigned, violations=violations)
        if not ok:
            return False, message
        verdict_messages.append(message)

    if d5_matches:
        ok, message = _evaluate_d5(d5_matches[0])
        if not ok:
            return False, message
        verdict_messages.append(message)

    return True, " ".join(verdict_messages)


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
