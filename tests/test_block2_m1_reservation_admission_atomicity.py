"""Block-2 M-1: reservation and risk-admission must be atomic.

A canonical-approved BUY must not leave a stale capital reservation or a
stale `_risk_admissions` entry behind when a later compatibility gate
rejects the request.

The reject-capable gate that proves this is the position-limit check (T1,
T7, T9). Block-5B withdrew the capital-manager risk check: CapitalManager no
longer holds admission authority over a canonical RiskDecision, so T2 now
pins that demotion instead of a rollback it can no longer trigger. The
rollback invariant itself is unchanged and still proven by T1/T4/T7/T9.
"""

from decimal import Decimal
from datetime import UTC, datetime
import threading

import pytest

from core.risk_engine import PositionExposure, RiskEngine, RiskPolicy, RiskState
from core.execution_manager import ExecutionManager
from core.execution_models import ExecutionRequest
from core.capital_reservation import CapitalReservationLedger
from core.risk_state_store import RestoredRiskState


D = Decimal


def policy(**changes):
    values = {"total_capital": D("1000")}
    values.update(changes)
    return RiskPolicy(**values)


def position(symbol="BTCUSDT", quote="100", price="10"):
    return PositionExposure(symbol, D(quote) / D(price), D(price), D(quote))


def state(*positions, pnl="0", peak="1000", equity="1000", ready=True):
    return RiskState(tuple(positions), sum((p.quote_exposure for p in positions), D("0")),
                     D(pnl), D(peak), D(equity), ready,
                     datetime.now(UTC).date().isoformat(), "block2-m1-v1")


class MemoryStore:
    def __init__(self, initial=()): self.items = tuple(initial); self.fail = False
    def load(self): return self.items
    def save(self, items):
        if self.fail: raise OSError("save failed")
        self.items = tuple(items)


class MemoryRiskStateStore:
    def load(self, *, expected_policy_version, today_utc):
        return RestoredRiskState(today_utc, D("0"), D("1000"), D("1000"), expected_policy_version)


class DenyingPositionController:
    """Always rejects position limit checks (compatibility gate)."""
    def can_open(self, symbol):
        return False


class DenyingCapitalManager:
    """Rejects everything it is asked - and after 5B it is asked nothing."""
    def validate_execution(self, request_dict, market_state):
        return {"approved": False, "reason": "CAPITAL_RISK_CHECK_TRIPPED"}

    def calculate_position_size(self, *args, **kwargs):
        return 1


def ledger(total="800"):
    return CapitalReservationLedger(MemoryStore(), D(total))


def execution_manager(*, position_controller=None, capital_manager=None, reservations=None):
    manager = ExecutionManager.__new__(ExecutionManager)
    manager.risk_engine = RiskEngine(policy())
    manager.reservation_ledger = reservations if reservations is not None else ledger()
    manager.risk_state_store = MemoryRiskStateStore()
    # No durable portfolio book is configured here, so the supplied
    # RiskState remains the position authority for these unit contracts.
    manager.portfolio_foundation = None
    manager.position_controller = position_controller
    manager.capital_manager = capital_manager
    manager.last_risk_decision = None
    manager._risk_admissions = {}
    manager.mode = "PAPER"
    manager.event_bus = None
    manager._lock = threading.RLock()
    manager.errors = []
    return manager


def buy_request(request_id, amount="100"):
    return ExecutionRequest("BTCUSDT", "BUY", 10, amount, confidence=90, risk="HIGH",
                            request_id=request_id)


def reduce_only_sell(request_id, amount="100"):
    return ExecutionRequest("BTCUSDT", "SELL", 10, amount, confidence=90, risk="HIGH",
                            request_id=request_id, reduce_only=True)


# --------------------------------------------------------------------------
# T1 — POSITION_LIMIT rollback
# --------------------------------------------------------------------------

def test_position_limit_rejection_leaves_no_reservation_or_admission():
    manager = execution_manager(position_controller=DenyingPositionController())
    before = manager.reservation_ledger.active_reserved_capital()

    result = manager.risk_check(buy_request("r1"), state())

    assert result["approved"] is False
    assert result["reason"] == "POSITION_LIMIT"
    assert manager.reservation_ledger.active_reserved_capital() == before
    assert manager.reservation_ledger.get("r1") is None
    assert "r1" not in manager._risk_admissions


def test_position_limit_rejection_does_not_accumulate_across_repeats():
    manager = execution_manager(position_controller=DenyingPositionController())
    before = manager.reservation_ledger.active_reserved_capital()

    for i in range(6):
        result = manager.risk_check(buy_request(f"r{i}"), state())
        assert result["reason"] == "POSITION_LIMIT"

    assert manager.reservation_ledger.active_reserved_capital() == before
    assert manager._risk_admissions == {}


# --------------------------------------------------------------------------
# T2 — CapitalManager holds no admission authority (Block-5B)
# --------------------------------------------------------------------------

def test_capital_manager_cannot_veto_an_approved_canonical_decision():
    """A denying CapitalManager is not consulted and changes nothing.

    Before 5B this same manager turned a canonical RISK_APPROVED into a
    rejection. It now has no gate to reject from, so the approval, the
    reservation and the admission all stand exactly as the engine decided.
    """
    manager = execution_manager(capital_manager=DenyingCapitalManager())

    result = manager.risk_check(buy_request("r1"), state())

    assert result["approved"] is True
    assert result["reason"] == "RISK_APPROVED"
    assert manager.last_risk_decision["reason_code"] == "RISK_APPROVED"
    reservation = manager.reservation_ledger.get("r1")
    assert reservation is not None
    assert reservation.amount == D("100")
    assert "r1" in manager._risk_admissions


def test_capital_manager_denial_cannot_shrink_the_approved_allocation():
    """Demotion covers sizing as well as vetoing."""
    manager = execution_manager(capital_manager=DenyingCapitalManager())
    request = buy_request("r1")

    manager.risk_check(request, state())

    approved = D(manager.last_risk_decision["approved_allocation"])
    assert approved == D("100")
    assert D(str(request.amount)) == approved
    assert manager.reservation_ledger.get("r1").amount == approved


# --------------------------------------------------------------------------
# T3 — successful BUY invariance
# --------------------------------------------------------------------------

def test_approved_buy_retains_reservation_and_admission():
    manager = execution_manager()
    request = buy_request("r1")

    result = manager.risk_check(request, state())

    assert result["approved"] is True
    assert result["reason"] == "RISK_APPROVED"
    reservation = manager.reservation_ledger.get("r1")
    assert reservation is not None
    assert reservation.amount == D("100")
    # The token seals the approval the engine granted, so it is reproducible
    # only from the admitted request - never from an unapproved copy of it.
    assert manager._risk_admissions.get("r1") == manager._risk_admission_key(request)
    assert manager._risk_admissions.get("r1") != manager._risk_admission_key(buy_request("r1"))
    assert manager.reservation_ledger.active_reserved_capital() == D("100")


# --------------------------------------------------------------------------
# T4 — risk-engine rejection: no reservation ever created
# --------------------------------------------------------------------------

def test_canonical_risk_rejection_never_creates_reservation():
    manager = execution_manager()
    # amount far exceeds bucket/portfolio caps -> canonical REJECT before any gate.
    result = manager.risk_check(buy_request("r1", amount="999"), state())

    assert result["approved"] is False
    assert manager.reservation_ledger.get("r1") is None
    assert "r1" not in manager._risk_admissions


# --------------------------------------------------------------------------
# T5 — reduce-only exit unaffected
# --------------------------------------------------------------------------

def test_reduce_only_exit_creates_no_buy_reservation_and_can_approve():
    manager = execution_manager(position_controller=DenyingPositionController())
    p = position()
    result = manager.risk_check(reduce_only_sell("r1", amount="100"), state(p))

    assert result["approved"] is True
    assert manager.reservation_ledger.get("r1") is None
    assert manager._risk_admissions.get("r1") is not None


# --------------------------------------------------------------------------
# T6 — cleanup idempotence
# --------------------------------------------------------------------------

def test_release_capital_reservation_is_idempotent_for_missing_state():
    manager = execution_manager()
    assert manager._release_capital_reservation("never-existed") is True
    assert manager._release_capital_reservation("never-existed") is True


def test_release_capital_reservation_idempotent_after_release():
    manager = execution_manager()
    manager.risk_check(buy_request("r1"), state())
    assert manager._release_capital_reservation("r1") is True
    assert manager.reservation_ledger.get("r1").status.value == "RELEASED"
    assert manager._release_capital_reservation("r1") is True


# --------------------------------------------------------------------------
# T7 — repeated rejection, mixed gates
# --------------------------------------------------------------------------

def test_repeated_mixed_rejections_never_leave_stale_reservation():
    manager = execution_manager(position_controller=DenyingPositionController(),
                                capital_manager=DenyingCapitalManager())
    initial = manager.reservation_ledger.active_reserved_capital()

    for i in range(10):
        result = manager.risk_check(buy_request(f"r{i}"), state())
        assert result["approved"] is False

    assert manager.reservation_ledger.active_reserved_capital() == initial
    assert manager._risk_admissions == {}


# --------------------------------------------------------------------------
# T9 — reservation/admission consistency across terminal states
# --------------------------------------------------------------------------

@pytest.mark.parametrize("position_controller,capital_manager,expect_approved", [
    (None, None, True),
    (DenyingPositionController(), None, False),
    # Block-5B: a denying CapitalManager is no longer a terminal state at all,
    # so this row asserts an approved outcome whose reservation and admission
    # must both be present and consistent.
    (None, DenyingCapitalManager(), True),
])
def test_reservation_and_admission_consistency(position_controller, capital_manager, expect_approved):
    manager = execution_manager(position_controller=position_controller, capital_manager=capital_manager)

    result = manager.risk_check(buy_request("r1"), state())

    assert result["approved"] is expect_approved
    reservation = manager.reservation_ledger.get("r1")
    admitted = "r1" in manager._risk_admissions
    if expect_approved:
        assert reservation is not None
        assert admitted
    else:
        assert reservation is None
        assert not admitted
