"""
core/decision.py - Decision.confidence float-preservation fix.

Root cause: Decision.__post_init__ normalized confidence via
max(0, min(float(x), 100)) - mixing an int literal (0, 100) into
max()/min() alongside a float value. Python's max()/min() return
whichever operand they select; whenever the int literal is selected
(e.g. an input at or below 0, or above 100), the earlier float() cast
is silently discarded and confidence becomes an int. This was latent
until Phase 2 Step 2C made confidence=0.0 (INSUFFICIENT_EVIDENCE) a
reachable live value, at which point `isinstance(confidence, float)`
- which the Decision contract requires (confidence: float) - could
fail.

Fix: clamp bounds are float literals (0.0, 100.0), so the result is
float regardless of which operand is selected.
"""

from __future__ import annotations

import math

import pytest

from core.decision import Decision, DecisionAction


def _decision(confidence):
    return Decision(
        action=DecisionAction.HOLD,
        symbol="BTCUSDT",
        confidence=confidence,
        reasoning="test",
    )


def test_zero_confidence_normalizes_to_float_zero():
    """Item 1: the exact case Step 2C's INSUFFICIENT_EVIDENCE reaches."""

    decision = _decision(0.0)

    assert decision.confidence == 0.0
    assert isinstance(decision.confidence, float)


def test_hundred_confidence_normalizes_to_float_hundred():
    """Item 2."""

    decision = _decision(100.0)

    assert decision.confidence == 100.0
    assert isinstance(decision.confidence, float)


def test_negative_confidence_clamps_to_float_zero():
    """Item 3."""

    decision = _decision(-25.0)

    assert decision.confidence == 0.0
    assert isinstance(decision.confidence, float)


def test_over_hundred_confidence_clamps_to_float_hundred():
    """Item 4."""

    decision = _decision(150.0)

    assert decision.confidence == 100.0
    assert isinstance(decision.confidence, float)


def test_interior_confidence_value_is_preserved_and_float():
    """Item 5: numeric behavior for a representative interior value is unchanged."""

    decision = _decision(42.36)

    assert decision.confidence == pytest.approx(42.36)
    assert isinstance(decision.confidence, float)


def test_int_input_confidence_is_still_normalized_to_float():
    """
    Non-boundary characterization: an int input (not just int-typed
    boundary literals) must also come out as float - this was already
    true before the fix and remains true after it.
    """

    decision = _decision(60)

    assert decision.confidence == 60.0
    assert isinstance(decision.confidence, float)


def test_nan_confidence_clamps_to_float_zero():
    """
    NaN/invalid handling: numeric outcome (0) is unchanged from before
    the fix; only its type changes from int to float, consistent with
    every other clamped case this fix addresses.
    """

    decision = _decision(float("nan"))

    assert decision.confidence == 0.0
    assert isinstance(decision.confidence, float)
    assert not math.isnan(decision.confidence)


def test_decision_serialization_contract_unchanged():
    """
    Item 6: to_dict()/summary()/__str__ behavior is unaffected by the
    type-preservation fix - confidence was already numerically 0/100/
    interior-correct before, only its Python type changes.
    """

    decision = _decision(0.0)

    as_dict = decision.to_dict()
    assert as_dict["confidence"] == 0.0
    assert isinstance(as_dict["confidence"], float)
    assert as_dict["action"] == "HOLD"
    assert as_dict["symbol"] == "BTCUSDT"

    assert decision.summary() == "BTCUSDT | HOLD | Confidence: 0.0% | Risk: MEDIUM"
    assert str(decision) == decision.summary()


def test_step2c_insufficient_evidence_confidence_survives_decision_construction():
    """
    Item 7: reproduces the exact Phase 2 Step 2C path - AgentFusion's
    INSUFFICIENT_EVIDENCE floor result carries confidence=0.0 (float,
    per the Step 2C fix in agent_fusion.py) into DecisionBuilder, which
    computes round(fusion.confidence * 100, 2) before handing it to
    Decision(). Confirms that value survives Decision construction
    without reverting to int.
    """

    from ai.core.intelligence.agent_fusion import AgentFusion
    from ai.core.intelligence.decision_builder import DecisionBuilder
    from ai.core.intelligence.risk_engine import AdvisoryRiskScorer

    fusion_engine = AgentFusion()
    # Only 2 configured agents (technical+momentum) - below the
    # accepted MIN_PARTICIPATING_AGENTS=3 floor.
    fusion_result = fusion_engine.fuse(
        {
            "technical": {"action": "BUY", "score": 0.85},
            "momentum": {"action": "BUY", "score": 0.70},
        }
    )
    assert fusion_result.reason == "INSUFFICIENT_EVIDENCE"
    assert fusion_result.confidence == 0.0

    risk_result = AdvisoryRiskScorer().calculate(confidence=fusion_result.confidence)
    decision = DecisionBuilder().create(
        "BTCUSDT",
        fusion_result,
        risk_result,
        agents={"momentum": {"action": "BUY", "score": 0.70}},
    )

    assert decision.confidence == 0.0
    assert isinstance(decision.confidence, float)
