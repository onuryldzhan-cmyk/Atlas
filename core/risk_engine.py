"""Canonical, deterministic Phase-3 risk and capital admission contract.

This module performs calculations only.  Callers own authoritative portfolio
and accounting persistence and must restore it before setting ``state_ready``.
All financially material values are Decimal; binary floats are rejected.

Risk taxonomy projection
------------------------
Upstream analytical risk has four states (LOW, MEDIUM, HIGH, CRITICAL);
executable bucket policy has three (``RiskBucket``).  CRITICAL is a valid
upstream state, not malformed input, so it stays visible in decision and
audit contracts and is never normalized away or aliased to HIGH.  It simply
cannot open or increase exposure: a new-risk request carrying CRITICAL is
rejected with ``CRITICAL_RISK_NOT_EXECUTABLE`` and zero allocation.  Genuine
risk reduction stays permitted, because refusing to let a position be closed
would trap exposure in exactly the state judged most dangerous; such requests
still satisfy every existing reduction check before approval.

Unsupported risk (NBF-4)
------------------------
A risk classification that is present but that Atlas does not understand
(``EXTREME``, ``VERY_HIGH``, ``SEVERE``, any future label) is a fifth
analytical state, distinct from both CRITICAL and malformed input.  It
carries no policy, so it can never be resolved into an executable bucket:
it collapses onto the ``UNKNOWN`` sentinel and a new-risk request carrying
it is rejected with ``UNSUPPORTED_RISK_LEVEL`` and zero allocation.  Like
CRITICAL, it does not trap exposure: a structurally verified reduce-only
exit is still approved through the existing reduction checks.

Absence is deliberately *not* this state.  A missing/None/empty risk value
retains its legacy ``MEDIUM`` default, which is applied by the syntactic
normalization layers before a request reaches this module; an empty value
arriving here is therefore malformed input, not absence.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation, ROUND_HALF_EVEN, localcontext
from datetime import UTC, datetime
from enum import Enum
import threading
from typing import Any, Mapping


ZERO = Decimal("0")
ONE = Decimal("1")

# Block 5L: every capital figure this module derives is computed inside an
# explicit local context, matching the settlement precision
# ``ExecutionPortfolioFoundation`` already uses. Risk ceilings and the
# quantity/notional gate are capital-accounting authority: derived under
# whatever ``decimal`` precision the calling process happens to have set, a
# ceiling could round *up* and admit an allocation above the true policy
# limit. Restated here rather than imported so no new module edge is created.
RISK_CONTEXT_PRECISION = 50


class RiskDecisionStatus(str, Enum):
    APPROVE = "APPROVE"
    REJECT = "REJECT"
    BLOCK_RECOVERY_REQUIRED = "BLOCK_RECOVERY_REQUIRED"


class RiskBucket(str, Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"


NON_EXECUTABLE_RISK_LEVELS = frozenset({"CRITICAL"})
UNSUPPORTED_RISK_SENTINEL = "UNKNOWN"
ANALYTICAL_RISK_LEVELS = (
    frozenset(b.value for b in RiskBucket)
    | NON_EXECUTABLE_RISK_LEVELS
    | {UNSUPPORTED_RISK_SENTINEL}
)


def analytical_risk_level(value: Any) -> str:
    """Resolve a request risk level inside the analytical taxonomy.

    Recognized states are LOW / MEDIUM / HIGH (executable), CRITICAL (valid
    maximum-risk, non-executable) and UNKNOWN (unsupported, non-executable).

    A present but unrecognized classification collapses onto the UNKNOWN
    sentinel rather than raising: it is a real upstream state Atlas cannot
    interpret, and it must fail closed as unsupported instead of being
    reported as malformed financial input or resolved to a bucket.

    An absent, empty or non-textual value still raises, so it keeps failing
    closed as malformed financial input exactly as before.  Absence defaults
    belong to the syntactic normalization layers, not to this boundary.
    """
    if isinstance(value, RiskBucket):
        return value.value
    if isinstance(value, Enum):
        raw = value.value if isinstance(value.value, str) else value.name
    elif isinstance(value, str):
        raw = value
    else:
        raise ValueError("risk level must be a risk enum or string")
    level = raw.strip().upper()
    if not level:
        raise ValueError("risk level is required")
    if level not in ANALYTICAL_RISK_LEVELS:
        return UNSUPPORTED_RISK_SENTINEL
    return level


class DrawdownLevel(str, Enum):
    NORMAL = "NORMAL"
    WARNING = "WARNING"
    RESTRICT = "RESTRICT"
    HALT_NEW_RISK = "HALT_NEW_RISK"


def decimal_value(value: Any, name: str, *, allow_zero: bool = True) -> Decimal:
    """Convert safe textual/integer values and reject floats/non-finite values."""
    if isinstance(value, bool) or isinstance(value, float):
        raise ValueError(f"{name} must be a Decimal-compatible non-float value")
    try:
        result = value if isinstance(value, Decimal) else Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise ValueError(f"{name} is not a valid decimal") from exc
    if not result.is_finite() or result < ZERO or (not allow_zero and result == ZERO):
        qualifier = "positive" if not allow_zero else "non-negative"
        raise ValueError(f"{name} must be finite and {qualifier}")
    return result


@dataclass(frozen=True)
class BucketPolicy:
    max_allocation_pct: Decimal
    minimum_confidence: Decimal
    exposure_ceiling_pct: Decimal

    def __post_init__(self) -> None:
        for name in ("max_allocation_pct", "minimum_confidence", "exposure_ceiling_pct"):
            value = decimal_value(getattr(self, name), name)
            if value > ONE:
                raise ValueError(f"{name} must be between 0 and 1")
            object.__setattr__(self, name, value)


# Registry v5.22 (owner decision): while a confidence-floor experiment admits
# a BUY that the default floor would reject, the position is sized with this
# bucket's allocation/exposure limits (10% / 20%), whatever the decision's
# bucket - so moving decisions from HIGH to MEDIUM cannot enlarge them.
EXPERIMENT_SIZING_BUCKET = RiskBucket.HIGH


def _default_buckets() -> dict[RiskBucket, BucketPolicy]:
    return {
        RiskBucket.LOW: BucketPolicy(Decimal("0.40"), Decimal("0.60"), Decimal("0.60")),
        RiskBucket.MEDIUM: BucketPolicy(Decimal("0.25"), Decimal("0.70"), Decimal("0.40")),
        RiskBucket.HIGH: BucketPolicy(Decimal("0.10"), Decimal("0.80"), Decimal("0.20")),
    }


@dataclass(frozen=True)
class ConfidenceFloorExperiment:
    """A time-boxed, sample-capped lowering of the BUY confidence floor.

    It is not policy: ``RiskPolicy`` and its version stay unchanged, so
    persisted risk state keeps matching. It can only lower the floor for the
    named buckets, never below the policy's global minimum, and only while
    ``starts_at <= now < ends_at`` and fewer than ``max_admissions`` tagged
    approvals have been issued. Attachment is the composition root's job and
    is restricted to PAPER there.
    """

    experiment_id: str
    minimum_confidence: Decimal
    buckets: frozenset[RiskBucket]
    starts_at: datetime
    ends_at: datetime
    max_admissions: int

    def __post_init__(self) -> None:
        if not isinstance(self.experiment_id, str) or not self.experiment_id.strip():
            raise ValueError("experiment_id is required")
        floor = decimal_value(self.minimum_confidence, "minimum_confidence", allow_zero=False)
        if floor > ONE:
            raise ValueError("minimum_confidence must be between 0 and 1")
        object.__setattr__(self, "minimum_confidence", floor)
        buckets = frozenset(self.buckets)
        if not buckets or not all(isinstance(b, RiskBucket) for b in buckets):
            raise ValueError("buckets must be a non-empty set of RiskBucket")
        object.__setattr__(self, "buckets", buckets)
        for name in ("starts_at", "ends_at"):
            value = getattr(self, name)
            if not isinstance(value, datetime) or value.tzinfo is None:
                raise ValueError(f"{name} must be a timezone-aware datetime")
        if self.ends_at <= self.starts_at:
            raise ValueError("ends_at must be after starts_at")
        if (not isinstance(self.max_admissions, int) or isinstance(self.max_admissions, bool)
                or self.max_admissions <= 0):
            raise ValueError("max_admissions must be a positive integer")

    def is_open(self, now: datetime, admissions: int) -> bool:
        return self.starts_at <= now < self.ends_at and admissions < self.max_admissions


# registry v5.01, GRANT-EXP001-PAPER-CONFIDENCE-EXPERIMENT. Pinned here on
# purpose: no config file or environment variable may enable, extend or
# loosen it. Changing any value is a governed change.
EXP001_PAPER_CONFIDENCE_EXPERIMENT = ConfidenceFloorExperiment(
    experiment_id="EXP-001",
    minimum_confidence=Decimal("0.60"),
    buckets=frozenset({RiskBucket.MEDIUM, RiskBucket.HIGH}),
    starts_at=datetime(2026, 9, 28, 10, 0, tzinfo=UTC),
    ends_at=datetime(2026, 10, 12, 10, 0, tzinfo=UTC),
    max_admissions=50,
)


# Owner choice 2026-10-01 ("B ve C birlikte"): a second, smaller and stricter
# experiment than EXP-001. MEDIUM bucket only (HIGH stays at 0.80), floor
# 0.62 (above EXP-001's 0.60), 30 admissions, two weeks. Pinned like EXP-001;
# it is attached only when main.py names it, in PAPER only, and admissions are
# sized with the HIGH bucket's limits (EXPERIMENT_SIZING_BUCKET).
EXP002_PAPER_CONFIDENCE_EXPERIMENT = ConfidenceFloorExperiment(
    experiment_id="EXP-002",
    minimum_confidence=Decimal("0.62"),
    buckets=frozenset({RiskBucket.MEDIUM}),
    starts_at=datetime(2026, 10, 2, 0, 0, tzinfo=UTC),
    ends_at=datetime(2026, 10, 16, 0, 0, tzinfo=UTC),
    max_admissions=30,
)
PAPER_CONFIDENCE_EXPERIMENTS = {e.experiment_id: e for e in (EXP001_PAPER_CONFIDENCE_EXPERIMENT,
                                                             EXP002_PAPER_CONFIDENCE_EXPERIMENT)}


@dataclass(frozen=True)
class RiskPolicy:
    total_capital: Decimal
    cash_reserve_pct: Decimal = Decimal("0.20")
    max_position_pct: Decimal = Decimal("0.40")
    portfolio_exposure_pct: Decimal = Decimal("0.80")
    per_symbol_pct: Decimal = Decimal("0.40")
    concentration_pct: Decimal = Decimal("0.40")
    global_minimum_confidence: Decimal = Decimal("0.60")
    max_positions: int = 5
    max_daily_loss_amount: Decimal | None = None
    max_daily_loss_pct: Decimal | None = Decimal("0.05")
    # Audit finding F-3 (owner 2026-09-30): when True, the daily-loss gate also
    # counts the open positions' unrealized loss (RiskState.unrealized_pnl).
    # Unknown unrealized P&L then blocks new risk (fail closed). Default False
    # keeps the historical, realized-only behaviour byte-identical.
    count_unrealized_in_daily_loss: bool = False
    # S1 capital sleeves (owner "S1 onay" 2026-10-01; plan in
    # proposals/2026-09-29_staged_entries_and_sleeves_runtime_plan.md). When
    # True, a BUY is refused with SLEEVE_FULL if its bucket's open cost plus the
    # new allocation would exceed the bucket's share of equity. Default False
    # keeps today's behaviour byte-identical. Exits are never affected.
    sleeves_enabled: bool = False
    sleeve_shares: Mapping[str, Decimal] = field(default_factory=lambda: {
        "LOW": Decimal("0.50"), "MEDIUM": Decimal("0.35"), "HIGH": Decimal("0.15")})
    drawdown_warning_pct: Decimal = Decimal("0.05")
    drawdown_restrict_pct: Decimal = Decimal("0.10")
    drawdown_halt_pct: Decimal = Decimal("0.15")
    buckets: Mapping[RiskBucket, BucketPolicy] = field(default_factory=_default_buckets)
    version: str = "phase3-risk-v1"

    def __post_init__(self) -> None:
        object.__setattr__(self, "total_capital", decimal_value(self.total_capital, "total_capital", allow_zero=False))
        pct_names = (
            "cash_reserve_pct", "max_position_pct", "portfolio_exposure_pct",
            "per_symbol_pct", "concentration_pct", "global_minimum_confidence",
            "drawdown_warning_pct", "drawdown_restrict_pct", "drawdown_halt_pct",
        )
        for name in pct_names:
            value = decimal_value(getattr(self, name), name)
            if value > ONE:
                raise ValueError(f"{name} must be between 0 and 1")
            object.__setattr__(self, name, value)
        if not 0 <= self.drawdown_warning_pct <= self.drawdown_restrict_pct <= self.drawdown_halt_pct:
            raise ValueError("drawdown thresholds must be ordered warning <= restrict <= halt")
        if not isinstance(self.max_positions, int) or isinstance(self.max_positions, bool) or self.max_positions <= 0:
            raise ValueError("max_positions must be a positive integer")
        for name in ("max_daily_loss_amount", "max_daily_loss_pct"):
            raw = getattr(self, name)
            if raw is not None:
                value = decimal_value(raw, name, allow_zero=False)
                if name.endswith("pct") and value > ONE:
                    raise ValueError(f"{name} must be between 0 and 1")
                object.__setattr__(self, name, value)
        normalized: dict[RiskBucket, BucketPolicy] = {}
        for key, value in self.buckets.items():
            try:
                bucket = key if isinstance(key, RiskBucket) else RiskBucket(str(key).upper())
            except ValueError as exc:
                raise ValueError("invalid risk bucket policy") from exc
            if not isinstance(value, BucketPolicy):
                raise ValueError("bucket policies must be BucketPolicy values")
            normalized[bucket] = value
        if set(normalized) != set(RiskBucket):
            raise ValueError("LOW, MEDIUM, and HIGH bucket policies are required")
        object.__setattr__(self, "buckets", normalized)

    @property
    def reserved_capital(self) -> Decimal:
        with localcontext() as context:
            context.prec = RISK_CONTEXT_PRECISION
            context.rounding = ROUND_HALF_EVEN
            return self.total_capital * self.cash_reserve_pct

    @property
    def allocatable_capital(self) -> Decimal:
        with localcontext() as context:
            context.prec = RISK_CONTEXT_PRECISION
            context.rounding = ROUND_HALF_EVEN
            return self.total_capital - self.reserved_capital


@dataclass(frozen=True)
class BuyCapacityLimits:
    """The canonical BUY capacity ceilings for one symbol/bucket/committed state.

    Every field is exactly the limit ``RiskEngine.evaluate`` has always bound
    a BUY's ``approved_allocation`` by; this dataclass changes no formula and
    no numeric meaning, it only gives the existing limits one shared name and
    shape so a second authority (``PositionSizingService``) can bound its own
    proposal by the same ceilings without copying the formula text.
    """

    max_position: Decimal
    bucket_allocation: Decimal
    per_symbol: Decimal
    concentration: Decimal
    bucket_exposure_ceiling: Decimal
    portfolio_exposure: Decimal
    allocatable_capital: Decimal

    def as_tuple(self) -> tuple[Decimal, ...]:
        return (
            self.max_position,
            self.bucket_allocation,
            self.per_symbol,
            self.concentration,
            self.bucket_exposure_ceiling,
            self.portfolio_exposure,
            self.allocatable_capital,
        )


def derive_buy_capacity_limits(
    policy: RiskPolicy,
    bucket_policy: BucketPolicy,
    *,
    symbol_exposure: Decimal,
    committed_quote: Decimal,
) -> BuyCapacityLimits:
    """Derive the canonical BUY capacity limits for one admission evaluation.

    Pure and side-effect free: it reads only ``policy``, ``bucket_policy``,
    and the two exposure figures the caller already holds. ``RiskEngine.evaluate``
    and ``PositionSizingService.propose`` both call this, so a policy or
    exposure change moves both authorities' ceilings together and can never
    let the two drift apart.
    """

    with localcontext() as context:
        context.prec = RISK_CONTEXT_PRECISION
        context.rounding = ROUND_HALF_EVEN
        return BuyCapacityLimits(
            max_position=policy.total_capital * policy.max_position_pct,
            bucket_allocation=policy.total_capital * bucket_policy.max_allocation_pct,
            per_symbol=policy.total_capital * policy.per_symbol_pct - symbol_exposure,
            concentration=policy.total_capital * policy.concentration_pct - symbol_exposure,
            bucket_exposure_ceiling=policy.total_capital * bucket_policy.exposure_ceiling_pct - symbol_exposure,
            portfolio_exposure=policy.total_capital * policy.portfolio_exposure_pct - committed_quote,
            allocatable_capital=policy.allocatable_capital - committed_quote,
        )


@dataclass(frozen=True)
class PositionExposure:
    symbol: str
    base_quantity: Decimal
    execution_price: Decimal
    quote_exposure: Decimal
    # S1 capital sleeves: the bucket the position was opened under. None means
    # UNKNOWN (positions opened before the bucket was recorded); UNKNOWN counts
    # against every sleeve (audit F-1), so it can only refuse more.
    risk_bucket: str | None = None

    def __post_init__(self) -> None:
        symbol = str(self.symbol).strip().upper()
        if not symbol:
            raise ValueError("position symbol is required")
        base = decimal_value(self.base_quantity, "base_quantity", allow_zero=False)
        price = decimal_value(self.execution_price, "execution_price", allow_zero=False)
        quote = decimal_value(self.quote_exposure, "quote_exposure", allow_zero=False)
        if base * price != quote:
            raise ValueError("base quantity and quote exposure disagree")
        object.__setattr__(self, "symbol", symbol)
        object.__setattr__(self, "base_quantity", base)
        object.__setattr__(self, "execution_price", price)
        object.__setattr__(self, "quote_exposure", quote)


@dataclass(frozen=True)
class RiskState:
    positions: tuple[PositionExposure, ...] = ()
    committed_quote: Decimal = ZERO
    realized_daily_pnl: Decimal = ZERO
    peak_equity: Decimal = ZERO
    current_equity: Decimal = ZERO
    state_ready: bool = False
    accounting_day_utc: str = ""
    policy_version: str = ""
    # Mark-to-market P&L of open positions; None = not known (never guessed as 0).
    unrealized_pnl: Decimal | None = None

    def __post_init__(self) -> None:
        if self.unrealized_pnl is not None:
            if isinstance(self.unrealized_pnl, float):
                raise ValueError("unrealized_pnl must not be float")
            u = Decimal(str(self.unrealized_pnl))
            if not u.is_finite():
                raise ValueError("unrealized_pnl must be finite")
            object.__setattr__(self, "unrealized_pnl", u)
        committed = decimal_value(self.committed_quote, "committed_quote")
        peak = decimal_value(self.peak_equity, "peak_equity")
        current = decimal_value(self.current_equity, "current_equity")
        if isinstance(self.realized_daily_pnl, float):
            raise ValueError("realized_daily_pnl must not be float")
        try:
            pnl = self.realized_daily_pnl if isinstance(self.realized_daily_pnl, Decimal) else Decimal(str(self.realized_daily_pnl))
        except (InvalidOperation, ValueError, TypeError) as exc:
            raise ValueError("realized_daily_pnl is invalid") from exc
        if not pnl.is_finite():
            raise ValueError("realized_daily_pnl must be finite")
        position_total = sum((p.quote_exposure for p in self.positions), ZERO)
        if position_total != committed:
            raise ValueError("committed exposure and authoritative positions disagree")
        if self.state_ready:
            try:
                datetime.strptime(self.accounting_day_utc, "%Y-%m-%d")
            except (TypeError, ValueError) as exc:
                raise ValueError("valid UTC accounting day is required") from exc
            if peak <= ZERO or current <= ZERO or current > peak:
                raise ValueError("restored equity state is inconsistent")
            if not self.policy_version:
                raise ValueError("restored policy version is required")
        object.__setattr__(self, "committed_quote", committed)
        object.__setattr__(self, "realized_daily_pnl", pnl)
        object.__setattr__(self, "peak_equity", peak)
        object.__setattr__(self, "current_equity", current)


@dataclass(frozen=True)
class RiskRequest:
    symbol: str
    action: str
    confidence: Decimal
    requested_quote_allocation: Decimal
    execution_price: Decimal
    risk_bucket: RiskBucket | str
    base_quantity: Decimal | None = None
    reduce_only: bool = False


@dataclass(frozen=True)
class RiskDecision:
    status: RiskDecisionStatus
    reason_code: str
    approved_allocation: Decimal = ZERO
    gross_exposure: Decimal = ZERO
    available_capital: Decimal = ZERO
    reserved_capital: Decimal = ZERO
    daily_realized_pnl: Decimal = ZERO
    drawdown_amount: Decimal = ZERO
    drawdown_pct: Decimal = ZERO
    drawdown_level: DrawdownLevel = DrawdownLevel.NORMAL
    policy_version: str = ""
    experiment_id: str = ""

    @property
    def approved(self) -> bool:
        return self.status is RiskDecisionStatus.APPROVE

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status.value, "approved": self.approved,
            "reason_code": self.reason_code, "approved_allocation": str(self.approved_allocation),
            "gross_exposure": str(self.gross_exposure), "available_capital": str(self.available_capital),
            "reserved_capital": str(self.reserved_capital), "daily_realized_pnl": str(self.daily_realized_pnl),
            "drawdown_amount": str(self.drawdown_amount), "drawdown_pct": str(self.drawdown_pct),
            "drawdown_level": self.drawdown_level.value, "policy_version": self.policy_version,
            "experiment_id": self.experiment_id,
        }


class RiskEngine:
    """Pure fail-closed evaluator; it never reserves, executes, or enables LIVE."""

    VERSION = "3.0"

    def __init__(self, policy: RiskPolicy | None = None, **legacy: Any) -> None:
        if policy is None:
            total = legacy.pop("total_capital", None)
            if total is None:
                # Import compatibility only: no-state validation still returns
                # BLOCK_RECOVERY_REQUIRED, so this placeholder cannot authorize
                # financial execution or infer usable capital.
                total = Decimal("1")
            policy = RiskPolicy(total_capital=total)
        if legacy:
            raise ValueError(f"unsupported legacy risk settings: {', '.join(sorted(legacy))}")
        self.policy = policy
        self.approved_count = 0
        self.rejected_count = 0
        self.experiment: ConfidenceFloorExperiment | None = None
        self.experiment_admissions = 0
        self.experiment_closed_reason: str | None = None
        self._experiment_clock = lambda: datetime.now(UTC)
        self._experiment_lock = threading.Lock()

    def attach_experiment(self, experiment: ConfidenceFloorExperiment, *, prior_admissions: int,
                          clock: Any = None, admission_recorder: Any = None) -> None:
        """Attach a confidence-floor experiment; the caller restricts this to PAPER."""
        if not isinstance(experiment, ConfidenceFloorExperiment):
            raise ValueError("experiment must be a ConfidenceFloorExperiment")
        if not isinstance(prior_admissions, int) or isinstance(prior_admissions, bool) or prior_admissions < 0:
            raise ValueError("prior_admissions must be a non-negative integer")
        self.experiment = experiment
        self.experiment_admissions = prior_admissions
        # registry v5.17: called with the new count *before* an admission is
        # granted; if it raises, the admission is refused and the experiment
        # closes, so the durable count can never trail the granted count.
        self._experiment_recorder = admission_recorder
        if clock is not None:
            self._experiment_clock = clock

    def close_experiment(self, reason: str) -> None:
        """Close the attached experiment for the rest of this process; only tightens."""
        if self.experiment is not None and self.experiment_closed_reason is None:
            self.experiment_closed_reason = str(reason) or "CLOSED"

    def _experiment_floor(self, bucket: RiskBucket) -> Decimal | None:
        experiment = self.experiment
        if experiment is None or self.experiment_closed_reason is not None:
            return None
        if bucket not in experiment.buckets:
            return None
        if not experiment.is_open(self._experiment_clock(), self.experiment_admissions):
            return None
        return max(self.policy.global_minimum_confidence, experiment.minimum_confidence)

    def sizing_bucket(self, bucket: Any, confidence: Any) -> RiskBucket:
        """Bucket whose size limits apply to a BUY at ``confidence`` (registry v5.22).

        An admission that only the experiment floor would grant is sized with
        EXPERIMENT_SIZING_BUCKET's limits (owner: "Deney bitene kadar %10
        kalsın"), so the regime-derived bucket cannot enlarge experiment
        positions. PositionSizingService (via MarketLoop) and evaluate() both
        use this, so the proposal and the approval cannot disagree. Only ever
        returns an equal-or-stricter bucket.
        """
        bucket = RiskBucket(bucket)
        bucket_policy = self.policy.buckets[bucket]
        default_floor = max(self.policy.global_minimum_confidence, bucket_policy.minimum_confidence)
        if decimal_value(confidence, "confidence") >= default_floor:
            return bucket
        if self._experiment_floor(bucket) is None:
            return bucket
        return EXPERIMENT_SIZING_BUCKET

    def experiment_status(self) -> dict[str, Any] | None:
        experiment = self.experiment
        if experiment is None:
            return None
        return {
            "experiment_id": experiment.experiment_id,
            "active": (self.experiment_closed_reason is None
                       and experiment.is_open(self._experiment_clock(), self.experiment_admissions)),
            "closed_reason": self.experiment_closed_reason,
            "minimum_confidence": str(experiment.minimum_confidence),
            "buckets": sorted(b.value for b in experiment.buckets),
            "starts_at": experiment.starts_at.isoformat(),
            "ends_at": experiment.ends_at.isoformat(),
            "admissions": self.experiment_admissions,
            "max_admissions": experiment.max_admissions,
        }

    def _sleeve_check(self, bucket: str, allocation: Decimal, state: RiskState) -> str | None:
        """S1: per-bucket share of equity. Unknown inputs refuse (fail closed)."""
        share = self.policy.sleeve_shares.get(bucket)
        if share is None:
            return "SLEEVE_UNKNOWN_BUCKET"
        equity = state.current_equity if state.current_equity > ZERO else ZERO
        if equity <= ZERO:
            return "SLEEVE_EQUITY_UNKNOWN"
        used = ZERO
        for p in state.positions:
            pb = (p.risk_bucket or "").upper() or None
            # Audit 2026-10-01 F-1 (HIGH, NB-4): an UNKNOWN position counts against
            # EVERY sleeve. Counting it only against the smallest one freed the
            # sleeve it was really admitted under, so losing evidence loosened limits.
            if pb == bucket or pb not in self.policy.sleeve_shares:
                used += p.quote_exposure
        with localcontext() as context:
            context.prec = RISK_CONTEXT_PRECISION
            if used + allocation > equity * share:
                return "SLEEVE_FULL"
        return None

    def _decision(self, status: RiskDecisionStatus, reason: str, state: RiskState,
                  *, allocation: Decimal = ZERO, experiment_id: str = "") -> RiskDecision:
        with localcontext() as context:
            context.prec = RISK_CONTEXT_PRECISION
            context.rounding = ROUND_HALF_EVEN
            drawdown_amount = max(state.peak_equity - state.current_equity, ZERO)
            drawdown_pct = drawdown_amount / state.peak_equity if state.peak_equity > ZERO else ZERO
            gross = state.committed_quote
            available = max(self.policy.allocatable_capital - gross, ZERO)
        level = self._drawdown_level(drawdown_pct)
        return RiskDecision(status, reason, allocation, gross, available,
                            self.policy.reserved_capital, state.realized_daily_pnl,
                            drawdown_amount, drawdown_pct, level, self.policy.version,
                            experiment_id)

    def _drawdown_level(self, pct: Decimal) -> DrawdownLevel:
        if pct >= self.policy.drawdown_halt_pct:
            return DrawdownLevel.HALT_NEW_RISK
        if pct >= self.policy.drawdown_restrict_pct:
            return DrawdownLevel.RESTRICT
        if pct >= self.policy.drawdown_warning_pct:
            return DrawdownLevel.WARNING
        return DrawdownLevel.NORMAL

    def evaluate(self, request: RiskRequest, state: RiskState) -> RiskDecision:
        def reject(code: str, recovery: bool = False) -> RiskDecision:
            self.rejected_count += 1
            return self._decision(RiskDecisionStatus.BLOCK_RECOVERY_REQUIRED if recovery else RiskDecisionStatus.REJECT,
                                  code, state)

        if not isinstance(state, RiskState) or not state.state_ready:
            return reject("RISK_STATE_NOT_READY", True)
        if state.policy_version != self.policy.version:
            return reject("RISK_POLICY_STATE_MISMATCH", True)
        if state.accounting_day_utc != datetime.now(UTC).date().isoformat():
            return reject("RISK_ACCOUNTING_DAY_RECONCILIATION_REQUIRED", True)
        symbol = str(request.symbol).strip().upper()
        action = str(request.action).strip().upper()
        reducing = bool(request.reduce_only) and action == "SELL"
        if not symbol or action not in {"BUY", "SELL"}:
            return reject("INVALID_REQUEST")
        try:
            confidence = decimal_value(request.confidence, "confidence")
            allocation = decimal_value(request.requested_quote_allocation, "requested_quote_allocation", allow_zero=False)
            price = decimal_value(request.execution_price, "execution_price", allow_zero=False)
            # Analytical state only: conversion to an executable RiskBucket is
            # deferred past the risk-reduction path so a CRITICAL or
            # unsupported exit is not blocked for lacking a bucket it must
            # never have.
            risk_level = analytical_risk_level(request.risk_bucket)
            if confidence > ONE:
                raise ValueError("confidence out of range")
            if request.base_quantity is not None:
                quantity = decimal_value(request.base_quantity, "base_quantity", allow_zero=False)
                with localcontext() as context:
                    context.prec = RISK_CONTEXT_PRECISION
                    context.rounding = ROUND_HALF_EVEN
                    quantity_notional = quantity * price
                if quantity_notional != allocation:
                    return reject("QUANTITY_NOTIONAL_MISMATCH")
        except (ValueError, TypeError):
            return reject("INVALID_FINANCIAL_INPUT")

        symbol_positions = [p for p in state.positions if p.symbol == symbol]
        with localcontext() as context:
            context.prec = RISK_CONTEXT_PRECISION
            context.rounding = ROUND_HALF_EVEN
            symbol_exposure = sum((p.quote_exposure for p in symbol_positions), ZERO)
        if reducing:
            if not symbol_positions or allocation > symbol_exposure:
                return reject("INVALID_RISK_REDUCTION")
            self.approved_count += 1
            return self._decision(RiskDecisionStatus.APPROVE, "RISK_REDUCTION_APPROVED", state,
                                  allocation=allocation)
        if action != "BUY":
            return reject("NON_RISK_REDUCING_SELL")

        # New or increasing risk: CRITICAL is a valid upstream state that has
        # no executable bucket by policy, so it is rejected on its own terms
        # rather than resolved, aliased, or reported as malformed input.
        if risk_level in NON_EXECUTABLE_RISK_LEVELS:
            return reject("CRITICAL_RISK_NOT_EXECUTABLE")
        # An unsupported classification carries no policy at all, so there is
        # nothing to resolve it into; it fails closed on its own reason code
        # and stays distinguishable from CRITICAL and from malformed input.
        if risk_level == UNSUPPORTED_RISK_SENTINEL:
            return reject("UNSUPPORTED_RISK_LEVEL")

        bucket = RiskBucket(risk_level)
        bucket_policy = self.policy.buckets[bucket]
        if self.policy.sleeves_enabled:
            sleeve_reject = self._sleeve_check(bucket.value, allocation, state)
            if sleeve_reject:
                return reject(sleeve_reject)
        experiment_id = ""
        default_floor = max(self.policy.global_minimum_confidence, bucket_policy.minimum_confidence)
        if confidence < default_floor:
            experiment_floor = self._experiment_floor(bucket)
            if experiment_floor is None or confidence < experiment_floor:
                return reject("CONFIDENCE_BELOW_POLICY")
            experiment_id = self.experiment.experiment_id
        with localcontext() as context:
            context.prec = RISK_CONTEXT_PRECISION
            context.rounding = ROUND_HALF_EVEN
            loss = max(-state.realized_daily_pnl, ZERO)
            if self.policy.count_unrealized_in_daily_loss:
                if state.unrealized_pnl is None:
                    return reject("UNREALIZED_PNL_UNKNOWN")
                # Audit 2026-10-01 F-A (HIGH): only unrealized LOSSES count. A paper
                # gain on an open position must never offset a realized loss, or
                # F-3 ON would be looser than OFF.
                loss = max(-(state.realized_daily_pnl + min(state.unrealized_pnl, ZERO)), ZERO)
            daily_loss_ceiling = (
                self.policy.total_capital * self.policy.max_daily_loss_pct
                if self.policy.max_daily_loss_pct is not None else None
            )
            dd_pct = (max(state.peak_equity - state.current_equity, ZERO) / state.peak_equity
                      if state.peak_equity > ZERO else ZERO)
        if self.policy.max_daily_loss_amount is not None and loss >= self.policy.max_daily_loss_amount:
            return reject("DAILY_LOSS_LIMIT_BREACHED")
        if daily_loss_ceiling is not None and loss >= daily_loss_ceiling:
            return reject("DAILY_LOSS_LIMIT_BREACHED")
        level = self._drawdown_level(dd_pct)
        if level is DrawdownLevel.HALT_NEW_RISK:
            return reject("DRAWDOWN_HALT_NEW_RISK")
        if level is DrawdownLevel.RESTRICT:
            return reject("DRAWDOWN_RESTRICT_NEW_RISK")
        if symbol_positions:
            return reject("DUPLICATE_OPEN_POSITION")
        if len(state.positions) >= self.policy.max_positions:
            return reject("MAX_POSITIONS_REACHED")

        # Experiment admissions are sized with EXPERIMENT_SIZING_BUCKET's limits
        # (registry v5.22); sizing_bucket() gives the sizer the same answer.
        capacity_policy = (
            self.policy.buckets[EXPERIMENT_SIZING_BUCKET] if experiment_id else bucket_policy
        )
        capacity = derive_buy_capacity_limits(
            self.policy, capacity_policy,
            symbol_exposure=symbol_exposure, committed_quote=state.committed_quote,
        )
        approved = min((allocation, *capacity.as_tuple()))
        if approved <= ZERO:
            return reject("INSUFFICIENT_ALLOCATABLE_CAPITAL")
        if approved < allocation:
            return reject("REQUEST_EXCEEDS_RISK_LIMIT")
        if experiment_id:
            # Re-check and count atomically so concurrent evaluations cannot
            # overshoot the cap or slip past a close between check and count.
            with self._experiment_lock:
                if self._experiment_floor(bucket) is None:
                    return reject("CONFIDENCE_BELOW_POLICY")
                recorder = getattr(self, "_experiment_recorder", None)
                if recorder is not None:
                    try:
                        recorder(experiment_id, self.experiment_admissions + 1)
                    except Exception:
                        self.close_experiment("ADMISSION_LEDGER_WRITE_FAILED")
                        return reject("CONFIDENCE_BELOW_POLICY")
                self.experiment_admissions += 1
        self.approved_count += 1
        return self._decision(RiskDecisionStatus.APPROVE, "RISK_APPROVED", state, allocation=approved,
                              experiment_id=experiment_id)

    def validate(self, decision: Mapping[str, Any], state: RiskState | None = None) -> dict[str, Any]:
        """Compatibility adapter; absent authoritative state deliberately fails closed."""
        try:
            request = RiskRequest(
                symbol=decision.get("symbol", ""), action=decision.get("action", ""),
                confidence=decision.get("confidence", ZERO),
                requested_quote_allocation=decision.get("amount", decision.get("requested_quote_allocation", ZERO)),
                execution_price=decision.get("price", ZERO), risk_bucket=decision.get("risk", "MEDIUM"),
                base_quantity=decision.get("base_quantity"), reduce_only=bool(decision.get("reduce_only", False)),
            )
            result = self.evaluate(request, state or RiskState())
        except Exception:
            result = self._decision(RiskDecisionStatus.REJECT, "INVALID_REQUEST", state or RiskState())
        return result.to_dict()

    def approve(self, decision: Mapping[str, Any], state: RiskState | None = None) -> dict[str, Any]:
        """Historical alias retained as the same fail-closed adapter."""
        return self.validate(decision, state)

    def status(self) -> dict[str, Any]:
        return {"version": self.VERSION, "policy_version": self.policy.version,
                "approved": self.approved_count, "blocked": self.rejected_count,
                "experiment": self.experiment_status()}
