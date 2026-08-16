"""NBF-4: unsupported / unknown risk must fail closed (Policy D').

The verified fail-open: an explicit ``EXTREME`` risk classification was
normalized to ``MEDIUM`` by DecisionAdapter and by ExecutionManager, landed in
the executable MEDIUM bucket, was approved as new risk, and reserved capital.

Policy D' keeps three states distinct:

    missing / None / ""      -> MEDIUM   (frozen legacy absence default)
    explicit unsupported     -> UNKNOWN  (non-executable)
    CRITICAL                 -> CRITICAL (valid analytical maximum risk)

New or increasing risk carrying UNKNOWN is rejected with
``UNSUPPORTED_RISK_LEVEL``, zero allocation and no capital reservation.  A
structurally verified reduce-only exit is still approved, because unsupported
metadata must not trap exposure.
"""

from decimal import Decimal as D
from datetime import UTC, datetime
import threading

import pytest

from core.risk_engine import (
    NON_EXECUTABLE_RISK_LEVELS, UNSUPPORTED_RISK_SENTINEL, PositionExposure,
    RiskBucket, RiskDecisionStatus, RiskEngine, RiskPolicy, RiskRequest,
    RiskState, analytical_risk_level,
)
from core.decision_adapter import DecisionAdapter
from core.execution_manager import ExecutionManager
from core.execution_models import ExecutionRequest, normalize_risk
from core.capital_reservation import CapitalReservationLedger
from core.risk_state_store import RestoredRiskState


UNSUPPORTED = ["UNKNOWN", "EXTREME", "VERY_HIGH", "SEVERE"]


# =====================================================================
# Shared fixtures / helpers
# =====================================================================

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


def exit_request(bucket="UNKNOWN", amount="100", symbol="ETHUSDT", reduce_only=True, **changes):
    values = dict(symbol=symbol, action="SELL", confidence=D("0.95"),
                  requested_quote_allocation=D(amount), execution_price=D("10"),
                  risk_bucket=bucket, base_quantity=D(amount) / D("10"),
                  reduce_only=reduce_only)
    values.update(changes)
    return RiskRequest(**values)


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


def execution_manager(ledger=None):
    manager = ExecutionManager.__new__(ExecutionManager)
    manager.risk_engine = RiskEngine(policy())
    manager.reservation_ledger = ledger if ledger is not None else SpyLedger()
    manager.risk_state_store = MemoryRiskStateStore()
    # No durable portfolio book is configured here, so the supplied
    # RiskState remains the position authority for these unit contracts.
    manager.portfolio_foundation = None
    manager.position_controller = None
    manager.capital_manager = None
    manager.last_risk_decision = None
    manager._risk_admissions = {}
    manager.mode = "PAPER"
    manager.event_bus = None
    manager._lock = threading.RLock()
    manager.errors = []
    return manager


def raw_decision(risk, action="BUY", amount=50):
    return {"symbol": "ETHUSDT", "action": action, "price": 10,
            "amount": amount, "confidence": 95, "risk_level": risk,
            "strategy": "Atlas"}


def path1_request(manager, risk, action="BUY", amount=50):
    """DecisionAdapter -> MarketLoop-style handoff -> ExecutionManager."""
    schema = DecisionAdapter().normalize(raw_decision(risk, action=action))
    assert isinstance(schema, dict)
    # The allocation is attached downstream of the adapter, exactly as the
    # market loop hands the normalized decision on for execution.
    return manager.build_request({**schema, "amount": amount})


def path2_request(risk, action="BUY", amount=50):
    """Direct ExecutionRequest construction."""
    return ExecutionRequest("ETHUSDT", action, 10, amount, confidence=95, risk=risk)


def path3_request(manager, risk, action="BUY", amount=50):
    """Raw dict -> ExecutionManager.build_request."""
    return manager.build_request(raw_decision(risk, action=action, amount=amount))


# =====================================================================
# T1 - path invariance for new risk
# =====================================================================

@pytest.mark.parametrize("risk", UNSUPPORTED)
@pytest.mark.parametrize("path", ["adapter", "direct", "raw_dict"])
def test_unsupported_new_risk_fails_closed_on_every_construction_path(risk, path):
    ledger = SpyLedger()
    manager = execution_manager(ledger)

    if path == "adapter":
        request = path1_request(manager, risk)
    elif path == "direct":
        request = path2_request(risk)
    else:
        request = path3_request(manager, risk)

    assert request.risk == UNSUPPORTED_RISK_SENTINEL

    result = manager.risk_check(request, state())

    assert result["approved"] is False
    assert result["reason"] == "UNSUPPORTED_RISK_LEVEL"
    assert result["status"] == "REJECT"
    assert D(manager.last_risk_decision["approved_allocation"]) == D("0")
    assert ledger.reserve_calls == []
    assert manager._risk_admissions == {}


@pytest.mark.parametrize("risk", UNSUPPORTED)
def test_all_paths_agree_on_the_same_outcome(risk):
    manager = execution_manager()
    outcomes = {
        path: manager.risk_check(builder, state())["reason"]
        for path, builder in (
            ("adapter", path1_request(manager, risk)),
            ("direct", path2_request(risk)),
            ("raw_dict", path3_request(manager, risk)),
        )
    }
    assert set(outcomes.values()) == {"UNSUPPORTED_RISK_LEVEL"}


# =====================================================================
# T2 - direct fail-open regression (EXTREME BUY)
# =====================================================================

def test_extreme_buy_no_longer_reaches_the_executable_medium_bucket():
    """The exact verified fail-open: BUY + EXTREME with otherwise approvable
    values previously normalized to MEDIUM, approved, and reserved capital."""
    ledger = SpyLedger()
    manager = execution_manager(ledger)
    request = path2_request("EXTREME")

    # Severity is not downgraded anywhere on the way in.
    assert request.risk != "MEDIUM"
    assert request.risk == "UNKNOWN"

    result = manager.risk_check(request, state())

    assert result["approved"] is False
    assert result["reason"] == "UNSUPPORTED_RISK_LEVEL"
    assert D(manager.last_risk_decision["approved_allocation"]) == D("0")
    # Reservation ledger untouched, no admission recorded for routing.
    assert ledger.reserve_calls == []
    assert ledger.inner.active_reserved_capital() == D("0")
    assert manager._risk_admissions == {}


def test_identical_request_under_medium_still_approves():
    """Proves the rejection is caused by the classification, not by size,
    confidence or state - and that MEDIUM itself is untouched."""
    ledger = SpyLedger()
    manager = execution_manager(ledger)

    result = manager.risk_check(path2_request("MEDIUM"), state())

    assert result["approved"] is True
    assert len(ledger.reserve_calls) == 1


# =====================================================================
# T3 - reason-code separation
# =====================================================================

def test_reason_codes_stay_semantically_distinct():
    engine = RiskEngine(policy())

    critical = engine.evaluate(buy(bucket="CRITICAL"), state())
    unsupported = engine.evaluate(buy(bucket="EXTREME"), state())
    malformed = engine.evaluate(
        buy(requested_quote_allocation="not-a-number", base_quantity=None), state())
    threshold = engine.evaluate(buy(bucket="HIGH", confidence="0.79"), state())

    assert critical.reason_code == "CRITICAL_RISK_NOT_EXECUTABLE"
    assert unsupported.reason_code == "UNSUPPORTED_RISK_LEVEL"
    assert malformed.reason_code == "INVALID_FINANCIAL_INPUT"
    assert threshold.reason_code == "CONFIDENCE_BELOW_POLICY"

    codes = {critical.reason_code, unsupported.reason_code,
             malformed.reason_code, threshold.reason_code}
    assert len(codes) == 4
    for result in (critical, unsupported, malformed, threshold):
        assert result.status is RiskDecisionStatus.REJECT
        assert result.approved_allocation == D("0")


# =====================================================================
# T4 - missing vs unsupported
# =====================================================================

def test_missing_risk_field_retains_the_legacy_medium_default():
    manager = execution_manager()
    request = manager.build_request(
        {"symbol": "ETHUSDT", "action": "BUY", "price": 10, "amount": 50,
         "confidence": 95})
    assert request.risk == "MEDIUM"
    assert DecisionAdapter().get_risk_level({"action": "BUY"}) == "MEDIUM"


@pytest.mark.parametrize("absent", [None, ""])
def test_none_and_empty_risk_retain_the_legacy_medium_default(absent):
    manager = execution_manager()
    assert normalize_risk(absent) == "MEDIUM"
    assert manager._normalize_risk_level(absent) == "MEDIUM"
    assert DecisionAdapter().get_risk_level({"risk_level": absent}) == "MEDIUM"
    assert ExecutionRequest("ETHUSDT", "BUY", 10, 50, risk=absent).risk == "MEDIUM"


def test_absence_and_explicit_unsupported_are_not_the_same_state():
    manager = execution_manager()
    absent = manager.build_request(
        {"symbol": "ETHUSDT", "action": "BUY", "price": 10, "amount": 50,
         "confidence": 95})
    explicit = path3_request(manager, "EXTREME")

    assert absent.risk == "MEDIUM"
    assert explicit.risk == "UNKNOWN"
    assert absent.risk != explicit.risk

    assert manager.risk_check(absent, state())["approved"] is True
    assert execution_manager().risk_check(explicit, state())["reason"] == "UNSUPPORTED_RISK_LEVEL"


# =====================================================================
# T5 - reduce-only unsupported exit stays possible
# =====================================================================

@pytest.mark.parametrize("risk", UNSUPPORTED)
@pytest.mark.parametrize("amount", ["100", "40"])
def test_unsupported_risk_reduce_only_exit_is_approved(risk, amount):
    current = state(position(quote="100"))
    exposure_before = current.committed_quote

    result = RiskEngine(policy()).evaluate(
        exit_request(bucket=risk, amount=amount), current)

    assert result.status is RiskDecisionStatus.APPROVE
    assert result.reason_code == "RISK_REDUCTION_APPROVED"
    assert result.approved_allocation == D(amount)

    exposure_after = exposure_before - result.approved_allocation
    assert exposure_after <= exposure_before
    assert exposure_after >= D("0")


@pytest.mark.parametrize("risk", UNSUPPORTED)
def test_unsupported_risk_exit_at_the_execution_seam_reserves_nothing(risk):
    ledger = SpyLedger()
    manager = execution_manager(ledger)
    request = ExecutionRequest("ETHUSDT", "SELL", 10, 100, confidence=95,
                               risk=risk, reduce_only=True)

    result = manager.risk_check(request, state(position(quote="100")))

    assert result["approved"] is True
    assert manager.last_risk_decision["reason_code"] == "RISK_REDUCTION_APPROVED"
    # Exits never reserve new capital.
    assert ledger.reserve_calls == []


# =====================================================================
# T6 - unknown risk is not an exit bypass
# =====================================================================

@pytest.mark.parametrize("risk", UNSUPPORTED)
def test_reduce_only_sell_without_position_is_still_rejected(risk):
    result = RiskEngine(policy()).evaluate(exit_request(bucket=risk), state())
    assert result.status is RiskDecisionStatus.REJECT
    assert result.reason_code == "INVALID_RISK_REDUCTION"
    assert result.approved_allocation == D("0")


@pytest.mark.parametrize("risk", UNSUPPORTED)
def test_reduction_larger_than_exposure_is_still_rejected(risk):
    result = RiskEngine(policy()).evaluate(
        exit_request(bucket=risk, amount="150"), state(position(quote="100")))
    assert result.reason_code == "INVALID_RISK_REDUCTION"
    assert result.approved_allocation == D("0")


@pytest.mark.parametrize("risk", UNSUPPORTED)
def test_reduction_for_a_different_symbol_is_still_rejected(risk):
    result = RiskEngine(policy()).evaluate(
        exit_request(bucket=risk, symbol="BTCUSDT"), state(position("ETHUSDT", "100")))
    assert result.reason_code == "INVALID_RISK_REDUCTION"


@pytest.mark.parametrize("risk", UNSUPPORTED)
def test_arbitrary_sell_without_reduce_only_is_still_rejected(risk):
    result = RiskEngine(policy()).evaluate(
        exit_request(bucket=risk, reduce_only=False), state(position(quote="100")))
    assert result.status is RiskDecisionStatus.REJECT
    assert result.reason_code == "NON_RISK_REDUCING_SELL"
    assert result.approved_allocation == D("0")


@pytest.mark.parametrize("risk", UNSUPPORTED)
def test_quantity_notional_mismatch_on_an_unsupported_exit_is_still_rejected(risk):
    result = RiskEngine(policy()).evaluate(
        exit_request(bucket=risk, amount="100", base_quantity=D("100")),
        state(position(quote="100")))
    assert result.reason_code == "QUANTITY_NOTIONAL_MISMATCH"


@pytest.mark.parametrize("changes", [
    {"requested_quote_allocation": "not-a-number", "base_quantity": None},
    {"execution_price": D("0"), "base_quantity": None},
    {"requested_quote_allocation": 100.0, "base_quantity": None},
])
def test_malformed_financial_values_on_an_unsupported_exit_are_still_rejected(changes):
    result = RiskEngine(policy()).evaluate(
        exit_request(bucket="EXTREME", **changes), state(position(quote="100")))
    assert result.status is RiskDecisionStatus.REJECT
    assert result.reason_code == "INVALID_FINANCIAL_INPUT"
    assert result.approved_allocation == D("0")


def test_unsupported_buy_cannot_be_laundered_through_the_reduce_only_flag():
    result = RiskEngine(policy()).evaluate(
        buy(bucket="EXTREME", reduce_only=True), state())
    assert result.reason_code == "UNSUPPORTED_RISK_LEVEL"
    assert result.approved_allocation == D("0")


# =====================================================================
# T7 - normalizer matrix
# =====================================================================

@pytest.mark.parametrize("value,expected", [
    ("LOW", "LOW"),
    ("MEDIUM", "MEDIUM"),
    ("HIGH", "HIGH"),
    ("CRITICAL", "CRITICAL"),
    ("UNKNOWN", "UNKNOWN"),
    ("EXTREME", "UNKNOWN"),
    ("", "MEDIUM"),
    (None, "MEDIUM"),
    (" high ", "HIGH"),
    ("RiskLevel.HIGH", "HIGH"),
    (RiskBucket.HIGH, "HIGH"),
])
def test_canonical_normalizer_matrix(value, expected):
    assert normalize_risk(value) == expected


@pytest.mark.parametrize("value,expected", [
    ("LOW", "LOW"), ("MEDIUM", "MEDIUM"), ("HIGH", "HIGH"),
    ("CRITICAL", "CRITICAL"), ("UNKNOWN", "UNKNOWN"), ("EXTREME", "UNKNOWN"),
    ("", "MEDIUM"), (None, "MEDIUM"), (" high ", "HIGH"),
    ("RiskLevel.HIGH", "HIGH"), (RiskBucket.HIGH, "HIGH"),
])
def test_every_normalization_seam_agrees(value, expected):
    """ExecutionRequest, ExecutionManager and DecisionAdapter must not hold
    divergent risk semantics."""
    assert ExecutionRequest("ETHUSDT", "BUY", 10, 50, risk=value).risk == expected
    assert ExecutionManager._normalize_risk_level(value) == expected
    assert DecisionAdapter().get_risk_level({"risk_level": value}) == expected


@pytest.mark.parametrize("value", ["EXTREME", "VERY_HIGH", "SEVERE", "ELEVATED"])
def test_no_seam_maps_an_unsupported_value_to_medium(value):
    assert normalize_risk(value) != "MEDIUM"
    assert ExecutionManager._normalize_risk_level(value) != "MEDIUM"
    assert DecisionAdapter().get_risk_level({"risk_level": value}) != "MEDIUM"
    assert ExecutionRequest("ETHUSDT", "BUY", 10, 50, risk=value).risk != "MEDIUM"


def test_unsupported_never_normalizes_into_an_executable_bucket():
    executable = {b.value for b in RiskBucket}
    for value in UNSUPPORTED + ["ELEVATED", "MODERATE-ISH"]:
        assert normalize_risk(value) not in executable
        assert analytical_risk_level(value) == UNSUPPORTED_RISK_SENTINEL


def test_unsupported_sentinel_is_not_folded_into_the_critical_set():
    assert NON_EXECUTABLE_RISK_LEVELS == frozenset({"CRITICAL"})
    assert UNSUPPORTED_RISK_SENTINEL == "UNKNOWN"
    assert UNSUPPORTED_RISK_SENTINEL not in NON_EXECUTABLE_RISK_LEVELS
    assert UNSUPPORTED_RISK_SENTINEL not in {b.value for b in RiskBucket}


# =====================================================================
# T8 - LOW / MEDIUM / HIGH invariance
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


@pytest.mark.parametrize("bucket", ["LOW", "MEDIUM", "HIGH"])
def test_executable_buckets_still_approve_with_unchanged_allocation(bucket):
    result = RiskEngine(policy()).evaluate(buy(bucket=bucket), state())
    assert result.status is RiskDecisionStatus.APPROVE
    assert result.reason_code == "RISK_APPROVED"
    assert result.approved_allocation == D("50")


@pytest.mark.parametrize("bucket,confidence,approved", [
    ("LOW", "0.60", True), ("MEDIUM", "0.69", False),
    ("HIGH", "0.79", False), ("HIGH", "0.80", True),
])
def test_bucket_confidence_thresholds_unchanged(bucket, confidence, approved):
    result = RiskEngine(policy()).evaluate(
        buy(bucket=bucket, confidence=confidence), state())
    assert result.approved is approved


@pytest.mark.parametrize("bucket,amount", [("LOW", "401"), ("MEDIUM", "251"), ("HIGH", "101")])
def test_bucket_allocation_caps_unchanged(bucket, amount):
    result = RiskEngine(policy()).evaluate(buy(bucket=bucket, amount=amount), state())
    assert result.reason_code == "REQUEST_EXCEEDS_RISK_LIMIT"


@pytest.mark.parametrize("bucket", ["LOW", "MEDIUM", "HIGH"])
def test_executable_buckets_still_reserve_capital_at_the_seam(bucket):
    ledger = SpyLedger()
    manager = execution_manager(ledger)
    result = manager.risk_check(path2_request(bucket), state())
    assert result["approved"] is True
    assert len(ledger.reserve_calls) == 1
    assert manager._risk_admissions != {}


# =====================================================================
# T9 - CRITICAL / NBF-3 invariance
# =====================================================================

def test_new_risk_critical_still_rejects_with_its_dedicated_reason():
    result = RiskEngine(policy()).evaluate(buy(bucket="CRITICAL"), state())
    assert result.status is RiskDecisionStatus.REJECT
    assert result.reason_code == "CRITICAL_RISK_NOT_EXECUTABLE"
    assert result.approved_allocation == D("0")


def test_valid_critical_reduction_is_still_approved():
    current = state(position(quote="100"))
    result = RiskEngine(policy()).evaluate(
        exit_request(bucket="CRITICAL", amount="100"), current)
    assert result.status is RiskDecisionStatus.APPROVE
    assert result.reason_code == "RISK_REDUCTION_APPROVED"
    assert result.approved_allocation == D("100")


def test_critical_survives_every_normalization_seam():
    assert normalize_risk("CRITICAL") == "CRITICAL"
    assert ExecutionManager._normalize_risk_level("CRITICAL") == "CRITICAL"
    assert DecisionAdapter().get_risk_level({"risk_level": "CRITICAL"}) == "CRITICAL"
    assert path2_request("CRITICAL").risk == "CRITICAL"


def test_critical_and_unsupported_remain_distinguishable_at_the_seam():
    critical = execution_manager().risk_check(path2_request("CRITICAL"), state())
    unsupported = execution_manager().risk_check(path2_request("EXTREME"), state())
    assert critical["reason"] == "CRITICAL_RISK_NOT_EXECUTABLE"
    assert unsupported["reason"] == "UNSUPPORTED_RISK_LEVEL"


# =====================================================================
# T10 - future-state guard
# =====================================================================

def test_a_future_unsupported_label_fails_closed_rather_than_inheriting_medium():
    manager = execution_manager()
    request = path3_request(manager, "ELEVATED")
    assert request.risk == "UNKNOWN"

    result = manager.risk_check(request, state())
    assert result["approved"] is False
    assert result["reason"] == "UNSUPPORTED_RISK_LEVEL"


# =====================================================================
# T11 - audit preservation
# =====================================================================

def test_raw_unsupported_risk_is_preserved_for_diagnostics():
    schema = DecisionAdapter().normalize(raw_decision("EXTREME"))
    assert schema["risk_level"] == "UNKNOWN"
    assert schema["metadata"]["raw_risk_level"] == "EXTREME"


def test_raw_risk_survives_into_the_execution_request_metadata():
    manager = execution_manager()
    request = path1_request(manager, "SEVERE")
    assert request.risk == "UNKNOWN"
    assert request.metadata["raw_risk_level"] == "SEVERE"


@pytest.mark.parametrize("value", ["LOW", "MEDIUM", "HIGH", "CRITICAL", None])
def test_raw_risk_is_only_recorded_for_unsupported_values(value):
    data = {"action": "BUY", "symbol": "ETHUSDT", "price": 10, "confidence": 95}
    if value is not None:
        data["risk_level"] = value
    schema = DecisionAdapter().normalize(data)
    assert "raw_risk_level" not in schema["metadata"]


def test_preserved_raw_value_is_diagnostic_only_and_grants_no_admission():
    manager = execution_manager()
    request = path1_request(manager, "EXTREME")
    assert request.metadata["raw_risk_level"] == "EXTREME"
    assert manager.risk_check(request, state())["reason"] == "UNSUPPORTED_RISK_LEVEL"
