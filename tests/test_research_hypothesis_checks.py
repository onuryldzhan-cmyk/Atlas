"""Contract tests for the five-check validation protocol.

These cover the sealed ``check_plan``, the conjunctive promotion gate, and the
two regression guards the project contract names:

* **NB-4 analogue** -- removing evidence must never make the system less
  conservative. A required check with no recorded result adjudicates as a
  failure, so deleting a result can only move a hypothesis away from
  promotion, never towards it.
* **NB-5 analogue** -- "how many checks passed" is always scored against the
  sealed plan's required-check count, never against however many results
  happen to be present, so a half-run plan can never read as unanimous.

They also pin the one ordering property the statistics depend on:
Benjamini-Hochberg runs over the whole tested family before any check verdict
is consulted, so ``m`` is the true number of tests.

Check results are constructed here as plain data. Computing them is a
separate concern that lives outside this module by design.
"""

from __future__ import annotations

import itertools
import json
from dataclasses import replace

import pytest

from research.hypothesis_registry import (
    REGISTRY_FORMAT_VERSION,
    CheckName,
    CheckPlan,
    CheckPlanStatus,
    CheckResult,
    CheckVerdict,
    DuplicateCheckError,
    EvaluationNotPermittedError,
    EvaluationRecord,
    FamilyAdjudicationRequiredError,
    HypothesisRecord,
    HypothesisRegistry,
    PreRegistration,
    RegistryError,
    SealVerificationError,
    ThresholdBindingError,
    UnplannedCheckError,
)
from research.lifecycle import HypothesisState
from tests.test_research_hypothesis_registry import make_preregistration

FAMILY_ID = "FAM-REVERSAL-2026Q3"

#: The owner's full protocol: all five checks, each with its parameters
#: committed before any data is read.
FULL_CHECK_PLAN = CheckPlan(
    required_checks=(
        CheckName.BACKTEST,
        CheckName.WALK_FORWARD,
        CheckName.OUT_OF_SAMPLE,
        CheckName.COST_ADJUSTED,
        CheckName.MONTE_CARLO,
    ),
    parameters={
        "BACKTEST": {"minimum_effect_size": 0.5},
        "WALK_FORWARD": {"window_count": 6, "minimum_fraction_passing": 0.6},
        "COST_ADJUSTED": {"cost_model_id": "taker_flat", "cost_bps": 7.5},
        "MONTE_CARLO": {
            "trial_count": 2000,
            "null_model_id": "stationary_bootstrap",
            "percentile_threshold": 95.0,
        },
    },
)

#: The three checks scored against the single TEST read.
TEST_SEGMENT_CHECKS = (
    CheckName.OUT_OF_SAMPLE,
    CheckName.COST_ADJUSTED,
    CheckName.MONTE_CARLO,
)

PASS = CheckVerdict.PASS
FAIL = CheckVerdict.FAIL

#: Every subset of the five checks, used to exercise the NB-4 property over
#: all possible removals of evidence rather than a chosen few.
EVERY_SUBSET_OF_CHECKS = [
    subset
    for size in range(len(CheckName) + 1)
    for subset in itertools.combinations(list(CheckName), size)
]


@pytest.fixture
def registry(tmp_path) -> HypothesisRegistry:
    return HypothesisRegistry(registry_path=tmp_path / "hypotheses.json")


# --- helpers -------------------------------------------------------------


def full_preregistration(hypothesis_id: str = "HYP-0001", **overrides):
    overrides.setdefault("check_plan", FULL_CHECK_PLAN)
    return make_preregistration(hypothesis_id=hypothesis_id, **overrides)


#: Sentinel meaning "use the threshold the plan sealed", so a test can pass
#: ``threshold_applied=None`` explicitly and mean it.
_SEALED = object()


def make_check(
    check_name: CheckName,
    verdict: CheckVerdict = PASS,
    *,
    plan: CheckPlan | None = None,
    threshold_applied=_SEALED,
) -> CheckResult:
    """A check result scored, by default, against its sealed threshold.

    The default is the sealed number because that is the only threshold
    ``record_evaluation`` accepts; a test that wants to prove the binding
    bites passes a different one deliberately.
    """
    plan = FULL_CHECK_PLAN if plan is None else plan
    if threshold_applied is _SEALED:
        threshold_applied = plan.threshold_for(check_name)
    return CheckResult(
        check_name=check_name,
        verdict=verdict,
        statistic_value=0.8,
        p_value=0.01,
        effect_size=0.8,
        threshold_applied=threshold_applied,
        payload={"engine": "package-d-placeholder"},
    )


def record_backtest(registry, hypothesis_id, verdict=PASS) -> None:
    registry.record_evaluation(
        hypothesis_id,
        EvaluationRecord(
            segment="TRAIN",
            statistic_value=0.8,
            checks=(make_check(CheckName.BACKTEST, verdict),),
        ),
    )


def record_walk_forward(registry, hypothesis_id, verdict=PASS) -> None:
    registry.record_evaluation(
        hypothesis_id,
        EvaluationRecord(
            segment="CALIBRATION",
            statistic_value=0.7,
            checks=(make_check(CheckName.WALK_FORWARD, verdict),),
        ),
    )


def record_test_read(
    registry,
    hypothesis_id,
    *,
    p_value: float,
    effect_size: float,
    test_checks=TEST_SEGMENT_CHECKS,
    verdicts=None,
) -> None:
    """Consume the single TEST read, carrying its check results with it."""
    verdicts = verdicts or {}
    registry.record_evaluation(
        hypothesis_id,
        EvaluationRecord(
            segment="TEST",
            statistic_value=effect_size,
            p_value=p_value,
            effect_size=effect_size,
            checks=tuple(
                make_check(name, verdicts.get(name, PASS)) for name in test_checks
            ),
        ),
    )


def run_full_protocol(
    registry,
    hypothesis_id: str,
    *,
    p_value: float = 0.001,
    effect_size: float = 0.9,
    omit: tuple[CheckName, ...] = (),
    verdicts: dict | None = None,
    **prereg_overrides,
) -> None:
    """Register a hypothesis and run its whole five-check protocol.

    ``omit`` leaves a required check unrecorded; ``verdicts`` overrides
    individual outcomes. Both leave the *plan* untouched -- the plan is
    sealed, so only the recorded evidence can vary.
    """
    verdicts = verdicts or {}
    registry.register(full_preregistration(hypothesis_id, **prereg_overrides))
    if CheckName.BACKTEST not in omit:
        record_backtest(registry, hypothesis_id, verdicts.get(CheckName.BACKTEST, PASS))
    if CheckName.WALK_FORWARD not in omit:
        record_walk_forward(
            registry, hypothesis_id, verdicts.get(CheckName.WALK_FORWARD, PASS)
        )
    registry.advance(hypothesis_id, HypothesisState.CALIBRATED)
    record_test_read(
        registry,
        hypothesis_id,
        p_value=p_value,
        effect_size=effect_size,
        test_checks=tuple(n for n in TEST_SEGMENT_CHECKS if n not in omit),
        verdicts=verdicts,
    )


def retaining_only(record: HypothesisRecord, keep) -> HypothesisRecord:
    """A copy of ``record`` whose recorded checks are restricted to ``keep``.

    Used to simulate evidence being removed. The sealed plan is untouched,
    which is the whole point: the plan is what the removal is scored against.
    """
    keep = frozenset(keep)
    return replace(
        record,
        evaluations=tuple(
            replace(
                evaluation,
                checks=tuple(
                    check
                    for check in evaluation.checks
                    if check.check_name in keep
                ),
            )
            for evaluation in record.evaluations
        ),
    )


# --- the closed data model ----------------------------------------------


def test_the_five_checks_are_exactly_the_owners_five():
    assert [check.value for check in CheckName] == [
        "BACKTEST",
        "WALK_FORWARD",
        "OUT_OF_SAMPLE",
        "COST_ADJUSTED",
        "MONTE_CARLO",
    ]


def test_a_check_verdict_has_no_third_value():
    """No INCONCLUSIVE: a check that could not be computed is simply absent,
    and an absent required check already adjudicates as a failure."""
    assert [verdict.value for verdict in CheckVerdict] == ["PASS", "FAIL"]


def test_the_lifecycle_gained_no_state_for_check_progress():
    """Check progress is data on the existing evaluations, not new states.

    The state machine's discipline -- ten states, monotone, with no LIVE,
    PRODUCTION or DEPLOYED state -- is load-bearing, and representing "which
    checks have run" needed nothing added to it.
    """
    assert len(HypothesisState) == 10
    assert not {"LIVE", "PRODUCTION", "DEPLOYED"} & {
        state.value for state in HypothesisState
    }


@pytest.mark.parametrize(
    "check_name,segment",
    [
        (CheckName.BACKTEST, "TRAIN"),
        (CheckName.WALK_FORWARD, "CALIBRATION"),
        (CheckName.OUT_OF_SAMPLE, "TEST"),
        (CheckName.COST_ADJUSTED, "TEST"),
        (CheckName.MONTE_CARLO, "TEST"),
    ],
)
def test_each_check_is_bound_to_one_segment(check_name, segment):
    assert make_check(check_name).segment == segment


def test_a_check_cannot_be_attached_to_the_wrong_segment():
    with pytest.raises(RegistryError, match="cannot be attached"):
        EvaluationRecord(
            segment="TEST",
            statistic_value=0.5,
            p_value=0.01,
            effect_size=0.5,
            checks=(make_check(CheckName.BACKTEST),),
        )


@pytest.mark.parametrize("p_value", [-0.1, 1.4])
def test_check_result_p_value_bounds_are_enforced(p_value):
    with pytest.raises(RegistryError, match="p_value"):
        CheckResult(
            check_name=CheckName.BACKTEST,
            verdict=PASS,
            statistic_value=0.5,
            p_value=p_value,
        )


def test_check_result_rejects_an_unknown_check_name():
    with pytest.raises(RegistryError, match="check_name"):
        CheckResult(check_name="SNIFF_TEST", verdict=PASS, statistic_value=0.5)


def test_check_result_rejects_an_unknown_verdict():
    with pytest.raises(RegistryError, match="verdict"):
        CheckResult(
            check_name=CheckName.BACKTEST, verdict="MAYBE", statistic_value=0.5
        )


def test_check_result_survives_a_round_trip():
    original = make_check(CheckName.MONTE_CARLO, FAIL)
    assert CheckResult.from_dict(original.as_dict()) == original


# --- the sealed check plan ----------------------------------------------


def test_an_empty_check_plan_is_refused():
    """An empty plan would make the check gate vacuously true."""
    with pytest.raises(RegistryError, match="at least one check"):
        CheckPlan(required_checks=())


def test_a_check_cannot_be_required_twice():
    with pytest.raises(RegistryError, match="same check twice"):
        CheckPlan(
            required_checks=(CheckName.OUT_OF_SAMPLE, CheckName.OUT_OF_SAMPLE)
        )


def test_a_required_check_must_pre_register_its_parameters():
    with pytest.raises(RegistryError, match="missing parameters"):
        CheckPlan(required_checks=(CheckName.MONTE_CARLO,))


def test_a_check_plan_refuses_unknown_parameters():
    with pytest.raises(RegistryError, match="unknown parameters"):
        CheckPlan(
            required_checks=(CheckName.COST_ADJUSTED,),
            parameters={
                "COST_ADJUSTED": {
                    "cost_model_id": "taker_flat",
                    "cost_bps": 7.5,
                    "fudge_factor": 0.5,
                }
            },
        )


def test_a_check_plan_refuses_parameters_for_checks_it_does_not_require():
    with pytest.raises(RegistryError, match="does not require"):
        CheckPlan(
            required_checks=(CheckName.OUT_OF_SAMPLE,),
            parameters={"MONTE_CARLO": {"trial_count": 10}},
        )


@pytest.mark.parametrize(
    "parameters",
    [
        {"trial_count": 0, "null_model_id": "x", "percentile_threshold": 95.0},
        {"trial_count": 10, "null_model_id": "  ", "percentile_threshold": 95.0},
        {"trial_count": 10, "null_model_id": "x", "percentile_threshold": 100.0},
        {"trial_count": 10, "null_model_id": "x", "percentile_threshold": 0.0},
        {"trial_count": 1.5, "null_model_id": "x", "percentile_threshold": 95.0},
    ],
)
def test_check_plan_parameter_values_are_validated(parameters):
    with pytest.raises(RegistryError, match="MONTE_CARLO check parameter"):
        CheckPlan(
            required_checks=(CheckName.MONTE_CARLO,),
            parameters={"MONTE_CARLO": parameters},
        )


def test_walk_forward_fraction_must_lie_in_the_unit_interval():
    with pytest.raises(RegistryError, match="minimum_fraction_passing"):
        CheckPlan(
            required_checks=(CheckName.WALK_FORWARD,),
            parameters={
                "WALK_FORWARD": {
                    "window_count": 6,
                    "minimum_fraction_passing": 1.5,
                }
            },
        )


def test_an_opaque_model_identifier_is_preserved_byte_exact():
    plan = CheckPlan(
        required_checks=(CheckName.COST_ADJUSTED,),
        parameters={
            "COST_ADJUSTED": {"cost_model_id": " Taker-Flat_v2 ", "cost_bps": 7.5}
        },
    )
    assert plan.parameters_for(CheckName.COST_ADJUSTED)["cost_model_id"] == (
        " Taker-Flat_v2 "
    )


def test_plan_order_does_not_change_the_seal():
    """Two plans requiring the same checks must seal identically."""
    forwards = make_preregistration(
        check_plan=CheckPlan(
            required_checks=(CheckName.BACKTEST, CheckName.OUT_OF_SAMPLE),
            parameters={"BACKTEST": {"minimum_effect_size": 0.5}},
        )
    )
    backwards = make_preregistration(
        check_plan=CheckPlan(
            required_checks=(CheckName.OUT_OF_SAMPLE, CheckName.BACKTEST),
            parameters={"BACKTEST": {"minimum_effect_size": 0.5}},
        )
    )
    assert forwards.seal_hash() == backwards.seal_hash()


def test_an_integer_parameter_seals_the_same_as_its_float_spelling():
    """Canonical JSON distinguishes 6 from 6.0, so coercion must settle it."""
    integral = CheckPlan(
        required_checks=(CheckName.WALK_FORWARD,),
        parameters={
            "WALK_FORWARD": {"window_count": 6, "minimum_fraction_passing": 1}
        },
    )
    fractional = CheckPlan(
        required_checks=(CheckName.WALK_FORWARD,),
        parameters={
            "WALK_FORWARD": {"window_count": 6, "minimum_fraction_passing": 1.0}
        },
    )
    assert json.dumps(integral.as_dict(), sort_keys=True) == json.dumps(
        fractional.as_dict(), sort_keys=True
    )


def test_the_check_plan_is_part_of_the_seal():
    baseline = make_preregistration().seal_hash()
    assert make_preregistration(check_plan=FULL_CHECK_PLAN).seal_hash() != baseline


def test_a_pre_registration_requires_a_check_plan():
    payload = make_preregistration().sealed_payload()
    payload.pop("check_plan")
    with pytest.raises(RegistryError, match="missing field 'check_plan'"):
        PreRegistration.from_dict(payload)


# --- test 18: tampering with the sealed plan ----------------------------


def _stored(path):
    return json.loads(path.read_text(encoding="utf-8"))


def _rewrite(path, payload):
    path.write_text(json.dumps(payload), encoding="utf-8")


def _tamper(path, registered_plan, mutate):
    """Register under ``registered_plan``, then edit the stored plan on disk."""
    registry = HypothesisRegistry(registry_path=path)
    registry.register(full_preregistration(check_plan=registered_plan))

    payload = _stored(path)
    mutate(payload["records"][0]["preregistration"]["check_plan"])
    _rewrite(path, payload)


#: The full plan minus MONTE_CARLO, so that *adding* a check is expressible
#: as a tamper.
FOUR_CHECK_PLAN = CheckPlan(
    required_checks=tuple(
        check for check in FULL_CHECK_PLAN.required_checks
        if check is not CheckName.MONTE_CARLO
    ),
    parameters={
        name: values
        for name, values in FULL_CHECK_PLAN.parameters.items()
        if name != CheckName.MONTE_CARLO.value
    },
)


def _drop_monte_carlo(plan):
    plan["required_checks"].remove("MONTE_CARLO")
    plan["parameters"].pop("MONTE_CARLO")


def _add_monte_carlo(plan):
    plan["required_checks"].append("MONTE_CARLO")
    plan["parameters"]["MONTE_CARLO"] = {
        "trial_count": 10,
        "null_model_id": "whatever",
        "percentile_threshold": 50.0,
    }


@pytest.mark.parametrize(
    "registered_plan,mutate",
    [
        pytest.param(
            FULL_CHECK_PLAN, _drop_monte_carlo, id="drop-a-required-check"
        ),
        pytest.param(
            FOUR_CHECK_PLAN, _add_monte_carlo, id="add-a-required-check"
        ),
        pytest.param(
            FULL_CHECK_PLAN,
            lambda plan: plan["parameters"]["MONTE_CARLO"].update(
                {"percentile_threshold": 50.0}
            ),
            id="loosen-a-threshold",
        ),
        pytest.param(
            FULL_CHECK_PLAN,
            lambda plan: plan["parameters"]["COST_ADJUSTED"].update(
                {"cost_bps": 0.0}
            ),
            id="zero-the-cost-model",
        ),
        pytest.param(
            FULL_CHECK_PLAN,
            lambda plan: plan["parameters"]["COST_ADJUSTED"].update(
                {"cost_model_id": "free_lunch"}
            ),
            id="swap-the-cost-model",
        ),
    ],
)
def test_editing_the_sealed_check_plan_is_detected(
    tmp_path, registered_plan, mutate
):
    """The v2 seal covers the plan, so post-hoc protocol edits are visible.

    Every edit here leaves the plan internally valid, so nothing but the seal
    can catch it. Dropping MONTE_CARLO once it fails is the check-level HARK
    this seal exists to catch, and it must be no more possible than flipping
    ``direction`` was under version 1.
    """
    path = tmp_path / "hypotheses.json"
    _tamper(path, registered_plan, mutate)

    with pytest.raises(SealVerificationError, match="seal mismatch"):
        HypothesisRegistry(registry_path=path)


@pytest.mark.parametrize(
    "mutate",
    [
        pytest.param(
            lambda plan: plan["required_checks"].remove("MONTE_CARLO"),
            id="check-dropped-but-parameters-left",
        ),
        pytest.param(
            lambda plan: plan["parameters"].pop("MONTE_CARLO"),
            id="parameters-dropped-but-check-left",
        ),
        pytest.param(
            lambda plan: plan["required_checks"].clear(), id="plan-emptied"
        ),
    ],
)
def test_a_structurally_broken_check_plan_is_refused_on_load(tmp_path, mutate):
    """A half-finished edit is refused by the plan's own validation.

    It never reaches the seal check, so this pins the other half of the
    fail-closed boundary: an inconsistent stored plan is an error, never a
    plan quietly repaired into something loadable.
    """
    path = tmp_path / "hypotheses.json"
    _tamper(path, FULL_CHECK_PLAN, mutate)

    with pytest.raises(RegistryError):
        HypothesisRegistry(registry_path=path)


def test_the_registry_writes_the_version_2_format(tmp_path):
    path = tmp_path / "hypotheses.json"
    registry = HypothesisRegistry(registry_path=path)
    registry.register(full_preregistration())
    assert _stored(path)["version"] == REGISTRY_FORMAT_VERSION == 2


def test_checks_survive_a_reload(tmp_path):
    path = tmp_path / "hypotheses.json"
    registry = HypothesisRegistry(registry_path=path)
    run_full_protocol(registry, "HYP-0001")

    reloaded = HypothesisRegistry(registry_path=path)
    record = reloaded.get("HYP-0001")
    record.verify_seal()
    adjudication = record.adjudicate_checks()
    assert adjudication.status is CheckPlanStatus.COMPLETE_PASS
    assert adjudication.required_check_count == 5
    assert {check.check_name for check in record.check_results()} == set(CheckName)


# --- test 15: the three TEST checks are still one read ------------------


def test_the_three_test_checks_ride_on_a_single_test_read(registry):
    """COST_ADJUSTED re-scores the read and MONTE_CARLO resamples it.

    Neither is a second look at the test segment, so neither may consume the
    single-read budget a second time.
    """
    run_full_protocol(registry, "HYP-0001")
    record = registry.get("HYP-0001")

    test_evaluations = [e for e in record.evaluations if e.segment == "TEST"]
    assert len(test_evaluations) == 1
    assert len(test_evaluations[0].checks) == 3
    assert record.state is HypothesisState.TESTED
    assert record.adjudicate_checks().status is CheckPlanStatus.COMPLETE_PASS


def test_a_second_test_read_is_still_refused_after_the_checks(registry):
    """The state guard refuses it: the hypothesis has left CALIBRATED and the
    machine is monotone, so CALIBRATED is unreachable again. The
    already-consumed guard behind it is defence in depth and is not reachable
    through any public path."""
    run_full_protocol(registry, "HYP-0001")
    with pytest.raises(
        EvaluationNotPermittedError, match="permitted only from"
    ):
        record_test_read(
            registry, "HYP-0001", p_value=0.001, effect_size=0.9, test_checks=()
        )


# --- test 14: an unplanned check is refused -----------------------------


def test_recording_a_check_outside_the_sealed_plan_raises(registry):
    """The plan is the protocol. A check added later was not committed to."""
    registry.register(make_preregistration())  # minimal plan: OUT_OF_SAMPLE
    registry.advance("HYP-0001", HypothesisState.CALIBRATED)

    with pytest.raises(UnplannedCheckError, match="did not pre-register"):
        record_test_read(
            registry,
            "HYP-0001",
            p_value=0.001,
            effect_size=0.9,
            test_checks=(CheckName.OUT_OF_SAMPLE, CheckName.MONTE_CARLO),
        )


def test_an_unplanned_check_leaves_the_record_untouched(registry):
    registry.register(make_preregistration())
    with pytest.raises(UnplannedCheckError):
        record_backtest(registry, "HYP-0001")

    record = registry.get("HYP-0001")
    assert record.evaluations == ()
    assert record.state is HypothesisState.REGISTERED


# --- test 20: duplicate check results -----------------------------------


def test_one_evaluation_cannot_carry_the_same_check_twice():
    with pytest.raises(DuplicateCheckError, match="same check twice"):
        EvaluationRecord(
            segment="TRAIN",
            statistic_value=0.8,
            checks=(make_check(CheckName.BACKTEST), make_check(CheckName.BACKTEST)),
        )


def test_a_check_result_is_recorded_once_and_never_re_rolled(registry):
    """Follows the single-use TEST evaluation's convention: refuse, do not
    overwrite. An idempotent overwrite would let a FAIL be replaced by a
    PASS, which is the failure mode the whole protocol is built against."""
    registry.register(full_preregistration())
    record_backtest(registry, "HYP-0001", FAIL)

    with pytest.raises(DuplicateCheckError, match="never re-rolled"):
        record_backtest(registry, "HYP-0001", PASS)

    record = registry.get("HYP-0001")
    assert len(record.check_results()) == 1
    assert record.check_results()[0].verdict is FAIL


def test_a_refused_duplicate_does_not_partially_write(tmp_path):
    path = tmp_path / "hypotheses.json"
    registry = HypothesisRegistry(registry_path=path)
    registry.register(full_preregistration())
    record_backtest(registry, "HYP-0001", FAIL)
    before = path.read_text(encoding="utf-8")

    with pytest.raises(DuplicateCheckError):
        record_backtest(registry, "HYP-0001", PASS)

    assert path.read_text(encoding="utf-8") == before
    assert len(HypothesisRegistry(registry_path=path).get("HYP-0001").evaluations) == 1


# --- test 21: order independence ----------------------------------------


def test_the_verdict_does_not_depend_on_the_order_checks_were_recorded(tmp_path):
    forwards = HypothesisRegistry(registry_path=tmp_path / "forwards.json")
    forwards.register(full_preregistration())
    record_backtest(forwards, "HYP-0001")
    record_walk_forward(forwards, "HYP-0001")
    forwards.advance("HYP-0001", HypothesisState.CALIBRATED)
    record_test_read(forwards, "HYP-0001", p_value=0.001, effect_size=0.9)

    backwards = HypothesisRegistry(registry_path=tmp_path / "backwards.json")
    backwards.register(full_preregistration())
    record_walk_forward(backwards, "HYP-0001")
    record_backtest(backwards, "HYP-0001")
    backwards.advance("HYP-0001", HypothesisState.CALIBRATED)
    record_test_read(
        backwards,
        "HYP-0001",
        p_value=0.001,
        effect_size=0.9,
        test_checks=tuple(reversed(TEST_SEGMENT_CHECKS)),
    )

    assert forwards.get("HYP-0001").adjudicate_checks() == (
        backwards.get("HYP-0001").adjudicate_checks()
    )
    forwards.adjudicate_family(FAMILY_ID, q=0.1)
    backwards.adjudicate_family(FAMILY_ID, q=0.1)
    assert (
        forwards.get("HYP-0001").state
        is backwards.get("HYP-0001").state
        is HypothesisState.CANDIDATE
    )


@pytest.mark.parametrize("permutation", list(itertools.permutations(range(3))))
def test_test_segment_check_order_never_changes_the_adjudication(
    tmp_path, permutation
):
    path = tmp_path / f"order_{''.join(str(i) for i in permutation)}.json"
    registry = HypothesisRegistry(registry_path=path)
    registry.register(full_preregistration())
    record_backtest(registry, "HYP-0001")
    record_walk_forward(registry, "HYP-0001")
    registry.advance("HYP-0001", HypothesisState.CALIBRATED)
    record_test_read(
        registry,
        "HYP-0001",
        p_value=0.001,
        effect_size=0.9,
        test_checks=tuple(TEST_SEGMENT_CHECKS[i] for i in permutation),
        verdicts={CheckName.MONTE_CARLO: FAIL},
    )

    adjudication = registry.get("HYP-0001").adjudicate_checks()
    assert adjudication.status is CheckPlanStatus.COMPLETE_FAIL
    assert adjudication.failed_checks == (CheckName.MONTE_CARLO,)
    assert adjudication.passed_check_count == 4
    assert adjudication.required_check_count == 5


# --- test 13 + 22: the NB-5 denominator and partial state ---------------


def test_the_denominator_is_the_plan_not_the_results(registry):
    """NB-5 analogue: three of five recorded must never read as three of three.

    A denominator taken from the results present is the same error as
    computing consensus over surviving agents: the count shrinks to fit
    whatever evidence happens to exist, and a half-run protocol reports
    unanimity.
    """
    registry.register(full_preregistration())
    record_backtest(registry, "HYP-0001")
    record_walk_forward(registry, "HYP-0001")
    registry.advance("HYP-0001", HypothesisState.CALIBRATED)
    record_test_read(
        registry,
        "HYP-0001",
        p_value=0.001,
        effect_size=0.9,
        test_checks=(CheckName.OUT_OF_SAMPLE,),
    )

    adjudication = registry.get("HYP-0001").adjudicate_checks()

    assert adjudication.required_check_count == 5
    assert adjudication.recorded_check_count == 3
    assert adjudication.passed_check_count == 3
    # The failure mode in one line: nothing here may be read as 3/3.
    assert adjudication.passed_check_count != adjudication.required_check_count
    assert (
        adjudication.passed_check_count / adjudication.required_check_count == 0.6
    )
    assert not adjudication.all_required_checks_passed
    assert set(adjudication.missing_checks) == {
        CheckName.COST_ADJUSTED,
        CheckName.MONTE_CARLO,
    }


def test_the_denominator_holds_when_nothing_has_been_recorded(registry):
    registry.register(full_preregistration())
    adjudication = registry.get("HYP-0001").adjudicate_checks()
    assert adjudication.required_check_count == 5
    assert adjudication.recorded_check_count == 0
    assert adjudication.passed_check_count == 0
    assert adjudication.status is CheckPlanStatus.INCOMPLETE


def test_partial_state_is_distinct_from_both_complete_outcomes(registry):
    """Test 22: "still running" and "ran and failed" are different facts."""
    registry.register(full_preregistration())
    record_backtest(registry, "HYP-0001")
    assert (
        registry.get("HYP-0001").adjudicate_checks().status
        is CheckPlanStatus.INCOMPLETE
    )

    record_walk_forward(registry, "HYP-0001", FAIL)
    partial_but_failing = registry.get("HYP-0001").adjudicate_checks()
    # A recorded failure does not end the plan; three checks are outstanding.
    assert partial_but_failing.status is CheckPlanStatus.INCOMPLETE
    assert partial_but_failing.failed_checks == (CheckName.WALK_FORWARD,)

    registry.advance("HYP-0001", HypothesisState.CALIBRATED)
    record_test_read(registry, "HYP-0001", p_value=0.001, effect_size=0.9)
    complete = registry.get("HYP-0001").adjudicate_checks()
    assert complete.status is CheckPlanStatus.COMPLETE_FAIL
    assert not complete.missing_checks


def test_a_partial_plan_adjudicates_as_rejected(registry):
    """Test 22's second half: adjudicated while incomplete, it resolves per
    NB-4 -- missing is failing -- rather than being held open or promoted."""
    run_full_protocol(registry, "HYP-0001", omit=(CheckName.MONTE_CARLO,))
    assert (
        registry.get("HYP-0001").adjudicate_checks().status
        is CheckPlanStatus.INCOMPLETE
    )

    registry.adjudicate_family(FAMILY_ID, q=0.1)
    assert registry.get("HYP-0001").state is HypothesisState.REJECTED


# --- test 12: NB-4, a missing required check is a failure ---------------


def test_a_complete_five_check_pass_is_promoted(registry):
    run_full_protocol(registry, "HYP-0001")
    registry.adjudicate_family(FAMILY_ID, q=0.1)
    assert registry.get("HYP-0001").state is HypothesisState.CANDIDATE


@pytest.mark.parametrize("omitted", list(CheckName))
def test_an_otherwise_identical_hypothesis_missing_one_check_is_rejected(
    registry, omitted
):
    """NB-4 analogue. Two hypotheses, identical statistics, identical sealed
    plans; the only difference is that one check's result is absent. The
    absence must be read as a failure, never as a check that did not apply.
    """
    run_full_protocol(registry, "HYP-0001")
    run_full_protocol(registry, "HYP-0002", omit=(omitted,))

    registry.adjudicate_family(FAMILY_ID, q=0.1)

    assert registry.get("HYP-0001").state is HypothesisState.CANDIDATE
    assert registry.get("HYP-0002").state is HypothesisState.REJECTED


@pytest.mark.parametrize("kept", EVERY_SUBSET_OF_CHECKS)
def test_removing_evidence_can_only_make_the_verdict_less_permissive(
    registry, kept
):
    """NB-4 as a property, over every subset of the recorded results.

    ``all_required_checks_passed`` is true for the complete set and for
    nothing else, and the pass count tracks exactly what survives. There is
    no subset of the evidence whose removal improves the outcome.
    """
    run_full_protocol(registry, "HYP-0001")
    complete = registry.get("HYP-0001")
    assert complete.adjudicate_checks().all_required_checks_passed

    reduced = retaining_only(complete, kept).adjudicate_checks()

    assert reduced.passed_check_count == len(kept)
    assert reduced.required_check_count == 5  # unchanged: it comes from the plan
    assert reduced.all_required_checks_passed is (len(kept) == 5)
    assert reduced.passed_check_count <= (
        complete.adjudicate_checks().passed_check_count
    )


# --- test 16: the gate is conjunctive -----------------------------------


@pytest.mark.parametrize("failing", list(CheckName))
def test_any_single_failed_check_rejects_despite_fdr_alpha_and_effect(
    registry, failing
):
    """A hard AND. A p-value of 0.001 does not buy its way past a failed
    cost-adjusted check; the two quantities are not exchangeable."""
    run_full_protocol(registry, "HYP-0001")
    run_full_protocol(registry, "HYP-0002", verdicts={failing: FAIL})

    decision = registry.adjudicate_family(FAMILY_ID, q=0.1)

    # Both cleared the statistical gates outright.
    assert decision.is_rejected("HYP-0002")
    assert decision.p_values == (0.001, 0.001)
    # Only the check verdict separates them.
    assert registry.get("HYP-0001").state is HypothesisState.CANDIDATE
    assert registry.get("HYP-0002").state is HypothesisState.REJECTED


def test_checks_cannot_rescue_a_hypothesis_that_fails_a_statistical_gate(
    registry,
):
    """The conjunction runs both ways: five passing checks do not substitute
    for a p-value that fails its own pre-registered alpha."""
    run_full_protocol(registry, "HYP-0001", p_value=0.001, effect_size=0.9)
    run_full_protocol(registry, "HYP-0002", p_value=0.2, effect_size=0.9)

    registry.adjudicate_family(FAMILY_ID, q=0.1)

    assert (
        registry.get("HYP-0002").adjudicate_checks().status
        is CheckPlanStatus.COMPLETE_PASS
    )
    assert registry.get("HYP-0002").state is HypothesisState.REJECTED


# --- test 17: check verdicts never touch the BH family ------------------


def _family_with(tmp_path, name, *, failing_ids) -> HypothesisRegistry:
    """Four hypotheses with fixed p-values; ``failing_ids`` fail a check."""
    registry = HypothesisRegistry(registry_path=tmp_path / f"{name}.json")
    for hypothesis_id, p_value in (
        ("HYP-0001", 0.001),
        ("HYP-0002", 0.010),
        ("HYP-0003", 0.030),
        ("HYP-0004", 0.900),
    ):
        run_full_protocol(
            registry,
            hypothesis_id,
            p_value=p_value,
            effect_size=0.9,
            verdicts=(
                {CheckName.MONTE_CARLO: FAIL}
                if hypothesis_id in failing_ids
                else {}
            ),
        )
    return registry


def test_the_bh_family_size_is_unaffected_by_check_verdicts(tmp_path):
    """The ordering property, demonstrated rather than asserted.

    Two families with identical p-values differ only in whether two members
    passed their Monte Carlo check. Every input and every output of the
    correction itself -- ``m``, the p-values, the adjusted p-values, the
    per-hypothesis rejections -- is identical. Only the final promotion
    differs.

    Gating on checks before the correction would drop the failing members
    from the family, shrinking ``m`` from 4 to 2 and making the survivors'
    thresholds twice as easy to clear. That is the selection bias BH exists
    to remove, reintroduced by the thing meant to add rigour.
    """
    failing = _family_with(
        tmp_path, "failing", failing_ids={"HYP-0002", "HYP-0003"}
    )
    passing = _family_with(tmp_path, "passing", failing_ids=set())

    failing_decision = failing.adjudicate_family(FAMILY_ID, q=0.1)
    passing_decision = passing.adjudicate_family(FAMILY_ID, q=0.1)

    # The correction itself is bit-for-bit identical.
    assert failing_decision.n_tests == passing_decision.n_tests == 4
    assert failing_decision.labels == passing_decision.labels
    assert failing_decision.p_values == passing_decision.p_values
    assert failing_decision.adjusted_p_values == passing_decision.adjusted_p_values
    assert failing_decision.rejected == passing_decision.rejected
    assert failing_decision.n_rejected == passing_decision.n_rejected
    assert failing_decision.critical_p_value == passing_decision.critical_p_value
    assert failing_decision.as_dict() == passing_decision.as_dict()

    # A hypothesis that failed a check is still counted in the family.
    assert "HYP-0002" in failing_decision.labels
    assert failing_decision.is_rejected("HYP-0002")

    # Only the promotion differs.
    assert passing.get("HYP-0002").state is HypothesisState.CANDIDATE
    assert failing.get("HYP-0002").state is HypothesisState.REJECTED


def test_a_check_failure_does_not_relax_another_hypothesis_threshold(tmp_path):
    """The concrete consequence of the ordering, at the boundary.

    With m=4 and q=0.1, HYP-0003's p=0.030 sits just under its BH threshold
    of 3/4 * 0.1 = 0.075. Were the two check-failing members pre-filtered
    out, m would be 2 and the same hypothesis would face a materially
    different correction. It must not.
    """
    failing = _family_with(
        tmp_path, "boundary_failing", failing_ids={"HYP-0001", "HYP-0004"}
    )
    passing = _family_with(tmp_path, "boundary_passing", failing_ids=set())

    failing_decision = failing.adjudicate_family(FAMILY_ID, q=0.1)
    passing_decision = passing.adjudicate_family(FAMILY_ID, q=0.1)

    assert failing_decision.adjusted_p_value("HYP-0003") == (
        passing_decision.adjusted_p_value("HYP-0003")
    )
    assert failing.get("HYP-0003").state is passing.get("HYP-0003").state
    assert failing.get("HYP-0001").state is HypothesisState.REJECTED


def test_removing_a_failed_check_does_not_make_a_hypothesis_promotable(registry):
    """The sharpest form of NB-4.

    Deleting the one result that failed is the most attractive edit anyone
    could make to this file. It moves the plan from COMPLETE_FAIL to
    INCOMPLETE and leaves the hypothesis exactly as unpromotable, because
    the missing check is scored against the sealed plan either way.
    """
    run_full_protocol(registry, "HYP-0001", verdicts={CheckName.MONTE_CARLO: FAIL})
    complete = registry.get("HYP-0001")
    assert complete.adjudicate_checks().status is CheckPlanStatus.COMPLETE_FAIL
    assert not complete.adjudicate_checks().all_required_checks_passed

    scrubbed = retaining_only(
        complete, set(CheckName) - {CheckName.MONTE_CARLO}
    ).adjudicate_checks()

    assert scrubbed.status is CheckPlanStatus.INCOMPLETE
    assert scrubbed.missing_checks == (CheckName.MONTE_CARLO,)
    assert not scrubbed.all_required_checks_passed
    assert scrubbed.required_check_count == 5


def test_the_train_checks_cannot_be_run_after_the_test_read(registry):
    """An emergent consequence of the segment access rules, worth pinning.

    BACKTEST and WALK_FORWARD score segments that are readable only before
    TESTED. Consuming the test read first therefore makes them permanently
    unrecordable, and the hypothesis permanently unpromotable. "Look at the
    test set first, justify it afterwards" is structurally unavailable, not
    merely discouraged.
    """
    registry.register(full_preregistration())
    registry.advance("HYP-0001", HypothesisState.CALIBRATED)
    record_test_read(registry, "HYP-0001", p_value=0.001, effect_size=0.9)

    with pytest.raises(EvaluationNotPermittedError, match="permitted only from"):
        record_backtest(registry, "HYP-0001")

    registry.adjudicate_family(FAMILY_ID, q=0.1)
    assert registry.get("HYP-0001").state is HypothesisState.REJECTED


def test_a_parameterless_check_seals_the_same_whether_or_not_it_is_spelled_out():
    """OUT_OF_SAMPLE takes no parameters, so ``{}`` and an absent entry are
    the same plan and must not seal two different ways."""
    implicit = CheckPlan(required_checks=(CheckName.OUT_OF_SAMPLE,))
    explicit = CheckPlan(
        required_checks=(CheckName.OUT_OF_SAMPLE,),
        parameters={"OUT_OF_SAMPLE": {}},
    )
    assert implicit == explicit
    assert (
        make_preregistration(check_plan=implicit).seal_hash()
        == make_preregistration(check_plan=explicit).seal_hash()
    )


# --- the load path enforces what the write path enforces ----------------


def _append_evaluation(path, source_index: int, mutate) -> None:
    """Append a copy of a stored evaluation, edited by ``mutate``.

    Appending rather than editing is the interesting attack: it leaves the
    pre-registration and its hash untouched, so the seal cannot see it.
    """
    payload = _stored(path)
    evaluations = payload["records"][0]["evaluations"]
    copied = json.loads(json.dumps(evaluations[source_index]))
    mutate(copied)
    evaluations.append(copied)
    _rewrite(path, payload)


def test_a_failing_verdict_cannot_be_re_rolled_by_appending_a_passing_copy(
    tmp_path,
):
    """Evaluations are outside the seal, so the load path must re-check them.

    Appending a second BACKTEST result saying PASS, after the first said
    FAIL, is the cheapest possible way to launder a failed check: nothing in
    the sealed pre-registration changes, so the hash still verifies. The
    write path's "recorded once, never re-rolled" rule has to hold on load
    too or it only holds until the next restart.
    """
    path = tmp_path / "hypotheses.json"
    registry = HypothesisRegistry(registry_path=path)
    run_full_protocol(registry, "HYP-0001", verdicts={CheckName.BACKTEST: FAIL})
    assert (
        registry.get("HYP-0001").adjudicate_checks().status
        is CheckPlanStatus.COMPLETE_FAIL
    )

    def flip_to_pass(evaluation):
        evaluation["checks"][0]["verdict"] = "PASS"

    _append_evaluation(path, 0, flip_to_pass)

    with pytest.raises(DuplicateCheckError, match="never re-rolled"):
        HypothesisRegistry(registry_path=path)


def test_a_stored_check_outside_the_sealed_plan_is_refused_on_load(tmp_path):
    """The load path honours UnplannedCheckError as the write path does."""
    path = tmp_path / "hypotheses.json"
    registry = HypothesisRegistry(registry_path=path)
    registry.register(make_preregistration())  # minimal plan: OUT_OF_SAMPLE
    registry.advance("HYP-0001", HypothesisState.CALIBRATED)
    record_test_read(
        registry,
        "HYP-0001",
        p_value=0.001,
        effect_size=0.9,
        test_checks=(CheckName.OUT_OF_SAMPLE,),
    )

    payload = _stored(path)
    stored_check = payload["records"][0]["evaluations"][0]["checks"][0]
    smuggled = json.loads(json.dumps(stored_check))
    smuggled["check_name"] = "MONTE_CARLO"
    payload["records"][0]["evaluations"][0]["checks"].append(smuggled)
    _rewrite(path, payload)

    with pytest.raises(UnplannedCheckError, match="never required"):
        HypothesisRegistry(registry_path=path)


def test_a_duplicate_check_folds_to_the_failing_verdict(tmp_path):
    """Defence in depth behind the load-path refusal.

    A duplicate should be unreachable, but if a record ever holds two results
    for one check, the adjudicator must not let the later one win. The
    tiebreak resolves towards FAIL, never towards promotion.
    """
    path = tmp_path / "hypotheses.json"
    registry = HypothesisRegistry(registry_path=path)
    run_full_protocol(registry, "HYP-0001", verdicts={CheckName.BACKTEST: FAIL})
    record = registry.get("HYP-0001")

    passing_copy = make_check(CheckName.BACKTEST, PASS)
    train_index = next(
        index
        for index, evaluation in enumerate(record.evaluations)
        if evaluation.segment == "TRAIN"
    )
    evaluations = list(record.evaluations)
    evaluations.append(
        replace(evaluations[train_index], checks=(passing_copy,))
    )
    forced = replace(record, evaluations=tuple(evaluations))

    adjudication = forced.adjudicate_checks()
    assert adjudication.failed_checks == (CheckName.BACKTEST,)
    assert not adjudication.all_required_checks_passed


def test_an_identifier_parameter_must_actually_be_a_string():
    """str() coercion would seal 123 and "123" as the same plan."""
    with pytest.raises(RegistryError, match="must be a string"):
        CheckPlan(
            required_checks=(CheckName.COST_ADJUSTED,),
            parameters={"COST_ADJUSTED": {"cost_model_id": 123, "cost_bps": 7.5}},
        )


@pytest.mark.parametrize(
    "mutate",
    [
        pytest.param(lambda ev: ev.update({"checks": None}), id="checks-null"),
        pytest.param(
            lambda ev: ev.update({"checks": "BACKTEST"}), id="checks-a-string"
        ),
        pytest.param(
            lambda ev: ev.update({"checks": [["not", "a", "dict"]]}),
            id="check-entry-not-a-mapping",
        ),
        pytest.param(
            lambda ev: ev.update({"statistic_value": "abc"}),
            id="statistic-not-a-number",
        ),
    ],
)
def test_a_malformed_stored_evaluation_raises_the_documented_error_family(
    tmp_path, mutate
):
    """Fail-closed is not enough on its own: it must fail closed as a
    RegistryError, or a caller guarding the load with ``except RegistryError``
    is bypassed by a bad payload type."""
    path = tmp_path / "hypotheses.json"
    registry = HypothesisRegistry(registry_path=path)
    run_full_protocol(registry, "HYP-0001")

    payload = _stored(path)
    mutate(payload["records"][0]["evaluations"][0])
    _rewrite(path, payload)

    with pytest.raises(RegistryError):
        HypothesisRegistry(registry_path=path)


# --- a sealed threshold is binding, not documentary ---------------------


#: The sealed threshold each check must be scored against, and a different
#: number that must therefore be refused.
SEALED_AND_WRONG = [
    pytest.param(CheckName.BACKTEST, 0.5, 0.0001, id="backtest"),
    pytest.param(CheckName.WALK_FORWARD, 0.6, 0.3, id="walk-forward"),
    pytest.param(CheckName.COST_ADJUSTED, 7.5, 0.0, id="cost-adjusted"),
    pytest.param(CheckName.MONTE_CARLO, 95.0, 50.0, id="monte-carlo"),
]


@pytest.mark.parametrize("check_name,sealed,wrong", SEALED_AND_WRONG)
def test_the_plan_exposes_the_threshold_a_check_must_be_scored_against(
    check_name, sealed, wrong
):
    assert FULL_CHECK_PLAN.threshold_for(check_name) == sealed
    assert sealed != wrong


def test_out_of_sample_seals_no_threshold():
    """Its identity is the pre-registered split's TEST segment, already sealed
    through split_spec, so there is no separate number to bind."""
    assert FULL_CHECK_PLAN.threshold_for(CheckName.OUT_OF_SAMPLE) is None


def _record_one_check(registry, hypothesis_id, check):
    """Record a single check against whichever segment it is bound to."""
    segment = check.segment
    if segment == "TEST":
        registry.advance(hypothesis_id, HypothesisState.CALIBRATED)
        registry.record_evaluation(
            hypothesis_id,
            EvaluationRecord(
                segment="TEST",
                statistic_value=0.9,
                p_value=0.001,
                effect_size=0.9,
                checks=(check,),
            ),
        )
    else:
        registry.record_evaluation(
            hypothesis_id,
            EvaluationRecord(
                segment=segment, statistic_value=0.8, checks=(check,)
            ),
        )


@pytest.mark.parametrize("check_name,sealed,wrong", SEALED_AND_WRONG)
def test_a_check_scored_against_the_wrong_threshold_is_refused(
    registry, check_name, sealed, wrong
):
    """The heart of the binding: a PASS decided against a number the plan
    never sealed is not the check that was pre-registered."""
    registry.register(full_preregistration())
    check = make_check(check_name, PASS, threshold_applied=wrong)

    with pytest.raises(ThresholdBindingError, match="sealed plan requires"):
        _record_one_check(registry, "HYP-0001", check)


@pytest.mark.parametrize("check_name,sealed,wrong", SEALED_AND_WRONG)
def test_a_check_scored_against_the_sealed_threshold_is_accepted(
    registry, check_name, sealed, wrong
):
    registry.register(full_preregistration())
    _record_one_check(
        registry, "HYP-0001", make_check(check_name, PASS, threshold_applied=sealed)
    )

    recorded = registry.get("HYP-0001").check_results()
    assert [c.check_name for c in recorded] == [check_name]
    assert recorded[0].threshold_applied == sealed


@pytest.mark.parametrize("check_name,sealed,wrong", SEALED_AND_WRONG)
def test_a_check_with_a_sealed_threshold_must_declare_one(
    registry, check_name, sealed, wrong
):
    """Omitting it is not a way around declaring the wrong one."""
    registry.register(full_preregistration())
    check = make_check(check_name, PASS, threshold_applied=None)

    with pytest.raises(ThresholdBindingError, match="must declare"):
        _record_one_check(registry, "HYP-0001", check)


def test_a_check_with_no_sealed_threshold_must_not_declare_one(registry):
    """A stored number nothing validates would read as a binding that held."""
    registry.register(full_preregistration())
    registry.advance("HYP-0001", HypothesisState.CALIBRATED)
    check = make_check(CheckName.OUT_OF_SAMPLE, PASS, threshold_applied=0.5)

    with pytest.raises(ThresholdBindingError, match="seals no threshold"):
        registry.record_evaluation(
            "HYP-0001",
            EvaluationRecord(
                segment="TEST",
                statistic_value=0.9,
                p_value=0.001,
                effect_size=0.9,
                checks=(check,),
            ),
        )


def test_the_audit_reproduction_no_longer_promotes(registry):
    """The exact case the independent audit demonstrated.

    A BACKTEST PASS decided against 0.0001, on a plan that sealed
    minimum_effect_size 0.5, previously travelled through the ordinary public
    API and promoted to CANDIDATE. It is now refused at the point of
    recording, so the hypothesis never acquires the laundered check at all.
    """
    registry.register(full_preregistration())
    assert FULL_CHECK_PLAN.threshold_for(CheckName.BACKTEST) == 0.5

    with pytest.raises(ThresholdBindingError, match="scored against threshold"):
        registry.record_evaluation(
            "HYP-0001",
            EvaluationRecord(
                segment="TRAIN",
                statistic_value=0.001,
                checks=(
                    make_check(
                        CheckName.BACKTEST, PASS, threshold_applied=0.0001
                    ),
                ),
            ),
        )

    record = registry.get("HYP-0001")
    assert record.check_results() == ()
    assert record.state is HypothesisState.REGISTERED


def test_the_threshold_binding_is_enforced_on_the_load_path_too(tmp_path):
    """The lesson from the appended-duplicate finding, applied here.

    Evaluations are outside the seal, so enforcing the binding only in
    record_evaluation would mean it held until the next restart. Editing a
    stored threshold_applied must be refused on load.
    """
    path = tmp_path / "hypotheses.json"
    registry = HypothesisRegistry(registry_path=path)
    run_full_protocol(registry, "HYP-0001")

    payload = _stored(path)
    for evaluation in payload["records"][0]["evaluations"]:
        for check in evaluation["checks"]:
            if check["check_name"] == "MONTE_CARLO":
                check["threshold_applied"] = 50.0
    _rewrite(path, payload)

    with pytest.raises(ThresholdBindingError, match="sealed plan requires"):
        HypothesisRegistry(registry_path=path)


# --- promotion is reachable only through family adjudication ------------


def test_a_hypothesis_cannot_be_promoted_by_advancing_it_directly(registry):
    """FAMILY_ADJUDICATED_TRANSITION is declared in lifecycle and enforced here.

    Promotion depends on how many *other* hypotheses were tested, so it is
    not a transition a hypothesis can make on its own evidence. Left open,
    this single call routes around the FDR, alpha, effect-size and check
    gates together.
    """
    run_full_protocol(registry, "HYP-0001")
    assert registry.get("HYP-0001").state is HypothesisState.TESTED

    with pytest.raises(
        FamilyAdjudicationRequiredError, match="adjudicate_family"
    ):
        registry.advance("HYP-0001", HypothesisState.CANDIDATE)

    assert registry.get("HYP-0001").state is HypothesisState.TESTED


def test_the_bypass_cannot_launder_a_failed_check(registry):
    """The attack the closure exists to stop, end to end."""
    run_full_protocol(registry, "HYP-0001", verdicts={CheckName.MONTE_CARLO: FAIL})

    with pytest.raises(FamilyAdjudicationRequiredError):
        registry.advance("HYP-0001", HypothesisState.CANDIDATE)

    registry.adjudicate_family(FAMILY_ID, q=0.1)
    assert registry.get("HYP-0001").state is HypothesisState.REJECTED


def test_family_adjudication_still_promotes_through_its_own_gated_path(registry):
    """The closure must not break the legitimate route.

    adjudicate_family validates and writes its transitions directly rather
    than calling advance(), so the refusal above never stands in its way.
    """
    run_full_protocol(registry, "HYP-0001")
    registry.adjudicate_family(FAMILY_ID, q=0.1)
    assert registry.get("HYP-0001").state is HypothesisState.CANDIDATE


@pytest.mark.parametrize(
    "target", [HypothesisState.PAPER_VALIDATING, HypothesisState.RETIRED]
)
def test_advance_still_serves_every_transition_it_always_did(registry, target):
    """Only promotion is withdrawn; the rest of the machine is untouched."""
    run_full_protocol(registry, "HYP-0001")
    registry.adjudicate_family(FAMILY_ID, q=0.1)
    assert registry.advance("HYP-0001", target).state is target


def test_advance_still_permits_rejection_from_tested(registry):
    """TESTED -> REJECTED needs no family evidence: it is never a promotion."""
    run_full_protocol(registry, "HYP-0001")
    assert (
        registry.advance("HYP-0001", HypothesisState.REJECTED).state
        is HypothesisState.REJECTED
    )
