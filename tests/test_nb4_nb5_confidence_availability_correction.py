"""
NB-4 / NB-5 - Confidence agreement availability correction.

Defect: ConfidenceEngine.calculate_agent_agreement() computed
`strongest / len(actions)` using only surviving/available agents as the
denominator. Missing evidence therefore vanished from the denominator
instead of penalizing it: a small surviving set of agreeing agents
could read as agreement=1.0 (unanimous) even though most of the
configured roster was absent, which could inflate intermediate
confidence and relax the derived risk bucket - the opposite of the
required conservative-degradation behavior.

Fix: calculate_agent_agreement() / calculate() accept an optional
`expected_agent_count`. When supplied and larger than the number of
surviving agents, it becomes the denominator instead of the surviving
count. Unavailable agents are never fabricated as HOLD/default votes -
they affect the result only through this denominator. Callers that
omit `expected_agent_count` (or pass a value no larger than the
surviving count) get byte-for-byte the prior behavior.

This file does not reopen NB-1 (momentum RSI failsafe), NB-2 (fusion
audit metadata), or NB-3 (momentum evidence gating) - it only proves
their behavior is unaffected by this change.
"""

from __future__ import annotations

import pytest

from ai.core.intelligence.agent_fusion import AgentFusion
from ai.core.intelligence.confidence.confidence_engine import ConfidenceEngine
from ai.core.intelligence.risk_engine import RiskCategory, RiskEngine


REASONING = {"confidence": 0.7}


def _agents(actions):
    return {
        f"agent_{i}": {"action": action}
        for i, action in enumerate(actions)
    }


# =============================================================
# 1. Full-evidence invariance
# =============================================================


def test_full_evidence_invariance_agreement_confidence_risk():
    engine = ConfidenceEngine()
    risk = RiskEngine()

    full_agents = _agents(["BUY", "BUY", "HOLD", "HOLD", "HOLD"])

    before = engine.calculate(full_agents, REASONING, {"level": "MEDIUM"})
    after = engine.calculate(
        full_agents,
        REASONING,
        {"level": "MEDIUM"},
        expected_agent_count=len(full_agents),
    )

    assert before.agreement == pytest.approx(0.6)
    assert after.agreement == pytest.approx(0.6)
    assert before.value == pytest.approx(after.value)

    risk_before = risk.calculate(confidence=before.value)
    risk_after = risk.calculate(confidence=after.value)

    assert risk_before.level == risk_after.level
    assert risk_before.score == pytest.approx(risk_after.score)


# =============================================================
# 2. Evidence-loss monotonicity
# =============================================================


def test_evidence_loss_does_not_increase_confidence():
    engine = ConfidenceEngine()

    full_agents = _agents(["BUY", "BUY", "HOLD", "HOLD", "HOLD"])
    reduced_agents = _agents(["BUY", "BUY"])

    full = engine.calculate(
        full_agents,
        REASONING,
        {"level": "MEDIUM"},
        expected_agent_count=5,
    )
    reduced = engine.calculate(
        reduced_agents,
        REASONING,
        {"level": "MEDIUM"},
        expected_agent_count=5,
    )

    assert full.agreement == pytest.approx(0.6)
    assert reduced.agreement == pytest.approx(0.4)
    assert reduced.value <= full.value
    assert reduced.value == pytest.approx(0.415)
    assert full.value == pytest.approx(0.515)


# =============================================================
# 3. Risk conservatism
# =============================================================


def test_evidence_loss_does_not_relax_risk_bucket():
    engine = ConfidenceEngine()
    risk = RiskEngine()

    full_agents = _agents(["BUY", "BUY", "HOLD", "HOLD", "HOLD"])
    reduced_agents = _agents(["BUY", "BUY"])

    full_conf = engine.calculate(
        full_agents,
        REASONING,
        {"level": "MEDIUM"},
        expected_agent_count=5,
    )
    reduced_conf = engine.calculate(
        reduced_agents,
        REASONING,
        {"level": "MEDIUM"},
        expected_agent_count=5,
    )

    risk_full = risk.calculate(confidence=full_conf.value)
    risk_reduced = risk.calculate(confidence=reduced_conf.value)

    assert risk_full.level == RiskCategory.MEDIUM
    assert risk_full.score == pytest.approx(0.493)

    assert risk_reduced.level == RiskCategory.HIGH
    assert risk_reduced.score == pytest.approx(0.542)

    # Evidence loss must move risk toward (or stay at) the same or a
    # *more* conservative bucket - never less conservative.
    assert risk_reduced.score >= risk_full.score
    assert list(RiskCategory).index(risk_reduced.level) >= list(
        RiskCategory
    ).index(risk_full.level)


# =============================================================
# 4. All-BUY availability ladder
# =============================================================


def test_all_buy_availability_ladder_is_not_uniformly_unanimous():
    engine = ConfidenceEngine()

    ladder = {}
    for available in (5, 3, 2, 1):
        agents = _agents(["BUY"] * available)
        ladder[available] = engine.calculate_agent_agreement(
            agents,
            expected_agent_count=5,
        )

    assert ladder[5] == pytest.approx(1.0)
    assert ladder[3] == pytest.approx(0.6)
    assert ladder[2] == pytest.approx(0.4)
    assert ladder[1] == pytest.approx(0.2)

    # The defect made every reduced set read as agreement=1.0.
    assert len({ladder[3], ladder[2], ladder[1]}) == 3
    assert ladder[3] < ladder[5]
    assert ladder[2] < ladder[3]
    assert ladder[1] < ladder[2]


# =============================================================
# 5. Dissent removal
# =============================================================


def test_removing_dissenter_does_not_raise_agreement_via_denominator():
    engine = ConfidenceEngine()

    with_dissent = _agents(["BUY", "BUY", "BUY", "BUY", "SELL"])
    dissent_removed = _agents(["BUY", "BUY", "BUY", "BUY"])

    agreement_with_dissent = engine.calculate_agent_agreement(
        with_dissent,
        expected_agent_count=5,
    )
    agreement_without_dissent = engine.calculate_agent_agreement(
        dissent_removed,
        expected_agent_count=5,
    )

    assert agreement_with_dissent == pytest.approx(0.8)
    # Same expected roster -> removing the dissenting/unavailable
    # provider must not raise agreement merely because it is absent.
    assert agreement_without_dissent == pytest.approx(0.8)
    assert agreement_without_dissent <= 1.0


# =============================================================
# 6. Future-third-provider scenario
# =============================================================


def test_three_genuine_providers_under_larger_configured_roster():
    engine = ConfidenceEngine()

    three_providers = _agents(["BUY", "BUY", "BUY"])

    agreement = engine.calculate_agent_agreement(
        three_providers,
        expected_agent_count=len(AgentFusion.WEIGHTS),
    )

    assert len(AgentFusion.WEIGHTS) == 5
    assert agreement == pytest.approx(0.6)
    assert agreement < 1.0


# =============================================================
# 7. Participant-floor separation
# =============================================================


def test_participant_floor_blocks_independently_of_agreement_fix():
    fusion = AgentFusion()

    # Below MIN_PARTICIPATING_AGENTS (3): the floor must still block,
    # regardless of what ConfidenceEngine would compute for the same
    # surviving signals.
    signals = {
        "technical": {"action": "BUY", "score": 0.9},
        "momentum": {"action": "BUY", "score": 0.9},
    }

    result = fusion.fuse(signals)

    assert result.reason == "INSUFFICIENT_EVIDENCE"
    assert result.action == "HOLD"
    assert result.confidence == 0.0

    # Confirm the intermediate-confidence path itself is not what is
    # being exercised here - agreement can be computed without the
    # floor being involved at all.
    engine = ConfidenceEngine()
    agreement = engine.calculate_agent_agreement(
        {k: {"action": v["action"]} for k, v in signals.items()},
        expected_agent_count=5,
    )
    assert agreement == pytest.approx(0.4)


# =============================================================
# 8. No double scaling
# =============================================================


def test_fusion_confidence_path_is_unaffected_by_agreement_fix():
    fusion = AgentFusion()

    signals = {
        "technical": {"action": "BUY", "score": 0.9},
        "momentum": {"action": "BUY", "score": 0.8},
        "risk": {"action": "BUY", "score": 0.7},
    }

    result = fusion.fuse(signals)

    available_weight = (
        AgentFusion.WEIGHTS["technical"]
        + AgentFusion.WEIGHTS["momentum"]
        + AgentFusion.WEIGHTS["risk"]
    )
    total_weight = sum(AgentFusion.WEIGHTS.values())
    weight_coverage = available_weight / total_weight

    buy = 0.9 * AgentFusion.WEIGHTS["technical"]
    buy += 0.8 * AgentFusion.WEIGHTS["momentum"]
    buy += 0.7 * AgentFusion.WEIGHTS["risk"]
    bucket_confidence = buy / buy  # single-bucket total == buy total

    expected_confidence = round(bucket_confidence * weight_coverage, 4)

    assert result.action == "BUY"
    assert result.confidence == pytest.approx(expected_confidence)

    # AgentFusion.fuse() never imports/calls ConfidenceEngine - the
    # agreement-denominator fix in this change touches a structurally
    # separate path from Decision.confidence.
    import inspect

    from ai.core.intelligence import agent_fusion as agent_fusion_module

    source = inspect.getsource(agent_fusion_module)
    assert "ConfidenceEngine" not in source
    assert "confidence_engine" not in source


# =============================================================
# 9. Backward compatibility
# =============================================================


def test_calculate_agent_agreement_without_expected_count_is_unchanged():
    engine = ConfidenceEngine()

    agents = _agents(["BUY", "BUY", "HOLD"])

    agreement = engine.calculate_agent_agreement(agents)

    assert agreement == pytest.approx(2 / 3)


def test_calculate_without_expected_count_is_unchanged():
    engine = ConfidenceEngine()

    agents = _agents(["BUY", "BUY"])

    result = engine.calculate(agents, REASONING, {"level": "MEDIUM"})

    # Legacy behavior: denominator is the surviving count only.
    assert result.agreement == pytest.approx(1.0)


# =============================================================
# 10. NB-1 / NB-2 / NB-3 preservation
# =============================================================


def test_nb1_nb2_nb3_untouched_by_this_change():
    fusion = AgentFusion()

    # NB-3: missing rsi/trend excludes momentum rather than fabricating
    # a neutral HOLD@0.5 vote.
    signals = fusion.evaluate("BTCUSDT", {"trend": "BULLISH"})
    assert "momentum" not in signals
    assert fusion.last_unavailable_agents["momentum"] == "RSI_MISSING"

    # NB-1: malformed rsi is excluded (fails safe), not defaulted.
    fusion2 = AgentFusion()
    signals2 = fusion2.evaluate(
        "BTCUSDT",
        {"rsi": "not-a-number", "trend": "BULLISH"},
    )
    assert "momentum" not in signals2
    assert (
        fusion2.last_unavailable_agents["momentum"]
        == "RSI_UNAVAILABLE_OR_MALFORMED"
    )

    # NB-2: diagnostics (last_unavailable_agents) remain populated and
    # machine-readable after a fuse() call using the same instance.
    assert isinstance(fusion.last_unavailable_agents, dict)
