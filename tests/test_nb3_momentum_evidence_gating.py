"""
NB-3 - Momentum default-evidence fabrication removal.

Post-freeze follow-up to Phase 2 / Step 2C (FROZEN). NB-1 (malformed/
None RSI fail-safe) and NB-2 (fusion audit metadata propagation) are
complete and green; this file does not reopen either.

Defect: momentum was the one configured agent still exempt from Step
2C's "unavailable evidence must not become neutral evidence" policy.
calculate_momentum() defaulted a missing "rsi" key to 50 and a missing
"trend" key to "SIDEWAYS". Both defaults are numerically inert in its
own formula (50 is neither <35 nor >70; SIDEWAYS produces the same
"no adjustment" as any non-BULLISH/non-BEARISH value) - so neither
injected a false directional signal - but both let momentum cast a
full HOLD@0.5 vote, counted toward AgentFusion's participant/coverage
totals, backed by zero real evidence. Inert today only because the
3-agent floor already blocks technical+momentum; would become
execution-relevant the moment a genuine third provider exists.

Fix: evaluate() now excludes momentum (same absence-based pattern as
every other agent) whenever "rsi" or "trend" is genuinely absent from
market_data, using the closed-vocabulary reasons RSI_MISSING /
TREND_MISSING, in addition to NB-1's existing RSI_UNAVAILABLE_OR_
MALFORMED for a present-but-unusable RSI. calculate_momentum() itself
is unchanged; it is now only ever reached once both fields are
confirmed genuinely present.
"""

from __future__ import annotations

from analysis.evidence_status import MarketDataEvidenceStatus
from analysis.world_analysis_engine import WorldAnalysisEngine
from ai.core.atlas_brain import AtlasBrain
from ai.core.intelligence.agent_fusion import AgentFusion


# =============================================================
# 1-3. Missing RSI / trend / both -> no momentum signal
# =============================================================


def test_missing_rsi_key_excludes_momentum():
    fusion_engine = AgentFusion()

    signals = fusion_engine.evaluate("BTCUSDT", {"trend": "BULLISH"})

    assert "momentum" not in signals
    assert fusion_engine.last_unavailable_agents["momentum"] == "RSI_MISSING"


def test_missing_trend_key_excludes_momentum():
    fusion_engine = AgentFusion()

    signals = fusion_engine.evaluate("BTCUSDT", {"rsi": 55})

    assert "momentum" not in signals
    assert fusion_engine.last_unavailable_agents["momentum"] == "TREND_MISSING"


def test_both_rsi_and_trend_missing_excludes_momentum():
    fusion_engine = AgentFusion()

    signals = fusion_engine.evaluate("BTCUSDT", {})

    assert "momentum" not in signals
    assert fusion_engine.last_unavailable_agents["momentum"] == "RSI_MISSING"


# =============================================================
# 4-5. Never a fabricated HOLD@0.5 / SIDEWAYS-derived vote
# =============================================================


def test_missing_rsi_never_becomes_hold_half():
    fusion_engine = AgentFusion()

    signals = fusion_engine.evaluate("BTCUSDT", {"trend": "BULLISH"})

    assert signals.get("momentum") != {"action": "HOLD", "score": 0.5}
    assert "momentum" not in signals


def test_missing_trend_never_becomes_sideways_derived_hold():
    fusion_engine = AgentFusion()

    signals = fusion_engine.evaluate("BTCUSDT", {"rsi": 50})

    assert signals.get("momentum") != {"action": "HOLD", "score": 0.5}
    assert "momentum" not in signals


# =============================================================
# 6-7. NB-1 behavior and numeric-string compatibility preserved
# =============================================================


def test_present_but_malformed_rsi_keeps_nb1_behavior():
    fusion_engine = AgentFusion()

    signals = fusion_engine.evaluate(
        "BTCUSDT", {"rsi": "not-a-number", "trend": "BULLISH"}
    )

    assert "momentum" not in signals
    assert (
        fusion_engine.last_unavailable_agents["momentum"]
        == "RSI_UNAVAILABLE_OR_MALFORMED"
    )


def test_present_but_none_rsi_keeps_nb1_behavior():
    fusion_engine = AgentFusion()

    signals = fusion_engine.evaluate("BTCUSDT", {"rsi": None, "trend": "BULLISH"})

    assert "momentum" not in signals
    assert (
        fusion_engine.last_unavailable_agents["momentum"]
        == "RSI_UNAVAILABLE_OR_MALFORMED"
    )


def test_numeric_string_rsi_compatibility_remains():
    numeric_engine = AgentFusion()
    numeric_signals = numeric_engine.evaluate(
        "BTCUSDT", {"rsi": 55, "trend": "BULLISH"}
    )

    string_engine = AgentFusion()
    string_signals = string_engine.evaluate(
        "BTCUSDT", {"rsi": "55", "trend": "BULLISH"}
    )

    assert string_signals == numeric_signals
    assert "momentum" not in string_engine.last_unavailable_agents


# =============================================================
# 8. Valid inputs preserve existing momentum output exactly
# =============================================================


def test_valid_rsi_and_trend_preserve_existing_momentum_output():
    fusion_engine = AgentFusion()

    signals = fusion_engine.evaluate("BTCUSDT", {"rsi": 55, "trend": "BULLISH"})

    assert signals["momentum"] == {"action": "BUY", "score": 0.7}
    assert "momentum" not in fusion_engine.last_unavailable_agents


# =============================================================
# 9-11. Diagnostics: deterministic, propagate via NB-2, no leak
# =============================================================


def test_diagnostics_are_deterministic_across_repeated_calls():
    for market_data in ({"trend": "BULLISH"}, {"rsi": 55}, {}):
        first = AgentFusion()
        first.evaluate("BTCUSDT", dict(market_data))

        second = AgentFusion()
        second.evaluate("BTCUSDT", dict(market_data))

        assert (
            first.last_unavailable_agents["momentum"]
            == second.last_unavailable_agents["momentum"]
        )


def test_missing_rsi_diagnostic_survives_into_decision_metadata_via_nb2():
    engine = WorldAnalysisEngine()
    market_data = engine.build_market_data(
        "BTCUSDT", 100.0, {"trend": "BULLISH"}, 0.5
    )
    market_data.pop("rsi", None)

    brain = AtlasBrain()
    decision = brain.analyze_and_decide("BTCUSDT", market_data)

    assert (
        decision.metadata["unavailable_agents"].get("momentum")
        in ("RSI_MISSING", "RSI_UNAVAILABLE_OR_MALFORMED")
    )


def test_no_previous_cycle_diagnostic_leak_across_malformed_and_missing_cycles():
    fusion_engine = AgentFusion()

    fusion_engine.evaluate("BTCUSDT", {"rsi": None, "trend": "BULLISH"})
    assert fusion_engine.last_unavailable_agents["momentum"] == (
        "RSI_UNAVAILABLE_OR_MALFORMED"
    )

    fusion_engine.evaluate("BTCUSDT", {"trend": "BULLISH"})
    assert fusion_engine.last_unavailable_agents["momentum"] == "RSI_MISSING"

    fusion_engine.evaluate("BTCUSDT", {"rsi": 55, "trend": "BULLISH"})
    assert "momentum" not in fusion_engine.last_unavailable_agents


# =============================================================
# 12-13. Current live path unaffected: HOLD @ 0.0 / INSUFFICIENT_
#         EVIDENCE, never Atlas_Error_Fallback
# =============================================================


def test_live_path_with_valid_rsi_and_trend_remains_insufficient_evidence():
    engine = WorldAnalysisEngine()
    market_data = engine.build_market_data(
        "BTCUSDT",
        100.0,
        {"rsi": 55, "trend": "BULLISH", "ema20": 101.0, "ema50": 99.0},
        0.85,
    )

    brain = AtlasBrain()
    decision = brain.analyze_and_decide("BTCUSDT", market_data)

    assert decision.action.value == "HOLD"
    assert decision.confidence == 0.0
    assert decision.metadata["fusion_reason"] == "INSUFFICIENT_EVIDENCE"


def test_missing_momentum_evidence_never_reaches_error_fallback():
    engine = WorldAnalysisEngine()
    market_data = engine.build_market_data(
        "BTCUSDT", 100.0, {"trend": "BULLISH"}, 0.5
    )
    market_data.pop("rsi", None)

    brain = AtlasBrain()
    decision = brain.analyze_and_decide("BTCUSDT", market_data)

    assert decision.action.value == "HOLD"
    assert decision.confidence == 0.0
    assert decision.strategy == "Atlas_v10_MultiAgent"
    assert "fallback" not in decision.metadata


# =============================================================
# 14-15. Future third-provider safety + unconfigured names
# =============================================================


def test_future_third_provider_with_missing_momentum_evidence_does_not_inflate_participants():
    """
    Simulates a genuine future third provider (macro, hand-built - no
    real provider exists today) alongside missing RSI. Proves momentum
    cannot fabricate a third participant to falsely clear the floor:
    participant count must reflect only the two genuine sources.
    """

    fusion_engine = AgentFusion()
    market_data = {
        "technical_score": 0.9,
        "macro_score": 0.9,
        "evidence_status": {
            "technical": MarketDataEvidenceStatus.AVAILABLE.value,
            "macro": MarketDataEvidenceStatus.AVAILABLE.value,
            "sentiment": MarketDataEvidenceStatus.UNAVAILABLE_NO_PROVIDER.value,
            "market_risk": MarketDataEvidenceStatus.UNAVAILABLE_NO_PROVIDER.value,
        },
        # "rsi" deliberately absent - momentum must not participate.
        "trend": "BULLISH",
    }

    signals = fusion_engine.evaluate("BTCUSDT", market_data)

    assert set(signals.keys()) == {"technical", "macro"}
    assert len(signals) == 2
    assert len(signals) < AgentFusion.MIN_PARTICIPATING_AGENTS

    fusion = fusion_engine.fuse(signals)
    assert fusion.action == "HOLD"
    assert fusion.confidence == 0.0
    assert fusion.reason == "INSUFFICIENT_EVIDENCE"


def test_unconfigured_agent_names_still_cannot_satisfy_floor():
    fusion_engine = AgentFusion()

    fusion = fusion_engine.fuse(
        {
            "unknown_agent_1": {"action": "BUY", "score": 0.9},
            "unknown_agent_2": {"action": "BUY", "score": 0.9},
        }
    )

    assert fusion.action == "HOLD"
    assert fusion.confidence == 0.0
    assert fusion.reason == "INSUFFICIENT_EVIDENCE"


# =============================================================
# 16. action/confidence/risk invariance for valid existing inputs
# =============================================================


def test_action_confidence_risk_unchanged_for_valid_existing_inputs():
    engine = WorldAnalysisEngine()
    market_data = engine.build_market_data(
        "BTCUSDT",
        100.0,
        {"rsi": 55, "trend": "BULLISH", "ema20": 101.0, "ema50": 99.0},
        0.85,
    )

    brain = AtlasBrain()
    decision = brain.analyze_and_decide("BTCUSDT", market_data)

    assert decision.action.value == "HOLD"
    assert decision.confidence == 0.0
    assert decision.risk_level is not None
