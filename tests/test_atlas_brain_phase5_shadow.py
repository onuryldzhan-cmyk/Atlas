from __future__ import annotations

import json
import os

from datetime import UTC, datetime
from decimal import Decimal

import pytest

from ai.core.atlas_brain import AtlasBrain
from ai.core.intelligence.agent_fusion import AgentFusion
from analysis.evidence_status import MarketDataEvidenceStatus
from core.decision_intelligence import Action, CanonicalDecision


@pytest.fixture(autouse=True)
def _isolated_cwd(tmp_path, monkeypatch):
    # AtlasBrain() construction bootstraps AtlasMemoryCore/
    # AtlasReasoningEngine/AtlasWorldModel, each of which may create a
    # CWD-relative "memory_data" directory (production behavior, left
    # unchanged). Redirecting the test CWD into pytest's isolated
    # tmp_path keeps that side effect out of the repository/dev
    # environment without mocking or disabling any production code.
    monkeypatch.chdir(tmp_path)


MARKET_DATA = {
    "price": 65_000.0,
    "technical_score": 0.8,
    "risk_score": 0.7,
    "macro_score": 0.75,
    "sentiment_score": 0.9,
    # Post-Step-2A/2C evidence_status contract (this fixture predates
    # it and lacked the key entirely, which the current baseline
    # AgentFusion.evaluate() treats as every status-gated field being
    # unavailable - never as implicit availability). This fixture
    # deliberately supplies real numeric values for exactly these four
    # fields, so each is marked AVAILABLE, matching the fixture's
    # original intent (not a fabricated 0.5 placeholder). momentum has
    # no evidence_status entry by contract - it is derived internally
    # from rsi/trend, not a producer field.
    "evidence_status": {
        "technical": MarketDataEvidenceStatus.AVAILABLE.value,
        "macro": MarketDataEvidenceStatus.AVAILABLE.value,
        "sentiment": MarketDataEvidenceStatus.AVAILABLE.value,
        "market_risk": MarketDataEvidenceStatus.AVAILABLE.value,
    },
    # Step NB-3: this fixture predates momentum's evidence-presence
    # gate too. It previously omitted "rsi"/"trend" entirely, which
    # AgentFusion.evaluate() used to tolerate by letting
    # calculate_momentum() silently default to rsi=50/trend="SIDEWAYS"
    # internally - producing this exact HOLD@0.5 momentum vote from
    # fabricated evidence. Post-NB-3, an absent "rsi"/"trend" key
    # excludes momentum instead. Supplying these explicitly (the same
    # values the old default computed) keeps momentum's vote and every
    # numeric assertion in this file byte-identical, while making its
    # participation genuine test-supplied evidence rather than a
    # producer-side fabricated default.
    "rsi": 50,
    "trend": "SIDEWAYS",
    # Generated once at import time; every test in this file runs well
    # inside the 5-minute freshness window, so this is not a sleep- or
    # elapsed-time-dependent assertion.
    "timestamp": datetime.now(UTC).isoformat(),
}


def _execution_relevant_fields(decision) -> dict:
    return {
        "action": decision.action,
        "confidence": decision.confidence,
        "risk_level": decision.risk_level,
        "price": getattr(decision, "price", None),
    }


def test_phase5_shadow_does_not_alter_execution_relevant_fields() -> None:
    baseline_brain = AtlasBrain()
    baseline_brain._build_phase5_shadow_proposal = (  # type: ignore[method-assign]
        lambda *args, **kwargs: None
    )
    baseline_decision = baseline_brain.analyze_and_decide(
        "BTCUSDT",
        MARKET_DATA,
    )

    assert "phase5_proposal" not in baseline_decision.metadata

    shadow_brain = AtlasBrain()
    shadow_decision = shadow_brain.analyze_and_decide(
        "BTCUSDT",
        MARKET_DATA,
    )

    assert "phase5_proposal" in shadow_decision.metadata

    assert _execution_relevant_fields(
        baseline_decision
    ) == _execution_relevant_fields(
        shadow_decision
    )


def test_phase5_confidence_may_diverge_materially_from_baseline_by_design() -> None:
    # Phase 5 intentionally uses SignalFusion's equal-weight,
    # one-source-one-vote conviction instead of AgentFusion.WEIGHTS'
    # configured importance weighting - it is a different research
    # metric, not a reproduction of production conviction. Divergence
    # here is expected behavior, not a parity regression.
    baseline_brain = AtlasBrain()
    baseline_brain._build_phase5_shadow_proposal = (  # type: ignore[method-assign]
        lambda *args, **kwargs: None
    )
    baseline_decision = baseline_brain.analyze_and_decide(
        "BTCUSDT",
        MARKET_DATA,
    )

    shadow_brain = AtlasBrain()
    shadow_decision = shadow_brain.analyze_and_decide(
        "BTCUSDT",
        MARKET_DATA,
    )

    # Execution-relevant output is unaffected by enabling Phase 5.
    assert _execution_relevant_fields(
        baseline_decision
    ) == _execution_relevant_fields(
        shadow_decision
    )

    baseline_confidence_pct = shadow_decision.confidence
    phase5_confidence_pct = 100 * float(
        shadow_decision.metadata["phase5_proposal"]["confidence"]
    )

    # Same agent inputs, deliberately different weighting semantics:
    # baseline ~86.2% (weighted bucket-share) vs Phase 5 ~63.0% (equal
    # -weight signed average). Assert the gap is real and material.
    assert abs(
        baseline_confidence_pct - phase5_confidence_pct
    ) > 10


def test_phase5_shadow_construction_failure_does_not_break_legacy_decision() -> None:
    baseline_brain = AtlasBrain()
    baseline_brain._build_phase5_shadow_proposal = (  # type: ignore[method-assign]
        lambda *args, **kwargs: None
    )
    baseline_decision = baseline_brain.analyze_and_decide(
        "BTCUSDT",
        MARKET_DATA,
    )

    failing_brain = AtlasBrain()

    def _raise(*args, **kwargs):
        raise RuntimeError("simulated phase5 construction failure")

    failing_brain._build_phase5_shadow_proposal = _raise  # type: ignore[method-assign]

    failing_decision = failing_brain.analyze_and_decide(
        "BTCUSDT",
        MARKET_DATA,
    )

    assert _execution_relevant_fields(
        baseline_decision
    ) == _execution_relevant_fields(
        failing_decision
    )
    assert "phase5_proposal" not in failing_decision.metadata


def test_phase5_shadow_creates_one_evidence_per_agent() -> None:
    brain = AtlasBrain()

    fixed_now = datetime(2026, 1, 1, 12, 5, 0, tzinfo=UTC)
    market_data = {
        **MARKET_DATA,
        "timestamp": "2026-01-01T12:04:30+00:00",
    }
    agent_results = {
        "technical": {"action": "BUY", "score": 0.8},
        "momentum": {"action": "HOLD", "score": 0.5},
        "risk": {"action": "SELL", "score": 0.6},
    }

    proposal = brain._build_phase5_shadow_proposal(
        "BTCUSDT",
        agent_results,
        market_data,
        now=fixed_now,
    )

    assert isinstance(proposal, CanonicalDecision)
    assert proposal.authority == "PROPOSAL_ONLY"
    assert len(proposal.strategy_sources) == 3
    assert proposal.symbol == "BTCUSDT"
    # CanonicalDecision.timestamp is the independent fusion/evaluation
    # time, not the ingestion timestamp used for Evidence.observed_at.
    assert proposal.timestamp == fixed_now


def test_sell_score_conviction_matches_agent_fusion_convention() -> None:
    # AgentFusion.fuse() treats SELL strength as (1 - score); score_to_action
    # only emits SELL for score <= 0.40, so 0.10 is a strong, realistic SELL.
    assert AtlasBrain._agent_score_to_conviction("SELL", 0.10) == 0.90
    assert AtlasBrain._agent_score_to_conviction("BUY", 0.80) == 0.80
    assert AtlasBrain._agent_score_to_conviction("HOLD", 0.50) == 0.50


def test_strong_sell_produces_high_sell_conviction_proposal() -> None:
    brain = AtlasBrain()

    # F-1 (P4-CLOSURE-004): the shadow fusion now counts the full expected roster
    # (AgentFusion.WEIGHTS). Every agent votes the same way so this test keeps its own
    # subject; a lone agent deciding for all five is covered by the NB-5 tests.
    agent_results = {name: {"action": "SELL", "score": 0.10} for name in AgentFusion.WEIGHTS}

    proposal = brain._build_phase5_shadow_proposal(
        "BTCUSDT",
        agent_results,
        MARKET_DATA,
    )

    assert isinstance(proposal, CanonicalDecision)
    assert proposal.action is Action.SELL
    # conviction must reflect (1 - 0.10) = 0.90, not the raw 0.10 score.
    assert proposal.confidence > Decimal("0.5")


def test_phase5_shadow_fails_safe_on_malformed_agent_results() -> None:
    brain = AtlasBrain()

    proposal = brain._build_phase5_shadow_proposal(
        "BTCUSDT",
        {"technical": {"action": "NOT_AN_ACTION", "score": 0.8}},
        MARKET_DATA,
    )

    assert proposal is None

    decision = brain.analyze_and_decide(
        "BTCUSDT",
        MARKET_DATA,
    )

    assert decision.action.value in {"BUY", "SELL", "HOLD"}
    assert isinstance(decision.confidence, float)


# =========================================================
# INGESTION-TIME FRESHNESS (Evidence.observed_at semantics)
# =========================================================


def test_ingestion_timestamp_is_used_as_evidence_observed_at() -> None:
    # Proves Evidence.observed_at is derived from market_data["timestamp"]
    # (ingestion time), not cycle-start or wall-clock construction time.
    brain = AtlasBrain()

    fixed_now = datetime(2026, 1, 1, 12, 5, 0, tzinfo=UTC)
    ingestion_timestamp = "2026-01-01T12:04:30+00:00"
    market_data = {
        **MARKET_DATA,
        "timestamp": ingestion_timestamp,
    }

    proposal = brain._build_phase5_shadow_proposal(
        "BTCUSDT",
        {"technical": {"action": "BUY", "score": 0.8}},
        market_data,
        now=fixed_now,
    )

    assert isinstance(proposal, CanonicalDecision)

    expected_observed_at = datetime.fromisoformat(
        ingestion_timestamp
    )
    assert proposal.evidence_ids == (
        f"agent:technical:BTCUSDT:{expected_observed_at.isoformat()}",
    )


def test_stale_ingestion_timestamp_is_rejected_by_freshness_gate() -> None:
    # Proves the previously-dead freshness path is now reachable: an
    # ingestion timestamp older than FreshnessPolicy.max_age (5 minutes
    # by default) relative to an independent fusion `now` causes the
    # evidence to be excluded, degrading the proposal to ABSTAIN.
    brain = AtlasBrain()

    fixed_now = datetime(2026, 1, 1, 12, 10, 0, tzinfo=UTC)
    stale_market_data = {
        **MARKET_DATA,
        "timestamp": "2026-01-01T12:00:00+00:00",  # 10 minutes old
    }

    proposal = brain._build_phase5_shadow_proposal(
        "BTCUSDT",
        {"technical": {"action": "BUY", "score": 0.8}},
        stale_market_data,
        now=fixed_now,
    )

    assert isinstance(proposal, CanonicalDecision)
    assert proposal.action is Action.ABSTAIN
    assert proposal.confidence == Decimal("0")
    assert proposal.evidence_ids == ()


def test_fresh_ingestion_timestamp_is_accepted_by_freshness_gate() -> None:
    brain = AtlasBrain()

    fixed_now = datetime(2026, 1, 1, 12, 10, 0, tzinfo=UTC)
    fresh_market_data = {
        **MARKET_DATA,
        "timestamp": "2026-01-01T12:09:00+00:00",  # 1 minute old
    }

    # F-1 (P4-CLOSURE-004): the shadow fusion now counts the full expected roster
    # (AgentFusion.WEIGHTS). Every agent votes the same way so this test keeps its own
    # subject; a lone agent deciding for all five is covered by the NB-5 tests.
    proposal = brain._build_phase5_shadow_proposal(
        "BTCUSDT",
        {name: {"action": "BUY", "score": 0.8} for name in AgentFusion.WEIGHTS},
        fresh_market_data,
        now=fixed_now,
    )

    assert isinstance(proposal, CanonicalDecision)
    assert proposal.action is Action.BUY
    assert len(proposal.evidence_ids) == len(AgentFusion.WEIGHTS)


def test_freshness_boundary_matches_strict_greater_than_semantics() -> None:
    # FreshnessPolicy marks STALE only when (now - observed_at) > max_age
    # (strict greater-than); exactly max_age must remain VALID. This is
    # a characterization of Evidence.quality_at()'s existing comparison,
    # not a change to FreshnessPolicy itself.
    brain = AtlasBrain()
    fixed_now = datetime(2026, 1, 1, 12, 5, 0, tzinfo=UTC)
    # F-1 (P4-CLOSURE-004): the shadow fusion now counts the full expected roster
    # (AgentFusion.WEIGHTS). Every agent votes the same way so this test keeps its own
    # subject; a lone agent deciding for all five is covered by the NB-5 tests.
    agent_results = {name: {"action": "BUY", "score": 0.8} for name in AgentFusion.WEIGHTS}

    at_exactly_max_age = {
        **MARKET_DATA,
        "timestamp": "2026-01-01T12:00:00+00:00",  # exactly 5:00 old
    }
    proposal_at_boundary = brain._build_phase5_shadow_proposal(
        "BTCUSDT",
        agent_results,
        at_exactly_max_age,
        now=fixed_now,
    )
    assert proposal_at_boundary.action is Action.BUY

    just_past_max_age = {
        **MARKET_DATA,
        "timestamp": "2026-01-01T11:59:59+00:00",  # 5:01 old
    }
    proposal_past_boundary = brain._build_phase5_shadow_proposal(
        "BTCUSDT",
        agent_results,
        just_past_max_age,
        now=fixed_now,
    )
    assert proposal_past_boundary.action is Action.ABSTAIN


def test_missing_ingestion_timestamp_fails_safe() -> None:
    brain = AtlasBrain()

    market_data_no_timestamp = {
        key: value
        for key, value in MARKET_DATA.items()
        if key != "timestamp"
    }

    proposal = brain._build_phase5_shadow_proposal(
        "BTCUSDT",
        {"technical": {"action": "BUY", "score": 0.8}},
        market_data_no_timestamp,
    )
    assert proposal is None

    decision = brain.analyze_and_decide(
        "BTCUSDT",
        market_data_no_timestamp,
    )
    assert "phase5_proposal" not in decision.metadata
    assert decision.action.value in {"BUY", "SELL", "HOLD"}


def test_malformed_ingestion_timestamp_fails_safe() -> None:
    brain = AtlasBrain()

    malformed_market_data = {
        **MARKET_DATA,
        "timestamp": "not-a-timestamp",
    }

    proposal = brain._build_phase5_shadow_proposal(
        "BTCUSDT",
        {"technical": {"action": "BUY", "score": 0.8}},
        malformed_market_data,
    )
    assert proposal is None

    decision = brain.analyze_and_decide(
        "BTCUSDT",
        malformed_market_data,
    )
    assert "phase5_proposal" not in decision.metadata
    assert decision.action.value in {"BUY", "SELL", "HOLD"}


def test_naive_ingestion_timestamp_is_not_trusted() -> None:
    # A timezone-unaware timestamp must never be silently treated as
    # verified UTC provenance.
    brain = AtlasBrain()

    naive_market_data = {
        **MARKET_DATA,
        "timestamp": "2026-01-01T12:00:00",  # no offset
    }

    proposal = brain._build_phase5_shadow_proposal(
        "BTCUSDT",
        {"technical": {"action": "BUY", "score": 0.8}},
        naive_market_data,
    )
    assert proposal is None

    decision = brain.analyze_and_decide(
        "BTCUSDT",
        naive_market_data,
    )
    assert "phase5_proposal" not in decision.metadata
    assert decision.action.value in {"BUY", "SELL", "HOLD"}


# =========================================================
# PER-AGENT SCORE ISOLATION (one malformed agent must not
# discard valid evidence from other agents)
# =========================================================


def _rejections(proposal) -> list[dict]:
    raw = proposal.market_context.get(
        "phase5_agent_input_rejections"
    )
    if raw is None:
        return []
    return json.loads(raw)


def test_one_malformed_agent_preserves_valid_evidence_and_records_rejection() -> None:
    brain = AtlasBrain()

    agent_results = {
        "technical": {"action": "BUY", "score": 0.8},
        "risk": {"action": "SELL", "score": 1.5},  # malformed: out of range
        "sentiment": {"action": "BUY", "score": 0.9},
    }

    proposal = brain._build_phase5_shadow_proposal(
        "BTCUSDT",
        agent_results,
        MARKET_DATA,
    )

    assert proposal is not None
    assert set(proposal.strategy_sources) == {
        "agent:technical",
        "agent:sentiment",
    }
    assert {"agent": "risk", "reason": "score_out_of_range"} in _rejections(
        proposal
    )


def test_malformed_agent_first_does_not_suppress_later_valid_agents() -> None:
    brain = AtlasBrain()

    agent_results = {
        "risk": {"action": "SELL", "score": 1.5},  # malformed, iterated first
        "technical": {"action": "BUY", "score": 0.8},
        "sentiment": {"action": "BUY", "score": 0.9},
    }

    proposal = brain._build_phase5_shadow_proposal(
        "BTCUSDT",
        agent_results,
        MARKET_DATA,
    )

    assert proposal is not None
    assert set(proposal.strategy_sources) == {
        "agent:technical",
        "agent:sentiment",
    }


def test_malformed_agent_last_does_not_suppress_earlier_valid_agents() -> None:
    brain = AtlasBrain()

    agent_results = {
        "technical": {"action": "BUY", "score": 0.8},
        "sentiment": {"action": "BUY", "score": 0.9},
        "risk": {"action": "SELL", "score": 1.5},  # malformed, iterated last
    }

    proposal = brain._build_phase5_shadow_proposal(
        "BTCUSDT",
        agent_results,
        MARKET_DATA,
    )

    assert proposal is not None
    assert set(proposal.strategy_sources) == {
        "agent:technical",
        "agent:sentiment",
    }


def test_unsupported_action_reason_code() -> None:
    brain = AtlasBrain()
    observed_at = datetime.now(UTC)

    evidence, reason = brain._build_phase5_agent_evidence(
        "macro",
        {"action": "FROBNICATE", "score": 0.5},
        "BTCUSDT",
        observed_at,
    )

    assert evidence is None
    assert reason == "unsupported_action"


def test_non_numeric_score_reason_code() -> None:
    brain = AtlasBrain()
    observed_at = datetime.now(UTC)

    evidence, reason = brain._build_phase5_agent_evidence(
        "macro",
        {"action": "BUY", "score": "high"},
        "BTCUSDT",
        observed_at,
    )

    assert evidence is None
    assert reason == "invalid_score_type"


def test_boolean_score_is_rejected_not_coerced() -> None:
    # bool is a Python int subclass (float(True) == 1.0); it must be
    # explicitly rejected rather than silently masquerading as a
    # calibrated conviction.
    brain = AtlasBrain()
    observed_at = datetime.now(UTC)

    evidence_true, reason_true = brain._build_phase5_agent_evidence(
        "technical",
        {"action": "BUY", "score": True},
        "BTCUSDT",
        observed_at,
    )
    evidence_false, reason_false = brain._build_phase5_agent_evidence(
        "technical",
        {"action": "SELL", "score": False},
        "BTCUSDT",
        observed_at,
    )

    assert evidence_true is None
    assert reason_true == "invalid_score_type"
    assert evidence_false is None
    assert reason_false == "invalid_score_type"


def test_nan_and_inf_scores_are_rejected() -> None:
    brain = AtlasBrain()
    observed_at = datetime.now(UTC)

    for bad_score in (float("nan"), float("inf"), float("-inf")):
        evidence, reason = brain._build_phase5_agent_evidence(
            "technical",
            {"action": "BUY", "score": bad_score},
            "BTCUSDT",
            observed_at,
        )
        assert evidence is None
        assert reason == "score_out_of_range"


def test_out_of_range_scores_are_rejected() -> None:
    brain = AtlasBrain()
    observed_at = datetime.now(UTC)

    for bad_score in (-0.1, 1.5):
        evidence, reason = brain._build_phase5_agent_evidence(
            "technical",
            {"action": "BUY", "score": bad_score},
            "BTCUSDT",
            observed_at,
        )
        assert evidence is None
        assert reason == "score_out_of_range"


def test_numeric_string_score_remains_accepted() -> None:
    # Characterizes existing intended compatibility: numeric strings
    # were already silently coerced via float() before this remediation
    # and remain accepted - this behavior is preserved, not broadened.
    brain = AtlasBrain()
    observed_at = datetime.now(UTC)

    evidence, reason = brain._build_phase5_agent_evidence(
        "technical",
        {"action": "BUY", "score": "0.8"},
        "BTCUSDT",
        observed_at,
    )

    assert reason is None
    assert evidence is not None
    assert evidence.score == Decimal("0.8")


def test_all_agents_malformed_returns_none_and_baseline_unaffected() -> None:
    baseline_brain = AtlasBrain()
    baseline_brain._build_phase5_shadow_proposal = (  # type: ignore[method-assign]
        lambda *args, **kwargs: None
    )
    baseline_decision = baseline_brain.analyze_and_decide(
        "BTCUSDT",
        MARKET_DATA,
    )

    brain = AtlasBrain()
    agent_results = {
        "technical": {"action": "FROBNICATE", "score": 0.8},
        "risk": {"action": "BUY", "score": 5.0},
        "macro": {"action": "SELL", "score": "bad"},
    }

    proposal = brain._build_phase5_shadow_proposal(
        "BTCUSDT",
        agent_results,
        MARKET_DATA,
    )
    assert proposal is None

    decision = brain.analyze_and_decide(
        "BTCUSDT",
        MARKET_DATA,
    )

    assert _execution_relevant_fields(
        decision
    ) == _execution_relevant_fields(
        baseline_decision
    )


def test_partial_valid_evidence_does_not_alter_execution_relevant_fields() -> None:
    baseline_brain = AtlasBrain()
    baseline_decision = baseline_brain.analyze_and_decide(
        "BTCUSDT",
        MARKET_DATA,
    )

    mixed_brain = AtlasBrain()
    original_builder = mixed_brain._build_phase5_shadow_proposal

    def _inject_malformed_agent(symbol, agent_results, market_data, **kwargs):
        overridden = dict(agent_results)
        overridden["risk"] = {"action": "SELL", "score": 1.5}
        return original_builder(
            symbol,
            overridden,
            market_data,
            **kwargs,
        )

    mixed_brain._build_phase5_shadow_proposal = (  # type: ignore[method-assign]
        _inject_malformed_agent
    )

    mixed_decision = mixed_brain.analyze_and_decide(
        "BTCUSDT",
        MARKET_DATA,
    )

    assert "phase5_proposal" in mixed_decision.metadata

    rejections = json.loads(
        mixed_decision.metadata["phase5_proposal"]["market_context"][
            "phase5_agent_input_rejections"
        ]
    )
    assert {"agent": "risk", "reason": "score_out_of_range"} in rejections

    # The real production agent_results (from the unmodified
    # agents.evaluate()/agents.fuse() path) are untouched by the
    # injected Phase-5-only malformed override, so execution-relevant
    # output must match the clean baseline exactly.
    assert _execution_relevant_fields(
        mixed_decision
    ) == _execution_relevant_fields(
        baseline_decision
    )


# =========================================================
# TEST FILESYSTEM ISOLATION (AtlasBrain() bootstraps
# production persistence components with a CWD-relative
# default "memory_data" directory)
# =========================================================


def test_atlas_brain_construction_is_isolated_to_temp_cwd(tmp_path) -> None:
    # Proves positively that the autouse _isolated_cwd fixture redirected
    # this test's working directory into pytest's tmp_path, and that a
    # real, unmodified AtlasBrain() construction - with production
    # persistence bootstrapping left entirely intact - creates its
    # "memory_data" directory only beneath that isolated tmp_path, never
    # touching the repository's pre-existing memory_data/. Safe on a
    # fresh clone or clean CI worker since tmp_path is always empty.
    assert os.getcwd() == str(tmp_path)

    AtlasBrain()

    created_memory_dir = tmp_path / "memory_data"
    assert created_memory_dir.exists()
    assert created_memory_dir.is_dir()


# -- P4-CLOSURE-004 F-1: expected roster (NB-5) and no gain from removal (NB-4) --


def _shadow(agent_results):
    brain = AtlasBrain()
    fixed_now = datetime(2026, 1, 1, 12, 5, 0, tzinfo=UTC)
    market_data = {**MARKET_DATA, "timestamp": "2026-01-01T12:04:30+00:00"}
    return brain._build_phase5_shadow_proposal("BTCUSDT", agent_results, market_data, now=fixed_now)


AUDIT_FULL = {"technical": {"action": "BUY", "score": 0.9}, "momentum": {"action": "SELL", "score": 0.1},
              "risk": {"action": "HOLD", "score": 0.5}, "macro": {"action": "HOLD", "score": 0.5},
              "sentiment": {"action": "HOLD", "score": 0.5}}


def test_f1_auditor_scenario_full_roster_with_dissent_abstains():
    proposal = _shadow(AUDIT_FULL)
    assert proposal.action is Action.ABSTAIN and proposal.confidence == Decimal("0")


def test_f1_removing_the_counter_evidence_does_not_promote_or_raise():
    """Auditor: dropping the SELL used to turn ABSTAIN/0 into BUY/0.225."""
    full = _shadow(AUDIT_FULL)
    without_sell = _shadow({k: v for k, v in AUDIT_FULL.items() if k != "momentum"})
    assert without_sell.action is Action.ABSTAIN
    assert without_sell.confidence <= full.confidence
    assert "EXPECTED_SOURCES_MISSING" in without_sell.reason_codes
    assert json.loads(without_sell.market_context["missing_expected_sources"]) == ["agent:momentum"]


def test_f1_one_surviving_agent_cannot_speak_for_the_roster():
    """Auditor: one of five BUY 0.9 used to give BUY/0.9."""
    proposal = _shadow({"technical": {"action": "BUY", "score": 0.9}})
    assert proposal.action is Action.ABSTAIN and proposal.confidence == Decimal("0")
    assert proposal.market_context["expected_source_coverage"] == "0.200000"


def test_f1_full_unanimous_roster_is_unchanged():
    proposal = _shadow({name: {"action": "BUY", "score": 0.8} for name in AgentFusion.WEIGHTS})
    assert proposal.action is Action.BUY and proposal.confidence == Decimal("0.800000")
    assert "missing_expected_sources" not in proposal.market_context


def test_f1_an_unexpected_agent_is_not_counted_as_support():
    roster = {name: {"action": "HOLD", "score": 0.5} for name in AgentFusion.WEIGHTS}
    with_stranger = _shadow({**roster, "unlisted_agent": {"action": "BUY", "score": 1.0}})
    assert with_stranger.action is Action.ABSTAIN and with_stranger.confidence == Decimal("0")
