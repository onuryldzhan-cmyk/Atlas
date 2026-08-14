"""
Phase 2 - Market-Data Evidence Semantics

History:
- Step 2A: introduced the evidence-status contract on WorldAnalysisEngine
  while numeric placeholders (macro_score/sentiment_score/risk_score,
  all 0.5) remained, so baseline runtime behavior was unchanged.
- Step 2B: added AgentFusion's minimum-evidence floor (>=2 participating
  configured agents AND >=0.50 configured-weight coverage), inert at the
  time since evaluate() still fabricated all five agents.
- Step 2C (semantic cutover): producer no longer emits macro_score/
  sentiment_score/risk_score at all. AgentFusion.evaluate() reads
  evidence_status and excludes any agent that is not AVAILABLE, instead
  of defaulting it to 0.5. Reported fusion confidence is scaled by
  available configured-weight coverage: final_confidence =
  winning_bucket_share * available_weight_fraction.
- Step 2C participant-floor policy (this file's current state): a
  threshold-boundary review found that technical+momentum full
  agreement always produces final_confidence == exactly 0.60 (because
  technical and momentum are NOT independent - both derive from the
  same RSI/EMA-trend observation - and their combined configured
  weight 0.40+0.20=0.60 coincides with execution's MIN_CONFIDENCE=60.0
  under strict `<` rejection), making a two-source duplication
  confidence-eligible for execution. ACCEPTED POLICY DECISION:
  AgentFusion.MIN_PARTICIPATING_AGENTS raised from 2 to 3.
  MIN_WEIGHT_COVERAGE stays 0.50. Accepted, intentional consequence:
  since macro/sentiment/market_risk currently have no provider,
  technical+momentum (2 agents) is the only combination ever reachable
  today, so every live decision now resolves to HOLD @ 0.0 /
  INSUFFICIENT_EVIDENCE until a genuine third evidence source exists.
  This is a deliberate fail-closed state, not a bug, and must not be
  worked around by reintroducing placeholder evidence.

Tests originally written as "PRE-CUTOVER CHARACTERIZATION" in Step 2A/2B
described behavior that no longer exists after this cutover. Per the
Step 2C task contract they were not silently deleted: they are converted
below into explicit BEFORE/AFTER tests. Their "BEFORE" halves reconstruct
the old fabricated-agent shape by hand and feed it directly into
AgentFusion.fuse() - this reproduces the exact historical pinned values,
because fuse()'s bucket arithmetic is unchanged and, at 100% signal
coverage, the new confidence-scaling step is an identity operation
(share * 1.0 == share). Their "AFTER" halves exercise the real,
current WorldAnalysisEngine + AgentFusion pipeline for the same
underlying technical/momentum evidence.
"""

from __future__ import annotations

import pytest

import ai.core.intelligence.agent_fusion as agent_fusion_module
import analysis.world_analysis_engine as world_analysis_engine_module
from analysis.evidence_status import MarketDataEvidenceStatus
from analysis.world_analysis_engine import WorldAnalysisEngine
from ai.core.intelligence.agent_fusion import AgentFusion
from ai.core.intelligence.risk_engine import AdvisoryRiskScorer


VALID_ANALYSIS = {
    "rsi": 55,
    "trend": "BULLISH",
    "ema20": 101.0,
    "ema50": 99.0,
}

MALFORMED_ANALYSIS = {
    "rsi": "not-a-number",
    "trend": "BULLISH",
    "ema20": None,
    "ema50": None,
}


def build_market_data(analysis=None, score=0.85, price=100.0, symbol="BTCUSDT"):
    engine = WorldAnalysisEngine()
    return engine.build_market_data(
        symbol,
        price,
        dict(analysis if analysis is not None else VALID_ANALYSIS),
        score,
    )


# =============================================================
# PRODUCER CONTRACT
# =============================================================


def test_placeholder_numeric_fields_removed_post_cutover():
    """
    Item 1. BEFORE/AFTER (supersedes Step 2A's
    test_placeholder_numeric_fields_remain_present_and_neutral, which
    asserted these three kept their fabricated 0.5 values).

    AFTER (Step 2C): macro_score/sentiment_score/risk_score are removed
    entirely - not None, not 0.5, not any other sentinel - because no
    genuine value exists to report, and Step 2A/2B established that any
    numeric placeholder here is indistinguishable from real evidence.
    """

    market_data = build_market_data()

    assert "macro_score" not in market_data
    assert "sentiment_score" not in market_data
    assert "risk_score" not in market_data


def test_evidence_status_key_exists():
    market_data = build_market_data()

    assert "evidence_status" in market_data
    assert isinstance(market_data["evidence_status"], dict)


def test_macro_evidence_status_is_unavailable_no_provider():
    """Item 2 (macro)."""

    market_data = build_market_data()

    assert (
        market_data["evidence_status"]["macro"]
        == MarketDataEvidenceStatus.UNAVAILABLE_NO_PROVIDER.value
    )


def test_sentiment_evidence_status_is_unavailable_no_provider():
    """Item 2 (sentiment)."""

    market_data = build_market_data()

    assert (
        market_data["evidence_status"]["sentiment"]
        == MarketDataEvidenceStatus.UNAVAILABLE_NO_PROVIDER.value
    )


def test_market_risk_evidence_status_is_unavailable_no_provider():
    """Item 2 (market_risk)."""

    market_data = build_market_data()

    assert (
        market_data["evidence_status"]["market_risk"]
        == MarketDataEvidenceStatus.UNAVAILABLE_NO_PROVIDER.value
    )


def test_technical_evidence_status_available_for_valid_input():
    """Item 3."""

    market_data = build_market_data(analysis=VALID_ANALYSIS)

    assert (
        market_data["evidence_status"]["technical"]
        == MarketDataEvidenceStatus.AVAILABLE.value
    )


def test_technical_evidence_status_rejected_malformed_for_bad_rsi():
    market_data = build_market_data(analysis=MALFORMED_ANALYSIS)

    assert (
        market_data["evidence_status"]["technical"]
        == MarketDataEvidenceStatus.REJECTED_MALFORMED.value
    )


def test_evidence_status_values_belong_to_closed_vocabulary():
    market_data = build_market_data()

    allowed = {member.value for member in MarketDataEvidenceStatus}

    for field_status in market_data["evidence_status"].values():
        assert field_status in allowed


def test_evidence_status_is_deterministic_across_repeated_calls():
    """
    Updated for Step 2C: no longer asserts macro_score/sentiment_score/
    risk_score determinism (those keys no longer exist at all - their
    absence is itself checked on both calls).
    """

    first = build_market_data()
    second = build_market_data()

    assert first["evidence_status"] == second["evidence_status"]
    assert first["technical_score"] == second["technical_score"]

    for legacy_key in ("macro_score", "sentiment_score", "risk_score"):
        assert legacy_key not in first
        assert legacy_key not in second


def test_build_market_state_unchanged_by_evidence_status():
    """Item 18."""

    engine = WorldAnalysisEngine()
    market_data = build_market_data()

    market_state = engine.build_market_state(market_data)

    assert market_state == {
        "symbol": market_data["symbol"],
        "price": market_data["price"],
        "rsi": market_data["rsi"],
        "trend": market_data["trend"],
        "score": market_data["technical_score"],
        "timestamp": market_data["timestamp"],
    }
    assert "evidence_status" not in market_state
    assert "macro_score" not in market_state
    assert "sentiment_score" not in market_state
    assert "risk_score" not in market_state


# =============================================================
# STEP 2C SEMANTIC CUTOVER - BEFORE/AFTER
# =============================================================


def test_step2c_evidence_status_still_governs_participation_though_floor_now_blocks_both():
    """
    BEFORE/AFTER (supersedes Step 2A/2B's
    test_evidence_status_addition_does_not_change_downstream_decision),
    updated again for the accepted Step 2C participant-floor policy
    (MIN_PARTICIPATING_AGENTS raised 2 -> 3).

    evidence_status still genuinely governs which raw agents
    participate: with it present, technical+momentum both participate
    (2 agents); without it, only momentum does (1 agent) - a real,
    meaningful difference visible in both `signals` and
    last_unavailable_agents.

    Under the accepted 3-agent floor, however, BOTH outcomes now
    resolve to INSUFFICIENT_EVIDENCE at the fuse() level (2 < 3 and
    1 < 3 both fail) - intentional: no 2-agent combination is ever
    currently sufficient, regardless of which two agents they are.
    """

    market_data_with_status = build_market_data()

    market_data_without_status = dict(market_data_with_status)
    market_data_without_status.pop("evidence_status")

    fusion_engine = AgentFusion()

    agents_with = fusion_engine.evaluate("BTCUSDT", market_data_with_status)
    assert set(agents_with.keys()) == {"technical", "momentum"}

    agents_without = fusion_engine.evaluate("BTCUSDT", market_data_without_status)
    assert set(agents_without.keys()) == {"momentum"}
    assert fusion_engine.last_unavailable_agents == {
        "technical": "STATUS_MISSING",
        "macro": "STATUS_MISSING",
        "sentiment": "STATUS_MISSING",
        "risk": "STATUS_MISSING",
    }

    # Agent-level participation genuinely differs (2 agents vs 1)...
    assert agents_with != agents_without

    # ...but under the accepted 3-agent floor, both now resolve the
    # same way at the fusion level.
    fusion_with = fusion_engine.fuse(agents_with)
    fusion_without = fusion_engine.fuse(agents_without)

    for fusion in (fusion_with, fusion_without):
        assert fusion.action == "HOLD"
        assert fusion.confidence == 0.0
        assert fusion.reason == "INSUFFICIENT_EVIDENCE"


def test_step2c_unavailable_agents_no_longer_vote_hold():
    """
    Items 4, 5, 15. BEFORE/AFTER (supersedes Step 2A/2B's
    test_pre_cutover_fabricated_agents_currently_vote_hold).

    BEFORE (Step 2A/2B): macro/sentiment/risk were fabricated 0.5 values
    that evaluate() converted into full HOLD votes indistinguishable
    from genuine neutral evidence.

    AFTER (Step 2C): these three do not appear in `signals` at all -
    excluded, not voted as HOLD - and are recorded in
    last_unavailable_agents (diagnostics), distinguishing "no evidence"
    from "evidence supporting HOLD" both in the returned signals and in
    the diagnostic surface.
    """

    market_data = build_market_data()

    fusion_engine = AgentFusion()
    agents = fusion_engine.evaluate("BTCUSDT", market_data)

    for name in ("macro", "sentiment", "risk"):
        assert name not in agents
        assert "HOLD" != agents.get(name, {}).get("action")

    assert fusion_engine.last_unavailable_agents == {
        "macro": "UNAVAILABLE_NO_PROVIDER",
        "sentiment": "UNAVAILABLE_NO_PROVIDER",
        "risk": "UNAVAILABLE_NO_PROVIDER",
    }


def test_step2c_before_after_strong_buy_now_insufficient():
    """
    Required item 2 (participant-floor policy). BEFORE/AFTER
    (supersedes Step 2A/2B's
    test_pre_cutover_fabricated_agents_contribute_fixed_hold_mass, and
    updated again for the accepted 3-agent floor policy).

    Representative strong-BUY case: technical=0.85 BUY, momentum=0.70
    BUY (rsi=55/BULLISH). BEFORE reconstructs the historical fabricated
    5-agent shape by hand (5 >= 3, so the new floor does not change
    this reconstruction - it reproduces the exact old pinned value).

    AFTER (accepted policy): only technical+momentum are ever available
    today (2 agents). This is exactly the case the threshold-boundary
    review flagged - full technical+momentum agreement always produced
    final_confidence == 0.60, coincidentally equal to execution's
    MIN_CONFIDENCE. Under the accepted 3-agent floor this is now
    INSUFFICIENT_EVIDENCE regardless of how strongly technical and
    momentum agree - the boundary-tie hazard is closed categorically,
    not by tuning a confidence value.
    """

    # ---- BEFORE (historical reconstruction, Step 2A/2B) ----
    historical_signals = {
        "technical": {"action": "BUY", "score": 0.85},
        "momentum": {"action": "BUY", "score": 0.70},
        "risk": {"action": "HOLD", "score": 0.5},
        "macro": {"action": "HOLD", "score": 0.5},
        "sentiment": {"action": "HOLD", "score": 0.5},
    }
    fusion_engine = AgentFusion()
    before = fusion_engine.fuse(historical_signals)

    assert before.action == "BUY"
    # Full 5/5 roster, so the M-2 correction leaves this value unchanged as
    # a quantity: missing_weight is 0 and confidence is exactly the winning
    # bucket share. The only movement is precision - the old code rounded
    # the share to 3 places before scaling it by a coverage of 1.0, the new
    # code rounds the ratio once at 4 places. 0.48/0.68 = 0.70588...
    assert before.confidence == pytest.approx(0.7059)
    assert before.confidence == pytest.approx(before.scores["BUY"], abs=1e-3)
    assert before.scores == {"BUY": 0.706, "SELL": 0.0, "HOLD": 0.294}

    # ---- AFTER (real producer + evaluate(), accepted floor policy) ----
    market_data = build_market_data(analysis=VALID_ANALYSIS, score=0.85)
    agents = fusion_engine.evaluate("BTCUSDT", market_data)
    after = fusion_engine.fuse(agents)

    assert set(agents.keys()) == {"technical", "momentum"}
    assert after.action == "HOLD"
    assert after.confidence == 0.0
    assert after.reason == "INSUFFICIENT_EVIDENCE"
    assert after.confidence < before.confidence


def test_step2c_before_after_weak_buy_now_insufficient():
    """
    Required item 4 (participant-floor policy): a genuinely mixed
    technical+momentum case (technical BUY, momentum HOLD - not full
    agreement) is now insufficient too, for the same reason as full
    agreement (required item 2): evidence COUNT is only 2, regardless
    of the directional content or how the two agents vote relative to
    each other. Supersedes Step 2A/2B's
    test_pre_cutover_fabricated_agents_currently_vote_hold-adjacent
    weak-BUY characterization.

    Representative weak-BUY case: technical=0.60 BUY (boundary),
    momentum=0.50 HOLD (genuine neutral, rsi=50/NEUTRAL trend).

    BEFORE (Step 2A/2B, 5-agent reconstruction, unaffected by the new
    floor since 5 >= 3): fabricated HOLD mass from macro/sentiment/risk
    dominated -> action resolved to HOLD @ ~55.6%.

    AFTER (accepted floor policy): count=2 < 3 -> INSUFFICIENT_EVIDENCE
    regardless of the internal vote direction.
    """

    # ---- BEFORE (historical reconstruction) ----
    historical_signals = {
        "technical": {"action": "BUY", "score": 0.60},
        "momentum": {"action": "HOLD", "score": 0.50},
        "risk": {"action": "HOLD", "score": 0.5},
        "macro": {"action": "HOLD", "score": 0.5},
        "sentiment": {"action": "HOLD", "score": 0.5},
    }
    fusion_engine = AgentFusion()
    before = fusion_engine.fuse(historical_signals)

    assert before.action == "HOLD"
    assert before.confidence == pytest.approx(0.5556, abs=1e-3)

    # ---- AFTER (real producer + evaluate(), accepted floor policy) ----
    neutral_analysis = {"rsi": 50, "trend": "NEUTRAL", "ema20": 100.0, "ema50": 100.0}
    market_data = build_market_data(analysis=neutral_analysis, score=0.60)
    agents = fusion_engine.evaluate("BTCUSDT", market_data)
    after = fusion_engine.fuse(agents)

    assert set(agents.keys()) == {"technical", "momentum"}
    assert agents["technical"]["action"] == "BUY"
    assert agents["momentum"]["action"] == "HOLD"

    assert after.action == "HOLD"
    assert after.confidence == 0.0
    assert after.reason == "INSUFFICIENT_EVIDENCE"


def test_step2c_strong_sell_symmetric_case_now_insufficient():
    """
    Required item 3 (participant-floor policy). Symmetric strong-SELL
    mirror of the strong-BUY case: technical=0.15 SELL, momentum=0.20
    SELL (rsi=80/BEARISH). Full directional agreement is irrelevant to
    the accepted 3-agent floor - still only 2 agents participate.
    """

    sell_analysis = {"rsi": 80, "trend": "BEARISH", "ema20": 90.0, "ema50": 110.0}
    market_data = build_market_data(analysis=sell_analysis, score=0.15)

    fusion_engine = AgentFusion()
    agents = fusion_engine.evaluate("BTCUSDT", market_data)
    fusion = fusion_engine.fuse(agents)

    assert set(agents.keys()) == {"technical", "momentum"}
    assert agents["technical"]["action"] == "SELL"
    assert agents["momentum"]["action"] == "SELL"

    assert fusion.action == "HOLD"
    assert fusion.confidence == 0.0
    assert fusion.reason == "INSUFFICIENT_EVIDENCE"


def test_step2c_before_after_confidence_ceiling_now_insufficient_regardless_of_magnitude():
    """
    BEFORE/AFTER (supersedes Step 2A/2B's
    test_pre_cutover_confidence_ceiling_from_fabricated_hold_mass),
    updated again for the accepted 3-agent floor policy.

    BEFORE: maximal technical+momentum agreement was capped at ~0.737 by
    fabricated HOLD dilution - an artificial ceiling from voting
    non-existent evidence, not from evidence quality.

    AFTER (accepted floor policy): the artificial dilution is gone, and
    the "honest coverage ceiling" of exactly 0.60 (see the superseded
    strong-BUY/strong-SELL tests) is itself now moot - even PERFECT,
    maximal technical+momentum agreement never reaches the confidence
    stage at all, because it is still only 2 participating agents.
    """

    historical_signals = {
        "technical": {"action": "BUY", "score": 1.0},
        "momentum": {"action": "BUY", "score": 0.8},
        "risk": {"action": "HOLD", "score": 0.5},
        "macro": {"action": "HOLD", "score": 0.5},
        "sentiment": {"action": "HOLD", "score": 0.5},
    }
    fusion_engine = AgentFusion()
    before = fusion_engine.fuse(historical_signals)

    assert before.action == "BUY"
    # Full 5/5 roster: unchanged by the M-2 correction except for the same
    # single-rounding precision shift. 0.56/0.76 = 0.73684...
    assert before.confidence == pytest.approx(0.7368)
    assert before.confidence < 1.0

    maximal_analysis = {"rsi": 20, "trend": "BULLISH", "ema20": 110.0, "ema50": 90.0}
    market_data = build_market_data(analysis=maximal_analysis, score=1.0)
    agents = fusion_engine.evaluate("BTCUSDT", market_data)
    after = fusion_engine.fuse(agents)

    assert agents["technical"]["score"] == 1.0
    assert agents["momentum"]["score"] == 0.8

    assert after.action == "HOLD"
    assert after.confidence == 0.0
    assert after.reason == "INSUFFICIENT_EVIDENCE"
    assert after.confidence < before.confidence


def test_step2c_technical_plus_momentum_coverage_alone_no_longer_passes():
    """
    Required item 5: two high-weight agents (technical+momentum) no
    longer pass merely because their combined coverage (0.60) clears
    MIN_WEIGHT_COVERAGE (0.50) - the floor is an AND of count AND
    coverage, and count=2 < MIN_PARTICIPATING_AGENTS=3 fails on its own.
    """

    market_data = build_market_data(analysis=VALID_ANALYSIS, score=0.85)

    fusion_engine = AgentFusion()
    agents = fusion_engine.evaluate("BTCUSDT", market_data)

    assert set(agents.keys()) == {"technical", "momentum"}

    participating_weight = (
        AgentFusion.WEIGHTS["technical"] + AgentFusion.WEIGHTS["momentum"]
    )
    total_weight = sum(AgentFusion.WEIGHTS.values())
    coverage = participating_weight / total_weight

    # Coverage alone would satisfy the (unchanged) 0.50 requirement...
    assert coverage == pytest.approx(0.60)
    assert coverage >= AgentFusion.MIN_WEIGHT_COVERAGE

    # ...but the floor still fails, because only 2 agents participate.
    assert len(agents) < AgentFusion.MIN_PARTICIPATING_AGENTS

    fusion = fusion_engine.fuse(agents)
    assert fusion.action == "HOLD"
    assert fusion.confidence == 0.0
    assert fusion.reason == "INSUFFICIENT_EVIDENCE"


def test_step2c_three_agents_with_sufficient_coverage_pass():
    """
    Required item 9: three configured agents (technical+momentum+
    macro, hand-built - no real third provider exists today, this
    tests the fuse() mechanism itself) with combined coverage 0.70
    clear both the count (3 >= 3) and coverage (0.70 >= 0.50) floor and
    produce a genuine FUSED_EVIDENCE result.
    """

    fusion_engine = AgentFusion()
    signals = {
        "technical": {"action": "BUY", "score": 0.85},
        "momentum": {"action": "BUY", "score": 0.70},
        "macro": {"action": "BUY", "score": 0.90},
    }

    coverage = (
        AgentFusion.WEIGHTS["technical"]
        + AgentFusion.WEIGHTS["momentum"]
        + AgentFusion.WEIGHTS["macro"]
    ) / sum(AgentFusion.WEIGHTS.values())
    assert coverage == pytest.approx(0.70)

    fusion = fusion_engine.fuse(signals)

    assert fusion.action == "BUY"
    assert fusion.reason == "FUSED_EVIDENCE"
    assert fusion.scores == {"BUY": 1.0, "SELL": 0.0, "HOLD": 0.0}
    # Required item 13, restated for the M-2 correction. The old formula
    # was bucket_share (1.0) * coverage (0.70) = 0.70, which double-counted
    # the availability normalization: it took the share against surviving
    # mass and *then* scaled by coverage. The corrected single
    # normalization charges the two absent participants their full weight
    # instead: buy = 0.85*0.40 + 0.70*0.20 + 0.90*0.10 = 0.57, and
    # 0.57 / (0.57 + 0.30) = 0.6552.
    #
    # The lower value is the point. `scores` still reads 100% BUY among
    # the evidence that exists, but three of five configured sources
    # agreeing at ordinary strength is not 70% conviction about the whole
    # roster. Coverage is only reached as a ceiling under maximal
    # conviction (see the unanimous-1.0 ladder test).
    assert fusion.confidence == pytest.approx(0.6552)
    assert fusion.confidence < coverage


def test_step2c_three_agents_with_insufficient_coverage_fail():
    """
    Required item 10: verified against the actual configured WEIGHTS
    (technical=0.40, momentum=0.20, risk=0.20, macro=0.10,
    sentiment=0.10) that a genuine 3-agent combination with coverage
    below 0.50 exists - risk+macro+sentiment = 0.20+0.10+0.10 = 0.40 -
    so this is a real reachable configuration, not an invented case.
    Count (3 >= 3) passes but coverage (0.40 < 0.50) still fails.
    """

    fusion_engine = AgentFusion()
    signals = {
        "risk": {"action": "BUY", "score": 0.90},
        "macro": {"action": "BUY", "score": 0.90},
        "sentiment": {"action": "BUY", "score": 0.90},
    }

    coverage = (
        AgentFusion.WEIGHTS["risk"]
        + AgentFusion.WEIGHTS["macro"]
        + AgentFusion.WEIGHTS["sentiment"]
    ) / sum(AgentFusion.WEIGHTS.values())
    assert coverage == pytest.approx(0.40)
    assert coverage < AgentFusion.MIN_WEIGHT_COVERAGE

    fusion = fusion_engine.fuse(signals)

    assert fusion.action == "HOLD"
    assert fusion.confidence == 0.0
    assert fusion.reason == "INSUFFICIENT_EVIDENCE"


def test_step2c_three_agent_fusion_is_deterministic():
    """Required item 12, for a valid (>=3-agent) fused case specifically."""

    fusion_engine = AgentFusion()
    signals = {
        "technical": {"action": "BUY", "score": 0.85},
        "momentum": {"action": "BUY", "score": 0.70},
        "macro": {"action": "BUY", "score": 0.90},
    }

    first = fusion_engine.fuse(signals)
    second = fusion_engine.fuse(signals)

    assert first == second
    assert first.reason == "FUSED_EVIDENCE"


def test_step2c_operational_characterization_current_live_state_is_insufficient():
    """
    OPERATIONAL CHARACTERIZATION - accepted system state.

    Proves, via the real WorldAnalysisEngine + AgentFusion pipeline
    (not a hand-built fixture), that under CURRENT live provider
    availability - technical AVAILABLE, momentum unconditionally
    participating, macro/sentiment/market_risk all
    UNAVAILABLE_NO_PROVIDER - participant count is always exactly 2,
    which is below the accepted MIN_PARTICIPATING_AGENTS=3 floor.
    Every live decision therefore resolves to HOLD @ 0.0 /
    INSUFFICIENT_EVIDENCE until at least one genuine third evidence
    source becomes AVAILABLE. This is the accepted, intentional
    consequence of the Step 2C threshold-boundary policy decision - not
    a bug, and must not be worked around by reintroducing placeholder
    evidence.
    """

    market_data = build_market_data(analysis=VALID_ANALYSIS, score=0.85)

    assert market_data["evidence_status"]["technical"] == "AVAILABLE"
    assert market_data["evidence_status"]["macro"] == "UNAVAILABLE_NO_PROVIDER"
    assert market_data["evidence_status"]["sentiment"] == "UNAVAILABLE_NO_PROVIDER"
    assert market_data["evidence_status"]["market_risk"] == "UNAVAILABLE_NO_PROVIDER"

    fusion_engine = AgentFusion()
    agents = fusion_engine.evaluate("BTCUSDT", market_data)

    assert set(agents.keys()) == {"technical", "momentum"}
    assert len(agents) == 2
    assert len(agents) < AgentFusion.MIN_PARTICIPATING_AGENTS
    assert fusion_engine.last_unavailable_agents == {
        "macro": "UNAVAILABLE_NO_PROVIDER",
        "sentiment": "UNAVAILABLE_NO_PROVIDER",
        "risk": "UNAVAILABLE_NO_PROVIDER",
    }

    fusion = fusion_engine.fuse(agents)

    assert fusion.action == "HOLD"
    assert fusion.confidence == 0.0
    assert fusion.reason == "INSUFFICIENT_EVIDENCE"


def test_step2c_one_available_agent_via_real_pipeline_is_insufficient():
    """
    Item 11, via a realistic pipeline path: technical rejected as
    malformed (evidence_status="REJECTED_MALFORMED") leaves only
    momentum participating (count=1, weight=0.20) - below the floor.

    rsi/trend are kept numeric here (unlike a truly malformed RSI
    string) so this isolates AgentFusion's evidence-status gating from
    calculate_momentum()'s separate, pre-existing lack of RSI type
    validation (out of scope for Step 2C - see "real momentum
    propagation" in the deferred-items list).
    """

    market_data = {
        "technical_score": 0.85,
        "rsi": 55,
        "trend": "BULLISH",
        "evidence_status": {
            "technical": MarketDataEvidenceStatus.REJECTED_MALFORMED.value,
            "macro": MarketDataEvidenceStatus.UNAVAILABLE_NO_PROVIDER.value,
            "sentiment": MarketDataEvidenceStatus.UNAVAILABLE_NO_PROVIDER.value,
            "market_risk": MarketDataEvidenceStatus.UNAVAILABLE_NO_PROVIDER.value,
        },
    }

    fusion_engine = AgentFusion()
    agents = fusion_engine.evaluate("BTCUSDT", market_data)

    assert set(agents.keys()) == {"momentum"}

    fusion = fusion_engine.fuse(agents)

    assert fusion.action == "HOLD"
    assert fusion.confidence == 0.0
    assert fusion.reason == "INSUFFICIENT_EVIDENCE"


def test_step2c_zero_available_agents_fails_safely():
    """
    Item 12. Covered at the fuse() unit level (see also
    test_evidence_floor_zero_signals_fail_safely in the Step 2B
    section): the full evaluate()->fuse() pipeline currently cannot
    reach zero participating agents, because momentum has no
    evidence_status entry and always participates unconditionally
    (documented, unchanged design - momentum gating is explicitly out
    of scope for Step 2C). This directly exercises fuse()'s fail-safe
    result for the true zero-agent case.
    """

    fusion_engine = AgentFusion()

    fusion = fusion_engine.fuse({})

    assert fusion.action == "HOLD"
    assert fusion.confidence == 0.0
    assert fusion.reason == "INSUFFICIENT_EVIDENCE"


def test_step2c_genuine_neutral_technical_plus_momentum_now_insufficient():
    """
    Required item 4a: genuine neutral evidence (both technical and
    momentum honestly AVAILABLE and both actually HOLD, not a
    fabricated placeholder) is STILL insufficient under the accepted
    floor policy, purely because evidence count is only 2 - the count
    requirement applies regardless of whether the underlying evidence
    happens to be directional or neutral.

    Supersedes Step 2C's original
    test_step2c_genuine_available_neutral_evidence_remains_fused_hold
    (see test_step2c_genuine_neutral_with_sufficient_evidence_remains_fused_hold
    below for the >=3-agent case, which preserves the genuine-neutral-
    vs-insufficient-evidence distinction this test originally existed
    to make).
    """

    neutral_analysis = {"rsi": 50, "trend": "NEUTRAL", "ema20": 100.0, "ema50": 100.0}
    market_data = build_market_data(analysis=neutral_analysis, score=0.5)

    fusion_engine = AgentFusion()
    agents = fusion_engine.evaluate("BTCUSDT", market_data)

    assert agents["technical"] == {"action": "HOLD", "score": 0.5}
    assert agents["momentum"] == {"action": "HOLD", "score": 0.5}
    assert len(agents) < AgentFusion.MIN_PARTICIPATING_AGENTS

    fusion = fusion_engine.fuse(agents)

    assert fusion.action == "HOLD"
    assert fusion.confidence == 0.0
    assert fusion.reason == "INSUFFICIENT_EVIDENCE"


def test_step2c_genuine_neutral_with_sufficient_evidence_remains_fused_hold():
    """
    Preserves the genuine-neutral-vs-insufficient-evidence distinction
    at exactly the new accepted threshold: 3 participating agents
    (technical+momentum+macro, hand-built - no real third provider
    exists today, this tests the fuse() mechanism itself, not a claim
    about current live providers), all genuinely HOLD @ 0.5, clears
    both the count (3 >= 3) and coverage (0.70 >= 0.50) floor and
    produces a legitimate FUSED_EVIDENCE result - distinguishable from
    INSUFFICIENT_EVIDENCE's HOLD @ 0.0.
    """

    fusion_engine = AgentFusion()
    signals = {
        "technical": {"action": "HOLD", "score": 0.5},
        "momentum": {"action": "HOLD", "score": 0.5},
        "macro": {"action": "HOLD", "score": 0.5},
    }

    fusion = fusion_engine.fuse(signals)

    assert fusion.action == "HOLD"
    assert fusion.reason == "FUSED_EVIDENCE"
    # Distinguishable from insufficient evidence: nonzero confidence.
    #
    # Value updated for the M-2 correction (was 0.70 under the old
    # bucket_share * coverage double normalization). Three genuine HOLD
    # votes carry 0.5 * 0.70 = 0.35 of mass and the two absent
    # participants are charged their full 0.30: 0.35 / (0.35 + 0.30)
    # = 0.5385. Still emphatically not 0.0 - the genuine-neutral versus
    # insufficient-evidence distinction this test exists to protect is
    # unaffected.
    assert fusion.confidence == pytest.approx(0.5385)
    assert fusion.confidence != 0.0


def test_step2c_repeated_identical_inputs_are_deterministic():
    """Item 16."""

    market_data = build_market_data(analysis=VALID_ANALYSIS, score=0.85)

    fusion_engine = AgentFusion()

    agents_first = fusion_engine.evaluate("BTCUSDT", market_data)
    fusion_first = fusion_engine.fuse(agents_first)

    agents_second = fusion_engine.evaluate("BTCUSDT", market_data)
    fusion_second = fusion_engine.fuse(agents_second)

    assert agents_first == agents_second
    assert fusion_first == fusion_second


def test_risk_engine_output_unchanged_for_fixed_confidence_input():
    """
    Item 19. AdvisoryRiskScorer is untouched by the Step 2C cutover. Confirms
    its call signature and output for a fixed confidence input match
    the pre-existing formula exactly - the market/execution risk
    separation documented in the Phase 2 design review remains intact
    (AdvisoryRiskScorer never reads market_data["risk_score"] or the "risk"
    agent's score; it only ever receives `confidence=`).
    """

    result = AdvisoryRiskScorer().calculate(confidence=0.4236)

    assert result.to_dict() == {
        "level": "HIGH",
        "score": 0.538,
        "reason": "Risk classified as HIGH with score 0.538",
    }


def test_step2c_baseline_modules_do_not_import_phase5_decision_intelligence():
    """
    Item 20 (architectural boundary check). Full Phase-5 shadow
    independence is verified by running the existing dedicated
    tests/test_atlas_brain_phase5_shadow.py suite (see Step 2C
    validation) - this only confirms the modules touched in this step
    never import Phase-5's evidence/fusion classes.
    """

    for module in (agent_fusion_module, world_analysis_engine_module):
        assert "decision_intelligence" not in vars(module)
        assert not any(
            getattr(value, "__module__", "").startswith("core.decision_intelligence")
            for value in vars(module).values()
            if hasattr(value, "__module__")
        )


# =============================================================
# STEP 2B - MINIMUM-EVIDENCE FLOOR
#
# Mechanism unchanged by Step 2C: fuse()'s floor logic operates on
# whatever `signals` it is given, regardless of how those signals were
# produced. It was inert under Step 2A/2B (evaluate() always emitted 5
# agents); it became load-bearing under Step 2C's semantic cutover
# (evaluate() could emit as few as 1 agent); the THRESHOLD itself was
# then raised (MIN_PARTICIPATING_AGENTS 2 -> 3) by the accepted
# participant-floor policy decision. These tests exercise fuse()
# directly; those whose outcome depended on the old count=2 threshold
# are updated below - see each docstring.
# =============================================================


def test_evidence_floor_two_high_weight_agents_no_longer_pass():
    """
    Updated for the accepted participant-floor policy (was
    test_evidence_floor_two_high_weight_agents_pass, Step 2B): technical
    (0.40) + momentum (0.20) = 0.60 >= MIN_WEIGHT_COVERAGE (0.50), but
    count=2 < MIN_PARTICIPATING_AGENTS=3 now fails on its own. This is
    exactly the technical+momentum pair the threshold-boundary review
    flagged (see required item 5).
    """

    fusion_engine = AgentFusion()
    signals = {
        "technical": {"action": "BUY", "score": 0.9},
        "momentum": {"action": "BUY", "score": 0.8},
    }

    fusion = fusion_engine.fuse(signals)

    assert fusion.reason == "INSUFFICIENT_EVIDENCE"
    assert fusion.action == "HOLD"
    assert fusion.confidence == 0.0


def test_evidence_floor_single_agent_fails_even_at_maximal_conviction():
    """Item 3: one configured agent (count=1 < 2) fails regardless of conviction."""

    fusion_engine = AgentFusion()
    signals = {
        "technical": {"action": "BUY", "score": 1.0},
    }

    fusion = fusion_engine.fuse(signals)

    assert fusion.action == "HOLD"
    assert fusion.confidence == 0.0
    assert fusion.reason == "INSUFFICIENT_EVIDENCE"
    assert fusion.scores == {}


def test_evidence_floor_two_low_weight_agents_fail_coverage():
    """
    Required item 6 / Item 4 (Step 2B numbering): macro (0.10) +
    sentiment (0.10) = 0.20 weight. Under the accepted participant-
    floor policy this now fails on BOTH grounds - count=2 <
    MIN_PARTICIPATING_AGENTS=3 AND 0.20 < MIN_WEIGHT_COVERAGE=0.50 -
    whereas under the original Step 2B threshold (count>=2) it failed
    on coverage alone. Outcome is unchanged; the reason it fails is
    now doubly true.
    """

    fusion_engine = AgentFusion()
    signals = {
        "macro": {"action": "BUY", "score": 0.9},
        "sentiment": {"action": "BUY", "score": 0.9},
    }

    fusion = fusion_engine.fuse(signals)

    assert fusion.action == "HOLD"
    assert fusion.confidence == 0.0
    assert fusion.reason == "INSUFFICIENT_EVIDENCE"


def test_evidence_floor_zero_signals_fail_safely():
    """Item 5."""

    fusion_engine = AgentFusion()

    fusion = fusion_engine.fuse({})

    assert fusion.action == "HOLD"
    assert fusion.confidence == 0.0
    assert fusion.reason == "INSUFFICIENT_EVIDENCE"


def test_evidence_floor_unconfigured_signal_names_do_not_count():
    """
    Item 17 (Step 2C numbering) / Item 6 (Step 2B numbering): two
    entries are present, but neither name is in AgentFusion.WEIGHTS, so
    participation and coverage must both be 0 rather than inflated by
    the raw entry count.
    """

    fusion_engine = AgentFusion()
    signals = {
        "unknown_agent_1": {"action": "BUY", "score": 0.9},
        "unknown_agent_2": {"action": "BUY", "score": 0.9},
    }

    fusion = fusion_engine.fuse(signals)

    assert fusion.action == "HOLD"
    assert fusion.confidence == 0.0
    assert fusion.reason == "INSUFFICIENT_EVIDENCE"


def test_evidence_floor_genuine_hold_evidence_is_not_mislabeled_insufficient():
    """
    Item 7 (Step 2B numbering): all five configured agents genuinely
    voting HOLD (real neutral evidence, full weight coverage) must
    remain distinguishable from insufficient evidence - HOLD @ 100%
    confidence with FUSED_EVIDENCE, not HOLD @ 0.0 with
    INSUFFICIENT_EVIDENCE.
    """

    fusion_engine = AgentFusion()
    signals = {
        name: {"action": "HOLD", "score": 0.5}
        for name in AgentFusion.WEIGHTS
    }

    fusion = fusion_engine.fuse(signals)

    assert fusion.action == "HOLD"
    assert fusion.confidence == pytest.approx(1.0)
    assert fusion.reason == "FUSED_EVIDENCE"


def test_evidence_floor_diagnostics_are_deterministic():
    """Item 8 (Step 2B numbering): repeated identical below-floor input yields identical diagnostics."""

    fusion_engine = AgentFusion()
    signals = {
        "macro": {"action": "BUY", "score": 0.9},
        "sentiment": {"action": "BUY", "score": 0.9},
    }

    first = fusion_engine.fuse(signals)
    second = fusion_engine.fuse(signals)

    assert first == second
    assert first.reason == "INSUFFICIENT_EVIDENCE"


def test_evidence_floor_thresholds_match_configured_weights():
    """
    Threshold sanity check, updated for the accepted participant-floor
    policy (MIN_PARTICIPATING_AGENTS 2 -> 3): verifies the thresholds
    are meaningful against the actual configured WEIGHTS, not assumed.
    """

    assert AgentFusion.MIN_PARTICIPATING_AGENTS == 3
    assert AgentFusion.MIN_WEIGHT_COVERAGE == pytest.approx(0.50)

    total_weight = sum(AgentFusion.WEIGHTS.values())
    assert total_weight == pytest.approx(1.0)

    # A high-weight PAIR clears the coverage threshold on weight alone...
    high_pair_weight = (
        AgentFusion.WEIGHTS["technical"] + AgentFusion.WEIGHTS["momentum"]
    )
    assert high_pair_weight / total_weight >= AgentFusion.MIN_WEIGHT_COVERAGE
    # ...but no 2-agent combination can ever satisfy the count
    # requirement by itself - this is the categorical, WEIGHTS-
    # independent property the accepted policy relies on.
    assert 2 < AgentFusion.MIN_PARTICIPATING_AGENTS

    # A low-weight pair fails coverage regardless.
    low_pair_weight = (
        AgentFusion.WEIGHTS["macro"] + AgentFusion.WEIGHTS["sentiment"]
    )
    assert low_pair_weight / total_weight < AgentFusion.MIN_WEIGHT_COVERAGE

    # A 3-agent combination exists that clears coverage too...
    high_triple_weight = (
        AgentFusion.WEIGHTS["technical"]
        + AgentFusion.WEIGHTS["momentum"]
        + AgentFusion.WEIGHTS["macro"]
    )
    assert high_triple_weight / total_weight >= AgentFusion.MIN_WEIGHT_COVERAGE

    # ...and a genuine (not invented) 3-agent combination exists that
    # still fails coverage, verified against actual configured WEIGHTS.
    low_triple_weight = (
        AgentFusion.WEIGHTS["risk"]
        + AgentFusion.WEIGHTS["macro"]
        + AgentFusion.WEIGHTS["sentiment"]
    )
    assert low_triple_weight / total_weight < AgentFusion.MIN_WEIGHT_COVERAGE
