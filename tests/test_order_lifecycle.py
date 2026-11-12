"""Order state machine: terminal is final, DENIED never executes, UNKNOWN is reconciled not failed, fills idempotent."""

from decimal import Decimal as D

import pytest

from core.order_lifecycle import Order, OrderLifecycleError


def submitted(q="10"):
    o = Order("o1", D(q))
    o.transition("VALIDATED", "risk ok")
    o.transition("SUBMITTED", "sent")
    return o


def test_partial_then_full_fill_and_replayed_fill_ignored():
    o = submitted()
    assert o.apply_fill("f1", D("4")) and o.status == "PARTIALLY_FILLED"
    assert o.apply_fill("f1", D("4")) is False and o.filled == D("4")   # duplicate event
    assert o.apply_fill("f2", D("6")) and o.status == "FILLED"
    with pytest.raises(OrderLifecycleError, match="terminal"):
        o.transition("CANCELLED", "late cancel")


def test_overfill_and_bad_quantities_rejected():
    o = submitted()
    with pytest.raises(OrderLifecycleError, match="overfill"):
        o.apply_fill("f1", D("11"))
    for bad in (D("0"), D("-1"), D("NaN")):
        with pytest.raises(OrderLifecycleError):
            o.apply_fill("fx", bad)
    with pytest.raises(OrderLifecycleError):
        Order("o2", D("Infinity"))


def test_denied_can_never_execute():
    o = Order("o1", D("1"))
    o.transition("DENIED", "risk rejected")
    for nxt in ("SUBMITTED", "ACKNOWLEDGED", "FILLED"):
        with pytest.raises(OrderLifecycleError):
            o.transition(nxt, "x")


def test_unknown_is_reconciled_not_failed():
    o = submitted()
    o.transition("UNKNOWN", "timeout after send")
    for bad in ("REJECTED", "FILLED", "CANCELLED"):
        with pytest.raises(OrderLifecycleError):
            o.transition(bad, "guess")
    o.transition("RECONCILING", "query venue")
    assert o.apply_fill("f1", D("10")) and o.status == "FILLED"


def test_filled_requires_full_quantity():
    o = submitted()
    with pytest.raises(OrderLifecycleError, match="full quantity"):
        o.transition("FILLED", "claimed")


def test_cancel_fill_race_late_fill_is_recorded_not_dropped():
    o = submitted()
    o.transition("ACKNOWLEDGED", "venue ack")
    o.transition("PENDING_CANCEL", "cancel sent")
    o.transition("CANCELLED", "venue cancelled")
    assert o.apply_fill("late", D("10")) and o.status == "FILLED" and o.filled == D("10")
    assert any("LATE_FILL_AFTER_CANCEL" in h[1] for h in o.history)


def test_denied_and_rejected_never_accept_fills():
    o = Order("o1", D("1"))
    o.transition("DENIED", "risk")
    with pytest.raises(OrderLifecycleError):
        o.apply_fill("f", D("1"))
