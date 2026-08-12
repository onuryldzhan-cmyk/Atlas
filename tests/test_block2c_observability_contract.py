"""Block 2C Part C/E: observability and policy-gate seams.

Covers H6 / P5 from the Block 2C work order: structured operation metadata
is sanitized through the existing atlas_security authority before it is
observable, and the minimal PolicyDecision/PolicyGate shapes hold their
required fields.
"""

from __future__ import annotations

import pytest

from core.operational_contracts import (
    OperationContext,
    OperationResult,
    PolicyDecision,
)


def test_operation_context_requires_component_and_operation():
    with pytest.raises(ValueError, match="component"):
        OperationContext(component="", operation="risk_check")
    with pytest.raises(ValueError, match="operation"):
        OperationContext(component="execution_manager", operation="")


def test_operation_context_generates_trace_and_operation_ids():
    first = OperationContext(component="execution_manager", operation="risk_check")
    second = OperationContext(component="execution_manager", operation="risk_check")
    assert first.trace_id != second.trace_id
    assert first.operation_id != second.operation_id


def test_operation_result_sanitizes_secret_bearing_metadata():
    result = OperationResult(
        operation="risk_check", status="BLOCKED", component="execution_manager",
        metadata={"api_key": "sk-should-not-leak", "symbol": "BTCUSDT"},
    )
    assert result.metadata["api_key"] == "[REDACTED]"
    assert result.metadata["symbol"] == "BTCUSDT"


def test_operation_result_from_context_copies_identity():
    context = OperationContext(
        component="execution_manager", operation="risk_check", actor_id="operator-1",
    )
    result = OperationResult.from_context(
        context, status="APPROVED", reason_code="OK", latency_ms=12.5,
    )
    assert result.trace_id == context.trace_id
    assert result.actor_id == "operator-1"
    assert result.operation == "risk_check"
    assert result.component == "execution_manager"


def test_operation_result_requires_status_and_operation_and_component():
    with pytest.raises(ValueError):
        OperationResult(operation="", status="OK", component="x")
    with pytest.raises(ValueError):
        OperationResult(operation="x", status="", component="x")
    with pytest.raises(ValueError):
        OperationResult(operation="x", status="OK", component="")


def test_policy_decision_requires_reason_policy_and_operation():
    decision = PolicyDecision(
        allowed=False, reason_code="LIVE_TRADING_NOT_AUTHORIZED",
        policy_id="live-trading-gate-v1", operation="submit_live_order",
    )
    assert decision.allowed is False

    with pytest.raises(ValueError, match="reason_code"):
        PolicyDecision(allowed=True, reason_code="", policy_id="p", operation="op")
    with pytest.raises(ValueError, match="policy_id"):
        PolicyDecision(allowed=True, reason_code="r", policy_id="", operation="op")
    with pytest.raises(ValueError, match="operation"):
        PolicyDecision(allowed=True, reason_code="r", policy_id="p", operation="")
