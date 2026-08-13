"""Block 3 / Package 3: gateway enforcement and adversarial cases.

Covers test class F (policy deny-before-invoke) plus the Package-3 red-team
attack list: adapter substitution, policy-gate failure, adapter exceptions,
malformed adapter results, duplicate invocation identity, actor spoofing,
paid-capability escape, and network-required tools claiming to be local.

The central property under test is that a denial means *nothing happened*:
every fake adapter records whether it was reached, and a denied invocation
must leave that recorder untouched.

No network, no credential, no provider SDK, no MCP server.
"""

from __future__ import annotations

from decimal import Decimal as D

import pytest

from core.model_provider_contracts import (
    CapabilityClass,
    CostMetadata,
    InvocationOutcome,
    ModelInvocation,
    ModelInvocationResult,
    ModelProviderDescriptor,
)
from core.operational_contracts import OperationContext, PolicyDecision
from core.tool_gateway_contracts import (
    DEFAULT_ALLOWED_SIDE_EFFECTS,
    CapabilityGateway,
    GatewayReason,
    SideEffectClass,
    ToolDescriptor,
    ToolInvocation,
    ToolInvocationResult,
)


# ---------------------------------------------------------------------------
# deterministic fakes
# ---------------------------------------------------------------------------


class AllowGate:
    def __init__(self, operation: str = "read_file") -> None:
        self.operation = operation
        self.calls = 0

    def evaluate(self, context: OperationContext) -> PolicyDecision:
        self.calls += 1
        return PolicyDecision(
            allowed=True, reason_code="ALLOWED", policy_id="test-gate",
            operation=self.operation, actor_id=context.actor_id,
        )


class DenyGate:
    def __init__(self, operation: str = "read_file") -> None:
        self.operation = operation

    def evaluate(self, context: OperationContext) -> PolicyDecision:
        return PolicyDecision(
            allowed=False, reason_code="NOT_AUTHORIZED", policy_id="test-gate",
            operation=self.operation,
        )


class ExplodingGate:
    def evaluate(self, context: OperationContext) -> PolicyDecision:
        raise RuntimeError("gate backend unavailable")


class NonDecisionGate:
    def evaluate(self, context: OperationContext):
        return "yes, definitely allowed"


class RecordingToolAdapter:
    """Records whether it was reached; that is the whole point."""

    def __init__(self, descriptor: ToolDescriptor, *, result=None, raises=None) -> None:
        self._descriptor = descriptor
        self._result = result
        self._raises = raises
        self.invocations = 0

    @property
    def descriptor(self) -> ToolDescriptor:
        return self._descriptor

    def invoke(self, invocation: ToolInvocation) -> ToolInvocationResult:
        self.invocations += 1
        if self._raises is not None:
            raise self._raises
        if self._result is not None:
            return self._result
        return ToolInvocationResult(
            invocation_id=invocation.invocation_id,
            tool_id=invocation.descriptor.tool_id,
            outcome=InvocationOutcome.OK, reason_code="OK",
        )


class RecordingModelAdapter:
    def __init__(self, descriptor: ModelProviderDescriptor, *, result=None, raises=None) -> None:
        self._descriptor = descriptor
        self._result = result
        self._raises = raises
        self.invocations = 0

    @property
    def descriptor(self) -> ModelProviderDescriptor:
        return self._descriptor

    def invoke(self, invocation: ModelInvocation) -> ModelInvocationResult:
        self.invocations += 1
        if self._raises is not None:
            raise self._raises
        if self._result is not None:
            return self._result
        return ModelInvocationResult(
            invocation_id=invocation.invocation_id,
            provider_id=invocation.descriptor.provider_id,
            model_id=invocation.descriptor.model_id,
            outcome=InvocationOutcome.OK, reason_code="OK",
        )


# ---------------------------------------------------------------------------
# builders
# ---------------------------------------------------------------------------


def context(operation: str = "read_file", **overrides) -> OperationContext:
    values = dict(component="research_agent", operation=operation, actor_id="agent-1")
    values.update(overrides)
    return OperationContext(**values)


READ_TOOL = ToolDescriptor(
    tool_id="filesystem-read", side_effect=SideEffectClass.READ_ONLY,
    capability_class=CapabilityClass.LOCAL,
)
FINANCIAL_TOOL = ToolDescriptor(
    tool_id="exchange-order", side_effect=SideEffectClass.FINANCIAL,
    capability_class=CapabilityClass.FREE_TIER, requires_network=True,
    required_permission="trading.execute",
)
LOCAL_MODEL = ModelProviderDescriptor(
    provider_id="local-runtime", model_id="local-small",
    capability_class=CapabilityClass.LOCAL, requires_network=False,
)
PAID_MODEL = ModelProviderDescriptor(
    provider_id="paid-vendor", model_id="expensive-1",
    capability_class=CapabilityClass.PAID,
)


def tool_invocation(descriptor=READ_TOOL, *, operation="read_file", **overrides):
    values = dict(
        context=context(operation), descriptor=descriptor, operation=operation,
        cost=CostMetadata(capability_class=descriptor.capability_class),
    )
    values.update(overrides)
    return ToolInvocation(**values)


def model_invocation(descriptor=LOCAL_MODEL, *, operation="infer", **overrides):
    cost = (
        CostMetadata(capability_class=CapabilityClass.PAID, estimated_cost=D("0.5"))
        if descriptor.capability_class is CapabilityClass.PAID
        else CostMetadata(capability_class=descriptor.capability_class)
    )
    values = dict(
        context=context(operation), descriptor=descriptor, task_type="summarize",
        input_reference="ref-1", cost=cost,
    )
    values.update(overrides)
    return ModelInvocation(**values)


# ---------------------------------------------------------------------------
# F. policy deny-before-invoke
# ---------------------------------------------------------------------------


def test_approved_read_only_tool_reaches_the_adapter():
    gateway = CapabilityGateway(AllowGate())
    adapter = RecordingToolAdapter(READ_TOOL)
    result = gateway.invoke_tool(tool_invocation(), adapter)
    assert result.succeeded
    assert adapter.invocations == 1


def test_policy_denial_never_reaches_the_adapter():
    gateway = CapabilityGateway(DenyGate())
    adapter = RecordingToolAdapter(READ_TOOL)
    result = gateway.invoke_tool(tool_invocation(), adapter)
    assert result.outcome is InvocationOutcome.DENIED
    assert result.reason_code == GatewayReason.POLICY_DENIED.value
    assert adapter.invocations == 0


def test_policy_gate_exception_fails_closed_and_never_invokes():
    gateway = CapabilityGateway(ExplodingGate())
    adapter = RecordingToolAdapter(READ_TOOL)
    result = gateway.invoke_tool(tool_invocation(), adapter)
    assert result.outcome is InvocationOutcome.DENIED
    assert result.reason_code == GatewayReason.POLICY_GATE_ERROR.value
    assert adapter.invocations == 0


def test_policy_gate_returning_a_non_decision_fails_closed():
    gateway = CapabilityGateway(NonDecisionGate())
    adapter = RecordingToolAdapter(READ_TOOL)
    result = gateway.invoke_tool(tool_invocation(), adapter)
    assert result.outcome is InvocationOutcome.DENIED
    assert result.reason_code == GatewayReason.POLICY_GATE_ERROR.value
    assert adapter.invocations == 0


def test_policy_decision_about_a_different_operation_is_rejected():
    """A gate that approved some other operation has not approved this one."""
    gateway = CapabilityGateway(AllowGate(operation="something_else"))
    adapter = RecordingToolAdapter(READ_TOOL)
    result = gateway.invoke_tool(tool_invocation(), adapter)
    assert result.outcome is InvocationOutcome.DENIED
    assert result.reason_code == GatewayReason.POLICY_GATE_ERROR.value
    assert adapter.invocations == 0


# ---------------------------------------------------------------------------
# side-effect and permission enforcement
# ---------------------------------------------------------------------------


def test_default_gateway_allows_only_read_only():
    assert DEFAULT_ALLOWED_SIDE_EFFECTS == frozenset({SideEffectClass.READ_ONLY})
    gateway = CapabilityGateway(AllowGate(operation="place_order"))
    adapter = RecordingToolAdapter(FINANCIAL_TOOL)
    result = gateway.invoke_tool(
        tool_invocation(
            FINANCIAL_TOOL, operation="place_order",
            granted_permissions=frozenset({"trading.execute"}),
        ),
        adapter,
    )
    assert result.outcome is InvocationOutcome.DENIED
    assert result.reason_code == GatewayReason.SIDE_EFFECT_NOT_ALLOWED.value
    assert adapter.invocations == 0


def test_elevated_tool_without_permission_is_denied_even_when_side_effect_allowed():
    gateway = CapabilityGateway(
        AllowGate(operation="place_order"),
        allowed_side_effects=frozenset({SideEffectClass.FINANCIAL}),
    )
    adapter = RecordingToolAdapter(FINANCIAL_TOOL)
    result = gateway.invoke_tool(
        tool_invocation(FINANCIAL_TOOL, operation="place_order"), adapter,
    )
    assert result.outcome is InvocationOutcome.DENIED
    assert result.reason_code == GatewayReason.POLICY_DENIED.value
    assert adapter.invocations == 0


def test_elevated_tool_requires_an_actor_identity():
    """Actor spoofing via an anonymous context is refused."""
    gateway = CapabilityGateway(
        AllowGate(operation="place_order"),
        allowed_side_effects=frozenset({SideEffectClass.FINANCIAL}),
    )
    adapter = RecordingToolAdapter(FINANCIAL_TOOL)
    anonymous = ToolInvocation(
        context=OperationContext(
            component="c", operation="place_order", actor_id="   ",
        ),
        descriptor=FINANCIAL_TOOL, operation="place_order",
        cost=CostMetadata(capability_class=CapabilityClass.FREE_TIER),
        granted_permissions=frozenset({"trading.execute"}),
    )
    result = gateway.invoke_tool(anonymous, adapter)
    assert result.outcome is InvocationOutcome.DENIED
    assert result.reason_code == GatewayReason.ACTOR_IDENTITY_REQUIRED.value
    assert adapter.invocations == 0


def test_explicitly_widened_gateway_permits_a_fully_authorized_elevated_tool():
    gateway = CapabilityGateway(
        AllowGate(operation="place_order"),
        allowed_side_effects=frozenset({SideEffectClass.FINANCIAL}),
    )
    adapter = RecordingToolAdapter(FINANCIAL_TOOL)
    result = gateway.invoke_tool(
        tool_invocation(
            FINANCIAL_TOOL, operation="place_order",
            granted_permissions=frozenset({"trading.execute"}),
        ),
        adapter,
    )
    assert result.succeeded
    assert adapter.invocations == 1


# ---------------------------------------------------------------------------
# paid-capability enforcement
# ---------------------------------------------------------------------------


def test_paid_model_is_denied_by_default_and_never_invoked():
    gateway = CapabilityGateway(AllowGate(operation="infer"))
    adapter = RecordingModelAdapter(PAID_MODEL)
    result = gateway.invoke_model(model_invocation(PAID_MODEL), adapter)
    assert result.outcome is InvocationOutcome.DENIED
    assert result.reason_code == GatewayReason.PAID_CAPABILITY_NOT_AUTHORIZED.value
    assert adapter.invocations == 0


def test_free_tier_with_overage_estimate_is_denied_when_paid_not_permitted():
    """A non-free amount cannot slip through under a free-sounding class."""
    gateway = CapabilityGateway(AllowGate(operation="infer"))
    descriptor = ModelProviderDescriptor(
        provider_id="freemium", model_id="m", capability_class=CapabilityClass.FREE_TIER,
    )
    adapter = RecordingModelAdapter(descriptor)
    result = gateway.invoke_model(
        model_invocation(
            descriptor,
            cost=CostMetadata(
                capability_class=CapabilityClass.FREE_TIER, estimated_cost=D("2.50"),
            ),
        ),
        adapter,
    )
    assert result.outcome is InvocationOutcome.DENIED
    assert result.reason_code == GatewayReason.PAID_CAPABILITY_NOT_AUTHORIZED.value
    assert adapter.invocations == 0


def test_paid_model_permitted_when_explicitly_authorized():
    gateway = CapabilityGateway(AllowGate(operation="infer"), permit_paid_capabilities=True)
    adapter = RecordingModelAdapter(PAID_MODEL)
    result = gateway.invoke_model(model_invocation(PAID_MODEL), adapter)
    assert result.succeeded
    assert adapter.invocations == 1


def test_local_model_is_free_and_allowed_by_default():
    gateway = CapabilityGateway(AllowGate(operation="infer"))
    adapter = RecordingModelAdapter(LOCAL_MODEL)
    result = gateway.invoke_model(model_invocation(LOCAL_MODEL), adapter)
    assert result.succeeded
    assert adapter.invocations == 1


# ---------------------------------------------------------------------------
# adapter substitution / identity attacks
# ---------------------------------------------------------------------------


def test_adapter_with_a_different_descriptor_is_refused_before_invocation():
    """The approved descriptor must be the one that actually runs."""
    gateway = CapabilityGateway(AllowGate())
    impostor = ToolDescriptor(
        tool_id="filesystem-read", side_effect=SideEffectClass.READ_ONLY,
        capability_class=CapabilityClass.FREE_TIER, requires_network=True,
    )
    adapter = RecordingToolAdapter(impostor)
    result = gateway.invoke_tool(tool_invocation(READ_TOOL), adapter)
    assert result.outcome is InvocationOutcome.DENIED
    assert result.reason_code == GatewayReason.ADAPTER_IDENTITY_MISMATCH.value
    assert adapter.invocations == 0


def test_adapter_whose_descriptor_property_raises_is_refused():
    class HostileAdapter:
        def __init__(self) -> None:
            self.invocations = 0

        @property
        def descriptor(self):
            raise RuntimeError("no descriptor for you")

        def invoke(self, invocation):
            self.invocations += 1
            return None

    gateway = CapabilityGateway(AllowGate())
    adapter = HostileAdapter()
    result = gateway.invoke_tool(tool_invocation(), adapter)
    assert result.outcome is InvocationOutcome.DENIED
    assert result.reason_code == GatewayReason.ADAPTER_IDENTITY_MISMATCH.value
    assert adapter.invocations == 0


def test_model_adapter_identity_mismatch_is_refused():
    gateway = CapabilityGateway(AllowGate(operation="infer"))
    other = ModelProviderDescriptor(
        provider_id="local-runtime", model_id="a-different-model",
        capability_class=CapabilityClass.LOCAL, requires_network=False,
    )
    adapter = RecordingModelAdapter(other)
    result = gateway.invoke_model(model_invocation(LOCAL_MODEL), adapter)
    assert result.outcome is InvocationOutcome.DENIED
    assert result.reason_code == GatewayReason.ADAPTER_IDENTITY_MISMATCH.value
    assert adapter.invocations == 0


# ---------------------------------------------------------------------------
# adapter failure containment
# ---------------------------------------------------------------------------


def test_adapter_exception_is_contained_as_a_fixed_reason_code():
    gateway = CapabilityGateway(AllowGate())
    adapter = RecordingToolAdapter(
        READ_TOOL, raises=RuntimeError("connection refused to 10.0.0.5:443"),
    )
    result = gateway.invoke_tool(tool_invocation(), adapter)
    assert result.outcome is InvocationOutcome.PROVIDER_ERROR
    assert result.reason_code == GatewayReason.ADAPTER_ERROR.value
    # Adapter text must not become audit evidence.
    assert "10.0.0.5" not in result.reason_code
    assert "connection refused" not in repr(result)


def test_adapter_returning_a_foreign_tool_id_is_rejected():
    gateway = CapabilityGateway(AllowGate())
    forged = ToolInvocationResult(
        invocation_id="whatever", tool_id="some-other-tool",
        outcome=InvocationOutcome.OK, reason_code="OK",
    )
    adapter = RecordingToolAdapter(READ_TOOL, result=forged)
    result = gateway.invoke_tool(tool_invocation(), adapter)
    assert result.outcome is InvocationOutcome.INVALID_RESULT
    assert result.reason_code == GatewayReason.ADAPTER_RESULT_INVALID.value


def test_adapter_returning_a_wrong_type_is_rejected():
    gateway = CapabilityGateway(AllowGate())
    adapter = RecordingToolAdapter(READ_TOOL, result="totally fine, trust me")
    result = gateway.invoke_tool(tool_invocation(), adapter)
    assert result.outcome is InvocationOutcome.INVALID_RESULT


def test_model_adapter_returning_a_foreign_provider_is_rejected():
    gateway = CapabilityGateway(AllowGate(operation="infer"))
    forged = ModelInvocationResult(
        invocation_id="x", provider_id="attacker", model_id="attacker-model",
        outcome=InvocationOutcome.OK, reason_code="OK",
    )
    adapter = RecordingModelAdapter(LOCAL_MODEL, result=forged)
    result = gateway.invoke_model(model_invocation(LOCAL_MODEL), adapter)
    assert result.outcome is InvocationOutcome.INVALID_RESULT


# ---------------------------------------------------------------------------
# duplicate invocation identity
# ---------------------------------------------------------------------------


def test_replayed_invocation_id_is_refused_within_the_process():
    gateway = CapabilityGateway(AllowGate())
    adapter = RecordingToolAdapter(READ_TOOL)
    invocation = tool_invocation()

    first = gateway.invoke_tool(invocation, adapter)
    second = gateway.invoke_tool(invocation, adapter)

    assert first.succeeded
    assert second.outcome is InvocationOutcome.DENIED
    assert second.reason_code == GatewayReason.DUPLICATE_INVOCATION.value
    assert adapter.invocations == 1


def test_distinct_invocations_are_not_treated_as_replays():
    gateway = CapabilityGateway(AllowGate())
    adapter = RecordingToolAdapter(READ_TOOL)
    assert gateway.invoke_tool(tool_invocation(), adapter).succeeded
    assert gateway.invoke_tool(tool_invocation(), adapter).succeeded
    assert adapter.invocations == 2


def test_denied_invocation_does_not_consume_its_identity():
    """A denial must not make a later legitimate retry look like a replay."""
    adapter = RecordingToolAdapter(READ_TOOL)
    invocation = tool_invocation()

    denied = CapabilityGateway(DenyGate()).invoke_tool(invocation, adapter)
    assert denied.outcome is InvocationOutcome.DENIED

    allowed = CapabilityGateway(AllowGate()).invoke_tool(invocation, adapter)
    assert allowed.succeeded
    assert adapter.invocations == 1


# ---------------------------------------------------------------------------
# type discipline
# ---------------------------------------------------------------------------


def test_gateway_rejects_a_foreign_invocation_type():
    gateway = CapabilityGateway(AllowGate())
    with pytest.raises(TypeError):
        gateway.invoke_tool("not an invocation", RecordingToolAdapter(READ_TOOL))
    with pytest.raises(TypeError):
        gateway.invoke_model("not an invocation", RecordingModelAdapter(LOCAL_MODEL))


def test_gateway_exposes_its_configured_posture():
    gateway = CapabilityGateway(AllowGate())
    assert gateway.allowed_side_effects == frozenset({SideEffectClass.READ_ONLY})
    assert gateway.permits_paid_capabilities is False


def test_gateway_rejects_an_unknown_side_effect_in_its_allow_list():
    """A typo in the allow-list must fail loudly, not silently allow nothing."""
    with pytest.raises(ValueError):
        CapabilityGateway(AllowGate(), allowed_side_effects=frozenset({"ANYTHING_GOES"}))


def test_descriptor_subclass_is_not_accepted_as_the_approved_descriptor():
    """A subclass could relax behaviour, so identity must not accept one."""

    class SneakyDescriptor(ToolDescriptor):
        pass

    sneaky = SneakyDescriptor(
        tool_id="filesystem-read", side_effect=SideEffectClass.READ_ONLY,
        capability_class=CapabilityClass.LOCAL,
    )
    gateway = CapabilityGateway(AllowGate())
    adapter = RecordingToolAdapter(sneaky)
    result = gateway.invoke_tool(tool_invocation(READ_TOOL), adapter)
    assert result.outcome is InvocationOutcome.DENIED
    assert result.reason_code == GatewayReason.ADAPTER_IDENTITY_MISMATCH.value
    assert adapter.invocations == 0


def test_replay_history_is_bounded():
    """A long-running gateway must not accumulate invocation ids forever."""

    class TinyHistoryGateway(CapabilityGateway):
        REPLAY_HISTORY_LIMIT = 3

    gateway = TinyHistoryGateway(AllowGate())
    adapter = RecordingToolAdapter(READ_TOOL)
    for _ in range(10):
        assert gateway.invoke_tool(tool_invocation(), adapter).succeeded
    assert len(gateway._seen_invocations) <= TinyHistoryGateway.REPLAY_HISTORY_LIMIT
    assert adapter.invocations == 10


def test_replay_guard_still_catches_a_recent_replay_when_bounded():
    class TinyHistoryGateway(CapabilityGateway):
        REPLAY_HISTORY_LIMIT = 3

    gateway = TinyHistoryGateway(AllowGate())
    adapter = RecordingToolAdapter(READ_TOOL)
    invocation = tool_invocation()
    assert gateway.invoke_tool(invocation, adapter).succeeded
    replayed = gateway.invoke_tool(invocation, adapter)
    assert replayed.reason_code == GatewayReason.DUPLICATE_INVOCATION.value


def test_gateway_metadata_never_carries_adapter_supplied_secrets():
    """An adapter returning secret-bearing metadata is still sanitized."""
    gateway = CapabilityGateway(AllowGate())
    invocation = tool_invocation()
    leaky = ToolInvocationResult(
        invocation_id=invocation.invocation_id, tool_id=READ_TOOL.tool_id,
        outcome=InvocationOutcome.OK, reason_code="OK",
        metadata={"api_key": "sk-adapter-supplied"},
    )
    adapter = RecordingToolAdapter(READ_TOOL, result=leaky)
    result = gateway.invoke_tool(invocation, adapter)
    assert result.succeeded
    assert result.metadata["api_key"] == "[REDACTED]"
    assert "sk-adapter-supplied" not in repr(result)
