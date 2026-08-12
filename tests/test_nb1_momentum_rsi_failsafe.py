"""
NB-1 - Malformed/None RSI momentum fail-safe.

Post-freeze follow-up to Phase 2 / Step 2C (FROZEN, PASS WITH
NON-BLOCKING FINDINGS). NB-2 (fusion audit metadata propagation) is
complete and green; this file does not depend on reopening either.

Defect: AgentFusion.calculate_momentum() did raw numeric comparisons
(`rsi < 35`, `rsi > 70`) with no type guard, even though technical
evidence for the identical "rsi" field is already validated by
WorldAnalysisEngine._technical_evidence_status() (a bare float() parse
check). A PRESENT-but-unusable "rsi" value (None, a malformed string,
or any other non-numeric object) made AgentFusion.evaluate() raise,
which AtlasBrain's broad handler converted into Atlas_Error_Fallback
(HOLD @ 0.0, risk_level=CRITICAL, strategy=Atlas_Error_Fallback) - a
runtime failure, not the intended "no directional decision" fail-closed
path.

Fix: evaluate() now validates "rsi" (when the key is present) with the
same float()-parse convention the producer already uses, mirroring
_technical_evidence_status() rather than inventing a new heuristic.
When unusable, momentum is excluded from `signals` exactly like every
other unavailable agent - never by raising, never by fabricating a
HOLD@0.5 score, and never by coercing the value to a neutral default.
A MISSING "rsi" key is untouched (calculate_momentum()'s own
pre-existing default of 50 is separate, already-scoped NB-3 territory).
calculate_momentum() itself gained a defensive float() coercion so an
already-validated numeric-string RSI (e.g. "55") - which the same
producer-side convention already treats as valid/AVAILABLE - no longer
raises either; this preserves the project's existing numeric-string
compatibility rather than tightening it.
"""

from __future__ import annotations

from analysis.evidence_status import MarketDataEvidenceStatus
from analysis.world_analysis_engine import WorldAnalysisEngine
from ai.core.atlas_brain import AtlasBrain
from ai.core.intelligence.agent_fusion import AgentFusion


UNUSABLE_RSI_VALUES = {
    "none": None,
    "malformed_string": "not-a-number",
    "non_numeric_object": object(),
}


# =============================================================
# 1-3. Unusable RSI does not raise
# =============================================================


def test_none_rsi_does_not_raise():
    fusion_engine = AgentFusion()

    signals = fusion_engine.evaluate(
        "BTCUSDT",
        {"rsi": None, "trend": "BULLISH"},
    )

    assert isinstance(signals, dict)


def test_malformed_string_rsi_does_not_raise():
    fusion_engine = AgentFusion()

    signals = fusion_engine.evaluate(
        "BTCUSDT",
        {"rsi": "not-a-number", "trend": "BULLISH"},
    )

    assert isinstance(signals, dict)


def test_non_numeric_object_rsi_does_not_raise():
    fusion_engine = AgentFusion()

    signals = fusion_engine.evaluate(
        "BTCUSDT",
        {"rsi": object(), "trend": "BULLISH"},
    )

    assert isinstance(signals, dict)


# =============================================================
# 4-5. Unusable RSI does not produce a momentum signal and does
#      not silently become HOLD@0.5 momentum evidence
# =============================================================


def test_unusable_rsi_excludes_momentum_from_signals():
    for label, rsi_value in UNUSABLE_RSI_VALUES.items():
        fusion_engine = AgentFusion()

        signals = fusion_engine.evaluate(
            "BTCUSDT",
            {"rsi": rsi_value, "trend": "BULLISH"},
        )

        assert "momentum" not in signals, label
        assert signals == {}, label


def test_unusable_rsi_never_fabricates_hold_half_momentum():
    for label, rsi_value in UNUSABLE_RSI_VALUES.items():
        fusion_engine = AgentFusion()

        signals = fusion_engine.evaluate(
            "BTCUSDT",
            {"rsi": rsi_value, "trend": "BULLISH"},
        )

        assert signals.get("momentum") != {"action": "HOLD", "score": 0.5}, label


# =============================================================
# 6. Momentum exclusion appears in deterministic diagnostics
# =============================================================


def test_momentum_exclusion_recorded_in_diagnostics_deterministically():
    for label, rsi_value in UNUSABLE_RSI_VALUES.items():
        fusion_engine = AgentFusion()

        fusion_engine.evaluate(
            "BTCUSDT",
            {"rsi": rsi_value, "trend": "BULLISH"},
        )

        assert (
            fusion_engine.last_unavailable_agents["momentum"]
            == "RSI_UNAVAILABLE_OR_MALFORMED"
        ), label

        # Repeated identical input yields identical diagnostics.
        fusion_engine_2 = AgentFusion()
        fusion_engine_2.evaluate(
            "BTCUSDT",
            {"rsi": rsi_value, "trend": "BULLISH"},
        )

        assert (
            fusion_engine.last_unavailable_agents
            == fusion_engine_2.last_unavailable_agents
        ), label


def test_momentum_diagnostic_reason_is_closed_vocabulary_string_not_repr():
    fusion_engine = AgentFusion()

    fusion_engine.evaluate(
        "BTCUSDT",
        {"rsi": object(), "trend": "BULLISH"},
    )

    reason = fusion_engine.last_unavailable_agents["momentum"]

    assert reason == "RSI_UNAVAILABLE_OR_MALFORMED"
    assert "object" not in reason
    assert "0x" not in reason


# =============================================================
# 7. Previous-cycle last_unavailable_agents cannot leak into the
#    next malformed cycle (INFO-3)
# =============================================================


def test_previous_cycle_diagnostics_do_not_leak_into_next_cycle():
    fusion_engine = AgentFusion()

    # First cycle: a genuine, different diagnostic set.
    fusion_engine.evaluate(
        "BTCUSDT",
        {
            "rsi": 55,
            "trend": "BULLISH",
            "evidence_status": {
                "technical": MarketDataEvidenceStatus.REJECTED_MALFORMED.value,
            },
        },
    )
    first_cycle_diagnostics = dict(fusion_engine.last_unavailable_agents)
    assert "momentum" not in first_cycle_diagnostics

    # Second cycle: unusable RSI. Diagnostics must reflect only this
    # cycle - not a merge with, or a leftover from, the first cycle.
    fusion_engine.evaluate(
        "BTCUSDT",
        {"rsi": None, "trend": "BULLISH"},
    )

    assert fusion_engine.last_unavailable_agents != first_cycle_diagnostics
    assert fusion_engine.last_unavailable_agents["momentum"] == "RSI_UNAVAILABLE_OR_MALFORMED"


def test_last_unavailable_agents_reset_at_start_of_evaluate():
    fusion_engine = AgentFusion()

    fusion_engine.last_unavailable_agents = {
        "stale": "FROM_A_PRIOR_UNRELATED_CYCLE",
    }

    fusion_engine.evaluate(
        "BTCUSDT",
        {"rsi": 55, "trend": "BULLISH"},
    )

    assert "stale" not in fusion_engine.last_unavailable_agents


# =============================================================
# 8. Current live provider reality: malformed/None RSI resolves
#    through the normal Decision path, not Atlas_Error_Fallback
# =============================================================


def test_malformed_rsi_resolves_through_normal_decision_path_not_error_fallback():
    engine = WorldAnalysisEngine()
    market_data = engine.build_market_data(
        "BTCUSDT",
        100.0,
        {"rsi": "not-a-number", "trend": "BULLISH"},
        0.5,
    )

    assert market_data["evidence_status"]["technical"] == "REJECTED_MALFORMED"

    brain = AtlasBrain()
    decision = brain.analyze_and_decide("BTCUSDT", market_data)

    assert decision.action.value == "HOLD"
    assert decision.confidence == 0.0
    assert decision.metadata["fusion_reason"] == "INSUFFICIENT_EVIDENCE"

    # Proof this is the normal path, not the exception fallback: the
    # fallback path uses a different strategy label and sets an
    # explicit "fallback" metadata flag; neither is present here.
    assert decision.strategy == "Atlas_v10_MultiAgent"
    assert "fallback" not in decision.metadata
    assert decision.metadata.get("error") is None

    unavailable = decision.metadata["unavailable_agents"]
    assert unavailable["technical"] == "REJECTED_MALFORMED"
    assert unavailable["momentum"] == "RSI_UNAVAILABLE_OR_MALFORMED"


def test_none_rsi_resolves_through_normal_decision_path_not_error_fallback():
    engine = WorldAnalysisEngine()
    market_data = engine.build_market_data(
        "BTCUSDT",
        100.0,
        {"rsi": None, "trend": "BULLISH"},
        0.5,
    )

    brain = AtlasBrain()
    decision = brain.analyze_and_decide("BTCUSDT", market_data)

    assert decision.action.value == "HOLD"
    assert decision.confidence == 0.0
    assert decision.strategy == "Atlas_v10_MultiAgent"
    assert "fallback" not in decision.metadata


# =============================================================
# 9. No directional execution becomes reachable
# =============================================================


def test_malformed_rsi_never_reaches_directional_action():
    for rsi_value in UNUSABLE_RSI_VALUES.values():
        engine = WorldAnalysisEngine()
        market_data = engine.build_market_data(
            "BTCUSDT",
            100.0,
            {"rsi": rsi_value, "trend": "BULLISH"},
            0.5,
        )

        brain = AtlasBrain()
        decision = brain.analyze_and_decide("BTCUSDT", market_data)

        assert decision.action.value not in ("BUY", "SELL")
        assert decision.confidence == 0.0


# =============================================================
# 10. Valid numeric RSI retains existing momentum behavior exactly
# =============================================================


def test_valid_numeric_rsi_momentum_behavior_unchanged():
    fusion_engine = AgentFusion()

    signals = fusion_engine.evaluate(
        "BTCUSDT",
        {"rsi": 55, "trend": "BULLISH"},
    )

    assert signals["momentum"] == {"action": "BUY", "score": 0.7}
    assert "momentum" not in fusion_engine.last_unavailable_agents


def test_missing_rsi_key_excludes_momentum_per_nb3():
    """
    Superseded by Step NB-3 (momentum default-evidence fabrication
    removal): a genuinely absent "rsi" key no longer lets momentum
    fabricate a HOLD@0.5 vote from internal rsi=50/trend=SIDEWAYS
    defaults. This was explicitly out of scope for NB-1 (see the
    module docstring above) and is now closed by NB-3 - momentum is
    excluded from `signals`, recorded as "RSI_MISSING", the same
    absence-based pattern already used for every other unavailable
    agent. Full NB-3 coverage lives in
    tests/test_nb3_momentum_evidence_gating.py; this test only
    confirms NB-1's own suite no longer describes the superseded
    behavior.
    """

    fusion_engine = AgentFusion()

    signals = fusion_engine.evaluate("BTCUSDT", {})

    assert "momentum" not in signals
    assert fusion_engine.last_unavailable_agents["momentum"] == "RSI_MISSING"


# =============================================================
# 11. Numeric-string RSI compatibility is preserved, not tightened
# =============================================================


def test_numeric_string_rsi_is_accepted_and_matches_numeric_equivalent():
    """
    WorldAnalysisEngine._technical_evidence_status() already treats a
    numeric-string RSI as AVAILABLE (bare float() parse check). This
    fix must not make momentum stricter than the producer it mirrors:
    a numeric-string RSI must produce the identical momentum result as
    its numeric equivalent, not an exclusion.
    """

    numeric_engine = AgentFusion()
    numeric_signals = numeric_engine.evaluate(
        "BTCUSDT",
        {"rsi": 55, "trend": "BULLISH"},
    )

    string_engine = AgentFusion()
    string_signals = string_engine.evaluate(
        "BTCUSDT",
        {"rsi": "55", "trend": "BULLISH"},
    )

    assert string_signals == numeric_signals
    assert "momentum" not in string_engine.last_unavailable_agents


# =============================================================
# 12. Step-2C valid technical+momentum behavior remains unchanged
# =============================================================


def test_step2c_valid_technical_plus_momentum_behavior_unchanged():
    engine = WorldAnalysisEngine()
    market_data = engine.build_market_data(
        "BTCUSDT",
        100.0,
        {"rsi": 55, "trend": "BULLISH", "ema20": 101.0, "ema50": 99.0},
        0.85,
    )

    fusion_engine = AgentFusion()
    agents = fusion_engine.evaluate("BTCUSDT", market_data)
    fusion = fusion_engine.fuse(agents)

    assert set(agents.keys()) == {"technical", "momentum"}
    assert fusion.action == "HOLD"
    assert fusion.confidence == 0.0
    assert fusion.reason == "INSUFFICIENT_EVIDENCE"


# =============================================================
# 13. NB-2 metadata propagation persists the new diagnostic
# =============================================================


def test_nb2_metadata_propagation_includes_momentum_unavailable_reason():
    engine = WorldAnalysisEngine()
    market_data = engine.build_market_data(
        "BTCUSDT",
        100.0,
        {"rsi": None, "trend": "BULLISH"},
        0.5,
    )

    brain = AtlasBrain()
    decision = brain.analyze_and_decide("BTCUSDT", market_data)

    assert (
        decision.metadata["unavailable_agents"]["momentum"]
        == "RSI_UNAVAILABLE_OR_MALFORMED"
    )
