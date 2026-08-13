"""Block 3 / Package 2, M-E: harden OperationContext/OperationResult against
the leak vectors measured in the Package-2 Phase-1 investigation:

1. post-construction metadata mutation (top-level and nested)
2. future scalar field leakage (model_id, tool_id, cost, reason_code, actor_id)
3. OperationContext field leakage (actor_id, request_id, symbol, mode)
4. evidence_ids leakage

The accepted limitation from Phase 1 is retained: an opaque secret string
under a benign/unrecognized key (e.g. metadata={"raw": "sk-plain-token"}) is
not required to be detected beyond the existing atlas_security sanitizer
contract.
"""

from __future__ import annotations

from types import MappingProxyType

import pytest

from core.operational_contracts import OperationContext, OperationResult


# ---------------------------------------------------------------------------
# 1. post-construction metadata mutation
# ---------------------------------------------------------------------------


def test_metadata_rejects_top_level_post_construction_mutation():
    result = OperationResult(
        operation="op", status="OK", component="c",
        metadata={"api_key": "sk-original", "symbol": "BTCUSDT"},
    )
    assert isinstance(result.metadata, MappingProxyType)
    with pytest.raises(TypeError):
        result.metadata["api_key"] = "sk-injected-post-construction"
    assert result.metadata["api_key"] == "[REDACTED]"


def test_metadata_caller_dict_mutation_after_construction_does_not_leak():
    source = {"api_key": "sk-should-not-leak", "symbol": "BTCUSDT"}
    result = OperationResult(operation="op", status="OK", component="c", metadata=source)
    source["api_key"] = "sk-mutated-after-construction"
    assert result.metadata["api_key"] == "[REDACTED]"


def test_metadata_nested_structures_are_frozen_and_isolated():
    source = {"outer": {"api_key": "sk-nested"}, "items": [{"token": "sk-list-item"}]}
    result = OperationResult(operation="op", status="OK", component="c", metadata=source)

    assert isinstance(result.metadata["outer"], MappingProxyType)
    with pytest.raises(TypeError):
        result.metadata["outer"]["api_key"] = "sk-injected-nested"
    assert result.metadata["outer"]["api_key"] == "[REDACTED]"

    assert isinstance(result.metadata["items"], tuple)
    assert isinstance(result.metadata["items"][0], MappingProxyType)
    assert result.metadata["items"][0]["token"] == "[REDACTED]"

    source["outer"]["api_key"] = "sk-mutated-after-construction"
    assert result.metadata["outer"]["api_key"] == "[REDACTED]"


def test_metadata_default_is_frozen_empty_mapping():
    result = OperationResult(operation="op", status="OK", component="c")
    assert isinstance(result.metadata, MappingProxyType)
    assert dict(result.metadata) == {}


# ---------------------------------------------------------------------------
# 2. future scalar field leakage
# ---------------------------------------------------------------------------


def test_operation_result_future_scalar_fields_are_sanitized():
    result = OperationResult(
        operation="op", status="OK", component="c",
        reason_code="password=hunter2",
        actor_id="token=abc123456",
        model_provider="api_key=sk-provider",
        model_id="Bearer sk-model-secret",
        tool_id="user@example.com",
        cost="api_key=sk-cost",
    )
    assert "hunter2" not in result.reason_code
    assert "abc123456" not in result.actor_id
    assert "sk-provider" not in result.model_provider
    assert "sk-model-secret" not in result.model_id
    assert result.tool_id == "[REDACTED]"
    assert "sk-cost" not in result.cost


def test_operation_result_repr_and_str_do_not_expose_future_field_secrets():
    result = OperationResult(
        operation="op", status="OK", component="c",
        model_id="Bearer sk-model-secret",
        cost="api_key=sk-cost",
        tool_id="user@example.com",
        reason_code="password=hunter2",
        actor_id="token=abc123456",
    )
    for form in (repr(result), str(result)):
        assert "sk-model-secret" not in form
        assert "sk-cost" not in form
        assert "user@example.com" not in form
        assert "hunter2" not in form
        assert "abc123456" not in form


def test_operation_result_token_count_and_latency_are_untouched_non_strings():
    result = OperationResult(
        operation="op", status="OK", component="c",
        token_count=42, latency_ms=12.5,
    )
    assert result.token_count == 42
    assert result.latency_ms == 12.5


# ---------------------------------------------------------------------------
# 3. OperationContext field leakage
# ---------------------------------------------------------------------------


def test_operation_context_secret_bearing_fields_are_sanitized():
    context = OperationContext(
        component="execution_manager", operation="risk_check",
        actor_id="api_key=sk-ctx-secret",
        request_id="Bearer sk-req",
        symbol="user@example.com",
        mode="password=hunter2",
    )
    assert "sk-ctx-secret" not in context.actor_id
    assert "sk-req" not in context.request_id
    assert context.symbol == "[REDACTED]"
    assert "hunter2" not in context.mode


def test_operation_context_repr_does_not_expose_secrets():
    context = OperationContext(
        component="execution_manager", operation="risk_check",
        actor_id="api_key=sk-ctx-secret", request_id="Bearer sk-req",
    )
    assert "sk-ctx-secret" not in repr(context)
    assert "sk-req" not in repr(context)


def test_operation_context_normal_values_are_unchanged():
    context = OperationContext(
        component="execution_manager", operation="risk_check",
        actor_id="operator-1", symbol="BTCUSDT", mode="PAPER",
    )
    assert context.component == "execution_manager"
    assert context.operation == "risk_check"
    assert context.actor_id == "operator-1"
    assert context.symbol == "BTCUSDT"
    assert context.mode == "PAPER"


def test_operation_context_trace_and_operation_ids_are_not_mutated_by_sanitization():
    context = OperationContext(component="execution_manager", operation="risk_check")
    assert len(context.trace_id) == 36
    assert len(context.operation_id) == 36
    assert context.trace_id.count("-") == 4


def test_from_context_preserves_sanitized_boundary():
    context = OperationContext(
        component="execution_manager", operation="risk_check",
        actor_id="api_key=sk-ctx-secret",
    )
    result = OperationResult.from_context(
        context, status="OK",
        metadata={"token": "sk-should-be-redacted"},
        model_id="Bearer sk-future-secret",
    )
    assert "sk-ctx-secret" not in result.actor_id
    assert result.trace_id == context.trace_id
    assert result.metadata["token"] == "[REDACTED]"
    assert "sk-future-secret" not in result.model_id


# ---------------------------------------------------------------------------
# 4. evidence_ids leakage
# ---------------------------------------------------------------------------


def test_evidence_ids_are_sanitized_and_immutable():
    result = OperationResult(
        operation="op", status="OK", component="c",
        evidence_ids=("api_key=sk-ev", "evidence-plain-id"),
    )
    assert "sk-ev" not in result.evidence_ids[0]
    assert result.evidence_ids[1] == "evidence-plain-id"
    assert isinstance(result.evidence_ids, tuple)


# ---------------------------------------------------------------------------
# Accepted limitation retained: opaque secret under a benign key
# ---------------------------------------------------------------------------


def test_opaque_secret_under_benign_key_is_not_required_to_be_detected():
    result = OperationResult(
        operation="op", status="OK", component="c",
        metadata={"raw": "sk-plain-token-value"},
    )
    assert result.metadata["raw"] == "sk-plain-token-value"


# ---------------------------------------------------------------------------
# Existing public behavior must not regress
# ---------------------------------------------------------------------------


def test_operation_context_requires_component_and_operation():
    with pytest.raises(ValueError, match="component"):
        OperationContext(component="", operation="risk_check")
    with pytest.raises(ValueError, match="operation"):
        OperationContext(component="execution_manager", operation="")


def test_operation_result_sanitizes_secret_bearing_metadata():
    result = OperationResult(
        operation="risk_check", status="BLOCKED", component="execution_manager",
        metadata={"api_key": "sk-should-not-leak", "symbol": "BTCUSDT"},
    )
    assert result.metadata["api_key"] == "[REDACTED]"
    assert result.metadata["symbol"] == "BTCUSDT"
