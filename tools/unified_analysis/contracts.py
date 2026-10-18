"""Structured contracts shared by every stage of the unified analysis. Pure data: no I/O, no model, no state."""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass, field
from datetime import datetime
from decimal import Decimal
from enum import Enum
from typing import Any


class FindingKind(str, Enum):
    """What a finding is. Only an OBSERVED_FACT may be stated as true; the rest are labelled as what they are."""

    OBSERVED_FACT = "OBSERVED_FACT"      # a value read or computed from data (verifiable)
    INTERPRETATION = "INTERPRETATION"    # what a fact is taken to mean
    HYPOTHESIS = "HYPOTHESIS"            # a possible explanation, weaker than an interpretation
    PREDICTION = "PREDICTION"            # a claim about the future (settled later, never verified now)


class Stance(str, Enum):
    BULLISH = "BULLISH"
    BEARISH = "BEARISH"
    NEUTRAL = "NEUTRAL"
    NONE = "NONE"                        # carries no directional view


class AgentStatus(str, Enum):
    OK = "OK"
    ABSTAIN = "ABSTAIN"                  # no usable input (no provider, stale, unavailable): never a default view
    FAILED = "FAILED"                    # the agent raised or returned something malformed


class Classification(str, Enum):
    BULLISH_SETUP = "BULLISH_SETUP"
    BEARISH_SETUP = "BEARISH_SETUP"
    NEUTRAL_RANGE = "NEUTRAL_RANGE"
    INSUFFICIENT_EVIDENCE = "INSUFFICIENT_EVIDENCE"
    RISK_REJECTED = "RISK_REJECTED"


DIRECTIONAL = frozenset({Classification.BULLISH_SETUP, Classification.BEARISH_SETUP})


class Severity(str, Enum):
    BLOCKING = "BLOCKING"                # the conclusion cannot stand while this holds
    MAJOR = "MAJOR"                      # lowers confidence
    MINOR = "MINOR"                      # recorded as an unresolved question


class CheckStatus(str, Enum):
    PASS = "PASS"
    FAIL = "FAIL"
    UNVERIFIABLE = "UNVERIFIABLE"


@dataclass(frozen=True)
class SourceRef:
    """Where a piece of evidence came from and when it was observed (provenance)."""

    source_id: str
    source: str                          # e.g. "binance_spot_klines", "market_archive", "alternative.me_fng"
    symbol: str | None
    timeframe: str | None
    observed_at: datetime                # the newest moment the data describes (a bar's close time)
    fetched_at: datetime | None
    reference: str = ""                  # e.g. "bars 1h 1760000000000..1760716800000 sha256:..."


@dataclass(frozen=True)
class Claim:
    """A numeric statement that verification recomputes from the bars."""

    metric: str
    timeframe: str | None
    value: float

    def __post_init__(self) -> None:
        if not isinstance(self.metric, str) or not self.metric:
            raise ValueError("claim metric is required")
        if isinstance(self.value, bool) or not isinstance(self.value, (int, float)) or not math.isfinite(self.value):
            raise ValueError("claim value must be a finite number")


@dataclass(frozen=True)
class Finding:
    finding_id: str
    agent: str
    kind: FindingKind
    statement: str
    stance: Stance = Stance.NONE
    strength: float = 0.0                # 0..1, the agent's own weight of this finding (not a probability)
    evidence: tuple[str, ...] = ()       # SourceRef ids
    claims: tuple[Claim, ...] = ()
    # Findings computed from the same underlying series share a group: five indicators of one price series are one
    # piece of independent evidence, not five.
    independence_group: str = ""
    model_generated: bool = False

    def __post_init__(self) -> None:
        object.__setattr__(self, "kind", FindingKind(self.kind))
        object.__setattr__(self, "stance", Stance(self.stance))
        if isinstance(self.strength, bool) or not isinstance(self.strength, (int, float)) \
                or not math.isfinite(self.strength) or not 0.0 <= self.strength <= 1.0:
            raise ValueError("finding strength must be in 0..1")
        if not self.finding_id or not self.agent or not self.statement:
            raise ValueError("finding identity and statement are required")


@dataclass(frozen=True)
class SpecialistReport:
    agent: str
    status: AgentStatus
    stance: Stance = Stance.NONE         # the agent's overall view (from its own findings)
    strength: float = 0.0
    findings: tuple[Finding, ...] = ()
    reason: str = ""
    inference_calls: int = 0
    cost_usd: Decimal = Decimal("0")


@dataclass(frozen=True)
class InvalidationCondition:
    """A concrete, checkable condition under which a scenario is wrong."""

    description: str
    metric: str                          # "close"
    timeframe: str
    operator: str                        # "<" or ">"
    threshold: float

    def __post_init__(self) -> None:
        if self.operator not in ("<", ">"):
            raise ValueError("operator must be < or >")
        if isinstance(self.threshold, bool) or not isinstance(self.threshold, (int, float)) \
                or not math.isfinite(self.threshold) or self.threshold <= 0:
            raise ValueError("threshold must be a positive finite number")

    def hit(self, value: float) -> bool:
        return value < self.threshold if self.operator == "<" else value > self.threshold


@dataclass(frozen=True)
class Scenario:
    name: str                            # BULL | BEAR | NEUTRAL
    stance: Stance
    thesis: str
    supporting: tuple[str, ...]          # finding ids
    opposing: tuple[str, ...]
    support_score: float                 # sum over independence groups of the strongest supporting finding
    independent_groups: tuple[str, ...]
    invalidation: tuple[InvalidationCondition, ...]


@dataclass(frozen=True)
class Objection:
    objection_id: str
    reviewer: str
    severity: Severity
    category: str
    statement: str
    targets: tuple[str, ...] = ()        # finding ids or metrics the objection is about
    model_generated: bool = False


@dataclass(frozen=True)
class ReviewResult:
    objections: tuple[Objection, ...]
    unresolved_questions: tuple[str, ...]
    court_status: str                    # NOT_RUN | COMPLETE | PARTIAL | ABSTAINED
    votes: tuple[dict[str, Any], ...] = ()
    tally: dict[str, int] = field(default_factory=dict)
    independence_note: str = ""
    inference_calls: int = 0
    cost_usd: Decimal = Decimal("0")


@dataclass(frozen=True)
class Check:
    check_id: str
    status: CheckStatus
    detail: str
    # A non-blocking FAIL is recorded but excluded the failing item instead of failing the run (a model finding with
    # a wrong number is dropped; a failed specialist becomes a missing source).
    blocking: bool = True


@dataclass(frozen=True)
class VerificationResult:
    checks: tuple[Check, ...]

    @property
    def passed(self) -> bool:
        return all(c.status is not CheckStatus.FAIL for c in self.checks if c.blocking)

    @property
    def failures(self) -> tuple[Check, ...]:
        return tuple(c for c in self.checks if c.status is CheckStatus.FAIL)


@dataclass(frozen=True)
class RiskAssessment:
    rejections: tuple[str, ...]
    warnings: tuple[str, ...]

    @property
    def approved(self) -> bool:
        return not self.rejections


@dataclass(frozen=True)
class AnalysisReport:
    analysis_id: str
    symbol: str
    as_of: datetime
    cutoff_ms: int
    classification: Classification
    primary_scenario: str | None
    confidence: Decimal                  # an evidence-agreement bound, capped by calibration; never a probability
    confidence_basis: dict[str, Any]
    horizon_hours: int
    reason_codes: tuple[str, ...]
    scenarios: tuple[Scenario, ...]
    specialists: tuple[SpecialistReport, ...]
    review: ReviewResult
    verification: VerificationResult
    risk: RiskAssessment
    sources: tuple[SourceRef, ...]
    reference_close: float | None
    unavailable_capabilities: tuple[str, ...]
    metrics: dict[str, Any]
    entry_from_ms: int = 0               # settlement starts at this bar boundary (at or after the decision time)
    note: str = "Advisory analysis only. Not a trading instruction; no order, size or gate follows from it."

    def to_dict(self) -> dict[str, Any]:
        out = to_jsonable(asdict(self))
        out["verification"]["passed"] = self.verification.passed
        out["risk"]["approved"] = self.risk.approved
        return out


def to_jsonable(value: Any) -> Any:
    """Plain JSON types: enums by value, datetimes as ISO-8601, Decimals as strings."""
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, dict):
        return {str(k): to_jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [to_jsonable(v) for v in value]
    return value
