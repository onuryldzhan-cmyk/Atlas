"""Task 011: Strategic Scout, 7-step acceptance gate, trader reputation, memory firewall.

Owner decisions 2026-10-11 (registry v5.95): research/scout/ only; offline (no
network, subprocess or code execution); never auto-accept (7/7 means
PENDING_OWNER_REVIEW); gate step 6 passes only on a sealed Atlas hypothesis
that passed Task 006 adjudication, never on an external benchmark claim.
"""

from __future__ import annotations

import ast
import dataclasses
import os
import hashlib
import json
import logging
import random
import subprocess
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from research.hypothesis_registry import (
    CheckName,
    CheckPlan,
    CheckPlanStatus,
    CheckResult,
    CheckVerdict,
    EvaluationRecord,
    HypothesisRecord,
    HypothesisRegistry,
    PreRegistration,
    RegistryError,
    SealVerificationError,
)
from research.lifecycle import HypothesisState
from research.scout import (
    EXPLORATORY,
    GATE_STEPS,
    MODE_SPECS,
    REQUIRED_DIMENSION_COUNT,
    REQUIRED_STEP_COUNT,
    ClaimType,
    GateStatus,
    GateStep,
    ReputationPolicy,
    ReputationRating,
    GatePolicy,
    ScoutCandidate,
    ScoutFinding,
    ScoutInputError,
    ScoutLedger,
    ScoutLedgerError,
    ScoutMode,
    ScoutRequest,
    StrategicScout,
    TraderClaim,
    assess_claim,
    evaluate_candidate,
)
from research.scout.strategic_scout import _report_problem
from research.scout.trader_reputation import NEXT_STEP, RATING_RANK
from research.splitting import SplitSpec

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
SCOUT_ROOT = REPOSITORY_ROOT / "research" / "scout"
AS_OF = datetime(2026, 10, 11, 12, 0, tzinfo=UTC)
PROBLEMS = ("ATLAS-PROBLEM-001",)

# -- fixtures ------------------------------------------------------------------

#: The registry stamps its own transitions with the wall clock; frozen here so every hypothesis is
#: adjudicated before AS_OF on any day the suite runs (otherwise step 6 rightly refuses it as
#: evidence from after as_of, and the module would only pass before AS_OF on 2026-10-11).
REGISTRY_CLOCK = datetime(2026, 9, 15, 0, 0, tzinfo=UTC)


@pytest.fixture(autouse=True)
def frozen_registry_clock(monkeypatch):
    import research.hypothesis_registry as hypothesis_registry_module

    class FrozenDateTime(datetime):
        @classmethod
        def now(cls, tz=None):
            return REGISTRY_CLOCK if tz is not None else REGISTRY_CLOCK.replace(tzinfo=None)

    monkeypatch.setattr(hypothesis_registry_module, "datetime", FrozenDateTime)


def _source(**overrides):
    source = {
        "url": "https://github.com/example/tool",
        "source_type": "REPOSITORY",
        "retrieved_at": "2026-10-10T09:00:00+00:00",
        "retrieved_by": "owner",
    }
    source.update(overrides)
    return source


def good_candidate(**overrides):
    candidate = {
        "candidate_id": "cand-good",
        "kind": "LIBRARY",
        "name": "Example tool",
        "source": _source(),
        "problem_ref": "ATLAS-PROBLEM-001",
        "license_spdx": "MIT",
        "last_activity_at": "2026-09-01T00:00:00+00:00",
        "maintainer_count": 3,
        "security": {
            "network_access": False,
            "subprocess_execution": False,
            "dynamic_code_execution": False,
            "install_time_hooks": False,
            "known_vulnerabilities": 0,
        },
        "overlapping_components": [],
        "new_dependency_count": 1,
        "sealed_hypothesis_id": "HYP-0001",
        "removal_plan": "Delete the module and its single import; no state is written.",
        "requires_state_migration": False,
        "monthly_cost_usd": 0.0,
    }
    candidate.update(overrides)
    return candidate


BOUND = {"scout_candidate_id": "cand-good", "scout_source_url": "https://github.com/example/tool"}


def _preregistration(hypothesis_id, family_id, binding=BOUND):
    return PreRegistration(
        hypothesis_id=hypothesis_id,
        title="Overnight reversal in majors",
        description="Large negative overnight moves partially revert.",
        economic_rationale="Forced liquidation into thin books overshoots fair value.",
        author="research",
        universe=("BTCUSDT",),
        timeframe="1h",
        data_start="2024-01-01T00:00:00+00:00",
        data_end="2025-01-01T00:00:00+00:00",
        entry_rule="long when overnight return < -2 sigma",
        exit_rule="exit at next session close",
        test_statistic="mean_excess_return",
        direction="greater",
        null_hypothesis="mean excess return is zero",
        alpha=0.05,
        minimum_effect_size=0.5,
        family_id=family_id,
        split_spec=SplitSpec(train_fraction=0.6, calibration_fraction=0.2, test_fraction=0.2,
                             label_horizon_bars=10, embargo_pct=0.01),
        check_plan=CheckPlan(required_checks=(CheckName.OUT_OF_SAMPLE,)),
        feature_spec={"lookback": 24, **binding},
        preregistered_at="2026-08-01T00:00:00+00:00",
    )


def _register_and_test(registry, hypothesis_id, family_id, *, p_value, effect_size, binding=BOUND):
    registry.register(_preregistration(hypothesis_id, family_id, binding))
    registry.advance(hypothesis_id, HypothesisState.CALIBRATED)
    registry.record_evaluation(hypothesis_id, EvaluationRecord(
        segment="TEST", statistic_value=effect_size, p_value=p_value, effect_size=effect_size,
        checks=(CheckResult(check_name=CheckName.OUT_OF_SAMPLE, verdict=CheckVerdict.PASS,
                            statistic_value=effect_size, p_value=p_value, effect_size=effect_size),),
    ))


@pytest.fixture
def registry_path(tmp_path):
    """A registry built through the Task 005/006 API (test setup only; the scout only reads)."""
    path = tmp_path / "research" / "hypotheses.json"
    registry = HypothesisRegistry(registry_path=path)
    _register_and_test(registry, "HYP-0001", "FAM-SCOUT-PASS", p_value=0.001, effect_size=0.9)
    registry.adjudicate_family("FAM-SCOUT-PASS", q=0.1)
    _register_and_test(registry, "HYP-0002", "FAM-SCOUT-FAIL", p_value=0.9, effect_size=0.9)
    registry.adjudicate_family("FAM-SCOUT-FAIL", q=0.1)
    registry.register(_preregistration("HYP-0003", "FAM-SCOUT-OPEN"))
    # Adjudicated and passing, but sealed for a different candidate.
    _register_and_test(registry, "HYP-0004", "FAM-SCOUT-OTHER", p_value=0.001, effect_size=0.9,
                       binding={"scout_candidate_id": "cand-other", "scout_source_url": "https://example.org/other"})
    registry.adjudicate_family("FAM-SCOUT-OTHER", q=0.1)
    return path


@pytest.fixture
def registry(registry_path):
    registry = HypothesisRegistry(registry_path=registry_path)
    assert registry.get("HYP-0001").state is HypothesisState.CANDIDATE
    assert registry.get("HYP-0002").state is HypothesisState.REJECTED
    assert registry.get("HYP-0003").state is HypothesisState.REGISTERED
    assert registry.get("HYP-0004").state is HypothesisState.CANDIDATE
    return registry


def _gate(payload, registry=None, problems=PROBLEMS, **kwargs):
    return evaluate_candidate(ScoutCandidate.from_dict(payload), as_of=AS_OF,
                              verified_problems=problems, registry=registry, **kwargs)


def _failed(verdict):
    return {result.step: result.reasons for result in verdict.failed_steps}


# -- 0/7 acceptance gate -------------------------------------------------------


def test_a_fully_compliant_candidate_reaches_owner_review_never_acceptance(registry):
    verdict = _gate(good_candidate(), registry)
    assert verdict.status is GateStatus.PENDING_OWNER_REVIEW
    assert (verdict.passed_step_count, verdict.required_step_count) == (7, 7)
    assert verdict.as_dict()["score"] == "7/7"
    assert "ACCEPTED" not in {status.value for status in GateStatus}


def test_a_non_compliant_candidate_is_rejected_with_exact_failed_criteria_logged(registry, caplog):
    payload = good_candidate(
        license_spdx="GPL-3.0-only",
        security=dict(good_candidate()["security"], network_access=True, known_vulnerabilities=2),
        removal_plan=None,
    )
    with caplog.at_level(logging.WARNING, logger="research.scout.acceptance_gate"):
        verdict = _gate(payload, registry)
    assert verdict.status is GateStatus.REJECTED
    assert _failed(verdict) == {
        GateStep.LICENSE_COMPLIANCE: ("LICENSE_NOT_ALLOWED:GPL-3.0-only",),
        GateStep.SECURITY_RISK: ("NETWORK_ACCESS", "KNOWN_VULNERABILITIES:2"),
        GateStep.REVERSIBILITY: ("REMOVAL_PLAN_MISSING",),
    }
    assert verdict.passed_step_count == 4
    [record] = caplog.records
    message = record.getMessage()
    assert "REJECTED cand-good (4/7)" in message
    for fragment in ("LICENSE_COMPLIANCE=LICENSE_NOT_ALLOWED:GPL-3.0-only",
                     "SECURITY_RISK=NETWORK_ACCESS,KNOWN_VULNERABILITIES:2",
                     "REVERSIBILITY=REMOVAL_PLAN_MISSING"):
        assert fragment in message


def test_an_empty_candidate_fails_every_step_and_all_seven_are_reported():
    minimal = {"candidate_id": "bare", "kind": "REPOSITORY", "name": "bare", "source": _source()}
    verdict = _gate(minimal, problems=())
    assert [r.step for r in verdict.steps] == list(GATE_STEPS)
    assert verdict.passed_step_count == 0 and verdict.required_step_count == REQUIRED_STEP_COUNT == 7
    assert verdict.status is GateStatus.REJECTED
    assert all(r.reasons for r in verdict.steps)


@pytest.mark.parametrize("field", [
    "problem_ref", "license_spdx", "last_activity_at", "maintainer_count", "overlapping_components",
    "new_dependency_count", "sealed_hypothesis_id", "removal_plan", "requires_state_migration",
])
def test_nb4_removing_evidence_never_makes_the_gate_more_permissive(registry, field):
    full = _gate(good_candidate(), registry)
    removed = _gate(good_candidate(**{field: None}), registry)
    assert removed.status is GateStatus.REJECTED
    assert removed.passed_step_count < full.passed_step_count


@pytest.mark.parametrize("flag", [
    "network_access", "subprocess_execution", "dynamic_code_execution", "install_time_hooks",
    "known_vulnerabilities",
])
@pytest.mark.parametrize("value", [None, True])
def test_security_fails_on_any_hazard_or_any_unassessed_field(registry, flag, value):
    security = dict(good_candidate()["security"])
    security[flag] = (5 if value else None) if flag == "known_vulnerabilities" else value
    verdict = _gate(good_candidate(security=security), registry)
    assert GateStep.SECURITY_RISK in _failed(verdict)
    assert verdict.status is GateStatus.REJECTED


def test_nb5_the_denominator_never_shrinks_to_the_steps_with_data(registry):
    for payload in (good_candidate(), good_candidate(license_spdx=None, security=None)):
        assert _gate(payload, registry).required_step_count == 7


@pytest.mark.parametrize("overrides, step, reason", [
    ({"problem_ref": "UNLISTED"}, GateStep.REAL_PROBLEM_ALIGNMENT, "PROBLEM_NOT_VERIFIED:UNLISTED"),
    ({"source": _source(source_type="SOCIAL")}, GateStep.SOURCE_RELIABILITY, "SOCIAL_SOURCE"),
    ({"last_activity_at": "2024-01-01T00:00:00+00:00"}, GateStep.SOURCE_RELIABILITY, "INACTIVE_MORE_THAN_365_DAYS"),
    ({"last_activity_at": "2027-01-01T00:00:00+00:00"}, GateStep.SOURCE_RELIABILITY, "LAST_ACTIVITY_IN_THE_FUTURE"),
    ({"source": _source(retrieved_at="2027-01-01T00:00:00+00:00")}, GateStep.SOURCE_RELIABILITY,
     "SOURCE_RETRIEVED_AFTER_AS_OF"),
    ({"maintainer_count": 0}, GateStep.SOURCE_RELIABILITY, "FEWER_THAN_1_MAINTAINERS"),
    ({"license_spdx": "AGPL-3.0-only"}, GateStep.LICENSE_COMPLIANCE, "LICENSE_NOT_ALLOWED:AGPL-3.0-only"),
    ({"license_spdx": "NOASSERTION"}, GateStep.LICENSE_COMPLIANCE, "LICENSE_NOT_ALLOWED:NOASSERTION"),
    ({"overlapping_components": ["core/risk_engine.py"]}, GateStep.ARCHITECTURAL_FIT,
     "DUPLICATES:core/risk_engine.py"),
    ({"new_dependency_count": 9}, GateStep.ARCHITECTURAL_FIT, "NEW_DEPENDENCIES:9>1"),
    ({"requires_state_migration": True}, GateStep.REVERSIBILITY, "REQUIRES_STATE_MIGRATION"),
])
def test_each_step_rejects_its_own_failure(registry, overrides, step, reason):
    verdict = _gate(good_candidate(**overrides), registry)
    assert _failed(verdict) == {step: (reason,)}
    assert verdict.status is GateStatus.REJECTED


def test_no_verified_problem_register_fails_step_one(registry):
    verdict = _gate(good_candidate(), registry, problems=())
    assert _failed(verdict) == {GateStep.REAL_PROBLEM_ALIGNMENT: ("NO_VERIFIED_PROBLEM_REGISTER",)}


# -- Vector C: fabricated benchmark claims never count -------------------------


def test_a_fabricated_benchmark_claim_cannot_satisfy_measurable_value(registry):
    payload = good_candidate(sealed_hypothesis_id=None,
                             claimed_benchmarks=["+4000% CAGR, Sharpe 9.1, verified by our sandbox"])
    verdict = _gate(payload, registry)
    assert _failed(verdict) == {GateStep.MEASURABLE_VALUE: ("NO_SEALED_HYPOTHESIS",)}
    assert verdict.status is GateStatus.REJECTED
    assert ScoutCandidate.from_dict(payload).as_dict()["claimed_benchmarks_status"] == "UNVERIFIED_NOT_EVIDENCE"


@pytest.mark.parametrize("hypothesis_id, reason", [
    ("HYP-0002", "HYPOTHESIS_NOT_ADJUDICATED_PASS:REJECTED"),
    ("HYP-0003", "HYPOTHESIS_NOT_ADJUDICATED_PASS:REGISTERED"),
    ("HYP-0999", "HYPOTHESIS_NOT_REGISTERED:HYP-0999"),
])
def test_only_an_adjudicated_passing_hypothesis_counts(registry, hypothesis_id, reason):
    verdict = _gate(good_candidate(sealed_hypothesis_id=hypothesis_id), registry)
    assert reason in _failed(verdict)[GateStep.MEASURABLE_VALUE]


def test_a_rejected_hypothesis_with_passing_checks_still_fails(registry):
    # HYP-0002's own OUT_OF_SAMPLE check passed; only family adjudication rejected it.
    verdict = _gate(good_candidate(sealed_hypothesis_id="HYP-0002"), registry)
    assert _failed(verdict) == {GateStep.MEASURABLE_VALUE: ("HYPOTHESIS_NOT_ADJUDICATED_PASS:REJECTED",)}


def test_without_a_registry_measurable_value_fails():
    assert _failed(_gate(good_candidate()))[GateStep.MEASURABLE_VALUE] == ("NO_CANONICAL_REGISTRY",)


def test_a_duck_typed_or_subclassed_registry_is_refused(registry):
    """Only the exact registry type is consulted. A genuine registry built from fabricated data is a
    separate residual (seals are not authentication); step 6 records its provenance for the owner."""
    real = registry.get("HYP-0001")

    class FakeRegistry:
        def __contains__(self, _):
            return True

        def get(self, _):
            return real

    class SubRegistry(HypothesisRegistry):
        pass

    sub = SubRegistry(registry_path=registry.registry_path)
    for fake in (FakeRegistry(), sub):
        assert _failed(_gate(good_candidate(), fake)) == {GateStep.MEASURABLE_VALUE: ("NO_CANONICAL_REGISTRY",)}


def test_a_record_failing_re_verification_is_refused(registry, monkeypatch):
    # The gate re-reads the registry file fresh; that load re-verifies every record's seal, state
    # chain and recorded checks, so one failing record refuses the whole file (stricter than
    # refusing the record alone).
    def broken(self):
        raise SealVerificationError("tampered")
    monkeypatch.setattr(HypothesisRecord, "verify_seal", broken)
    verdict = _gate(good_candidate(), registry)
    assert _failed(verdict) == {
        GateStep.MEASURABLE_VALUE: ("REGISTRY_FILE_INVALID:SealVerificationError",),
    }


def test_a_hypothesis_whose_checks_do_not_all_pass_is_refused(registry, monkeypatch):
    # The registry itself refuses to promote such a hypothesis; the gate re-checks independently.
    real = HypothesisRecord.adjudicate_checks

    def incomplete(self):
        return dataclasses.replace(real(self), status=CheckPlanStatus.INCOMPLETE)
    monkeypatch.setattr(HypothesisRecord, "adjudicate_checks", incomplete)
    verdict = _gate(good_candidate(), registry)
    assert _failed(verdict) == {GateStep.MEASURABLE_VALUE: ("HYPOTHESIS_CHECKS_NOT_COMPLETE_PASS",)}


def test_a_tampered_registry_file_cannot_even_be_opened(registry_path):
    payload = json.loads(registry_path.read_text(encoding="utf-8"))
    payload["records"][0]["preregistration"]["direction"] = "less"
    registry_path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(RegistryError):
        HypothesisRegistry(registry_path=registry_path)


# -- trader reputation ---------------------------------------------------------


LOG_DIGEST = hashlib.sha256(b"trader-a venue statement 2025-01..2026-06").hexdigest()


def good_claim(**overrides):
    claim = {
        "claim_id": "claim-1",
        "trader_id": "trader-a",
        "claim_type": "LIVE_TRACK_RECORD",
        "source": _source(url="https://example.org/track-record", source_type="ARTICLE"),
        "period_start": "2025-01-01T00:00:00+00:00",
        "period_end": "2026-06-01T00:00:00+00:00",
        "trade_count": 240,
        "fees_and_slippage_included": True,
        "regimes_covered": ["TRENDING_UP", "RANGING", "TRENDING_DOWN"],
        "execution_log": {
            "sha256": LOG_DIGEST,
            "record_count": 240,
            "venue": "binance",
            "verified_by": "owner",
            "verification_method": "VENUE_STATEMENT",
        },
        "claimed_return_pct": "+38%",
    }
    claim.update(overrides)
    return claim


TRUSTING = ReputationPolicy(trusted_verifiers=frozenset({"owner"}))


def _assess(payload, policy=TRUSTING):
    return assess_claim(TraderClaim.from_dict(payload), as_of=AS_OF, policy=policy)


def test_unverified_backtest_claims_are_insufficient_evidence():
    assessment = _assess(good_claim(claim_type="BACKTEST", execution_log=None, claimed_return_pct="+900%"))
    assert assessment.rating is ReputationRating.INSUFFICIENT_EVIDENCE
    assert "CLAIM_TYPE_NOT_VERIFIABLE:BACKTEST" in assessment.reasons
    assert "NO_EXECUTION_LOG" in assessment.reasons


@pytest.mark.parametrize("claim_type", ["BACKTEST", "COMMENTARY", "SOCIAL_SIGNAL"])
def test_non_track_record_claims_never_rise_above_insufficient_evidence(claim_type):
    # Even with a complete, matching log attached.
    assert _assess(good_claim(claim_type=claim_type)).rating is ReputationRating.INSUFFICIENT_EVIDENCE


def test_a_complete_verifiable_track_record_is_only_a_research_candidate():
    assessment = _assess(good_claim())
    assert assessment.rating is ReputationRating.RESEARCH_CANDIDATE
    assert (assessment.passed_dimension_count, assessment.required_dimension_count) == (4, REQUIRED_DIMENSION_COUNT)
    data = assessment.as_dict()
    assert data["signal_authority"] == "NONE" and data["epistemic_status"] == EXPLORATORY
    assert data["next_step"] == NEXT_STEP == "REQUIRES_TASK005_PREREGISTRATION_AND_TASK006_ADJUDICATION"
    assert {r.value for r in ReputationRating} == {"INSUFFICIENT_EVIDENCE", "UNRELIABLE", "RESEARCH_CANDIDATE"}


@pytest.mark.parametrize("overrides, rating, reason", [
    ({"execution_log": None}, ReputationRating.INSUFFICIENT_EVIDENCE, "NO_EXECUTION_LOG"),
    ({"execution_log": dict(good_claim()["execution_log"], record_count=12)},
     ReputationRating.INSUFFICIENT_EVIDENCE, "LOG_RECORD_COUNT_MISMATCH"),
    ({"trade_count": 40, "execution_log": dict(good_claim()["execution_log"], record_count=40)},
     ReputationRating.INSUFFICIENT_EVIDENCE, "FEWER_THAN_100_TRADES"),
    ({"period_end": "2027-01-01T00:00:00+00:00"}, ReputationRating.INSUFFICIENT_EVIDENCE, "CLAIM_DATED_AFTER_AS_OF"),
    ({"fees_and_slippage_included": None}, ReputationRating.INSUFFICIENT_EVIDENCE, "FEES_NOT_STATED"),
    ({"fees_and_slippage_included": False}, ReputationRating.UNRELIABLE, "FEES_AND_SLIPPAGE_EXCLUDED"),
    ({"regimes_covered": ["BULL", "bull"]}, ReputationRating.UNRELIABLE, "FEWER_THAN_2_REGIMES"),
])
def test_reputation_dimensions(overrides, rating, reason):
    assessment = _assess(good_claim(**overrides))
    assert assessment.rating is rating
    assert reason in assessment.reasons


@pytest.mark.parametrize("field", [
    "trade_count", "fees_and_slippage_included", "regimes_covered", "execution_log",
])
def test_nb4_removing_claim_evidence_never_raises_the_rating(field):
    full = _assess(good_claim())
    removed = _assess(good_claim(**{field: None}))
    assert RATING_RANK[removed.rating] <= RATING_RANK[full.rating]
    assert removed.rating is ReputationRating.INSUFFICIENT_EVIDENCE


@pytest.mark.parametrize("overrides", [
    {"execution_log": dict(good_claim()["execution_log"], sha256="not-a-hash")},
    {"execution_log": dict(good_claim()["execution_log"], sha256=LOG_DIGEST + "0")},
    {"execution_log": dict(good_claim()["execution_log"], sha256=LOG_DIGEST + "\n")},
    {"fees_and_slippage_included": "true"},
    {"trade_count": True},
    {"period_end": "2024-01-01T00:00:00+00:00"},
    {"period_start": "2025-01-01T00:00:00"},
    {"claim_type": "TRUST_ME"},
    {"claimed_return_pct": 300},
    {"unexpected": "field"},
])
def test_malformed_claims_are_refused_not_coerced(overrides):
    with pytest.raises(ScoutInputError):
        TraderClaim.from_dict(good_claim(**overrides))


# -- 6-mode routing ------------------------------------------------------------

MODE_CONTEXT = {
    ScoutMode.SEARCH: {},
    ScoutMode.HUNT: {},
    ScoutMode.COMPETITOR: {"atlas_component": "core/risk_engine.py"},
    ScoutMode.COST: {"current_monthly_cost_usd": 49.0},
    ScoutMode.RED_TEAM: {},
    ScoutMode.EMERGENCY: {"incident_ref": "INC-2026-10-11-feed-stall"},
}
MODE_ANALYSIS_KEYS = {
    ScoutMode.SEARCH: set(),
    ScoutMode.HUNT: {"by_source_type"},
    ScoutMode.COMPETITOR: {"atlas_component", "comparison"},
    ScoutMode.COST: {"current_monthly_cost_usd", "cost_comparison"},
    ScoutMode.RED_TEAM: {"failure_modes"},
    ScoutMode.EMERGENCY: {"incident_ref", "remediation_authority", "fast_path", "note"},
}
REPORT_KEYS = {
    "schema_version", "mode", "query", "as_of", "purpose", "research_questions", "context", "findings",
    "trader_assessments", "trader_claim_errors", "mode_analysis", "epistemic_status", "evidence_eligible",
    "authority", "production_effect", "live_effect", "registry_writes", "report_id",
}


def _candidates():
    return [
        good_candidate(),
        good_candidate(candidate_id="cand-gpl", license_spdx="GPL-3.0-only", monthly_cost_usd=None),
        good_candidate(candidate_id="cand-social", source=_source(source_type="SOCIAL"), monthly_cost_usd=99.0),
    ]


def _request(mode, **overrides):
    params = dict(mode=mode, query="order-book imbalance features", as_of=AS_OF, candidates=_candidates(),
                  trader_claims=[good_claim(), good_claim(claim_id="claim-2", claim_type="BACKTEST")],
                  context=MODE_CONTEXT[mode])
    params.update(overrides)
    return ScoutRequest(**params)


def _scout(registry=None):
    return StrategicScout(verified_problems=PROBLEMS, registry=registry, reputation_policy=TRUSTING)


@pytest.mark.parametrize("mode", list(ScoutMode))
def test_every_mode_returns_a_deterministic_structure(registry, mode):
    first = _scout(registry).run(_request(mode)).to_dict()
    again = _scout(registry).run(_request(mode)).to_dict()
    assert first == again and first["report_id"] == again["report_id"]
    assert set(first) == REPORT_KEYS
    assert first["mode"] == mode.value
    assert first["research_questions"] == list(MODE_SPECS[mode].research_questions)
    assert set(first["mode_analysis"]) == {"ranking", "pending_owner_review"} | MODE_ANALYSIS_KEYS[mode]
    assert [f["candidate_id"] for f in first["findings"]] == ["cand-good", "cand-gpl", "cand-social"]
    assert {f["candidate_id"]: f["status"] for f in first["findings"]}["cand-gpl"] == "REJECTED"
    assert {a["claim_id"]: a["rating"] for a in first["trader_assessments"]} == {
        "claim-1": "RESEARCH_CANDIDATE", "claim-2": "INSUFFICIENT_EVIDENCE"}
    shuffled = _candidates()
    random.Random(7).shuffle(shuffled)
    assert _scout(registry).run(_request(mode, candidates=shuffled)).report_id == first["report_id"]


def test_modes_differ_only_where_their_spec_says(registry):
    statuses = {
        mode: {f["candidate_id"]: f["status"] for f in _scout(registry).run(_request(mode)).to_dict()["findings"]}
        for mode in ScoutMode
    }
    assert statuses[ScoutMode.SEARCH] == {"cand-good": "PENDING_OWNER_REVIEW", "cand-gpl": "REJECTED",
                                          "cand-social": "REJECTED"}
    assert statuses[ScoutMode.EMERGENCY] == statuses[ScoutMode.SEARCH]  # no fast path
    assert statuses[ScoutMode.COMPETITOR] == statuses[ScoutMode.SEARCH]
    assert statuses[ScoutMode.HUNT] == statuses[ScoutMode.SEARCH]
    assert statuses[ScoutMode.COST]["cand-good"] == "PENDING_OWNER_REVIEW"
    # The compliant candidate (3 maintainers, every field assessed) gives the red team nothing to block.
    assert statuses[ScoutMode.RED_TEAM]["cand-good"] == "PENDING_OWNER_REVIEW"


def test_hunt_flags_sources_outside_primary_material(registry):
    report = _scout(registry).run(_request(ScoutMode.HUNT, candidates=[
        good_candidate(source=_source(source_type="ARTICLE"))])).to_dict()
    [finding] = report["findings"]
    assert finding["mode_flags"] == ["SOURCE_TYPE_OUT_OF_MODE:ARTICLE"]
    assert finding["gate"]["status"] == "PENDING_OWNER_REVIEW" and finding["status"] == "REJECTED"


def test_competitor_records_overlap_with_the_named_component(registry):
    report = _scout(registry).run(_request(ScoutMode.COMPETITOR, candidates=[
        good_candidate(overlapping_components=["core/risk_engine.py"])])).to_dict()
    [row] = report["mode_analysis"]["comparison"]
    assert row["overlaps_atlas_component"] is True and row["failed_steps"] == ["ARCHITECTURAL_FIT"]


def test_cost_flags_unknown_costs_and_computes_deltas(registry):
    report = _scout(registry).run(_request(ScoutMode.COST)).to_dict()
    rows = {r["candidate_id"]: r for r in report["mode_analysis"]["cost_comparison"]}
    assert rows["cand-good"] == {"candidate_id": "cand-good", "monthly_cost_usd": 0.0, "delta_usd": -49.0,
                                 "cheaper": True}
    assert rows["cand-gpl"]["cheaper"] is None
    flags = {f["candidate_id"]: f["mode_flags"] for f in report["findings"]}
    assert flags["cand-gpl"] == ["COST_UNKNOWN"]


def test_red_team_findings_are_blocking(registry):
    risky = good_candidate(candidate_id="cand-solo", maintainer_count=1, kind="PROMPT_SKILL",
                           claimed_benchmarks=["beats everything"], sealed_hypothesis_id=None)
    report = _scout(registry).run(_request(ScoutMode.RED_TEAM, candidates=[risky])).to_dict()
    [finding] = report["findings"]
    assert finding["status"] == "REJECTED"
    assert report["mode_analysis"]["failure_modes"]["cand-solo"] == [
        "UNVERIFIED_BENCHMARK_CLAIMS", "SINGLE_POINT_OF_MAINTENANCE", "PROMPT_INJECTION_SURFACE"]


def test_emergency_has_no_fast_path_and_no_remediation_authority(registry):
    analysis = _scout(registry).run(_request(ScoutMode.EMERGENCY)).to_dict()["mode_analysis"]
    assert analysis["remediation_authority"] == "NONE" and analysis["fast_path"] is False
    assert analysis["incident_ref"] == "INC-2026-10-11-feed-stall"


@pytest.mark.parametrize("mode", list(ScoutMode))
def test_no_mode_can_lift_a_gate_rejection(registry, mode):
    report = _scout(registry).run(_request(mode, candidates=[good_candidate(license_spdx=None)])).to_dict()
    assert report["findings"][0]["status"] == "REJECTED"


@pytest.mark.parametrize("kwargs", [
    {"mode": "SHOP"},
    {"query": "  "},
    {"as_of": datetime(2026, 10, 11)},
    {"candidates": "not-a-list"},
    {"context": {"surprise": "x"}},
])
def test_malformed_requests_are_refused(kwargs):
    params = dict(mode=ScoutMode.SEARCH, query="q", as_of=AS_OF, candidates=[], context={})
    params.update(kwargs)
    with pytest.raises(ScoutInputError):
        ScoutRequest(**params)


@pytest.mark.parametrize("mode, context", [
    (ScoutMode.COMPETITOR, {}),
    (ScoutMode.COST, {"current_monthly_cost_usd": -1}),
    (ScoutMode.COST, {"current_monthly_cost_usd": "49"}),
    (ScoutMode.EMERGENCY, {"incident_ref": ""}),
])
def test_modes_require_their_context(mode, context):
    with pytest.raises(ScoutInputError):
        ScoutRequest(mode=mode, query="q", as_of=AS_OF, context=context)


def test_malformed_and_duplicate_candidates_are_rejected_without_hiding_others(registry):
    request = _request(ScoutMode.SEARCH, candidates=[
        good_candidate(),
        good_candidate(candidate_id="dup"),
        good_candidate(candidate_id="dup", license_spdx="MIT"),
        {"candidate_id": "bad", "kind": "LIBRARY", "name": "x", "source": _source(), "maintainer_count": "3"},
        "not even a mapping",
    ], trader_claims=[good_claim(), {"claim_id": "broken"}])
    report = _scout(registry).run(request).to_dict()
    statuses = {f["candidate_id"]: (f["status"], f["input_errors"]) for f in report["findings"]}
    assert statuses["cand-good"] == ("PENDING_OWNER_REVIEW", [])
    assert [s for cid, s in statuses.items() if cid == "dup"] == [("REJECTED", ["DUPLICATE_CANDIDATE_ID"])]
    assert sum(1 for f in report["findings"] if f["candidate_id"] == "dup") == 2
    malformed = [f for f in report["findings"] if f["candidate_id"].startswith("<malformed:")]
    assert len(malformed) == 2 and all(f["status"] == "REJECTED" for f in malformed)
    assert all(f["input_errors"][0].startswith("MALFORMED_CANDIDATE") for f in malformed)
    [claim_error] = report["trader_claim_errors"]
    assert set(claim_error) == {"record_sha256", "error"}
    assert claim_error["error"].startswith("claim_type must be one of")
    assert claim_error["record_sha256"] == hashlib.sha256(b'{"claim_id":"broken"}').hexdigest()
    assert [a["claim_id"] for a in report["trader_assessments"]] == ["claim-1"]


def test_scout_refuses_a_single_string_as_the_problem_register():
    with pytest.raises(ScoutInputError):
        StrategicScout(verified_problems="ATLAS-PROBLEM-001")


# -- memory firewall -----------------------------------------------------------


@pytest.mark.parametrize("mode", list(ScoutMode))
def test_every_output_is_exploratory_and_carries_no_authority(registry, mode):
    report = _scout(registry).run(_request(mode)).to_dict()
    assert report["epistemic_status"] == EXPLORATORY and report["evidence_eligible"] is False
    for key in ("authority", "production_effect", "live_effect", "registry_writes"):
        assert report[key] == "NONE"
    assert all(f["epistemic_status"] == EXPLORATORY and f["evidence_eligible"] is False for f in report["findings"])
    assert all(a["epistemic_status"] == EXPLORATORY and a["signal_authority"] == "NONE"
               for a in report["trader_assessments"])


def test_reports_are_immutable(registry):
    report = _scout(registry).run(_request(ScoutMode.COST))
    with pytest.raises(dataclasses.FrozenInstanceError):
        report.evidence_eligible = True
    with pytest.raises(TypeError):
        report.mode_analysis["pending_owner_review"] = ("cand-gpl",)
    with pytest.raises(dataclasses.FrozenInstanceError):
        report.findings[0].status = GateStatus.PENDING_OWNER_REVIEW


def test_the_scout_never_writes_the_hypothesis_registry(registry_path, registry):
    before = {p.name: p.read_bytes() for p in registry_path.parent.iterdir()}
    for mode in ScoutMode:
        _scout(registry).run(_request(mode))
    assert {p.name: p.read_bytes() for p in registry_path.parent.iterdir()} == before


def test_the_ledger_is_append_only_hash_chained_and_halts_on_tampering(tmp_path, registry):
    ledger = ScoutLedger(tmp_path / "sandbox" / "scout_ledger.jsonl")
    reports = [_scout(registry).run(_request(mode)) for mode in (ScoutMode.SEARCH, ScoutMode.RED_TEAM)]
    hashes = [ledger.append(report) for report in reports]
    entries = ledger.entries()
    assert [e["entry_sha256"] for e in entries] == hashes
    assert [e["report"]["report_id"] for e in entries] == [r.report_id for r in reports]
    assert all(e["report"]["epistemic_status"] == EXPLORATORY for e in entries)

    lines = ledger.path.read_text(encoding="utf-8").splitlines()
    tampered = json.loads(lines[0])
    tampered["report"]["evidence_eligible"] = True
    ledger.path.write_text(json.dumps(tampered) + "\n" + lines[1] + "\n", encoding="utf-8")
    with pytest.raises(ScoutLedgerError):
        ledger.entries()
    with pytest.raises(ScoutLedgerError):
        ledger.append(reports[0])


def test_the_ledger_detects_an_edit_that_keeps_the_exploratory_tags(tmp_path, registry):
    ledger = ScoutLedger(tmp_path / "scout.jsonl")
    ledger.append(_scout(registry).run(_request(ScoutMode.SEARCH)))
    entry = json.loads(ledger.path.read_text(encoding="utf-8"))
    entry["report"]["query"] = "something else entirely"
    ledger.path.write_text(json.dumps(entry) + "\n", encoding="utf-8")
    with pytest.raises(ScoutLedgerError, match="does not match its hash"):
        ledger.entries()


def test_the_ledger_detects_truncation_and_dropped_lines(tmp_path, registry):
    ledger = ScoutLedger(tmp_path / "scout.jsonl")
    for mode in (ScoutMode.SEARCH, ScoutMode.HUNT, ScoutMode.COST):
        ledger.append(_scout(registry).run(_request(mode)))
    lines = ledger.path.read_text(encoding="utf-8").splitlines()
    ledger.path.write_text(lines[0] + "\n" + lines[2] + "\n", encoding="utf-8")  # middle line dropped
    with pytest.raises(ScoutLedgerError):
        ledger.entries()
    ledger.path.write_text(lines[0] + "\n" + lines[1][:20], encoding="utf-8")  # partial last line
    with pytest.raises(ScoutLedgerError):
        ledger.entries()
    ledger.path.write_text(lines[0] + "\n" + lines[1], encoding="utf-8")  # last write not completed
    with pytest.raises(ScoutLedgerError, match="partial line"):
        ledger.entries()


@pytest.mark.parametrize("path", ["", "research/hypotheses.json", "scout.txt", "memory_data/research/scout.jsonl"])
def test_the_ledger_refuses_canonical_registry_and_runtime_paths(tmp_path, path):
    with pytest.raises(ScoutLedgerError):
        ScoutLedger(path if path == "" else tmp_path / path)


def test_the_ledger_only_records_scout_reports(tmp_path):
    with pytest.raises(ScoutLedgerError):
        ScoutLedger(tmp_path / "scout.jsonl").append({"epistemic_status": "VALIDATED"})


# -- Vectors A and B: static containment ---------------------------------------

_FORBIDDEN_MODULES = {
    "socket", "ssl", "subprocess", "urllib", "http", "requests", "httpx", "aiohttp", "websocket", "websockets",
    "ftplib", "smtplib", "importlib", "ctypes", "pickle", "marshal", "shelve", "multiprocessing", "asyncio",
    "shutil", "runpy", "code", "pty",
}
#: Builtins that run code from data; and os-level process launchers (attribute calls).
_FORBIDDEN_BUILTIN_CALLS = {"eval", "exec", "compile", "__import__", "breakpoint"}
_FORBIDDEN_ATTRIBUTE_CALLS = {"system", "popen", "execv", "execve", "execvp", "spawnv", "spawnl", "startfile",
                              "fork", "forkpty"}
_REGISTRY_WRITES = {"register", "advance", "record_evaluation", "adjudicate_family", "_save"}


def _scout_trees():
    files = sorted(SCOUT_ROOT.glob("*.py"))
    assert {p.name for p in files} >= {"__init__.py", "acceptance_gate.py", "provenance.py",
                                       "strategic_scout.py", "trader_reputation.py"}
    return [(p, ast.parse(p.read_text(encoding="utf-8"))) for p in files]


def test_scout_code_has_no_network_subprocess_or_dynamic_execution_path():
    for path, tree in _scout_trees():
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                roots = {alias.name.split(".")[0] for alias in node.names}
            elif isinstance(node, ast.ImportFrom):
                roots = {(node.module or "").split(".")[0]}
            else:
                roots = set()
            assert not roots & _FORBIDDEN_MODULES, (path.name, roots)
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
                assert node.func.id not in _FORBIDDEN_BUILTIN_CALLS, (path.name, node.func.id)
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
                assert node.func.attr not in _FORBIDDEN_ATTRIBUTE_CALLS, (path.name, node.func.attr)


def test_scout_code_never_calls_a_registry_write_method():
    """Vector A: nothing in research/scout can seal, advance or adjudicate a hypothesis."""
    for path, tree in _scout_trees():
        for node in ast.walk(tree):
            if isinstance(node, ast.Attribute):
                assert node.attr not in _REGISTRY_WRITES, (path.name, node.attr)


def test_nothing_outside_research_and_tests_imports_the_scout():
    tracked = subprocess.run(["git", "ls-files", "-z", "*.py"], cwd=REPOSITORY_ROOT, capture_output=True, text=True,
                             check=True).stdout.split("\0")
    importers = []
    for relative in filter(None, tracked):
        if relative.startswith(("research/", "tests/")):
            continue
        source = (REPOSITORY_ROOT / relative).read_text(encoding="utf-8", errors="replace")
        if "research.scout" in source or "research import scout" in source:
            importers.append(relative)
    assert importers == []
    closure = json.loads((REPOSITORY_ROOT / "packaging" / "atlas_runtime_closure.json").read_text(encoding="utf-8"))
    assert "research/scout" not in json.dumps(closure)


def test_a_compliant_finding_gets_no_further_than_owner_review(registry):
    # End-to-end Vector C: perfect inputs plus a lavish external claim still stop at owner review.
    payload = good_candidate(claimed_benchmarks=["10x faster than everything, independently verified"])
    report = _scout(registry).run(_request(ScoutMode.SEARCH, candidates=[payload])).to_dict()
    [finding] = report["findings"]
    assert finding["status"] == "PENDING_OWNER_REVIEW" and finding["evidence_eligible"] is False
    assert report["mode_analysis"]["pending_owner_review"] == ["cand-good"]


def test_the_as_of_clock_is_explicit():
    candidate = ScoutCandidate.from_dict(good_candidate())
    with pytest.raises(ScoutInputError):
        evaluate_candidate(candidate, as_of=datetime(2026, 10, 11), verified_problems=PROBLEMS)
    later = evaluate_candidate(candidate, as_of=AS_OF + timedelta(days=500), verified_problems=PROBLEMS)
    assert "INACTIVE_MORE_THAN_365_DAYS" in _failed(later)[GateStep.SOURCE_RELIABILITY]
    assert ClaimType.LIVE_TRACK_RECORD.value == "LIVE_TRACK_RECORD"


# -- review 1 regressions (M-1..M-5, L-1..L-6, I-4) -----------------------------


def test_m1_step_six_records_the_provenance_it_relied_on(registry):
    result = _gate(good_candidate(), registry).result_for(GateStep.MEASURABLE_VALUE)
    record = registry.get("HYP-0001")
    assert dict(result.evidence) == {
        "hypothesis_id": "HYP-0001",
        "authenticity": "TAMPER_EVIDENT_NOT_AUTHENTICATED",
        "registry_path": str(registry.registry_path),
        "title": "Overnight reversal in majors",
        "family_id": "FAM-SCOUT-PASS",
        "preregistration_hash": record.preregistration_hash,
        "state_chain_hash": record.state_chain_hash,
        "state": "CANDIDATE",
        "checks_status": "COMPLETE_PASS",
        "preregistered_at": "2026-08-01T00:00:00+00:00",
        "adjudicated_at": REGISTRY_CLOCK.isoformat(),
        "registry_file_sha256": hashlib.sha256(Path(registry.registry_path).read_bytes()).hexdigest(),
    }
    report = _scout(registry).run(_request(ScoutMode.SEARCH, candidates=[good_candidate()])).to_dict()
    step6 = report["findings"][0]["gate"]["steps"][5]
    assert step6["step"] == "MEASURABLE_VALUE" and step6["evidence"]["registry_path"] == str(registry.registry_path)


def test_m2_a_hypothesis_bound_to_another_candidate_cannot_be_borrowed(registry):
    # HYP-0004 passed adjudication, but it was sealed for cand-other.
    borrowed = _gate(good_candidate(sealed_hypothesis_id="HYP-0004"), registry)
    assert _failed(borrowed) == {GateStep.MEASURABLE_VALUE: ("HYPOTHESIS_NOT_BOUND_TO_CANDIDATE:HYP-0004",)}
    # Quoting the bound id from another candidate, or from the same id at another URL, fails too.
    for payload in (good_candidate(candidate_id="cand-copy"),
                    good_candidate(source=_source(url="https://github.com/example/fork"))):
        assert _failed(_gate(payload, registry)) == {
            GateStep.MEASURABLE_VALUE: ("HYPOTHESIS_NOT_BOUND_TO_CANDIDATE:HYP-0001",)}
    report = _scout(registry).run(_request(ScoutMode.SEARCH, candidates=[
        good_candidate(), good_candidate(candidate_id="cand-copy"), good_candidate(candidate_id="cand-copy-2")],
        trader_claims=[])).to_dict()
    assert report["mode_analysis"]["pending_owner_review"] == ["cand-good"]


@pytest.mark.parametrize("separator", ["\u2028", "\u2029", "\x85", "\r", "\x1c"])
def test_m3_line_separators_in_external_text_do_not_break_the_ledger(tmp_path, registry, separator):
    ledger = ScoutLedger(tmp_path / "scout.jsonl")
    report = _scout(registry).run(_request(ScoutMode.SEARCH, query=f"nice{separator}query",
                                           candidates=[good_candidate(name=f"nice{separator}tool")]))
    first = ledger.append(report)
    second = ledger.append(report)
    entries = ledger.entries(anchor=second)
    assert [e["entry_sha256"] for e in entries] == [first, second]
    assert entries[0]["report"]["findings"][0]["candidate"]["name"] == f"nice{separator}tool"
    assert ledger.path.read_bytes().isascii()


def test_m4_firewall_tags_cannot_be_overridden(registry):
    report = _scout(registry).run(_request(ScoutMode.SEARCH))
    for field, value in (("authority", "FULL"), ("live_effect", "LIVE"), ("registry_writes", "WRITE"),
                         ("evidence_eligible", True), ("epistemic_status", "VALIDATED")):
        with pytest.raises(ValueError):
            dataclasses.replace(report, **{field: value})
    finding = report.findings[0]
    with pytest.raises(ValueError):
        dataclasses.replace(finding, evidence_eligible=True)
    assessment = report.trader_assessments[0]
    for field, value in (("signal_authority", "TRADE"), ("epistemic_status", "VALIDATED"), ("next_step", "BUY")):
        with pytest.raises(ValueError):
            dataclasses.replace(assessment, **{field: value})


def test_m4_a_never_gated_or_inconsistent_pending_finding_cannot_be_built(registry):
    report = _scout(registry).run(_request(ScoutMode.SEARCH))
    good = next(f for f in report.findings if f.candidate_id == "cand-good")
    bad = next(f for f in report.findings if f.candidate_id == "cand-gpl")
    with pytest.raises(ValueError):
        ScoutFinding("never-gated", GateStatus.PENDING_OWNER_REVIEW, None, good.gate, (), ())
    with pytest.raises(ValueError):
        dataclasses.replace(bad, status=GateStatus.PENDING_OWNER_REVIEW)
    with pytest.raises(ValueError):
        dataclasses.replace(good, mode_flags=("RED_TEAM:X",))
    with pytest.raises(ValueError):
        dataclasses.replace(bad.gate, status=GateStatus.PENDING_OWNER_REVIEW)
    with pytest.raises(ValueError):
        dataclasses.replace(good.gate, steps=good.gate.steps[:6])
    with pytest.raises(ValueError):
        dataclasses.replace(good.gate.steps[0], passed=False)


def test_m4_the_ledger_validates_before_writing_and_never_corrupts_itself(tmp_path, registry):
    ledger = ScoutLedger(tmp_path / "scout.jsonl")
    head = ledger.append(_scout(registry).run(_request(ScoutMode.SEARCH)))
    forged = _scout(registry).run(_request(ScoutMode.HUNT))
    object.__setattr__(forged, "authority", "FULL")  # bypasses the frozen dataclass deliberately
    with pytest.raises(ScoutLedgerError, match="refusing to record"):
        ledger.append(forged)
    assert len(ledger.entries(anchor=head)) == 1  # the ledger stays readable
    ledger.append(_scout(registry).run(_request(ScoutMode.COST)))
    assert len(ledger.entries(anchor=head)) == 2


def test_m4_a_hand_built_entry_with_a_valid_chain_but_an_authority_tag_is_refused(tmp_path, registry):
    ledger = ScoutLedger(tmp_path / "scout.jsonl")
    payload = _scout(registry).run(_request(ScoutMode.SEARCH)).to_dict()
    payload["live_effect"] = "LIVE"
    payload["report_id"] = hashlib.sha256(json.dumps({k: v for k, v in payload.items() if k != "report_id"},
                                                     sort_keys=True, separators=(",", ":"),
                                                     ensure_ascii=False).encode()).hexdigest()
    body = {"seq": 0, "prev_sha256": "0" * 64, "report": payload}
    body["entry_sha256"] = hashlib.sha256(json.dumps({k: body[k] for k in ("seq", "prev_sha256", "report")},
                                                     sort_keys=True, separators=(",", ":"),
                                                     ensure_ascii=False).encode()).hexdigest()
    ledger.path.write_text(json.dumps(body) + "\n", encoding="utf-8")
    with pytest.raises(ScoutLedgerError, match="live_effect"):
        ledger.entries()


@pytest.mark.parametrize("overrides, reason", [
    ({"source": _source(url="https://x.com/someone/status/1", source_type="SOCIAL")}, "SOCIAL_SOURCE"),
    ({"execution_log": dict(good_claim()["execution_log"], sha256="0" * 64)}, "PLACEHOLDER_LOG_DIGEST"),
    ({"execution_log": dict(good_claim()["execution_log"], sha256=hashlib.sha256(b"").hexdigest())},
     "PLACEHOLDER_LOG_DIGEST"),
    ({"execution_log": dict(good_claim()["execution_log"], verified_by="me")}, "VERIFIER_NOT_TRUSTED"),
])
def test_m5_self_attested_or_social_track_records_are_insufficient_evidence(overrides, reason):
    assessment = _assess(good_claim(**overrides))
    assert assessment.rating is ReputationRating.INSUFFICIENT_EVIDENCE
    assert reason in assessment.reasons


def test_m5_without_an_owner_named_verifier_nothing_reaches_research_candidate():
    assert _assess(good_claim(), policy=ReputationPolicy()).rating is ReputationRating.INSUFFICIENT_EVIDENCE
    assert "VERIFIER_NOT_TRUSTED" in _assess(good_claim(), policy=ReputationPolicy()).reasons


@pytest.mark.parametrize("bad_id", ["cand\n", "cand\r", " cand", "cand ", "-cand", "c" * 65])
def test_l1_identifiers_must_match_completely(bad_id):
    with pytest.raises(ScoutInputError):
        ScoutCandidate.from_dict(good_candidate(candidate_id=bad_id))
    with pytest.raises(ScoutInputError):
        TraderClaim.from_dict(good_claim(claim_id=bad_id))


def test_l2_an_overflowing_number_is_a_malformed_record_not_a_crash(registry):
    report = _scout(registry).run(_request(ScoutMode.SEARCH, candidates=[
        good_candidate(), good_candidate(candidate_id="cand-huge", monthly_cost_usd=10 ** 400)])).to_dict()
    statuses = {f["candidate_id"]: f["status"] for f in report["findings"]}
    assert statuses.pop("cand-good") == "PENDING_OWNER_REVIEW"
    [(malformed, status)] = statuses.items()
    assert malformed.startswith("<malformed:") and status == "REJECTED"
    with pytest.raises(ScoutInputError):
        ScoutRequest(mode=ScoutMode.COST, query="q", as_of=AS_OF, context={"current_monthly_cost_usd": 10 ** 400})


def test_l3_collections_of_names_refuse_a_bare_string():
    candidate = ScoutCandidate.from_dict(good_candidate(problem_ref="A"))
    with pytest.raises(ScoutInputError):
        evaluate_candidate(candidate, as_of=AS_OF, verified_problems="ATLAS-PROBLEM-001")
    with pytest.raises(ValueError):
        GatePolicy(allowed_licenses="MIT")
    with pytest.raises(ValueError):
        ReputationPolicy(trusted_verifiers="owner")
    with pytest.raises(ScoutInputError):
        evaluate_candidate(candidate, as_of=AS_OF, verified_problems=PROBLEMS, policy="lenient")


def test_l4_an_anchor_detects_lost_trailing_entries_and_a_full_rewrite(tmp_path, registry):
    ledger = ScoutLedger(tmp_path / "scout.jsonl")
    reports = [_scout(registry).run(_request(mode)) for mode in (ScoutMode.SEARCH, ScoutMode.HUNT)]
    ledger.append(reports[0])
    head = ledger.append(reports[1])
    lines = ledger.path.read_text(encoding="utf-8").split("\n")
    ledger.path.write_text(lines[0] + "\n", encoding="utf-8")  # trailing entry lost
    assert len(ledger.entries()) == 1  # undetectable without an anchor ...
    with pytest.raises(ScoutLedgerError, match="anchored entry is missing"):
        ledger.entries(anchor=head)  # ... detected with one
    ledger.path.unlink()
    ledger.append(reports[1])  # a complete rewrite with fresh, valid hashes
    with pytest.raises(ScoutLedgerError, match="anchored entry is missing"):
        ledger.entries(anchor=head)
    ledger.path.unlink()
    with pytest.raises(ScoutLedgerError):
        ledger.entries(anchor=head)


def test_l5_duplicate_claims_are_refused_and_reports_ignore_input_order(registry):
    candidates = _candidates() + [good_candidate(candidate_id="dup"), good_candidate(candidate_id="dup", name="other"),
                                  {"candidate_id": "bad", "kind": "?"}, "junk"]
    claims = [good_claim(), good_claim(claim_id="claim-2", trader_id="trader-b"),
              good_claim(claim_id="claim-2", trader_id="trader-c"), {"claim_id": "broken"}, 7]
    first = _scout(registry).run(_request(ScoutMode.SEARCH, candidates=candidates, trader_claims=claims))
    data = first.to_dict()
    assert [a["claim_id"] for a in data["trader_assessments"]] == ["claim-1"]
    assert sorted(e["error"] for e in data["trader_claim_errors"])[:2] == ["DUPLICATE_CLAIM_ID:claim-2"] * 2
    rng = random.Random(11)
    for _ in range(5):
        rng.shuffle(candidates)
        rng.shuffle(claims)
        assert _scout(registry).run(_request(ScoutMode.SEARCH, candidates=candidates,
                                             trader_claims=claims)).report_id == first.report_id


def test_l6_the_ledger_refuses_runtime_roots_and_linked_files(tmp_path, monkeypatch):
    state = tmp_path / "relocated_state"
    state.mkdir()
    monkeypatch.setenv("ATLAS_STATE_DIRECTORY", str(state))
    with pytest.raises(ScoutLedgerError, match="ATLAS_STATE_DIRECTORY"):
        ScoutLedger(state / "execution_closed_positions.jsonl")
    target = tmp_path / "real.jsonl"
    target.write_text("", encoding="utf-8")
    link = tmp_path / "link.jsonl"
    link.symlink_to(target)
    with pytest.raises(ScoutLedgerError, match="symlink"):
        ScoutLedger(link)
    hard = tmp_path / "hard.jsonl"
    hard.hardlink_to(target)
    with pytest.raises(ScoutLedgerError, match="hard-linked"):
        ScoutLedger(hard)


def test_i4_red_team_surfaces_benchmark_claims_even_when_step_six_passes(registry):
    payload = good_candidate(claimed_benchmarks=["3x faster"])
    report = _scout(registry).run(_request(ScoutMode.RED_TEAM, candidates=[payload])).to_dict()
    assert report["findings"][0]["gate"]["status"] == "PENDING_OWNER_REVIEW"
    assert report["mode_analysis"]["failure_modes"]["cand-good"] == ["UNVERIFIED_BENCHMARK_CLAIMS"]
    assert report["findings"][0]["status"] == "REJECTED"


def test_m3_the_reader_alone_survives_raw_separators_in_a_valid_ledger(tmp_path, registry):
    # Defence in depth: a valid ledger whose lines carry an unescaped U+2028 (any JSON writer may emit one)
    # still reads, because the reader splits on "\n" only.
    ledger = ScoutLedger(tmp_path / "scout.jsonl")
    head = ledger.append(_scout(registry).run(_request(ScoutMode.SEARCH, query="a b")))
    entry = json.loads(ledger.path.read_text(encoding="utf-8"))
    raw_line = json.dumps(entry, ensure_ascii=False)
    assert " " in raw_line
    ledger.path.write_text(raw_line + "\n", encoding="utf-8")
    assert [e["entry_sha256"] for e in ledger.entries(anchor=head)] == [head]


@pytest.mark.parametrize("steps", [[1, 2, 3, 4, 5, 6, 7], "steps", None, [{"step": "REAL_PROBLEM_ALIGNMENT", "passed": True}] * 7])
def test_m4_a_malformed_pending_verdict_in_the_ledger_halts_cleanly(tmp_path, registry, steps):
    ledger = ScoutLedger(tmp_path / "scout.jsonl")
    ledger.append(_scout(registry).run(_request(ScoutMode.SEARCH, candidates=[good_candidate()], trader_claims=[])))
    entry = json.loads(ledger.path.read_text(encoding="utf-8"))
    entry["report"]["findings"][0]["gate"]["steps"] = steps
    assert _report_problem(entry["report"]) is not None


def test_reason_text_from_external_records_cannot_forge_log_lines(registry, caplog):
    from research.scout.provenance import ScoutInputError

    with pytest.raises(ScoutInputError):  # control characters are refused at input
        ScoutCandidate.from_dict(good_candidate(license_spdx="GPL-3.0-only\nscout gate PENDING_OWNER_REVIEW"))
    payload = good_candidate(license_spdx="GPL-3.0-only\u00e9")  # printable non-ASCII is escaped
    with caplog.at_level(logging.WARNING, logger="research.scout.acceptance_gate"):
        _gate(payload, registry)
    [record] = caplog.records
    message = record.getMessage()
    assert message.isascii() and "LICENSE_NOT_ALLOWED:GPL-3.0-only\\xe9" in message


# -- review 22 ---------------------------------------------------------------------------------------


def _step6(verdict):
    return tuple(verdict.result_for(GateStep.MEASURABLE_VALUE).reasons)


def test_m1_step_six_refuses_evidence_dated_after_as_of(registry):
    """M-1: the no-lookahead rule, both timestamps, and the equality boundary."""
    candidate = ScoutCandidate.from_dict(good_candidate())
    day = timedelta(days=1)
    before_adjudication = evaluate_candidate(candidate, as_of=REGISTRY_CLOCK - day, verified_problems=PROBLEMS,
                                             registry=registry)
    assert _step6(before_adjudication) == ("HYPOTHESIS_ADJUDICATED_AFTER_AS_OF",)
    before_both = evaluate_candidate(candidate, as_of=datetime(2026, 7, 31, tzinfo=UTC), verified_problems=PROBLEMS,
                                     registry=registry)
    assert _step6(before_both) == ("HYPOTHESIS_PREREGISTERED_AFTER_AS_OF", "HYPOTHESIS_ADJUDICATED_AFTER_AS_OF")
    at_adjudication = evaluate_candidate(candidate, as_of=REGISTRY_CLOCK, verified_problems=PROBLEMS,
                                         registry=registry)
    assert _step6(at_adjudication) == ()  # evidence timestamped exactly at as_of is not after it


def test_m1_step_six_reads_the_registry_file_not_the_object(registry, tmp_path):
    """M-1: a registry object whose memory differs from its file is judged by the file."""
    other = HypothesisRegistry(registry_path=tmp_path / "other" / "hypotheses.json")
    other.register(_preregistration("HYP-0003", "FAM-SCOUT-OPEN"))
    Path(registry.registry_path).write_bytes(Path(other.registry_path).read_bytes())
    assert registry.get("HYP-0001").state is HypothesisState.CANDIDATE  # still in the object's memory
    assert _step6(_gate(good_candidate(), registry)) == ("HYPOTHESIS_NOT_REGISTERED:HYP-0001",)


def test_m1_a_registry_file_that_changes_while_read_or_cannot_be_read_is_refused(registry, monkeypatch):
    import research.scout.acceptance_gate as gate_module

    digests = iter(["a" * 64, "b" * 64])
    monkeypatch.setattr(gate_module, "_file_digest", lambda path: next(digests))
    assert _step6(_gate(good_candidate(), registry)) == ("REGISTRY_CHANGED_DURING_READ",)
    monkeypatch.setattr(gate_module, "_file_digest", lambda path: None)
    assert _step6(_gate(good_candidate(), registry)) == ("REGISTRY_FILE_UNREADABLE",)


def _pending_report(registry):
    report = _scout(registry).run(_request(ScoutMode.SEARCH, candidates=[good_candidate()], trader_claims=[]))
    assert [f.status for f in report.findings] == [GateStatus.PENDING_OWNER_REVIEW]
    return report


def _resealed(payload):
    from research.scout.provenance import sha256_hex

    body = {key: value for key, value in payload.items() if key != "report_id"}
    return {**body, "report_id": sha256_hex(body)}


def test_m1_a_report_or_ledger_entry_with_lookahead_evidence_is_refused(registry):
    report = _pending_report(registry)
    with pytest.raises(ValueError, match="adjudicated_at is after as_of"):
        dataclasses.replace(report, as_of=REGISTRY_CLOCK - timedelta(days=1))
    payload = report.to_dict()
    payload["as_of"] = (REGISTRY_CLOCK - timedelta(days=1)).isoformat()
    assert "adjudicated_at is after as_of" in _report_problem(_resealed(payload))
    assert _report_problem(report.to_dict()) is None


def test_l1_read_side_validation_of_pending_findings_and_research_candidates(registry):
    payload = _pending_report(registry).to_dict()
    flagged = json.loads(json.dumps(payload))
    flagged["findings"][0]["mode_flags"] = ["FORGED"]
    assert "carries flags or errors" in _report_problem(_resealed(flagged))
    orphan = json.loads(json.dumps(payload))
    orphan["findings"][0]["candidate"] = None
    assert "lacks its candidate" in _report_problem(_resealed(orphan))
    promoted = json.loads(json.dumps(payload))
    promoted["trader_assessments"] = [{"epistemic_status": "EXPLORATORY", "signal_authority": "NONE",
                                       "next_step": NEXT_STEP, "rating": "RESEARCH_CANDIDATE",
                                       "claim_type": "BACKTEST", "source": {"source_type": "REPOSITORY"},
                                       "dimensions": []}]
    assert "does not follow from its claim" in _report_problem(_resealed(promoted))


def test_l1_the_ledger_refuses_a_path_swapped_after_construction(registry, tmp_path):
    report = _pending_report(registry)
    path = tmp_path / "scout.jsonl"
    ledger = ScoutLedger(path)
    ledger.append(report)
    os.link(path, tmp_path / "copy.jsonl")  # a hard link appears after construction
    with pytest.raises(ScoutLedgerError):
        ledger.append(report)
    os.unlink(tmp_path / "copy.jsonl")
    target = tmp_path / "elsewhere.jsonl"
    path.rename(target)
    path.symlink_to(target)  # the path becomes a symlink after construction
    with pytest.raises(ScoutLedgerError):
        ledger.append(report)


def test_l1_appends_hold_the_registry_write_lock(registry, tmp_path, monkeypatch):
    import contextlib

    import research.scout.strategic_scout as scout_module

    held: list[Path] = []
    real = scout_module.registry_write_lock

    @contextlib.contextmanager
    def recording(path, **kw):
        with real(path, **kw):
            held.append(Path(path))
            yield

    monkeypatch.setattr(scout_module, "registry_write_lock", recording)
    ledger = ScoutLedger(tmp_path / "scout.jsonl")
    ledger.append(_pending_report(registry))
    assert held == [ledger.path]


@pytest.mark.parametrize("count, passes", [(0, True), (1, False)])
def test_l1_one_known_vulnerability_fails_the_security_step(registry, count, passes):
    security = dict(good_candidate()["security"], known_vulnerabilities=count)
    result = _gate(good_candidate(security=security), registry).result_for(GateStep.SECURITY_RISK)
    assert result.passed is passes
    assert result.reasons == (() if passes else ("KNOWN_VULNERABILITIES:1",))


def test_l2_a_malformed_registry_file_is_refused_not_a_crash(registry):
    path = Path(registry.registry_path)
    payload = json.loads(path.read_text(encoding="utf-8"))
    for records in ([1], [None]):
        path.write_text(json.dumps({**payload, "records": records}), encoding="utf-8")
        reasons = _step6(_gate(good_candidate(), registry))
        assert len(reasons) == 1 and reasons[0].startswith("REGISTRY_FILE_INVALID:"), reasons
    path.write_text("[" * 100_000 + "]" * 100_000, encoding="utf-8")
    reasons = _step6(_gate(good_candidate(), registry))
    assert len(reasons) == 1 and reasons[0].startswith("REGISTRY_FILE_INVALID:"), reasons


def test_l2_a_deeply_nested_record_is_refused_without_hiding_the_others(registry):
    deep: dict[str, Any] = {}
    cursor = deep
    for _ in range(100_000):
        cursor["x"] = {}
        cursor = cursor["x"]
    report = _scout(registry).run(_request(ScoutMode.SEARCH, candidates=[good_candidate(), deep],
                                           trader_claims=[good_claim(), deep]))
    statuses = sorted(f.status.value for f in report.findings)
    assert statuses == ["PENDING_OWNER_REVIEW", "REJECTED"]
    assert len(report.trader_assessments) == 1 and len(report.trader_claim_errors) == 1


def test_m1_the_fresh_read_record_decides_even_when_memory_holds_another(registry, tmp_path):
    """M-1 (G36): the file holds HYP-0001 bound to another candidate; the object's memory does not."""
    other = HypothesisRegistry(registry_path=tmp_path / "other" / "hypotheses.json")
    _register_and_test(other, "HYP-0001", "FAM-SCOUT-PASS", p_value=0.001, effect_size=0.9,
                       binding={"scout_candidate_id": "cand-other", "scout_source_url": "https://example.org/o"})
    other.adjudicate_family("FAM-SCOUT-PASS", q=0.1)
    Path(registry.registry_path).write_bytes(Path(other.registry_path).read_bytes())
    assert dict(registry.get("HYP-0001").preregistration.feature_spec)["scout_candidate_id"] == "cand-good"
    assert _step6(_gate(good_candidate(), registry)) == ("HYPOTHESIS_NOT_BOUND_TO_CANDIDATE:HYP-0001",)


@pytest.mark.parametrize("parts", [("data", "market_archive"), ("evidence_store",)])
def test_l1_the_ledger_refuses_the_default_runtime_roots(parts):
    root = REPOSITORY_ROOT.joinpath(*parts)
    with pytest.raises(ScoutLedgerError, match="runtime root"):
        ScoutLedger(root / "scout.jsonl")


@pytest.mark.parametrize("field, value", [("seq", 7), ("prev_sha256", "0" * 64)])
def test_l1_the_ledger_checks_sequence_and_previous_hash_separately(registry, tmp_path, field, value):
    ledger = ScoutLedger(tmp_path / "scout.jsonl")
    ledger.append(_pending_report(registry))
    ledger.append(_scout(registry).run(_request(ScoutMode.HUNT)))
    lines = ledger.path.read_text(encoding="utf-8").splitlines()
    entries = [json.loads(line) for line in lines]
    index = next(i for i, e in enumerate(entries) if isinstance(e, dict) and e.get("seq") == 1)
    entries[index][field] = value
    ledger.path.write_text("".join(json.dumps(e) + "\n" for e in entries), encoding="utf-8")
    with pytest.raises(ScoutLedgerError, match="breaks the sequence or hash chain"):
        ledger.entries()


def test_l1_report_tags_types_ids_and_pending_provenance_are_checked_on_read(registry):
    payload = _pending_report(registry).to_dict()
    retyped = json.loads(json.dumps(payload))
    retyped["evidence_eligible"] = 0  # equal to False, but not the declared type
    assert "report tag evidence_eligible" in _report_problem(_resealed(retyped))
    altered = json.loads(json.dumps(payload))
    altered["query"] = "something else"  # report_id no longer matches
    assert _report_problem(altered) == "report_id does not match the report"
    stripped = json.loads(json.dumps(payload))
    del stripped["findings"][0]["gate"]["steps"][5]["evidence"]["registry_file_sha256"]
    assert "PENDING_OWNER_REVIEW refused" in _report_problem(_resealed(stripped))


def test_l1_trader_assessments_do_not_depend_on_input_order(registry):
    claims = [good_claim(), good_claim(claim_id="claim-2", trader_id="trader-0")]
    forward = _scout(registry).run(_request(ScoutMode.SEARCH, trader_claims=claims)).to_dict()
    backward = _scout(registry).run(_request(ScoutMode.SEARCH, trader_claims=claims[::-1])).to_dict()
    assert forward == backward


@pytest.mark.parametrize("overrides, mode", [
    ({"security": dict(good_candidate()["security"], network_access=None)}, "SECURITY_NOT_FULLY_ASSESSED"),
    ({"requires_state_migration": True}, "STATE_MIGRATION_RISK"),
    ({"license_spdx": "GPL-3.0-only"}, "LICENSE_RISK"),
])
def test_l1_each_red_team_failure_mode_is_raised(registry, overrides, mode):
    from research.scout.strategic_scout import _red_team_failure_modes

    candidate = ScoutCandidate.from_dict(good_candidate(**overrides))
    gate = evaluate_candidate(candidate, as_of=AS_OF, verified_problems=PROBLEMS, registry=registry)
    assert mode in _red_team_failure_modes(candidate, gate)


def test_l1_research_candidate_cannot_be_forged_and_a_late_source_is_not_verifiable():
    from research.scout.trader_reputation import DimensionVerdict, ReputationDimension

    backtest = _assess(good_claim(claim_type="BACKTEST"), TRUSTING)
    with pytest.raises(ValueError, match="RESEARCH_CANDIDATE requires"):
        dataclasses.replace(backtest, rating=ReputationRating.RESEARCH_CANDIDATE)
    late = _assess(good_claim(source=_source(url="https://example.org/track-record", source_type="ARTICLE",
                                              retrieved_at="2026-10-12T00:00:00+00:00")), TRUSTING)
    verdicts = {d.dimension: d.verdict for d in late.dimensions}
    assert verdicts[ReputationDimension.SOURCE_VERIFIABILITY] is not DimensionVerdict.PASS
    assert late.rating is not ReputationRating.RESEARCH_CANDIDATE


@pytest.mark.parametrize("overrides", [
    {"monthly_cost_usd": float("inf")},
    {"name": "x" * 4001},
    {"source": _source(url="javascript:alert(1)")},
    {"source": _source(url="https://github.com/example/to ol")},
    {"license_spdx": "MIT x"},
])
def test_l1_input_validators_refuse_bad_records(overrides):
    with pytest.raises(ScoutInputError):
        ScoutCandidate.from_dict(good_candidate(**overrides))


@pytest.mark.parametrize("path, value", [
    (("gate", "steps", 5, "evidence", "state"), "REGISTERED"),
    (("candidate", "requires_state_migration"), True),
])
def test_l1_pending_findings_are_rechecked_on_read(registry, path, value):
    payload = json.loads(json.dumps(_pending_report(registry).to_dict()))
    target = payload["findings"][0]
    for key in path[:-1]:
        target = target[key]
    target[path[-1]] = value
    assert "PENDING_OWNER_REVIEW refused" in _report_problem(_resealed(payload))


def test_l1_the_gate_denominator_is_fixed(registry):
    verdict = _gate(good_candidate(), registry)
    with pytest.raises(ValueError):
        dataclasses.replace(verdict, required_step_count=6)


# -- review 23 ---------------------------------------------------------------------------------------


def _deep(depth=100_000):
    root: dict[str, Any] = {}
    cursor = root
    for _ in range(depth):
        cursor["x"] = {}
        cursor = cursor["x"]
    return root


def test_m1_a_deep_value_inside_a_known_field_is_refused_per_record(registry):
    """Review 23 M-1: an enum field holding a deep value recurses while it is parsed."""
    report = _scout(registry).run(_request(
        ScoutMode.SEARCH,
        candidates=[good_candidate(), good_candidate(candidate_id="cand-deep", kind=_deep())],
        trader_claims=[good_claim(), good_claim(claim_id="claim-deep", claim_type=_deep())],
    ))
    errors = [f.input_errors for f in report.findings if f.status is GateStatus.REJECTED]
    assert errors == [("MALFORMED_CANDIDATE: RECORD_NESTED_TOO_DEEPLY",)]
    assert [f.status for f in report.findings].count(GateStatus.PENDING_OWNER_REVIEW) == 1
    assert [e["error"] for e in report.trader_claim_errors] == ["RECORD_NESTED_TOO_DEEPLY"]
    assert len(report.trader_assessments) == 1


def test_l4_unserialisable_malformed_records_do_not_depend_on_input_order(registry):
    first = good_candidate(candidate_id="cand-a", last_activity_at=datetime(2026, 1, 1), kind="NOT-A-KIND")
    second = good_candidate(candidate_id="cand-b", last_activity_at=datetime(2026, 1, 1), name="")
    forward = _scout(registry).run(_request(ScoutMode.SEARCH, candidates=[first, second])).to_dict()
    backward = _scout(registry).run(_request(ScoutMode.SEARCH, candidates=[second, first])).to_dict()
    assert forward == backward


def _pending_parts(registry):
    finding = json.loads(json.dumps(_pending_report(registry).to_dict()))["findings"][0]
    return finding["candidate"], finding["gate"]


@pytest.mark.parametrize("where, key, value", [
    ("candidate", "overlapping_components", ["core/risk_engine.py"]),
    ("candidate", "problem_ref", None),
    ("security", "network_access", True),
    ("security", "known_vulnerabilities", 1),
    ("source", "source_type", "SOCIAL"),
    ("evidence", "hypothesis_id", "HYP-9999"),
    ("evidence", "checks_status", "INCOMPLETE"),
    ("evidence", "title", ""),
    ("gate", "candidate_id", "cand-other"),
])
def test_l1_each_pending_condition_is_rechecked_alone(registry, where, key, value):
    from research.scout.acceptance_gate import pending_problem

    candidate, gate = _pending_parts(registry)
    assert pending_problem(candidate, gate) is None
    target = {"candidate": candidate, "security": candidate["security"], "source": candidate["source"],
              "evidence": gate["steps"][5]["evidence"], "gate": gate}[where]
    target[key] = value
    assert pending_problem(candidate, gate) is not None


def _report_with_assessments(registry):
    report = json.loads(json.dumps(_scout(registry).run(_request(ScoutMode.SEARCH)).to_dict()))
    assert _report_problem(report) is None
    return report


@pytest.mark.parametrize("mutate, message", [
    (lambda r: r["findings"][0].update(evidence_eligible=True), "a finding is not EXPLORATORY"),
    (lambda r: r["findings"][0].update(status="ACCEPTED"), "a finding has an unknown status"),
    (lambda r: r["trader_assessments"][0].update(signal_authority="FULL"), "a trader assessment carries authority"),
    (lambda r: r["trader_assessments"][0].update(next_step="TRADE"), "a trader assessment carries authority"),
    (lambda r: r["trader_assessments"][0].update(rating="STAR"), "a trader assessment has an unknown rating"),
])
def test_l1_the_read_side_firewall_checks_each_condition_alone(registry, mutate, message):
    report = _report_with_assessments(registry)
    mutate(report)
    assert _report_problem(_resealed(report)) == message
    assert _report_problem([report]) == "the report is not an object"


def _research_candidate_report(registry):
    report = _report_with_assessments(registry)
    index = next(i for i, a in enumerate(report["trader_assessments"]) if a["rating"] == "RESEARCH_CANDIDATE")
    return report, report["trader_assessments"][index]


@pytest.mark.parametrize("mutate", [
    lambda a: a.update(claim_type="BACKTEST"),
    lambda a: a["source"].update(source_type="SOCIAL"),
    lambda a: a.update(dimensions=a["dimensions"][:3]),
])
def test_l1_each_research_candidate_condition_is_rechecked_on_read(registry, mutate):
    report, assessment = _research_candidate_report(registry)
    mutate(assessment)
    assert _report_problem(_resealed(report)) == "a RESEARCH_CANDIDATE assessment does not follow from its claim"


def test_l1_a_social_source_cannot_be_research_candidate_at_construction():
    from research.scout.provenance import SourceType

    assessment = _assess(good_claim(), TRUSTING)
    assert assessment.rating is ReputationRating.RESEARCH_CANDIDATE
    with pytest.raises(ValueError, match="RESEARCH_CANDIDATE requires"):
        dataclasses.replace(assessment, source=dataclasses.replace(assessment.source, source_type=SourceType.SOCIAL))


# -- review 24 ---------------------------------------------------------------------------------------


@pytest.mark.parametrize("mutate", [
    lambda record: record["preregistration"].update(alpha=10 ** 400),  # OverflowError while loading
    lambda record: record["preregistration"]["split_spec"].update(train_fraction=-1),  # SplitError
])
def test_r24_any_failure_to_load_the_registry_file_is_refused_never_a_crash(registry, mutate):
    path = Path(registry.registry_path)
    payload = json.loads(path.read_text(encoding="utf-8"))
    mutate(next(r for r in payload["records"] if r["preregistration"]["hypothesis_id"] == "HYP-0001"))
    path.write_text(json.dumps(payload), encoding="utf-8")
    reasons = _step6(_gate(good_candidate(), registry))
    assert len(reasons) == 1 and reasons[0].startswith("REGISTRY_FILE_INVALID:"), reasons
    report = _scout(registry).run(_request(ScoutMode.SEARCH, candidates=[good_candidate()]))
    assert [f.status for f in report.findings] == [GateStatus.REJECTED]


def test_r24_duplicate_unserialisable_records_do_not_depend_on_input_order(registry):
    first = good_candidate(candidate_id="dup", name="Alpha", last_activity_at=datetime(2026, 9, 1, tzinfo=UTC))
    second = good_candidate(candidate_id="dup", name="Beta", last_activity_at=datetime(2026, 9, 1, tzinfo=UTC))
    forward = _scout(registry).run(_request(ScoutMode.SEARCH, candidates=[first, second])).to_dict()
    backward = _scout(registry).run(_request(ScoutMode.SEARCH, candidates=[second, first])).to_dict()
    assert forward == backward


# -- review 25 ---------------------------------------------------------------------------------------


def test_r25_a_failed_dimension_cannot_be_research_candidate_at_construction():
    from research.scout.trader_reputation import DimensionVerdict

    assessment = _assess(good_claim(), TRUSTING)
    assert assessment.rating is ReputationRating.RESEARCH_CANDIDATE
    failed = (dataclasses.replace(assessment.dimensions[0], verdict=DimensionVerdict.FAIL),
              *assessment.dimensions[1:])
    with pytest.raises(ValueError, match="RESEARCH_CANDIDATE requires"):
        dataclasses.replace(assessment, dimensions=failed)


@pytest.mark.parametrize("mutate", [
    lambda a: a["dimensions"][0].update(verdict="FAIL"),
    lambda a: a.update(source="https://example.org/track-record"),
])
def test_r25_a_research_candidate_with_a_failed_dimension_or_no_source_object_is_refused_on_read(
        registry, mutate):
    report, assessment = _research_candidate_report(registry)
    mutate(assessment)
    assert _report_problem(_resealed(report)) == "a RESEARCH_CANDIDATE assessment does not follow from its claim"


def test_r25_an_unusable_registry_path_fails_step_six_not_the_run(registry, tmp_path):
    broken = HypothesisRegistry(registry_path=tmp_path / "a\0b.json")
    assert _step6(_gate(good_candidate(), broken)) == ("REGISTRY_FILE_UNREADABLE",)


# -- review 26 ---------------------------------------------------------------------------------------


def test_r26_a_never_adjudicated_hypothesis_records_no_adjudication_time(registry):
    """G15: the provenance shown to the owner never carries a fabricated adjudication date."""
    result = _gate(good_candidate(sealed_hypothesis_id="HYP-0003"), registry).result_for(GateStep.MEASURABLE_VALUE)
    assert result.passed is False and result.evidence["state"] == "REGISTERED"
    assert result.evidence["adjudicated_at"] is None


def test_r26_a_tested_but_unadjudicated_hypothesis_fails_for_that_reason(registry_path):
    """G09: a hypothesis that was tested but not family-adjudicated fails as not adjudicated."""
    registry = HypothesisRegistry(registry_path=registry_path)
    _register_and_test(registry, "HYP-0005", "FAM-SCOUT-TESTED", p_value=0.001, effect_size=0.9)
    assert registry.get("HYP-0005").state is HypothesisState.TESTED
    assert _step6(_gate(good_candidate(sealed_hypothesis_id="HYP-0005"), registry)) == (
        "HYPOTHESIS_NOT_ADJUDICATED_PASS:TESTED",)


# -- review 27 ---------------------------------------------------------------------------------------


@pytest.mark.parametrize("naive", ["2026-08-01T00:00:00", "2026-12-01T00:00:00"])
def test_r27_a_preregistration_time_without_a_timezone_never_passes_step_six(registry_path, naive):
    """The registry accepts an author-supplied naive timestamp; the gate refuses it, before or after as_of."""
    registry = HypothesisRegistry(registry_path=registry_path)
    preregistration = dataclasses.replace(_preregistration("HYP-0006", "FAM-SCOUT-NAIVE"), preregistered_at=naive)
    registry.register(preregistration)
    registry.advance("HYP-0006", HypothesisState.CALIBRATED)
    registry.record_evaluation("HYP-0006", EvaluationRecord(
        segment="TEST", statistic_value=0.9, p_value=0.001, effect_size=0.9,
        checks=(CheckResult(check_name=CheckName.OUT_OF_SAMPLE, verdict=CheckVerdict.PASS,
                            statistic_value=0.9, p_value=0.001, effect_size=0.9),),
    ))
    registry.adjudicate_family("FAM-SCOUT-NAIVE", q=0.1)
    assert registry.get("HYP-0006").state is HypothesisState.CANDIDATE
    verdict = _gate(good_candidate(sealed_hypothesis_id="HYP-0006"), registry)
    assert _step6(verdict) == ("HYPOTHESIS_PREREGISTERED_TIME_INVALID",)
    assert verdict.status is GateStatus.REJECTED


def test_r27_a_report_or_ledger_entry_with_a_naive_step_six_time_is_refused(registry):
    report = _pending_report(registry)
    payload = report.to_dict()
    payload["findings"][0]["gate"]["steps"][5]["evidence"]["preregistered_at"] = "2026-08-01T00:00:00"
    assert "preregistered_at is not a timestamp" in _report_problem(_resealed(payload))
    finding = report.findings[0]
    steps = list(finding.gate.steps)
    steps[5] = dataclasses.replace(steps[5], evidence={**steps[5].evidence, "preregistered_at": "2026-08-01T00:00:00"})
    forged = dataclasses.replace(finding, gate=dataclasses.replace(finding.gate, steps=tuple(steps)))
    with pytest.raises(ValueError, match="preregistered_at is not a timestamp"):
        dataclasses.replace(report, findings=(forged,))


def test_r27_a_registry_path_that_is_a_directory_at_gate_time_is_unreadable(tmp_path):
    path = tmp_path / "hypotheses.json"
    registry = HypothesisRegistry(registry_path=path)
    path.mkdir()
    assert _step6(_gate(good_candidate(), registry)) == ("REGISTRY_FILE_UNREADABLE",)


# -- review 28 ---------------------------------------------------------------------------------------


def test_r28_a_secondary_source_alone_blocks_an_otherwise_passing_red_team_finding(registry):
    """An ARTICLE source passes all seven gate steps; the red team alone must reject it."""
    article = good_candidate(source=_source(source_type="ARTICLE"))
    assert _gate(article, registry).status is GateStatus.PENDING_OWNER_REVIEW
    report = _scout(registry).run(_request(ScoutMode.RED_TEAM, candidates=[article])).to_dict()
    [finding] = report["findings"]
    assert finding["status"] == "REJECTED"
    assert finding["mode_flags"] == ["RED_TEAM:SECONDARY_OR_SOCIAL_SOURCE"]
    assert report["mode_analysis"]["failure_modes"]["cand-good"] == ["SECONDARY_OR_SOCIAL_SOURCE"]


def test_r28_a_ledger_entry_whose_as_of_is_not_a_timestamp_is_refused(registry):
    payload = _pending_report(registry).to_dict()
    payload["as_of"] = "2026-10-11T12:00:00"
    assert _report_problem(_resealed(payload)) == "PENDING_OWNER_REVIEW refused: the report as_of is not a timestamp"


@pytest.mark.parametrize("override, mode", [
    ({"security": {**good_candidate()["security"], "network_access": True}}, "EXECUTES_CODE_OR_REACHES_NETWORK"),
    ({"security": {**good_candidate()["security"], "known_vulnerabilities": 2}}, "KNOWN_VULNERABILITIES"),
    ({"removal_plan": None}, "NO_REMOVAL_PATH"),
])
def test_r28_a_each_remaining_red_team_mode_is_reported(registry, override, mode):
    report = _scout(registry).run(_request(ScoutMode.RED_TEAM, candidates=[good_candidate(**override)])).to_dict()
    [finding] = report["findings"]
    assert finding["status"] == "REJECTED"
    assert report["mode_analysis"]["failure_modes"]["cand-good"] == [mode]


def test_r28_a_ranking_puts_pending_findings_and_more_passed_steps_first(registry):
    # HYP-0001 is bound to cand-good, so the other two also fail step 6; ids sort against the expected order.
    candidates = [good_candidate(candidate_id="cand-a-weak", license_spdx=None),
                  good_candidate(candidate_id="cand-z-near"),
                  good_candidate()]
    report = _scout(registry).run(_request(ScoutMode.SEARCH, candidates=candidates)).to_dict()
    passed = {f["candidate_id"]: f["gate"]["passed_step_count"] for f in report["findings"]}
    assert passed == {"cand-a-weak": 5, "cand-z-near": 6, "cand-good": 7}
    assert report["mode_analysis"]["ranking"] == ["cand-good", "cand-z-near", "cand-a-weak"]


def test_r28_a_ranking_puts_a_pending_finding_before_a_rejected_one_with_every_step_passed(registry):
    # The red team rejects cand-good's ARTICLE source after all seven steps pass; cand-other (HYP-0004) stays pending.
    candidates = [good_candidate(source=_source(source_type="ARTICLE")),
                  good_candidate(candidate_id="cand-other", sealed_hypothesis_id="HYP-0004",
                                 source=_source(url="https://example.org/other"))]
    report = _scout(registry).run(_request(ScoutMode.RED_TEAM, candidates=candidates)).to_dict()
    outcome = {f["candidate_id"]: (f["status"], f["gate"]["passed_step_count"]) for f in report["findings"]}
    assert outcome == {"cand-good": ("REJECTED", 7), "cand-other": ("PENDING_OWNER_REVIEW", 7)}
    assert report["mode_analysis"]["ranking"] == ["cand-other", "cand-good"]


# -- review 29 ---------------------------------------------------------------------------------------

ONE_MICROSECOND = timedelta(microseconds=1)


@pytest.mark.parametrize("trades, rating", [
    (99, ReputationRating.INSUFFICIENT_EVIDENCE), (100, ReputationRating.RESEARCH_CANDIDATE)])
def test_r29_a_trade_count_boundary_is_exactly_the_policy_minimum(trades, rating):
    assessment = _assess(good_claim(trade_count=trades,
                                    execution_log=dict(good_claim()["execution_log"], record_count=trades)))
    assert assessment.rating is rating
    assert ("FEWER_THAN_100_TRADES" in assessment.reasons) is (trades == 99)


@pytest.mark.parametrize("overrides, reasons", [
    ({"source": _source(retrieved_at=AS_OF.isoformat())}, None),
    ({"source": _source(retrieved_at=(AS_OF + ONE_MICROSECOND).isoformat())}, ("SOURCE_RETRIEVED_AFTER_AS_OF",)),
    ({"last_activity_at": AS_OF.isoformat()}, None),
    ({"last_activity_at": (AS_OF + ONE_MICROSECOND).isoformat()}, ("LAST_ACTIVITY_IN_THE_FUTURE",)),
    ({"last_activity_at": (AS_OF - timedelta(days=365)).isoformat()}, None),
    ({"last_activity_at": (AS_OF - timedelta(days=365) - ONE_MICROSECOND).isoformat()},
     ("INACTIVE_MORE_THAN_365_DAYS",)),
])
def test_r29_a_source_reliability_boundaries_are_exact(registry, overrides, reasons):
    verdict = _gate(good_candidate(**overrides), registry)
    if reasons is None:
        assert verdict.status is GateStatus.PENDING_OWNER_REVIEW
    else:
        assert verdict.status is GateStatus.REJECTED
        assert _failed(verdict) == {GateStep.SOURCE_RELIABILITY: reasons}


def test_r29_a_licence_match_is_exact_and_case_sensitive(registry):
    verdict = _gate(good_candidate(license_spdx="mit"), registry)
    assert verdict.status is GateStatus.REJECTED
    assert _failed(verdict) == {GateStep.LICENSE_COMPLIANCE: ("LICENSE_NOT_ALLOWED:mit",)}


def test_r29_a_adjudicated_hypothesis_whose_stored_check_failed_never_passes_step_six(registry_path):
    # Check verdicts are not sealed (see unknowns_recorded_v5_95): a hand-edited file still loads.
    raw = json.loads(registry_path.read_text(encoding="utf-8"))
    [index] = [i for i, record in enumerate(raw["records"])
               if json.dumps(record).count('"hypothesis_id": "HYP-0001"')]
    edited = json.dumps(raw["records"][index]).replace('"verdict": "PASS"', '"verdict": "FAIL"')
    assert edited != json.dumps(raw["records"][index])
    raw["records"][index] = json.loads(edited)
    registry_path.write_text(json.dumps(raw), encoding="utf-8")
    registry = HypothesisRegistry(registry_path=registry_path)
    assert registry.get("HYP-0001").state is HypothesisState.CANDIDATE
    verdict = _gate(good_candidate(), registry)
    assert _step6(verdict) == ("HYPOTHESIS_CHECKS_NOT_COMPLETE_PASS",)
    assert verdict.status is GateStatus.REJECTED


def test_r29_a_ledger_refuses_a_pending_finding_with_input_errors_or_a_foreign_candidate(registry):
    payload = _pending_report(registry).to_dict()
    errored = json.loads(json.dumps(payload))
    errored["findings"][0]["input_errors"] = ["SOME_ERROR"]
    assert _report_problem(_resealed(errored)) == "a PENDING_OWNER_REVIEW finding carries flags or errors"
    foreign = json.loads(json.dumps(payload))
    foreign["findings"][0]["candidate"]["candidate_id"] = "cand-other"
    assert _report_problem(_resealed(foreign)) == "a PENDING_OWNER_REVIEW finding lacks its candidate"
