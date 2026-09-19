"""Contract tests for the pre-registration hypothesis registry."""

from __future__ import annotations

import json

import pytest

from research.hypothesis_registry import (
    CheckName,
    CheckPlan,
    CheckResult,
    CheckVerdict,
    DuplicateHypothesisError,
    EvaluationNotPermittedError,
    EvaluationRecord,
    FamilyAlreadyAdjudicatedError,
    FamilyNotReadyError,
    HypothesisRegistry,
    PreRegistration,
    RegistryError,
    SealVerificationError,
    UnknownHypothesisError,
)
from research.lifecycle import HypothesisState
from research.splitting import SplitSpec

SPLIT_SPEC = SplitSpec(
    train_fraction=0.6,
    calibration_fraction=0.2,
    test_fraction=0.2,
    label_horizon_bars=10,
    embargo_pct=0.01,
)

#: The minimal plan: the out-of-sample check alone, which is the single TEST
#: read every hypothesis performs anyway. Tests in this module exercise the
#: FDR, alpha and effect-size gates, so they pre-register the smallest plan
#: that keeps the check gate satisfied rather than a five-check one. The full
#: five-check plan is exercised in test_research_hypothesis_checks.py.
MINIMAL_CHECK_PLAN = CheckPlan(required_checks=(CheckName.OUT_OF_SAMPLE,))


def make_preregistration(**overrides) -> PreRegistration:
    params = {
        "hypothesis_id": "HYP-0001",
        "title": "Overnight reversal in majors",
        "description": "Large negative overnight moves partially revert.",
        "economic_rationale": (
            "Forced liquidation into thin overnight books pushes price beyond "
            "fair value; liquidity providers reclaim the spread at the open."
        ),
        "author": "research",
        "universe": ("BTCUSDT",),
        "timeframe": "1h",
        "data_start": "2024-01-01T00:00:00+00:00",
        "data_end": "2025-01-01T00:00:00+00:00",
        "entry_rule": "long when overnight return < -2 sigma",
        "exit_rule": "exit at next session close",
        "test_statistic": "mean_excess_return",
        "direction": "greater",
        "null_hypothesis": "mean excess return is zero",
        "alpha": 0.05,
        "minimum_effect_size": 0.5,
        "family_id": "FAM-REVERSAL-2026Q3",
        "split_spec": SPLIT_SPEC,
        "check_plan": MINIMAL_CHECK_PLAN,
        "feature_spec": {"lookback": 24, "sigma_window": 200},
        "preregistered_at": "2026-08-01T00:00:00+00:00",
    }
    params.update(overrides)
    return PreRegistration(**params)


@pytest.fixture
def registry(tmp_path) -> HypothesisRegistry:
    return HypothesisRegistry(registry_path=tmp_path / "registry" / "hypotheses.json")


def calibrate(registry: HypothesisRegistry, hypothesis_id: str) -> None:
    registry.advance(hypothesis_id, HypothesisState.CALIBRATED)


def run_test_segment(
    registry: HypothesisRegistry,
    hypothesis_id: str,
    *,
    p_value: float,
    effect_size: float,
) -> None:
    """Consume the single TEST read, satisfying the minimal check plan."""
    registry.record_evaluation(
        hypothesis_id,
        EvaluationRecord(
            segment="TEST",
            statistic_value=effect_size,
            p_value=p_value,
            effect_size=effect_size,
            checks=(
                CheckResult(
                    check_name=CheckName.OUT_OF_SAMPLE,
                    verdict=CheckVerdict.PASS,
                    statistic_value=effect_size,
                    p_value=p_value,
                    effect_size=effect_size,
                ),
            ),
        ),
    )


# --- pre-registration validation ----------------------------------------


@pytest.mark.parametrize("bad_id", ["HYP-1", "HYP-00001", "hyp-0001", "0001", ""])
def test_hypothesis_id_must_match_the_strict_slug(bad_id):
    with pytest.raises(RegistryError, match="hypothesis_id"):
        make_preregistration(hypothesis_id=bad_id)


def test_family_id_must_match_the_strict_slug():
    with pytest.raises(RegistryError, match="family_id"):
        make_preregistration(family_id="reversal")


def test_economic_rationale_is_required():
    """A hypothesis without a mechanism is data mining with extra steps."""
    with pytest.raises(RegistryError, match="economic_rationale"):
        make_preregistration(economic_rationale="   ")


@pytest.mark.parametrize("alpha", [0.0, 1.0, -0.1, 1.5])
def test_alpha_must_lie_strictly_inside_the_unit_interval(alpha):
    with pytest.raises(RegistryError, match="alpha"):
        make_preregistration(alpha=alpha)


def test_minimum_effect_size_must_not_be_negative():
    with pytest.raises(RegistryError, match="minimum_effect_size"):
        make_preregistration(minimum_effect_size=-0.1)


def test_direction_must_be_pre_committed_to_a_known_value():
    with pytest.raises(RegistryError, match="direction"):
        make_preregistration(direction="whichever_wins")


@pytest.mark.parametrize(
    "universe", [(), ("btcusdt",), ("BTC/USDT",), ("BTCUSDT", "BTCUSDT")]
)
def test_universe_is_validated(universe):
    with pytest.raises(RegistryError):
        make_preregistration(universe=universe)


def test_data_window_must_be_ordered():
    with pytest.raises(RegistryError, match="strictly before"):
        make_preregistration(
            data_start="2025-01-01T00:00:00+00:00",
            data_end="2024-01-01T00:00:00+00:00",
        )


def test_data_window_must_be_iso_timestamps():
    with pytest.raises(RegistryError, match="ISO-8601"):
        make_preregistration(data_start="last january")


def test_universe_is_normalised_to_a_tuple():
    prereg = make_preregistration(universe=["BTCUSDT", "ETHUSDT"])
    assert prereg.universe == ("BTCUSDT", "ETHUSDT")


# --- the seal ------------------------------------------------------------


def test_seal_is_stable_across_identical_content():
    assert make_preregistration().seal_hash() == make_preregistration().seal_hash()


@pytest.mark.parametrize(
    "field,value",
    [
        ("direction", "less"),
        ("alpha", 0.01),
        ("minimum_effect_size", 0.1),
        ("test_statistic", "sharpe_ratio"),
        ("universe", ("ETHUSDT",)),
        ("data_end", "2025-06-01T00:00:00+00:00"),
        ("economic_rationale", "a different mechanism entirely"),
        ("feature_spec", {"lookback": 48}),
        (
            "check_plan",
            CheckPlan(
                required_checks=(
                    CheckName.OUT_OF_SAMPLE,
                    CheckName.COST_ADJUSTED,
                ),
                parameters={
                    "COST_ADJUSTED": {
                        "cost_model_id": "taker_flat",
                        "cost_bps": 7.5,
                    }
                },
            ),
        ),
    ],
)
def test_changing_any_sealed_field_changes_the_seal(field, value):
    baseline = make_preregistration().seal_hash()
    assert make_preregistration(**{field: value}).seal_hash() != baseline


def test_seal_survives_a_reordered_feature_spec():
    """The seal is over canonical JSON, so key order must not matter."""
    first = make_preregistration(feature_spec={"a": 1, "b": 2}).seal_hash()
    second = make_preregistration(feature_spec={"b": 2, "a": 1}).seal_hash()
    assert first == second


def test_registry_rejects_a_hand_edited_file(tmp_path):
    """The whole point of the seal: post-hoc edits are detectable."""
    path = tmp_path / "hypotheses.json"
    registry = HypothesisRegistry(registry_path=path)
    registry.register(make_preregistration())

    payload = json.loads(path.read_text(encoding="utf-8"))
    # Flip the pre-committed direction after the fact, the classic HARK.
    payload["records"][0]["preregistration"]["direction"] = "less"
    path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(SealVerificationError, match="seal mismatch"):
        HypothesisRegistry(registry_path=path)


# --- registration --------------------------------------------------------


def test_registration_seals_and_stores_in_the_registered_state(registry):
    prereg = make_preregistration()
    record = registry.register(prereg)
    assert record.state is HypothesisState.REGISTERED
    assert record.preregistration_hash == prereg.seal_hash()
    assert record.evaluations == ()
    record.verify_seal()


def test_a_hypothesis_id_cannot_be_reused(registry):
    registry.register(make_preregistration())
    with pytest.raises(DuplicateHypothesisError, match="new id"):
        registry.register(make_preregistration(title="a revised idea"))


def test_registry_path_is_required():
    with pytest.raises(RegistryError, match="registry_path is required"):
        HypothesisRegistry(registry_path="   ")


def test_records_survive_a_reload(tmp_path):
    path = tmp_path / "hypotheses.json"
    first = HypothesisRegistry(registry_path=path)
    first.register(make_preregistration())
    first.register(make_preregistration(hypothesis_id="HYP-0002"))

    second = HypothesisRegistry(registry_path=path)
    assert len(second) == 2
    assert "HYP-0001" in second
    assert second.get("HYP-0002").state is HypothesisState.REGISTERED


def test_registry_writes_only_to_the_path_it_was_given(tmp_path):
    path = tmp_path / "nested" / "hypotheses.json"
    registry = HypothesisRegistry(registry_path=path)
    registry.register(make_preregistration())
    written = {p for p in tmp_path.rglob("*") if p.is_file()}
    assert written == {path}


def test_unknown_hypothesis_is_reported(registry):
    with pytest.raises(UnknownHypothesisError, match="HYP-9999"):
        registry.get("HYP-9999")


def test_unsupported_format_version_is_refused(tmp_path):
    path = tmp_path / "hypotheses.json"
    path.write_text(json.dumps({"version": 99, "records": []}), encoding="utf-8")
    with pytest.raises(RegistryError, match="unsupported registry format"):
        HypothesisRegistry(registry_path=path)


def test_a_format_version_1_registry_is_refused(tmp_path):
    """The version-1 boundary is closed on purpose, not by omission.

    No version-1 registry exists anywhere, so there is no migration path to
    write. This test pins the resulting behaviour: a version-1 payload -- a
    pre-registration with no sealed check plan -- fails to load with a
    version-mismatch error rather than being loaded with an empty plan that
    would satisfy the check gate vacuously.
    """
    path = tmp_path / "hypotheses.json"
    version_1_preregistration = make_preregistration().sealed_payload()
    version_1_preregistration.pop("check_plan")
    path.write_text(
        json.dumps(
            {
                "version": 1,
                "records": [
                    {
                        "preregistration": version_1_preregistration,
                        "preregistration_hash": "0" * 64,
                        "state": "REGISTERED",
                        "evaluations": [],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(RegistryError, match="unsupported registry format") as exc:
        HypothesisRegistry(registry_path=path)
    assert "expected 2" in str(exc.value)


# --- evaluation access rules --------------------------------------------


def test_train_and_calibration_segments_have_unlimited_access(registry):
    registry.register(make_preregistration())
    for _ in range(3):
        registry.record_evaluation(
            "HYP-0001", EvaluationRecord(segment="TRAIN", statistic_value=0.4)
        )
        registry.record_evaluation(
            "HYP-0001", EvaluationRecord(segment="CALIBRATION", statistic_value=0.3)
        )
    record = registry.get("HYP-0001")
    assert len(record.evaluations) == 6
    assert record.state is HypothesisState.REGISTERED


def test_test_segment_cannot_be_read_before_calibration(registry):
    registry.register(make_preregistration())
    with pytest.raises(EvaluationNotPermittedError, match="permitted only from"):
        run_test_segment(registry, "HYP-0001", p_value=0.01, effect_size=0.9)


def test_reading_the_test_segment_advances_the_hypothesis(registry):
    registry.register(make_preregistration())
    calibrate(registry, "HYP-0001")
    run_test_segment(registry, "HYP-0001", p_value=0.01, effect_size=0.9)

    record = registry.get("HYP-0001")
    assert record.state is HypothesisState.TESTED
    assert record.test_evaluation is not None
    assert record.test_evaluation.p_value == 0.01


def test_the_test_segment_can_only_ever_be_read_once(registry):
    registry.register(make_preregistration())
    calibrate(registry, "HYP-0001")
    run_test_segment(registry, "HYP-0001", p_value=0.4, effect_size=0.1)

    with pytest.raises(EvaluationNotPermittedError):
        run_test_segment(registry, "HYP-0001", p_value=0.01, effect_size=0.9)


def test_a_tested_hypothesis_cannot_be_returned_to_calibration(registry):
    registry.register(make_preregistration())
    calibrate(registry, "HYP-0001")
    run_test_segment(registry, "HYP-0001", p_value=0.4, effect_size=0.1)

    with pytest.raises(Exception, match="illegal transition"):
        registry.advance("HYP-0001", HypothesisState.CALIBRATED)


def test_a_test_evaluation_must_carry_a_p_value_and_effect_size():
    with pytest.raises(RegistryError, match="p_value"):
        EvaluationRecord(segment="TEST", statistic_value=0.5, effect_size=0.5)
    with pytest.raises(RegistryError, match="effect_size"):
        EvaluationRecord(segment="TEST", statistic_value=0.5, p_value=0.01)


def test_evaluations_are_append_only_and_ordered(registry):
    registry.register(make_preregistration())
    registry.record_evaluation(
        "HYP-0001", EvaluationRecord(segment="TRAIN", statistic_value=1.0)
    )
    registry.record_evaluation(
        "HYP-0001", EvaluationRecord(segment="TRAIN", statistic_value=2.0)
    )
    values = [e.statistic_value for e in registry.get("HYP-0001").evaluations]
    assert values == [1.0, 2.0]


def test_evaluation_segment_must_be_known():
    with pytest.raises(RegistryError, match="segment"):
        EvaluationRecord(segment="VALIDATION", statistic_value=1.0)


def test_p_value_bounds_are_enforced_on_evaluations():
    with pytest.raises(RegistryError, match="p_value"):
        EvaluationRecord(segment="TRAIN", statistic_value=1.0, p_value=1.4)


# --- family adjudication -------------------------------------------------


def register_and_test(
    registry: HypothesisRegistry,
    hypothesis_id: str,
    *,
    p_value: float,
    effect_size: float,
    alpha: float = 0.05,
    minimum_effect_size: float = 0.5,
) -> None:
    registry.register(
        make_preregistration(
            hypothesis_id=hypothesis_id,
            alpha=alpha,
            minimum_effect_size=minimum_effect_size,
        )
    )
    calibrate(registry, hypothesis_id)
    run_test_segment(
        registry, hypothesis_id, p_value=p_value, effect_size=effect_size
    )


def test_adjudication_applies_all_three_gates(registry):
    register_and_test(registry, "HYP-0001", p_value=0.001, effect_size=0.9)
    register_and_test(
        registry, "HYP-0002", p_value=0.020, effect_size=0.9, alpha=0.01
    )
    register_and_test(registry, "HYP-0003", p_value=0.001, effect_size=0.1)
    register_and_test(registry, "HYP-0004", p_value=0.900, effect_size=0.9)

    decision = registry.adjudicate_family("FAM-REVERSAL-2026Q3", q=0.1)

    assert decision.n_tests == 4
    assert decision.n_rejected == 3  # BH discoveries, before the other gates

    # Clears FDR, its own alpha, and the minimum effect size.
    assert registry.get("HYP-0001").state is HypothesisState.CANDIDATE
    # Clears FDR but not its own pre-registered alpha.
    assert registry.get("HYP-0002").state is HypothesisState.REJECTED
    # Clears FDR and alpha but is economically meaningless.
    assert registry.get("HYP-0003").state is HypothesisState.REJECTED
    # Fails FDR outright.
    assert registry.get("HYP-0004").state is HypothesisState.REJECTED


def test_adjudication_refuses_while_a_family_member_is_untested(registry):
    register_and_test(registry, "HYP-0001", p_value=0.001, effect_size=0.9)
    registry.register(make_preregistration(hypothesis_id="HYP-0002"))

    with pytest.raises(FamilyNotReadyError, match="understate the family size"):
        registry.adjudicate_family("FAM-REVERSAL-2026Q3", q=0.1)


def test_adjudication_happens_once_per_family(registry):
    register_and_test(registry, "HYP-0001", p_value=0.001, effect_size=0.9)
    registry.adjudicate_family("FAM-REVERSAL-2026Q3", q=0.1)

    with pytest.raises(FamilyAlreadyAdjudicatedError, match="already been adjudicated"):
        registry.adjudicate_family("FAM-REVERSAL-2026Q3", q=0.1)


def test_hypotheses_rejected_before_testing_do_not_inflate_the_family(registry):
    """They produced no p-value, so they are not one of the m tests."""
    register_and_test(registry, "HYP-0001", p_value=0.001, effect_size=0.9)
    registry.register(make_preregistration(hypothesis_id="HYP-0002"))
    registry.advance("HYP-0002", HypothesisState.REJECTED)

    decision = registry.adjudicate_family("FAM-REVERSAL-2026Q3", q=0.1)
    assert decision.n_tests == 1
    assert len(registry.family("FAM-REVERSAL-2026Q3")) == 2


def test_family_listing_includes_failures(registry):
    register_and_test(registry, "HYP-0001", p_value=0.001, effect_size=0.9)
    register_and_test(registry, "HYP-0002", p_value=0.900, effect_size=0.1)
    registry.adjudicate_family("FAM-REVERSAL-2026Q3", q=0.1)

    family = registry.family("FAM-REVERSAL-2026Q3")
    states = {r.hypothesis_id: r.state for r in family}
    assert states["HYP-0002"] is HypothesisState.REJECTED
    assert len(family) == 2


def test_adjudicating_an_unknown_family_is_an_error(registry):
    with pytest.raises(UnknownHypothesisError, match="FAM-NOTHING"):
        registry.adjudicate_family("FAM-NOTHING", q=0.1)


def test_a_promoted_candidate_can_enter_paper_validation(registry):
    register_and_test(registry, "HYP-0001", p_value=0.001, effect_size=0.9)
    registry.adjudicate_family("FAM-REVERSAL-2026Q3", q=0.1)

    registry.advance("HYP-0001", HypothesisState.PAPER_VALIDATING)
    registry.advance("HYP-0001", HypothesisState.VALIDATED)
    assert registry.get("HYP-0001").state is HypothesisState.VALIDATED


def test_adjudication_result_persists_across_a_reload(tmp_path):
    path = tmp_path / "hypotheses.json"
    registry = HypothesisRegistry(registry_path=path)
    register_and_test(registry, "HYP-0001", p_value=0.001, effect_size=0.9)
    registry.adjudicate_family("FAM-REVERSAL-2026Q3", q=0.1)

    reloaded = HypothesisRegistry(registry_path=path)
    record = reloaded.get("HYP-0001")
    assert record.state is HypothesisState.CANDIDATE
    assert record.test_evaluation is not None
    record.verify_seal()
