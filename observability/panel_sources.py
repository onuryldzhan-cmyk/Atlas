"""Pure readers behind the lightweight observability panel.

This module deliberately imports no web framework and no Atlas runtime
component. It only reads files that some other, explicitly invoked process
has already produced:

* panel (b) "test results" reads the pytest JUnit XML artifact at
  ``reports/observability/test_results.junit.xml`` together with its
  sidecar ``reports/observability/test_results.meta.json``. The artifact is
  produced on demand by ``tools/generate_test_results_artifact.py``. The
  panel never runs pytest itself.
* panel (c) "governance" reads the highest-version milestone registry in
  ``governance/current/``, resolved through the ``supersedes`` chain rather
  than by sorting filenames, and reports its ``governance_reconciliation``
  record (GOV-DRIFT).
* the S-3/M-2 telemetry summary reads
  ``reports/observability/telemetry_summary.json``, the ``--json`` report of
  ``tools/extract_candle_age_telemetry.py`` saved by the operator, and
  projects it. The tool is neither run nor imported here; its statistics are
  reused as produced, never reimplemented.

Contract for these readers: on a missing, malformed, ambiguous or internally
inconsistent source they return ``{"available": False, "reason": ...}``.
They never fabricate test counts and never infer a governance status.
"""

from __future__ import annotations

import codecs
import json
import xml.etree.ElementTree as ElementTree

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]

TEST_RESULTS_ARTIFACT_RELPATH = "reports/observability/test_results.junit.xml"
TEST_RESULTS_META_RELPATH = "reports/observability/test_results.meta.json"
GOVERNANCE_CURRENT_RELPATH = "governance/current"

# Defensive bound on artifact size. The artifact is locally generated, but a
# reader mounted behind an HTTP route should never be able to be turned into
# an unbounded read by a stray or corrupted file.
MAX_ARTIFACT_BYTES = 16 * 1024 * 1024
MAX_META_BYTES = 256 * 1024

REQUIRED_META_KEYS = (
    "commit",
    "generated_at",
    "command",
    "pytest_exit_code",
    "target",
)


def _resolve_root(repository_root: Path | None) -> Path:
    return REPOSITORY_ROOT if repository_root is None else Path(repository_root)


def _unavailable(reason: str, **detail: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {"available": False, "reason": reason}
    payload.update(detail)
    return payload


# ---------------------------------------------------------------------------
# Commit identity (read-only, no subprocess)
# ---------------------------------------------------------------------------


def read_head_commit(repository_root: Path | None = None) -> str | None:
    """Return the current HEAD commit hash by reading ``.git`` directly.

    Returns ``None`` when HEAD cannot be resolved. No subprocess is spawned
    and nothing is written.
    """

    root = _resolve_root(repository_root)
    git_dir = root / ".git"

    try:
        head_text = (git_dir / "HEAD").read_text(encoding="utf-8").strip()
    except OSError:
        return None

    if not head_text.startswith("ref:"):
        return head_text or None

    reference = head_text[len("ref:"):].strip()

    if not reference:
        return None

    loose_reference = git_dir / Path(reference)

    try:
        return loose_reference.read_text(encoding="utf-8").strip() or None
    except OSError:
        pass

    try:
        packed = (git_dir / "packed-refs").read_text(encoding="utf-8")
    except OSError:
        return None

    for line in packed.splitlines():
        if line.startswith("#") or line.startswith("^"):
            continue

        parts = line.split(maxsplit=1)

        if len(parts) == 2 and parts[1].strip() == reference:
            return parts[0].strip() or None

    return None


def _commit_alignment(
    artifact_commit: str | None,
    head_commit: str | None,
) -> dict[str, Any]:
    """Compare the artifact's stamped commit with the current HEAD.

    A stale artifact is surfaced explicitly; it is never silently presented
    as if it described the current working tree.
    """

    if artifact_commit is None or head_commit is None:
        state = "UNKNOWN"
    elif artifact_commit == head_commit:
        state = "MATCH"
    else:
        state = "STALE"

    return {
        "state": state,
        "artifact_commit": artifact_commit,
        "head_commit": head_commit,
    }


# ---------------------------------------------------------------------------
# Panel (b): test results
# ---------------------------------------------------------------------------


def _read_int_attribute(
    element: ElementTree.Element,
    name: str,
    *,
    required: bool,
) -> int | None:
    raw = element.get(name)

    if raw is None:
        return None if required else 0

    try:
        return int(raw)
    except ValueError:
        return None


def _read_meta(meta_path: Path) -> dict[str, Any]:
    if not meta_path.is_file():
        return _unavailable("META_MISSING")

    try:
        if meta_path.stat().st_size > MAX_META_BYTES:
            return _unavailable("META_TOO_LARGE")

        payload = json.loads(meta_path.read_text(encoding="utf-8-sig"))
    except OSError as error:
        return _unavailable("META_UNREADABLE", detail=type(error).__name__)
    except json.JSONDecodeError as error:
        return _unavailable("META_MALFORMED", detail=str(error))

    if not isinstance(payload, dict):
        return _unavailable("META_MALFORMED", detail="root is not an object")

    missing = [key for key in REQUIRED_META_KEYS if key not in payload]

    if missing:
        return _unavailable("META_INCOMPLETE", missing_keys=missing)

    commit = payload.get("commit")

    if not isinstance(commit, str) or not commit:
        return _unavailable("META_INCOMPLETE", missing_keys=["commit"])

    return {"available": True, **payload}


def read_test_results_panel(
    repository_root: Path | None = None,
) -> dict[str, Any]:
    """Read the generated pytest JUnit XML artifact.

    Never triggers a test run. Returns an ``available: False`` payload when
    the artifact is absent, oversized, or unparseable.
    """

    root = _resolve_root(repository_root)
    artifact_path = root / TEST_RESULTS_ARTIFACT_RELPATH
    meta_path = root / TEST_RESULTS_META_RELPATH

    location = {
        "artifact_path": TEST_RESULTS_ARTIFACT_RELPATH,
        "meta_path": TEST_RESULTS_META_RELPATH,
    }

    if not artifact_path.is_file():
        return _unavailable("ARTIFACT_MISSING", **location)

    try:
        size = artifact_path.stat().st_size

        if size > MAX_ARTIFACT_BYTES:
            return _unavailable(
                "ARTIFACT_TOO_LARGE",
                size_bytes=size,
                limit_bytes=MAX_ARTIFACT_BYTES,
                **location,
            )

        raw = artifact_path.read_text(encoding="utf-8-sig")
    except OSError as error:
        return _unavailable(
            "ARTIFACT_UNREADABLE",
            detail=type(error).__name__,
            **location,
        )

    # xml.etree can be driven into entity-expansion blowups by a document
    # carrying a DTD. Nothing pytest emits has one, so reject rather than
    # add a parser dependency.
    if "<!DOCTYPE" in raw or "<!ENTITY" in raw:
        return _unavailable("ARTIFACT_REJECTED_DOCTYPE", **location)

    try:
        parsed_root = ElementTree.fromstring(raw)
    except ElementTree.ParseError as error:
        return _unavailable(
            "ARTIFACT_MALFORMED",
            detail=str(error),
            **location,
        )

    if parsed_root.tag == "testsuite":
        suites = [parsed_root]
    elif parsed_root.tag == "testsuites":
        suites = list(parsed_root.iter("testsuite"))
    else:
        return _unavailable(
            "ARTIFACT_MALFORMED",
            detail=f"unexpected root element {parsed_root.tag!r}",
            **location,
        )

    if not suites:
        return _unavailable(
            "ARTIFACT_MALFORMED",
            detail="no testsuite element",
            **location,
        )

    totals = {"tests": 0, "failures": 0, "errors": 0, "skipped": 0}
    duration_seconds = 0.0
    duration_known = False
    suite_timestamp: str | None = None

    for suite in suites:
        for name, required in (
            ("tests", True),
            ("failures", False),
            ("errors", False),
            ("skipped", False),
        ):
            value = _read_int_attribute(suite, name, required=required)

            if value is None:
                return _unavailable(
                    "ARTIFACT_MALFORMED",
                    detail=f"missing or non-integer {name!r} attribute",
                    **location,
                )

            totals[name] += value

        raw_time = suite.get("time")

        if raw_time is not None:
            try:
                duration_seconds += float(raw_time)
                duration_known = True
            except ValueError:
                return _unavailable(
                    "ARTIFACT_MALFORMED",
                    detail="non-numeric 'time' attribute",
                    **location,
                )

        if suite_timestamp is None:
            suite_timestamp = suite.get("timestamp")

    passed = (
        totals["tests"]
        - totals["failures"]
        - totals["errors"]
        - totals["skipped"]
    )

    if passed < 0 or any(value < 0 for value in totals.values()):
        return _unavailable(
            "ARTIFACT_INCONSISTENT",
            detail="counts do not reconcile",
            totals=dict(totals),
            **location,
        )

    provenance = _read_meta(meta_path)
    artifact_commit = provenance.get("commit") if provenance["available"] else None

    return {
        "available": True,
        "totals": {
            "tests": totals["tests"],
            "passed": passed,
            "failed": totals["failures"],
            "errors": totals["errors"],
            "skipped": totals["skipped"],
        },
        "duration_seconds": round(duration_seconds, 3) if duration_known else None,
        "suite_timestamp": suite_timestamp,
        "provenance": provenance,
        "commit_alignment": _commit_alignment(
            artifact_commit,
            read_head_commit(root),
        ),
        **location,
    }


# ---------------------------------------------------------------------------
# Panel (c): governance reconciliation (GOV-DRIFT)
# ---------------------------------------------------------------------------


def _load_registry_files(directory: Path) -> tuple[dict[str, dict[str, Any]], list[str]]:
    registries: dict[str, dict[str, Any]] = {}
    unparseable: list[str] = []

    for path in sorted(directory.glob("*.json")):
        try:
            payload = json.loads(path.read_text(encoding="utf-8-sig"))
        except (OSError, json.JSONDecodeError):
            unparseable.append(path.name)
            continue

        if not isinstance(payload, dict):
            unparseable.append(path.name)
            continue

        registries[path.name] = payload

    return registries, unparseable


def _supersedes_name(payload: dict[str, Any]) -> str | None:
    value = payload.get("supersedes")

    if not isinstance(value, str) or not value:
        return None

    return Path(value.replace("\\", "/")).name


def resolve_current_registry(
    repository_root: Path | None = None,
) -> dict[str, Any]:
    """Resolve the head of the ``governance/current`` supersedes chain.

    The head is the registry no other current registry supersedes. An
    ambiguous head, a cycle, or a current registry unreachable from the head
    is reported as unavailable rather than guessed at.
    """

    root = _resolve_root(repository_root)
    directory = root / GOVERNANCE_CURRENT_RELPATH

    location = {"registry_directory": GOVERNANCE_CURRENT_RELPATH}

    if not directory.is_dir():
        return _unavailable("REGISTRY_DIRECTORY_MISSING", **location)

    registries, unparseable = _load_registry_files(directory)

    if unparseable:
        return _unavailable(
            "REGISTRY_MALFORMED",
            unparseable_files=unparseable,
            **location,
        )

    if not registries:
        return _unavailable("REGISTRY_EMPTY", **location)

    superseded = {
        name
        for payload in registries.values()
        if (name := _supersedes_name(payload)) is not None
    }

    heads = sorted(set(registries) - superseded)

    if len(heads) == 0:
        return _unavailable("REGISTRY_CHAIN_CYCLIC", **location)

    if len(heads) > 1:
        return _unavailable(
            "REGISTRY_HEAD_AMBIGUOUS",
            candidate_heads=heads,
            **location,
        )

    head = heads[0]

    # Walk the chain so a registry that is present but detached from the
    # head cannot hide behind an otherwise well-formed head.
    reachable: list[str] = []
    seen: set[str] = set()
    cursor: str | None = head

    while cursor is not None and cursor in registries:
        if cursor in seen:
            return _unavailable("REGISTRY_CHAIN_CYCLIC", **location)

        seen.add(cursor)
        reachable.append(cursor)
        cursor = _supersedes_name(registries[cursor])

    orphans = sorted(set(registries) - seen)

    if orphans:
        return _unavailable(
            "REGISTRY_CHAIN_BROKEN",
            head=head,
            unreachable_files=orphans,
            **location,
        )

    return {
        "available": True,
        "head": head,
        "chain": reachable,
        "payload": registries[head],
        **location,
    }


def read_governance_panel(
    repository_root: Path | None = None,
) -> dict[str, Any]:
    """Report the GOV-DRIFT reconciliation record of the current registry."""

    resolved = resolve_current_registry(repository_root)

    if not resolved["available"]:
        return resolved

    payload = resolved["payload"]
    reconciliation = payload.get("governance_reconciliation")

    location = {
        "registry_directory": resolved["registry_directory"],
        "registry_file": f"{GOVERNANCE_CURRENT_RELPATH}/{resolved['head']}",
        "chain_depth": len(resolved["chain"]),
    }

    if not isinstance(reconciliation, dict):
        return _unavailable(
            "GOVERNANCE_RECONCILIATION_MISSING",
            **location,
        )

    status = reconciliation.get("status")

    if not isinstance(status, str) or not status:
        return _unavailable(
            "GOVERNANCE_RECONCILIATION_STATUS_MISSING",
            **location,
        )

    schema_version = payload.get("schema_version")
    registry_status = payload.get("registry_status")

    return {
        "available": True,
        "schema_version": schema_version if isinstance(schema_version, str) else None,
        "registry_status": (
            registry_status if isinstance(registry_status, str) else None
        ),
        "reconciliation": {
            "id": reconciliation.get("id"),
            "status": status,
            "severity": reconciliation.get("severity"),
            "historical_registry": reconciliation.get("historical_registry"),
            "historical_registry_policy": reconciliation.get(
                "historical_registry_policy"
            ),
            "alignment_record": reconciliation.get("alignment_record"),
            "alignment_decision": reconciliation.get("alignment_decision"),
            "historical_state_preserved": reconciliation.get(
                "historical_state_preserved"
            ),
            "historical_state_rewritten": reconciliation.get(
                "historical_state_rewritten"
            ),
            "compatibility_mode": reconciliation.get("compatibility_mode"),
        },
        **location,
    }


# ---------------------------------------------------------------------------
# Known, owner-accepted limitations (System Integrity panel)
# ---------------------------------------------------------------------------

# Static by design: each entry mirrors an owner-accepted or recorded-open
# item in the governance registry, and the registry reference is published
# with it so the operator can look it up. The package that closes one of
# these must remove or update its entry here in the same change - nothing
# infers closure automatically.
KNOWN_LIMITATIONS: tuple[dict[str, str], ...] = (
    {
        "id": "EXEC-MGR-COMMIT-UNKNOWN-GAP-001",
        "status": "OPEN_OWNER_ACCEPTED",
        "registry_reference": "v4.74 owner_accepted_known_limitation",
        "summary": (
            "If a financial-state write is refused at the wrong moment, "
            "execution halts as COMMIT_STATUS_UNKNOWN and needs manual "
            "recovery; automatic recovery does not cover this case yet."
        ),
    },
    {
        "id": "DAILY-LOSS-LIMIT-WIRING",
        "status": "OPEN_NOT_YET_WIRED",
        "registry_reference": (
            "v4.81 paper_risk_accounting_day_auto_rollover_result "
            "informational_pre_existing"
        ),
        "summary": (
            "Realized daily P&L is not accumulated anywhere yet, so the "
            "daily-loss limit cannot trip; equity in the risk store only "
            "refreshes at the daily rollover."
        ),
    },
    {
        "id": "RISK-ACCOUNTING-RECOVERY-REBOOK-GAP-001",
        "status": "OPEN_NARROWED_FAIL_CLOSED",
        "registry_reference": (
            "v4.82 paper_realized_pnl_risk_accounting_and_halted_rollover_"
            "refusal_result independent_audit.medium MEDIUM-1 "
            "(residual of HIGH-1); narrowed by v4.84 "
            "paper_recovery_risk_accounting_booking_result"
        ),
        "summary": (
            "PAPER crash-recovery now books a recovered SELL's realized P&L "
            "into risk accounting exactly once, through the same hook normal "
            "execution uses. It refuses, writing nothing, when it cannot: "
            "the stored accounting day is not today, or the process died "
            "after the trade was applied but before the hook's write-ahead "
            "audit record. A journal entry left COMMIT_STATUS_UNKNOWN by a "
            "failed booking is still outside the recovery tool. In those "
            "cases the operator must reconcile the risk store by hand."
        ),
    },
    {
        "id": "RISK-EQUITY-UNREALIZED-DRAWDOWN-GAP-001",
        "status": "OPEN_OWNER_ACCEPTED",
        "registry_reference": (
            "v4.82 paper_realized_pnl_risk_accounting_and_halted_rollover_"
            "refusal_result independent_audit.informational"
        ),
        "summary": (
            "Risk-store equity (current_equity/peak_equity) only refreshes "
            "on a SELL commit or at day rollover, so an open position's "
            "unrealized drawdown is not currently monitored by the "
            "daily-loss/drawdown halts."
        ),
    },
)


# ---------------------------------------------------------------------------
# S-3 / M-2 telemetry summary
# ---------------------------------------------------------------------------

# Produced on demand by the operator with the unchanged extraction tool:
#
#     python tools/extract_candle_age_telemetry.py --json > reports/observability/telemetry_summary.json
#
# The panel reads that artifact the same way it reads the test-results
# artifact. It never runs the tool (no subprocess here) and never imports it
# (the tool imports core.application, an edge this L5 package may not take),
# so every statistic shown is one the tool itself computed.
TELEMETRY_SUMMARY_ARTIFACT_RELPATH = "reports/observability/telemetry_summary.json"
TELEMETRY_GENERATE_COMMAND = (
    "python tools/extract_candle_age_telemetry.py --json > "
    + TELEMETRY_SUMMARY_ARTIFACT_RELPATH
)

TELEMETRY_DISTRIBUTION_KEYS = ("count", "min", "max", "p50", "p90", "p95", "p99")


def _public_distribution(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {"count": 0}

    return {
        key: value[key]
        for key in TELEMETRY_DISTRIBUTION_KEYS
        if key in value and isinstance(value[key], (int, float))
        and not isinstance(value[key], bool)
    }


def summarize_telemetry_report(report: Any) -> dict[str, Any]:
    """Project the tool's ``--json`` report onto the panel's fields.

    No statistic is computed here - every number is one the tool already
    produced. The log path is not published. An absent or empty log is
    reported as ``has_data: False`` with a reason, never as zeros.
    """

    if not isinstance(report, dict):
        return _unavailable("TELEMETRY_REPORT_MALFORMED")

    parse = report.get("parse")
    candle_age = report.get("candle_age_s3")
    cycle_duration = report.get("cycle_duration_m2")

    if not all(isinstance(part, dict) for part in (parse, candle_age, cycle_duration)):
        return _unavailable("TELEMETRY_REPORT_MALFORMED")

    if report.get("log_path") is None:
        return {"available": True, "has_data": False, "reason": "LOG_DIRECTORY_NOT_CONFIGURED"}

    if report.get("log_file_found") is not True:
        return {"available": True, "has_data": False, "reason": "LOG_FILE_NOT_FOUND"}

    parsed_records = parse.get("parsed_records")

    if not isinstance(parsed_records, int) or parsed_records <= 0:
        return {"available": True, "has_data": False, "reason": "NO_RECORDS"}

    skipped = sum(
        value
        for key in (
            "blank_lines",
            "malformed_json_lines",
            "non_object_lines",
            "missing_required_field_lines",
        )
        if isinstance(value := parse.get(key), int)
    )

    per_run = cycle_duration.get("per_run")
    latest_run = None

    if isinstance(per_run, dict) and per_run:
        latest_key = max(per_run, key=lambda key: int(key) if str(key).isdigit() else -1)
        latest_run = _public_distribution(per_run[latest_key])

    status_counts = candle_age.get("overall_status_counts")

    return {
        "available": True,
        "has_data": True,
        "parsed_records": parsed_records,
        "skipped_lines": skipped,
        "unexpected_schema_version_present": (
            parse.get("unexpected_schema_version_present") is True
        ),
        "candle_age_seconds": _public_distribution(
            candle_age.get("overall_measured_distribution")
        ),
        "candle_age_status_counts": {
            str(key): value
            for key, value in status_counts.items()
            if isinstance(value, int)
        } if isinstance(status_counts, dict) else {},
        "cycle_duration_seconds": _public_distribution(cycle_duration.get("overall")),
        "cycle_duration_latest_run_seconds": latest_run,
        "run_count": (
            cycle_duration.get("run_count")
            if isinstance(cycle_duration.get("run_count"), int)
            else None
        ),
    }


def _decode_artifact_text(raw: bytes) -> str:
    """UTF-8 (with or without BOM) or BOM-marked UTF-16.

    Windows PowerShell 5.1's ``>`` redirection writes UTF-16LE with a BOM,
    so the documented one-line generate command must be readable from it.
    """

    if raw.startswith((codecs.BOM_UTF16_LE, codecs.BOM_UTF16_BE)):
        return raw.decode("utf-16")

    return raw.decode("utf-8-sig")


def read_telemetry_summary(
    repository_root: Path | None = None,
) -> dict[str, Any]:
    """Read the S-3/M-2 telemetry artifact and summarise it.

    A missing or empty artifact is ``available: False`` - the same contract
    as the test-results reader - and carries the command that produces it;
    it is never rendered as zeros. An oversized, undecodable or malformed artifact is
    ``available: False``. A tool refusal captured into the artifact is
    reported by its fixed error code only - its detail can name a path.
    """

    root = _resolve_root(repository_root)
    artifact_path = root / TELEMETRY_SUMMARY_ARTIFACT_RELPATH
    location = {
        "artifact_path": TELEMETRY_SUMMARY_ARTIFACT_RELPATH,
        "generate_command": TELEMETRY_GENERATE_COMMAND,
    }

    if not artifact_path.is_file():
        return _unavailable("ARTIFACT_MISSING", **location)

    try:
        stat = artifact_path.stat()

        if stat.st_size > MAX_ARTIFACT_BYTES:
            return _unavailable("ARTIFACT_TOO_LARGE", **location)

        text = _decode_artifact_text(artifact_path.read_bytes())
    except OSError as error:
        return _unavailable("ARTIFACT_UNREADABLE", detail=type(error).__name__, **location)
    except UnicodeDecodeError:
        return _unavailable("ARTIFACT_MALFORMED", **location)

    if not text.strip():
        return _unavailable("ARTIFACT_EMPTY", **location)

    try:
        report = json.loads(text)
    except json.JSONDecodeError:
        return _unavailable("ARTIFACT_MALFORMED", **location)

    if isinstance(report, dict) and "error" in report:
        code = report.get("error")

        return _unavailable(
            "TELEMETRY_TOOL_REFUSED",
            tool_error=code if isinstance(code, str) and code.isidentifier() else "UNKNOWN",
            **location,
        )

    summary = summarize_telemetry_report(report)

    # The artifact's own modification time, so a stale summary is visible
    # as stale rather than read as current.
    summary["artifact_written_at"] = datetime.fromtimestamp(
        stat.st_mtime, UTC
    ).isoformat(timespec="seconds")
    summary.update(location)

    return summary


def read_observability_panels(
    repository_root: Path | None = None,
) -> dict[str, Any]:
    """Both read-only panels in one payload."""

    root = _resolve_root(repository_root)

    return {
        "test_results": read_test_results_panel(root),
        "governance": read_governance_panel(root),
    }
