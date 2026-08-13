"""Operational seams for future observability and policy/governance hooks.

These are data contracts only:

- OperationContext / OperationResult: an OpenTelemetry-compatible shape
  for a structured operation (trace/operation/actor/request identity in,
  status/reason/latency out), sanitized through the existing
  atlas_security authority before it ever leaves this module. No
  OpenTelemetry SDK, exporter, or collector is introduced here.

- PolicyDecision / PolicyGate: the minimum shape a future authorization
  check (model call, tool call, code modification, deployment, live
  trading) would need to return. No policy engine, RBAC store, or agent
  scheduler is introduced here, and nothing in the runtime currently
  calls PolicyGate.evaluate().

Existing production call sites are not required to adopt these types by
this change.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from types import MappingProxyType
from typing import Any, Mapping, Protocol

from atlas_security import sanitize_sensitive_data, sanitize_sensitive_text


def _new_id() -> str:
    return str(uuid.uuid4())


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _required(value: str, field_name: str) -> None:
    if not str(value).strip():
        raise ValueError(f"{field_name} is required")


def _sanitized_optional(value: str | None) -> str | None:
    return None if value is None else sanitize_sensitive_text(value)


def _freeze(value: Any) -> Any:
    """Recursively convert a sanitized structure into an immutable one.

    sanitize_sensitive_data already returns structures with no aliasing to
    caller-owned objects, but the result is still built from plain, mutable
    dict/list instances. Freezing closes the remaining post-construction
    mutation path (e.g. ``result.metadata["k"] = "secret"`` or mutating a
    nested dict reached through the sanitized value).
    """
    if isinstance(value, Mapping):
        return MappingProxyType({key: _freeze(item) for key, item in value.items()})
    if isinstance(value, (list, tuple)):
        return tuple(_freeze(item) for item in value)
    return value


def sanitized_metadata(metadata: Mapping[str, Any] | None) -> Mapping[str, Any]:
    """Sanitize and freeze a caller-supplied metadata mapping.

    The single place any Atlas contract turns untrusted metadata into
    something safe to hold, repr, and audit. Exposed so that other contract
    modules reuse this exact boundary instead of growing a second, weaker
    one; every caller gets the same redaction rules and the same immunity to
    post-construction mutation.
    """
    sanitized = sanitize_sensitive_data(dict(metadata or {}))
    return _freeze(sanitized if isinstance(sanitized, dict) else {})


@dataclass(frozen=True, slots=True)
class OperationContext:
    """Immutable identity for one in-flight Atlas operation."""

    component: str
    operation: str
    trace_id: str = field(default_factory=_new_id)
    operation_id: str = field(default_factory=_new_id)
    request_id: str | None = None
    actor_id: str | None = None
    symbol: str | None = None
    mode: str | None = None
    timestamp: str = field(default_factory=_now)

    def __post_init__(self) -> None:
        _required(self.component, "component")
        _required(self.operation, "operation")
        # trace_id / operation_id are internally generated UUID identity and
        # are left untouched. Every other string-bearing field is caller- or
        # operator-influenced and is sanitized so a secret-shaped value
        # cannot survive into repr()/str() or a downstream OperationResult.
        object.__setattr__(self, "component", sanitize_sensitive_text(self.component))
        object.__setattr__(self, "operation", sanitize_sensitive_text(self.operation))
        object.__setattr__(self, "request_id", _sanitized_optional(self.request_id))
        object.__setattr__(self, "actor_id", _sanitized_optional(self.actor_id))
        object.__setattr__(self, "symbol", _sanitized_optional(self.symbol))
        object.__setattr__(self, "mode", _sanitized_optional(self.mode))


@dataclass(frozen=True, slots=True)
class OperationResult:
    """Structured outcome of one OperationContext, sanitized on construction."""

    operation: str
    status: str
    component: str
    reason_code: str = ""
    latency_ms: float | None = None
    trace_id: str | None = None
    actor_id: str | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)

    # Future-compatible optional fields (model/tool/evidence provenance).
    # None of these are populated by any current caller.
    model_provider: str | None = None
    model_id: str | None = None
    tool_id: str | None = None
    token_count: int | None = None
    cost: str | None = None
    evidence_ids: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        _required(self.operation, "operation")
        _required(self.status, "status")
        _required(self.component, "component")
        # trace_id is internally generated/propagated UUID identity and is
        # left untouched. Every other string-bearing scalar, evidence_ids,
        # and metadata are sanitized so a secret-shaped value cannot survive
        # into repr()/str() or serialized output, regardless of which field
        # it arrived through.
        object.__setattr__(self, "operation", sanitize_sensitive_text(self.operation))
        object.__setattr__(self, "status", sanitize_sensitive_text(self.status))
        object.__setattr__(self, "component", sanitize_sensitive_text(self.component))
        object.__setattr__(self, "reason_code", sanitize_sensitive_text(self.reason_code))
        object.__setattr__(self, "actor_id", _sanitized_optional(self.actor_id))
        object.__setattr__(self, "model_provider", _sanitized_optional(self.model_provider))
        object.__setattr__(self, "model_id", _sanitized_optional(self.model_id))
        object.__setattr__(self, "tool_id", _sanitized_optional(self.tool_id))
        object.__setattr__(self, "cost", _sanitized_optional(self.cost))
        object.__setattr__(
            self,
            "evidence_ids",
            tuple(sanitize_sensitive_text(item) for item in self.evidence_ids),
        )
        object.__setattr__(self, "metadata", sanitized_metadata(self.metadata))

    @classmethod
    def from_context(
        cls,
        context: OperationContext,
        *,
        status: str,
        reason_code: str = "",
        latency_ms: float | None = None,
        metadata: Mapping[str, Any] | None = None,
        **future_fields: Any,
    ) -> "OperationResult":
        return cls(
            operation=context.operation,
            status=status,
            component=context.component,
            reason_code=reason_code,
            latency_ms=latency_ms,
            trace_id=context.trace_id,
            actor_id=context.actor_id,
            metadata=metadata or {},
            **future_fields,
        )


@dataclass(frozen=True, slots=True)
class PolicyDecision:
    """Minimum shape a future authorization gate returns."""

    allowed: bool
    reason_code: str
    policy_id: str
    operation: str
    actor_id: str | None = None

    def __post_init__(self) -> None:
        _required(self.reason_code, "reason_code")
        _required(self.policy_id, "policy_id")
        _required(self.operation, "operation")


class PolicyGate(Protocol):
    """Contract a future authorization check (model/tool/code/deploy/live
    trading) would implement. Nothing in the runtime calls this yet."""

    def evaluate(self, context: OperationContext) -> PolicyDecision:
        ...
