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
