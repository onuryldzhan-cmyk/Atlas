"""NBF-6: DecisionAdapter enum authenticity (Policy B).

The verified fail-open: ``DecisionAdapter._normalize_enum_or_string`` trusted
any object exposing a string ``.value`` attribute as if it were a genuine
``Enum`` member. A plain object with ``.value = "LOW"`` therefore normalized
to ``LOW``, reached ``RISK_APPROVED`` at the execution seam, and reserved
capital - identical to the real ``RiskLevel.LOW`` / ``RiskBucket.LOW`` path.

Policy B: only ``isinstance(value, Enum)`` objects receive Enum ``.value`` /
``.name`` extraction. Arbitrary objects that merely duck-type ``.value`` (or
``.name``) fall through to plain string representation, exactly like any
other unsupported value - which downstream syntactic normalization resolves
to ``UNKNOWN`` (risk) or ``HOLD`` (action).

This file does not reopen NBF-3 (CRITICAL non-executable), NBF-4 (unsupported
risk fail-closed) or NBF-5 (Decision's strict Enum type contract) - it only
proves the shared adapter helper no longer grants Enum semantics to spoofed
objects, and that every existing genuine-Enum / string contract is unchanged.
"""

from decimal import Decimal as D
from datetime import UTC, datetime
import threading

import pytest

from core.decision import DecisionAction, RiskLevel
from core.decision_adapter import DecisionAdapter
from core.execution_manager import ExecutionManager
from core.execution_models import ExecutionRequest, normalize_risk
from core.capital_reservation import CapitalReservationLedger
from core.risk_state_store import RestoredRiskState
from core.risk_engine import (
    PositionExposure,
    RiskBucket,
    RiskDecisionStatus,
    RiskEngine,
    RiskPolicy,
    RiskRequest,
    RiskState,
    UNSUPPORTED_RISK_SENTINEL,
)
from ai.core.intelligence.risk_engine import RiskCategory


# =====================================================================
# Spoof objects
# =====================================================================


class SpoofValue:
    """Arbitrary non-Enum object that merely exposes ``.value``."""

    def __init__(self, value):
        self.value = value


class SpoofValueAndName:
    """Arbitrary non-Enum object exposing both ``.value`` and ``.name``."""

    def __init__(self, value, name):
        self.value = value
        self.name = name


class RaisingValue:
    """``.value`` raises if evaluated; normalization must never touch it."""

    @property
    def value(self):
        raise RuntimeError("value must not be evaluated by the adapter")


class SideEffectingValue:
    """``.value`` records reads; normalization must never touch it."""

    def __init__(self):
        self.reads = 0

    @property
    def value(self):
        self.reads += 1
        return "LOW"


class _ObjectWithRiskLevel:
    def __init__(self, risk_level):
        self.risk_level = risk_level
        self.symbol = "ETHUSDT"
        self.action = "BUY"
        self.price = 10
        self.confidence = 95


# =====================================================================
# Shared execution-seam fixtures (mirrors NBF-4 harness)
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
    return manager.build_request({**schema, "amount": amount}), schema


SPOOF_RISK_VALUES = ["LOW", "MEDIUM", "HIGH", "CRITICAL"]


# =====================================================================
# T1 - risk spoof authenticity
# =====================================================================


@pytest.mark.parametrize("value", SPOOF_RISK_VALUES)
def test_t1_risk_spoof_object_is_not_interpreted_as_its_claimed_value(value):
    schema = DecisionAdapter().normalize(raw_decision(SpoofValue(value)))
    assert schema["risk_level"] == "UNKNOWN"
    assert schema["risk_level"] != value


@pytest.mark.parametrize("value", SPOOF_RISK_VALUES)
def test_t1_risk_spoof_object_with_name_is_not_interpreted_as_its_claimed_value(value):
    schema = DecisionAdapter().normalize(
        raw_decision(SpoofValueAndName(value, value))
    )
    assert schema["risk_level"] == "UNKNOWN"
    assert schema["risk_level"] != value


# =====================================================================
# T2 - no capital admission
# =====================================================================


@pytest.mark.parametrize("value", ["LOW", "MEDIUM", "HIGH"])
def test_t2_risk_spoof_grants_no_capital_admission(value):
    ledger = SpyLedger()
    manager = execution_manager(ledger)
    request, _ = path1_request(manager, SpoofValue(value))

    result = manager.risk_check(request, state())

    assert result["approved"] is False
    assert result["reason"] == "UNSUPPORTED_RISK_LEVEL"
    assert D(manager.last_risk_decision["approved_allocation"]) == D("0")
    assert ledger.reserve_calls == []
    assert manager._risk_admissions == {}


# =====================================================================
# T3 - legitimate Enum preservation
# =====================================================================


@pytest.mark.parametrize("enum_value", [RiskLevel.HIGH, RiskCategory.HIGH, RiskBucket.HIGH])
def test_t3_genuine_enum_still_normalizes_to_high(enum_value):
    assert DecisionAdapter().get_risk_level({"risk_level": enum_value}) == "HIGH"


# =====================================================================
# T4 - action spoof authenticity
# =====================================================================


def test_t4_action_spoof_buy_falls_back_to_hold():
    schema = DecisionAdapter().normalize(raw_decision("LOW", action=SpoofValue("BUY")))
    assert schema["action"] == "HOLD"


def test_t4_action_spoof_sell_falls_back_to_hold():
    schema = DecisionAdapter().normalize(raw_decision("LOW", action=SpoofValue("SELL")))
    assert schema["action"] == "HOLD"


def test_t4_genuine_decision_action_enum_still_normalizes():
    buy_schema = DecisionAdapter().normalize(raw_decision("LOW", action=DecisionAction.BUY))
    sell_schema = DecisionAdapter().normalize(raw_decision("LOW", action=DecisionAction.SELL))
    assert buy_schema["action"] == "BUY"
    assert sell_schema["action"] == "SELL"


# =====================================================================
# T5 - string syntax invariance
# =====================================================================


@pytest.mark.parametrize("value,expected", [
    ("low", "LOW"),
    (" high ", "HIGH"),
    ("RiskLevel.HIGH", "HIGH"),
    ("riskbucket.low", "LOW"),
    ('"HIGH"', "HIGH"),
    ("HIGH: reason", "HIGH"),
])
def test_t5_accepted_string_forms_are_unchanged(value, expected):
    assert DecisionAdapter().get_risk_level({"risk_level": value}) == expected


# =====================================================================
# T6 - unsupported string invariance
# =====================================================================


def test_t6_unsupported_string_normalizes_to_unknown():
    assert DecisionAdapter().get_risk_level({"risk_level": "EXTREME"}) == "UNKNOWN"


def test_t6_unsupported_string_fails_closed_at_the_execution_seam():
    ledger = SpyLedger()
    manager = execution_manager(ledger)
    request, _ = path1_request(manager, "EXTREME")

    result = manager.risk_check(request, state())

    assert result["approved"] is False
    assert result["reason"] == "UNSUPPORTED_RISK_LEVEL"
    assert D(manager.last_risk_decision["approved_allocation"]) == D("0")
    assert ledger.reserve_calls == []


# =====================================================================
# T7 - audit breadcrumb
# =====================================================================


@pytest.mark.parametrize("value", SPOOF_RISK_VALUES)
def test_t7_spoof_risk_preserves_a_diagnostic_breadcrumb(value):
    schema = DecisionAdapter().normalize(raw_decision(SpoofValue(value)))
    assert schema["risk_level"] == "UNKNOWN"
    assert "raw_risk_level" in schema["metadata"]
    assert schema["metadata"]["raw_risk_level"]


# =====================================================================
# T8 - raising property robustness
# =====================================================================


def test_t8_raising_value_property_is_never_evaluated_by_the_helper():
    # If the property were touched, this call raises RuntimeError directly.
    normalized = DecisionAdapter._normalize_enum_or_string(RaisingValue())
    assert normalize_risk(normalized) == "UNKNOWN"


def test_t8_raising_value_property_survives_the_full_adapter_pipeline():
    schema = DecisionAdapter().normalize(raw_decision(RaisingValue()))
    # A caught-and-swallowed exception would have produced None instead.
    assert schema is not None
    assert schema["risk_level"] == "UNKNOWN"


# =====================================================================
# T9 - side-effecting property robustness
# =====================================================================


def test_t9_side_effecting_value_property_is_never_evaluated_by_the_helper():
    spoof = SideEffectingValue()
    DecisionAdapter._normalize_enum_or_string(spoof)
    assert spoof.reads == 0


def test_t9_side_effecting_value_property_untouched_through_full_pipeline():
    spoof = SideEffectingValue()
    schema = DecisionAdapter().normalize(raw_decision(spoof))
    assert spoof.reads == 0
    assert schema["risk_level"] == "UNKNOWN"


# =====================================================================
# T10 - reduce-only non-trapping
# =====================================================================


def test_t10_reduce_only_exit_is_still_approved_after_spoof_normalization():
    normalized_bucket = DecisionAdapter().get_risk_level({"risk_level": SpoofValue("LOW")})
    assert normalized_bucket == "UNKNOWN"

    current = state(position(quote="100"))
    exposure_before = current.committed_quote

    result = RiskEngine(policy()).evaluate(exit_request(bucket=normalized_bucket), current)

    assert result.status is RiskDecisionStatus.APPROVE
    assert result.reason_code == "RISK_REDUCTION_APPROVED"
    assert result.approved_allocation == D("100")

    exposure_after = exposure_before - result.approved_allocation
    assert exposure_after < exposure_before
    assert exposure_after >= D("0")


def test_t10_reduce_only_exit_at_the_execution_seam_reserves_nothing():
    ledger = SpyLedger()
    manager = execution_manager(ledger)
    normalized_bucket = DecisionAdapter().get_risk_level({"risk_level": SpoofValue("HIGH")})
    request = ExecutionRequest("ETHUSDT", "SELL", 10, 100, confidence=95,
                               risk=normalized_bucket, reduce_only=True)

    result = manager.risk_check(request, state(position(quote="100")))

    assert result["approved"] is True
    assert manager.last_risk_decision["reason_code"] == "RISK_REDUCTION_APPROVED"
    assert ledger.reserve_calls == []


# =====================================================================
# T11 - supported container shapes
# =====================================================================


@pytest.mark.parametrize("value", SPOOF_RISK_VALUES)
def test_t11_dict_container_shape_fails_closed(value):
    schema = DecisionAdapter().normalize(raw_decision(SpoofValue(value)))
    assert schema["risk_level"] == "UNKNOWN"


@pytest.mark.parametrize("value", SPOOF_RISK_VALUES)
def test_t11_object_attribute_shape_fails_closed(value):
    schema = DecisionAdapter.convert(_ObjectWithRiskLevel(SpoofValue(value)))
    assert schema["risk_level"] == "UNKNOWN"


@pytest.mark.parametrize("value", SPOOF_RISK_VALUES)
def test_t11_direct_convert_call_fails_closed(value):
    schema = DecisionAdapter.convert(raw_decision(SpoofValue(value)))
    assert schema["risk_level"] == "UNKNOWN"


@pytest.mark.parametrize("risk", ["LOW", "MEDIUM", "HIGH"])
def test_t11_container_shapes_never_reserve_capital(risk):
    ledger = SpyLedger()
    manager = execution_manager(ledger)
    schema = DecisionAdapter.convert(_ObjectWithRiskLevel(SpoofValue(risk)))

    request = manager.build_request({**schema, "amount": 50})
    result = manager.risk_check(request, state())

    assert result["approved"] is False
    assert result["reason"] == "UNSUPPORTED_RISK_LEVEL"
    assert ledger.reserve_calls == []
    assert manager._risk_admissions == {}
    assert request.risk == UNSUPPORTED_RISK_SENTINEL
