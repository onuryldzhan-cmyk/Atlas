"""tools/ci_check_known_accepted_failures.py must discriminate correctly.

This is CI build-criteria configuration for two permanently/durably-accepted
known failures - B2 (GRANT-B2-PERMANENT-CLOSURE, registry v4.63,
governance/findings/ARCH-EDGE-001_ANCESTOR_PACKAGE_FORBIDDEN_EDGES.md) and D5
(registry v4.97/v4.99, tests/architecture/test_rem001_state_authority_map.py's
stale-artifact assertion) - not a change to either underlying test. These
tests prove the CI-side script discriminates rather than merely asserting it
passes on the current, expected repository state: a clean run, an unrelated
additional failure, the same test failing for a different reason, a missing
or extra B2 edge, a duplicate known testcase, and - specific to D5 - the
identically-named-but-different Gate 3 construction-paths test must each be
told apart, mirroring the proven-to-discriminate pattern already used by
tests/architecture/test_data_layer_init_is_lazy.py for a comparable
CI/architecture governance guard.

The JUnit-parsing and decision logic under test is pure (no real pytest run,
no real architecture-map mutation) so these fixtures never touch the real
tree, matching this repository's standing rule that a regression is
constructed as a fixture or scratch copy, never by editing real source.
"""

from __future__ import annotations

from tools.ci_check_known_accepted_failures import (
    D5_KNOWN_FAILURE_MESSAGE,
    D5_TEST_CLASSNAME,
    D5_TEST_NAME,
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

B2_TESTCASE = (
    "tests.architecture.test_forbidden_layer_imports",
    "test_forbidden_layer_imports",
)
D5_TESTCASE = (D5_TEST_CLASSNAME, D5_TEST_NAME)
# The Gate 3 construction-paths test shares D5's exact test name but lives in
# a different module and checks a different artifact - it must never be
# accepted under the D5 carve-out even though it fails with the identical
# name.
CONSTRUCTION_PATHS_TESTCASE = (
    "tests.architecture.test_rem001_construction_paths",
    D5_TEST_NAME,
)


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
    assert parse_junit_failed_testcases(xml_text) == [
        ("a", "b", "x"),
        ("c", "d", "y"),
    ]


def test_parse_junit_missing_message_attribute_is_none() -> None:
    xml_text = _junit('<testcase classname="a" name="b"><failure>no message attr</failure></testcase>')
    assert parse_junit_failed_testcases(xml_text) == [("a", "b", None)]


def test_clean_suite_passes() -> None:
    ok, _ = evaluate_build_status([], unassigned=[], violations=[])
    assert ok is True


# ---------------------------------------------------------------------------
# B2 alone
# ---------------------------------------------------------------------------


def test_exactly_known_b2_case_passes() -> None:
    ok, message = evaluate_build_status(
        [(*B2_TESTCASE, "AssertionError: ...")],
        unassigned=[],
        violations=KNOWN_VIOLATIONS,
    )
    assert ok is True
    assert "GRANT-B2-PERMANENT-CLOSURE" in message


def test_a_different_test_failing_fails() -> None:
    ok, message = evaluate_build_status(
        [("tests.test_something_else", "test_something_else", "AssertionError: x")],
        unassigned=[],
        violations=[],
    )
    assert ok is False
    assert "not one of the known-accepted B2/D5 cases" in message


def test_the_same_test_plus_an_unrelated_failure_fails() -> None:
    ok, message = evaluate_build_status(
        [
            (*B2_TESTCASE, "AssertionError: ..."),
            ("tests.test_something_else", "test_something_else", "AssertionError: x"),
        ],
        unassigned=[],
        violations=KNOWN_VIOLATIONS,
    )
    assert ok is False
    assert "not one of the known-accepted B2/D5 cases" in message
    assert "test_something_else" in message


def test_same_test_failing_on_unassigned_modules_fails() -> None:
    ok, message = evaluate_build_status(
        [(*B2_TESTCASE, "AssertionError: ...")],
        unassigned=["some/new/module.py"],
        violations=[],
    )
    assert ok is False
    assert "unassigned modules" in message


def test_an_additional_forbidden_edge_beyond_the_known_two_fails() -> None:
    extra_violations = [*KNOWN_VIOLATIONS, "some/new_l1.py -> some/l2/__init__.py (reason)"]
    ok, message = evaluate_build_status(
        [(*B2_TESTCASE, "AssertionError: ...")],
        unassigned=[],
        violations=extra_violations,
    )
    assert ok is False
    assert "unexpected=" in message
    assert "some/new_l1.py" in message


def test_a_missing_known_edge_fails() -> None:
    ok, message = evaluate_build_status(
        [(*B2_TESTCASE, "AssertionError: ...")],
        unassigned=[],
        violations=[KNOWN_VIOLATIONS[0]],
    )
    assert ok is False
    assert "missing=" in message


def test_b2_testcase_appearing_twice_fails() -> None:
    ok, message = evaluate_build_status(
        [(*B2_TESTCASE, "AssertionError: ..."), (*B2_TESTCASE, "AssertionError: ...")],
        unassigned=[],
        violations=KNOWN_VIOLATIONS,
    )
    assert ok is False
    assert "more than once" in message


# ---------------------------------------------------------------------------
# D5 alone
# ---------------------------------------------------------------------------


def test_exactly_known_d5_case_passes() -> None:
    ok, message = evaluate_build_status(
        [(*D5_TESTCASE, D5_KNOWN_FAILURE_MESSAGE)],
        unassigned=[],
        violations=[],
    )
    assert ok is True
    assert "D5" in message


def test_known_d5_case_with_the_real_pytest_diff_suffix_passes() -> None:
    """Pytest's assertion rewrite appends its own (legitimately drifting) diff
    explanation after the first line; only the first line is matched."""
    message_with_diff = (
        D5_KNOWN_FAILURE_MESSAGE + "\nassert '# REM-001_ST...ee test |\\n\\n' == "
        "'# REM-001_ST...ee test |\\n\\n'\n  \n  Skipping 508 identical leading "
        "characters in diff, use -v to show\n  - some drifted line\n  + some other line"
    )
    ok, message = evaluate_build_status(
        [(*D5_TESTCASE, message_with_diff)],
        unassigned=[],
        violations=[],
    )
    assert ok is True
    assert "D5" in message


def test_d5_failing_with_a_different_first_line_fails() -> None:
    ok, message = evaluate_build_status(
        [(*D5_TESTCASE, "AssertionError: some other assertion entirely\nassert 1 == 2")],
        unassigned=[],
        violations=[],
    )
    assert ok is False
    assert "different reason than the known D5" in message


def test_d5_failing_with_a_different_message_fails() -> None:
    ok, message = evaluate_build_status(
        [(*D5_TESTCASE, "AssertionError: some other assertion entirely")],
        unassigned=[],
        violations=[],
    )
    assert ok is False
    assert "different reason than the known D5" in message


def test_d5_failing_with_no_message_fails() -> None:
    ok, message = evaluate_build_status(
        [(*D5_TESTCASE, None)],
        unassigned=[],
        violations=[],
    )
    assert ok is False
    assert "different reason than the known D5" in message


def test_the_identically_named_construction_paths_test_is_not_accepted_as_d5() -> None:
    """Gate 3's test shares D5's exact test name but a different classname and
    checks a different artifact; it must be rejected, not conflated with D5."""
    ok, message = evaluate_build_status(
        [(*CONSTRUCTION_PATHS_TESTCASE, D5_KNOWN_FAILURE_MESSAGE)],
        unassigned=[],
        violations=[],
    )
    assert ok is False
    assert "not one of the known-accepted B2/D5 cases" in message


def test_d5_testcase_appearing_twice_fails() -> None:
    ok, message = evaluate_build_status(
        [
            (*D5_TESTCASE, D5_KNOWN_FAILURE_MESSAGE),
            (*D5_TESTCASE, D5_KNOWN_FAILURE_MESSAGE),
        ],
        unassigned=[],
        violations=[],
    )
    assert ok is False
    assert "more than once" in message


# ---------------------------------------------------------------------------
# B2 and D5 together
# ---------------------------------------------------------------------------


def test_both_known_b2_and_d5_together_pass() -> None:
    ok, message = evaluate_build_status(
        [
            (*B2_TESTCASE, "AssertionError: ..."),
            (*D5_TESTCASE, D5_KNOWN_FAILURE_MESSAGE),
        ],
        unassigned=[],
        violations=KNOWN_VIOLATIONS,
    )
    assert ok is True
    assert "GRANT-B2-PERMANENT-CLOSURE" in message
    assert "D5" in message


def test_b2_and_d5_together_but_b2_edge_set_wrong_fails() -> None:
    ok, message = evaluate_build_status(
        [
            (*B2_TESTCASE, "AssertionError: ..."),
            (*D5_TESTCASE, D5_KNOWN_FAILURE_MESSAGE),
        ],
        unassigned=[],
        violations=[KNOWN_VIOLATIONS[0]],
    )
    assert ok is False
    assert "missing=" in message


def test_b2_and_d5_together_but_d5_message_wrong_fails() -> None:
    ok, message = evaluate_build_status(
        [
            (*B2_TESTCASE, "AssertionError: ..."),
            (*D5_TESTCASE, "AssertionError: something else"),
        ],
        unassigned=[],
        violations=KNOWN_VIOLATIONS,
    )
    assert ok is False
    assert "different reason than the known D5" in message


def test_b2_and_d5_plus_an_extra_unrelated_failure_fails() -> None:
    ok, message = evaluate_build_status(
        [
            (*B2_TESTCASE, "AssertionError: ..."),
            (*D5_TESTCASE, D5_KNOWN_FAILURE_MESSAGE),
            ("tests.test_something_else", "test_something_else", "AssertionError: x"),
        ],
        unassigned=[],
        violations=KNOWN_VIOLATIONS,
    )
    assert ok is False
    assert "not one of the known-accepted B2/D5 cases" in message
