"""tools/ci_check_known_accepted_b2_failure.py must discriminate correctly.

This is CI build-criteria configuration for the permanently-accepted
GRANT-B2-PERMANENT-CLOSURE case (registry v4.63,
governance/findings/ARCH-EDGE-001_ANCESTOR_PACKAGE_FORBIDDEN_EDGES.md), not a
change to the architecture gate itself. These tests prove the CI-side script
discriminates rather than merely asserting it passes on the current, expected
repository state: a clean run, an unrelated additional failure, the same test
failing for a different reason, and both a missing and an extra edge must
each be told apart, mirroring the proven-to-discriminate pattern already used
by tests/architecture/test_data_layer_init_is_lazy.py for a comparable
CI/architecture governance guard.

The JUnit-parsing and decision logic under test is pure (no real pytest run,
no real architecture-map mutation) so these fixtures never touch the real
tree, matching this repository's standing rule that a regression is
constructed as a fixture or scratch copy, never by editing real source.
"""

from __future__ import annotations

from tools.ci_check_known_accepted_b2_failure import (
    KNOWN_ACCEPTED_EDGES,
    evaluate_build_status,
    parse_junit_failed_testcases,
    parse_violation,
)

KNOWN_VIOLATIONS = [
    "atlas_finance/market_data/contracts.py -> atlas_finance/__init__.py "
    "(hard forbidden edge: domain/contracts must not depend on infrastructure)",
    "atlas_finance/market_data/contracts.py -> atlas_finance/market_data/__init__.py "
    "(hard forbidden edge: domain/contracts must not depend on infrastructure)",
]


def _junit(testcases_xml: str) -> str:
    return (
        '<?xml version="1.0" encoding="utf-8"?>'
        f'<testsuites><testsuite name="pytest">{testcases_xml}</testsuite></testsuites>'
    )


def test_parse_violation_splits_from_to_ignoring_reason() -> None:
    assert parse_violation(KNOWN_VIOLATIONS[0]) == (
        "atlas_finance/market_data/contracts.py",
        "atlas_finance/__init__.py",
    )
    assert parse_violation(KNOWN_VIOLATIONS[1]) == (
        "atlas_finance/market_data/contracts.py",
        "atlas_finance/market_data/__init__.py",
    )


def test_known_accepted_edges_matches_registry_v4_63() -> None:
    assert KNOWN_ACCEPTED_EDGES == {
        parse_violation(KNOWN_VIOLATIONS[0]),
        parse_violation(KNOWN_VIOLATIONS[1]),
    }


def test_parse_junit_all_passed_reports_no_failures() -> None:
    xml_text = _junit(
        '<testcase classname="tests.architecture.test_forbidden_layer_imports" '
        'name="test_forbidden_layer_imports"/>'
    )
    assert parse_junit_failed_testcases(xml_text) == []


def test_parse_junit_detects_failure_and_error_elements() -> None:
    xml_text = _junit(
        '<testcase classname="a" name="b"><failure message="x">x</failure></testcase>'
        '<testcase classname="c" name="d"><error message="y">y</error></testcase>'
        '<testcase classname="e" name="f"/>'
    )
    assert parse_junit_failed_testcases(xml_text) == [("a", "b"), ("c", "d")]


def test_clean_suite_passes() -> None:
    ok, _ = evaluate_build_status([], unassigned=[], violations=[])
    assert ok is True


def test_exactly_known_b2_case_passes() -> None:
    ok, message = evaluate_build_status(
        [
            (
                "tests.architecture.test_forbidden_layer_imports",
                "test_forbidden_layer_imports",
            )
        ],
        unassigned=[],
        violations=KNOWN_VIOLATIONS,
    )
    assert ok is True
    assert "GRANT-B2-PERMANENT-CLOSURE" in message


def test_a_different_test_failing_fails() -> None:
    ok, message = evaluate_build_status(
        [("tests.test_something_else", "test_something_else")],
        unassigned=[],
        violations=[],
    )
    assert ok is False
    assert "not the known GRANT-B2-PERMANENT-CLOSURE case" in message


def test_the_same_test_plus_an_unrelated_failure_fails() -> None:
    ok, message = evaluate_build_status(
        [
            (
                "tests.architecture.test_forbidden_layer_imports",
                "test_forbidden_layer_imports",
            ),
            ("tests.test_something_else", "test_something_else"),
        ],
        unassigned=[],
        violations=KNOWN_VIOLATIONS,
    )
    assert ok is False
    assert "found 2 failing/erroring testcases" in message


def test_same_test_failing_on_unassigned_modules_fails() -> None:
    ok, message = evaluate_build_status(
        [
            (
                "tests.architecture.test_forbidden_layer_imports",
                "test_forbidden_layer_imports",
            )
        ],
        unassigned=["some/new/module.py"],
        violations=[],
    )
    assert ok is False
    assert "unassigned modules" in message


def test_an_additional_forbidden_edge_beyond_the_known_two_fails() -> None:
    extra_violations = [*KNOWN_VIOLATIONS, "some/new_l1.py -> some/l2/__init__.py (reason)"]
    ok, message = evaluate_build_status(
        [
            (
                "tests.architecture.test_forbidden_layer_imports",
                "test_forbidden_layer_imports",
            )
        ],
        unassigned=[],
        violations=extra_violations,
    )
    assert ok is False
    assert "unexpected=" in message
    assert "some/new_l1.py" in message


def test_a_missing_known_edge_fails() -> None:
    ok, message = evaluate_build_status(
        [
            (
                "tests.architecture.test_forbidden_layer_imports",
                "test_forbidden_layer_imports",
            )
        ],
        unassigned=[],
        violations=[KNOWN_VIOLATIONS[0]],
    )
    assert ok is False
    assert "missing=" in message
