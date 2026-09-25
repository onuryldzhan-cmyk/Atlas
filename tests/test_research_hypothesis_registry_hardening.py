"""Owner brief 2026-09-25, Part I - hypothesis registry hardening.

Three gaps identified in
``checkpoints/20260925T185500Z_batch-i-hypothesis-registry-already-built.md``
(items 5, 4 and 6), closed in that order:

1. **Truncated-file refusal.** A registry file missing its ``records`` or
   ``family_manifests`` key (or carrying a non-list value for either) must
   fail closed rather than load as an empty registry.
2. **Family manifest sealing.** Deleting a hypothesis record from the file
   must no longer silently shrink what ``adjudicate_family`` treats as the
   family, because that would inflate the survivors' BH power.
3. **State hash chain.** A hand-edited ``state`` field must no longer load
   as a silently-promoted hypothesis.

Every registry in this file writes into ``tmp_path``. Nothing here touches
the repository's real runtime state, and none exists to touch: no
hypothesis registry file has ever been checked into this repository.
"""

from __future__ import annotations

import json

import pytest

from research.hypothesis_registry import (
    CheckName,
    CheckPlan,
    CheckResult,
    CheckVerdict,
    EvaluationRecord,
    FamilyManifest,
    FamilyMembershipTamperedError,
    HypothesisRegistry,
    PreRegistration,
    REGISTRY_FORMAT_VERSION,
    RegistryError,
    SealVerificationError,
    StateChainError,
    StateTransition,
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


def load_raw(path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def write_raw(path, payload: dict) -> None:
    path.write_text(json.dumps(payload), encoding="utf-8")


# ===========================================================================
# item 1: truncated-file refusal
# ===========================================================================


def test_a_missing_records_key_is_refused_not_read_as_empty(tmp_path):
    path = tmp_path / "hypotheses.json"
    write_raw(path, {"version": REGISTRY_FORMAT_VERSION, "family_manifests": []})

    with pytest.raises(RegistryError, match="records"):
        HypothesisRegistry(registry_path=path)


def test_a_non_list_records_field_is_refused(tmp_path):
    path = tmp_path / "hypotheses.json"
    write_raw(
        path,
        {"version": REGISTRY_FORMAT_VERSION, "records": "not-a-list", "family_manifests": []},
    )

    with pytest.raises(RegistryError, match="records"):
        HypothesisRegistry(registry_path=path)


def test_a_missing_family_manifests_key_is_refused(tmp_path):
    path = tmp_path / "hypotheses.json"
    write_raw(path, {"version": REGISTRY_FORMAT_VERSION, "records": []})

    with pytest.raises(RegistryError, match="family_manifests"):
        HypothesisRegistry(registry_path=path)


def test_a_non_list_family_manifests_field_is_refused(tmp_path):
    path = tmp_path / "hypotheses.json"
    write_raw(
        path,
        {"version": REGISTRY_FORMAT_VERSION, "records": [], "family_manifests": "x"},
    )

    with pytest.raises(RegistryError, match="family_manifests"):
        HypothesisRegistry(registry_path=path)


def test_a_non_object_top_level_payload_is_refused(tmp_path):
    path = tmp_path / "hypotheses.json"
    write_raw_list = json.dumps([1, 2, 3])
    path.write_text(write_raw_list, encoding="utf-8")

    with pytest.raises(RegistryError, match="not a JSON object"):
        HypothesisRegistry(registry_path=path)


def test_a_registry_with_no_file_yet_is_genuinely_empty(tmp_path):
    """The one legitimate way to have zero records: the file was never
    written, because nothing has ever been registered. This must still
    succeed - the hardening targets a truncated *existing* file, not a
    registry that has not been used yet."""
    path = tmp_path / "hypotheses.json"
    assert not path.exists()

    registry = HypothesisRegistry(registry_path=path)

    assert len(registry) == 0


# ===========================================================================
# item 2: family manifest sealing
# ===========================================================================


def test_registering_two_hypotheses_builds_an_ordered_manifest(registry):
    registry.register(make_preregistration(hypothesis_id="HYP-0001"))
    registry.register(
        make_preregistration(hypothesis_id="HYP-0002", title="A related idea")
    )

    manifest = registry.family_manifest("FAM-REVERSAL-2026Q3")
    assert manifest is not None
    assert manifest.member_ids == ("HYP-0001", "HYP-0002")


def test_manifest_is_none_for_an_unregistered_family(registry):
    assert registry.family_manifest("FAM-NEVER-SEEN") is None


def test_manifest_survives_a_reload(tmp_path):
    path = tmp_path / "hypotheses.json"
    registry = HypothesisRegistry(registry_path=path)
    registry.register(make_preregistration(hypothesis_id="HYP-0001"))
    registry.register(
        make_preregistration(hypothesis_id="HYP-0002", title="A related idea")
    )

    reloaded = HypothesisRegistry(registry_path=path)
    manifest = reloaded.family_manifest("FAM-REVERSAL-2026Q3")
    assert manifest.member_ids == ("HYP-0001", "HYP-0002")


def test_deleting_a_member_record_is_caught_on_reload(tmp_path):
    """The property this item exists for: dropping a losing hypothesis from
    ``records`` must not silently shrink the family BH corrects over."""
    path = tmp_path / "hypotheses.json"
    registry = HypothesisRegistry(registry_path=path)
    registry.register(make_preregistration(hypothesis_id="HYP-0001"))
    registry.register(
        make_preregistration(hypothesis_id="HYP-0002", title="A related idea")
    )

    payload = load_raw(path)
    assert len(payload["records"]) == 2
    payload["records"] = [
        entry
        for entry in payload["records"]
        if entry["preregistration"]["hypothesis_id"] != "HYP-0002"
    ]
    write_raw(path, payload)

    with pytest.raises(FamilyMembershipTamperedError, match="HYP-0002|deleted"):
        HypothesisRegistry(registry_path=path)


def test_a_tampered_manifest_hash_is_caught(tmp_path):
    """Editing member_ids without recomputing manifest_hash is the cheapest
    tamper attempt, and the seal alone catches it."""
    path = tmp_path / "hypotheses.json"
    registry = HypothesisRegistry(registry_path=path)
    registry.register(make_preregistration(hypothesis_id="HYP-0001"))
    registry.register(
        make_preregistration(hypothesis_id="HYP-0002", title="A related idea")
    )

    payload = load_raw(path)
    payload["family_manifests"][0]["member_ids"] = ["HYP-0001"]
    write_raw(path, payload)

    with pytest.raises(SealVerificationError, match="family manifest seal mismatch"):
        HypothesisRegistry(registry_path=path)


def test_a_self_consistent_forged_manifest_is_still_caught_by_cross_check(tmp_path):
    """A more careful tamper: shrink member_ids AND recompute the manifest's
    own hash, so the manifest is internally consistent. The cross-check
    against the actual records - not the manifest's own seal - is what
    catches this one."""
    path = tmp_path / "hypotheses.json"
    registry = HypothesisRegistry(registry_path=path)
    registry.register(make_preregistration(hypothesis_id="HYP-0001"))
    registry.register(
        make_preregistration(hypothesis_id="HYP-0002", title="A related idea")
    )

    forged = FamilyManifest(family_id="FAM-REVERSAL-2026Q3", member_ids=("HYP-0001",))
    payload = load_raw(path)
    payload["family_manifests"][0] = forged.as_dict()
    write_raw(path, payload)

    with pytest.raises(FamilyMembershipTamperedError):
        HypothesisRegistry(registry_path=path)


def test_a_record_added_outside_register_with_no_manifest_entry_is_caught(tmp_path):
    path = tmp_path / "hypotheses.json"
    registry = HypothesisRegistry(registry_path=path)
    registry.register(make_preregistration(hypothesis_id="HYP-0001"))

    other_registry_path = tmp_path / "donor.json"
    donor = HypothesisRegistry(registry_path=other_registry_path)
    donor.register(
        make_preregistration(
            hypothesis_id="HYP-0002",
            title="A smuggled-in hypothesis",
            family_id="FAM-REVERSAL-2026Q3",
        )
    )
    donor_payload = load_raw(other_registry_path)

    payload = load_raw(path)
    payload["records"].append(donor_payload["records"][0])
    # Deliberately do NOT touch family_manifests: this record was spliced in
    # directly, not through register(), so no manifest was ever extended for
    # it.
    write_raw(path, payload)

    with pytest.raises(FamilyMembershipTamperedError):
        HypothesisRegistry(registry_path=path)


def test_an_orphaned_manifest_with_no_records_is_caught(tmp_path):
    path = tmp_path / "hypotheses.json"
    registry = HypothesisRegistry(registry_path=path)
    registry.register(make_preregistration(hypothesis_id="HYP-0001"))

    payload = load_raw(path)
    payload["records"] = []
    write_raw(path, payload)

    with pytest.raises(FamilyMembershipTamperedError, match="no recorded hypotheses"):
        HypothesisRegistry(registry_path=path)


def test_family_manifest_rejects_a_duplicate_member(registry):
    manifest = FamilyManifest(family_id="FAM-X-1", member_ids=("HYP-0001",))
    with pytest.raises(RegistryError, match="already a member"):
        manifest.extended("HYP-0001")


def test_family_manifest_requires_at_least_one_member():
    with pytest.raises(RegistryError, match="at least one member"):
        FamilyManifest(family_id="FAM-X-1", member_ids=())


# ===========================================================================
# item 3: state hash chain
# ===========================================================================


def test_registration_seals_a_one_link_genesis_chain(registry):
    record = registry.register(make_preregistration())
    assert len(record.state_chain) == 1
    assert record.state_chain[0].from_state is None
    assert record.state_chain[0].to_state is HypothesisState.REGISTERED
    record.verify_state_chain()


def test_the_chain_grows_one_link_per_transition_through_full_lifecycle(registry):
    registry.register(make_preregistration())
    calibrate(registry, "HYP-0001")
    run_test_segment(registry, "HYP-0001", p_value=0.01, effect_size=1.0)
    decision = registry.adjudicate_family("FAM-REVERSAL-2026Q3", q=0.10)
    assert decision.is_rejected("HYP-0001")

    record = registry.get("HYP-0001")
    assert record.state is HypothesisState.CANDIDATE
    assert [t.to_state for t in record.state_chain] == [
        HypothesisState.REGISTERED,
        HypothesisState.CALIBRATED,
        HypothesisState.TESTED,
        HypothesisState.CANDIDATE,
    ]
    record.verify_state_chain()


def test_the_chain_survives_a_reload(tmp_path):
    path = tmp_path / "hypotheses.json"
    registry = HypothesisRegistry(registry_path=path)
    registry.register(make_preregistration())
    calibrate(registry, "HYP-0001")

    reloaded = HypothesisRegistry(registry_path=path)
    record = reloaded.get("HYP-0001")
    assert [t.to_state for t in record.state_chain] == [
        HypothesisState.REGISTERED,
        HypothesisState.CALIBRATED,
    ]


def test_a_hand_edited_state_with_no_matching_chain_link_is_refused(tmp_path):
    """The property this item exists for: a hand-edited CANDIDATE must not
    load as promoted."""
    path = tmp_path / "hypotheses.json"
    registry = HypothesisRegistry(registry_path=path)
    registry.register(make_preregistration())

    payload = load_raw(path)
    payload["records"][0]["state"] = "CANDIDATE"
    write_raw(path, payload)

    with pytest.raises(StateChainError, match="stored state is CANDIDATE"):
        HypothesisRegistry(registry_path=path)


def test_a_tampered_chain_hash_is_caught(tmp_path):
    path = tmp_path / "hypotheses.json"
    registry = HypothesisRegistry(registry_path=path)
    registry.register(make_preregistration())
    calibrate(registry, "HYP-0001")

    payload = load_raw(path)
    # Edit a link's content without recomputing the fold hash.
    payload["records"][0]["state_chain"][1]["recorded_at"] = "2030-01-01T00:00:00+00:00"
    write_raw(path, payload)

    with pytest.raises(StateChainError, match="state chain hash mismatch"):
        HypothesisRegistry(registry_path=path)


def test_a_forged_but_illegal_chain_is_caught(tmp_path):
    """Even a chain whose fold hash was correctly recomputed after the edit
    (a more careful forgery) is refused, because REGISTERED -> CANDIDATE
    directly is not a legal lifecycle transition."""
    path = tmp_path / "hypotheses.json"
    registry = HypothesisRegistry(registry_path=path)
    registry.register(make_preregistration())

    forged_chain = (
        StateTransition(from_state=None, to_state=HypothesisState.REGISTERED),
        StateTransition(
            from_state=HypothesisState.REGISTERED, to_state=HypothesisState.CANDIDATE
        ),
    )
    from research.hypothesis_registry import _fold_state_chain

    payload = load_raw(path)
    payload["records"][0]["state"] = "CANDIDATE"
    payload["records"][0]["state_chain"] = [t.as_dict() for t in forged_chain]
    payload["records"][0]["state_chain_hash"] = _fold_state_chain(
        "HYP-0001", forged_chain
    )
    write_raw(path, payload)

    with pytest.raises(StateChainError, match="illegal"):
        HypothesisRegistry(registry_path=path)


def test_a_discontinuous_chain_is_caught(tmp_path):
    path = tmp_path / "hypotheses.json"
    registry = HypothesisRegistry(registry_path=path)
    registry.register(make_preregistration())
    calibrate(registry, "HYP-0001")
    run_test_segment(registry, "HYP-0001", p_value=0.01, effect_size=1.0)

    forged_chain = (
        StateTransition(from_state=None, to_state=HypothesisState.REGISTERED),
        # Skips CALIBRATED: this link's from_state disagrees with the
        # previous link's to_state.
        StateTransition(
            from_state=HypothesisState.CALIBRATED, to_state=HypothesisState.TESTED
        ),
    )
    from research.hypothesis_registry import _fold_state_chain

    payload = load_raw(path)
    payload["records"][0]["state_chain"] = [t.as_dict() for t in forged_chain]
    payload["records"][0]["state_chain_hash"] = _fold_state_chain(
        "HYP-0001", forged_chain
    )
    write_raw(path, payload)

    with pytest.raises(StateChainError, match="starts at"):
        HypothesisRegistry(registry_path=path)


def test_an_empty_state_chain_is_refused(tmp_path):
    path = tmp_path / "hypotheses.json"
    registry = HypothesisRegistry(registry_path=path)
    registry.register(make_preregistration())

    payload = load_raw(path)
    payload["records"][0]["state_chain"] = []
    payload["records"][0]["state_chain_hash"] = "GENESIS"
    write_raw(path, payload)

    with pytest.raises(StateChainError, match="empty state chain"):
        HypothesisRegistry(registry_path=path)


def test_a_missing_state_chain_key_is_refused(tmp_path):
    """Pre-version-3 shaped records (no state_chain at all) must fail to
    load rather than default to an empty chain."""
    path = tmp_path / "hypotheses.json"
    registry = HypothesisRegistry(registry_path=path)
    registry.register(make_preregistration())

    payload = load_raw(path)
    del payload["records"][0]["state_chain"]
    write_raw(path, payload)

    with pytest.raises(RegistryError, match="state_chain"):
        HypothesisRegistry(registry_path=path)


def test_a_genesis_link_that_does_not_land_on_registered_is_refused(tmp_path):
    path = tmp_path / "hypotheses.json"
    registry = HypothesisRegistry(registry_path=path)
    registry.register(make_preregistration())

    forged_chain = (StateTransition(from_state=None, to_state=HypothesisState.TESTED),)
    from research.hypothesis_registry import _fold_state_chain

    payload = load_raw(path)
    payload["records"][0]["state"] = "TESTED"
    payload["records"][0]["state_chain"] = [t.as_dict() for t in forged_chain]
    payload["records"][0]["state_chain_hash"] = _fold_state_chain(
        "HYP-0001", forged_chain
    )
    write_raw(path, payload)

    with pytest.raises(StateChainError, match="genesis"):
        HypothesisRegistry(registry_path=path)
