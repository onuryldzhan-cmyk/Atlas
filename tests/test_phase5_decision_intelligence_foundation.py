from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal as D

import pytest

from core.decision_intelligence import (
    Action, CanonicalDecision, Evidence, EvidenceStatus, FreshnessPolicy,
    FusionPolicy, ModelRequest, ModelResponse, ModelStatus,
    OfflineLearningBoundary, SignalFusion, StrategyDescriptor, StrategyRegistry,
    model_response_to_evidence,
)


NOW = datetime(2026, 7, 30, 12, tzinfo=UTC)


def ev(source="technical", action=Action.BUY, score="0.8", *, eid=None,
       symbol="BTCUSDT", observed_at=NOW, status=EvidenceStatus.VALID,
       provider=None, model=None):
    return Evidence(eid or f"{source}-1", source, "1", symbol, action, score,
                    observed_at, status, model_provider=provider, model_name=model)


def policy(**changes):
    values = dict(weights={"technical": D("1"), "regime": D("1")},
                  freshness=FreshnessPolicy(timedelta(minutes=5)), minimum_sources=1,
                  decision_threshold=D("0.2"))
    values.update(changes)
    return FusionPolicy(**values)


@pytest.mark.parametrize("action", list(Action))
def test_canonical_actions_and_deterministic_audit_contract(action):
    source = ev(action=action, score="0.8")
    fusion = SignalFusion(policy()).fuse("BTCUSDT", [source], now=NOW)
    first = CanonicalDecision.from_fusion("BTCUSDT", fusion, timestamp=NOW)
    second = CanonicalDecision.from_fusion("BTCUSDT", fusion, timestamp=NOW)
    assert first.decision_id == second.decision_id
    assert first.authority == "PROPOSAL_ONLY"
    assert first.audit_record()["confidence_is_probability"] is False
    assert first.audit_record()["evidence_ids"] == [source.evidence_id]


def test_invalid_actions_bounds_non_finite_and_float_rejected():
    with pytest.raises(ValueError): ev(action="EXECUTE")
    for value in (D("-0.1"), D("1.1"), D("NaN"), D("Infinity"), 0.5):
        with pytest.raises(ValueError): ev(score=value)


def test_agreement_conflict_missing_and_deterministic_repeat():
    fusion = SignalFusion(policy(minimum_sources=2))
    inputs = [ev(), ev("regime", score="0.6")]
    assert fusion.fuse("BTCUSDT", inputs, now=NOW).action is Action.BUY
    assert fusion.fuse("BTCUSDT", inputs, now=NOW) == fusion.fuse("BTCUSDT", reversed(inputs), now=NOW)
    conflict = fusion.fuse("BTCUSDT", [ev(), ev("regime", Action.SELL, "0.8")], now=NOW)
    assert conflict.action is Action.ABSTAIN and conflict.disagreement == D("1.000000")
    assert fusion.fuse("BTCUSDT", [], now=NOW).reason_codes == ("INSUFFICIENT_VALID_EVIDENCE",)


def test_duplicate_stale_invalid_future_and_wrong_symbol_never_inflate():
    fusion = SignalFusion(policy())
    good = ev(score="0.4")
    duplicate = ev(score="1", eid="technical-2")
    result = fusion.fuse("BTCUSDT", [good, duplicate], now=NOW)
    assert result.confidence == D("0.400000")
    assert ("technical-2", "DUPLICATE_SOURCE") in result.rejected
    bad = [
        ev(observed_at=NOW - timedelta(minutes=6), eid="old"),
        ev(observed_at=NOW + timedelta(minutes=1), eid="future"),
        ev(symbol="ETHUSDT", eid="wrong"),
        ev(status=EvidenceStatus.INVALID, eid="invalid"),
    ]
    result = fusion.fuse("BTCUSDT", bad, now=NOW)
    assert result.action is Action.ABSTAIN and result.confidence == 0
    assert {reason for _, reason in result.rejected} == {"STALE", "INVALID", "WRONG_SYMBOL"}


def test_unconfigured_source_and_missing_required_evidence_abstain():
    result = SignalFusion(policy()).fuse("BTCUSDT", [ev("macro")], now=NOW)
    assert result.action is Action.ABSTAIN
    assert result.rejected == (("macro-1", "UNCONFIGURED_SOURCE"),)


def request():
    return ModelRequest("req-1", "BTCUSDT", "v1", {"evidence": ["t-1"]}, 1000)


def response(output, status=ModelStatus.OK, request_id="req-1"):
    return ModelResponse("mock-provider", "mock-model", request_id, status, output, 5)


def test_provider_neutral_structured_model_output_and_attribution():
    output = {"action": "BUY", "confidence": "0.7", "symbol": "BTCUSDT",
              "evidence_ids": ["t-1"], "reason_codes": ["MODEL_SUPPORT"]}
    item = model_response_to_evidence(response(output), request(), observed_at=NOW)
    assert item.action is Action.BUY and item.score == D("0.7")
    assert (item.model_provider, item.model_name) == ("mock-provider", "mock-model")


@pytest.mark.parametrize("output,status,reason", [
    (None, ModelStatus.OK, "MALFORMED_MODEL_OUTPUT"),
    ({"action": "BUY", "confidence": "2", "symbol": "BTCUSDT", "evidence_ids": ["x"]}, ModelStatus.OK, "MODEL_CONFIDENCE_OUT_OF_BOUNDS"),
    ({"action": "BUY", "confidence": "0.5", "symbol": "HALLUCINATED", "evidence_ids": ["x"]}, ModelStatus.OK, "MODEL_SYMBOL_MISMATCH"),
    ({"action": "BUY", "confidence": "0.5", "symbol": "BTCUSDT", "evidence_ids": []}, ModelStatus.OK, "MODEL_EVIDENCE_REQUIRED"),
    ({"action": "BUY", "confidence": "0.5", "symbol": "BTCUSDT", "evidence_ids": ["x"], "tool_call": "execute"}, ModelStatus.OK, "MALFORMED_MODEL_OUTPUT"),
    ({}, ModelStatus.TIMEOUT, "MODEL_UNAVAILABLE"),
])
def test_untrusted_model_output_fails_closed(output, status, reason):
    item = model_response_to_evidence(response(output, status), request(), observed_at=NOW)
    assert item.action is Action.ABSTAIN and item.score == 0
    assert item.reason_codes == (reason,)


def test_no_silent_provider_fallback_or_request_substitution():
    item = model_response_to_evidence(response({}, request_id="other"), request(), observed_at=NOW)
    assert item.action is Action.ABSTAIN and item.reason_codes == ("MODEL_UNAVAILABLE",)


class StubStrategy:
    def __init__(self, enabled=True, source="strategy:trend:v1"):
        self.descriptor = StrategyDescriptor("trend", "v1", frozenset({"BTCUSDT"}),
                                             frozenset({"SPOT"}), frozenset({"close"}), enabled=enabled)
        self.source = source

    def generate(self, symbol, inputs, now):
        return ev(self.source, eid="trend-1", symbol=symbol, observed_at=now)


def test_strategy_registry_preserves_attribution_and_filters_safely():
    registry = StrategyRegistry(); registry.register(StubStrategy())
    assert registry.generate("BTCUSDT", "SPOT", {"close": D("1")}, NOW)[0].source == "strategy:trend:v1"
    assert registry.generate("ETHUSDT", "SPOT", {"close": D("1")}, NOW) == ()
    assert registry.generate("BTCUSDT", "SPOT", {}, NOW) == ()
    with pytest.raises(ValueError): registry.register(StubStrategy())
    disabled = StrategyRegistry(); disabled.register(StubStrategy(enabled=False))
    assert disabled.generate("BTCUSDT", "SPOT", {"close": D("1")}, NOW) == ()


def test_invalid_strategy_output_rejected():
    registry = StrategyRegistry(); registry.register(StubStrategy(source="spoofed"))
    with pytest.raises(ValueError, match="attribution"):
        registry.generate("BTCUSDT", "SPOT", {"close": D("1")}, NOW)


def test_material_decision_requires_evidence_and_cannot_gain_execution_authority():
    base = dict(decision_id="x", symbol="BTCUSDT", action=Action.BUY, confidence=D(".5"),
                timestamp=NOW, strategy_sources=(), evidence_ids=(), reason_codes=("x",),
                data_status=EvidenceStatus.INVALID, policy_version="v1")
    with pytest.raises(ValueError, match="valid evidence"): CanonicalDecision(**base)
    base.update(action=Action.ABSTAIN, authority="EXECUTE")
    with pytest.raises(ValueError, match="execution authority"): CanonicalDecision(**base)


def test_decision_id_binds_reason_codes_model_attribution_and_market_context():
    source = ev(provider="prov", model="mdl")
    fusion = SignalFusion(policy()).fuse("BTCUSDT", [source], now=NOW)

    baseline = CanonicalDecision.from_fusion("BTCUSDT", fusion, timestamp=NOW)
    same = CanonicalDecision.from_fusion("BTCUSDT", fusion, timestamp=NOW)
    assert baseline.decision_id == same.decision_id

    reason_variant = CanonicalDecision.from_fusion(
        "BTCUSDT", replace(fusion, reason_codes=("DIFFERENT_REASON",)), timestamp=NOW
    )
    assert reason_variant.decision_id != baseline.decision_id

    other_source = ev(provider="other-prov", model="other-mdl")
    other_fusion = SignalFusion(policy()).fuse("BTCUSDT", [other_source], now=NOW)
    assert other_fusion.evidence[0].model_provider != source.model_provider
    model_variant = CanonicalDecision.from_fusion("BTCUSDT", other_fusion, timestamp=NOW)
    assert model_variant.decision_id != baseline.decision_id

    context_variant = CanonicalDecision.from_fusion(
        "BTCUSDT", fusion, timestamp=NOW, market_context={"regime": "risk_on"}
    )
    assert context_variant.decision_id != baseline.decision_id


def test_decision_threshold_boundary_is_not_abstain():
    fusion = SignalFusion(policy(decision_threshold=D("0.2")))
    result = fusion.fuse("BTCUSDT", [ev(score="0.2")], now=NOW)
    assert result.action is Action.BUY
    assert result.confidence == D("0.200000")


def test_decision_threshold_edge_values():
    with pytest.raises(ValueError):
        policy(decision_threshold=D("-0.01"))
    with pytest.raises(ValueError):
        policy(decision_threshold=D("1.01"))
    zero_threshold = SignalFusion(policy(decision_threshold=D("0")))
    assert zero_threshold.fuse("BTCUSDT", [ev(score="0.0001")], now=NOW).action is Action.BUY


def test_freshness_exactly_at_max_age_boundary_is_valid():
    evidence = ev(observed_at=NOW - timedelta(minutes=5))
    assert evidence.quality_at(NOW, FreshnessPolicy(timedelta(minutes=5))) is EvidenceStatus.VALID


def test_minimum_sources_edge_value():
    with pytest.raises(ValueError):
        policy(minimum_sources=0)
    fusion = SignalFusion(policy(minimum_sources=1))
    assert fusion.fuse("BTCUSDT", [ev()], now=NOW).action is Action.BUY


def test_learning_records_and_proposes_but_cannot_self_modify():
    learning = OfflineLearningBoundary(); learning.record_outcome("d1", {"pnl": "1"})
    proposal = learning.propose_parameters("trend", {"weight": "0.8"})
    assert len(learning.outcomes) == 1 and proposal["approved"] is False
    with pytest.raises(PermissionError): learning.mutate_production({"live": True})


def test_module_has_no_direct_execution_or_provider_sdk_dependency():
    import core.decision_intelligence as module
    names = set(vars(module))
    assert not ({"ExecutionManager", "ExchangeManager", "OpenAI", "Anthropic"} & names)
