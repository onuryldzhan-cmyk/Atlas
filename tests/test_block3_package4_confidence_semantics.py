"""Block 3 / Package 4: M-2, M-3 and M-4 closure evidence.

M-2 - evidence-removal monotonicity (AgentFusion.fuse)
------------------------------------------------------
Frozen Block-1/Block-2 statement: "AgentFusion.fuse can produce higher
confidence after removing a dissenting participant (verified example:
0.6894 -> 0.7000)." Reproduced at the Package-4 starting HEAD by grid
search at up to +0.133 (0.667 -> 0.800) for a single removal.

Cause: `bucket_share * weight_coverage` normalized twice against two
different populations. bucket_share divided by the mass of the *surviving*
participants, which shrinks when a participant disappears; the coverage
factor did not always cancel that, because a participant contributes only a
fraction of its weight to the mass (score for BUY, 1-score for SELL, 0.5 for
HOLD) while contributing all of it to coverage.

Correction: one normalization against the whole configured roster. An absent
participant is charged its full configured weight against whichever bucket
wins - `confidence = winning_mass / (observed_mass + missing_weight)`.

M-3 - risk-penalty fallback (ConfidenceEngine.calculate_risk_penalty)
---------------------------------------------------------------------
Frozen statement: "calculate_risk_penalty has no CRITICAL entry, so
CRITICAL/UNKNOWN/EXTREME all fall back to the MEDIUM penalty (0.20)." A
maximum-risk or uninterpretable classification therefore scored as less
dangerous than a HIGH one. CRITICAL and UNKNOWN are now explicit maximum
penalties and an unrecognized PRESENT level fails closed at the maximum.

M-4 - confidence authority
--------------------------
Frozen statement: "Semantic-record mismatch only... No authority bypass."
This file proves that rather than refactoring it: the authority map below
is asserted structurally, so a future change that lets an advisory number
reach Decision.confidence fails here.

Scope note
----------
Nothing in this file relaxes the M-2 provider interlock. Third evidence
providers stay unavailable and MIN_PARTICIPATING_AGENTS stays at 3;
correcting the confidence mathematics is what makes enabling one *safe* to
consider, not a decision to enable one.
"""

from __future__ import annotations

import inspect
import itertools
import math
from datetime import UTC, datetime
from decimal import Decimal as D

import pytest

import ai.core.atlas_brain as atlas_brain_module
from ai.core.intelligence.agent_fusion import AgentFusion, AgentFusionResult
from ai.core.intelligence.confidence.confidence_engine import ConfidenceEngine
from ai.core.intelligence.decision_builder import DecisionBuilder
from ai.core.intelligence.risk_engine import AdvisoryRiskScorer, RiskCategory
from analysis.evidence_status import MarketDataEvidenceStatus
from core.decision_adapter import DecisionAdapter
from core.risk_engine import (
    PositionExposure,
    RiskBucket,
    RiskDecisionStatus,
    RiskEngine,
    RiskPolicy,
    RiskRequest,
    RiskState,
    analytical_risk_level,
)


WEIGHTS = AgentFusion.WEIGHTS
TOTAL_WEIGHT = sum(WEIGHTS.values())
ROSTER = tuple(WEIGHTS)


def signals(**scores):
    """Build a fuse() input from {agent_name: score}."""
    engine = AgentFusion()
    return {
        name: {"action": engine.score_to_action(score), "score": score}
        for name, score in scores.items()
    }


def fuse(**scores) -> AgentFusionResult:
    return AgentFusion().fuse(signals(**scores))


def full_roster(score):
    return {name: score for name in ROSTER}


# =====================================================================
# M-2 / A - full 5/5 roster is the backward-compatible baseline
# =====================================================================


def test_a_full_roster_confidence_is_the_winning_bucket_share():
    """With nothing missing there is nothing to charge, so the corrected
    formula collapses to exactly what the old one produced at coverage
    1.0: the winning bucket's share of the observed mass."""

    result = fuse(technical=0.85, momentum=0.70, risk=0.5, macro=0.5, sentiment=0.5)

    buy = 0.85 * WEIGHTS["technical"] + 0.70 * WEIGHTS["momentum"]
    hold = 0.5 * (WEIGHTS["risk"] + WEIGHTS["macro"] + WEIGHTS["sentiment"])

    assert result.action == "BUY"
    assert result.confidence == pytest.approx(round(buy / (buy + hold), 4))
    assert result.confidence == pytest.approx(result.scores["BUY"], abs=1e-3)


def test_a_full_roster_unanimous_maximal_conviction_is_one():
    assert fuse(**full_roster(1.0)).confidence == pytest.approx(1.0)


# =====================================================================
# M-2 / B, C - availability penalty at 4/5 and 3/5
# =====================================================================


def test_b_and_c_availability_ladder_under_unanimous_maximal_conviction():
    """Under perfect agreement the confidence ceiling is exactly the
    weight coverage, so the ladder is readable directly. This is the
    Step-2C intent, preserved: only the cases Step 2C computed wrongly
    moved, and they only moved down."""

    five = fuse(**full_roster(1.0))
    four = fuse(technical=1.0, momentum=1.0, risk=1.0, macro=1.0)
    three = fuse(technical=1.0, momentum=1.0, risk=1.0)

    assert five.confidence == pytest.approx(1.0)
    assert four.confidence == pytest.approx(0.9)
    assert three.confidence == pytest.approx(0.8)
    assert three.confidence < four.confidence < five.confidence


def test_c_three_of_five_is_strictly_below_the_equivalent_five_of_five():
    """Same per-agent scores, fewer participants: strictly less certain."""

    five = fuse(technical=0.9, momentum=0.9, risk=0.9, macro=0.9, sentiment=0.9)
    three = fuse(technical=0.9, momentum=0.9, risk=0.9)

    assert three.confidence < five.confidence


# =====================================================================
# M-2 / D, E - two participants and one participant
# =====================================================================


def test_d_two_participants_cannot_reach_the_confidence_stage():
    """The 2/5 rung is not a smaller number, it is no number at all: the
    participation floor returns INSUFFICIENT_EVIDENCE before any
    confidence is computed. Strongest possible bound."""

    result = fuse(technical=1.0, momentum=1.0)

    assert result.reason == "INSUFFICIENT_EVIDENCE"
    assert result.action == "HOLD"
    assert result.confidence == 0.0


def test_e_a_single_participant_is_floored_to_zero():
    for name in ROSTER:
        result = fuse(**{name: 1.0})
        assert result.reason == "INSUFFICIENT_EVIDENCE"
        assert result.confidence == 0.0


# =====================================================================
# M-2 / F, G - removing supportive evidence and removing a dissenter
# =====================================================================


def test_f_removing_a_supportive_participant_lowers_confidence():
    before = fuse(technical=0.9, momentum=0.9, risk=0.9, macro=0.9, sentiment=0.9)
    after = fuse(technical=0.9, momentum=0.9, risk=0.9, macro=0.9)

    assert before.action == after.action == "BUY"
    assert after.confidence < before.confidence


def test_g_removing_a_dissenter_never_raises_confidence():
    """The exact M-2 defect. Under the old formula the dissenter's
    disappearance shrank the denominator faster than coverage shrank the
    result, so the reported certainty went up."""

    before = fuse(technical=0.62, momentum=0.62, risk=0.0, macro=0.5, sentiment=0.5)
    after = fuse(technical=0.62, momentum=0.62, macro=0.5, sentiment=0.5)

    assert before.scores["SELL"] > 0.0
    assert after.scores["SELL"] == 0.0
    # Directional agreement genuinely improved - and confidence still did
    # not rise, because the availability charge covers exactly that gap.
    assert after.scores[after.action] > before.scores[before.action]
    assert after.confidence <= before.confidence


def test_g_reproduces_the_recorded_defect_shape_and_now_holds():
    """Grid-discovered worst single-removal case at the Package-4 starting
    HEAD: 0.667 -> 0.800 (+0.133). Now non-increasing."""

    before = fuse(technical=0.45, momentum=0.0, risk=0.45, macro=0.45, sentiment=0.45)
    after = fuse(technical=0.45, risk=0.45, macro=0.45, sentiment=0.45)

    assert before.confidence == pytest.approx(0.6667, abs=1e-3)
    assert after.confidence <= before.confidence


def test_g_exhaustive_removal_monotonicity_over_a_score_grid():
    """The property, not an example: over every roster in a boundary-
    spanning grid, removing any one or any two participants never raises
    confidence. This is the test that fails if the denominator ever
    reverts to the surviving population."""

    engine = AgentFusion()
    grid = (0.0, 0.3, 0.45, 0.6, 0.85, 1.0)

    checked = 0
    for combination in itertools.product(grid, repeat=len(ROSTER)):
        roster = signals(**dict(zip(ROSTER, combination)))
        base = engine.fuse(roster)
        if base.reason != "FUSED_EVIDENCE":
            continue
        for size in (1, 2):
            for removed in itertools.combinations(ROSTER, size):
                reduced = engine.fuse(
                    {k: v for k, v in roster.items() if k not in removed}
                )
                if reduced.reason != "FUSED_EVIDENCE":
                    continue
                checked += 1
                assert reduced.confidence <= base.confidence, (
                    f"removing {removed} from {combination} raised confidence "
                    f"{base.confidence} -> {reduced.confidence}"
                )

    assert checked > 10_000


# =====================================================================
# M-2 / H - unavailable providers are represented, never fabricated
# =====================================================================


def test_h_unavailable_providers_are_recorded_and_excluded():
    engine = AgentFusion()
    market_data = {
        "evidence_status": {
            "technical": MarketDataEvidenceStatus.AVAILABLE.value,
            "macro": "UNAVAILABLE_NO_PROVIDER",
            "sentiment": "UNAVAILABLE_NO_PROVIDER",
            "market_risk": "UNAVAILABLE_NO_PROVIDER",
        },
        "technical_score": 0.9,
        "rsi": 55,
        "trend": "BULLISH",
    }

    produced = engine.evaluate("BTCUSDT", market_data)

    assert set(produced) == {"technical", "momentum"}
    assert set(engine.last_unavailable_agents) == {"macro", "sentiment", "risk"}
    # No fabricated HOLD@0.5 stand-ins for the absent providers.
    assert all(name in produced for name in ("technical", "momentum"))


# =====================================================================
# M-2 / I - duplicate / unconfigured participants
# =====================================================================


def test_i_an_unconfigured_duplicate_cannot_raise_confidence():
    """A second participant echoing an existing one under a name that is
    not in WEIGHTS carries weight 0. It must not add mass, must not count
    toward participation, and must not move the result at all."""

    honest = fuse(technical=0.9, momentum=0.9, risk=0.9)

    engine = AgentFusion()
    padded = dict(signals(technical=0.9, momentum=0.9, risk=0.9))
    padded["technical_copy"] = {"action": "BUY", "score": 0.9}
    duplicated = engine.fuse(padded)

    assert duplicated.confidence == pytest.approx(honest.confidence)
    assert duplicated.action == honest.action


def test_i_a_configured_name_cannot_appear_twice():
    """Structural: signals is a mapping keyed by agent name, so one
    configured participant can never be counted twice."""

    roster = signals(technical=0.9, momentum=0.9, risk=0.9)
    assert len(roster) == len(set(roster))


# =====================================================================
# M-2 / J, K - stale and malformed providers
# =====================================================================


def test_j_a_stale_provider_status_excludes_the_participant():
    engine = AgentFusion()
    produced = engine.evaluate(
        "BTCUSDT",
        {
            "evidence_status": {"technical": "STALE"},
            "technical_score": 0.95,
            "rsi": 55,
            "trend": "BULLISH",
        },
    )

    assert "technical" not in produced
    assert engine.last_unavailable_agents["technical"] == "STALE"


def test_k_a_malformed_provider_is_excluded_not_defaulted():
    engine = AgentFusion()
    produced = engine.evaluate(
        "BTCUSDT",
        {
            "evidence_status": {
                "technical": MarketDataEvidenceStatus.AVAILABLE.value,
            },
            # AVAILABLE claimed, no value supplied.
            "rsi": "not-a-number",
            "trend": "BULLISH",
        },
    )

    assert produced == {}
    assert (
        engine.last_unavailable_agents["technical"]
        == "SCORE_MISSING_DESPITE_AVAILABLE_STATUS"
    )
    assert (
        engine.last_unavailable_agents["momentum"]
        == "RSI_UNAVAILABLE_OR_MALFORMED"
    )


# =====================================================================
# M-2 / L, M - expected roster versus observed roster
# =====================================================================


def test_l_expected_roster_larger_than_observed_charges_the_difference():
    """The denominator is the configured roster, so it cannot shrink just
    because providers disappeared."""

    result = fuse(technical=1.0, momentum=1.0, risk=1.0)
    observed_weight = WEIGHTS["technical"] + WEIGHTS["momentum"] + WEIGHTS["risk"]

    assert result.confidence == pytest.approx(
        round(observed_weight / TOTAL_WEIGHT, 4)
    )
    assert result.confidence < 1.0


def test_m_expected_roster_equal_to_observed_charges_nothing():
    result = fuse(**full_roster(1.0))
    assert result.confidence == pytest.approx(1.0)


def test_m_confidence_engine_denominator_is_the_expected_roster():
    """The NB-4/NB-5 correction on the advisory side, still in force."""

    engine = ConfidenceEngine()
    agents = {f"a{i}": {"action": "BUY"} for i in range(3)}

    assert engine.calculate_agent_agreement(agents, expected_agent_count=5) == (
        pytest.approx(0.6)
    )
    assert engine.calculate_agent_agreement(agents) == pytest.approx(1.0)


# =====================================================================
# M-2 / N - the availability adjustment is applied exactly once
# =====================================================================


def test_n_no_double_availability_scaling():
    """The old formula's shape, computed explicitly, must no longer be
    what fuse() returns."""

    result = fuse(technical=0.9, momentum=0.8, risk=0.7)

    available_weight = WEIGHTS["technical"] + WEIGHTS["momentum"] + WEIGHTS["risk"]
    coverage = available_weight / TOTAL_WEIGHT
    buy = 0.9 * WEIGHTS["technical"] + 0.8 * WEIGHTS["momentum"] + 0.7 * WEIGHTS["risk"]

    corrected = round(buy / (buy + (TOTAL_WEIGHT - available_weight)), 4)
    old_double_scaled = round(1.0 * coverage, 4)

    assert result.confidence == pytest.approx(corrected)
    assert result.confidence != pytest.approx(old_double_scaled)
    # And the corrected value is not itself scaled a second time.
    assert result.confidence != pytest.approx(round(corrected * coverage, 4))


def test_n_fusion_never_consults_the_confidence_engine():
    source = inspect.getsource(
        __import__(
            "ai.core.intelligence.agent_fusion", fromlist=["agent_fusion"]
        )
    )
    assert "ConfidenceEngine" not in source
    assert "confidence_engine" not in source


# =====================================================================
# M-2 / O - risk classification monotonicity
# =====================================================================


def test_o_evidence_loss_never_relaxes_the_advisory_risk_bucket():
    engine = ConfidenceEngine()
    scorer = AdvisoryRiskScorer()
    reasoning = {"confidence": 0.7}

    previous_score = None
    previous_index = None
    for available in (5, 4, 3, 2, 1):
        agents = {f"a{i}": {"action": "BUY"} for i in range(available)}
        confidence = engine.calculate(
            agents, reasoning, {"level": "MEDIUM"}, expected_agent_count=5,
        )
        risk = scorer.calculate(confidence=confidence.value)
        index = list(RiskCategory).index(risk.level)

        if previous_score is not None:
            assert risk.score >= previous_score
            assert index >= previous_index
        previous_score, previous_index = risk.score, index


# =====================================================================
# M-2 / P - execution safety is unchanged
# =====================================================================


def test_p_execution_admission_gates_are_untouched():
    policy = RiskPolicy(total_capital=D("1000"))

    assert policy.global_minimum_confidence == D("0.60")
    assert policy.buckets[RiskBucket.LOW].minimum_confidence == D("0.60")
    assert policy.buckets[RiskBucket.MEDIUM].minimum_confidence == D("0.70")
    assert policy.buckets[RiskBucket.HIGH].minimum_confidence == D("0.80")
    assert policy.buckets[RiskBucket.LOW].max_allocation_pct == D("0.40")
    assert policy.buckets[RiskBucket.MEDIUM].max_allocation_pct == D("0.25")
    assert policy.buckets[RiskBucket.HIGH].max_allocation_pct == D("0.10")


def test_p_a_lower_confidence_can_only_narrow_admission():
    """The corrected fusion values are lower, never higher, so no request
    that used to be rejected on confidence can now be admitted."""

    engine = RiskEngine(RiskPolicy(total_capital=D("1000")))
    ready = RiskState(
        (), D("0"), D("0"), D("1000"), D("1000"), True,
        datetime.now(UTC).date().isoformat(), "phase3-risk-v1",
    )

    def admit(confidence):
        return engine.evaluate(
            RiskRequest(
                symbol="ETHUSDT", action="BUY", confidence=D(confidence),
                requested_quote_allocation=D("50"), execution_price=D("10"),
                risk_bucket="MEDIUM", base_quantity=D("5"),
            ),
            ready,
        )

    assert admit("0.95").status is RiskDecisionStatus.APPROVE
    assert admit("0.65").reason_code == "CONFIDENCE_BELOW_POLICY"


# =====================================================================
# M-2 / Q, R - third-provider simulation and the retained interlock
# =====================================================================


def test_q_simulated_third_provider_obeys_monotonicity_without_going_live():
    """A hand-built macro participant, exercising fuse() only. No producer
    is enabled and no evidence_status changes."""

    with_third = fuse(technical=0.85, momentum=0.70, macro=0.90)
    without_third = fuse(technical=0.85, momentum=0.70)

    assert with_third.reason == "FUSED_EVIDENCE"
    # Removing it drops below the floor rather than raising confidence.
    assert without_third.reason == "INSUFFICIENT_EVIDENCE"
    assert without_third.confidence < with_third.confidence

    # And with a fourth participant present so the floor is not what does
    # the work, silencing the dissenting third provider buys nothing.
    dissenting = fuse(technical=0.62, momentum=0.62, macro=0.0, sentiment=0.62)
    silenced = fuse(technical=0.62, momentum=0.62, sentiment=0.62)

    assert dissenting.reason == silenced.reason == "FUSED_EVIDENCE"
    assert silenced.scores["SELL"] == 0.0 < dissenting.scores["SELL"]
    assert silenced.confidence <= dissenting.confidence


def test_r_the_m2_provider_interlock_is_still_active():
    """M-2's mathematics is corrected; its interlock is deliberately not
    lifted. Enabling a third evidence provider stays a separate decision."""

    from analysis.world_analysis_engine import WorldAnalysisEngine

    assert AgentFusion.MIN_PARTICIPATING_AGENTS == 3
    assert AgentFusion.MIN_WEIGHT_COVERAGE == 0.50

    market_data = WorldAnalysisEngine().build_market_data(
        "BTCUSDT", 100.0, analysis={}, score=0.5,
    )
    for provider in ("macro", "sentiment", "market_risk"):
        assert market_data["evidence_status"][provider] == (
            MarketDataEvidenceStatus.UNAVAILABLE_NO_PROVIDER.value
        )


# =====================================================================
# M-2 red team: out-of-contract scores
# =====================================================================


def test_redteam_confidence_stays_within_zero_and_one_for_in_contract_scores():
    engine = AgentFusion()
    for combination in itertools.product((0.0, 0.4, 0.6, 1.0), repeat=len(ROSTER)):
        result = engine.fuse(signals(**dict(zip(ROSTER, combination))))
        assert 0.0 <= result.confidence <= 1.0


@pytest.mark.parametrize(
    "score",
    [5.0, -5.0, 1.0001, -0.0001, float("nan"), float("inf"), float("-inf"),
     "0.9", True, None, [0.9]],
)
def test_redteam_an_out_of_contract_score_excludes_its_participant(score):
    """Found by red team at the Package-4 starting HEAD: fuse() trusted
    the score range, so a score outside [0, 1] made a bucket mass exceed
    the participant's weight and confidence escaped [0, 1] entirely
    (measured: 1.3333). The participant is now excluded rather than
    clamped, matching how NB-1/NB-3 treat a malformed RSI."""

    result = AgentFusion().fuse(
        {
            "technical": {"action": "BUY", "score": score},
            "momentum": {"action": "BUY", "score": 0.9},
            "risk": {"action": "BUY", "score": 0.9},
        }
    )

    # Two survivors is below the participation floor, so exclusion here
    # fails closed all the way to no directional decision at all.
    assert result.reason == "INSUFFICIENT_EVIDENCE"
    assert result.confidence == 0.0


def test_redteam_an_out_of_contract_score_is_reported_as_a_diagnostic():
    engine = AgentFusion()
    engine.evaluate(
        "BTCUSDT",
        {
            "evidence_status": {
                "technical": MarketDataEvidenceStatus.AVAILABLE.value,
            },
            "technical_score": 4.2,
            "rsi": 55,
            "trend": "BULLISH",
        },
    )

    assert (
        engine.last_unavailable_agents["technical"]
        == "SCORE_OUT_OF_CONTRACT_RANGE"
    )


def test_redteam_confidence_is_bounded_by_the_arithmetic_not_a_clamp():
    """Whatever is thrown at fuse(), the reported confidence stays in
    [0, 1] without any downstream clamp being involved."""

    engine = AgentFusion()
    hostile = (0.0, 1.0, 0.5, -3.0, 7.0, float("nan"), "x", None)

    for combination in itertools.product(hostile, repeat=3):
        result = engine.fuse(
            {
                name: {"action": "BUY", "score": score}
                for name, score in zip(("technical", "momentum", "risk"), combination)
            }
        )
        assert 0.0 <= result.confidence <= 1.0


def test_redteam_a_nan_score_cannot_produce_a_nan_decision_confidence():
    """Two independent defences, asserted together: fuse() excludes the
    NaN participant, and Decision normalizes whatever reaches it. Neither
    is allowed to be the only one that works."""

    result = AgentFusion().fuse(
        {
            "technical": {"action": "BUY", "score": float("nan")},
            "momentum": {"action": "BUY", "score": 0.9},
            "risk": {"action": "BUY", "score": 0.9},
        }
    )

    decision = DecisionBuilder().create(
        "BTCUSDT", result, AdvisoryRiskScorer().calculate(confidence=0.5),
    )
    assert not math.isnan(decision.confidence)
    assert 0.0 <= decision.confidence <= 100.0


# =====================================================================
# M-3 - risk-penalty taxonomy
# =====================================================================


def test_m3_critical_and_unknown_are_explicit_maximum_penalties():
    engine = ConfidenceEngine()

    low = engine.calculate_risk_penalty({"level": "LOW"})
    medium = engine.calculate_risk_penalty({"level": "MEDIUM"})
    high = engine.calculate_risk_penalty({"level": "HIGH"})
    critical = engine.calculate_risk_penalty({"level": "CRITICAL"})
    unknown = engine.calculate_risk_penalty({"level": "UNKNOWN"})

    assert low < medium < high < critical
    assert critical == unknown == 1.00
    # The three pre-existing values are untouched: no policy number moved.
    assert (low, medium, high) == (0.05, 0.20, 0.40)


def test_m3_unsupported_present_level_fails_closed_at_the_maximum():
    engine = ConfidenceEngine()

    for label in ("EXTREME", "VERY_HIGH", "SEVERE", "anything_new", "5"):
        penalty = engine.calculate_risk_penalty({"level": label})
        assert penalty == 1.00, label
        assert penalty != 0.20


def test_m3_non_textual_present_level_fails_closed():
    engine = ConfidenceEngine()
    assert engine.calculate_risk_penalty({"level": 5}) == 1.00
    assert engine.calculate_risk_penalty({"level": ["HIGH"]}) == 1.00


def test_m3_absence_keeps_the_frozen_medium_default():
    """Block-1's convention: a missing/None/empty risk value keeps MEDIUM
    and is never confused with malformed PRESENT input. It is no longer
    zero, which had made "no risk information" the single most favourable
    input this method accepted."""

    engine = ConfidenceEngine()

    for absent in (None, {}, {"level": None}, {"level": ""}, {"score": 0.9}):
        assert engine.calculate_risk_penalty(absent) == 0.20


def test_m3_case_and_whitespace_follow_the_canonical_risk_parser():
    engine = ConfidenceEngine()

    for raw in ("high", " HIGH ", "High"):
        assert engine.calculate_risk_penalty({"level": raw}) == 0.40
        assert analytical_risk_level(raw) == "HIGH"


def test_m3_enum_levels_resolve_like_their_values():
    engine = ConfidenceEngine()
    assert engine.calculate_risk_penalty({"level": RiskCategory.CRITICAL}) == 1.00
    assert engine.calculate_risk_penalty({"level": RiskCategory.LOW}) == 0.05


def test_m3_a_worse_risk_level_can_only_lower_confidence():
    engine = ConfidenceEngine()
    agents = {f"a{i}": {"action": "BUY"} for i in range(5)}
    reasoning = {"confidence": 0.7}

    values = [
        engine.calculate(agents, reasoning, {"level": level}, expected_agent_count=5).value
        for level in ("LOW", "MEDIUM", "HIGH", "CRITICAL")
    ]
    assert values == sorted(values, reverse=True)
    assert len(set(values)) == 4


def test_m3_live_call_site_still_passes_a_static_medium_level():
    """M-3's closure makes a dynamic risk level safe; it does not
    introduce one. The single production caller is unchanged."""

    source = inspect.getsource(atlas_brain_module)
    assert '"level": "MEDIUM"' in source or "'level': 'MEDIUM'" in source


# =====================================================================
# M-3 red team: the executable risk boundary is unchanged
# =====================================================================


def risk_state(*positions):
    return RiskState(
        tuple(positions),
        sum((p.quote_exposure for p in positions), D("0")),
        D("0"), D("1000"), D("1000"), True,
        datetime.now(UTC).date().isoformat(), "phase3-risk-v1",
    )


def buy_request(bucket):
    return RiskRequest(
        symbol="ETHUSDT", action="BUY", confidence=D("0.95"),
        requested_quote_allocation=D("50"), execution_price=D("10"),
        risk_bucket=bucket, base_quantity=D("5"),
    )


def reduce_request(bucket):
    return RiskRequest(
        symbol="ETHUSDT", action="SELL", confidence=D("0.95"),
        requested_quote_allocation=D("100"), execution_price=D("10"),
        risk_bucket=bucket, base_quantity=D("10"), reduce_only=True,
    )


@pytest.mark.parametrize("bucket", ["CRITICAL", "UNKNOWN", "EXTREME"])
def test_m3_redteam_new_risk_is_refused_for_non_executable_levels(bucket):
    result = RiskEngine(RiskPolicy(total_capital=D("1000"))).evaluate(
        buy_request(bucket), risk_state(),
    )

    assert result.status is RiskDecisionStatus.REJECT
    assert result.approved_allocation == D("0")
    assert result.reason_code in {
        "CRITICAL_RISK_NOT_EXECUTABLE", "UNSUPPORTED_RISK_LEVEL",
    }


@pytest.mark.parametrize("bucket", ["CRITICAL", "UNKNOWN", "EXTREME"])
def test_m3_redteam_reduce_only_exits_stay_possible(bucket):
    """Refusing an exit would trap exposure in the state judged most
    dangerous. Restrictive risk must never do that."""

    position = PositionExposure("ETHUSDT", D("10"), D("10"), D("100"))
    result = RiskEngine(RiskPolicy(total_capital=D("1000"))).evaluate(
        reduce_request(bucket), risk_state(position),
    )

    assert result.status is RiskDecisionStatus.APPROVE
    assert result.reason_code == "RISK_REDUCTION_APPROVED"


def test_m3_redteam_missing_risk_stays_distinguishable_from_unsupported():
    assert analytical_risk_level("EXTREME") == "UNKNOWN"
    for absent in ("", "   ", None, 5):
        with pytest.raises(ValueError):
            analytical_risk_level(absent)


def test_m3_redteam_risk_level_survives_a_serialization_round_trip():
    scorer = AdvisoryRiskScorer()
    result = scorer.calculate(confidence=0.05)

    serialized = result.to_dict()
    assert serialized["level"] == result.level.value
    assert analytical_risk_level(serialized["level"]) == result.level.value

    engine = ConfidenceEngine()
    assert engine.calculate_risk_penalty(serialized) == (
        engine.calculate_risk_penalty({"level": result.level})
    )


# =====================================================================
# M-4 - confidence authority map
# =====================================================================


def test_m4_decision_confidence_has_exactly_one_producer():
    """Structural: DecisionBuilder.create() takes no confidence argument,
    so nothing but fusion.confidence can set Decision.confidence."""

    parameters = set(inspect.signature(DecisionBuilder.create).parameters)
    assert not any("confidence" in name for name in parameters)

    fusion = fuse(technical=0.9, momentum=0.9, risk=0.9)
    decision = DecisionBuilder().create(
        "BTCUSDT", fusion, AdvisoryRiskScorer().calculate(confidence=0.99),
    )
    assert decision.confidence == round(fusion.confidence * 100, 2)


def test_m4_an_advisory_value_cannot_displace_the_authoritative_one():
    """A deliberately divergent advisory confidence, attached exactly the
    way AtlasBrain attaches it, must leave Decision.confidence alone."""

    fusion = fuse(technical=0.9, momentum=0.9, risk=0.9)
    advisory = ConfidenceEngine().calculate(
        {"technical": {"action": "SELL"}}, {"confidence": 0.05},
        {"level": "MEDIUM"}, expected_agent_count=5,
    )
    assert advisory.value != fusion.confidence

    decision = DecisionBuilder().create(
        "BTCUSDT", fusion, AdvisoryRiskScorer().calculate(confidence=advisory.value),
    )
    decision.metadata["intermediate_confidence"] = advisory.value * 100
    decision.metadata["final_confidence"] = float(decision.confidence)

    assert decision.confidence == round(fusion.confidence * 100, 2)
    assert DecisionAdapter.get_confidence(decision) == pytest.approx(
        decision.confidence
    )


def test_m4_the_adapter_cannot_select_an_advisory_confidence_field():
    """The names an advisory number travels under are not in the
    adapter's search vocabulary, and metadata is not one of the
    containers it descends into."""

    assert "intermediate_confidence" not in DecisionAdapter.CONFIDENCE_KEYS
    assert "advisory_confidence" not in DecisionAdapter.CONFIDENCE_KEYS
    assert "reasoning_confidence" not in DecisionAdapter.CONFIDENCE_KEYS
    assert "metadata" not in DecisionAdapter.CONFIDENCE_CONTAINER_KEYS
    # And the authoritative names are searched ahead of the generic ones.
    keys = DecisionAdapter.CONFIDENCE_KEYS
    assert keys.index("final_confidence") < keys.index("confidence")
    assert keys.index("decision_confidence") < keys.index("score")


def test_m4_only_atlas_brain_produces_the_advisory_record():
    """One producer, zero consumers: the advisory value is a diagnostic
    record and has no downstream reader to mislead."""

    from pathlib import Path

    root = Path(__file__).resolve().parent.parent
    producers = []
    for package in ("core", "ai", "analysis", "portfolio"):
        directory = root / package
        if not directory.exists():
            continue
        for path in directory.rglob("*.py"):
            if "intermediate_confidence" in path.read_text(
                encoding="utf-8-sig", errors="ignore"
            ):
                producers.append(path.relative_to(root).as_posix())

    assert producers == ["ai/core/atlas_brain.py"]


def test_m4_advisory_confidence_reaches_risk_level_only_and_conservatively():
    """The one financial channel the advisory value does have: it selects
    the analytical risk level, which selects an executable bucket. That
    channel is bounded in the safe direction - a *lower* advisory value
    can only produce an equal or stricter bucket, never a looser one."""

    scorer = AdvisoryRiskScorer()
    previous = None
    for advisory in (0.95, 0.8, 0.6, 0.4, 0.2, 0.0):
        risk = scorer.calculate(confidence=advisory)
        index = list(RiskCategory).index(risk.level)
        if previous is not None:
            assert index >= previous
        previous = index

    # And the value compared against bucket minimums is the authoritative
    # one, re-derived at admission from Decision.confidence - never this.
    source = inspect.getsource(RiskEngine.evaluate)
    assert "request.confidence" in source
    assert "intermediate" not in source


def test_m4_intelligence_cannot_reach_the_execution_risk_authority():
    """core.risk_engine is the confidence authority at admission, and the
    L4->L2/L3 forbidden edges mean intelligence cannot import it to
    substitute a value of its own."""

    from pathlib import Path

    root = Path(__file__).resolve().parent.parent
    offenders = []
    for path in (root / "ai").rglob("*.py"):
        text = path.read_text(encoding="utf-8-sig", errors="ignore")
        if "from core.risk_engine import" in text or "import core.risk_engine" in text:
            offenders.append(path.relative_to(root).as_posix())

    assert offenders == []


# =====================================================================
# M-4 red team: malformed / stale advisory values
# =====================================================================


def test_m4_redteam_the_advisory_value_is_always_in_range_by_construction():
    """AdvisoryRiskScorer clamps, and an out-of-range input would be
    clamped to a *favourable* value - so the protection that matters is
    that ConfidenceEngine cannot emit one. It cannot: calculate() bounds
    its result to [0, 1] before the scorer ever sees it."""

    engine = ConfidenceEngine()
    for reasoning_confidence in (-5, 0, 0.5, 1, 500, 10_000):
        result = engine.calculate(
            {"a": {"action": "BUY"}}, {"confidence": reasoning_confidence},
            {"level": "MEDIUM"}, expected_agent_count=5,
        )
        assert 0.0 <= result.value <= 1.0


def test_m4_redteam_a_stale_advisory_record_cannot_leak_between_cycles():
    """Each calculate() call is pure - no instance state carries a prior
    cycle's value forward."""

    engine = ConfidenceEngine()
    strong = engine.calculate(
        {f"a{i}": {"action": "BUY"} for i in range(5)}, {"confidence": 0.9},
        {"level": "LOW"}, expected_agent_count=5,
    )
    weak = engine.calculate(
        {"a0": {"action": "BUY"}}, {"confidence": 0.0},
        {"level": "CRITICAL"}, expected_agent_count=5,
    )
    again = engine.calculate(
        {f"a{i}": {"action": "BUY"} for i in range(5)}, {"confidence": 0.9},
        {"level": "LOW"}, expected_agent_count=5,
    )

    assert weak.value < strong.value
    assert again.value == strong.value
    assert not vars(engine)
