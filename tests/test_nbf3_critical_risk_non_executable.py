"""NBF-3: CRITICAL is a non-executable new-risk state (Policy C1).

Upstream analytical risk has four states; executable bucket policy has three.
CRITICAL is a valid upstream state that must never open or increase exposure,
must never be reported as malformed financial input, and must never alias
HIGH.  Genuine risk reduction stays permitted so exposure is never trapped in
the state judged most dangerous.
"""

from decimal import Decimal as D
from datetime import UTC, datetime
import threading

import pytest

from core.risk_engine import (
    NON_EXECUTABLE_RISK_LEVELS, PositionExposure, RiskBucket,
    RiskDecisionStatus, RiskEngine, RiskPolicy, RiskRequest, RiskState,
)
from core.execution_manager import ExecutionManager
from core.execution_models import ExecutionRequest
from core.capital_reservation import CapitalReservationLedger
from core.instrument_rules import InstrumentRules, InstrumentRuleset
from core.risk_state_store import RestoredRiskState

# A minimal, hermetic stand-in for the real checked-in ETHUSDT rule (Block
# 5D): every request in this file trades ETHUSDT at price 10.
ETHUSDT_RULES = InstrumentRuleset({
    "ETHUSDT": InstrumentRules(
        venue="BINANCE", symbol="ETHUSDT", base_asset="ETH", quote_asset="USDT",
        quantity_step="0.0001", min_quantity="0.0001", min_notional="5",
        price_tick="0.01", source="test-fixture", source_version="v1",
        retrieved_at="2026-01-01T00:00:00Z",
    ),
})


def policy(**changes):
    values = {"total_capital": D("1000")}
    values.update(changes)
    return RiskPolicy(**values)


def position(symbol="ETHUSDT", quote="100", price="10"):
    return PositionExposure(symbol, D(quote) / D(price), D(price), D(quote))


def state(*positions, pnl="0", peak="1000", equity="1000", ready=True):
    return RiskState(tuple(positions), sum((p.quote_exposure for p in positions), D("0")),
                     D(pnl), D(peak), D(equity), ready,
                     datetime.now(UTC).date().isoformat(), "phase3-risk-v1")


def buy(bucket="MEDIUM", amount="50", confidence="0.95", symbol="ETHUSDT", **changes):
    values = dict(symbol=symbol, action="BUY", confidence=D(confidence),
                  requested_quote_allocation=D(amount), execution_price=D("10"),
                  risk_bucket=bucket, base_quantity=D(amount) / D("10"))
    values.update(changes)
    return RiskRequest(**values)


def exit_request(bucket="CRITICAL", amount="100", symbol="ETHUSDT", reduce_only=True):
    return RiskRequest(symbol=symbol, action="SELL", confidence=D("0.95"),
                       requested_quote_allocation=D(amount), execution_price=D("10"),
                       risk_bucket=bucket, base_quantity=D(amount) / D("10"),
                       reduce_only=reduce_only)


# =====================================================================
# T1 - executable taxonomy remains three-state
# =====================================================================

def test_executable_bucket_taxonomy_remains_three_state():
    assert [b.value for b in RiskBucket] == ["LOW", "MEDIUM", "HIGH"]
    assert "CRITICAL" not in {b.value for b in RiskBucket}
    with pytest.raises(ValueError):
        RiskBucket("CRITICAL")
    assert NON_EXECUTABLE_RISK_LEVELS == frozenset({"CRITICAL"})


# =====================================================================
# T2 - new-risk BUY carrying CRITICAL is rejected on its own terms
# =====================================================================

def test_new_risk_buy_with_critical_is_rejected_with_dedicated_reason():
    result = RiskEngine(policy()).evaluate(buy(bucket="CRITICAL"), state())
    assert result.status is RiskDecisionStatus.REJECT
    assert result.reason_code == "CRITICAL_RISK_NOT_EXECUTABLE"
    assert result.approved_allocation == D("0")
    assert result.approved is False


def test_critical_rejection_is_not_caused_by_confidence_or_notional():
    """The identical request approves under an executable bucket, so only the
    CRITICAL classification can explain the rejection."""
    approved = RiskEngine(policy()).evaluate(buy(bucket="HIGH"), state())
    assert approved.status is RiskDecisionStatus.APPROVE
    assert approved.reason_code == "RISK_APPROVED"
    assert approved.approved_allocation == D("50")

    rejected = RiskEngine(policy()).evaluate(buy(bucket="CRITICAL"), state())
    assert rejected.reason_code == "CRITICAL_RISK_NOT_EXECUTABLE"


def test_reduce_only_flag_cannot_make_a_buy_executable_under_critical():
    result = RiskEngine(policy()).evaluate(
        buy(bucket="CRITICAL", reduce_only=True), state())
    assert result.reason_code == "CRITICAL_RISK_NOT_EXECUTABLE"
    assert result.approved_allocation == D("0")


# =====================================================================
# T3 - CRITICAL is semantically distinct from malformed financial input
# =====================================================================

def test_critical_is_not_conflated_with_malformed_financial_input():
    critical = RiskEngine(policy()).evaluate(buy(bucket="CRITICAL"), state())
    malformed = RiskEngine(policy()).evaluate(
        buy(requested_quote_allocation="not-a-number", base_quantity=None), state())

    assert critical.reason_code == "CRITICAL_RISK_NOT_EXECUTABLE"
    assert malformed.reason_code == "INVALID_FINANCIAL_INPUT"
    assert critical.reason_code != malformed.reason_code


@pytest.mark.parametrize("changes", [
    {"requested_quote_allocation": "not-a-number", "base_quantity": None},
    {"execution_price": D("0"), "base_quantity": None},
    {"confidence": D("1.5")},
    {"requested_quote_allocation": 50.0, "base_quantity": None},
])
def test_malformed_financial_input_semantics_unchanged(changes):
    result = RiskEngine(policy()).evaluate(buy(**changes), state())
    assert result.status is RiskDecisionStatus.REJECT
    assert result.reason_code == "INVALID_FINANCIAL_INPUT"
    assert result.approved_allocation == D("0")


# =====================================================================
# T4 - LOW / MEDIUM / HIGH invariance
# =====================================================================

@pytest.mark.parametrize("bucket,max_alloc,min_conf,ceiling", [
    (RiskBucket.LOW, D("0.40"), D("0.60"), D("0.60")),
    (RiskBucket.MEDIUM, D("0.25"), D("0.70"), D("0.40")),
    (RiskBucket.HIGH, D("0.10"), D("0.80"), D("0.20")),
])
def test_executable_bucket_policy_values_unchanged(bucket, max_alloc, min_conf, ceiling):
    bucket_policy = policy().buckets[bucket]
    assert bucket_policy.max_allocation_pct == max_alloc
    assert bucket_policy.minimum_confidence == min_conf
    assert bucket_policy.exposure_ceiling_pct == ceiling


def test_global_minimum_confidence_unchanged():
    assert policy().global_minimum_confidence == D("0.60")


@pytest.mark.parametrize("bucket", ["LOW", "MEDIUM", "HIGH"])
def test_executable_buckets_still_approve_normally(bucket):
    result = RiskEngine(policy()).evaluate(buy(bucket=bucket), state())
    assert result.status is RiskDecisionStatus.APPROVE
    assert result.reason_code == "RISK_APPROVED"
    assert result.approved_allocation == D("50")


@pytest.mark.parametrize("bucket,confidence,approved", [
    (RiskBucket.LOW, "0.60", True), (RiskBucket.MEDIUM, "0.69", False),
    (RiskBucket.HIGH, "0.79", False), (RiskBucket.HIGH, "0.80", True),
])
def test_bucket_confidence_thresholds_unchanged(bucket, confidence, approved):
    result = RiskEngine(policy()).evaluate(
        buy(bucket=bucket, amount="50", confidence=confidence), state())
    assert result.approved is approved


@pytest.mark.parametrize("bucket,amount", [("LOW", "401"), ("MEDIUM", "251"), ("HIGH", "101")])
def test_bucket_allocation_caps_unchanged(bucket, amount):
    result = RiskEngine(policy()).evaluate(buy(bucket=bucket, amount=amount), state())
    assert result.reason_code == "REQUEST_EXCEEDS_RISK_LIMIT"


# =====================================================================
# T5 - CRITICAL must not block a genuine risk-reducing exit (MANDATORY)
# =====================================================================

def test_critical_full_exit_is_approved_through_existing_reduction_path():
    open_position = position(quote="100")
    current = state(open_position)
    assert current.committed_quote == D("100")

    result = RiskEngine(policy()).evaluate(exit_request(amount="100"), current)

    assert result.status is RiskDecisionStatus.APPROVE
    assert result.reason_code == "RISK_REDUCTION_APPROVED"
    assert result.approved_allocation == D("100")
    # Exposure after <= exposure before.
    assert current.committed_quote - result.approved_allocation == D("0")


def test_critical_partial_exit_is_approved_and_strictly_reduces_exposure():
    open_position = position(quote="100")
    current = state(open_position)

    result = RiskEngine(policy()).evaluate(exit_request(amount="40"), current)

    assert result.status is RiskDecisionStatus.APPROVE
    assert result.reason_code == "RISK_REDUCTION_APPROVED"
    assert result.approved_allocation == D("40")
    assert current.committed_quote - result.approved_allocation == D("60")
    assert current.committed_quote - result.approved_allocation < current.committed_quote


@pytest.mark.parametrize("bucket", ["LOW", "MEDIUM", "HIGH", "CRITICAL"])
def test_exit_outcome_is_independent_of_risk_classification(bucket):
    """Risk classification must not decide whether de-risking is permitted."""
    current = state(position(quote="100"))
    result = RiskEngine(policy()).evaluate(exit_request(bucket=bucket, amount="100"), current)
    assert result.status is RiskDecisionStatus.APPROVE
    assert result.reason_code == "RISK_REDUCTION_APPROVED"
    assert result.approved_allocation == D("100")


# =====================================================================
# T6 - the exit rule is not a bypass for arbitrary SELLs
# =====================================================================

def test_non_reduce_only_sell_with_critical_still_blocked():
    result = RiskEngine(policy()).evaluate(
        exit_request(amount="100", reduce_only=False), state(position(quote="100")))
    assert result.status is RiskDecisionStatus.REJECT
    assert result.reason_code == "NON_RISK_REDUCING_SELL"
    assert result.approved_allocation == D("0")


def test_reduce_only_sell_without_any_position_still_blocked():
    result = RiskEngine(policy()).evaluate(exit_request(amount="100"), state())
    assert result.status is RiskDecisionStatus.REJECT
    assert result.reason_code == "INVALID_RISK_REDUCTION"
    assert result.approved_allocation == D("0")


def test_reduce_only_sell_exceeding_exposure_still_blocked():
    result = RiskEngine(policy()).evaluate(
        exit_request(amount="150"), state(position(quote="100")))
    assert result.status is RiskDecisionStatus.REJECT
    assert result.reason_code == "INVALID_RISK_REDUCTION"
    assert result.approved_allocation == D("0")


def test_reduce_only_sell_for_a_different_symbol_still_blocked():
    result = RiskEngine(policy()).evaluate(
        exit_request(amount="100", symbol="BTCUSDT"), state(position("ETHUSDT", "100")))
    assert result.reason_code == "INVALID_RISK_REDUCTION"


def test_reduce_only_exit_still_enforces_financial_input_validation():
    result = RiskEngine(policy()).evaluate(
        RiskRequest(symbol="ETHUSDT", action="SELL", confidence=D("0.95"),
                    requested_quote_allocation=D("100"), execution_price=D("10"),
                    risk_bucket="CRITICAL", base_quantity=D("100"), reduce_only=True),
        state(position(quote="100")))
    assert result.reason_code == "QUANTITY_NOTIONAL_MISMATCH"


# =====================================================================
# T7 - new-risk CRITICAL never reaches capital reservation or routing
# =====================================================================

class MemoryStore:
    def __init__(self): self.items = ()
    def load(self): return self.items
    def save(self, items): self.items = tuple(items)


class MemoryRiskStateStore:
    def load(self, *, expected_policy_version, today_utc):
        return RestoredRiskState(today_utc, D("0"), D("1000"), D("1000"),
                                 expected_policy_version)


class SpyLedger:
    """Wraps the real ledger so reservation attempts are observable."""

    def __init__(self):
        self.inner = CapitalReservationLedger(MemoryStore(), D("800"))
        self.reserve_calls = []

    @property
    def ready(self):
        return self.inner.ready

    def reserve(self, *args, **kwargs):
        self.reserve_calls.append((args, kwargs))
        return self.inner.reserve(*args, **kwargs)


def execution_manager(ledger):
    manager = ExecutionManager.__new__(ExecutionManager)
    manager.risk_engine = RiskEngine(policy())
    manager.reservation_ledger = ledger
    manager.risk_state_store = MemoryRiskStateStore()
    # No durable portfolio book is configured here, so the supplied
    # RiskState remains the position authority for these unit contracts.
    manager.portfolio_foundation = None
    manager.position_controller = None
    manager.capital_manager = None
    manager.last_risk_decision = None
    manager._risk_admissions = {}
    manager.instrument_rules = ETHUSDT_RULES
    manager.mode = "PAPER"
    manager.event_bus = None
    manager._lock = threading.RLock()
    manager.errors = []
    return manager


def test_execution_seam_blocks_critical_before_capital_reservation():
    ledger = SpyLedger()
    manager = execution_manager(ledger)
    request = ExecutionRequest("ETHUSDT", "BUY", 10, 50, confidence=95, risk="CRITICAL")

    result = manager.risk_check(request, state())

    assert result["approved"] is False
    assert result["reason"] == "CRITICAL_RISK_NOT_EXECUTABLE"
    assert result["status"] == "REJECT"
    # No capital reserved, and no admission recorded that could authorize routing.
    assert ledger.reserve_calls == []
    assert manager._risk_admissions == {}
    assert D(manager.last_risk_decision["approved_allocation"]) == D("0")


def test_execution_seam_still_reserves_for_executable_buckets():
    ledger = SpyLedger()
    manager = execution_manager(ledger)
    request = ExecutionRequest("ETHUSDT", "BUY", 10, 50, confidence=95, risk="HIGH")

    result = manager.risk_check(request, state())

    assert result["approved"] is True
    assert len(ledger.reserve_calls) == 1
    assert manager._risk_admissions != {}


def test_execution_request_still_carries_critical_to_the_boundary():
    """CRITICAL must stay visible upstream, not be normalized away."""
    request = ExecutionRequest("ETHUSDT", "BUY", 10, 50, confidence=95, risk="CRITICAL")
    assert request.risk == "CRITICAL"


# =====================================================================
# T8 - unsupported / unknown risk semantics (superseded by NBF-4)
#
# These expectations were written while unsupported risk was out of scope
# and fell into the malformed-input reason code.  NBF-4 (Policy D') gives
# unsupported risk its own non-executable state, so the assertions below
# now pin the dedicated reason code and the reduction path.  Fail-closed
# strength is unchanged for new risk and the full NBF-4 contract is proven
# in tests/test_nbf4_unsupported_risk_fail_closed.py.
# =====================================================================

@pytest.mark.parametrize("bucket", ["UNKNOWN", "EXTREME", "SEVERE"])
def test_unsupported_risk_levels_fail_closed_with_their_own_reason(bucket):
    result = RiskEngine(policy()).evaluate(buy(bucket=bucket), state())
    assert result.status is RiskDecisionStatus.REJECT
    assert result.reason_code == "UNSUPPORTED_RISK_LEVEL"
    assert result.approved_allocation == D("0")
    assert result.approved is False


def test_empty_risk_at_the_admission_boundary_is_still_malformed_input():
    """Absence defaults belong to the normalization layers; an empty value
    reaching the evaluator is malformed, not an unsupported classification."""
    result = RiskEngine(policy()).evaluate(buy(bucket=""), state())
    assert result.status is RiskDecisionStatus.REJECT
    assert result.reason_code == "INVALID_FINANCIAL_INPUT"
    assert result.approved_allocation == D("0")


@pytest.mark.parametrize("bucket", ["UNKNOWN", "EXTREME"])
def test_unsupported_risk_does_not_trap_a_verified_risk_reducing_exit(bucket):
    """Unsupported metadata must not become a reason exposure cannot be closed."""
    current = state(position(quote="100"))
    result = RiskEngine(policy()).evaluate(
        exit_request(bucket=bucket, amount="100"), current)
    assert result.status is RiskDecisionStatus.APPROVE
    assert result.reason_code == "RISK_REDUCTION_APPROVED"
    assert result.approved_allocation == D("100")
    assert current.committed_quote - result.approved_allocation <= current.committed_quote


@pytest.mark.parametrize("bucket", ["UNKNOWN", "EXTREME"])
def test_unsupported_risk_exit_is_not_a_bypass_for_arbitrary_sells(bucket):
    result = RiskEngine(policy()).evaluate(
        exit_request(bucket=bucket, amount="100", reduce_only=False),
        state(position(quote="100")))
    assert result.status is RiskDecisionStatus.REJECT
    assert result.approved_allocation == D("0")


def test_unknown_risk_is_not_silently_promoted_to_an_executable_bucket():
    result = RiskEngine(policy()).evaluate(buy(bucket="UNKNOWN"), state())
    assert result.reason_code != "RISK_APPROVED"
    assert result.approved_allocation == D("0")


def test_unsupported_and_critical_remain_distinct_states():
    unsupported = RiskEngine(policy()).evaluate(buy(bucket="EXTREME"), state())
    critical = RiskEngine(policy()).evaluate(buy(bucket="CRITICAL"), state())
    assert unsupported.reason_code == "UNSUPPORTED_RISK_LEVEL"
    assert critical.reason_code == "CRITICAL_RISK_NOT_EXECUTABLE"
    assert unsupported.reason_code != critical.reason_code


# =====================================================================
# No-alias proof
# =====================================================================

def test_critical_never_aliases_high():
    engine_policy = policy()
    high = RiskEngine(engine_policy).evaluate(buy(bucket="HIGH"), state())
    critical = RiskEngine(engine_policy).evaluate(buy(bucket="CRITICAL"), state())

    assert high.status is RiskDecisionStatus.APPROVE
    assert critical.status is RiskDecisionStatus.REJECT
    assert critical.reason_code != high.reason_code
    assert critical.approved_allocation == D("0")
    assert high.approved_allocation > critical.approved_allocation


def test_critical_cannot_open_exposure_at_any_confidence_or_size():
    for confidence in ("0.60", "0.80", "0.95", "1.00"):
        for amount in ("1", "50", "100", "400"):
            result = RiskEngine(policy()).evaluate(
                buy(bucket="CRITICAL", amount=amount, confidence=confidence), state())
            assert result.status is RiskDecisionStatus.REJECT
            assert result.approved_allocation == D("0")
