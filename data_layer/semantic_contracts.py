"""Phase-2 financial persistence semantics; no runtime wiring lives here."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from enum import Enum

from .models import decimal_text, normalize_symbol, utc_text, validate_id


class OrderState(str, Enum):
    NEW = "NEW"
    ACCEPTED = "ACCEPTED"
    PARTIALLY_FILLED = "PARTIALLY_FILLED"
    FILLED = "FILLED"
    CANCELLED = "CANCELLED"
    REJECTED = "REJECTED"


TERMINAL_ORDER_STATES = frozenset({OrderState.FILLED, OrderState.CANCELLED, OrderState.REJECTED})
ORDER_TRANSITIONS = {
    OrderState.NEW: frozenset({OrderState.ACCEPTED, OrderState.REJECTED, OrderState.CANCELLED}),
    OrderState.ACCEPTED: frozenset({OrderState.PARTIALLY_FILLED, OrderState.FILLED, OrderState.CANCELLED, OrderState.REJECTED}),
    OrderState.PARTIALLY_FILLED: frozenset({OrderState.PARTIALLY_FILLED, OrderState.FILLED, OrderState.CANCELLED}),
    OrderState.FILLED: frozenset(),
    OrderState.CANCELLED: frozenset(),
    OrderState.REJECTED: frozenset(),
}


def validate_order_transition(current: OrderState | str, target: OrderState | str) -> bool:
    """Return False for an exact duplicate event; raise for an invalid mutation."""
    current_state, target_state = OrderState(current), OrderState(target)
    if current_state == target_state:
        return False
    if target_state not in ORDER_TRANSITIONS[current_state]:
        raise ValueError(f"invalid order transition: {current_state.value}->{target_state.value}")
    return True


class PersistenceBoundary(str, Enum):
    PRE_SIDE_EFFECT = "PRE_SIDE_EFFECT"
    SIDE_EFFECT_ATTEMPTED = "SIDE_EFFECT_ATTEMPTED"
    SIDE_EFFECT_CONFIRMED = "SIDE_EFFECT_CONFIRMED"
    SIDE_EFFECT_INDETERMINATE = "SIDE_EFFECT_INDETERMINATE"
    RECONCILIATION_REQUIRED = "RECONCILIATION_REQUIRED"
    DB_PERSISTENCE_PENDING = "DB_PERSISTENCE_PENDING"
    DB_PERSISTED = "DB_PERSISTED"
    TERMINAL_SUCCESS = "TERMINAL_SUCCESS"
    TERMINAL_FAILURE = "TERMINAL_FAILURE"


class RecoveryAction(str, Enum):
    READY = "READY"
    RECONCILE = "RECONCILE"
    FAIL_CLOSED = "FAIL_CLOSED"


def startup_recovery_action(*, journal_valid: bool, unresolved_journal: bool,
                            idempotency_valid: bool, relational_valid: bool,
                            sources_agree: bool) -> RecoveryAction:
    """Fail closed on corruption; reconcile ambiguity; never fall back to empty."""
    if not journal_valid or not idempotency_valid or not relational_valid:
        return RecoveryAction.FAIL_CLOSED
    if unresolved_journal or not sources_agree:
        return RecoveryAction.RECONCILE
    return RecoveryAction.READY


@dataclass(frozen=True, slots=True)
class PositionPersistenceDTO:
    """Long-only canonical projection of PositionController financial units."""

    position_id: str
    symbol: str
    base_quantity: Decimal
    quote_exposure: Decimal
    average_entry_price: Decimal
    realized_pnl_quote: Decimal
    status: str
    updated_at: str
    direction: str = "LONG"

    def __post_init__(self) -> None:
        object.__setattr__(self, "position_id", validate_id(self.position_id, "position_id"))
        object.__setattr__(self, "symbol", normalize_symbol(self.symbol))
        for name in ("base_quantity", "quote_exposure", "average_entry_price"):
            object.__setattr__(self, name, Decimal(decimal_text(getattr(self, name), name, nonnegative=True)))
        object.__setattr__(self, "realized_pnl_quote", Decimal(decimal_text(self.realized_pnl_quote, "realized_pnl_quote")))
        object.__setattr__(self, "updated_at", utc_text(self.updated_at))
        if self.direction != "LONG":
            raise ValueError("canonical runtime has no evidenced SHORT opening path")
        if self.status not in {"OPEN", "CLOSED"}:
            raise ValueError("invalid position status")
        if self.status == "OPEN" and (self.base_quantity <= 0 or self.quote_exposure <= 0 or self.average_entry_price <= 0):
            raise ValueError("open position financial values must be positive")
        if self.status == "CLOSED" and (self.base_quantity != 0 or self.quote_exposure != 0):
            raise ValueError("closed position must have zero remaining quantity and exposure")
        if self.base_quantity and self.base_quantity * self.average_entry_price != self.quote_exposure:
            raise ValueError("base quantity and quote exposure disagree")

