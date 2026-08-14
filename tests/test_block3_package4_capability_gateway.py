"""Block 3 / Package 4: the capability gateway, executed.

Package 3 shipped `CapabilityGateway`, `ToolAdapter` and `PolicyGate` as
contracts with no implementation, so the governed invocation path had never
actually run. Package 4 adds exactly one concrete adapter
(`LocalCapabilityProbeAdapter`) and one concrete policy gate
(`UnconfiguredPolicyGate`, which denies everything) and binds them in the
composition root.

What this file proves
---------------------
1. The adapter is genuinely local and inert: no network, no credential, no
   cost, no evidence, no financial authority, deterministic output.
2. The gateway is a chokepoint, not a suggestion: every denial path stops
   before the adapter is touched, and a denial is observable as such.
3. The composed application cannot invoke anything, because the gate it is
   wired with denies unconditionally.

An `AllowingPolicyGate` appears here only as a test double, so the
post-approval behaviour of the gateway can be exercised at all. Nothing in
production constructs an approving gate.
"""

from __future__ import annotations

import ast
import inspect
from decimal import Decimal
from pathlib import Path

import pytest

from core.local_capability_adapter import (
    DESCRIPTOR_MISMATCH,
    NO_POLICY_CONFIGURED,
    PROBE_OK,
    PROBE_OPERATION,
    UNCONFIGURED_POLICY_ID,
    LocalCapabilityProbeAdapter,
    UnconfiguredPolicyGate,
)
from core.model_provider_contracts import (
    CapabilityClass,
    CostMetadata,
    InvocationOutcome,
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


REPOSITORY_ROOT = Path(__file__).resolve().parent.parent
ADAPTER_PATH = REPOSITORY_ROOT / "core/local_capability_adapter.py"


class AllowingPolicyGate:
    """Test double. Approves the operation it is asked about."""

    def __init__(self) -> None:
        self.calls: list[OperationContext] = []

    def evaluate(self, context: OperationContext) -> PolicyDecision:
        self.calls.append(context)
        return PolicyDecision(
            allowed=True, reason_code="TEST_ALLOW", policy_id="test",
            operation=context.operation, actor_id=context.actor_id,
        )


class RaisingPolicyGate:
    def evaluate(self, context: OperationContext) -> PolicyDecision:
        raise RuntimeError("policy backend unavailable")


class MalformedPolicyGate:
    def evaluate(self, context: OperationContext):
        return {"allowed": True}


class WrongOperationPolicyGate:
    def evaluate(self, context: OperationContext) -> PolicyDecision:
        return PolicyDecision(
            allowed=True, reason_code="TEST_ALLOW", policy_id="test",
            operation="a_different_operation", actor_id=context.actor_id,
        )


class CountingAdapter:
    """Records whether it was reached at all."""

    def __init__(self, descriptor: ToolDescriptor) -> None:
        self._descriptor = descriptor
        self.invocations = 0

    @property
    def descriptor(self) -> ToolDescriptor:
        return self._descriptor

    def invoke(self, invocation: ToolInvocation) -> ToolInvocationResult:
        self.invocations += 1
        return ToolInvocationResult(
            invocation_id=invocation.invocation_id,
            tool_id=self._descriptor.tool_id,
            outcome=InvocationOutcome.OK,
            reason_code="REACHED",
            cost=invocation.cost,
        )


def context(operation=PROBE_OPERATION, actor="operator"):
    return OperationContext(
        component="test", operation=operation, actor_id=actor,
    )


def probe_invocation(*, operation=PROBE_OPERATION, actor="operator", cost=None,
                     descriptor=None, metadata=None):
    return ToolInvocation(
        context=context(operation=operation, actor=actor),
        descriptor=descriptor or LocalCapabilityProbeAdapter.DESCRIPTOR,
        operation=operation,
        cost=cost or LocalCapabilityProbeAdapter.free_cost(),
        metadata=metadata or {},
    )


# =====================================================================
# The adapter is local and inert
# =====================================================================


def test_adapter_declares_local_read_only_and_no_network():
    descriptor = LocalCapabilityProbeAdapter.DESCRIPTOR

    assert descriptor.capability_class is CapabilityClass.LOCAL
    assert descriptor.side_effect is SideEffectClass.READ_ONLY
    assert descriptor.requires_network is False
    assert descriptor.required_permission is None
    assert descriptor.side_effect in DEFAULT_ALLOWED_SIDE_EFFECTS


def test_adapter_cost_is_free_by_class_and_by_amount():
    cost = LocalCapabilityProbeAdapter.free_cost()

    assert cost.is_free is True
    assert cost.estimated_cost == Decimal("0")
    assert cost.actual_cost in (None, Decimal("0"))
    assert cost.capability_class.incurs_monetary_cost is False

    # A LOCAL capability that tried to declare spend is rejected outright.
    with pytest.raises(ValueError):
        CostMetadata(
            capability_class=CapabilityClass.LOCAL, estimated_cost=Decimal("1"),
        )


def test_adapter_imports_nothing_that_can_reach_outside_the_process():
    tree = ast.parse(ADAPTER_PATH.read_text(encoding="utf-8"))
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module)
        elif isinstance(node, ast.Import):
            imported.update(alias.name for alias in node.names)

    banned = {
        "socket", "ssl", "http", "urllib", "requests", "httpx", "ftplib",
        "subprocess", "os", "pathlib", "shutil", "sqlite3", "smtplib",
        "openai", "anthropic", "google", "cohere", "mistralai", "ollama",
        "langchain", "boto3", "mcp",
    }
    assert not ({module.split(".")[0] for module in imported} & banned)


def test_adapter_produces_no_evidence_and_touches_no_fusion():
    text = ADAPTER_PATH.read_text(encoding="utf-8")
    tree = ast.parse(text)
    references = {
        node.module for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module
    } | {
        alias.name for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) for alias in node.names
    } | {
        node.id for node in ast.walk(tree) if isinstance(node, ast.Name)
    } | {
        node.attr for node in ast.walk(tree) if isinstance(node, ast.Attribute)
    }

    for forbidden in (
        "Evidence", "core.decision_intelligence", "model_response_to_evidence",
        "AgentFusion", "ConfidenceEngine", "WorldAnalysisEngine", "Decision",
        "AtlasApplication", "ExecutionManager", "PaperTrader", "RiskEngine",
        "place_order", "submit_order", "execution_mode",
    ):
        assert forbidden not in references, f"adapter references {forbidden}"


def test_adapter_has_no_credential_surface():
    text = ADAPTER_PATH.read_text(encoding="utf-8").lower()
    for token in ("api_key", "secret_provider", "password", "token=", "bearer"):
        assert token not in text


def test_adapter_output_is_deterministic_for_the_same_invocation_identity():
    adapter = LocalCapabilityProbeAdapter()
    invocation = probe_invocation()

    first = adapter.invoke(invocation)
    second = adapter.invoke(invocation)

    assert first.outcome is InvocationOutcome.OK
    assert first.reason_code == PROBE_OK
    assert first.output_reference == second.output_reference
    assert len(first.output_reference) == 64


def test_adapter_output_changes_with_the_invocation_identity():
    adapter = LocalCapabilityProbeAdapter()
    assert (
        adapter.invoke(probe_invocation()).output_reference
        != adapter.invoke(probe_invocation()).output_reference
    )


def test_adapter_refuses_an_invocation_addressed_to_another_tool():
    """Defence in depth: the gateway already refuses this, and so does the
    adapter, so bypassing the gateway still does not let a foreign
    descriptor drive this adapter."""

    foreign = ToolDescriptor(
        tool_id="someone_else",
        side_effect=SideEffectClass.READ_ONLY,
        capability_class=CapabilityClass.LOCAL,
        requires_network=False,
    )
    result = LocalCapabilityProbeAdapter().invoke(
        probe_invocation(descriptor=foreign)
    )

    assert result.outcome is InvocationOutcome.INVALID_RESULT
    assert result.reason_code == DESCRIPTOR_MISMATCH
    assert result.output_reference is None


def test_adapter_metadata_is_sanitized_and_frozen():
    result = LocalCapabilityProbeAdapter().invoke(
        probe_invocation(metadata={"api_key": "sk-live-should-not-survive"})
    )

    assert "sk-live-should-not-survive" not in repr(result)
    with pytest.raises(TypeError):
        result.metadata["injected"] = "value"


def test_invocation_metadata_is_sanitized_on_construction():
    invocation = probe_invocation(
        metadata={"password": "hunter2", "note": "fine"}
    )

    assert "hunter2" not in repr(invocation)
    with pytest.raises(TypeError):
        invocation.metadata["injected"] = "value"


# =====================================================================
# The gateway denies before the adapter is reached
# =====================================================================


def test_unconfigured_policy_gate_denies_every_operation():
    gate = UnconfiguredPolicyGate()

    for operation in (PROBE_OPERATION, "anything", "place_order"):
        decision = gate.evaluate(context(operation=operation))
        assert decision.allowed is False
        assert decision.reason_code == NO_POLICY_CONFIGURED
        assert decision.policy_id == UNCONFIGURED_POLICY_ID
        assert decision.operation == operation


def test_unconfigured_policy_gate_takes_no_configuration():
    """There is no constructor argument that could make it approve."""

    parameters = set(inspect.signature(UnconfiguredPolicyGate).parameters)
    assert parameters == set()


def test_denial_happens_before_the_adapter_is_invoked():
    adapter = CountingAdapter(LocalCapabilityProbeAdapter.DESCRIPTOR)
    gateway = CapabilityGateway(UnconfiguredPolicyGate())

    result = gateway.invoke_tool(probe_invocation(), adapter)

    assert result.outcome is InvocationOutcome.DENIED
    assert result.reason_code == GatewayReason.POLICY_DENIED.value
    assert adapter.invocations == 0


def test_a_policy_gate_that_raises_denies_rather_than_admits():
    adapter = CountingAdapter(LocalCapabilityProbeAdapter.DESCRIPTOR)
    result = CapabilityGateway(RaisingPolicyGate()).invoke_tool(
        probe_invocation(), adapter,
    )

    assert result.outcome is InvocationOutcome.DENIED
    assert result.reason_code == GatewayReason.POLICY_GATE_ERROR.value
    assert adapter.invocations == 0


def test_a_malformed_policy_response_denies():
    adapter = CountingAdapter(LocalCapabilityProbeAdapter.DESCRIPTOR)
    result = CapabilityGateway(MalformedPolicyGate()).invoke_tool(
        probe_invocation(), adapter,
    )

    assert result.outcome is InvocationOutcome.DENIED
    assert result.reason_code == GatewayReason.POLICY_GATE_ERROR.value
    assert adapter.invocations == 0


def test_a_policy_decision_about_another_operation_denies():
    adapter = CountingAdapter(LocalCapabilityProbeAdapter.DESCRIPTOR)
    result = CapabilityGateway(WrongOperationPolicyGate()).invoke_tool(
        probe_invocation(), adapter,
    )

    assert result.outcome is InvocationOutcome.DENIED
    assert result.reason_code == GatewayReason.POLICY_GATE_ERROR.value
    assert adapter.invocations == 0


def test_a_forged_descriptor_is_refused_before_invocation():
    """An adapter presenting a descriptor other than the approved one is
    refused, so a permissive adapter cannot be swapped in behind an
    invocation that was authorized for something else."""

    permissive = ToolDescriptor(
        tool_id="local_capability_probe",
        side_effect=SideEffectClass.FINANCIAL,
        capability_class=CapabilityClass.LOCAL,
        requires_network=False,
        required_permission="trade",
    )
    adapter = CountingAdapter(permissive)
    result = CapabilityGateway(AllowingPolicyGate()).invoke_tool(
        probe_invocation(), adapter,
    )

    assert result.outcome is InvocationOutcome.DENIED
    assert result.reason_code == GatewayReason.ADAPTER_IDENTITY_MISMATCH.value
    assert adapter.invocations == 0


def test_a_financial_side_effect_is_denied_by_the_default_gateway():
    descriptor = ToolDescriptor(
        tool_id="pretend_broker",
        side_effect=SideEffectClass.FINANCIAL,
        capability_class=CapabilityClass.LOCAL,
        requires_network=False,
        required_permission="trade",
    )
    adapter = CountingAdapter(descriptor)
    invocation = ToolInvocation(
        context=context(operation="trade"),
        descriptor=descriptor,
        operation="trade",
        cost=CostMetadata(capability_class=CapabilityClass.LOCAL),
        granted_permissions=frozenset({"trade"}),
    )

    result = CapabilityGateway(AllowingPolicyGate()).invoke_tool(invocation, adapter)

    assert result.outcome is InvocationOutcome.DENIED
    assert result.reason_code == GatewayReason.SIDE_EFFECT_NOT_ALLOWED.value
    assert adapter.invocations == 0


def test_a_non_read_only_tool_requires_an_actor_identity():
    descriptor = ToolDescriptor(
        tool_id="local_writer",
        side_effect=SideEffectClass.LOCAL_WRITE,
        capability_class=CapabilityClass.LOCAL,
        requires_network=False,
        required_permission="write_local",
    )
    adapter = CountingAdapter(descriptor)
    invocation = ToolInvocation(
        context=OperationContext(
            component="test", operation="write", actor_id=None,
        ),
        descriptor=descriptor,
        operation="write",
        cost=CostMetadata(capability_class=CapabilityClass.LOCAL),
        granted_permissions=frozenset({"write_local"}),
    )

    gateway = CapabilityGateway(
        AllowingPolicyGate(),
        allowed_side_effects=frozenset(
            {SideEffectClass.READ_ONLY, SideEffectClass.LOCAL_WRITE}
        ),
    )
    result = gateway.invoke_tool(invocation, adapter)

    assert result.outcome is InvocationOutcome.DENIED
    assert result.reason_code == GatewayReason.ACTOR_IDENTITY_REQUIRED.value
    assert adapter.invocations == 0


def test_a_paid_capability_is_denied_by_default():
    descriptor = ToolDescriptor(
        tool_id="paid_research",
        side_effect=SideEffectClass.READ_ONLY,
        capability_class=CapabilityClass.PAID,
        requires_network=True,
    )
    adapter = CountingAdapter(descriptor)
    invocation = ToolInvocation(
        context=context(operation="research"),
        descriptor=descriptor,
        operation="research",
        cost=CostMetadata(
            capability_class=CapabilityClass.PAID, estimated_cost=Decimal("0.01"),
        ),
    )

    result = CapabilityGateway(AllowingPolicyGate()).invoke_tool(invocation, adapter)

    assert result.outcome is InvocationOutcome.DENIED
    assert result.reason_code == GatewayReason.PAID_CAPABILITY_NOT_AUTHORIZED.value
    assert adapter.invocations == 0


# =====================================================================
# Post-approval behaviour (requires the allowing test double)
# =====================================================================


def test_an_approved_probe_reaches_the_adapter_and_returns_its_digest():
    gate = AllowingPolicyGate()
    result = CapabilityGateway(gate).invoke_tool(
        probe_invocation(), LocalCapabilityProbeAdapter(),
    )

    assert result.outcome is InvocationOutcome.OK
    assert result.reason_code == PROBE_OK
    assert result.tool_id == LocalCapabilityProbeAdapter.TOOL_ID
    assert result.cost.is_free is True
    assert len(gate.calls) == 1


def test_a_duplicate_operation_id_is_refused_as_a_replay():
    gateway = CapabilityGateway(AllowingPolicyGate())
    adapter = LocalCapabilityProbeAdapter()
    invocation = probe_invocation()

    first = gateway.invoke_tool(invocation, adapter)
    second = gateway.invoke_tool(invocation, adapter)

    assert first.outcome is InvocationOutcome.OK
    assert second.outcome is InvocationOutcome.DENIED
    assert second.reason_code == GatewayReason.DUPLICATE_INVOCATION.value


def test_an_adapter_that_raises_after_approval_yields_a_provider_error():
    class ExplodingAdapter:
        descriptor = LocalCapabilityProbeAdapter.DESCRIPTOR

        def invoke(self, invocation):
            raise RuntimeError("secret-bearing failure text sk-live-abc")

    result = CapabilityGateway(AllowingPolicyGate()).invoke_tool(
        probe_invocation(), ExplodingAdapter(),
    )

    assert result.outcome is InvocationOutcome.PROVIDER_ERROR
    assert result.reason_code == GatewayReason.ADAPTER_ERROR.value
    assert "sk-live-abc" not in repr(result)


def test_a_malformed_adapter_result_is_rejected():
    class LyingAdapter:
        descriptor = LocalCapabilityProbeAdapter.DESCRIPTOR

        def invoke(self, invocation):
            return "not a result"

    result = CapabilityGateway(AllowingPolicyGate()).invoke_tool(
        probe_invocation(), LyingAdapter(),
    )

    assert result.outcome is InvocationOutcome.INVALID_RESULT
    assert result.reason_code == GatewayReason.ADAPTER_RESULT_INVALID.value


def test_a_result_claiming_another_tool_is_rejected():
    class ImpersonatingAdapter:
        descriptor = LocalCapabilityProbeAdapter.DESCRIPTOR

        def invoke(self, invocation):
            return ToolInvocationResult(
                invocation_id=invocation.invocation_id,
                tool_id="some_other_tool",
                outcome=InvocationOutcome.OK,
                reason_code="OK",
            )

    result = CapabilityGateway(AllowingPolicyGate()).invoke_tool(
        probe_invocation(), ImpersonatingAdapter(),
    )

    assert result.outcome is InvocationOutcome.INVALID_RESULT
    assert result.reason_code == GatewayReason.ADAPTER_RESULT_INVALID.value


# =====================================================================
# OPAQUE MACHINE IDENTITY (finding 3 regression suite)
# =====================================================================
#
# Defect: `ToolInvocationResult`/`ModelInvocationResult` ran `invocation_id`
# through `sanitized_identifier`, even though that id is a copy of
# `OperationContext.operation_id`, which `operational_contracts` documents
# as "internally generated UUID identity ... left untouched" (and which
# `OperationResult.trace_id` also exempts). The card-number detector matches
# hyphen-separated 13-19 digit runs passing a Luhn check, and a uuid4's
# middle groups form such a run in roughly 1 value in 450 - so a correct
# adapter's correct result was refused as ADAPTER_RESULT_INVALID at that
# rate, and audit records carried an id that no longer joined to anything.
#
# Fix: `machine_identifier` validates structurally and returns the value
# unchanged. Every descriptive identifier keeps `sanitized_identifier`.
#
# These tests are deterministic. The values below are real uuid4s captured
# from the sampling run that found the defect, so the regression cannot
# depend on generating a mangling uuid by chance.


#: Real uuid4 values that `sanitize_sensitive_text` rewrites. Measured rate:
#: 447 in 200,000 uuid4s (~0.22%).
MANGLED_UUIDS = (
    "991f566c-fe7f-4064-9927-46430d7b3ece",
    "c316f45b-104b-4308-8090-29906c9f9444",
    "11c2ea39-a4cc-4702-9196-53847d55be1f",
)


def test_the_mangling_inputs_are_still_genuinely_mangling():
    """Guards the guards: if the sanitizer's rules ever change so these
    values pass through untouched, the tests below would silently stop
    testing anything and would need new inputs."""
    from core.model_provider_contracts import sanitized_identifier

    for value in MANGLED_UUIDS:
        assert sanitized_identifier(value, "x") != value
        assert "[REDACTED]" in sanitized_identifier(value, "x")


# --- A: a formerly mangled identity is preserved exactly -------------


@pytest.mark.parametrize("operation_id", MANGLED_UUIDS)
def test_a_machine_identifier_preserves_a_formerly_mangled_uuid(operation_id):
    from core.model_provider_contracts import machine_identifier

    assert machine_identifier(operation_id, "invocation_id") == operation_id


@pytest.mark.parametrize("operation_id", MANGLED_UUIDS)
def test_a_result_construction_preserves_a_formerly_mangled_uuid(operation_id):
    result = ToolInvocationResult(
        invocation_id=operation_id,
        tool_id=LocalCapabilityProbeAdapter.TOOL_ID,
        outcome=InvocationOutcome.OK,
        reason_code=PROBE_OK,
    )
    assert result.invocation_id == operation_id


@pytest.mark.parametrize("operation_id", MANGLED_UUIDS)
def test_a_model_result_construction_preserves_it_too(operation_id):
    """The same defect existed on the model side and is fixed with it."""
    from core.model_provider_contracts import ModelInvocationResult

    result = ModelInvocationResult(
        invocation_id=operation_id,
        provider_id="local",
        model_id="deterministic",
        outcome=InvocationOutcome.OK,
        reason_code="OK",
    )
    assert result.invocation_id == operation_id


# --- B, C: identity round-trips through the gateway ------------------


@pytest.mark.parametrize("operation_id", MANGLED_UUIDS)
def test_b_and_c_gateway_accepts_a_correct_result_carrying_that_identity(
    operation_id,
):
    invocation = ToolInvocation(
        context=OperationContext(
            component="test", operation=PROBE_OPERATION,
            operation_id=operation_id, actor_id="operator",
        ),
        descriptor=LocalCapabilityProbeAdapter.DESCRIPTOR,
        operation=PROBE_OPERATION,
        cost=LocalCapabilityProbeAdapter.free_cost(),
    )
    assert invocation.invocation_id == operation_id

    result = CapabilityGateway(AllowingPolicyGate()).invoke_tool(
        invocation, LocalCapabilityProbeAdapter(),
    )

    assert result.outcome is InvocationOutcome.OK
    assert result.reason_code == PROBE_OK
    assert result.invocation_id == invocation.invocation_id == operation_id


@pytest.mark.parametrize("operation_id", MANGLED_UUIDS)
def test_b_a_denial_result_also_keeps_the_audit_join(operation_id):
    """Denials are the path the composed application actually takes, so a
    denial record that cannot be joined to its operation would be the
    common case, not the rare one."""
    invocation = ToolInvocation(
        context=OperationContext(
            component="test", operation=PROBE_OPERATION,
            operation_id=operation_id, actor_id="operator",
        ),
        descriptor=LocalCapabilityProbeAdapter.DESCRIPTOR,
        operation=PROBE_OPERATION,
        cost=LocalCapabilityProbeAdapter.free_cost(),
    )
    result = CapabilityGateway(UnconfiguredPolicyGate()).invoke_tool(
        invocation, LocalCapabilityProbeAdapter(),
    )

    assert result.outcome is InvocationOutcome.DENIED
    assert result.invocation_id == operation_id


# --- D: replay detection still keys on the correct identity ----------


@pytest.mark.parametrize("operation_id", MANGLED_UUIDS)
def test_d_replay_detection_uses_the_preserved_identity(operation_id):
    gateway = CapabilityGateway(AllowingPolicyGate())
    adapter = LocalCapabilityProbeAdapter()

    def invocation():
        return ToolInvocation(
            context=OperationContext(
                component="test", operation=PROBE_OPERATION,
                operation_id=operation_id, actor_id="operator",
            ),
            descriptor=LocalCapabilityProbeAdapter.DESCRIPTOR,
            operation=PROBE_OPERATION,
            cost=LocalCapabilityProbeAdapter.free_cost(),
        )

    first = gateway.invoke_tool(invocation(), adapter)
    second = gateway.invoke_tool(invocation(), adapter)

    assert first.outcome is InvocationOutcome.OK
    assert second.reason_code == GatewayReason.DUPLICATE_INVOCATION.value
    assert operation_id in gateway._seen_invocations


def test_d_distinct_identities_are_not_conflated_by_the_guard():
    """The redaction collapsed distinct ids toward a shared shape; two
    different mangling uuids must remain two different invocations."""
    gateway = CapabilityGateway(AllowingPolicyGate())
    adapter = LocalCapabilityProbeAdapter()

    for operation_id in MANGLED_UUIDS:
        result = gateway.invoke_tool(
            ToolInvocation(
                context=OperationContext(
                    component="test", operation=PROBE_OPERATION,
                    operation_id=operation_id, actor_id="operator",
                ),
                descriptor=LocalCapabilityProbeAdapter.DESCRIPTOR,
                operation=PROBE_OPERATION,
                cost=LocalCapabilityProbeAdapter.free_cost(),
            ),
            adapter,
        )
        assert result.outcome is InvocationOutcome.OK

    assert set(MANGLED_UUIDS) <= set(gateway._seen_invocations)


# --- E, F: malformed identity fails closed ---------------------------


@pytest.mark.parametrize(
    "bad",
    ["", "   ", " padded ", "padded ", "a\nb", "a\rb", "a\tb", "a\x00b",
     "x" * 201, None, 123, 4.5, b"bytes", True],
)
def test_e_and_f_a_malformed_identity_is_rejected_not_repaired(bad):
    from core.model_provider_contracts import machine_identifier

    with pytest.raises(ValueError):
        machine_identifier(bad, "invocation_id")


@pytest.mark.parametrize("bad", ["", " padded ", "a\nb", "x" * 201, None, 123])
def test_e_a_result_cannot_be_constructed_with_a_malformed_identity(bad):
    with pytest.raises(ValueError):
        ToolInvocationResult(
            invocation_id=bad,
            tool_id=LocalCapabilityProbeAdapter.TOOL_ID,
            outcome=InvocationOutcome.OK,
            reason_code=PROBE_OK,
        )


def test_e_the_length_and_control_character_rules_match_the_sibling_function():
    """The two identifier functions differ in exactly one respect - one
    rewrites what it accepts and one does not. Their structural rules are
    shared constants so they cannot drift apart."""
    from core.model_provider_contracts import (
        FORBIDDEN_IDENTIFIER_CHARACTERS,
        MAX_IDENTIFIER_LENGTH,
        machine_identifier,
        sanitized_identifier,
    )

    assert MAX_IDENTIFIER_LENGTH == 200
    assert FORBIDDEN_IDENTIFIER_CHARACTERS == "\r\n\t\x00"

    boundary = "a" * MAX_IDENTIFIER_LENGTH
    assert machine_identifier(boundary, "x") == boundary
    assert sanitized_identifier(boundary, "x") == boundary
    for function in (machine_identifier, sanitized_identifier):
        with pytest.raises(ValueError):
            function(boundary + "a", "x")
        with pytest.raises(ValueError):
            function("", "x")


# --- G, H, I: the secret boundary is untouched -----------------------


def test_g_metadata_secrets_are_still_redacted():
    result = ToolInvocationResult(
        invocation_id=MANGLED_UUIDS[0],
        tool_id=LocalCapabilityProbeAdapter.TOOL_ID,
        outcome=InvocationOutcome.OK,
        reason_code=PROBE_OK,
        metadata={"api_key": "sk-live-must-not-survive", "card": "4111111111111111"},
    )

    rendered = repr(result)
    assert "sk-live-must-not-survive" not in rendered
    assert "4111111111111111" not in rendered


def test_h_descriptive_identifiers_keep_their_sanitization():
    """Only invocation_id changed. Every id a provider or operator chose
    the text of must still be redactable."""
    from core.model_provider_contracts import ModelInvocationResult

    leaky = "4111111111111111"

    result = ModelInvocationResult(
        invocation_id=MANGLED_UUIDS[0],
        provider_id=leaky,
        model_id=leaky,
        outcome=InvocationOutcome.OK,
        reason_code=leaky,
        output_reference=leaky,
    )

    assert result.invocation_id == MANGLED_UUIDS[0]
    for field in (result.provider_id, result.model_id,
                  result.reason_code, result.output_reference):
        assert field != leaky
        assert "[REDACTED]" in field


def test_h_tool_side_descriptive_identifiers_keep_their_sanitization():
    leaky = "4111111111111111"

    result = ToolInvocationResult(
        invocation_id=MANGLED_UUIDS[1],
        tool_id=leaky,
        outcome=InvocationOutcome.OK,
        reason_code=leaky,
        output_reference=leaky,
    )

    assert result.invocation_id == MANGLED_UUIDS[1]
    for field in (result.tool_id, result.reason_code, result.output_reference):
        assert "[REDACTED]" in field


def test_i_a_secret_shaped_identity_is_not_a_new_leak_path():
    """The identity field now preserves what it is given, so the honest
    question is whether that opens a leak. It does not add one: a secret
    placed in operation_id was already flowing unredacted through
    OperationContext and OperationResult.trace_id, which have always
    exempted machine identity. The mitigation is unchanged and is that
    Atlas mints these values itself."""
    from core.operational_contracts import OperationResult

    secret = "sk-live-abcdefghijklmnop"

    assert OperationContext(
        component="c", operation="o", trace_id=secret, operation_id=secret,
    ).operation_id == secret
    assert OperationResult(
        operation="o", status="OK", component="c", trace_id=secret,
    ).trace_id == secret
    assert ToolInvocationResult(
        invocation_id=secret,
        tool_id=LocalCapabilityProbeAdapter.TOOL_ID,
        outcome=InvocationOutcome.OK,
        reason_code=PROBE_OK,
    ).invocation_id == secret


# --- J, K: surrounding contracts unchanged ---------------------------


def test_j_and_k_operation_context_semantics_are_unchanged():
    """No part of the fix touched OperationContext: trace_id and
    operation_id are still generated, still caller-overridable, still
    exempt from sanitization, and every descriptive field is still
    sanitized."""
    import uuid

    from core.operational_contracts import OperationContext as OC

    generated = OC(component="c", operation="o")
    assert uuid.UUID(generated.trace_id)
    assert uuid.UUID(generated.operation_id)

    supplied = OC(
        component="c", operation="o",
        trace_id=MANGLED_UUIDS[0], operation_id=MANGLED_UUIDS[1],
        actor_id="4111111111111111",
    )
    assert supplied.trace_id == MANGLED_UUIDS[0]
    assert supplied.operation_id == MANGLED_UUIDS[1]
    assert "[REDACTED]" in supplied.actor_id


def test_k_only_invocation_id_moved_to_the_preserving_validator():
    """Structural: exactly two call sites use machine_identifier, and both
    are the invocation_id field."""
    for relative_path in ("core/model_provider_contracts.py",
                          "core/tool_gateway_contracts.py"):
        text = (REPOSITORY_ROOT / relative_path).read_text(encoding="utf-8")
        uses = [
            line.strip() for line in text.splitlines()
            if "machine_identifier(" in line and "def " not in line
        ]
        applications = [line for line in uses if "self.invocation_id" in line]
        assert len(applications) == 1, f"{relative_path}: {uses}"


# --- L: no random identity test remains ------------------------------


def test_l_no_identity_assertion_depends_on_a_minted_uuid():
    """Every identity assertion above pins its input. Minting one and
    asserting on its treatment is what made the historical gateway test
    fail ~1 run in 50.

    AST-based rather than a text scan, because a text scan of this file
    would match the very strings it is looking for.
    """
    tree = ast.parse(
        (REPOSITORY_ROOT / "tests/test_block3_package4_capability_gateway.py")
        .read_text(encoding="utf-8")
    )
    minted = [
        node for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and (
            (isinstance(node.func, ast.Attribute) and node.func.attr == "uuid4")
            or (isinstance(node.func, ast.Name) and node.func.id == "uuid4")
        )
    ]
    assert minted == []

    # And the pinned inputs are exactly the ones the identity tests use.
    assert len(MANGLED_UUIDS) == 3
    assert len(set(MANGLED_UUIDS)) == 3


# =====================================================================
# Composition root
# =====================================================================


def test_the_composed_application_gateway_can_never_reach_an_adapter(tmp_path):
    """End to end on the real composition root, against an isolated state
    directory so no durable Atlas state is touched."""

    from core.application import AtlasApplication

    application = AtlasApplication(state_directory=tmp_path)

    assert isinstance(application.capability_gateway, CapabilityGateway)
    assert isinstance(application.capability_policy_gate, UnconfiguredPolicyGate)
    assert isinstance(
        application.capability_probe_adapter, LocalCapabilityProbeAdapter
    )

    adapter = CountingAdapter(LocalCapabilityProbeAdapter.DESCRIPTOR)
    result = application.capability_gateway.invoke_tool(probe_invocation(), adapter)

    assert result.outcome is InvocationOutcome.DENIED
    assert result.reason_code == GatewayReason.POLICY_DENIED.value
    assert adapter.invocations == 0


def test_the_composed_gateway_permits_nothing_beyond_read_only(tmp_path):
    from core.application import AtlasApplication

    application = AtlasApplication(state_directory=tmp_path)

    assert application.capability_gateway.allowed_side_effects == (
        frozenset({SideEffectClass.READ_ONLY})
    )
    assert application.capability_gateway.permits_paid_capabilities is False


def test_the_capability_services_have_no_lifecycle_role(tmp_path):
    """Registered and injectable, but not started, stopped, or scheduled -
    so wiring them adds no runtime behaviour at all."""

    from core.application import AtlasApplication

    source = inspect.getsource(AtlasApplication.start)
    for name in ("capability_gateway", "capability_probe_adapter",
                 "capability_policy_gate"):
        assert name not in source
    assert "capability" not in inspect.getsource(AtlasApplication.stop)

    application = AtlasApplication(state_directory=tmp_path)
    for service in (application.capability_gateway,
                    application.capability_probe_adapter):
        assert not hasattr(service, "start")
        assert not hasattr(service, "stop")


def test_the_adapter_is_retrievable_from_the_service_container(tmp_path):
    from core.application import AtlasApplication

    application = AtlasApplication(state_directory=tmp_path)
    resolved = application.container.get(LocalCapabilityProbeAdapter)

    assert resolved is application.capability_probe_adapter
