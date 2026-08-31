"""Block 3 / Package 3: provider and tool contract validation.

Covers test classes A (provider-neutral contracts), B (capability
representation), C (free/local/paid cost classification), D
(secret-exclusion / repr safety), and E (tool side-effect classification).

No network, no credential, no provider SDK, no MCP server: every provider
and tool in these tests is a deterministic in-process fake.
"""

from __future__ import annotations

from decimal import Decimal as D

import pytest

from core.model_provider_contracts import (
    FREE_FIRST_PREFERENCE,
    CapabilityClass,
    CostMetadata,
    InvocationOutcome,
    ModelCapability,
    ModelInvocation,
    ModelInvocationResult,
    ModelProviderDescriptor,
)
from core.operational_contracts import OperationContext
from core.tool_gateway_contracts import (
    SideEffectClass,
    ToolDescriptor,
    ToolInvocation,
    ToolInvocationResult,
)


def context(**overrides) -> OperationContext:
    values = dict(component="research_agent", operation="fetch_reference", actor_id="agent-1")
    values.update(overrides)
    return OperationContext(**values)


def free_cost(capability_class=CapabilityClass.LOCAL) -> CostMetadata:
    return CostMetadata(capability_class=capability_class)


def local_model() -> ModelProviderDescriptor:
    return ModelProviderDescriptor(
        provider_id="local-runtime", model_id="local-small",
        capability_class=CapabilityClass.LOCAL, requires_network=False,
        capabilities=frozenset({ModelCapability.TEXT_COMPLETION}),
    )


def read_only_tool() -> ToolDescriptor:
    return ToolDescriptor(
        tool_id="filesystem-read", side_effect=SideEffectClass.READ_ONLY,
        capability_class=CapabilityClass.LOCAL,
    )


# ---------------------------------------------------------------------------
# A. provider-neutral contracts
# ---------------------------------------------------------------------------


def test_descriptor_requires_provider_and_model_identity():
    for bad in ("", "   "):
        with pytest.raises(ValueError, match="provider_id"):
            ModelProviderDescriptor(
                provider_id=bad, model_id="m", capability_class=CapabilityClass.FREE_TIER,
            )
        with pytest.raises(ValueError, match="model_id"):
            ModelProviderDescriptor(
                provider_id="p", model_id=bad, capability_class=CapabilityClass.FREE_TIER,
            )


def test_descriptor_qualified_id_is_provider_and_model():
    assert local_model().qualified_id == "local-runtime:local-small"


def test_invocation_requires_typed_context_descriptor_and_cost():
    with pytest.raises(ValueError, match="context"):
        ModelInvocation(
            context="not-a-context", descriptor=local_model(), task_type="t",
            input_reference="ref-1", cost=free_cost(),
        )
    with pytest.raises(ValueError, match="descriptor"):
        ModelInvocation(
            context=context(), descriptor="nope", task_type="t",
            input_reference="ref-1", cost=free_cost(),
        )
    with pytest.raises(ValueError, match="cost"):
        ModelInvocation(
            context=context(), descriptor=local_model(), task_type="t",
            input_reference="ref-1", cost="free",
        )


def test_invocation_id_is_the_context_operation_id():
    ctx = context()
    invocation = ModelInvocation(
        context=ctx, descriptor=local_model(), task_type="summarize",
        input_reference="ref-1", cost=free_cost(),
    )
    assert invocation.invocation_id == ctx.operation_id


def test_result_rejects_negative_and_nan_latency():
    for bad in (-1.0, float("nan")):
        with pytest.raises(ValueError, match="latency_ms"):
            ModelInvocationResult(
                invocation_id="i", provider_id="p", model_id="m",
                outcome=InvocationOutcome.OK, reason_code="OK", latency_ms=bad,
            )


def test_result_projects_onto_the_audited_operation_contract():
    result = ModelInvocationResult(
        invocation_id="i", provider_id="local-runtime", model_id="local-small",
        outcome=InvocationOutcome.OK, reason_code="OK",
        cost=free_cost(), metadata={"api_key": "sk-must-not-survive"},
    )
    projected = result.to_operation_result(component="gateway", operation="invoke_model")
    assert projected.status == "OK"
    assert projected.model_provider == "local-runtime"
    assert projected.metadata["api_key"] == "[REDACTED]"


# ---------------------------------------------------------------------------
# B. capability representation
# ---------------------------------------------------------------------------


def test_unknown_capability_is_rejected():
    with pytest.raises(ValueError):
        ModelProviderDescriptor(
            provider_id="p", model_id="m", capability_class=CapabilityClass.FREE_TIER,
            capabilities=frozenset({"TELEPATHY"}),
        )


def test_unknown_capability_class_is_rejected():
    with pytest.raises(ValueError):
        ModelProviderDescriptor(
            provider_id="p", model_id="m", capability_class="FREE_BEER",
        )


def test_invocation_requiring_undeclared_capability_is_rejected():
    with pytest.raises(ValueError, match="required capabilities"):
        ModelInvocation(
            context=context(), descriptor=local_model(), task_type="classify",
            input_reference="ref-1", cost=free_cost(),
            required_capabilities=frozenset({ModelCapability.EMBEDDING}),
        )


def test_invocation_requiring_declared_capability_is_accepted():
    invocation = ModelInvocation(
        context=context(), descriptor=local_model(), task_type="complete",
        input_reference="ref-1", cost=free_cost(),
        required_capabilities=frozenset({ModelCapability.TEXT_COMPLETION}),
    )
    assert ModelCapability.TEXT_COMPLETION in invocation.required_capabilities


def test_local_capability_may_not_require_network():
    with pytest.raises(ValueError, match="LOCAL"):
        ModelProviderDescriptor(
            provider_id="p", model_id="m", capability_class=CapabilityClass.LOCAL,
            requires_network=True,
        )


def test_max_input_tokens_must_be_a_positive_integer():
    for bad in (0, -1, True, 1.5):
        with pytest.raises(ValueError, match="max_input_tokens"):
            ModelProviderDescriptor(
                provider_id="p", model_id="m",
                capability_class=CapabilityClass.FREE_TIER, max_input_tokens=bad,
            )


# ---------------------------------------------------------------------------
# C. free / local / paid cost classification
# ---------------------------------------------------------------------------


def test_free_first_preference_orders_local_before_paid():
    assert FREE_FIRST_PREFERENCE == (
        CapabilityClass.LOCAL, CapabilityClass.OPEN_SOURCE,
        CapabilityClass.FREE_TIER, CapabilityClass.PAID,
    )
    assert FREE_FIRST_PREFERENCE.index(CapabilityClass.LOCAL) < FREE_FIRST_PREFERENCE.index(
        CapabilityClass.PAID
    )


def test_only_paid_incurs_monetary_cost():
    assert CapabilityClass.PAID.incurs_monetary_cost is True
    for other in (CapabilityClass.LOCAL, CapabilityClass.OPEN_SOURCE, CapabilityClass.FREE_TIER):
        assert other.incurs_monetary_cost is False


def test_local_and_open_source_must_not_declare_a_cost():
    for capability_class in (CapabilityClass.LOCAL, CapabilityClass.OPEN_SOURCE):
        with pytest.raises(ValueError, match="must not declare a cost"):
            CostMetadata(capability_class=capability_class, estimated_cost=D("0.01"))


def test_paid_must_declare_a_positive_estimate():
    """A paid provider cannot present itself as costing nothing."""
    with pytest.raises(ValueError, match="PAID"):
        CostMetadata(capability_class=CapabilityClass.PAID, estimated_cost=D("0"))


def test_free_tier_may_declare_an_overage_estimate():
    cost = CostMetadata(capability_class=CapabilityClass.FREE_TIER, estimated_cost=D("0.25"))
    assert cost.estimated_cost == D("0.25")
    # Classified free, but not actually free: is_free consults the amount too.
    assert cost.is_free is False


def test_is_free_requires_both_class_and_amount_to_be_free():
    assert CostMetadata(capability_class=CapabilityClass.LOCAL).is_free is True
    assert CostMetadata(capability_class=CapabilityClass.FREE_TIER).is_free is True
    paid = CostMetadata(capability_class=CapabilityClass.PAID, estimated_cost=D("1"))
    assert paid.is_free is False


def test_cost_rejects_negative_nan_infinity_and_float():
    with pytest.raises(ValueError, match="negative"):
        CostMetadata(capability_class=CapabilityClass.FREE_TIER, estimated_cost=D("-1"))
    for bad in (D("NaN"), D("Infinity")):
        with pytest.raises(ValueError, match="finite"):
            CostMetadata(capability_class=CapabilityClass.FREE_TIER, estimated_cost=bad)
    with pytest.raises(ValueError, match="must not be float"):
        CostMetadata(capability_class=CapabilityClass.FREE_TIER, estimated_cost=0.1)


def test_cost_actual_is_validated_like_estimate():
    with pytest.raises(ValueError, match="actual_cost"):
        CostMetadata(
            capability_class=CapabilityClass.FREE_TIER, actual_cost=D("-0.01"),
        )


def test_invocation_cost_class_must_match_descriptor_class():
    with pytest.raises(ValueError, match="capability_class must match"):
        ModelInvocation(
            context=context(), descriptor=local_model(), task_type="t",
            input_reference="ref-1",
            cost=CostMetadata(capability_class=CapabilityClass.FREE_TIER),
        )


# ---------------------------------------------------------------------------
# D. secret exclusion / repr safety
# ---------------------------------------------------------------------------


def test_secret_shaped_identifiers_are_sanitized_not_stored_raw():
    descriptor = ModelProviderDescriptor(
        provider_id="api_key=sk-live-must-not-leak", model_id="m",
        capability_class=CapabilityClass.FREE_TIER,
    )
    assert "sk-live-must-not-leak" not in descriptor.provider_id
    assert "sk-live-must-not-leak" not in repr(descriptor)


def test_tool_identifiers_are_sanitized():
    descriptor = ToolDescriptor(
        tool_id="token=abc123456789", side_effect=SideEffectClass.READ_ONLY,
        capability_class=CapabilityClass.LOCAL,
    )
    assert "abc123456789" not in descriptor.tool_id
    assert "abc123456789" not in repr(descriptor)


def test_invocation_repr_does_not_expose_secret_metadata():
    invocation = ModelInvocation(
        context=context(actor_id="api_key=sk-actor-secret"),
        descriptor=local_model(), task_type="t", input_reference="ref-1",
        cost=free_cost(),
    )
    assert "sk-actor-secret" not in repr(invocation)


def _metadata_carrying_contracts():
    """Every Package-3 contract that accepts caller-supplied metadata."""
    return (
        ModelInvocation(
            context=context(), descriptor=local_model(), task_type="t",
            input_reference="ref-1", cost=free_cost(),
            metadata={"api_key": "sk-must-not-survive", "symbol": "BTCUSDT"},
        ),
        ModelInvocationResult(
            invocation_id="i", provider_id="p", model_id="m",
            outcome=InvocationOutcome.OK, reason_code="OK",
            metadata={"api_key": "sk-must-not-survive", "symbol": "BTCUSDT"},
        ),
        ToolInvocation(
            context=context(), descriptor=read_only_tool(), operation="read_file",
            cost=free_cost(),
            metadata={"api_key": "sk-must-not-survive", "symbol": "BTCUSDT"},
        ),
        ToolInvocationResult(
            invocation_id="i", tool_id="filesystem-read", outcome=InvocationOutcome.OK,
            reason_code="OK",
            metadata={"api_key": "sk-must-not-survive", "symbol": "BTCUSDT"},
        ),
    )


def test_every_contract_sanitizes_its_metadata_on_construction():
    """A secret must not survive in any invocation or result, not merely in
    the OperationResult projection of one."""
    for contract in _metadata_carrying_contracts():
        assert contract.metadata["api_key"] == "[REDACTED]", type(contract).__name__
        assert contract.metadata["symbol"] == "BTCUSDT", type(contract).__name__


def test_every_contract_keeps_secrets_out_of_repr():
    for contract in _metadata_carrying_contracts():
        assert "sk-must-not-survive" not in repr(contract), type(contract).__name__
        assert "sk-must-not-survive" not in str(contract), type(contract).__name__


def test_every_contract_metadata_rejects_post_construction_mutation():
    for contract in _metadata_carrying_contracts():
        with pytest.raises(TypeError):
            contract.metadata["api_key"] = "sk-injected"
        assert contract.metadata["api_key"] == "[REDACTED]", type(contract).__name__


def test_caller_metadata_mutation_after_construction_does_not_leak():
    source = {"api_key": "sk-original"}
    invocation = ToolInvocation(
        context=context(), descriptor=read_only_tool(), operation="read_file",
        cost=free_cost(), metadata=source,
    )
    source["api_key"] = "sk-mutated-after-construction"
    assert invocation.metadata["api_key"] == "[REDACTED]"
    assert "sk-mutated-after-construction" not in repr(invocation)


def test_nested_metadata_is_sanitized_and_frozen():
    result = ToolInvocationResult(
        invocation_id="i", tool_id="filesystem-read", outcome=InvocationOutcome.OK,
        reason_code="OK", metadata={"outer": {"password": "hunter2"}},
    )
    assert result.metadata["outer"]["password"] == "[REDACTED]"
    with pytest.raises(TypeError):
        result.metadata["outer"]["password"] = "hunter2"


def test_identifiers_reject_control_characters_and_overlong_values():
    with pytest.raises(ValueError, match="control characters"):
        ToolDescriptor(
            tool_id="evil\nlog-injection", side_effect=SideEffectClass.READ_ONLY,
            capability_class=CapabilityClass.LOCAL,
        )
    with pytest.raises(ValueError, match="too long"):
        ToolDescriptor(
            tool_id="x" * 201, side_effect=SideEffectClass.READ_ONLY,
            capability_class=CapabilityClass.LOCAL,
        )


def test_no_credential_field_exists_on_any_contract():
    """Structural: a credential must have nowhere to live in these types."""
    forbidden = {"api_key", "apikey", "secret", "token", "password", "credential",
                 "authorization", "bearer"}
    for contract in (
        ModelProviderDescriptor, ModelInvocation, ModelInvocationResult,
        ToolDescriptor, ToolInvocation, ToolInvocationResult, CostMetadata,
    ):
        names = {name.lower() for name in contract.__dataclass_fields__}
        assert not (names & forbidden), contract.__name__


# ---------------------------------------------------------------------------
# E. tool side-effect classification
# ---------------------------------------------------------------------------


def test_side_effect_read_only_is_the_only_permissionless_class():
    assert SideEffectClass.READ_ONLY.requires_explicit_permission is False
    for elevated in (
        SideEffectClass.LOCAL_WRITE, SideEffectClass.EXTERNAL_WRITE,
        SideEffectClass.FINANCIAL, SideEffectClass.SECURITY_SENSITIVE,
    ):
        assert elevated.requires_explicit_permission is True


def test_unknown_side_effect_class_is_rejected():
    with pytest.raises(ValueError):
        ToolDescriptor(
            tool_id="t", side_effect="HARMLESS_PROMISE",
            capability_class=CapabilityClass.LOCAL,
        )


def test_elevated_tool_must_declare_a_required_permission():
    for elevated in (
        SideEffectClass.LOCAL_WRITE, SideEffectClass.EXTERNAL_WRITE,
        SideEffectClass.FINANCIAL, SideEffectClass.SECURITY_SENSITIVE,
    ):
        with pytest.raises(ValueError, match="required_permission"):
            ToolDescriptor(
                tool_id="t", side_effect=elevated,
                capability_class=CapabilityClass.FREE_TIER,
            )


def test_read_only_tool_must_not_declare_a_permission():
    """Blocks the 'read-only tool that quietly wants financial rights' shape."""
    with pytest.raises(ValueError, match="READ_ONLY"):
        ToolDescriptor(
            tool_id="t", side_effect=SideEffectClass.READ_ONLY,
            capability_class=CapabilityClass.LOCAL,
            required_permission="trading.execute",
        )


def test_local_tool_may_not_require_network():
    with pytest.raises(ValueError, match="LOCAL"):
        ToolDescriptor(
            tool_id="t", side_effect=SideEffectClass.READ_ONLY,
            capability_class=CapabilityClass.LOCAL, requires_network=True,
        )


def test_tool_permission_satisfaction_is_explicit():
    financial = ToolDescriptor(
        tool_id="exchange-order", side_effect=SideEffectClass.FINANCIAL,
        capability_class=CapabilityClass.FREE_TIER, requires_network=True,
        required_permission="trading.execute",
    )
    without = ToolInvocation(
        context=context(), descriptor=financial, operation="place_order",
        cost=CostMetadata(capability_class=CapabilityClass.FREE_TIER),
    )
    assert without.has_required_permission is False

    with_grant = ToolInvocation(
        context=context(), descriptor=financial, operation="place_order",
        cost=CostMetadata(capability_class=CapabilityClass.FREE_TIER),
        granted_permissions=frozenset({"trading.execute"}),
    )
    assert with_grant.has_required_permission is True


def test_read_only_tool_needs_no_permission_grant():
    invocation = ToolInvocation(
        context=context(), descriptor=read_only_tool(), operation="read_file",
        cost=free_cost(),
    )
    assert invocation.has_required_permission is True


def test_timeout_must_be_a_positive_integer():
    for bad in (0, -1, True, 1.5):
        with pytest.raises(ValueError, match="timeout_ms"):
            ToolInvocation(
                context=context(), descriptor=read_only_tool(), operation="read_file",
                cost=free_cost(), timeout_ms=bad,
            )
