"""Block 2C Parts F/G: M-2/M-3/M-4 remain latent, non-live backlog.

These are regression/architecture guards, not fixes. Per the Block 2C work
order: "Do not change behavior merely for conceptual neatness." Each test
proves the current interlock or invariant that keeps the known medium
backlog item non-executable; none of them alter production behavior.

M-2 (OPEN): removing a dissenting provider can raise AgentFusion
confidence. Not activated in Block 2 - no third evidence provider exists.
H10 proves the current provider/evidence-availability boundary that keeps
this categorically unreachable today.

M-3: ConfidenceEngine's CRITICAL risk-level penalty falls back to the same
value as MEDIUM (no explicit CRITICAL entry), but the only live call site
always passes "level": "MEDIUM". H11 proves that call site is unchanged.

M-4: the intermediate ConfidenceEngine result used for the advisory risk
record can differ from the final Decision.confidence, which remains
fusion-authoritative by design (core/../decision_builder.py). H12 proves
that authority boundary is unchanged.
"""

from __future__ import annotations

import inspect

import ai.core.atlas_brain as atlas_brain_module
from ai.core.intelligence.agent_fusion import AgentFusion
from ai.core.intelligence.confidence.confidence_engine import ConfidenceEngine
from ai.core.intelligence.decision_builder import DecisionBuilder
from ai.core.intelligence.risk_engine import AdvisoryRiskScorer
from analysis.evidence_status import MarketDataEvidenceStatus
from analysis.world_analysis_engine import WorldAnalysisEngine


# ---------------------------------------------------------------------------
# H10 - M-2 third-evidence-provider interlock remains active
# ---------------------------------------------------------------------------


def test_min_participating_agents_floor_is_still_three():
    assert AgentFusion.MIN_PARTICIPATING_AGENTS == 3


def test_only_technical_and_momentum_have_a_live_evidence_provider():
    """macro/sentiment/market_risk must still report UNAVAILABLE_NO_PROVIDER
    from the sole evidence producer; if any of these ever reports AVAILABLE,
    a third provider has gone live without an explicit M-2 resolution."""

    engine = WorldAnalysisEngine()
    market_data = engine.build_market_data("BTCUSDT", 100.0, analysis={}, score=0.5)

    evidence_status = market_data["evidence_status"]
    for agent in ("macro", "sentiment", "market_risk"):
        assert evidence_status[agent] == MarketDataEvidenceStatus.UNAVAILABLE_NO_PROVIDER.value


def test_two_agent_fusion_is_floored_to_insufficient_evidence():
    """The exact M-2 concern - dropping down to two sources - is categorically
    blocked today by the >=3 participating-agent floor."""

    fusion = AgentFusion()
    result = fusion.fuse({
        "technical": {"action": "BUY", "score": 0.90},
        "momentum": {"action": "BUY", "score": 0.90},
    })
    assert result.reason == "INSUFFICIENT_EVIDENCE"
    assert result.confidence == 0.0


def test_three_agent_fusion_clears_the_floor():
    """Characterizes the boundary: a genuine third source is what would let
    fusion clear MIN_PARTICIPATING_AGENTS - confirming the floor is real and
    not accidentally unreachable in both directions."""

    fusion = AgentFusion()
    result = fusion.fuse({
        "technical": {"action": "BUY", "score": 0.90},
        "momentum": {"action": "BUY", "score": 0.90},
        "risk": {"action": "BUY", "score": 0.90},
    })
    assert result.reason != "INSUFFICIENT_EVIDENCE"
    assert result.confidence > 0.0


# ---------------------------------------------------------------------------
# H11 - M-3 remains non-live
# ---------------------------------------------------------------------------


def test_confidence_engine_has_no_explicit_critical_penalty():
    """Characterizes the latent defect: CRITICAL is not a distinct penalty
    bucket, so an unknown/CRITICAL level silently falls back to the same
    0.20 penalty as MEDIUM. Documented, not fixed, per the work order."""

    engine = ConfidenceEngine()
    medium_penalty = engine.calculate_risk_penalty({"level": "MEDIUM"})
    critical_penalty = engine.calculate_risk_penalty({"level": "CRITICAL"})
    assert medium_penalty == critical_penalty == 0.20


def test_live_call_site_always_passes_medium_risk_level():
    """The only production caller of ConfidenceEngine.calculate() must still
    hardcode 'level': 'MEDIUM'. If this changes to a dynamic risk level
    without an explicit M-3 resolution, this guard must fail."""

    source = inspect.getsource(atlas_brain_module)
    assert '"level": "MEDIUM"' in source or "'level': 'MEDIUM'" in source


# ---------------------------------------------------------------------------
# H12 - M-4 Decision.confidence authority is unchanged
# ---------------------------------------------------------------------------


def test_decision_builder_create_has_no_confidence_override_parameter():
    """Structural proof that DecisionBuilder.create() cannot accept an
    external confidence value: only fusion.confidence can set it."""

    parameters = set(inspect.signature(DecisionBuilder.create).parameters)
    assert "confidence" not in parameters
    assert "confidence_result" not in parameters


def test_decision_confidence_is_fusion_authoritative_not_intermediate():
    """Reproduces the exact Phase-2 wiring: an intermediate ConfidenceEngine
    result is computed alongside fusion, but only fusion.confidence reaches
    Decision.confidence."""

    fusion = AgentFusion()
    fusion_result = fusion.fuse({
        "technical": {"action": "BUY", "score": 0.90},
        "momentum": {"action": "BUY", "score": 0.90},
        "risk": {"action": "BUY", "score": 0.90},
    })
    assert fusion_result.confidence > 0.0

    # An intermediate confidence result deliberately different from fusion.
    intermediate = ConfidenceEngine().calculate(
        {"technical": {"score": 0.1}}, {}, {"level": "MEDIUM"}, expected_agent_count=1,
    )
    assert intermediate.value != fusion_result.confidence

    risk_result = AdvisoryRiskScorer().calculate(confidence=fusion_result.confidence)
    decision = DecisionBuilder().create("BTCUSDT", fusion_result, risk_result)

    assert decision.confidence == round(fusion_result.confidence * 100, 2)
