"""Provider-neutral contracts for external model invocation.

This module is vocabulary only. It introduces no provider SDK, no network
client, no credential handling, and no concrete adapter; nothing in the
running system imports it yet. Its purpose is to make the *governance* of a
future external model call representable before any such call exists:

- who is asking (OperationContext identity, reused rather than re-invented),
- what is being asked of which provider/model,
- what that provider costs and whether it is local, open-source, free-tier,
  or paid,
- what came back, as a fixed reason code rather than free-form provider text.

Relationship to core/decision_intelligence.py
---------------------------------------------
`decision_intelligence` already defines `ModelRequest`/`ModelResponse`/
`ModelProvider` and `model_response_to_evidence()`. Those are *decision*
contracts: they describe turning a model's structured output into trading
`Evidence` (symbol, action, confidence, evidence_ids). They are deliberately
left untouched here, and this module neither imports them nor produces
`Evidence`. Introducing a live evidence-producing model provider would
activate a third evidence source, which the M-2 interlock forbids until
fusion confidence semantics are resolved.

This module is about *invocation governance* instead: identity, permission,
cost, and outcome. The two vocabularies are intentionally separate, and the
naming here (`ModelInvocation`/`ModelInvocationResult`/`ModelProviderAdapter`)
avoids colliding with the decision-side names.

Secrets
-------
No field in this module holds, or is permitted to hold, a credential. An
adapter obtains its own credentials through the `SecretProvider` boundary at
the point of use; a credential must never travel through an invocation, a
result, or their metadata. Metadata is sanitized through the same
`OperationResult` boundary used elsewhere.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from enum import Enum
from typing import Any, Mapping, Protocol

from atlas_security import sanitize_sensitive_text

from core.operational_contracts import (
    OperationContext,
    OperationResult,
    sanitized_metadata,
)


class CapabilityClass(str, Enum):
    """Free-first classification shared by model providers and tools.

    Declared in preference order: Atlas prefers deterministic/local work,
    then open-source, then a reliable free tier, and treats a paid provider
    as the last resort requiring an explicit decision.
    """

    LOCAL = "LOCAL"
    OPEN_SOURCE = "OPEN_SOURCE"
    FREE_TIER = "FREE_TIER"
    PAID = "PAID"

    @property
    def incurs_monetary_cost(self) -> bool:
        return self is CapabilityClass.PAID


# Deliberately a tuple, not a sort key computed at call time: the free-first
# order is a policy statement and should be readable as one. A future router
# may consult this; nothing selects a provider automatically today.
FREE_FIRST_PREFERENCE: tuple[CapabilityClass, ...] = (
    CapabilityClass.LOCAL,
    CapabilityClass.OPEN_SOURCE,
    CapabilityClass.FREE_TIER,
    CapabilityClass.PAID,
)


class ModelCapability(str, Enum):
    """What a model can be relied on to do. Unknown values are rejected."""

    TEXT_COMPLETION = "TEXT_COMPLETION"
    STRUCTURED_OUTPUT = "STRUCTURED_OUTPUT"
    CLASSIFICATION = "CLASSIFICATION"
    SUMMARIZATION = "SUMMARIZATION"
    EMBEDDING = "EMBEDDING"


class InvocationOutcome(str, Enum):
    """Fixed outcome vocabulary for any governed external invocation."""

    OK = "OK"
    DENIED = "DENIED"
    PROVIDER_ERROR = "PROVIDER_ERROR"
    TIMEOUT = "TIMEOUT"
    INVALID_RESULT = "INVALID_RESULT"


def sanitized_identifier(value: str, field_name: str) -> str:
    """Validate and sanitize a caller-supplied identifier.

    Identifiers reach logs, audit records, and reason codes, so an id is
    both length-bounded and passed through the sanitizer: a provider_id of
    'api_key=sk-live-...' must not become an audit record that leaks it.
    """
    text = str(value).strip()
    if not text:
        raise ValueError(f"{field_name} is required")
    if len(text) > 200:
        raise ValueError(f"{field_name} is too long")
    if any(character in text for character in "\r\n\t\x00"):
        raise ValueError(f"{field_name} must not contain control characters")
    return sanitize_sensitive_text(text)


def _cost_amount(value: Any, field_name: str) -> Decimal:
    if isinstance(value, float):
        raise ValueError(f"{field_name} must not be float")
    try:
        amount = value if isinstance(value, Decimal) else Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise ValueError(f"invalid {field_name}") from exc
    if not amount.is_finite():
        raise ValueError(f"{field_name} must be finite")
    if amount < 0:
        raise ValueError(f"{field_name} must not be negative")
    return amount


@dataclass(frozen=True, slots=True)
class CostMetadata:
    """Cost classification for one invocation.

    The class/amount consistency rules exist so a provider cannot quietly
    present itself as free: a PAID capability must declare a positive
    estimate, and a LOCAL/OPEN_SOURCE capability must declare none. FREE_TIER
    is allowed a non-zero estimate because a free quota can spill into paid
    overage, and the estimate is where that becomes visible.
    """

    capability_class: CapabilityClass
    estimated_cost: Decimal = Decimal("0")
    actual_cost: Decimal | None = None
    currency: str = "USD"
    budget_reference: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "capability_class", CapabilityClass(self.capability_class),
        )
        object.__setattr__(
            self, "estimated_cost", _cost_amount(self.estimated_cost, "estimated_cost"),
        )
        if self.actual_cost is not None:
            object.__setattr__(
                self, "actual_cost", _cost_amount(self.actual_cost, "actual_cost"),
            )
        object.__setattr__(self, "currency", sanitized_identifier(self.currency, "currency"))
        if self.budget_reference is not None:
            object.__setattr__(
                self, "budget_reference",
                sanitized_identifier(self.budget_reference, "budget_reference"),
            )

        if self.capability_class in (CapabilityClass.LOCAL, CapabilityClass.OPEN_SOURCE):
            if self.estimated_cost != 0 or (self.actual_cost or 0) != 0:
                raise ValueError(
                    f"{self.capability_class.value} capability must not declare a cost"
                )
        elif self.capability_class is CapabilityClass.PAID and self.estimated_cost <= 0:
            raise ValueError("PAID capability must declare a positive estimated_cost")

    @property
    def is_free(self) -> bool:
        """True only when nothing is spent, by class and by amount."""
        return (
            not self.capability_class.incurs_monetary_cost
            and self.estimated_cost == 0
            and (self.actual_cost or Decimal("0")) == 0
        )


@dataclass(frozen=True, slots=True)
class ModelProviderDescriptor:
    """Identity and declared capabilities of one provider/model pair."""

    provider_id: str
    model_id: str
    capability_class: CapabilityClass
    capabilities: frozenset[ModelCapability] = frozenset()
    requires_network: bool = True
    max_input_tokens: int | None = None

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "provider_id", sanitized_identifier(self.provider_id, "provider_id"),
        )
        object.__setattr__(
            self, "model_id", sanitized_identifier(self.model_id, "model_id"),
        )
        object.__setattr__(
            self, "capability_class", CapabilityClass(self.capability_class),
        )
        object.__setattr__(
            self, "capabilities",
            frozenset(ModelCapability(item) for item in self.capabilities),
        )
        if not isinstance(self.requires_network, bool):
            raise ValueError("requires_network must be a bool")
        if self.capability_class is CapabilityClass.LOCAL and self.requires_network:
            raise ValueError("LOCAL capability must not require network access")
        if self.max_input_tokens is not None:
            if (
                not isinstance(self.max_input_tokens, int)
                or isinstance(self.max_input_tokens, bool)
                or self.max_input_tokens <= 0
            ):
                raise ValueError("max_input_tokens must be a positive integer")

    @property
    def qualified_id(self) -> str:
        return f"{self.provider_id}:{self.model_id}"


@dataclass(frozen=True, slots=True)
class ModelInvocation:
    """One governed request to invoke an external model.

    `input_reference` is a pointer (an id, digest, or store key), never raw
    prompt content, so an invocation record can be audited without copying
    whatever the caller was reasoning about into the audit trail.
    """

    context: OperationContext
    descriptor: ModelProviderDescriptor
    task_type: str
    input_reference: str
    cost: CostMetadata
    required_capabilities: frozenset[ModelCapability] = frozenset()
    timeout_ms: int = 30_000
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not isinstance(self.context, OperationContext):
            raise ValueError("context must be an OperationContext")
        if not isinstance(self.descriptor, ModelProviderDescriptor):
            raise ValueError("descriptor must be a ModelProviderDescriptor")
        if not isinstance(self.cost, CostMetadata):
            raise ValueError("cost must be CostMetadata")
        object.__setattr__(self, "task_type", sanitized_identifier(self.task_type, "task_type"))
        object.__setattr__(
            self, "input_reference",
            sanitized_identifier(self.input_reference, "input_reference"),
        )
        object.__setattr__(
            self, "required_capabilities",
            frozenset(ModelCapability(item) for item in self.required_capabilities),
        )
        if (
            not isinstance(self.timeout_ms, int)
            or isinstance(self.timeout_ms, bool)
            or self.timeout_ms <= 0
        ):
            raise ValueError("timeout_ms must be a positive integer")
        if self.cost.capability_class is not self.descriptor.capability_class:
            raise ValueError("cost capability_class must match the descriptor")
        missing = self.required_capabilities - self.descriptor.capabilities
        if missing:
            raise ValueError("provider does not declare the required capabilities")
        object.__setattr__(self, "metadata", sanitized_metadata(self.metadata))

    @property
    def invocation_id(self) -> str:
        return self.context.operation_id


@dataclass(frozen=True, slots=True)
class ModelInvocationResult:
    """Outcome of one governed model invocation.

    Carries no model output, only a reference to it, for the same reason
    `ModelInvocation` carries no prompt.
    """

    invocation_id: str
    provider_id: str
    model_id: str
    outcome: InvocationOutcome
    reason_code: str
    latency_ms: float = 0.0
    cost: CostMetadata | None = None
    output_reference: str | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "invocation_id", sanitized_identifier(self.invocation_id, "invocation_id"),
        )
        object.__setattr__(
            self, "provider_id", sanitized_identifier(self.provider_id, "provider_id"),
        )
        object.__setattr__(self, "model_id", sanitized_identifier(self.model_id, "model_id"))
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
        object.__setattr__(self, "metadata", sanitized_metadata(self.metadata))

    @property
    def succeeded(self) -> bool:
        return self.outcome is InvocationOutcome.OK

    def to_operation_result(self, *, component: str, operation: str) -> OperationResult:
        """Project onto the audited operation contract.

        Routing through OperationResult means invocation metadata inherits
        the sanitization and immutability guarantees already enforced there,
        rather than growing a second, weaker evidence path.
        """
        return OperationResult(
            operation=operation,
            status=self.outcome.value,
            component=component,
            reason_code=self.reason_code,
            latency_ms=self.latency_ms,
            metadata=self.metadata,
            model_provider=self.provider_id,
            model_id=self.model_id,
            cost=(
                None if self.cost is None
                else f"{self.cost.capability_class.value}:{self.cost.estimated_cost}"
            ),
        )


class ModelProviderAdapter(Protocol):
    """Contract every concrete model adapter implements.

    Concrete adapters belong in the infrastructure layer, behind the
    gateway. Intelligence-layer code depends on this protocol, never on an
    adapter module; the L4->L2 forbidden edge enforces that structurally.
    """

    @property
    def descriptor(self) -> ModelProviderDescriptor:
        ...

    def invoke(self, invocation: ModelInvocation) -> ModelInvocationResult:
        ...
