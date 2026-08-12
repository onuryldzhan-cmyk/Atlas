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
from typing import Any, Mapping, Protocol

from atlas_security import sanitize_sensitive_data


def _new_id() -> str:
    return str(uuid.uuid4())


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _required(value: str, field_name: str) -> None:
    if not str(value).strip():
        raise ValueError(f"{field_name} is required")


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
        sanitized = sanitize_sensitive_data(dict(self.metadata))
        object.__setattr__(
            self, "metadata", sanitized if isinstance(sanitized, dict) else {},
        )

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
