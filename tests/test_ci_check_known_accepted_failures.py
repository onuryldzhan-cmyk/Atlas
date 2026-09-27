"""Discriminating tests for tools/ci_check_known_accepted_failures.py.

Each case exercises a different way a JUnit report can diverge from B2's
established failure signature (registry v4.88: the two ``atlas_finance``
forbidden-edge violations ``test_forbidden_layer_imports`` reports). The
point of the suite is to prove the check is narrow - it accepts that exact
signature and nothing merely sharing the test's name.
"""

from __future__ import annotations

import sys
import xml.sax.saxutils as saxutils
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

from tools.ci_check_known_accepted_failures import (  # noqa: E402
    JUnitReportError,
    evaluate,
    main,
    parse_failed_testcases,
)

B2_CLASSNAME = "tests.architecture.test_forbidden_layer_imports"
B2_NAME = "test_forbidden_layer_imports"

EDGE_1 = (
    "atlas_finance/market_data/contracts.py -> atlas_finance/__init__.py "
    "(hard forbidden edge: domain/contracts must not depend on infrastructure)"
)
EDGE_2 = (
    "atlas_finance/market_data/contracts.py -> "
    "atlas_finance/market_data/__init__.py (hard forbidden edge: "
    "domain/contracts must not depend on infrastructure)"
)
EDGE_3_EXTRA = (
    "atlas_finance/market_data/other.py -> atlas_finance/__init__.py "
    "(hard forbidden edge: domain/contracts must not depend on infrastructure)"
)

# Byte-for-byte the "message" attribute pytest 9.1.1 actually produced for
# this failure in the real GitHub Actions run (Atlas CI, run 36311901005,
# head_sha 0923805, Python 3.14.7) - captured from the run's uploaded
# JUnit artifact, not hand-written.
REAL_B2_MESSAGE = (
    "AssertionError: forbidden dependency edges detected (see "
    "packaging/atlas_architecture_map.json forbidden_edges / "
    "permitted_exceptions): ['atlas_finance/market_data/contracts.py -> "
    "atlas_finance/__init__.py (hard forbidden edge: domain/contracts must "
    "not depend on infrastructure)', 'atlas_finance/market_data/contracts.py "
    "-> atlas_finance/market_data/__init__.py (hard forbidden edge: "
    "domain/contracts must not depend on infrastructure)']\n"
    "assert ['atlas_finan...rastructure)'] == []\n"
    "  \n"
    "  Left contains 2 more items, first extra item: "
    "'atlas_finance/market_data/contracts.py -> atlas_finance/__init__.py "
    "(hard forbidden edge: domain/contracts must not depend on "
    "infrastructure)'\n"
    "  Use -v to get more diff"
)


def _b2_message(edges: list[str]) -> str:
    return (
        "AssertionError: forbidden dependency edges detected (see "
        "packaging/atlas_architecture_map.json forbidden_edges / "
        f"permitted_exceptions): {edges!r}\n"
        "assert [...] == []"
    )


def _escape_attribute(message: str) -> str:
    # xml.sax.saxutils.escape leaves literal control characters alone, but a
    # real XML writer (and pytest's own JUnit output) encodes them as
    # character references - otherwise a conformant parser's attribute-value
    # normalization collapses embedded newlines into spaces and merges the
    # message's lines together. Reproducing that encoding is required for
    # these fixtures to behave like pytest's actual JUnit files.
    escaped = saxutils.escape(message, {'"': "&quot;"})
    for char, reference in (("\n", "&#10;"), ("\r", "&#13;"), ("\t", "&#9;")):
        escaped = escaped.replace(char, reference)
    return escaped


def _failing_testcase(classname: str, name: str, message: str, kind: str = "failure") -> str:
    escaped = _escape_attribute(message)
    return (
        f'<testcase classname="{classname}" name="{name}" time="1.0">'
        f'<{kind} message="{escaped}">body</{kind}></testcase>'
    )


def _passing_testcase(classname: str, name: str) -> str:
    return f'<testcase classname="{classname}" name="{name}" time="0.01" />'


def _junit_xml(*testcases_xml: str) -> str:
    return (
        '<?xml version="1.0" encoding="utf-8"?>'
        '<testsuites name="pytest tests">'
        '<testsuite name="pytest" errors="0" failures="1" skipped="0" tests="1" '
        'time="1.0" timestamp="2026-09-27T00:00:00+00:00" hostname="vm">'
        f"{''.join(testcases_xml)}"
        "</testsuite></testsuites>"
    )


# ---------------------------------------------------------------------------
# Clean report
# ---------------------------------------------------------------------------


def test_clean_report_passes(tmp_path):
    report = tmp_path / "junit.xml"
    report.write_text(_junit_xml(_passing_testcase("tests.test_x", "test_x")))

    assert main([str(report)]) == 0


def test_no_failed_testcases_means_nothing_to_accept():
    outcome = evaluate(parse_failed_testcases(_junit_xml(_passing_testcase("t", "t"))))

    assert outcome.passed
    assert outcome.accepted == []


# ---------------------------------------------------------------------------
# Known case: B2 alone, exact signature
# ---------------------------------------------------------------------------


def test_known_b2_failure_alone_passes(tmp_path):
    report = tmp_path / "junit.xml"
    report.write_text(
        _junit_xml(_failing_testcase(B2_CLASSNAME, B2_NAME, _b2_message([EDGE_1, EDGE_2])))
    )

    assert main([str(report)]) == 0


def test_b2_edge_order_is_not_significant():
    xml_text = _junit_xml(
        _failing_testcase(B2_CLASSNAME, B2_NAME, _b2_message([EDGE_2, EDGE_1]))
    )
    outcome = evaluate(parse_failed_testcases(xml_text))

    assert outcome.passed
    assert outcome.accepted == [f"{B2_CLASSNAME}::{B2_NAME} (B2)"]


def test_real_ci_produced_b2_message_is_accepted():
    """Against the literal message pytest 9.1.1 wrote in the real CI run."""

    xml_text = _junit_xml(_failing_testcase(B2_CLASSNAME, B2_NAME, REAL_B2_MESSAGE))
    outcome = evaluate(parse_failed_testcases(xml_text))

    assert outcome.passed
    assert outcome.accepted == [f"{B2_CLASSNAME}::{B2_NAME} (B2)"]


# ---------------------------------------------------------------------------
# Must still fail loudly
# ---------------------------------------------------------------------------


def test_wrong_test_failing_fails(tmp_path):
    report = tmp_path / "junit.xml"
    report.write_text(
        _junit_xml(
            _failing_testcase(
                "tests.test_something_else", "test_unrelated", "AssertionError: boom"
            )
        )
    )

    assert main([str(report)]) == 1


def test_b2_plus_extra_failure_fails(tmp_path):
    report = tmp_path / "junit.xml"
    report.write_text(
        _junit_xml(
            _failing_testcase(B2_CLASSNAME, B2_NAME, _b2_message([EDGE_1, EDGE_2])),
            _failing_testcase(
                "tests.test_something_else", "test_unrelated", "AssertionError: boom"
            ),
        )
    )

    assert main([str(report)]) == 1


def test_b2_plus_extra_failure_still_recognizes_b2():
    xml_text = _junit_xml(
        _failing_testcase(B2_CLASSNAME, B2_NAME, _b2_message([EDGE_1, EDGE_2])),
        _failing_testcase("tests.test_other", "test_other", "AssertionError: boom"),
    )
    outcome = evaluate(parse_failed_testcases(xml_text))

    assert not outcome.passed
    assert outcome.accepted == [f"{B2_CLASSNAME}::{B2_NAME} (B2)"]
    assert len(outcome.unexplained) == 1
    assert "tests.test_other" in outcome.unexplained[0]


def test_b2_wrong_reason_fails():
    xml_text = _junit_xml(
        _failing_testcase(
            B2_CLASSNAME,
            B2_NAME,
            "AssertionError: cannot check forbidden edges: unassigned modules ['x']",
        )
    )
    outcome = evaluate(parse_failed_testcases(xml_text))

    assert not outcome.passed
    assert "established signature" in outcome.unexplained[0]


def test_b2_extra_edge_fails():
    xml_text = _junit_xml(
        _failing_testcase(
            B2_CLASSNAME, B2_NAME, _b2_message([EDGE_1, EDGE_2, EDGE_3_EXTRA])
        )
    )
    outcome = evaluate(parse_failed_testcases(xml_text))

    assert not outcome.passed


def test_b2_missing_edge_fails():
    xml_text = _junit_xml(_failing_testcase(B2_CLASSNAME, B2_NAME, _b2_message([EDGE_1])))
    outcome = evaluate(parse_failed_testcases(xml_text))

    assert not outcome.passed


def test_b2_reported_as_error_instead_of_failure_fails():
    xml_text = _junit_xml(
        _failing_testcase(
            B2_CLASSNAME, B2_NAME, _b2_message([EDGE_1, EDGE_2]), kind="error"
        )
    )
    outcome = evaluate(parse_failed_testcases(xml_text))

    assert not outcome.passed


def test_b2_name_with_different_classname_fails():
    xml_text = _junit_xml(
        _failing_testcase(
            "tests.architecture.some_other_module", B2_NAME, _b2_message([EDGE_1, EDGE_2])
        )
    )
    outcome = evaluate(parse_failed_testcases(xml_text))

    assert not outcome.passed


# ---------------------------------------------------------------------------
# Report-level failure modes
# ---------------------------------------------------------------------------


def test_missing_report_file_fails(tmp_path):
    assert main([str(tmp_path / "does_not_exist.xml")]) == 1


def test_malformed_xml_fails(tmp_path):
    report = tmp_path / "junit.xml"
    report.write_text("<testsuites><testsuite>not closed")

    assert main([str(report)]) == 1


def test_doctype_is_rejected():
    xml_text = (
        '<?xml version="1.0"?><!DOCTYPE testsuites>'
        + _junit_xml(_passing_testcase("t", "t"))
    )

    try:
        parse_failed_testcases(xml_text)
        assert False, "expected JUnitReportError"
    except JUnitReportError:
        pass


def test_unexpected_root_element_fails():
    try:
        parse_failed_testcases("<not_a_junit_report/>")
        assert False, "expected JUnitReportError"
    except JUnitReportError:
        pass
