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
from decimal import Decimal, InvalidOperation
from datetime import UTC, datetime
from enum import Enum
from typing import Any, Mapping


ZERO = Decimal("0")
ONE = Decimal("1")


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


def _default_buckets() -> dict[RiskBucket, BucketPolicy]:
    return {
        RiskBucket.LOW: BucketPolicy(Decimal("0.40"), Decimal("0.60"), Decimal("0.60")),
        RiskBucket.MEDIUM: BucketPolicy(Decimal("0.25"), Decimal("0.70"), Decimal("0.40")),
        RiskBucket.HIGH: BucketPolicy(Decimal("0.10"), Decimal("0.80"), Decimal("0.20")),
    }


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
        return self.total_capital * self.cash_reserve_pct

    @property
    def allocatable_capital(self) -> Decimal:
        return self.total_capital - self.reserved_capital


@dataclass(frozen=True)
class PositionExposure:
    symbol: str
    base_quantity: Decimal
    execution_price: Decimal
    quote_exposure: Decimal

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

    def __post_init__(self) -> None:
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

    def _decision(self, status: RiskDecisionStatus, reason: str, state: RiskState,
                  *, allocation: Decimal = ZERO) -> RiskDecision:
        drawdown_amount = max(state.peak_equity - state.current_equity, ZERO)
        drawdown_pct = drawdown_amount / state.peak_equity if state.peak_equity > ZERO else ZERO
        level = self._drawdown_level(drawdown_pct)
        gross = state.committed_quote
        available = max(self.policy.allocatable_capital - gross, ZERO)
        return RiskDecision(status, reason, allocation, gross, available,
                            self.policy.reserved_capital, state.realized_daily_pnl,
                            drawdown_amount, drawdown_pct, level, self.policy.version)

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
                if quantity * price != allocation:
                    return reject("QUANTITY_NOTIONAL_MISMATCH")
        except (ValueError, TypeError):
            return reject("INVALID_FINANCIAL_INPUT")

        symbol_positions = [p for p in state.positions if p.symbol == symbol]
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

        bucket_policy = self.policy.buckets[RiskBucket(risk_level)]
        if confidence < max(self.policy.global_minimum_confidence, bucket_policy.minimum_confidence):
            return reject("CONFIDENCE_BELOW_POLICY")
        loss = max(-state.realized_daily_pnl, ZERO)
        if self.policy.max_daily_loss_amount is not None and loss >= self.policy.max_daily_loss_amount:
            return reject("DAILY_LOSS_LIMIT_BREACHED")
        if self.policy.max_daily_loss_pct is not None and loss >= self.policy.total_capital * self.policy.max_daily_loss_pct:
            return reject("DAILY_LOSS_LIMIT_BREACHED")
        dd_pct = (max(state.peak_equity - state.current_equity, ZERO) / state.peak_equity
                  if state.peak_equity > ZERO else ZERO)
        level = self._drawdown_level(dd_pct)
        if level is DrawdownLevel.HALT_NEW_RISK:
            return reject("DRAWDOWN_HALT_NEW_RISK")
        if level is DrawdownLevel.RESTRICT:
            return reject("DRAWDOWN_RESTRICT_NEW_RISK")
        if symbol_positions:
            return reject("DUPLICATE_OPEN_POSITION")
        if len(state.positions) >= self.policy.max_positions:
            return reject("MAX_POSITIONS_REACHED")

        limits = (
            self.policy.total_capital * self.policy.max_position_pct,
            self.policy.total_capital * bucket_policy.max_allocation_pct,
            self.policy.total_capital * self.policy.per_symbol_pct - symbol_exposure,
            self.policy.total_capital * self.policy.concentration_pct - symbol_exposure,
            self.policy.total_capital * bucket_policy.exposure_ceiling_pct - symbol_exposure,
            self.policy.total_capital * self.policy.portfolio_exposure_pct - state.committed_quote,
            self.policy.allocatable_capital - state.committed_quote,
        )
        approved = min((allocation, *limits))
        if approved <= ZERO:
            return reject("INSUFFICIENT_ALLOCATABLE_CAPITAL")
        if approved < allocation:
            return reject("REQUEST_EXCEEDS_RISK_LIMIT")
        self.approved_count += 1
        return self._decision(RiskDecisionStatus.APPROVE, "RISK_APPROVED", state, allocation=approved)

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
                "approved": self.approved_count, "blocked": self.rejected_count}
