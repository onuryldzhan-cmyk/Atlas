"""Tool invocation contracts and the single governed invocation chokepoint.

A future Atlas will reach outside itself in several ways: a GitHub tool, a
web research tool, a filesystem tool, a market-data adapter, eventually an
exchange adapter. The point of this module is that none of them get their
own private path out. They all describe themselves with the same descriptor,
declare the same side-effect and cost vocabulary, and are invoked through the
same `CapabilityGateway`, which decides *before* the adapter is touched.

MCP
---
No MCP runtime, dependency, or framework is introduced here, and Atlas core
must not depend on one. `ToolAdapter` is deliberately shaped so that an MCP
client can later be written as one more adapter behind this gateway,
alongside a local filesystem adapter or an HTTP research adapter. MCP becomes
an implementation detail of a single adapter, never a core dependency.

What this module is not
-----------------------
It is not a governance engine. `CapabilityGateway` enforces the mechanical
preconditions it can prove (declared side effect, declared cost class,
adapter identity, replay within the process) and delegates the actual
authorization question to the existing `PolicyGate` seam. No concrete policy,
RBAC store, agent runtime, or treasury is implemented here, and no adapter
exists yet.

Declaration-based classification, honestly stated
-------------------------------------------------
Side-effect class is *declared* by the tool descriptor. This module can
enforce that a declaration is internally consistent and that a dangerous
declaration is denied by default; it cannot detect a tool that lies about
itself. A tool that performs financial writes while declaring READ_ONLY
would pass here. The mitigations are that the default gateway allows only
READ_ONLY, that widening requires an explicit allow-list at construction,
and that descriptors are reviewable code rather than runtime input.
"""

from __future__ import annotations

import threading
from collections import OrderedDict
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Mapping, Protocol

from core.model_provider_contracts import (
    CapabilityClass,
    CostMetadata,
    InvocationOutcome,
    ModelInvocation,
    ModelInvocationResult,
    ModelProviderAdapter,
    ModelProviderDescriptor,
    machine_digest,
    machine_identifier,
    sanitized_identifier,
)
from core.operational_contracts import (
    OperationContext,
    PolicyDecision,
    PolicyGate,
    sanitized_metadata,
)


class SideEffectClass(str, Enum):
    """What invoking a tool can change, in increasing order of authority."""

    READ_ONLY = "READ_ONLY"
    LOCAL_WRITE = "LOCAL_WRITE"
    EXTERNAL_WRITE = "EXTERNAL_WRITE"
    FINANCIAL = "FINANCIAL"
    SECURITY_SENSITIVE = "SECURITY_SENSITIVE"

    @property
    def requires_explicit_permission(self) -> bool:
        return self is not SideEffectClass.READ_ONLY


# Denied unless a gateway is deliberately constructed to allow them. Kept as
# an explicit constant so that widening the default is a visible diff.
DEFAULT_ALLOWED_SIDE_EFFECTS: frozenset[SideEffectClass] = frozenset(
    {SideEffectClass.READ_ONLY}
)


class GatewayReason(str, Enum):
    """Fixed reason codes emitted by the gateway.

    Provider and tool exception text never becomes a reason code; it would
    put untrusted third-party strings into audit evidence.
    """

    APPROVED = "APPROVED"
    SIDE_EFFECT_NOT_ALLOWED = "SIDE_EFFECT_NOT_ALLOWED"
    PAID_CAPABILITY_NOT_AUTHORIZED = "PAID_CAPABILITY_NOT_AUTHORIZED"
    ADAPTER_IDENTITY_MISMATCH = "ADAPTER_IDENTITY_MISMATCH"
    ACTOR_IDENTITY_REQUIRED = "ACTOR_IDENTITY_REQUIRED"
    DUPLICATE_INVOCATION = "DUPLICATE_INVOCATION"
    POLICY_DENIED = "POLICY_DENIED"
    POLICY_GATE_ERROR = "POLICY_GATE_ERROR"
    ADAPTER_ERROR = "ADAPTER_ERROR"
    ADAPTER_RESULT_INVALID = "ADAPTER_RESULT_INVALID"


@dataclass(frozen=True, slots=True)
class ToolDescriptor:
    """Identity, authority, and cost class of one tool."""

    tool_id: str
    side_effect: SideEffectClass
    capability_class: CapabilityClass
    requires_network: bool = False
    required_permission: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "tool_id", sanitized_identifier(self.tool_id, "tool_id"))
        object.__setattr__(self, "side_effect", SideEffectClass(self.side_effect))
        object.__setattr__(
            self, "capability_class", CapabilityClass(self.capability_class),
        )
        if not isinstance(self.requires_network, bool):
            raise ValueError("requires_network must be a bool")
        if self.required_permission is not None:
            object.__setattr__(
                self, "required_permission",
                sanitized_identifier(self.required_permission, "required_permission"),
            )

        if self.capability_class is CapabilityClass.LOCAL and self.requires_network:
            raise ValueError("LOCAL capability must not require network access")
        # A tool that can move money, write externally, or touch security
        # state must name the permission it needs; "no permission required"
        # is only coherent for a read.
        if self.side_effect.requires_explicit_permission and not self.required_permission:
            raise ValueError(
                f"{self.side_effect.value} tool must declare a required_permission"
            )
        if not self.side_effect.requires_explicit_permission and self.required_permission:
            raise ValueError("READ_ONLY tool must not declare a required_permission")


@dataclass(frozen=True, slots=True)
class ToolInvocation:
    """One governed request to invoke a tool."""

    context: OperationContext
    descriptor: ToolDescriptor
    operation: str
    cost: CostMetadata
    granted_permissions: frozenset[str] = frozenset()
    timeout_ms: int = 30_000
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not isinstance(self.context, OperationContext):
            raise ValueError("context must be an OperationContext")
        if not isinstance(self.descriptor, ToolDescriptor):
            raise ValueError("descriptor must be a ToolDescriptor")
        if not isinstance(self.cost, CostMetadata):
            raise ValueError("cost must be CostMetadata")
        object.__setattr__(self, "operation", sanitized_identifier(self.operation, "operation"))
        object.__setattr__(
            self, "granted_permissions",
            frozenset(
                sanitized_identifier(item, "granted_permission")
                for item in self.granted_permissions
            ),
        )
        if (
            not isinstance(self.timeout_ms, int)
            or isinstance(self.timeout_ms, bool)
            or self.timeout_ms <= 0
        ):
            raise ValueError("timeout_ms must be a positive integer")
        if self.cost.capability_class is not self.descriptor.capability_class:
            raise ValueError("cost capability_class must match the descriptor")
        object.__setattr__(self, "metadata", sanitized_metadata(self.metadata))

    @property
    def invocation_id(self) -> str:
        return self.context.operation_id

    @property
    def has_required_permission(self) -> bool:
        required = self.descriptor.required_permission
        return required is None or required in self.granted_permissions


@dataclass(frozen=True, slots=True)
class ToolInvocationResult:
    """Outcome of one governed tool invocation.

    An adapter can refer to its output in two ways, kept as separate fields
    because they have opposite trust properties:

    - `output_reference` is *descriptive* - a path, a URI, a resource id,
      whatever the adapter chose to call the output. Adapters are untrusted
      by design here, so this text is sanitized like any other adapter string.
    - `output_digest` is a *cryptographic digest* of the output: machine
      minted, meaningful only by being exactly itself, and therefore
      structurally validated and preserved rather than rewritten.

    An adapter may set either, both, or neither.
    """

    invocation_id: str
    tool_id: str
    outcome: InvocationOutcome
    reason_code: str
    latency_ms: float = 0.0
    cost: CostMetadata | None = None
    output_reference: str | None = None
    output_digest: str | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "invocation_id", machine_identifier(self.invocation_id, "invocation_id"),
        )
        object.__setattr__(self, "tool_id", sanitized_identifier(self.tool_id, "tool_id"))
        object.__setattr__(self, "outcome", InvocationOutcome(self.outcome))
        object.__setattr__(
            self, "reason_code", sanitized_identifier(self.reason_code, "reason_code"),
        )
        if isinstance(self.latency_ms, bool) or not isinstance(self.latency_ms, (int, float)):
            raise ValueError("latency_ms must be a number")
        if self.latency_ms < 0 or self.latency_ms != self.latency_ms:  # NaN-safe
            raise ValueError("latency_ms must be a non-negative number")
        object.__setattr__(self, "latency_ms", float(self.latency_ms))
        if self.cost is not None and not isinstance(self.cost, CostMetadata):
            raise ValueError("cost must be CostMetadata")
        if self.output_reference is not None:
            object.__setattr__(
                self, "output_reference",
                sanitized_identifier(self.output_reference, "output_reference"),
            )
        if self.output_digest is not None:
            object.__setattr__(
                self, "output_digest",
                machine_digest(self.output_digest, "output_digest"),
            )
        object.__setattr__(self, "metadata", sanitized_metadata(self.metadata))

    @property
    def succeeded(self) -> bool:
        return self.outcome is InvocationOutcome.OK


class ToolAdapter(Protocol):
    """Contract every concrete tool adapter implements.

    A future MCP client, filesystem tool, or HTTP research tool is one of
    these and nothing more. Adapters belong in the infrastructure layer,
    behind the gateway.
    """

    @property
    def descriptor(self) -> ToolDescriptor:
        ...

    def invoke(self, invocation: ToolInvocation) -> ToolInvocationResult:
        ...


class CapabilityGateway:
    """The single point at which an external capability may be invoked.

    Enforcement order matters and is deliberate: everything cheap and
    provable is checked before the adapter is consulted, and the adapter is
    never reached at all unless every check passed. A denial therefore
    guarantees no side effect occurred, which is the property that makes this
    worth having.

    The gateway is intentionally deny-biased:

    - only READ_ONLY side effects are permitted unless the caller widens
      `allowed_side_effects` explicitly,
    - a paid capability is refused unless `permit_paid_capabilities` is set,
    - a `PolicyGate` that raises denies rather than admits,
    - an adapter whose descriptor disagrees with the invocation is refused
      before invocation, so a permissive descriptor cannot be swapped in
      behind an approved one.
    """

    #: How many recent invocation ids the replay guard remembers. Bounded so
    #: a long-running process cannot grow this set without limit; an id older
    #: than this many invocations is forgotten and would be accepted again.
    REPLAY_HISTORY_LIMIT = 10_000

    def __init__(
        self,
        policy_gate: PolicyGate,
        *,
        allowed_side_effects: frozenset[SideEffectClass] = DEFAULT_ALLOWED_SIDE_EFFECTS,
        permit_paid_capabilities: bool = False,
    ) -> None:
        self._policy_gate = policy_gate
        self._allowed_side_effects = frozenset(
            SideEffectClass(item) for item in allowed_side_effects
        )
        self._permit_paid_capabilities = bool(permit_paid_capabilities)
        self._lock = threading.RLock()
        self._seen_invocations: OrderedDict[str, None] = OrderedDict()

    @property
    def allowed_side_effects(self) -> frozenset[SideEffectClass]:
        return self._allowed_side_effects

    @property
    def permits_paid_capabilities(self) -> bool:
        return self._permit_paid_capabilities

    # -- shared pre-invocation checks ------------------------------------

    def _reserve_invocation(self, invocation_id: str) -> bool:
        """Claim an invocation id, refusing a replay within this process.

        This is a process-local, bounded guard, not durable idempotency. It
        stops an invocation record being replayed inside one run; it does not
        survive a restart, it forgets ids beyond REPLAY_HISTORY_LIMIT, and it
        is not a substitute for the durable idempotency the execution path
        already owns.

        It is also only as strong as invocation-id uniqueness, which comes
        from OperationContext.operation_id and is therefore the caller's
        responsibility: two invocations that deliberately share one context
        are the same operation and are treated as such.
        """
        with self._lock:
            if invocation_id in self._seen_invocations:
                return False
            self._seen_invocations[invocation_id] = None
            while len(self._seen_invocations) > self.REPLAY_HISTORY_LIMIT:
                self._seen_invocations.popitem(last=False)
            return True

    def _pre_invocation_denial(
        self,
        *,
        context: OperationContext,
        side_effect: SideEffectClass,
        capability_class: CapabilityClass,
        cost: CostMetadata,
        identity_matches: bool,
        has_required_permission: bool,
        operation: str,
    ) -> GatewayReason | None:
        """Return the reason to deny, or None if the adapter may be reached."""
        if not identity_matches:
            return GatewayReason.ADAPTER_IDENTITY_MISMATCH
        if side_effect not in self._allowed_side_effects:
            return GatewayReason.SIDE_EFFECT_NOT_ALLOWED
        if side_effect.requires_explicit_permission and not has_required_permission:
            return GatewayReason.POLICY_DENIED
        if side_effect.requires_explicit_permission and not (context.actor_id or "").strip():
            return GatewayReason.ACTOR_IDENTITY_REQUIRED
        # A caller cannot escape the paid check by mislabelling the cost:
        # class and amount are both consulted.
        if not self._permit_paid_capabilities and (
            capability_class.incurs_monetary_cost or not cost.is_free
        ):
            return GatewayReason.PAID_CAPABILITY_NOT_AUTHORIZED

        try:
            decision = self._policy_gate.evaluate(context)
        except Exception:
            # A gate that fails is not a gate that approves.
            return GatewayReason.POLICY_GATE_ERROR
        if not isinstance(decision, PolicyDecision):
            return GatewayReason.POLICY_GATE_ERROR
        if not decision.allowed:
            return GatewayReason.POLICY_DENIED
        if decision.operation != operation:
            # The gate must have decided about *this* operation.
            return GatewayReason.POLICY_GATE_ERROR
        return None

    # -- tool invocation --------------------------------------------------

    def invoke_tool(
        self, invocation: ToolInvocation, adapter: ToolAdapter,
    ) -> ToolInvocationResult:
        if not isinstance(invocation, ToolInvocation):
            raise TypeError("invocation must be a ToolInvocation")

        def denied(reason: GatewayReason) -> ToolInvocationResult:
            return ToolInvocationResult(
                invocation_id=invocation.invocation_id,
                tool_id=invocation.descriptor.tool_id,
                outcome=InvocationOutcome.DENIED,
                reason_code=reason.value,
                cost=invocation.cost,
            )

        try:
            adapter_descriptor = adapter.descriptor
        except Exception:
            return denied(GatewayReason.ADAPTER_IDENTITY_MISMATCH)

        identity_matches = (
            isinstance(adapter_descriptor, ToolDescriptor)
            and adapter_descriptor == invocation.descriptor
        )
        reason = self._pre_invocation_denial(
            context=invocation.context,
            side_effect=invocation.descriptor.side_effect,
            capability_class=invocation.descriptor.capability_class,
            cost=invocation.cost,
            identity_matches=identity_matches,
            has_required_permission=invocation.has_required_permission,
            operation=invocation.operation,
        )
        if reason is not None:
            return denied(reason)

        if not self._reserve_invocation(invocation.invocation_id):
            return denied(GatewayReason.DUPLICATE_INVOCATION)

        try:
            result = adapter.invoke(invocation)
        except Exception:
            # Adapter text never becomes a reason code.
            return ToolInvocationResult(
                invocation_id=invocation.invocation_id,
                tool_id=invocation.descriptor.tool_id,
                outcome=InvocationOutcome.PROVIDER_ERROR,
                reason_code=GatewayReason.ADAPTER_ERROR.value,
                cost=invocation.cost,
            )

        if (
            not isinstance(result, ToolInvocationResult)
            or result.tool_id != invocation.descriptor.tool_id
            or result.invocation_id != invocation.invocation_id
        ):
            return ToolInvocationResult(
                invocation_id=invocation.invocation_id,
                tool_id=invocation.descriptor.tool_id,
                outcome=InvocationOutcome.INVALID_RESULT,
                reason_code=GatewayReason.ADAPTER_RESULT_INVALID.value,
                cost=invocation.cost,
            )
        return result

    # -- model invocation -------------------------------------------------

    def invoke_model(
        self, invocation: ModelInvocation, adapter: ModelProviderAdapter,
    ) -> ModelInvocationResult:
        """Models are governed by the same chokepoint as tools.

        A model call is treated as a READ_ONLY external capability: it
        returns information and must not, by itself, change anything.
        """
        if not isinstance(invocation, ModelInvocation):
            raise TypeError("invocation must be a ModelInvocation")

        def denied(reason: GatewayReason) -> ModelInvocationResult:
            return ModelInvocationResult(
                invocation_id=invocation.invocation_id,
                provider_id=invocation.descriptor.provider_id,
                model_id=invocation.descriptor.model_id,
                outcome=InvocationOutcome.DENIED,
                reason_code=reason.value,
                cost=invocation.cost,
            )

        try:
            adapter_descriptor = adapter.descriptor
        except Exception:
            return denied(GatewayReason.ADAPTER_IDENTITY_MISMATCH)

        identity_matches = (
            isinstance(adapter_descriptor, ModelProviderDescriptor)
            and adapter_descriptor == invocation.descriptor
        )
        reason = self._pre_invocation_denial(
            context=invocation.context,
            side_effect=SideEffectClass.READ_ONLY,
            capability_class=invocation.descriptor.capability_class,
            cost=invocation.cost,
            identity_matches=identity_matches,
            has_required_permission=True,
            operation=invocation.context.operation,
        )
        if reason is not None:
            return denied(reason)

        if not self._reserve_invocation(invocation.invocation_id):
            return denied(GatewayReason.DUPLICATE_INVOCATION)

        try:
            result = adapter.invoke(invocation)
        except Exception:
            return ModelInvocationResult(
                invocation_id=invocation.invocation_id,
                provider_id=invocation.descriptor.provider_id,
                model_id=invocation.descriptor.model_id,
                outcome=InvocationOutcome.PROVIDER_ERROR,
                reason_code=GatewayReason.ADAPTER_ERROR.value,
                cost=invocation.cost,
            )

        if (
            not isinstance(result, ModelInvocationResult)
            or result.provider_id != invocation.descriptor.provider_id
            or result.model_id != invocation.descriptor.model_id
            or result.invocation_id != invocation.invocation_id
        ):
            return ModelInvocationResult(
                invocation_id=invocation.invocation_id,
                provider_id=invocation.descriptor.provider_id,
                model_id=invocation.descriptor.model_id,
                outcome=InvocationOutcome.INVALID_RESULT,
                reason_code=GatewayReason.ADAPTER_RESULT_INVALID.value,
                cost=invocation.cost,
            )
        return result
