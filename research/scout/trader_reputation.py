"""Trader Reputation Engine: rate external performance claims (Task 011).

A claim ("this trader made 300 %") is untrusted external data. It is rated on
four fixed dimensions:

* SOURCE_VERIFIABILITY -- a hash-pinned execution log whose record count
  matches the claimed trade count, checked against the venue by a verifier on
  the owner's allow-list (``ReputationPolicy.trusted_verifiers``, empty by
  default, so nothing passes until the owner names one). A claim from a social
  source, or with a placeholder digest, fails. Atlas cannot authenticate the
  log itself; "verifiable" means a reviewer can re-check exactly what was
  rated.
* SAMPLE_SIZE -- at least ``min_trades`` trades.
* FEES_AND_SLIPPAGE -- the claim states they are included.
* REGIME_RESILIENCE -- the record spans at least ``min_regimes`` distinct
  market regimes.

Ratings, from least to most permissive:

* ``INSUFFICIENT_EVIDENCE`` -- no verifiable execution log, any dimension not
  assessed, a sample below the minimum, or a claim type that is not a live
  track record. Backtests, commentary and social signals always land here:
  an external backtest cannot be verified, and Atlas runs its own (Task 005).
* ``UNRELIABLE`` -- verifiable and sized, but fails fees or regime coverage.
* ``RESEARCH_CANDIDATE`` -- every dimension passed.

``RESEARCH_CANDIDATE`` is the ceiling and confers no trading authority: it
means only that the idea may be written up as a pre-registered hypothesis.
Anti-copycat rule: no rating, at any level, is a trade signal. Each assessment
carries ``signal_authority: NONE`` and names the only route onward, which is
canonical sealing (Task 005) and statistical adjudication (Task 006).

NB-4 / NB-5 analogues: an unassessed dimension is never a pass, so removing
evidence can only lower the rating; the dimension denominator is the fixed
``REQUIRED_DIMENSION_COUNT``.

This module performs no I/O and imports nothing outside ``research/`` and the
standard library (ADR-0009).
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any

from research.scout.provenance import (
    AUTHORITY_NONE,
    EXPLORATORY,
    ScoutInputError,
    SourceRecord,
    identifier,
    optional_bool,
    optional_count,
    optional_text_tuple,
    parse_utc,
    SourceType,
    reject_unknown_keys,
    require_mapping,
    text,
    text_set,
)

_SHA256_PATTERN = re.compile(r"[0-9a-f]{64}")
#: The digest of empty content: a log "pinned" to it pins nothing.
_EMPTY_SHA256 = hashlib.sha256(b"").hexdigest()

#: The only route by which an external idea can ever influence trading.
NEXT_STEP = "REQUIRES_TASK005_PREREGISTRATION_AND_TASK006_ADJUDICATION"


class ClaimType(str, Enum):
    LIVE_TRACK_RECORD = "LIVE_TRACK_RECORD"
    BACKTEST = "BACKTEST"
    COMMENTARY = "COMMENTARY"
    SOCIAL_SIGNAL = "SOCIAL_SIGNAL"


class VerificationMethod(str, Enum):
    VENUE_STATEMENT = "VENUE_STATEMENT"
    BROKER_API_EXPORT = "BROKER_API_EXPORT"
    ON_CHAIN = "ON_CHAIN"


class ReputationDimension(str, Enum):
    SOURCE_VERIFIABILITY = "SOURCE_VERIFIABILITY"
    SAMPLE_SIZE = "SAMPLE_SIZE"
    FEES_AND_SLIPPAGE = "FEES_AND_SLIPPAGE"
    REGIME_RESILIENCE = "REGIME_RESILIENCE"


DIMENSIONS: tuple[ReputationDimension, ...] = tuple(ReputationDimension)
REQUIRED_DIMENSION_COUNT = len(DIMENSIONS)


class DimensionVerdict(str, Enum):
    PASS = "PASS"
    FAIL = "FAIL"
    UNKNOWN = "UNKNOWN"


class ReputationRating(str, Enum):
    INSUFFICIENT_EVIDENCE = "INSUFFICIENT_EVIDENCE"
    UNRELIABLE = "UNRELIABLE"
    RESEARCH_CANDIDATE = "RESEARCH_CANDIDATE"


#: Permissiveness order, used by the monotonicity tests.
RATING_RANK = {
    ReputationRating.INSUFFICIENT_EVIDENCE: 0,
    ReputationRating.UNRELIABLE: 0,
    ReputationRating.RESEARCH_CANDIDATE: 1,
}


@dataclass(frozen=True)
class ReputationPolicy:
    min_trades: int = 100
    min_regimes: int = 2
    trusted_verifiers: frozenset[str] = field(default_factory=frozenset)

    def __post_init__(self) -> None:
        try:
            verifiers = text_set(self.trusted_verifiers, "trusted_verifiers")
        except ScoutInputError as exc:
            raise ValueError(str(exc)) from exc
        object.__setattr__(self, "trusted_verifiers", verifiers)
        for name in ("min_trades", "min_regimes"):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int) or value < 1:
                raise ValueError(f"{name} must be a positive integer")


@dataclass(frozen=True)
class ExecutionLogEvidence:
    sha256: str
    record_count: int
    venue: str
    verified_by: str
    verification_method: VerificationMethod

    _FIELDS = frozenset({"sha256", "record_count", "venue", "verified_by", "verification_method"})

    @classmethod
    def from_dict(cls, payload: Any) -> "ExecutionLogEvidence":
        payload = require_mapping(payload, "execution_log")
        reject_unknown_keys(payload, cls._FIELDS, "execution_log")
        digest = payload.get("sha256")
        if not isinstance(digest, str) or not _SHA256_PATTERN.fullmatch(digest):
            raise ScoutInputError("execution_log.sha256 must be 64 lowercase hex characters")
        record_count = optional_count(payload, "record_count")
        if record_count is None:
            raise ScoutInputError("execution_log.record_count is required")
        try:
            method = VerificationMethod(payload.get("verification_method"))
        except ValueError as exc:
            raise ScoutInputError(
                f"execution_log.verification_method must be one of {[m.value for m in VerificationMethod]}"
            ) from exc
        return cls(
            sha256=digest,
            record_count=record_count,
            venue=text(payload, "venue", single_line=True),
            verified_by=text(payload, "verified_by", single_line=True),
            verification_method=method,
        )

    def as_dict(self) -> dict[str, Any]:
        return {
            "sha256": self.sha256,
            "record_count": self.record_count,
            "venue": self.venue,
            "verified_by": self.verified_by,
            "verification_method": self.verification_method.value,
        }


@dataclass(frozen=True)
class TraderClaim:
    claim_id: str
    trader_id: str
    claim_type: ClaimType
    source: SourceRecord
    period_start: datetime
    period_end: datetime
    trade_count: int | None
    fees_and_slippage_included: bool | None
    regimes_covered: tuple[str, ...] | None
    execution_log: ExecutionLogEvidence | None
    claimed_return_pct: str | None = None

    _FIELDS = frozenset({
        "claim_id", "trader_id", "claim_type", "source", "period_start", "period_end",
        "trade_count", "fees_and_slippage_included", "regimes_covered", "execution_log",
        "claimed_return_pct",
    })

    @classmethod
    def from_dict(cls, payload: Any) -> "TraderClaim":
        payload = require_mapping(payload, "trader claim")
        reject_unknown_keys(payload, cls._FIELDS, "trader claim")
        try:
            claim_type = ClaimType(payload.get("claim_type"))
        except ValueError as exc:
            raise ScoutInputError(f"claim_type must be one of {[c.value for c in ClaimType]}") from exc
        period_start = parse_utc(payload.get("period_start"), "period_start")
        period_end = parse_utc(payload.get("period_end"), "period_end")
        if period_end <= period_start:
            raise ScoutInputError("period_end must be after period_start")
        log_payload = payload.get("execution_log")
        return cls(
            claim_id=identifier(payload, "claim_id"),
            trader_id=identifier(payload, "trader_id"),
            claim_type=claim_type,
            source=SourceRecord.from_dict(payload.get("source")),
            period_start=period_start,
            period_end=period_end,
            trade_count=optional_count(payload, "trade_count"),
            fees_and_slippage_included=optional_bool(payload, "fees_and_slippage_included"),
            regimes_covered=optional_text_tuple(payload, "regimes_covered", single_line=True),
            execution_log=None if log_payload is None else ExecutionLogEvidence.from_dict(log_payload),
            # The claimant's own words; never parsed into a number Atlas could act on.
            claimed_return_pct=text(payload, "claimed_return_pct", required=False),
        )


@dataclass(frozen=True)
class DimensionResult:
    dimension: ReputationDimension
    verdict: DimensionVerdict
    reason: str

    def as_dict(self) -> dict[str, Any]:
        return {"dimension": self.dimension.value, "verdict": self.verdict.value, "reason": self.reason}


@dataclass(frozen=True)
class TraderAssessment:
    claim_id: str
    trader_id: str
    claim_type: ClaimType
    rating: ReputationRating
    reasons: tuple[str, ...]
    dimensions: tuple[DimensionResult, ...]
    source: SourceRecord
    required_dimension_count: int = REQUIRED_DIMENSION_COUNT
    epistemic_status: str = EXPLORATORY
    signal_authority: str = AUTHORITY_NONE
    next_step: str = NEXT_STEP

    def __post_init__(self) -> None:
        # The firewall tags are invariants, not overridable defaults.
        if (self.epistemic_status != EXPLORATORY or self.signal_authority != AUTHORITY_NONE
                or self.next_step != NEXT_STEP or self.required_dimension_count != REQUIRED_DIMENSION_COUNT):
            raise ValueError("a trader assessment is always EXPLORATORY with no signal authority")
        if tuple(d.dimension for d in self.dimensions) != DIMENSIONS:
            raise ValueError("an assessment must hold all four dimensions in order")
        if self.rating is ReputationRating.RESEARCH_CANDIDATE and (
            any(d.verdict is not DimensionVerdict.PASS for d in self.dimensions)
            or self.claim_type is not ClaimType.LIVE_TRACK_RECORD
            or self.source.source_type is SourceType.SOCIAL
        ):
            raise ValueError("RESEARCH_CANDIDATE requires a non-social live track record with every dimension passed")

    @property
    def passed_dimension_count(self) -> int:
        return sum(1 for d in self.dimensions if d.verdict is DimensionVerdict.PASS)

    def as_dict(self) -> dict[str, Any]:
        return {
            "claim_id": self.claim_id,
            "trader_id": self.trader_id,
            "claim_type": self.claim_type.value,
            "rating": self.rating.value,
            "reasons": list(self.reasons),
            "dimensions": [d.as_dict() for d in self.dimensions],
            "passed_dimension_count": self.passed_dimension_count,
            "required_dimension_count": self.required_dimension_count,
            "source": self.source.as_dict(),
            "epistemic_status": self.epistemic_status,
            "signal_authority": self.signal_authority,
            "next_step": self.next_step,
        }


def _verifiability(claim: TraderClaim, as_of: datetime, policy: ReputationPolicy) -> DimensionResult:
    dim = ReputationDimension.SOURCE_VERIFIABILITY
    if claim.period_end > as_of or claim.source.retrieved_at > as_of:
        return DimensionResult(dim, DimensionVerdict.FAIL, "CLAIM_DATED_AFTER_AS_OF")
    if claim.source.source_type is SourceType.SOCIAL:
        return DimensionResult(dim, DimensionVerdict.FAIL, "SOCIAL_SOURCE")
    log = claim.execution_log
    if log is None:
        return DimensionResult(dim, DimensionVerdict.UNKNOWN, "NO_EXECUTION_LOG")
    if claim.trade_count is None:
        return DimensionResult(dim, DimensionVerdict.UNKNOWN, "TRADE_COUNT_UNKNOWN")
    if log.record_count != claim.trade_count:
        return DimensionResult(dim, DimensionVerdict.FAIL, "LOG_RECORD_COUNT_MISMATCH")
    if len(set(log.sha256)) == 1 or log.sha256 == _EMPTY_SHA256:
        return DimensionResult(dim, DimensionVerdict.FAIL, "PLACEHOLDER_LOG_DIGEST")
    if log.verified_by not in policy.trusted_verifiers:
        return DimensionResult(dim, DimensionVerdict.FAIL, "VERIFIER_NOT_TRUSTED")
    return DimensionResult(dim, DimensionVerdict.PASS, "HASH_PINNED_LOG_MATCHES_TRADE_COUNT")


def _sample_size(claim: TraderClaim, policy: ReputationPolicy) -> DimensionResult:
    dim = ReputationDimension.SAMPLE_SIZE
    if claim.trade_count is None:
        return DimensionResult(dim, DimensionVerdict.UNKNOWN, "TRADE_COUNT_UNKNOWN")
    if claim.trade_count < policy.min_trades:
        return DimensionResult(dim, DimensionVerdict.FAIL, f"FEWER_THAN_{policy.min_trades}_TRADES")
    return DimensionResult(dim, DimensionVerdict.PASS, "SAMPLE_SIZE_MET")


def _fees(claim: TraderClaim) -> DimensionResult:
    dim = ReputationDimension.FEES_AND_SLIPPAGE
    if claim.fees_and_slippage_included is None:
        return DimensionResult(dim, DimensionVerdict.UNKNOWN, "FEES_NOT_STATED")
    if not claim.fees_and_slippage_included:
        return DimensionResult(dim, DimensionVerdict.FAIL, "FEES_AND_SLIPPAGE_EXCLUDED")
    return DimensionResult(dim, DimensionVerdict.PASS, "FEES_AND_SLIPPAGE_INCLUDED")


def _regimes(claim: TraderClaim, policy: ReputationPolicy) -> DimensionResult:
    dim = ReputationDimension.REGIME_RESILIENCE
    if claim.regimes_covered is None:
        return DimensionResult(dim, DimensionVerdict.UNKNOWN, "REGIMES_NOT_STATED")
    distinct = {label.upper() for label in claim.regimes_covered}
    if len(distinct) < policy.min_regimes:
        return DimensionResult(dim, DimensionVerdict.FAIL, f"FEWER_THAN_{policy.min_regimes}_REGIMES")
    return DimensionResult(dim, DimensionVerdict.PASS, "REGIME_COVERAGE_MET")


def assess_claim(
    claim: TraderClaim,
    *,
    as_of: datetime,
    policy: ReputationPolicy | None = None,
) -> TraderAssessment:
    """Rate one external claim. The result is a research lead, never a signal."""
    if not isinstance(claim, TraderClaim):
        raise ScoutInputError("claim must be a TraderClaim")
    if not isinstance(as_of, datetime) or as_of.tzinfo is None or as_of.utcoffset() is None:
        raise ScoutInputError("as_of must be a timezone-aware datetime")
    policy = policy or ReputationPolicy()
    if not isinstance(policy, ReputationPolicy):
        raise ScoutInputError("policy must be a ReputationPolicy")
    dimensions = (
        _verifiability(claim, as_of, policy),
        _sample_size(claim, policy),
        _fees(claim),
        _regimes(claim, policy),
    )
    by_dim = {d.dimension: d for d in dimensions}
    reasons: list[str] = []
    if claim.claim_type is not ClaimType.LIVE_TRACK_RECORD:
        reasons.append(f"CLAIM_TYPE_NOT_VERIFIABLE:{claim.claim_type.value}")
    reasons.extend(d.reason for d in dimensions if d.verdict is not DimensionVerdict.PASS)

    if (
        claim.claim_type is not ClaimType.LIVE_TRACK_RECORD
        or by_dim[ReputationDimension.SOURCE_VERIFIABILITY].verdict is not DimensionVerdict.PASS
        or any(d.verdict is DimensionVerdict.UNKNOWN for d in dimensions)
        or by_dim[ReputationDimension.SAMPLE_SIZE].verdict is not DimensionVerdict.PASS
    ):
        rating = ReputationRating.INSUFFICIENT_EVIDENCE
    elif sum(1 for d in dimensions if d.verdict is DimensionVerdict.PASS) == REQUIRED_DIMENSION_COUNT:
        rating = ReputationRating.RESEARCH_CANDIDATE
    else:
        rating = ReputationRating.UNRELIABLE

    return TraderAssessment(
        claim_id=claim.claim_id,
        trader_id=claim.trader_id,
        claim_type=claim.claim_type,
        rating=rating,
        reasons=tuple(reasons),
        dimensions=dimensions,
        source=claim.source,
    )
