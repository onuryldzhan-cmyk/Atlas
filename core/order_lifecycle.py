"""Canonical order state machine (owner MEGA TASK 4 §9; compared with NautilusTrader's OrderStatus model).

Pure and not yet wired: ExecutionManager keeps its current journal / idempotency
authority. This module fixes the rules any wiring must obey:

* terminal states never change (FILLED, REJECTED, CANCELLED, EXPIRED, DENIED);
* DENIED (refused by Atlas's own risk before submission) can never become
  SUBMITTED / ACKNOWLEDGED / FILLED - the NautilusTrader rule;
* UNKNOWN is never treated as failed: it can only move to RECONCILING, and
  RECONCILING only to a venue-confirmed state;
* a CANCELLED order can still receive a late fill (the cancel / fill race is
  a real venue behaviour; NautilusTrader models Canceled -> Filled for the
  same reason). The fill is recorded, never dropped;
* PENDING_CANCEL is in flight: fills and an ACKNOWLEDGED (cancel refused)
  are still possible;
* filled quantity is monotonic, Decimal, and never exceeds the order quantity;
* an event that repeats the same fill id is ignored (idempotent).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal

TERMINAL = frozenset({"FILLED", "REJECTED", "CANCELLED", "EXPIRED", "DENIED"})
TRANSITIONS: dict[str, frozenset[str]] = {
    "CREATED": frozenset({"VALIDATED", "DENIED"}),
    "VALIDATED": frozenset({"SUBMITTED", "DENIED"}),
    "SUBMITTED": frozenset({"ACKNOWLEDGED", "REJECTED", "PARTIALLY_FILLED", "FILLED", "UNKNOWN"}),
    "ACKNOWLEDGED": frozenset({"PARTIALLY_FILLED", "FILLED", "PENDING_CANCEL", "CANCELLED", "EXPIRED", "UNKNOWN"}),
    "PARTIALLY_FILLED": frozenset({"PARTIALLY_FILLED", "FILLED", "PENDING_CANCEL", "CANCELLED", "EXPIRED", "UNKNOWN"}),
    "PENDING_CANCEL": frozenset({"CANCELLED", "ACKNOWLEDGED", "PARTIALLY_FILLED", "FILLED", "EXPIRED", "UNKNOWN"}),
    "UNKNOWN": frozenset({"RECONCILING"}),
    "RECONCILING": frozenset({"ACKNOWLEDGED", "PARTIALLY_FILLED", "FILLED", "REJECTED", "CANCELLED", "EXPIRED"}),
}
STATES = frozenset(TRANSITIONS) | TERMINAL


class OrderLifecycleError(ValueError):
    pass


@dataclass
class Order:
    order_id: str
    quantity: Decimal
    status: str = "CREATED"
    filled: Decimal = Decimal("0")
    fill_ids: set[str] = field(default_factory=set)
    history: list[tuple[str, str]] = field(default_factory=list)

    def __post_init__(self) -> None:
        if not isinstance(self.quantity, Decimal) or not self.quantity.is_finite() or self.quantity <= 0:
            raise OrderLifecycleError("quantity must be a positive finite Decimal")

    def transition(self, new: str, reason: str) -> None:
        if new not in STATES:
            raise OrderLifecycleError(f"unknown state {new}")
        late_fill = self.status == "CANCELLED" and new in ("PARTIALLY_FILLED", "FILLED") and getattr(self, "_applying_fill", False)
        if late_fill:
            self.history.append((self.status, new + " (LATE_FILL_AFTER_CANCEL)"))
            # a partially filled then cancelled order stays CANCELLED for its remainder
            self.status = "FILLED" if self.filled == self.quantity else "CANCELLED"
            return
        if self.status in TERMINAL:
            raise OrderLifecycleError(f"{self.order_id} is terminal ({self.status})")
        if new not in TRANSITIONS[self.status]:
            raise OrderLifecycleError(f"illegal {self.status} -> {new}")
        if new == "FILLED" and self.filled != self.quantity:
            raise OrderLifecycleError("FILLED requires the full quantity to be filled")
        self.history.append((self.status, new))
        self.status = new

    def apply_fill(self, fill_id: str, qty: Decimal) -> bool:
        """Record a venue fill; returns False for a replayed fill id (no double count)."""
        if fill_id in self.fill_ids:
            return False
        if not isinstance(qty, Decimal) or not qty.is_finite() or qty <= 0:
            raise OrderLifecycleError("fill quantity must be a positive finite Decimal")
        if self.filled + qty > self.quantity:
            raise OrderLifecycleError("overfill: fills exceed order quantity")
        if self.status not in ("SUBMITTED", "ACKNOWLEDGED", "PARTIALLY_FILLED", "PENDING_CANCEL", "RECONCILING", "CANCELLED"):
            raise OrderLifecycleError(f"fill not allowed in {self.status}")
        self.fill_ids.add(fill_id)
        self.filled += qty
        self._applying_fill = True  # audit A-2: only a real fill may take the late-fill path
        try:
            self.transition("FILLED" if self.filled == self.quantity else "PARTIALLY_FILLED", f"fill {fill_id}")
        finally:
            self._applying_fill = False
        return True
