"""Block 5C — pure, BUY-only upstream position-sizing proposal authority.

``PositionSizingService`` is the single component authorized to turn durable
free capital and the already-authorized ``RiskPolicy`` bucket allocation
percentage into a proposed BUY quote allocation. It never approves anything;
authority stays exactly:

    PositionSizingService  -> PROPOSES
    RiskEngine              -> APPROVES / REJECTS
    risk_check                -> ADMITS / RESERVES
    Execution                  -> EXECUTES

The service is pure and deterministic: no I/O, no reservation, no execution,
no portfolio mutation, and no write to ``approved_quote_allocation`` (that
field stays canonical and stays ``risk_check``'s alone to write). SELL and
reduce-only requests never reach this module; Package 5B's exact
durable-exposure exit semantics are untouched and entirely outside this
service's authority.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import ROUND_DOWN, Decimal, localcontext
from enum import Enum
import hashlib
import json
from typing import Any, Mapping

from core.risk_engine import (
    NON_EXECUTABLE_RISK_LEVELS,
    RiskBucket,
    RiskPolicy,
    UNSUPPORTED_RISK_SENTINEL,
    analytical_risk_level,
    decimal_value,
    derive_buy_capacity_limits,
)

ZERO = Decimal("0")


class SizingStatus(str, Enum):
    PROPOSED = "PROPOSED"
    REFUSED = "REFUSED"


@dataclass(frozen=True)
class SizingInputs:
    """One BUY sizing request, resolved against durable runtime state.

    Every Decimal field is a durable read the caller already made - this
    service performs no I/O of its own. ``risk_bucket`` is resolved onto the
    same analytical taxonomy ``RiskEngine.evaluate`` resolves it onto, so
    both authorities classify an identical request identically.
    """

    request_id: str
    symbol: str
    risk_bucket: RiskBucket | str
    durable_free_quote_capital: Decimal
    symbol_exposure: Decimal
    committed_quote: Decimal

    def __post_init__(self) -> None:
        request_id = str(self.request_id).strip()
        if not request_id:
            raise ValueError("request_id is required")
        symbol = str(self.symbol).strip().upper()
        if not symbol:
            raise ValueError("symbol is required")
        risk_level = analytical_risk_level(self.risk_bucket)

        object.__setattr__(self, "request_id", request_id)
        object.__setattr__(self, "symbol", symbol)
        object.__setattr__(self, "risk_bucket", risk_level)
        object.__setattr__(
            self,
            "durable_free_quote_capital",
            decimal_value(self.durable_free_quote_capital, "durable_free_quote_capital"),
        )
        object.__setattr__(
            self,
            "symbol_exposure",
            decimal_value(self.symbol_exposure, "symbol_exposure"),
        )
        object.__setattr__(
            self,
            "committed_quote",
            decimal_value(self.committed_quote, "committed_quote"),
        )


@dataclass(frozen=True)
class SizingProposal:
    """The service's output: a proposal only, never an approval.

    ``provenance`` carries exact decimal-string serialization for every
    authoritative financial value behind ``proposed_quote_allocation``, plus
    a deterministic ``inputs_digest`` that lets a caller detect a replayed
    request whose sizing inputs have since changed.
    """

    status: SizingStatus
    reason_code: str
    proposed_quote_allocation: Decimal = ZERO
    provenance: Mapping[str, Any] = field(default_factory=dict)


class PositionSizingService:
    """Pure, deterministic, BUY-only proposer of quote-currency allocation.

    Given durable free capital and the RiskPolicy bucket allocation
    percentage already authorized for the request's risk classification,
    this proposes a candidate allocation bounded downward by the same
    per-symbol, position, concentration and portfolio capacities RiskEngine
    itself enforces - never by an invented ceiling, a confidence multiplier,
    or a legacy sizing ladder. RiskEngine remains the sole approve/reject
    authority over whatever this proposes.
    """

    AUTHORITY = "PositionSizingService"

    def __init__(self, policy: RiskPolicy) -> None:
        if not isinstance(policy, RiskPolicy):
            raise ValueError("policy must be a RiskPolicy")
        self.policy = policy

    def propose(self, inputs: SizingInputs) -> SizingProposal:
        if not isinstance(inputs, SizingInputs):
            raise ValueError("inputs must be a SizingInputs instance")

        base_provenance = {
            "authority": self.AUTHORITY,
            "policy_version": self.policy.version,
            "risk_bucket": inputs.risk_bucket,
            "durable_free_quote_capital": format(inputs.durable_free_quote_capital, "f"),
            "symbol_exposure": format(inputs.symbol_exposure, "f"),
            "committed_quote": format(inputs.committed_quote, "f"),
        }

        # CRITICAL is a valid upstream state with no executable bucket by
        # policy - the same reason RiskEngine refuses new risk carrying it -
        # so there is no bucket percentage to propose against.
        if inputs.risk_bucket in NON_EXECUTABLE_RISK_LEVELS:
            return SizingProposal(
                SizingStatus.REFUSED,
                "CRITICAL_RISK_NOT_EXECUTABLE",
                ZERO,
                {**base_provenance, "inputs_digest": self._inputs_digest(inputs), "proposed_quote_allocation": "0"},
            )

        # An unsupported classification carries no policy at all.
        if inputs.risk_bucket == UNSUPPORTED_RISK_SENTINEL:
            return SizingProposal(
                SizingStatus.REFUSED,
                "UNSUPPORTED_RISK_LEVEL",
                ZERO,
                {**base_provenance, "inputs_digest": self._inputs_digest(inputs), "proposed_quote_allocation": "0"},
            )

        bucket = RiskBucket(inputs.risk_bucket)
        bucket_policy = self.policy.buckets[bucket]
        basis_pct = bucket_policy.max_allocation_pct

        with localcontext() as context:
            context.rounding = ROUND_DOWN

            # The same canonical BUY capacity ceilings RiskEngine.evaluate()
            # itself enforces (Block 5C M1/M2): deriving them from the one
            # shared helper is what guarantees a proposal this service
            # considers fine can never exceed a limit RiskEngine will
            # actually apply, without copying any of RiskEngine's formulas.
            capacity = derive_buy_capacity_limits(
                self.policy, bucket_policy,
                symbol_exposure=inputs.symbol_exposure,
                committed_quote=inputs.committed_quote,
            )

            # The sizer's own desired-size formula: how much of the actually
            # spendable durable cash this risk bucket is authorized to
            # deploy. It is bounded downward by every canonical capacity
            # ceiling above and by the durable cash itself, never raised to
            # meet any of them.
            candidate = inputs.durable_free_quote_capital * basis_pct

            proposed = min(candidate, *capacity.as_tuple(), inputs.durable_free_quote_capital)

        capacity_provenance = {
            "basis_pct": format(basis_pct, "f"),
            "remaining_bucket_allocation_capacity": format(capacity.bucket_allocation, "f"),
            "remaining_bucket_exposure_ceiling_capacity": format(capacity.bucket_exposure_ceiling, "f"),
            "remaining_position_capacity": format(capacity.max_position, "f"),
            "remaining_symbol_capacity": format(capacity.per_symbol, "f"),
            "remaining_concentration_capacity": format(capacity.concentration, "f"),
            "remaining_portfolio_capacity": format(capacity.portfolio_exposure, "f"),
            "remaining_allocatable_capital_capacity": format(capacity.allocatable_capital, "f"),
        }

        provenance = {
            **base_provenance,
            **capacity_provenance,
            "inputs_digest": self._inputs_digest(inputs, extra=capacity_provenance),
            "proposed_quote_allocation": format(proposed, "f") if proposed > ZERO else "0",
        }

        if proposed <= ZERO:
            return SizingProposal(SizingStatus.REFUSED, "NON_POSITIVE_PROPOSAL", ZERO, provenance)

        return SizingProposal(SizingStatus.PROPOSED, "SIZING_PROPOSED", proposed, provenance)

    def _inputs_digest(self, inputs: SizingInputs, *, extra: Mapping[str, str] | None = None) -> str:
        """Seal every effective input capable of changing ``proposed_quote_allocation``.

        The resolved capacity ceilings passed in ``extra`` (Block 5C H1) are
        exactly the terms ``propose()`` actually mins over, so any change to
        ``total_capital``, a bucket or policy percentage, or either exposure
        figure changes one of those ceilings and therefore changes this
        digest - without the digest needing to separately enumerate every
        raw ``RiskPolicy`` field.
        """
        canonical: dict[str, Any] = {
            "request_id": inputs.request_id,
            "symbol": inputs.symbol,
            "risk_level": inputs.risk_bucket,
            "policy_version": self.policy.version,
            "durable_free_quote_capital": format(inputs.durable_free_quote_capital, "f"),
            "symbol_exposure": format(inputs.symbol_exposure, "f"),
            "committed_quote": format(inputs.committed_quote, "f"),
        }
        if extra:
            canonical.update(extra)
        payload = json.dumps(canonical, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()
