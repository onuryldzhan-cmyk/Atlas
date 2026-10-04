"""Acceptance tests for Experiment Manager v1 (GRANT-EXPMGR-V1-RESEARCH-ONLY, v5.86).

Each test names the acceptance item it pins (A1..A16). Verdict rules come from
``grant_expmgr_v1_research_only.verdict_rules`` in registry v5.86:

* SUPPORTED needs a registered p-value procedure and power analysis. Neither
  exists in this build, so the ceiling is INSUFFICIENT_EVIDENCE.
* REJECTED needs measurable negative criteria sealed at pre-registration and
  sufficient negative evidence. Missing / corrupt data, a missing check or a
  too-small sample is never REJECTED; it is INSUFFICIENT_EVIDENCE.
* No verdict creates trading authority.
"""

from __future__ import annotations

import dataclasses
import json
from dataclasses import replace

import pytest

from research.experiment_manager import (
    REGISTERED_P_VALUE_PROCEDURE,
    REGISTERED_POWER_ANALYSIS,
    REJECTION_CRITERIA_KEY,
    ExperimentError,
    ExperimentIntegrityError,
    ExperimentManager,
    ExperimentManagerHalted,
    ExperimentStatus,
    IllegalExperimentTransitionError,
    MalformedRunError,
    RunResult,
    Verdict,
    VerdictRecord,
)
from research.hypothesis_registry import (
    CheckName,
    CheckPlan,
    CheckResult,
    CheckVerdict,
    EvaluationRecord,
    HypothesisRegistry,
    UnknownHypothesisError,
    UnplannedCheckError,
)
from research.lifecycle import HypothesisState
from tests.test_research_hypothesis_registry import make_preregistration

HID = "HYP-0001"
CRITERIA = {"minimum_sample_size": 100, "failing_checks": ["OUT_OF_SAMPLE"]}


def _feature_spec(criteria=CRITERIA) -> dict:
    spec = {"lookback": 24}
    if criteria is not None:
        spec[REJECTION_CRITERIA_KEY] = criteria
    return spec


@pytest.fixture
def registry(tmp_path) -> HypothesisRegistry:
    return HypothesisRegistry(registry_path=tmp_path / "registry" / "hypotheses.json")


def _register(registry, hid=HID, criteria=CRITERIA, **overrides):
    return registry.register(
        make_preregistration(
            hypothesis_id=hid, feature_spec=_feature_spec(criteria), **overrides
        )
    )


def _record_test(registry, hid=HID, verdict=CheckVerdict.FAIL, with_check=True):
    registry.advance(hid, HypothesisState.CALIBRATED)
    checks = (
        (CheckResult(check_name=CheckName.OUT_OF_SAMPLE, verdict=verdict, statistic_value=-0.2),)
        if with_check
        else ()
    )
    registry.record_evaluation(
        hid,
        EvaluationRecord(
            segment="TEST", statistic_value=-0.2, p_value=0.4, effect_size=-0.1, checks=checks
        ),
    )


def _run(sample_size=500, refs=("backtest:run-1",), **kw) -> RunResult:
    return RunResult(sample_size=sample_size, evidence_refs=refs, metrics={"mean_excess_return": -0.1}, **kw)


def _complete(manager, hid=HID, run=None):
    manager.start(hid)
    manager.record_run(hid, run or _run())
    manager.complete(hid)


@pytest.fixture
def manager(registry) -> ExperimentManager:
    return ExperimentManager(registry=registry)


# -- A1 / A2: pre-registration required, hypothesis_id carried ---------------


def test_a1_experiment_cannot_be_created_without_preregistration(manager):
    with pytest.raises(UnknownHypothesisError):
        manager.register_experiment(HID)
    assert manager.log == ()


def test_a2_experiment_carries_hypothesis_id_and_family(registry, manager):
    record = _register(registry)
    exp = manager.register_experiment(HID)
    assert exp.hypothesis_id == HID
    assert exp.family_id == record.family_id
    assert exp.preregistration_hash == record.preregistration_hash
    assert exp.status is ExperimentStatus.REGISTERED


def test_a2_no_parallel_identity_one_experiment_per_hypothesis(registry, manager):
    _register(registry)
    manager.register_experiment(HID)
    with pytest.raises(ExperimentError):
        manager.register_experiment(HID)


def test_a2_terminal_hypothesis_cannot_open_an_experiment(registry, manager):
    _register(registry)
    registry.advance(HID, HypothesisState.REJECTED)
    with pytest.raises(ExperimentError):
        manager.register_experiment(HID)


# -- A3: sealed pre-registration is immutable --------------------------------


def test_a3_sealed_preregistration_is_frozen(registry):
    record = _register(registry)
    with pytest.raises(dataclasses.FrozenInstanceError):
        record.preregistration.direction = "less"  # type: ignore[misc]


def test_a3_seal_drift_after_registration_halts_the_manager(registry, manager):
    _register(registry)
    manager.register_experiment(HID)
    record = registry.get(HID)
    tampered = replace(
        record, preregistration=replace(record.preregistration, direction="less")
    )
    registry._records[HID] = tampered  # simulate an on-disk edit after load
    with pytest.raises(ExperimentIntegrityError):
        manager.start(HID)
    assert manager.halted
    with pytest.raises(ExperimentManagerHalted):
        manager.experiment(HID)


# -- A4: CheckPlan bound to the experiment -----------------------------------


def test_a4_check_plan_is_the_sealed_plan_of_the_hypothesis(registry, manager):
    record = _register(registry)
    exp = manager.register_experiment(HID)
    assert exp.check_plan == record.check_plan
    assert exp.required_check_count == record.check_plan.required_check_count


# -- A5: lifecycle -----------------------------------------------------------


def test_a5_lifecycle_registered_running_completed(registry, manager):
    _register(registry)
    manager.register_experiment(HID)
    assert manager.start(HID).status is ExperimentStatus.RUNNING
    assert manager.complete(HID).status is ExperimentStatus.COMPLETED
    with pytest.raises(IllegalExperimentTransitionError):
        manager.start(HID)
    with pytest.raises(IllegalExperimentTransitionError):
        manager.abort(HID, reason="late")


@pytest.mark.parametrize("started", [False, True])
def test_a5_abort_from_registered_or_running(registry, manager, started):
    _register(registry)
    manager.register_experiment(HID)
    if started:
        manager.start(HID)
    assert manager.abort(HID, reason="data vendor outage").status is ExperimentStatus.ABORTED
    with pytest.raises(IllegalExperimentTransitionError):
        manager.complete(HID)


def test_a5_cannot_complete_without_running(registry, manager):
    _register(registry)
    manager.register_experiment(HID)
    with pytest.raises(IllegalExperimentTransitionError):
        manager.complete(HID)


def test_a5_runs_only_while_running(registry, manager):
    _register(registry)
    manager.register_experiment(HID)
    with pytest.raises(IllegalExperimentTransitionError):
        manager.record_run(HID, _run())


# -- A6 / A7: append-only runs, idempotent duplicates ------------------------


def test_a6_runs_are_append_only_and_hash_chained(registry, manager):
    _register(registry)
    manager.register_experiment(HID)
    manager.start(HID)
    manager.record_run(HID, _run(refs=("backtest:a",)))
    manager.record_run(HID, _run(refs=("backtest:b",)))
    log = manager.log
    assert [e.sequence for e in log] == list(range(len(log)))
    for prev, entry in zip(log, log[1:]):
        assert entry.previous_hash == prev.entry_hash
    assert isinstance(log, tuple)
    assert len(manager.runs(HID)) == 2
    manager.verify_log()


def test_a7_duplicate_run_is_not_recorded_twice(registry, manager):
    _register(registry)
    manager.register_experiment(HID)
    manager.start(HID)
    first = manager.record_run(HID, _run())
    before = len(manager.log)
    second = manager.record_run(HID, _run())
    assert second == first
    assert len(manager.log) == before
    assert len(manager.runs(HID)) == 1


# -- A8 / A9: missing or malformed evidence ----------------------------------


@pytest.mark.parametrize(
    "kwargs",
    [
        {"sample_size": 0},
        {"sample_size": -5},
        {"sample_size": True},
        {"sample_size": 10.5},
        {"refs": ()},
        {"refs": ("",)},
        {"refs": ("bad ref with spaces",)},
        {"refs": ("dup", "dup")},
    ],
)
def test_a8_malformed_run_is_refused_not_recorded(registry, manager, kwargs):
    _register(registry)
    manager.register_experiment(HID)
    manager.start(HID)
    before = len(manager.log)
    with pytest.raises(MalformedRunError):
        manager.record_run(HID, _run(**kwargs))
    assert len(manager.log) == before
    assert not manager.halted


@pytest.mark.parametrize("metrics", [{"x": float("nan")}, {"x": float("inf")}, {"": 1.0}, {"x": "1"}])
def test_a8_malformed_metrics_refused(metrics):
    with pytest.raises(MalformedRunError):
        RunResult(sample_size=10, evidence_refs=("r",), metrics=metrics)


def test_a8_non_run_object_refused(registry, manager):
    _register(registry)
    manager.register_experiment(HID)
    manager.start(HID)
    with pytest.raises(MalformedRunError):
        manager.record_run(HID, {"sample_size": 500})  # type: ignore[arg-type]


def test_a9_no_run_is_insufficient(registry, manager):
    _register(registry)
    _record_test(registry)
    manager.register_experiment(HID)
    manager.start(HID)
    manager.complete(HID)
    v = manager.evaluate(HID)
    assert v.verdict is Verdict.INSUFFICIENT_EVIDENCE
    assert "NO_RUN" in v.reasons


def test_a9_missing_check_is_insufficient_never_rejected(registry, manager):
    _register(registry)  # OUT_OF_SAMPLE required, never recorded
    manager.register_experiment(HID)
    _complete(manager)
    v = manager.evaluate(HID)
    assert v.verdict is Verdict.INSUFFICIENT_EVIDENCE
    assert "CHECKS_MISSING" in v.reasons


def test_a9_small_sample_is_insufficient_never_rejected(registry, manager):
    _register(registry)
    _record_test(registry)
    manager.register_experiment(HID)
    _complete(manager, run=_run(sample_size=99))
    v = manager.evaluate(HID)
    assert v.verdict is Verdict.INSUFFICIENT_EVIDENCE
    assert "SAMPLE_TOO_SMALL" in v.reasons


def test_a9_aborted_experiment_is_insufficient(registry, manager):
    _register(registry)
    _record_test(registry)
    manager.register_experiment(HID)
    manager.start(HID)
    manager.record_run(HID, _run())
    manager.abort(HID, reason="vendor outage")
    v = manager.evaluate(HID)
    assert v.verdict is Verdict.INSUFFICIENT_EVIDENCE
    assert "EXPERIMENT_ABORTED" in v.reasons


def test_a9_evaluate_before_completion_is_refused(registry, manager):
    _register(registry)
    manager.register_experiment(HID)
    manager.start(HID)
    with pytest.raises(IllegalExperimentTransitionError):
        manager.evaluate(HID)


# -- A10: SUPPORTED ceiling --------------------------------------------------


def test_a10_procedures_are_not_registered_in_this_build():
    assert REGISTERED_P_VALUE_PROCEDURE is None
    assert REGISTERED_POWER_ANALYSIS is None


def test_a10_all_checks_passing_is_capped_at_insufficient(registry, manager):
    _register(registry)
    _record_test(registry, verdict=CheckVerdict.PASS)
    manager.register_experiment(HID)
    _complete(manager)
    v = manager.evaluate(HID)
    assert v.verdict is Verdict.INSUFFICIENT_EVIDENCE
    assert "SUPPORTED_CEILING_NO_REGISTERED_P_VALUE_PROCEDURE" in v.reasons
    assert "SUPPORTED_CEILING_NO_POWER_ANALYSIS" in v.reasons


def test_a10_supported_is_unreachable_across_a_grid(tmp_path):
    for i, (check_verdict, size, criteria) in enumerate(
        (cv, s, c)
        for cv in (CheckVerdict.PASS, CheckVerdict.FAIL)
        for s in (1, 99, 100, 10_000)
        for c in (CRITERIA, None)
    ):
        reg = HypothesisRegistry(registry_path=tmp_path / f"r{i}.json")
        _register(reg, criteria=criteria)
        _record_test(reg, verdict=check_verdict)
        mgr = ExperimentManager(registry=reg)
        mgr.register_experiment(HID)
        _complete(mgr, run=_run(sample_size=size))
        assert mgr.evaluate(HID).verdict is not Verdict.SUPPORTED


# -- A11 / A12: REJECTED only by sealed criteria; no hindsight ---------------


def test_a11_rejected_with_preregistered_measurable_criteria(registry, manager):
    _register(registry)
    _record_test(registry, verdict=CheckVerdict.FAIL)
    manager.register_experiment(HID)
    _complete(manager)
    v = manager.evaluate(HID)
    assert v.verdict is Verdict.REJECTED
    assert v.reasons == ("PREREGISTERED_REJECTION_CRITERIA_MET:OUT_OF_SAMPLE",)


@pytest.mark.parametrize(
    "criteria",
    [
        {"minimum_sample_size": 0, "failing_checks": ["OUT_OF_SAMPLE"]},
        {"minimum_sample_size": 100, "failing_checks": []},
        {"minimum_sample_size": 100, "failing_checks": ["MONTE_CARLO"]},  # not in plan
        {"minimum_sample_size": 100, "failing_checks": ["NOT_A_CHECK"]},
        {"minimum_sample_size": 100},
        {"minimum_sample_size": "100", "failing_checks": ["OUT_OF_SAMPLE"]},
        {"minimum_sample_size": 100, "failing_checks": ["OUT_OF_SAMPLE"], "extra": 1},
        "reject if bad",
    ],
)
def test_a11_unmeasurable_or_invalid_criteria_cannot_reject(registry, manager, criteria):
    _register(registry, criteria=criteria)
    _record_test(registry, verdict=CheckVerdict.FAIL)
    manager.register_experiment(HID)
    _complete(manager)
    v = manager.evaluate(HID)
    assert v.verdict is Verdict.INSUFFICIENT_EVIDENCE
    assert "REJECTION_CRITERIA_INVALID" in v.reasons


def test_a12_without_sealed_criteria_a_failed_check_cannot_reject(registry, manager):
    _register(registry, criteria=None)
    _record_test(registry, verdict=CheckVerdict.FAIL)
    manager.register_experiment(HID)
    _complete(manager)
    v = manager.evaluate(HID)
    assert v.verdict is Verdict.INSUFFICIENT_EVIDENCE
    assert "NO_PREREGISTERED_REJECTION_CRITERIA" in v.reasons


def test_a12_evaluate_accepts_no_runtime_criteria():
    import inspect

    params = set(inspect.signature(ExperimentManager.evaluate).parameters)
    assert params == {"self", "hypothesis_id"}


def test_a12_hindsight_criterion_breaks_the_seal(registry, manager):
    _register(registry, criteria=None)
    _record_test(registry, verdict=CheckVerdict.FAIL)
    manager.register_experiment(HID)
    _complete(manager)
    record = registry.get(HID)
    pre = record.preregistration
    hindsight = replace(pre, feature_spec={**pre.feature_spec, REJECTION_CRITERIA_KEY: CRITERIA})
    registry._records[HID] = replace(record, preregistration=hindsight)
    with pytest.raises(ExperimentIntegrityError):
        manager.evaluate(HID)
    assert manager.halted


def test_a12_hindsight_check_cannot_be_added_to_the_plan(registry):
    _register(registry)
    registry.advance(HID, HypothesisState.CALIBRATED)
    with pytest.raises(UnplannedCheckError):
        registry.record_evaluation(
            HID,
            EvaluationRecord(
                segment="TEST", statistic_value=0.0, p_value=0.5, effect_size=0.0,
                checks=(CheckResult(check_name=CheckName.MONTE_CARLO, verdict=CheckVerdict.FAIL,
                                    statistic_value=0.0, threshold_applied=95.0),),
            ),
        )


def test_a12_failure_of_a_check_outside_the_criteria_cannot_reject(registry, manager):
    plan = CheckPlan(
        required_checks=(CheckName.BACKTEST, CheckName.OUT_OF_SAMPLE),
        parameters={"BACKTEST": {"minimum_effect_size": 0.5}},
    )
    _register(registry, check_plan=plan)
    registry.record_evaluation(
        HID,
        EvaluationRecord(
            segment="TRAIN", statistic_value=0.1,
            checks=(CheckResult(check_name=CheckName.BACKTEST, verdict=CheckVerdict.FAIL,
                                statistic_value=0.1, threshold_applied=0.5),),
        ),
    )
    _record_test(registry, verdict=CheckVerdict.PASS)
    manager.register_experiment(HID)
    _complete(manager)
    v = manager.evaluate(HID)
    assert v.verdict is Verdict.INSUFFICIENT_EVIDENCE
    assert "FAILURE_NOT_A_PREREGISTERED_REJECTION_CRITERION" in v.reasons


# -- NB-4: removing evidence never makes the verdict more decisive -----------


def test_nb4_removing_the_check_result_cannot_keep_rejected(tmp_path):
    reg_full = HypothesisRegistry(registry_path=tmp_path / "full.json")
    _register(reg_full)
    _record_test(reg_full, verdict=CheckVerdict.FAIL)
    m_full = ExperimentManager(registry=reg_full)
    m_full.register_experiment(HID)
    _complete(m_full)
    assert m_full.evaluate(HID).verdict is Verdict.REJECTED

    reg_less = HypothesisRegistry(registry_path=tmp_path / "less.json")
    _register(reg_less)
    _record_test(reg_less, with_check=False)
    m_less = ExperimentManager(registry=reg_less)
    m_less.register_experiment(HID)
    _complete(m_less)
    assert m_less.evaluate(HID).verdict is Verdict.INSUFFICIENT_EVIDENCE


def test_nb4_a_small_sample_run_blocks_rejection_even_alongside_a_large_one(registry, manager):
    _register(registry)
    _record_test(registry)
    manager.register_experiment(HID)
    manager.start(HID)
    manager.record_run(HID, _run(sample_size=5000, refs=("a",)))
    manager.record_run(HID, _run(sample_size=10, refs=("b",)))
    manager.complete(HID)
    assert manager.evaluate(HID).verdict is Verdict.INSUFFICIENT_EVIDENCE


# -- A13 / A14: no trading authority, no runtime path ------------------------


def test_a13_verdict_record_carries_no_authority():
    fields = {f.name for f in dataclasses.fields(VerdictRecord)}
    forbidden = {"authority", "trading", "order", "execute", "capital", "risk", "position", "size"}
    assert not [f for f in fields if any(tok in f for tok in forbidden)], fields
    assert not [n for n in dir(VerdictRecord) if any(tok in n.lower() for tok in ("execute", "order", "trade", "submit"))]


def test_a13_rejected_verdict_is_frozen_evidence(registry, manager):
    _register(registry)
    _record_test(registry)
    manager.register_experiment(HID)
    _complete(manager)
    v = manager.evaluate(HID)
    with pytest.raises(dataclasses.FrozenInstanceError):
        v.verdict = Verdict.SUPPORTED  # type: ignore[misc]


def test_a14_manager_exposes_no_runtime_hooks():
    names = [n.lower() for n in dir(ExperimentManager) if not n.startswith("_")]
    for token in ("execute", "order", "trade", "risk", "capital", "portfolio", "publish", "bridge", "brain"):
        assert not [n for n in names if token in n], (token, names)


def test_a14_manager_writes_nothing_to_disk(registry, manager, tmp_path):
    _register(registry)
    _record_test(registry)
    before = sorted(p.relative_to(tmp_path) for p in tmp_path.rglob("*"))
    manager.register_experiment(HID)
    _complete(manager)
    manager.evaluate(HID)
    after = sorted(p.relative_to(tmp_path) for p in tmp_path.rglob("*"))
    assert before == after


# -- A15: fail safe ----------------------------------------------------------


def test_a15_broken_log_chain_halts(registry, manager):
    _register(registry)
    manager.register_experiment(HID)
    manager.start(HID)
    entry = manager._log[-1]
    manager._log[-1] = replace(entry, payload={**entry.payload, "to": "COMPLETED"})
    with pytest.raises(ExperimentIntegrityError):
        manager.verify_log()
    assert manager.halted
    for call in (
        lambda: manager.record_run(HID, _run()),
        lambda: manager.complete(HID),
        lambda: manager.register_experiment("HYP-0002"),
    ):
        with pytest.raises(ExperimentManagerHalted):
            call()


def test_a15_unexpected_registry_failure_halts_and_appends_nothing(registry, manager, monkeypatch):
    _register(registry)
    _record_test(registry)
    manager.register_experiment(HID)
    _complete(manager)
    before = manager.log

    def boom(_hid):
        raise OSError("disk gone")

    monkeypatch.setattr(registry, "get", boom)
    with pytest.raises(ExperimentManagerHalted):
        manager.evaluate(HID)
    assert manager.halted
    assert manager.log == before


def test_a15_stored_check_tamper_halts(registry, manager):
    _register(registry)
    _record_test(registry)
    manager.register_experiment(HID)
    _complete(manager)
    record = registry.get(HID)
    # Append a passing copy after the failing verdict: the cheapest re-roll.
    second = replace(
        record.evaluations[-1],
        checks=(CheckResult(check_name=CheckName.OUT_OF_SAMPLE,
                            verdict=CheckVerdict.PASS, statistic_value=1.0),),
    )
    registry._records[HID] = replace(record, evaluations=record.evaluations + (second,))
    with pytest.raises(ExperimentIntegrityError):
        manager.evaluate(HID)
    assert manager.halted


# -- A16: successor records --------------------------------------------------


def test_a16_run_correction_is_a_successor(registry, manager):
    _register(registry)
    _record_test(registry)
    manager.register_experiment(HID)
    manager.start(HID)
    bad = manager.record_run(HID, _run(sample_size=10, refs=("a",)))
    manager.record_run(HID, _run(sample_size=500, refs=("a-fixed",), supersedes=bad.entry_hash))
    manager.complete(HID)
    assert len(manager.runs(HID)) == 2  # the superseded run is kept
    assert [r.payload["run"]["sample_size"] for r in manager.effective_runs(HID)] == [500]
    # Test correction 2026-10-04 (owner-approved, review finding M1): this was
    # `verdict is Verdict.REJECTED`. A superseded small run and an attacker
    # hiding a small sample are indistinguishable from the data, so sample
    # sufficiency now counts every recorded run (provenance kept, above): the
    # correction stays recorded and the verdict is INSUFFICIENT_EVIDENCE. Stricter,
    # not weaker; every other assertion of this test is unchanged.
    v = manager.evaluate(HID)
    assert v.verdict is Verdict.INSUFFICIENT_EVIDENCE
    assert "SAMPLE_TOO_SMALL" in v.reasons


@pytest.mark.parametrize("target", ["0" * 64, "not-a-hash"])
def test_a16_successor_must_reference_an_existing_run(registry, manager, target):
    _register(registry)
    manager.register_experiment(HID)
    manager.start(HID)
    with pytest.raises(MalformedRunError):
        manager.record_run(HID, _run(supersedes=target))


def test_a16_a_run_cannot_be_superseded_twice(registry, manager):
    _register(registry)
    manager.register_experiment(HID)
    manager.start(HID)
    first = manager.record_run(HID, _run(refs=("a",)))
    manager.record_run(HID, _run(refs=("b",), supersedes=first.entry_hash))
    with pytest.raises(MalformedRunError):
        manager.record_run(HID, _run(refs=("c",), supersedes=first.entry_hash))


def test_a16_verdict_change_is_a_successor_and_repeat_is_idempotent(registry, manager):
    _register(registry)
    _record_test(registry)
    manager.register_experiment(HID)
    manager.start(HID)
    manager.record_run(HID, _run(sample_size=10))
    manager.complete(HID)
    first = manager.evaluate(HID)
    assert first.verdict is Verdict.INSUFFICIENT_EVIDENCE and first.supersedes is None
    again = manager.evaluate(HID)
    assert again == first
    assert len(manager.verdicts(HID)) == 1


def test_a16_changed_verdict_supersedes_the_previous_one(registry, manager):
    _register(registry)
    manager.register_experiment(HID)
    _complete(manager)
    first = manager.evaluate(HID)
    assert first.verdict is Verdict.INSUFFICIENT_EVIDENCE
    _record_test(registry, verdict=CheckVerdict.FAIL)  # the check arrives later
    second = manager.evaluate(HID)
    assert second.verdict is Verdict.REJECTED
    assert second.supersedes == first.entry_hash
    assert manager.verdicts(HID) == (first, second)
    assert manager.latest_verdict(HID) == second


def test_a16_log_is_read_only_snapshot(registry, manager):
    _register(registry)
    manager.register_experiment(HID)
    snapshot = manager.log
    assert isinstance(snapshot, tuple)
    with pytest.raises(dataclasses.FrozenInstanceError):
        snapshot[0].kind = "X"  # type: ignore[misc]
    json.dumps([e.as_dict() for e in snapshot])


# -- Review remediation (2026-10-04): H1 tamper-safe reads, M1 supersession, M2 evidence binding --


def _rejected_experiment(registry, manager):
    _register(registry)
    _record_test(registry)
    manager.register_experiment(HID)
    _complete(manager)
    v = manager.evaluate(HID)
    assert v.verdict is Verdict.REJECTED
    return v


def test_h1_mutating_a_returned_log_payload_cannot_forge_supported(registry, manager):
    _rejected_experiment(registry, manager)
    with pytest.raises(TypeError):
        manager.log[-1].payload["verdict"] = "SUPPORTED"  # the exact review attack
    with pytest.raises((TypeError, AttributeError)):
        manager.log[-1].payload["reasons"].append("x")
    assert manager.latest_verdict(HID).verdict is Verdict.REJECTED
    assert all(v.verdict is not Verdict.SUPPORTED for v in manager.verdicts(HID))
    assert not manager.halted


def test_h1_run_and_verdict_views_are_immutable(registry, manager):
    _rejected_experiment(registry, manager)
    run = manager.runs(HID)[0]
    with pytest.raises(TypeError):
        run.payload["run"]["sample_size"] = 1_000_000
    with pytest.raises(TypeError):
        manager.effective_runs(HID)[0].payload["run"]["metrics"]["mean_excess_return"] = 9.9
    with pytest.raises(AttributeError):
        run.payload["run"]["evidence_refs"].append("forged")
    exported = run.as_dict()          # a plain copy: changing it changes nothing
    exported["payload"]["run"]["sample_size"] = 1
    assert manager.runs(HID)[0].payload["run"]["sample_size"] == 500
    record = manager.latest_verdict(HID)
    assert isinstance(record.reasons, tuple)
    with pytest.raises(dataclasses.FrozenInstanceError):
        record.verdict = Verdict.SUPPORTED  # type: ignore[misc]
    assert manager.latest_verdict(HID).verdict is Verdict.REJECTED
    manager.verify_log()
    assert not manager.halted


@pytest.mark.parametrize("read", ["log", "runs", "effective_runs", "verdicts", "latest_verdict"])
def test_h1_every_public_read_verifies_the_chain_and_halts(tmp_path, read):
    reg = HypothesisRegistry(registry_path=tmp_path / "r.json")
    mgr = ExperimentManager(registry=reg)
    _rejected_experiment(reg, mgr)
    entry = mgr._log[-1]  # in-process forgery of the stored verdict, hash left stale
    mgr._log[-1] = replace(entry, payload={**entry.payload, "verdict": "SUPPORTED"})
    call = (lambda: mgr.log) if read == "log" else (lambda: getattr(mgr, read)(HID))
    with pytest.raises(ExperimentIntegrityError):
        call()
    assert mgr.halted
    for again in ("runs", "effective_runs", "verdicts", "latest_verdict", "experiment"):
        with pytest.raises(ExperimentManagerHalted):
            getattr(mgr, again)(HID)


def test_h1_halted_contract_reads_writes_and_forensic_log(registry, manager):
    _rejected_experiment(registry, manager)
    entry = manager._log[-1]
    manager._log[-1] = replace(entry, payload={**entry.payload, "verdict": "SUPPORTED"})
    with pytest.raises(ExperimentIntegrityError):
        manager.verify_log()
    for call in (
        lambda: manager.abort(HID, reason=""),   # validation never pre-empts the halt
        lambda: manager.abort(HID, reason="x"),
        lambda: manager.evaluate(HID),
        lambda: manager.latest_verdict(HID),
    ):
        with pytest.raises(ExperimentManagerHalted):
            call()
    forensic = manager.log                     # readable, frozen, untrusted after a halt
    assert isinstance(forensic, tuple) and manager.halted
    with pytest.raises(TypeError):
        forensic[-1].payload["verdict"] = "REJECTED"


def test_m1_superseding_a_small_run_with_a_large_one_cannot_reject(registry, manager):
    _register(registry)
    _record_test(registry)
    manager.register_experiment(HID)
    manager.start(HID)
    small = manager.record_run(HID, _run(sample_size=5, refs=("small",)))
    manager.record_run(HID, _run(sample_size=500, refs=("large",), supersedes=small.entry_hash))
    manager.complete(HID)
    v = manager.evaluate(HID)
    assert v.verdict is Verdict.INSUFFICIENT_EVIDENCE and "SAMPLE_TOO_SMALL" in v.reasons
    assert [r.payload["run"]["sample_size"] for r in manager.runs(HID)] == [5, 500]   # provenance kept
    assert [r.payload["run"]["sample_size"] for r in manager.effective_runs(HID)] == [500]


def test_m1_without_supersession_the_same_large_run_rejects(registry, manager):
    """Control: the M1 rule blocks the hidden small sample, not REJECTED itself."""
    _register(registry)
    _record_test(registry)
    manager.register_experiment(HID)
    manager.start(HID)
    manager.record_run(HID, _run(sample_size=500, refs=("large",)))
    manager.complete(HID)
    assert manager.evaluate(HID).verdict is Verdict.REJECTED


def _stored_evaluations(registry):
    return registry.get(HID).evaluations


def test_m2_verdict_is_bound_to_the_evidence_it_relied_on(registry, manager):
    v = _rejected_experiment(registry, manager)
    snapshot = ExperimentManager._evidence_snapshot(registry.get(HID))
    assert v.evidence_hash == ExperimentManager._evidence_hash(snapshot)
    assert v.evidence_after_completion is False
    assert manager.log[-1].payload["evidence_snapshot"] == snapshot


def test_m2_altering_adjudicated_evidence_halts_instead_of_changing_the_verdict(registry, manager):
    _register(registry)
    _record_test(registry, verdict=CheckVerdict.PASS)
    manager.register_experiment(HID)
    _complete(manager)
    assert manager.evaluate(HID).verdict is Verdict.INSUFFICIENT_EVIDENCE
    record = registry.get(HID)
    flipped = replace(
        record.evaluations[-1],
        checks=(CheckResult(check_name=CheckName.OUT_OF_SAMPLE, verdict=CheckVerdict.FAIL,
                            statistic_value=-0.2),),
    )   # in-place PASS -> FAIL: the registry itself cannot see this edit
    registry._records[HID] = replace(record, evaluations=record.evaluations[:-1] + (flipped,))
    with pytest.raises(ExperimentIntegrityError):
        manager.evaluate(HID)
    assert manager.halted
    with pytest.raises(ExperimentManagerHalted):
        manager.latest_verdict(HID)


def test_m2_removing_adjudicated_evidence_halts(registry, manager):
    _rejected_experiment(registry, manager)
    record = registry.get(HID)
    registry._records[HID] = replace(record, evaluations=())
    with pytest.raises(ExperimentIntegrityError):
        manager.evaluate(HID)
    assert manager.halted


def test_m2_evidence_altered_between_registration_and_completion_halts(registry, manager):
    _register(registry)
    _record_test(registry)
    manager.register_experiment(HID)            # pins the FAIL evaluation
    manager.start(HID)
    record = registry.get(HID)
    registry._records[HID] = replace(record, evaluations=())
    with pytest.raises(ExperimentIntegrityError):
        manager.record_run(HID, _run())
    assert manager.halted


def test_m2_evidence_inserted_before_a_pinned_evaluation_halts(registry, manager):
    _rejected_experiment(registry, manager)
    record = registry.get(HID)
    extra = replace(record.evaluations[-1], segment="TRAIN", checks=())
    registry._records[HID] = replace(record, evaluations=(extra,) + record.evaluations)
    with pytest.raises(ExperimentIntegrityError):
        manager.evaluate(HID)
    assert manager.halted


def test_m2_appended_evidence_is_an_explicit_flagged_successor(registry, manager):
    _register(registry)
    manager.register_experiment(HID)
    _complete(manager)
    first = manager.evaluate(HID)
    assert first.verdict is Verdict.INSUFFICIENT_EVIDENCE and first.evidence_after_completion is False
    _record_test(registry, verdict=CheckVerdict.FAIL)   # appended via the registry's own write path
    second = manager.evaluate(HID)
    assert second.verdict is Verdict.REJECTED
    assert second.supersedes == first.entry_hash
    assert second.evidence_after_completion is True
    assert second.evidence_hash != first.evidence_hash
    assert second.evidence_hash == ExperimentManager._evidence_hash(
        ExperimentManager._evidence_snapshot(registry.get(HID)))
    assert manager.evaluate(HID) == second            # idempotent while nothing changes
    assert manager.verdicts(HID) == (first, second)


def test_m2_appended_evidence_with_an_unchanged_verdict_still_rebinds(registry, manager):
    _register(registry, criteria=None)                  # no sealed criteria: never REJECTED
    manager.register_experiment(HID)
    _complete(manager)
    first = manager.evaluate(HID)
    _record_test(registry, verdict=CheckVerdict.FAIL)
    second = manager.evaluate(HID)
    assert first.verdict is second.verdict is Verdict.INSUFFICIENT_EVIDENCE
    assert second.supersedes == first.entry_hash and second.evidence_after_completion is True
    assert second.evidence_hash != first.evidence_hash
