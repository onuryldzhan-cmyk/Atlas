"""NBF-5: Decision.risk_level strict type contract (Policy B).

``core.decision.Decision`` declares ``risk_level: RiskLevel`` but the live
producer (``ai.core.intelligence.risk_engine.AdvisoryRiskScorer`` ->
``ai.core.intelligence.decision_builder.DecisionBuilder``) passed
``RiskCategory`` straight through, and ``Decision.__post_init__`` only
canonicalized ``str``. ``None``, integers and arbitrary objects (including
one that merely exposes ``.value``) could therefore be stored verbatim, and
serialization relied on duck-typed ``.value`` access.

Policy B: after every successful ``Decision`` construction/mutation,
``isinstance(decision.risk_level, RiskLevel)`` must hold unconditionally.
``RiskLevel`` keeps exactly LOW/MEDIUM/HIGH/CRITICAL - ``UNKNOWN`` is an
execution-normalization sentinel (NBF-4) and must never become a valid
``Decision.risk_level``.

This file does not reopen NBF-3 (CRITICAL non-executable) or NBF-4
(unsupported-risk fail-closed) - it only proves Decision's new strictness
does not change their behavior.
"""

from __future__ import annotations

import threading
from datetime import UTC, datetime
from decimal import Decimal as D

import pytest

from core.decision import Decision, DecisionAction, RiskLevel
from core.decision_adapter import DecisionAdapter
from core.execution_manager import ExecutionManager
from core.execution_models import ExecutionRequest, normalize_risk
from core.capital_reservation import CapitalReservationLedger
from core.risk_state_store import RestoredRiskState
from core.risk_engine import (
    RiskEngine as CoreRiskEngine,
    RiskPolicy,
    RiskState,
    UNSUPPORTED_RISK_SENTINEL,
)

from ai.core.intelligence.risk_engine import AdvisoryRiskScorer, RiskCategory
from ai.core.intelligence.decision_builder import DecisionBuilder
from ai.core.intelligence.agent_fusion import AgentFusionResult
from core.risk_engine import RiskBucket as ExecutableRiskBucket


# =====================================================================
# Shared execution-seam fixtures (mirrors NBF-3 / NBF-4 test helpers)
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


# =====================================================================
# Inputs
# =====================================================================

RISK_LEVEL_MEMBERS = list(RiskLevel)
RISK_CATEGORY_MEMBERS = list(RiskCategory)
EXECUTABLE_RISK_BUCKET_MEMBERS = list(ExecutableRiskBucket)
VALID_STRINGS = ["LOW", "low", "critical"]

REJECTED_STRINGS = [
    "",
    " HIGH ",
    "RiskLevel.HIGH",
    "UNKNOWN",
    "EXTREME",
    "VERY_HIGH",
    "SEVERE",
]


class _MisleadingValue:
    """Arbitrary object that duck-types ``.value`` but is not an Enum."""

    def __init__(self, value):
        self.value = value


INVALID_OBJECTS = [
    None,
    123,
    0,
    object(),
    _MisleadingValue("LOW"),
    _MisleadingValue("CRITICAL"),
]


_OMITTED = object()


def _decision(risk_level=_OMITTED, **overrides):
    kwargs = dict(
        action=DecisionAction.HOLD,
        symbol="BTCUSDT",
        confidence=50.0,
        reasoning="test",
    )
    kwargs.update(overrides)
    if risk_level is not _OMITTED:
        kwargs["risk_level"] = risk_level
    return Decision(**kwargs)


# =====================================================================
# T1 - canonical runtime type
# =====================================================================


def test_omitted_risk_level_is_canonical_type():
    decision = _decision()
    assert isinstance(decision.risk_level, RiskLevel)


@pytest.mark.parametrize("member", RISK_LEVEL_MEMBERS)
def test_risk_level_member_input_is_canonical_type(member):
    decision = _decision(risk_level=member)
    assert isinstance(decision.risk_level, RiskLevel)


@pytest.mark.parametrize("member", RISK_CATEGORY_MEMBERS)
def test_risk_category_member_input_is_canonical_type(member):
    decision = _decision(risk_level=member)
    assert isinstance(decision.risk_level, RiskLevel)


@pytest.mark.parametrize("member", EXECUTABLE_RISK_BUCKET_MEMBERS)
def test_risk_bucket_member_input_is_canonical_type(member):
    decision = _decision(risk_level=member)
    assert isinstance(decision.risk_level, RiskLevel)


@pytest.mark.parametrize("value", VALID_STRINGS)
def test_accepted_string_input_is_canonical_type(value):
    decision = _decision(risk_level=value)
    assert isinstance(decision.risk_level, RiskLevel)


# =====================================================================
# T2 - cross-enum semantic preservation
# =====================================================================


@pytest.mark.parametrize("member", RISK_CATEGORY_MEMBERS)
def test_risk_category_maps_to_matching_risk_level(member):
    decision = _decision(risk_level=member)
    assert decision.risk_level is RiskLevel[member.name]
    assert decision.risk_level.value == member.value


@pytest.mark.parametrize("member", EXECUTABLE_RISK_BUCKET_MEMBERS)
def test_risk_bucket_maps_to_matching_risk_level(member):
    decision = _decision(risk_level=member)
    assert decision.risk_level is RiskLevel[member.name]
    assert decision.risk_level.value == member.value


# =====================================================================
# T3 - live producer integration (AdvisoryRiskScorer -> DecisionBuilder -> Decision)
# =====================================================================


def test_live_producer_risk_category_is_canonicalized_to_risk_level():
    risk_result = AdvisoryRiskScorer().calculate(confidence=0.82)
    assert type(risk_result.level) is RiskCategory

    fusion = AgentFusionResult(action="BUY", confidence=0.82, scores={"BUY": 0.82})
    decision = DecisionBuilder().create(symbol="BTCUSDT", fusion=fusion, risk=risk_result)

    assert isinstance(decision.risk_level, RiskLevel)
    assert not isinstance(decision.risk_level, RiskCategory)
    assert decision.risk_level.value == risk_result.level.value


# =====================================================================
# T4 - invalid object rejection
# =====================================================================


@pytest.mark.parametrize("bad", INVALID_OBJECTS)
def test_invalid_object_construction_raises_type_error(bad):
    with pytest.raises(TypeError):
        _decision(risk_level=bad)


# =====================================================================
# T5 - unsupported strings remain rejected
# =====================================================================


@pytest.mark.parametrize("bad", REJECTED_STRINGS)
def test_unsupported_string_construction_raises_value_error(bad):
    with pytest.raises(ValueError):
        _decision(risk_level=bad)


# =====================================================================
# T6 - serialization totality
# =====================================================================

CONSTRUCTIBLE_RISK_INPUTS = (
    [_OMITTED]
    + RISK_LEVEL_MEMBERS
    + RISK_CATEGORY_MEMBERS
    + EXECUTABLE_RISK_BUCKET_MEMBERS
    + VALID_STRINGS
)


@pytest.mark.parametrize("risk_input", CONSTRUCTIBLE_RISK_INPUTS)
def test_serialization_succeeds_for_every_constructible_risk_input(risk_input):
    decision = _decision(risk_level=risk_input)

    serialized = decision.to_dict()
    summary = decision.summary()
    stringified = str(decision)
    via_getitem = decision["risk_level"]
    via_get = decision.get("risk_level")

    for value in (serialized["risk_level"], via_getitem, via_get):
        assert value in {"LOW", "MEDIUM", "HIGH", "CRITICAL"}
    assert serialized["risk_level"] in summary
    assert serialized["risk_level"] in stringified


# =====================================================================
# T7 - setitem parity
# =====================================================================


def test_setitem_accepts_lowercase_string():
    decision = _decision()
    decision["risk_level"] = "low"
    assert decision.risk_level is RiskLevel.LOW


def test_setitem_accepts_risk_category():
    decision = _decision()
    decision["risk_level"] = RiskCategory.HIGH
    assert decision.risk_level is RiskLevel.HIGH


def test_setitem_accepts_risk_bucket():
    decision = _decision()
    decision["risk_level"] = ExecutableRiskBucket.MEDIUM
    assert decision.risk_level is RiskLevel.MEDIUM


@pytest.mark.parametrize("bad", INVALID_OBJECTS)
def test_setitem_rejects_invalid_objects(bad):
    decision = _decision()
    with pytest.raises(TypeError):
        decision["risk_level"] = bad


@pytest.mark.parametrize("bad", ["UNKNOWN", "EXTREME"])
def test_setitem_rejects_unsupported_strings(bad):
    decision = _decision()
    with pytest.raises(ValueError):
        decision["risk_level"] = bad


# =====================================================================
# T8 - NBF-3 compatibility: CRITICAL stays non-executable
# =====================================================================


def test_nbf3_critical_decision_canonicalizes_and_stays_non_executable():
    decision = _decision(action=DecisionAction.BUY, risk_level=RiskCategory.CRITICAL)
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
# T9 - NBF-4 compatibility: UNKNOWN sentinel seam is untouched
# =====================================================================


def test_nbf4_decision_cannot_construct_with_unknown():
    with pytest.raises(ValueError):
        _decision(risk_level="UNKNOWN")


def test_nbf4_execution_seam_still_normalizes_unsupported_raw_risk_to_unknown():
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
# T10 - no MEDIUM (or any executable level) fail-open
# =====================================================================


@pytest.mark.parametrize("bad", INVALID_OBJECTS)
def test_invalid_input_never_silently_becomes_medium(bad):
    with pytest.raises(TypeError):
        _decision(risk_level=bad)
    # No Decision was constructed, so no risk_level - executable or
    # otherwise - was ever produced from this input.


# =====================================================================
# T11 - intentional Decision-vs-execution vocabulary divergence
# =====================================================================


@pytest.mark.parametrize("value", [" HIGH ", "RiskLevel.HIGH", "UNKNOWN"])
def test_decision_rejects_what_normalize_risk_may_accept(value):
    """Decision is a strict analytical domain object; normalize_risk is the
    syntactic execution-seam boundary. Divergence here is intentional
    architecture (see NBF-5), not a bug to reconcile."""
    with pytest.raises(ValueError):
        _decision(risk_level=value)

    # normalize_risk may resolve the same raw text at the execution seam.
    normalized = normalize_risk(value)
    assert normalized in {"HIGH", "UNKNOWN"}
