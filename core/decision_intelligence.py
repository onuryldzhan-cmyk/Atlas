"""Canonical Phase-5 decision-intelligence contracts.

This module produces auditable proposals only.  It deliberately has no broker,
exchange, risk-policy mutation, credential, or execution dependencies.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from decimal import Decimal, InvalidOperation
from enum import Enum
from typing import TYPE_CHECKING, Any, Mapping, Protocol, Sequence

if TYPE_CHECKING:
    from core.audit_event import AuditEvent
    from core.audit_event_store import AuditEventStore


D = Decimal
POLICY_VERSION = "phase5-decision-intelligence-v1"


def _decimal(value: Any, name: str) -> Decimal:
    if isinstance(value, float):
        raise ValueError(f"{name} must not be float")
    try:
        result = value if isinstance(value, Decimal) else D(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise ValueError(f"invalid {name}") from exc
    if not result.is_finite():
        raise ValueError(f"{name} must be finite")
    return result


def _utc(value: datetime, name: str) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None:
        raise ValueError(f"{name} must be timezone-aware")
    return value.astimezone(UTC)


class Action(str, Enum):
    BUY = "BUY"
    SELL = "SELL"
    HOLD = "HOLD"
    ABSTAIN = "ABSTAIN"


class EvidenceStatus(str, Enum):
    VALID = "VALID"
    STALE = "STALE"
    INVALID = "INVALID"


class ModelStatus(str, Enum):
    OK = "OK"
    TIMEOUT = "TIMEOUT"
    ERROR = "ERROR"


@dataclass(frozen=True)
class FreshnessPolicy:
    max_age: timedelta = timedelta(minutes=5)
    future_tolerance: timedelta = timedelta(seconds=5)

    def __post_init__(self) -> None:
        if self.max_age <= timedelta(0) or self.future_tolerance < timedelta(0):
            raise ValueError("invalid freshness policy")


@dataclass(frozen=True)
class Evidence:
    evidence_id: str
    source: str
    source_version: str
    symbol: str
    action: Action
    score: Decimal
    observed_at: datetime
    status: EvidenceStatus = EvidenceStatus.VALID
    reason_codes: tuple[str, ...] = ()
    model_provider: str | None = None
    model_name: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "action", Action(self.action))
        score = _decimal(self.score, "score")
        if not D("0") <= score <= D("1"):
            raise ValueError("score must be in 0..1")
        object.__setattr__(self, "score", score)
        object.__setattr__(self, "observed_at", _utc(self.observed_at, "observed_at"))
        if not self.evidence_id or not self.source or not self.source_version or not self.symbol:
            raise ValueError("evidence identity fields are required")
        if bool(self.model_provider) != bool(self.model_name):
            raise ValueError("model provider and model name must be supplied together")

    def quality_at(self, now: datetime, policy: FreshnessPolicy) -> EvidenceStatus:
        now = _utc(now, "now")
        if self.status is not EvidenceStatus.VALID:
            return self.status
        if self.observed_at > now + policy.future_tolerance:
            return EvidenceStatus.INVALID
        if now - self.observed_at > policy.max_age:
            return EvidenceStatus.STALE
        return EvidenceStatus.VALID


@dataclass(frozen=True)
class FusionPolicy:
    weights: Mapping[str, Decimal]
    freshness: FreshnessPolicy = field(default_factory=FreshnessPolicy)
    minimum_sources: int = 1
    decision_threshold: Decimal = D("0.20")

    def __post_init__(self) -> None:
        normalized = {key: _decimal(value, f"weight[{key}]") for key, value in self.weights.items()}
        if not normalized or any(value <= 0 for value in normalized.values()):
            raise ValueError("positive source weights required")
        threshold = _decimal(self.decision_threshold, "decision_threshold")
        if not D("0") <= threshold <= D("1") or self.minimum_sources < 1:
            raise ValueError("invalid fusion policy")
        object.__setattr__(self, "weights", normalized)
        object.__setattr__(self, "decision_threshold", threshold)


@dataclass(frozen=True)
class FusionResult:
    action: Action
    confidence: Decimal
    evidence: tuple[Evidence, ...]
    rejected: tuple[tuple[str, str], ...]
    reason_codes: tuple[str, ...]
    disagreement: Decimal
    calibrated_probability: bool = False
    # Availability against the expected roster (the policy's configured
    # sources), kept separate from what was observed (P4-CLOSURE-004 F-1).
    expected_sources: tuple[str, ...] = ()
    missing_sources: tuple[str, ...] = ()
    coverage: Decimal = D("1")


class SignalFusion:
    """Deterministic, one-source-one-vote evidence fusion.

    **Expected roster (NB-5).** The denominator is the total weight of every
    source the policy is configured to expect, never only the weight of the
    evidence that happened to arrive. An expected source with no accepted
    evidence (absent, stale, invalid, wrong symbol) is *missing*.

    **Missing is never agreement; removal never raises (NB-4).** Each
    direction's score is a worst-case bound over every vote a missing source
    could have cast: a missing source is counted as fully against that
    direction (``-weight``). Present evidence contributes its signed vote
    (``+score*w`` for, ``-score*w`` against, ``0`` for HOLD/ABSTAIN), which
    is always >= ``-w``. Removing any item therefore replaces a term with one
    that is no larger, for both directions at once: no confidence rises and
    no decision becomes more permissive when evidence is removed. With the
    full roster present the bound equals the previous signed mean exactly,
    so complete evidence behaves as before.

    **Precondition: one item per source.** A second item from a source is
    rejected as DUPLICATE_SOURCE, so removing the first lets the second count
    and the NB-4 guarantee above does not hold for such input. The Phase-5
    caller (``AtlasBrain._build_phase5_shadow_proposal``) sends exactly one
    item per agent (review N-3). The "never more permissive" part also
    assumes ``decision_threshold > 0``: at exactly 0 a zero net already
    resolves to SELL, as it did before this change (review NF-8); the
    Phase-5 caller uses the default 0.20.
    """

    def __init__(self, policy: FusionPolicy):
        self.policy = policy

    def fuse(self, symbol: str, evidence: Sequence[Evidence], *, now: datetime) -> FusionResult:
        accepted: list[Evidence] = []
        rejected: list[tuple[str, str]] = []
        seen_sources: set[str] = set()
        for item in sorted(evidence, key=lambda x: (x.source, x.evidence_id)):
            if item.symbol != symbol:
                rejected.append((item.evidence_id, "WRONG_SYMBOL")); continue
            if item.source not in self.policy.weights:
                rejected.append((item.evidence_id, "UNCONFIGURED_SOURCE")); continue
            if item.source in seen_sources:
                rejected.append((item.evidence_id, "DUPLICATE_SOURCE")); continue
            quality = item.quality_at(now, self.policy.freshness)
            if quality is not EvidenceStatus.VALID:
                rejected.append((item.evidence_id, quality.value)); continue
            seen_sources.add(item.source); accepted.append(item)

        weights = self.policy.weights
        expected = tuple(sorted(weights))
        present = {x.source for x in accepted}
        missing = tuple(source for source in expected if source not in present)
        expected_weight = sum(weights.values(), D("0"))  # NB-5 denominator
        accepted_weight = sum((weights[x.source] for x in accepted), D("0"))
        coverage = (accepted_weight / expected_weight).quantize(D("0.000001"))
        availability = {"expected_sources": expected, "missing_sources": missing, "coverage": coverage}

        if len(accepted) < self.policy.minimum_sources:
            return FusionResult(Action.ABSTAIN, D("0"), tuple(accepted), tuple(rejected),
                                ("INSUFFICIENT_VALID_EVIDENCE",), D("1"), **availability)
        signed = {Action.BUY: D("1"), Action.SELL: D("-1"), Action.HOLD: D("0"), Action.ABSTAIN: D("0")}
        present_net = sum((signed[x.action] * x.score * weights[x.source] for x in accepted), D("0"))
        missing_weight = expected_weight - accepted_weight
        # Worst-case bounds: every missing source counted as fully against.
        buy_bound = (present_net - missing_weight) / expected_weight
        sell_bound = (-present_net - missing_weight) / expected_weight
        bound = max(buy_bound, sell_bound)
        confidence = max(D("0"), min(D("1"), bound)).quantize(D("0.000001"))
        directional = {x.action for x in accepted if x.action in (Action.BUY, Action.SELL)}
        disagreement = (D("1") - confidence).quantize(D("0.000001")) if len(directional) > 1 else D("0")
        if bound < self.policy.decision_threshold:
            action = Action.ABSTAIN
            reasons: tuple[str, ...] = ("CONTRADICTORY_OR_WEAK_EVIDENCE",)
        else:
            action = Action.BUY if present_net > 0 else Action.SELL
            reasons = ("FUSED_EVIDENCE",)
        if missing:
            reasons = reasons + ("EXPECTED_SOURCES_MISSING",)
        return FusionResult(action, confidence, tuple(accepted), tuple(rejected), reasons, disagreement,
                            **availability)


@dataclass(frozen=True)
class ModelRequest:
    request_id: str
    symbol: str
    schema_version: str
    inputs: Mapping[str, Any]
    timeout_ms: int

    def __post_init__(self) -> None:
        if not self.request_id or not self.symbol or self.timeout_ms <= 0:
            raise ValueError("invalid model request")


@dataclass(frozen=True)
class ModelResponse:
    provider: str
    model: str
    request_id: str
    status: ModelStatus
    output: Mapping[str, Any] | None
    latency_ms: int
    finish_reason: str | None = None
    token_usage: Mapping[str, int] = field(default_factory=dict)
    cost_metadata: Mapping[str, str] = field(default_factory=dict)
    error_class: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "status", ModelStatus(self.status))
        if not self.provider or not self.model or not self.request_id or self.latency_ms < 0:
            raise ValueError("invalid model response metadata")


class ModelProvider(Protocol):
    def complete(self, request: ModelRequest) -> ModelResponse: ...


def model_response_to_evidence(response: ModelResponse, request: ModelRequest,
                               *, observed_at: datetime) -> Evidence:
    """Validate untrusted structured output; errors always become abstention evidence."""
    reason = "MODEL_OUTPUT_VALID"
    action = Action.ABSTAIN
    score = D("0")
    output = response.output
    try:
        if response.request_id != request.request_id or response.status is not ModelStatus.OK:
            raise ValueError("MODEL_UNAVAILABLE")
        if not isinstance(output, Mapping) or set(output) - {"action", "confidence", "symbol", "evidence_ids", "reason_codes"}:
            raise ValueError("MALFORMED_MODEL_OUTPUT")
        if output.get("symbol") != request.symbol:
            raise ValueError("MODEL_SYMBOL_MISMATCH")
        action = Action(str(output.get("action")))
        score = _decimal(output.get("confidence"), "model confidence")
        if not D("0") <= score <= D("1"):
            raise ValueError("MODEL_CONFIDENCE_OUT_OF_BOUNDS")
        refs = output.get("evidence_ids")
        if not isinstance(refs, list) or not refs or not all(isinstance(x, str) and x for x in refs):
            raise ValueError("MODEL_EVIDENCE_REQUIRED")
    except (ValueError, TypeError) as exc:
        reason = str(exc)
        action, score = Action.ABSTAIN, D("0")
    return Evidence(f"model:{response.provider}:{response.model}:{response.request_id}",
                    f"model:{response.provider}:{response.model}", "1", request.symbol,
                    action, score, observed_at, reason_codes=(reason,),
                    model_provider=response.provider, model_name=response.model)


@dataclass(frozen=True)
class StrategyDescriptor:
    strategy_id: str
    version: str
    supported_symbols: frozenset[str]
    market_types: frozenset[str]
    required_inputs: frozenset[str]
    confidence_weight: Decimal = D("1")
    enabled: bool = True

    def __post_init__(self) -> None:
        weight = _decimal(self.confidence_weight, "confidence_weight")
        if not self.strategy_id or not self.version or weight <= 0:
            raise ValueError("invalid strategy descriptor")
        object.__setattr__(self, "confidence_weight", weight)


class Strategy(Protocol):
    descriptor: StrategyDescriptor
    def generate(self, symbol: str, inputs: Mapping[str, Any], now: datetime) -> Evidence: ...


class StrategyRegistry:
    def __init__(self) -> None:
        self._strategies: dict[str, Strategy] = {}

    def register(self, strategy: Strategy) -> None:
        key = strategy.descriptor.strategy_id
        if key in self._strategies:
            raise ValueError("duplicate strategy_id")
        self._strategies[key] = strategy

    def generate(self, symbol: str, market_type: str, inputs: Mapping[str, Any], now: datetime) -> tuple[Evidence, ...]:
        result = []
        for key in sorted(self._strategies):
            strategy = self._strategies[key]; descriptor = strategy.descriptor
            if not descriptor.enabled or symbol not in descriptor.supported_symbols or market_type not in descriptor.market_types:
                continue
            if not descriptor.required_inputs.issubset(inputs):
                continue
            item = strategy.generate(symbol, inputs, now)
            if item.source != f"strategy:{descriptor.strategy_id}:{descriptor.version}" or item.symbol != symbol:
                raise ValueError("invalid strategy attribution")
            result.append(item)
        return tuple(result)


@dataclass(frozen=True)
class CanonicalDecision:
    decision_id: str
    symbol: str
    action: Action
    confidence: Decimal
    timestamp: datetime
    strategy_sources: tuple[str, ...]
    evidence_ids: tuple[str, ...]
    reason_codes: tuple[str, ...]
    data_status: EvidenceStatus
    policy_version: str
    market_context: Mapping[str, str] = field(default_factory=dict)
    model_attribution: tuple[tuple[str, str], ...] = ()
    calibrated_probability: bool = False
    authority: str = "PROPOSAL_ONLY"

    def __post_init__(self) -> None:
        object.__setattr__(self, "action", Action(self.action))
        confidence = _decimal(self.confidence, "confidence")
        if not D("0") <= confidence <= D("1"):
            raise ValueError("confidence must be in 0..1")
        object.__setattr__(self, "confidence", confidence)
        object.__setattr__(self, "timestamp", _utc(self.timestamp, "timestamp"))
        if self.authority != "PROPOSAL_ONLY":
            raise ValueError("Phase-5 decisions cannot carry execution authority")
        if self.action in (Action.BUY, Action.SELL) and (not self.evidence_ids or self.data_status is not EvidenceStatus.VALID):
            raise ValueError("material decisions require valid evidence")

    @classmethod
    def from_fusion(cls, symbol: str, fusion: FusionResult, *, timestamp: datetime,
                    market_context: Mapping[str, str] | None = None) -> "CanonicalDecision":
        timestamp = _utc(timestamp, "timestamp")
        market_context = dict(market_context or {})
        if fusion.missing_sources:
            # Availability stays visible in the audit trail (F-1): which
            # expected sources were absent and the observed coverage.
            market_context["missing_expected_sources"] = json.dumps(
                list(fusion.missing_sources), separators=(",", ":"))
            market_context["expected_source_coverage"] = str(fusion.coverage)
        models = sorted({(x.model_provider, x.model_name) for x in fusion.evidence if x.model_provider and x.model_name})
        strategies = sorted({x.source for x in fusion.evidence})
        payload = {
            "symbol": symbol, "action": fusion.action.value, "confidence": str(fusion.confidence),
            "timestamp": timestamp.isoformat(), "evidence": sorted(x.evidence_id for x in fusion.evidence),
            "policy": POLICY_VERSION,
            "reason_codes": list(fusion.reason_codes),
            "model_attribution": [list(m) for m in models],
            "market_context": dict(market_context),
        }
        decision_id = hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
        status = EvidenceStatus.VALID if fusion.evidence else EvidenceStatus.INVALID
        return cls(decision_id, symbol, fusion.action, fusion.confidence, timestamp,
                   tuple(strategies), tuple(sorted(x.evidence_id for x in fusion.evidence)),
                   fusion.reason_codes, status, POLICY_VERSION, market_context,
                   tuple(models), fusion.calibrated_probability)

    def audit_record(self) -> Mapping[str, Any]:
        return {
            "decision_id": self.decision_id, "symbol": self.symbol, "action": self.action.value,
            "confidence": str(self.confidence), "confidence_is_probability": self.calibrated_probability,
            "timestamp": self.timestamp.isoformat(), "strategy_sources": list(self.strategy_sources),
            "evidence_ids": list(self.evidence_ids), "model_attribution": [list(x) for x in self.model_attribution],
            "reason_codes": list(self.reason_codes), "data_status": self.data_status.value,
            "policy_version": self.policy_version, "market_context": dict(self.market_context),
            "authority": self.authority,
        }


def record_canonical_decision(store: "AuditEventStore", decision: CanonicalDecision) -> "AuditEvent":
    """Append a Phase-5 decision proposal to the append-only audit chain."""
    return store.append(
        event_type="DECISION_PROPOSED",
        source="core.decision_intelligence",
        aggregate_type="decision",
        aggregate_id=decision.decision_id,
        payload=decision.audit_record(),
    )


class OfflineLearningBoundary:
    """Outcome recording/proposals only; production mutation is categorically denied."""

    def __init__(self) -> None:
        self._outcomes: list[Mapping[str, Any]] = []

    def record_outcome(self, decision_id: str, metrics: Mapping[str, Any]) -> None:
        if not decision_id:
            raise ValueError("decision_id required")
        self._outcomes.append({"decision_id": decision_id, "metrics": dict(metrics)})

    def propose_parameters(self, strategy_id: str, parameters: Mapping[str, Any]) -> Mapping[str, Any]:
        return {"strategy_id": strategy_id, "parameters": dict(parameters), "status": "RESEARCH_PROPOSAL", "approved": False}

    def mutate_production(self, *_: Any, **__: Any) -> None:
        raise PermissionError("production self-modification is denied")

    @property
    def outcomes(self) -> tuple[Mapping[str, Any], ...]:
        return tuple(self._outcomes)
