"""Coverage for the execution-gates panel (/api/execution-gates) and the
dashboard's sectioned layout.

The panel shows the two confidence floors a BUY clears on its way to
execution - ExecutionManager's flat minimum_confidence and RiskEngine's
per-risk-bucket floor - and each symbol's latest risk-stage outcome from
the audit trail. The floors must be the running policy's own values, so the
tests build real RiskPolicy / RiskEngine instances and check the published
numbers against the engine's actual accept/reject boundary rather than
against a copy of the defaults.

Conventions follow tests/test_dashboard_adminlte_and_integrity_panels.py:
real stores under tmp_path, leak markers planted where the projection must
drop them, explicit fail-closed assertions. Nothing touches the
repository's runtime state.
"""

from __future__ import annotations

import re

from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

import pytest

from fastapi.testclient import TestClient

import web_app

from core.audit_event_store import AuditEventStore
from core.risk_engine import (
    BucketPolicy,
    RiskBucket,
    RiskEngine,
    RiskPolicy,
    RiskRequest,
    RiskState,
)
from web_app import create_app


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
NON_LOOPBACK = ("203.0.113.7", 44321)
ALLOCATION_LEAK = "4242.4242"


class _Runtime:
    def __init__(self, **attributes: object) -> None:
        for name, value in attributes.items():
            setattr(self, name, value)


class _Execution:
    def __init__(self, minimum_confidence: object) -> None:
        self.minimum_confidence = minimum_confidence


def _client(runtime: object | None = None, **kwargs: object) -> TestClient:
    return TestClient(create_app(runtime=runtime), **kwargs)


def _audit(tmp_path: Path) -> AuditEventStore:
    return AuditEventStore(tmp_path / "audit" / "events.jsonl", fsync_enabled=False)


def _gates(runtime: object | None) -> dict:
    response = _client(runtime).get("/api/execution-gates")
    assert response.status_code == 200, response.text
    return response.json()


# =====================================================================
# Policy floors
# =====================================================================


def test_route_refuses_non_loopback_peers() -> None:
    response = _client(client=NON_LOOPBACK).get("/api/execution-gates")

    assert response.status_code == 403
    assert response.json()["reason"] == "ATLAS_WEB_PANEL_IS_LOCALHOST_ONLY"


def test_default_policy_floors_are_published_as_the_engine_holds_them(tmp_path: Path) -> None:
    policy = RiskPolicy(total_capital=Decimal("10000"))
    runtime = _Runtime(risk_policy=policy, execution=_Execution(60.0), audit_store=_audit(tmp_path))

    payload = _gates(runtime)

    assert payload["available"] is True
    assert payload["execution_minimum_confidence"] == 60.0
    assert payload["risk_policy"] == {
        "available": True,
        "version": policy.version,
        "global_minimum_confidence_pct": 60.0,
        "buckets": {
            "LOW": {"minimum_confidence_pct": 60.0, "required_confidence_pct": 60.0},
            "MEDIUM": {"minimum_confidence_pct": 70.0, "required_confidence_pct": 70.0},
            "HIGH": {"minimum_confidence_pct": 80.0, "required_confidence_pct": 80.0},
        },
    }


def _custom_policy() -> RiskPolicy:
    # The global floor (0.75) is above LOW's own (0.60), so LOW's effective
    # floor is the global one; HIGH's own (0.90) is above it.
    return RiskPolicy(
        total_capital=Decimal("10000"),
        global_minimum_confidence=Decimal("0.75"),
        buckets={
            RiskBucket.LOW: BucketPolicy(Decimal("0.40"), Decimal("0.60"), Decimal("0.60")),
            RiskBucket.MEDIUM: BucketPolicy(Decimal("0.25"), Decimal("0.77"), Decimal("0.40")),
            RiskBucket.HIGH: BucketPolicy(Decimal("0.10"), Decimal("0.90"), Decimal("0.20")),
        },
        version="custom-policy-test-v1",
    )


def test_a_non_default_policy_is_shown_as_built_not_as_the_defaults() -> None:
    payload = _gates(_Runtime(risk_policy=_custom_policy()))
    buckets = payload["risk_policy"]["buckets"]

    assert payload["risk_policy"]["version"] == "custom-policy-test-v1"
    assert payload["risk_policy"]["global_minimum_confidence_pct"] == 75.0
    assert buckets["LOW"] == {"minimum_confidence_pct": 60.0, "required_confidence_pct": 75.0}
    assert buckets["MEDIUM"] == {"minimum_confidence_pct": 77.0, "required_confidence_pct": 77.0}
    assert buckets["HIGH"] == {"minimum_confidence_pct": 90.0, "required_confidence_pct": 90.0}


def _engine_reason(policy: RiskPolicy, bucket: str, confidence_pct: Decimal) -> str:
    state = RiskState(
        peak_equity=Decimal("10000"),
        current_equity=Decimal("10000"),
        state_ready=True,
        accounting_day_utc=datetime.now(UTC).date().isoformat(),
        policy_version=policy.version,
    )
    request = RiskRequest(
        symbol="BTCUSDT",
        action="BUY",
        # ExecutionManager hands RiskEngine the 0-100 confidence divided by
        # 100 (core/execution_manager.py); the same conversion is used here.
        confidence=confidence_pct / Decimal("100"),
        requested_quote_allocation=Decimal("10"),
        execution_price=Decimal("100"),
        risk_bucket=bucket,
    )
    return RiskEngine(policy).evaluate(request, state).reason_code


@pytest.mark.parametrize("policy_factory", [
    lambda: RiskPolicy(total_capital=Decimal("10000")),
    _custom_policy,
])
@pytest.mark.parametrize("bucket", ["LOW", "MEDIUM", "HIGH"])
def test_published_floor_is_the_real_engine_boundary(policy_factory, bucket: str) -> None:
    policy = policy_factory()
    published = _gates(_Runtime(risk_policy=policy))["risk_policy"]["buckets"][bucket]
    floor = Decimal(str(published["required_confidence_pct"]))

    assert _engine_reason(policy, bucket, floor - Decimal("0.01")) == "CONFIDENCE_BELOW_POLICY"
    assert _engine_reason(policy, bucket, floor) != "CONFIDENCE_BELOW_POLICY"


def test_missing_policy_and_execution_are_unavailable_not_invented() -> None:
    payload = _gates(_Runtime())

    assert payload["execution_minimum_confidence"] is None
    assert payload["risk_policy"] == {"available": False, "reason": "RISK_POLICY_UNAVAILABLE"}
    assert payload["latest_risk_decisions"] == {"available": False, "reason": "AUDIT_STORE_UNAVAILABLE"}


@pytest.mark.parametrize("value", [float("nan"), float("inf"), True, "60", None])
def test_a_non_numeric_execution_minimum_is_not_published(value: object) -> None:
    assert _gates(_Runtime(execution=_Execution(value)))["execution_minimum_confidence"] is None


def test_a_malformed_bucket_policy_fails_closed() -> None:
    class _Bucket:
        minimum_confidence = 0.8  # a float, not the Decimal RiskPolicy holds

    class _Policy:
        version = "malformed-v1"
        global_minimum_confidence = Decimal("0.60")
        buckets = {RiskBucket.HIGH: _Bucket()}

    assert _gates(_Runtime(risk_policy=_Policy()))["risk_policy"] == {
        "available": False,
        "reason": "RISK_POLICY_MALFORMED",
    }


def test_without_a_runtime_the_route_is_503() -> None:
    response = _client().get("/api/execution-gates")

    assert response.status_code == 503
    assert response.json() == {"available": False, "reason": "RUNTIME_NOT_ATTACHED"}


# =====================================================================
# Latest risk-stage outcome per symbol
# =====================================================================


def _request(audit: AuditEventStore, request_id: str, symbol: str, action: str, confidence: float) -> str:
    validated = audit.append(
        event_type=web_app.EXECUTION_REQUEST_VALIDATED,
        source="ExecutionManager",
        aggregate_type="execution_request",
        aggregate_id=request_id,
        payload={
            "approved": True,
            "symbol": symbol,
            "action": action,
            "confidence": confidence,
            "minimum_confidence": 60.0,
        },
        correlation_id=request_id,
    )
    return validated.event_id


def _risk_outcome(audit: AuditEventStore, request_id: str, event_type: str, reason: str, cause: str | None) -> None:
    audit.append(
        event_type=event_type,
        source="ExecutionManager",
        aggregate_type="execution_request",
        aggregate_id=request_id,
        payload={
            "approved": event_type == "RISK_APPROVED",
            "status": "REJECTED",
            "reason": reason,
            "details": {"approved_allocation": ALLOCATION_LEAK, "reason_code": reason},
        },
        correlation_id=request_id,
        causation_id=cause,
    )


def test_latest_risk_decision_per_symbol_comes_from_the_audit_chain(tmp_path: Path) -> None:
    audit = _audit(tmp_path)

    first = _request(audit, "BNBUSDT|open:1|BUY", "BNBUSDT", "BUY", 60.43)
    _risk_outcome(audit, "BNBUSDT|open:1|BUY", "RISK_REJECTED", "CONFIDENCE_BELOW_POLICY", first)
    later = _request(audit, "BNBUSDT|open:2|BUY", "BNBUSDT", "BUY", 63.58)
    _risk_outcome(audit, "BNBUSDT|open:2|BUY", "RISK_REJECTED", "CONFIDENCE_BELOW_POLICY", later)

    approved = _request(audit, "ETHUSDT|open:2|BUY", "ETHUSDT", "BUY", 85.0)
    _risk_outcome(audit, "ETHUSDT|open:2|BUY", "RISK_APPROVED", "ignored", approved)

    # A risk outcome whose validation event is not in the window is never
    # attributed by parsing its request id.
    _risk_outcome(audit, "SOLUSDT|open:2|BUY", "RISK_REJECTED", "CONFIDENCE_BELOW_POLICY", "missing-cause")

    response = _client(_Runtime(audit_store=audit)).get("/api/execution-gates")
    decisions = response.json()["latest_risk_decisions"]
    by_symbol = decisions["by_symbol"]

    assert decisions["available"] is True
    assert decisions["scan_truncated"] is False
    assert set(by_symbol) == {"BNBUSDT", "ETHUSDT"}
    assert by_symbol["BNBUSDT"]["outcome"] == "REJECTED"
    assert by_symbol["BNBUSDT"]["reason"] == "CONFIDENCE_BELOW_POLICY"
    assert by_symbol["BNBUSDT"]["action"] == "BUY"
    assert by_symbol["BNBUSDT"]["confidence"] == 63.58
    assert isinstance(by_symbol["BNBUSDT"]["decided_at"], str)
    assert set(by_symbol["BNBUSDT"]) == {"outcome", "reason", "action", "confidence", "decided_at"}
    assert by_symbol["ETHUSDT"]["outcome"] == "APPROVED"
    assert by_symbol["ETHUSDT"]["reason"] == "RISK_APPROVED"
    assert ALLOCATION_LEAK not in response.text


def test_malformed_audit_lines_are_skipped_not_fatal(tmp_path: Path) -> None:
    audit = _audit(tmp_path)
    cause = _request(audit, "BTCUSDT|open:1|BUY", "BTCUSDT", "BUY", 61.0)
    with audit.file_path.open("a", encoding="utf-8") as handle:
        handle.write("{not json\n")
        handle.write('{"aggregate_type": "execution_request", "event_type": "RISK_REJECTED", '
                     '"payload": {"reason": "X"}, "causation_id": ["unhashable"]}\n')
        handle.write('{"aggregate_type": "execution_request", "event_type": "RISK_REJECTED", "payload": null}\n')
    _risk_outcome(audit, "BTCUSDT|open:1|BUY", "RISK_REJECTED", "CONFIDENCE_BELOW_POLICY", cause)

    by_symbol = _gates(_Runtime(audit_store=audit))["latest_risk_decisions"]["by_symbol"]

    assert list(by_symbol) == ["BTCUSDT"]
    assert by_symbol["BTCUSDT"]["reason"] == "CONFIDENCE_BELOW_POLICY"


def test_an_unreadable_audit_log_is_reported_with_its_own_reason(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    audit = _audit(tmp_path)
    _request(audit, "BTCUSDT|open:1|BUY", "BTCUSDT", "BUY", 61.0)

    def _raise(path: Path):
        raise PermissionError("locked")

    monkeypatch.setattr(web_app, "_read_audit_tail_lines", _raise)

    decisions = _gates(_Runtime(audit_store=audit))["latest_risk_decisions"]

    assert decisions == {
        "available": False,
        "reason": "AUDIT_LOG_UNREADABLE",
        "error_type": "PermissionError",
    }


# =====================================================================
# Dashboard layout
# =====================================================================


def _dashboard() -> str:
    return _client().get("/dashboard").text


def _section(body: str, title_id: str) -> str:
    match = re.search(
        rf'<section\b[^>]*aria-labelledby="{title_id}".*?</section>',
        body,
        re.DOTALL,
    )
    assert match is not None, title_id
    return match.group(0)


def test_dashboard_is_grouped_into_top_level_sections() -> None:
    body = _dashboard()

    expected = {
        "section-decisions-title": ("signals-grid", "execution-gates-legend", "trade-log"),
        "section-execution-title": ("execution-health-panel", "risk-accounting-panel", "trade-history-panel"),
        "section-integrity-title": ("system-integrity-panel", "governance-panel", "test-results-panel", "known-limitations-panel"),
        "section-telemetry-title": ("telemetry-panel",),
    }

    for title_id, element_ids in expected.items():
        section = _section(body, title_id)
        assert 'data-lte-toggle="card-collapse"' in section, title_id
        for element_id in element_ids:
            assert f'id="{element_id}"' in section, (title_id, element_id)


def test_known_limitations_are_nested_collapsed_inside_system_integrity() -> None:
    section = _section(_dashboard(), "section-integrity-title")
    details = re.search(r"<details\b[^>]*>.*?</details>", section, re.DOTALL)

    assert details is not None
    assert 'id="known-limitations-panel"' in details.group(0)
    assert 'id="known-limitations-count"' in details.group(0)
    # Collapsed by default: no open attribute on the static element.
    assert " open" not in details.group(0).split(">", 1)[0]


def test_dashboard_reads_the_gates_from_the_api_not_from_literals() -> None:
    body = _dashboard()

    assert "fetch('/api/execution-gates')" in body
    assert "required_confidence_pct" in body
    assert "execution_minimum_confidence" in body
    # The Risk agent's regime line is labelled as a volatility regime, never
    # as a bare "rejim:" next to the RiskEngine risk bucket.
    assert "volatilite rejimi:" in body
    assert ">rejim: " not in body
    assert "risk bucket" in body
