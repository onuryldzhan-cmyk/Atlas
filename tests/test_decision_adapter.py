from core.decision_adapter import DecisionAdapter


adapter = DecisionAdapter()


decision1 = {
    "action": "BUY",
    "symbol": "BTCUSDT",
    "confidence": 75,
}


decision2 = {
    "decision": "BUY",
    "order": {
        "symbol": "ETHUSDT",
    },
    "strategy_confidence": 82,
}


print(
    adapter.normalize(
        decision1
    )
)


print(
    adapter.normalize(
        decision2
    )
)


print(
    adapter.status()
)


# =========================================================
# PHASE-5 SHADOW-ONLY METADATA TESTS
# =========================================================


CONTROL_FIELDS = (
    "action",
    "confidence",
    "price",
    "risk_level",
)


def _base_decision():
    return {
        "action": "BUY",
        "symbol": "BTCUSDT",
        "confidence": 75,
        "price": 65000.0,
        "risk_level": "MEDIUM",
        "metadata": {"existing_key": "existing_value"},
    }


def test_control_fields_identical_with_and_without_phase5_proposal():
    decision = _base_decision()
    proposal = {"decision_id": "abc123", "action": "SELL", "confidence": "0.99"}

    without = DecisionAdapter().normalize(decision)
    with_proposal = DecisionAdapter().normalize(decision, phase5_proposal=proposal)

    for field in CONTROL_FIELDS:
        assert without[field] == with_proposal[field]


def test_phase5_proposal_attached_only_under_expected_key():
    decision = _base_decision()
    proposal = {"decision_id": "abc123", "action": "SELL", "confidence": "0.99"}

    result = DecisionAdapter().normalize(decision, phase5_proposal=proposal)

    assert result["metadata"]["phase5_proposal"] == proposal
    assert result["action"] == "BUY"
    assert result["confidence"] == 75.0


def test_phase5_proposal_via_audit_record_object():
    class FakeCanonicalDecision:
        def audit_record(self):
            return {"decision_id": "xyz", "authority": "PROPOSAL_ONLY", "action": "SELL"}

    decision = _base_decision()
    result = DecisionAdapter().normalize(decision, phase5_proposal=FakeCanonicalDecision())

    assert result["metadata"]["phase5_proposal"]["authority"] == "PROPOSAL_ONLY"
    assert result["action"] == "BUY"


def test_existing_metadata_preserved_alongside_phase5_proposal():
    decision = _base_decision()
    proposal = {"decision_id": "abc123"}

    result = DecisionAdapter().normalize(decision, phase5_proposal=proposal)

    assert result["metadata"]["existing_key"] == "existing_value"
    assert result["metadata"]["phase5_proposal"] == proposal


def test_malformed_phase5_proposal_does_not_affect_control_fields():
    decision = _base_decision()

    without = DecisionAdapter().normalize(decision)
    with_malformed = DecisionAdapter().normalize(decision, phase5_proposal="not-a-record")

    for field in CONTROL_FIELDS:
        assert without[field] == with_malformed[field]

    assert "phase5_proposal" not in with_malformed["metadata"]


def test_absent_phase5_proposal_does_not_add_metadata_key():
    decision = _base_decision()

    result = DecisionAdapter().normalize(decision)

    assert "phase5_proposal" not in result["metadata"]


def test_existing_normalize_behavior_unchanged_without_proposal():
    result = DecisionAdapter().normalize(decision1)

    assert result["action"] == "BUY"
    assert result["symbol"] == "BTCUSDT"
    assert result["confidence"] == 75.0


# =========================================================
# PHASE-5 METADATA COLLISION TESTS (dual producers of
# metadata["phase5_proposal"]: source metadata vs explicit argument)
# =========================================================


def _decision_with_existing_proposal(proposal):
    decision = _base_decision()
    decision["metadata"] = {
        "existing_key": "existing_value",
        "phase5_proposal": proposal,
    }
    return decision


def test_collision_differing_proposals_explicit_argument_wins():
    existing = {"decision_id": "source-111", "action": "BUY"}
    explicit = {"decision_id": "explicit-222", "action": "SELL"}
    decision = _decision_with_existing_proposal(existing)

    result = DecisionAdapter().normalize(decision, phase5_proposal=explicit)

    assert result["metadata"]["phase5_proposal"] == explicit

    provenance = result["metadata"]["phase5_provenance"]
    assert provenance["collision"] is True
    assert provenance["resolution"] == "explicit_argument"
    assert provenance["source_metadata_proposal"] == existing
    assert provenance["explicit_argument_proposal"] == explicit


def test_collision_identical_proposals_is_idempotent_not_a_conflict():
    proposal = {"decision_id": "same-333", "action": "BUY"}
    decision = _decision_with_existing_proposal(dict(proposal))

    result = DecisionAdapter().normalize(decision, phase5_proposal=dict(proposal))

    assert result["metadata"]["phase5_proposal"] == proposal
    assert "phase5_provenance" not in result["metadata"]


def test_existing_proposal_survives_without_explicit_argument():
    existing = {"decision_id": "source-444", "action": "HOLD"}
    decision = _decision_with_existing_proposal(existing)

    result = DecisionAdapter().normalize(decision)

    assert result["metadata"]["phase5_proposal"] == existing
    assert "phase5_provenance" not in result["metadata"]


def test_no_existing_proposal_explicit_argument_contract_unchanged():
    proposal = {"decision_id": "explicit-only-555"}
    decision = _base_decision()

    result = DecisionAdapter().normalize(decision, phase5_proposal=proposal)

    assert result["metadata"]["phase5_proposal"] == proposal
    assert "phase5_provenance" not in result["metadata"]


def test_collision_malformed_explicit_argument_preserves_existing_proposal():
    existing = {"decision_id": "source-666", "action": "SELL"}
    decision = _decision_with_existing_proposal(existing)

    result = DecisionAdapter().normalize(decision, phase5_proposal="not-a-record")

    assert result["metadata"]["phase5_proposal"] == existing

    provenance = result["metadata"]["phase5_provenance"]
    assert provenance["collision"] is True
    assert provenance["resolution"] == "explicit_argument_rejected_malformed"
    assert provenance["source_metadata_proposal"] == existing
    assert provenance["explicit_argument_status"] == "malformed_or_unusable"
    # The raw malformed object itself must never be stored.
    assert "not-a-record" not in repr(provenance)


def test_collision_scenarios_do_not_affect_control_fields():
    existing = {"decision_id": "source-777"}
    explicit = {"decision_id": "explicit-888"}

    baseline = DecisionAdapter().normalize(_base_decision())

    differing = DecisionAdapter().normalize(
        _decision_with_existing_proposal(existing),
        phase5_proposal=explicit,
    )
    malformed = DecisionAdapter().normalize(
        _decision_with_existing_proposal(existing),
        phase5_proposal="not-a-record",
    )

    for field in CONTROL_FIELDS:
        assert baseline[field] == differing[field]
        assert baseline[field] == malformed[field]


def test_collision_handling_never_causes_normalize_to_return_none():
    existing = {"decision_id": "source-999"}
    explicit = {"decision_id": "explicit-000"}

    result = DecisionAdapter().normalize(
        _decision_with_existing_proposal(existing),
        phase5_proposal=explicit,
    )

    assert result is not None
    assert result["action"] == "BUY"
