"""Let CI pass when the only pytest failure present is a known-accepted one.

Registry v4.88 records Group B2 - the two ``atlas_finance`` forbidden-edge
violations that ``tests/architecture/test_forbidden_layer_imports.py``
reports - as a permanently accepted architecture disposition. Nothing in
that record authorizes editing ``packaging/atlas_architecture_map.json``,
adding a ``permitted_exceptions`` entry, or touching the test itself to make
it pass. CI therefore cannot just ignore pytest's exit code (that would also
swallow unrelated failures); instead this checks the JUnit report against
B2's exact, previously-verified failure signature (same test, same two
edges) and treats anything else - a different test, an additional edge, or
B2's own test failing for an unrecognized reason - as a real, build-failing
result.
"""

from __future__ import annotations

import ast
import sys
import xml.etree.ElementTree as ElementTree
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

DEFAULT_JUNIT_XML_PATH = "reports/observability/test_results.junit.xml"

_B2_CLASSNAME = "tests.architecture.test_forbidden_layer_imports"
_B2_NAME = "test_forbidden_layer_imports"
_B2_MESSAGE_PREFIX = (
    "AssertionError: forbidden dependency edges detected "
    "(see packaging/atlas_architecture_map.json forbidden_edges / "
    "permitted_exceptions): "
)
_B2_EXPECTED_EDGES = frozenset(
    {
        "atlas_finance/market_data/contracts.py -> atlas_finance/__init__.py "
        "(hard forbidden edge: domain/contracts must not depend on infrastructure)",
        "atlas_finance/market_data/contracts.py -> "
        "atlas_finance/market_data/__init__.py (hard forbidden edge: "
        "domain/contracts must not depend on infrastructure)",
    }
)


def _b2_signature_matches(message: str) -> bool:
    first_line = message.splitlines()[0] if message else ""

    if not first_line.startswith(_B2_MESSAGE_PREFIX):
        return False

    edges_repr = first_line[len(_B2_MESSAGE_PREFIX) :]

    try:
        edges = ast.literal_eval(edges_repr)
    except (ValueError, SyntaxError):
        return False

    if not isinstance(edges, list) or not all(isinstance(edge, str) for edge in edges):
        return False

    return frozenset(edges) == _B2_EXPECTED_EDGES


@dataclass(frozen=True)
class KnownAcceptedFailure:
    label: str
    classname: str
    name: str
    matches_signature: Callable[[str], bool]


KNOWN_ACCEPTED_FAILURES: tuple[KnownAcceptedFailure, ...] = (
    KnownAcceptedFailure(
        label="B2",
        classname=_B2_CLASSNAME,
        name=_B2_NAME,
        matches_signature=_b2_signature_matches,
    ),
)


@dataclass(frozen=True)
class FailedTestCase:
    classname: str
    name: str
    kind: str
    message: str


class JUnitReportError(RuntimeError):
    """The JUnit XML report could not be trusted as a build verdict."""


def parse_failed_testcases(xml_text: str) -> list[FailedTestCase]:
    # Same defensive posture as observability.panel_sources: nothing pytest
    # emits carries a DTD, so reject rather than risk an entity-expansion
    # blowup in the standard library parser.
    if "<!DOCTYPE" in xml_text or "<!ENTITY" in xml_text:
        raise JUnitReportError(
            "JUnit report rejected: contains a DOCTYPE/ENTITY declaration"
        )

    try:
        root = ElementTree.fromstring(xml_text)
    except ElementTree.ParseError as error:
        raise JUnitReportError(f"JUnit report is not well-formed XML: {error}") from error

    if root.tag not in ("testsuite", "testsuites"):
        raise JUnitReportError(f"unexpected JUnit root element {root.tag!r}")

    failed: list[FailedTestCase] = []

    for testcase in root.iter("testcase"):
        classname = testcase.get("classname", "")
        name = testcase.get("name", "")

        for kind in ("failure", "error"):
            node = testcase.find(kind)

            if node is not None:
                failed.append(
                    FailedTestCase(
                        classname=classname,
                        name=name,
                        kind=kind,
                        message=node.get("message", ""),
                    )
                )
                break

    return failed


@dataclass(frozen=True)
class CheckOutcome:
    accepted: list[str]
    unexplained: list[str]

    @property
    def passed(self) -> bool:
        return not self.unexplained


def evaluate(failed_testcases: list[FailedTestCase]) -> CheckOutcome:
    accepted: list[str] = []
    unexplained: list[str] = []

    for failure in failed_testcases:
        known = next(
            (
                candidate
                for candidate in KNOWN_ACCEPTED_FAILURES
                if candidate.classname == failure.classname and candidate.name == failure.name
            ),
            None,
        )

        if known is None:
            unexplained.append(
                f"{failure.classname}::{failure.name} ({failure.kind}) - "
                "not a known-accepted failure"
            )
            continue

        if failure.kind != "failure":
            unexplained.append(
                f"{failure.classname}::{failure.name} is a pytest 'error', not "
                f"{known.label}'s known-accepted assertion failure"
            )
            continue

        if not known.matches_signature(failure.message):
            first_line = failure.message.splitlines()[0] if failure.message else "(empty)"
            unexplained.append(
                f"{failure.classname}::{failure.name} failed, but not with "
                f"{known.label}'s established signature - message: {first_line}"
            )
            continue

        accepted.append(f"{failure.classname}::{failure.name} ({known.label})")

    return CheckOutcome(accepted=accepted, unexplained=unexplained)


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    path = Path(args[0]) if args else Path(DEFAULT_JUNIT_XML_PATH)

    if not path.is_file():
        print(
            f"ci_check_known_accepted_failures: JUnit report not found at {path}",
            file=sys.stderr,
        )
        return 1

    try:
        xml_text = path.read_text(encoding="utf-8-sig")
        failed_testcases = parse_failed_testcases(xml_text)
    except (OSError, JUnitReportError) as error:
        print(f"ci_check_known_accepted_failures: {error}", file=sys.stderr)
        return 1

    outcome = evaluate(failed_testcases)

    if outcome.accepted:
        print("ci_check_known_accepted_failures: known-accepted failures present:")
        for line in outcome.accepted:
            print(f"  - {line}")
    else:
        print("ci_check_known_accepted_failures: no failures in the report to accept.")

    if outcome.unexplained:
        print(
            "ci_check_known_accepted_failures: UNEXPLAINED failures, build stays red:",
            file=sys.stderr,
        )
        for line in outcome.unexplained:
            print(f"  - {line}", file=sys.stderr)
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
