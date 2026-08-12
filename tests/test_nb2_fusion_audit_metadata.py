"""
NB-2 - Fusion audit metadata propagation.

Post-freeze follow-up to Phase 2 / Step 2C (Market-Data Evidence
Semantics, FROZEN). Step 2C's independent review found that
AgentFusion.FusionResult.reason ("FUSED_EVIDENCE" /
"INSUFFICIENT_EVIDENCE") and AgentFusion.last_unavailable_agents
existed only in memory and were never persisted into Decision.metadata
or any audit surface - a HOLD @ 0.0 could be observed but its cause
could only be inferred, not read.

This is strictly additive, metadata-only wiring: DecisionBuilder.create()
gains an optional unavailable_agents parameter and writes two new
Decision.metadata keys - "fusion_reason" and "unavailable_agents" - and
nothing about action/confidence/risk_level/fusion arithmetic/evidence
floor/weights changes. Step 2C behavior itself is not reopened; these
tests exercise only the new metadata surface.
"""

from __future__ import annotations

import json

from analysis.evidence_status import MarketDataEvidenceStatus
from analysis.world_analysis_engine import WorldAnalysisEngine
from ai.core.atlas_brain import AtlasBrain
from ai.core.intelligence.agent_fusion import AgentFusion
from ai.core.intelligence.decision_builder import DecisionBuilder
from ai.core.intelligence.risk_engine import AdvisoryRiskScorer


def _build_decision(signals, unavailable_agents=None):
    fusion_engine = AgentFusion()
    fusion_result = fusion_engine.fuse(signals)
    risk_result = AdvisoryRiskScorer().calculate(confidence=fusion_result.confidence)

    return DecisionBuilder().create(
        "BTCUSDT",
        fusion_result,
        risk_result,
        agents=signals,
        unavailable_agents=unavailable_agents,
    )


# =============================================================
# 1. Normal fused decision persists FUSED_EVIDENCE
# =============================================================


def test_fused_decision_persists_fused_evidence_reason():
    decision = _build_decision(
        {
            "technical": {"action": "BUY", "score": 0.85},
            "momentum": {"action": "BUY", "score": 0.70},
            "macro": {"action": "BUY", "score": 0.90},
        }
    )

    assert decision.metadata["fusion_reason"] == "FUSED_EVIDENCE"


# =============================================================
# 2. Insufficient-evidence decision persists INSUFFICIENT_EVIDENCE
# =============================================================


def test_insufficient_evidence_decision_persists_reason():
    decision = _build_decision(
        {
            "technical": {"action": "BUY", "score": 0.85},
            "momentum": {"action": "BUY", "score": 0.70},
        }
    )

    assert decision.action.value == "HOLD"
    assert decision.confidence == 0.0
    assert decision.metadata["fusion_reason"] == "INSUFFICIENT_EVIDENCE"


# =============================================================
# 3. Unavailable agents are persisted deterministically
# =============================================================


def test_unavailable_agents_persisted_deterministically():
    unavailable = {
        "sentiment": "UNAVAILABLE_NO_PROVIDER",
        "macro": "UNAVAILABLE_NO_PROVIDER",
        "risk": "UNAVAILABLE_NO_PROVIDER",
    }

    decision = _build_decision(
        {"technical": {"action": "BUY", "score": 0.85}, "momentum": {"action": "BUY", "score": 0.70}},
        unavailable_agents=unavailable,
    )

    assert decision.metadata["unavailable_agents"] == {
        "macro": "UNAVAILABLE_NO_PROVIDER",
        "risk": "UNAVAILABLE_NO_PROVIDER",
        "sentiment": "UNAVAILABLE_NO_PROVIDER",
    }
    assert list(decision.metadata["unavailable_agents"].keys()) == [
        "macro",
        "risk",
        "sentiment",
    ]

    # Repeated construction from the same (differently ordered) input
    # produces identical, identically ordered output.
    reordered = {
        "risk": "UNAVAILABLE_NO_PROVIDER",
        "sentiment": "UNAVAILABLE_NO_PROVIDER",
        "macro": "UNAVAILABLE_NO_PROVIDER",
    }
    decision2 = _build_decision(
        {"technical": {"action": "BUY", "score": 0.85}, "momentum": {"action": "BUY", "score": 0.70}},
        unavailable_agents=reordered,
    )

    assert (
        decision.metadata["unavailable_agents"]
        == decision2.metadata["unavailable_agents"]
    )
    assert list(decision.metadata["unavailable_agents"].keys()) == list(
        decision2.metadata["unavailable_agents"].keys()
    )


# =============================================================
# 4. No raw market data or malformed object is persisted
# =============================================================


def test_malformed_or_non_string_diagnostics_are_dropped_not_persisted():
    malformed = {
        "macro": "UNAVAILABLE_NO_PROVIDER",
        "sentiment": {"nested": "object"},
        123: "NUMERIC_KEY_REJECTED",
        "risk": Exception("boom"),
    }

    decision = _build_decision(
        {"technical": {"action": "BUY", "score": 0.85}, "momentum": {"action": "BUY", "score": 0.70}},
        unavailable_agents=malformed,
    )

    assert decision.metadata["unavailable_agents"] == {
        "macro": "UNAVAILABLE_NO_PROVIDER",
    }

    # The whole payload must be JSON-serializable (proves no exception
    # repr, raw object, or arbitrary payload leaked through).
    json.dumps(decision.metadata["unavailable_agents"])


def test_arbitrary_object_diagnostics_argument_does_not_raise():
    decision = _build_decision(
        {"technical": {"action": "BUY", "score": 0.85}, "momentum": {"action": "BUY", "score": 0.70}},
        unavailable_agents=object(),
    )

    assert decision.metadata["unavailable_agents"] == {}


# =============================================================
# 5. Missing diagnostic state does not break Decision construction
# =============================================================


def test_missing_diagnostics_does_not_break_decision_construction():
    decision = _build_decision(
        {
            "technical": {"action": "BUY", "score": 0.85},
            "momentum": {"action": "BUY", "score": 0.70},
            "macro": {"action": "BUY", "score": 0.90},
        },
        unavailable_agents=None,
    )

    assert decision.action.value == "BUY"
    assert decision.metadata["unavailable_agents"] == {}
    assert decision.metadata["fusion_reason"] == "FUSED_EVIDENCE"


def test_decision_builder_call_without_unavailable_agents_argument_still_works():
    fusion_engine = AgentFusion()
    fused = fusion_engine.fuse({})
    risk = AdvisoryRiskScorer().calculate(confidence=fused.confidence)

    decision = DecisionBuilder().create(
        "BTCUSDT",
        fused,
        risk,
    )

    assert decision.action.value == "HOLD"
    assert decision.confidence == 0.0
    assert decision.metadata["fusion_reason"] == "INSUFFICIENT_EVIDENCE"
    assert decision.metadata["unavailable_agents"] == {}


# =============================================================
# 6. action/confidence/risk_level identical with and without
#    diagnostic propagation
# =============================================================


def test_action_confidence_risk_level_unchanged_by_diagnostic_propagation():
    signals = {
        "technical": {"action": "BUY", "score": 0.85},
        "momentum": {"action": "BUY", "score": 0.70},
    }

    without = _build_decision(signals, unavailable_agents=None)
    with_diagnostics = _build_decision(
        signals,
        unavailable_agents={"macro": "UNAVAILABLE_NO_PROVIDER"},
    )

    assert without.action == with_diagnostics.action
    assert without.confidence == with_diagnostics.confidence
    assert without.risk_level == with_diagnostics.risk_level


# =============================================================
# 7. Current Step-2C live state: HOLD @ 0.0, reason persisted,
#    unavailable macro/sentiment/market_risk visible in metadata
# =============================================================


def test_live_pipeline_persists_insufficient_evidence_and_unavailable_providers():
    engine = WorldAnalysisEngine()
    market_data = engine.build_market_data(
        "BTCUSDT",
        65_000.0,
        {"rsi": 55, "trend": "BULLISH", "ema20": 101.0, "ema50": 99.0},
        0.85,
    )

    brain = AtlasBrain()
    decision = brain.analyze_and_decide("BTCUSDT", market_data)

    assert decision.action.value == "HOLD"
    assert decision.confidence == 0.0
    assert decision.metadata["fusion_reason"] == "INSUFFICIENT_EVIDENCE"

    unavailable = decision.metadata["unavailable_agents"]
    assert unavailable["macro"] == MarketDataEvidenceStatus.UNAVAILABLE_NO_PROVIDER.value
    assert unavailable["sentiment"] == MarketDataEvidenceStatus.UNAVAILABLE_NO_PROVIDER.value
    assert unavailable["risk"] == MarketDataEvidenceStatus.UNAVAILABLE_NO_PROVIDER.value


# =============================================================
# 8. Serialization of Decision preserves the diagnostic metadata
# =============================================================


def test_decision_to_dict_preserves_diagnostic_metadata():
    decision = _build_decision(
        {"technical": {"action": "BUY", "score": 0.85}, "momentum": {"action": "BUY", "score": 0.70}},
        unavailable_agents={"macro": "UNAVAILABLE_NO_PROVIDER"},
    )

    as_dict = decision.to_dict()

    assert as_dict["metadata"]["fusion_reason"] == "INSUFFICIENT_EVIDENCE"
    assert as_dict["metadata"]["unavailable_agents"] == {
        "macro": "UNAVAILABLE_NO_PROVIDER",
    }
    json.dumps(as_dict["metadata"]["fusion_reason"])
    json.dumps(as_dict["metadata"]["unavailable_agents"])


# =============================================================
# 9. Phase-5 proposal metadata remains independent and is not
#    overwritten or merged incorrectly by the new diagnostic keys
# =============================================================


def test_phase5_proposal_metadata_independent_of_new_diagnostic_keys():
    from datetime import datetime, timezone

    market_data = {
        "price": 65_000.0,
        "technical_score": 0.8,
        "risk_score": 0.7,
        "macro_score": 0.75,
        "sentiment_score": 0.9,
        "rsi": 55,
        "trend": "BULLISH",
        "evidence_status": {
            "technical": MarketDataEvidenceStatus.AVAILABLE.value,
            "macro": MarketDataEvidenceStatus.AVAILABLE.value,
            "sentiment": MarketDataEvidenceStatus.AVAILABLE.value,
            "market_risk": MarketDataEvidenceStatus.AVAILABLE.value,
        },
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }

    brain = AtlasBrain()
    decision = brain.analyze_and_decide("BTCUSDT", market_data)

    assert "phase5_proposal" in decision.metadata
    assert isinstance(decision.metadata["phase5_proposal"], dict)

    # New diagnostic keys coexist without colliding with or replacing
    # the Phase-5 key.
    assert "fusion_reason" in decision.metadata
    assert "unavailable_agents" in decision.metadata
    assert decision.metadata["fusion_reason"] != decision.metadata["phase5_proposal"]
