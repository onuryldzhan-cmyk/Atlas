"""NBF-7: Decision.risk_level post-construction attribute-assignment invariant.

NBF-5 established that ``isinstance(decision.risk_level, RiskLevel)`` must
hold for every successfully constructed/mutated ``Decision``, and NBF-6
closed the ``DecisionAdapter`` enum-authenticity gap. Neither closed ordinary
attribute assignment: ``decision.risk_level = <anything>`` bypassed
``_coerce_risk_level`` entirely, so an arbitrary object (including one that
merely duck-types ``.value``, e.g. ``Spoof("LOW")``) could be stored
verbatim. ``Decision.to_dict()`` trusts ``.value`` unconditionally and
``MarketLoop`` calls ``Decision.to_dict()`` before ``DecisionAdapter`` ever
sees the object, so the spoof became the genuine string ``"LOW"`` before
NBF-6's authenticity check was ever reached - defeating NBF-6 downstream and
risking ``RISK_APPROVED`` with non-zero allocation and capital reservation
for a decision Atlas never actually classified.

Policy B: ``Decision.__setattr__`` is the lifetime enforcement choke point.
Every write to ``risk_level`` - construction, ``__setitem__``, or ordinary
attribute assignment - routes through the single canonical
``_coerce_risk_level`` authority, so the invariant holds unconditionally for
the object's entire lifetime, not just at construction.

This file does not reopen NBF-3 (CRITICAL non-executable), NBF-4 (unsupported
risk fail-closed), NBF-5 (construction/setitem type contract) or NBF-6
(adapter enum authenticity) - it only proves attribute assignment is now
covered by the same contract and that this closure does not disturb any of
them.
"""

from __future__ import annotations

import copy
import dataclasses
import pickle
import threading
from datetime import UTC, datetime
from decimal import Decimal as D

import pytest

from core.decision import Decision, DecisionAction, RiskLevel, _coerce_risk_level
from core.decision_adapter import DecisionAdapter
from core.execution_manager import ExecutionManager
from core.execution_models import ExecutionRequest
from core.capital_reservation import CapitalReservationLedger
from core.risk_state_store import RestoredRiskState
from core.market_loop import MarketLoop
from core.risk_engine import (
    RiskEngine as CoreRiskEngine,
    RiskPolicy,
    RiskState,
)

from ai.core.intelligence.risk_engine import RiskCategory
from core.risk_engine import RiskBucket as ExecutableRiskBucket


# =====================================================================
# Shared execution-seam fixtures (mirrors NBF-3/4/5/6 test helpers)
# =====================================================================


def policy(**changes):
    values = {"total_capital": D("1000")}
    values.update(changes)
    return RiskPolicy(**values)


def risk_state(pnl="0", peak="1000", equity="1000", ready=True):
    return RiskState((), D("0"), D(pnl), D(peak), D(equity), ready,
                     datetime.now(UTC).date().isoformat(), "phase3-risk-v1")


class MemoryStore:
    def __init__(self):
        self.items = ()

    def load(self):
        return self.items

    def save(self, items):
        self.items = tuple(items)


class MemoryRiskStateStore:
    def load(self, *, expected_policy_version, today_utc):
        return RestoredRiskState(today_utc, D("0"), D("1000"), D("1000"),
                                 expected_policy_version)


def execution_manager():
    manager = ExecutionManager.__new__(ExecutionManager)
    manager.risk_engine = CoreRiskEngine(policy())
    manager.reservation_ledger = CapitalReservationLedger(MemoryStore(), D("800"))
    manager.risk_state_store = MemoryRiskStateStore()
    manager.position_controller = None
    manager.capital_manager = None
    manager.last_risk_decision = None
    manager._risk_admissions = {}
    manager.mode = "PAPER"
    manager.event_bus = None
    manager._lock = threading.RLock()
    manager.errors = []
    return manager


def _decision(**overrides):
    kwargs = dict(
        action=DecisionAction.HOLD,
        symbol="BTCUSDT",
        confidence=50.0,
        reasoning="test",
    )
    kwargs.update(overrides)
    return Decision(**kwargs)


# =====================================================================
# Inputs
# =====================================================================

RISK_LEVEL_MEMBERS = list(RiskLevel)
RISK_CATEGORY_MEMBERS = list(RiskCategory)
EXECUTABLE_RISK_BUCKET_MEMBERS = list(ExecutableRiskBucket)
VALID_STRINGS = ["LOW", "low", "critical"]

ACCEPTED_INPUTS = (
    RISK_LEVEL_MEMBERS
    + RISK_CATEGORY_MEMBERS
    + EXECUTABLE_RISK_BUCKET_MEMBERS
    + VALID_STRINGS
)

REJECTED_STRINGS = [
    "",
    " HIGH ",
    "RiskLevel.HIGH",
    "UNKNOWN",
    "EXTREME",
    "VERY_HIGH",
]


class Spoof:
    """Arbitrary object that duck-types ``.value`` but is not an Enum."""

    def __init__(self, value):
        self.value = value


INVALID_OBJECTS = [
    None,
    123,
    0,
    object(),
    Spoof("LOW"),
    Spoof("CRITICAL"),
]


def _expected_level(member_or_string):
    if isinstance(member_or_string, str):
        return RiskLevel(member_or_string.upper())
    return RiskLevel[member_or_string.name]


# =====================================================================
# T1 - lifetime type invariant under direct assignment
# =====================================================================


@pytest.mark.parametrize("value", ACCEPTED_INPUTS)
def test_direct_assignment_lifetime_type_invariant(value):
    decision = _decision()
    decision.risk_level = value
    assert isinstance(decision.risk_level, RiskLevel)
    assert decision.risk_level is _expected_level(value)


# =====================================================================
# T2 - three-path equivalence
# =====================================================================


@pytest.mark.parametrize("value", ACCEPTED_INPUTS)
def test_three_paths_produce_identical_canonical_member(value):
    via_constructor = Decision(
        action=DecisionAction.HOLD, symbol="BTCUSDT", confidence=50.0,
        reasoning="test", risk_level=value,
    )

    via_setitem = _decision()
    via_setitem["risk_level"] = value

    via_attribute = _decision()
    via_attribute.risk_level = value

    expected = _expected_level(value)
    assert via_constructor.risk_level is expected
    assert via_setitem.risk_level is expected
    assert via_attribute.risk_level is expected


# =====================================================================
# T3 - rejected-path equivalence
# =====================================================================


@pytest.mark.parametrize("bad", INVALID_OBJECTS)
def test_rejected_objects_raise_type_error_on_every_path(bad):
    with pytest.raises(TypeError) as construct_exc:
        Decision(action=DecisionAction.HOLD, symbol="BTCUSDT",
                 confidence=50.0, reasoning="test", risk_level=bad)

    d1 = _decision()
    with pytest.raises(TypeError) as setitem_exc:
        d1["risk_level"] = bad

    d2 = _decision()
    with pytest.raises(TypeError) as attr_exc:
        d2.risk_level = bad

    assert construct_exc.type is setitem_exc.type is attr_exc.type is TypeError


@pytest.mark.parametrize("bad", REJECTED_STRINGS)
def test_rejected_strings_raise_value_error_on_every_path(bad):
    with pytest.raises(ValueError) as construct_exc:
        Decision(action=DecisionAction.HOLD, symbol="BTCUSDT",
                 confidence=50.0, reasoning="test", risk_level=bad)

    d1 = _decision()
    with pytest.raises(ValueError) as setitem_exc:
        d1["risk_level"] = bad

    d2 = _decision()
    with pytest.raises(ValueError) as attr_exc:
        d2.risk_level = bad

    assert construct_exc.type is setitem_exc.type is attr_exc.type is ValueError


# =====================================================================
# T4 - anti-laundering: the exact previously-dangerous shape
# =====================================================================


@pytest.mark.parametrize("spoofed", ["LOW", "CRITICAL"])
def test_spoof_assignment_is_rejected_before_serialization(spoofed):
    decision = _decision()
    original_risk_level = decision.risk_level

    with pytest.raises(TypeError):
        decision.risk_level = Spoof(spoofed)

    # The rejected write must not have landed: risk_level is unchanged and
    # still the canonical type, so to_dict() cannot possibly leak the spoof.
    assert decision.risk_level is original_risk_level
    assert isinstance(decision.risk_level, RiskLevel)
    assert decision.to_dict()["risk_level"] == original_risk_level.value


def test_spoof_assignment_never_reaches_to_dict_as_low():
    decision = _decision(risk_level=RiskLevel.HIGH)

    with pytest.raises(TypeError):
        decision.risk_level = Spoof("LOW")

    assert decision.to_dict()["risk_level"] == "HIGH"
    assert decision.to_dict()["risk_level"] != "LOW"


# =====================================================================
# T5 - serialization totality after direct assignment
# =====================================================================


@pytest.mark.parametrize("value", ACCEPTED_INPUTS)
def test_serialization_totality_after_direct_assignment(value):
    decision = _decision()
    decision.risk_level = value

    serialized = decision.to_dict()
    summary = decision.summary()
    stringified = str(decision)
    via_getitem = decision["risk_level"]
    via_get = decision.get("risk_level")

    for result in (serialized["risk_level"], via_getitem, via_get):
        assert result in {"LOW", "MEDIUM", "HIGH", "CRITICAL"}
    assert serialized["risk_level"] in summary
    assert serialized["risk_level"] in stringified


# =====================================================================
# T6 - MarketLoop laundering regression
# =====================================================================


def test_market_loop_emits_canonical_risk_after_legitimate_assignment():
    decision = _decision()
    decision.risk_level = RiskCategory.HIGH

    converted = MarketLoop._decision_to_dict(decision)
    assert converted["risk_level"] == "HIGH"


def test_market_loop_never_receives_spoofed_risk():
    decision = _decision(risk_level=RiskLevel.MEDIUM)

    with pytest.raises(TypeError):
        decision.risk_level = Spoof("LOW")

    converted = MarketLoop._decision_to_dict(decision)
    assert converted["risk_level"] == "MEDIUM"
    assert converted["risk_level"] != "LOW"


# =====================================================================
# T7 - dataclass mechanics
# =====================================================================


def test_default_construction_uses_medium():
    decision = _decision()
    assert decision.risk_level is RiskLevel.MEDIUM


def test_dataclass_fields_unchanged():
    names = [f.name for f in dataclasses.fields(Decision)]
    assert names == [
        "action", "symbol", "confidence", "reasoning",
        "risk_level", "strategy", "created_at", "metadata",
    ]


def test_asdict_reflects_canonical_member():
    decision = _decision(risk_level=RiskCategory.HIGH)
    as_dict = dataclasses.asdict(decision)
    assert as_dict["risk_level"] is RiskLevel.HIGH


def test_replace_preserves_invariant_and_allows_direct_field_change():
    decision = _decision()
    replaced = dataclasses.replace(decision, risk_level=RiskLevel.CRITICAL)
    assert replaced.risk_level is RiskLevel.CRITICAL
    assert isinstance(replaced.risk_level, RiskLevel)

    replaced.risk_level = "low"
    assert replaced.risk_level is RiskLevel.LOW


def test_deepcopy_preserves_canonical_type_and_independence():
    decision = _decision(risk_level=RiskLevel.HIGH)
    cloned = copy.deepcopy(decision)
    assert cloned.risk_level is RiskLevel.HIGH

    cloned.risk_level = RiskLevel.LOW
    assert decision.risk_level is RiskLevel.HIGH
    assert cloned.risk_level is RiskLevel.LOW


def test_pickle_round_trip_preserves_canonical_type():
    decision = _decision(risk_level=RiskLevel.CRITICAL)
    restored = pickle.loads(pickle.dumps(decision))
    assert restored.risk_level is RiskLevel.CRITICAL
    assert isinstance(restored.risk_level, RiskLevel)


# =====================================================================
# T8 - NBF-3 compatibility: direct assignment of RiskCategory.CRITICAL
# =====================================================================


def test_nbf3_direct_assignment_critical_stays_non_executable():
    decision = _decision(action=DecisionAction.BUY)
    decision.risk_level = RiskCategory.CRITICAL
    assert decision.risk_level is RiskLevel.CRITICAL

    manager = execution_manager()
    request = ExecutionRequest(
        decision.symbol, decision.action.value, 10, 50,
        confidence=95, risk=decision.risk_level.value,
    )
    result = manager.risk_check(request, risk_state())

    assert result["approved"] is False
    assert result["reason"] == "CRITICAL_RISK_NOT_EXECUTABLE"
    assert D(manager.last_risk_decision["approved_allocation"]) == D("0")


# =====================================================================
# T9 - NBF-4 compatibility: "UNKNOWN" stays invalid at the Decision boundary
# =====================================================================


def test_nbf4_direct_assignment_rejects_unknown():
    decision = _decision()
    with pytest.raises(ValueError):
        decision.risk_level = "UNKNOWN"


def test_nbf4_execution_seam_still_normalizes_unsupported_raw_risk():
    from core.risk_engine import UNSUPPORTED_RISK_SENTINEL

    manager = execution_manager()
    schema = DecisionAdapter().normalize(
        {"action": "BUY", "symbol": "ETHUSDT", "confidence": 95,
         "price": 10, "amount": 50, "risk_level": "EXTREME"}
    )
    request = manager.build_request({**schema, "amount": 50})

    assert request.risk == UNSUPPORTED_RISK_SENTINEL

    result = manager.risk_check(request, risk_state())
    assert result["approved"] is False
    assert result["reason"] == "UNSUPPORTED_RISK_LEVEL"


# =====================================================================
# T10 - NBF-5 compatibility: constructor/setitem contract re-verified
# =====================================================================


@pytest.mark.parametrize("member", RISK_LEVEL_MEMBERS)
def test_nbf5_constructor_still_canonicalizes(member):
    decision = _decision(risk_level=member)
    assert isinstance(decision.risk_level, RiskLevel)


@pytest.mark.parametrize("bad", INVALID_OBJECTS)
def test_nbf5_setitem_still_rejects_invalid_objects(bad):
    decision = _decision()
    with pytest.raises(TypeError):
        decision["risk_level"] = bad


# =====================================================================
# T11 - NBF-6 compatibility: raw adapter spoof still resolves to UNKNOWN,
# and a Decision spoof can no longer even be assigned.
# =====================================================================


def test_nbf6_adapter_spoof_still_resolves_to_unknown():
    class SpoofValue:
        def __init__(self, value):
            self.value = value

    normalized = DecisionAdapter().normalize(
        {"action": "BUY", "symbol": "ETHUSDT", "confidence": 95,
         "price": 10, "amount": 50, "risk_level": SpoofValue("LOW")}
    )
    assert normalized["risk_level"] != "LOW"


def test_nbf6_decision_spoof_cannot_be_assigned():
    decision = _decision()
    with pytest.raises(TypeError):
        decision.risk_level = Spoof("LOW")


# =====================================================================
# Canonical-authority sanity: __setattr__ delegates to the same helper
# =====================================================================


def test_setattr_and_coerce_helper_agree():
    for value in ACCEPTED_INPUTS:
        decision = _decision()
        decision.risk_level = value
        assert decision.risk_level is _coerce_risk_level(value)


def test_non_risk_level_attribute_assignment_is_unaffected():
    decision = _decision()
    decision.symbol = "ETHUSDT"
    decision.strategy = "OtherStrategy"
    assert decision.symbol == "ETHUSDT"
    assert decision.strategy == "OtherStrategy"
