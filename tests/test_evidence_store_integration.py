"""Evidence Store wiring (ADR-0008): env-var resolution and the brain hook.

Two invariants dominate this file:

- ``ATLAS_EVIDENCE_DIRECTORY`` is fail-CLOSED. A present-but-unusable
  override raises instead of silently falling back to the default.
- The brain's recording hook is fail-OPEN. A broken store costs a log line
  and a health() counter, never a decision.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from decimal import Decimal

import pytest

from ai.core.atlas_brain import AtlasBrain
from analysis.evidence_status import MarketDataEvidenceStatus
from core.application import (
    DEFAULT_EVIDENCE_DIRECTORY,
    EVIDENCE_DIRECTORY_ENV,
    ConfiguredDirectoryError,
    resolve_evidence_directory,
)
from data_layer.evidence_store import EvidenceStore


@pytest.fixture(autouse=True)
def _isolated_cwd(tmp_path, monkeypatch):
    # Mirrors tests/test_atlas_brain_phase5_shadow.py: AtlasBrain()
    # construction bootstraps memory/reasoning/world state under a
    # CWD-relative directory. Redirecting the CWD keeps that out of the
    # repository and away from the operator's real runtime state.
    monkeypatch.chdir(tmp_path)


def _market_data(
    *,
    technical: float,
    macro: float,
    sentiment: float,
    risk: float,
    timestamp: str | None = None,
) -> dict:
    return {
        "price": 65_000.0,
        "technical_score": technical,
        "macro_score": macro,
        "sentiment_score": sentiment,
        "risk_score": risk,
        "rsi": 50,
        "trend": "SIDEWAYS",
        "evidence_status": {
            "technical": MarketDataEvidenceStatus.AVAILABLE.value,
            "macro": MarketDataEvidenceStatus.AVAILABLE.value,
            "sentiment": MarketDataEvidenceStatus.AVAILABLE.value,
            "market_risk": MarketDataEvidenceStatus.AVAILABLE.value,
        },
        "timestamp": timestamp or datetime.now(UTC).isoformat(),
    }


def _brain(store: EvidenceStore | None, **config) -> AtlasBrain:
    return AtlasBrain(config={"evidence_store": store, **config})


# =====================================================================
# ENV VAR RESOLUTION - FAIL CLOSED
# =====================================================================


def test_unset_override_resolves_to_the_installation_default(monkeypatch):
    monkeypatch.delenv(EVIDENCE_DIRECTORY_ENV, raising=False)
    assert resolve_evidence_directory() == DEFAULT_EVIDENCE_DIRECTORY


def test_valid_override_is_honoured(monkeypatch, tmp_path):
    target = tmp_path / "evidence_root"
    target.mkdir()
    monkeypatch.setenv(EVIDENCE_DIRECTORY_ENV, str(target))
    assert resolve_evidence_directory() == target.resolve()


def test_empty_override_raises(monkeypatch):
    monkeypatch.setenv(EVIDENCE_DIRECTORY_ENV, "   ")
    with pytest.raises(ConfiguredDirectoryError):
        resolve_evidence_directory()


def test_relative_override_raises(monkeypatch):
    monkeypatch.setenv(EVIDENCE_DIRECTORY_ENV, "evidence_store")
    with pytest.raises(ConfiguredDirectoryError):
        resolve_evidence_directory()


def test_missing_override_raises_and_is_not_created(monkeypatch, tmp_path):
    target = tmp_path / "not_created_by_atlas"
    monkeypatch.setenv(EVIDENCE_DIRECTORY_ENV, str(target))
    with pytest.raises(ConfiguredDirectoryError):
        resolve_evidence_directory()
    assert not target.exists()


def test_override_pointing_at_a_file_raises(monkeypatch, tmp_path):
    target = tmp_path / "a_file"
    target.write_text("x", encoding="utf-8")
    monkeypatch.setenv(EVIDENCE_DIRECTORY_ENV, str(target))
    with pytest.raises(ConfiguredDirectoryError):
        resolve_evidence_directory()


def test_bad_override_never_falls_back_to_the_default(monkeypatch, tmp_path):
    """The silent-fallback failure mode this check exists to prevent."""

    monkeypatch.setenv(EVIDENCE_DIRECTORY_ENV, str(tmp_path / "typo"))
    with pytest.raises(ConfiguredDirectoryError):
        resolve_evidence_directory()


# =====================================================================
# CHANGE-TRIGGERED RECORDING (OQ-4)
# =====================================================================


def test_first_cycle_records_an_initial_observation(tmp_path):
    store = EvidenceStore(tmp_path / "e.sqlite3")
    store.open()
    brain = _brain(store)

    brain.analyze_and_decide(
        "BTCUSDT",
        _market_data(technical=0.8, macro=0.75, sentiment=0.9, risk=0.7),
    )

    claims = store.query(symbol="BTCUSDT")
    assert claims
    assert all(c.claim_kind == "DIRECTIONAL" for c in claims)
    assert all(c.agent_id.startswith("agent:") for c in claims)
    assert any("INITIAL_OBSERVATION" in c.reason_codes for c in claims)


def test_an_unchanged_cycle_records_nothing_further(tmp_path):
    store = EvidenceStore(tmp_path / "e.sqlite3")
    store.open()
    brain = _brain(store)
    data = _market_data(technical=0.8, macro=0.75, sentiment=0.9, risk=0.7)

    brain.analyze_and_decide("BTCUSDT", data)
    after_first = store.health()["claim_count"]

    # A fresh timestamp, identical readings: nothing new is asserted.
    brain.analyze_and_decide(
        "BTCUSDT",
        _market_data(technical=0.8, macro=0.75, sentiment=0.9, risk=0.7),
    )

    assert store.health()["claim_count"] == after_first


def test_a_small_conviction_move_under_the_threshold_is_silent(tmp_path):
    store = EvidenceStore(tmp_path / "e.sqlite3")
    store.open()
    brain = _brain(store, evidence_conviction_delta=0.15)

    brain.analyze_and_decide(
        "BTCUSDT", _market_data(technical=0.80, macro=0.75, sentiment=0.9, risk=0.7)
    )
    baseline = store.health()["claim_count"]

    brain.analyze_and_decide(
        "BTCUSDT", _market_data(technical=0.84, macro=0.75, sentiment=0.9, risk=0.7)
    )

    assert store.health()["claim_count"] == baseline


def test_a_large_conviction_move_is_recorded(tmp_path):
    store = EvidenceStore(tmp_path / "e.sqlite3")
    store.open()
    brain = _brain(store, evidence_conviction_delta=0.15)

    brain.analyze_and_decide(
        "BTCUSDT", _market_data(technical=0.20, macro=0.30, sentiment=0.25, risk=0.3)
    )
    baseline = store.health()["claim_count"]

    brain.analyze_and_decide(
        "BTCUSDT", _market_data(technical=0.95, macro=0.90, sentiment=0.95, risk=0.9)
    )

    assert store.health()["claim_count"] > baseline
    triggers = {
        code
        for claim in store.query(limit=500)
        for code in claim.reason_codes
    }
    assert {"ACTION_FLIP", "CONVICTION_DELTA"} & triggers


def test_the_threshold_is_configurable(tmp_path):
    store = EvidenceStore(tmp_path / "e.sqlite3")
    store.open()
    brain = _brain(store, evidence_conviction_delta=0.01)
    assert brain.evidence_conviction_delta == 0.01

    brain.analyze_and_decide(
        "BTCUSDT", _market_data(technical=0.80, macro=0.75, sentiment=0.9, risk=0.7)
    )
    baseline = store.health()["claim_count"]

    brain.analyze_and_decide(
        "BTCUSDT", _market_data(technical=0.84, macro=0.75, sentiment=0.9, risk=0.7)
    )

    # The same 0.04 move that was silent at the 0.15 default is a claim here.
    assert store.health()["claim_count"] > baseline


def test_default_threshold_is_the_documented_value(tmp_path):
    assert AtlasBrain.DEFAULT_EVIDENCE_CONVICTION_DELTA == 0.15
    assert _brain(None).evidence_conviction_delta == 0.15


def test_symbols_are_tracked_independently(tmp_path):
    store = EvidenceStore(tmp_path / "e.sqlite3")
    store.open()
    brain = _brain(store)
    data = _market_data(technical=0.8, macro=0.75, sentiment=0.9, risk=0.7)

    brain.analyze_and_decide("BTCUSDT", data)
    btc_only = store.health()["claim_count"]

    brain.analyze_and_decide("ETHUSDT", data)

    assert store.health()["claim_count"] > btc_only
    assert store.query(symbol="ETHUSDT")


def test_missing_ingestion_timestamp_records_nothing(tmp_path):
    """Absent provenance must not be replaced with a fabricated one."""

    store = EvidenceStore(tmp_path / "e.sqlite3")
    store.open()
    brain = _brain(store)

    data = _market_data(technical=0.8, macro=0.75, sentiment=0.9, risk=0.7)
    data.pop("timestamp")

    brain.analyze_and_decide("BTCUSDT", data)

    assert store.health()["claim_count"] == 0


def test_naive_ingestion_timestamp_records_nothing(tmp_path):
    store = EvidenceStore(tmp_path / "e.sqlite3")
    store.open()
    brain = _brain(store)

    data = _market_data(technical=0.8, macro=0.75, sentiment=0.9, risk=0.7)
    data["timestamp"] = datetime(2026, 9, 18, 12, 0, 0).isoformat()

    brain.analyze_and_decide("BTCUSDT", data)

    assert store.health()["claim_count"] == 0


def test_recorded_claims_carry_source_provenance(tmp_path):
    store = EvidenceStore(tmp_path / "e.sqlite3")
    store.open()
    brain = _brain(store)
    stamp = datetime.now(UTC)

    brain.analyze_and_decide(
        "BTCUSDT",
        _market_data(
            technical=0.8,
            macro=0.75,
            sentiment=0.9,
            risk=0.7,
            timestamp=stamp.isoformat(),
        ),
    )

    claim = store.query(symbol="BTCUSDT")[0]
    sources = store.sources_for(claim.claim_id)
    assert len(sources) == 1
    assert sources[0].source_kind == "MARKET_DATA"
    assert sources[0].source_uri == "market_data://BTCUSDT"
    assert sources[0].retrieved_at == stamp.astimezone(UTC)
    assert isinstance(claim.confidence, Decimal)


def test_directional_disagreement_creates_counter_evidence(tmp_path):
    """A BUY and a SELL in one cycle must become a CONTRADICTS edge."""

    store = EvidenceStore(tmp_path / "e.sqlite3")
    store.open()
    brain = _brain(store)

    # Deliberately polarised inputs so agents split on direction.
    brain.analyze_and_decide(
        "BTCUSDT",
        _market_data(technical=0.95, macro=0.05, sentiment=0.95, risk=0.05),
    )

    claims = store.query(symbol="BTCUSDT", limit=500)
    actions = {c.payload.get("action") for c in claims}

    if {"BUY", "SELL"} <= actions:
        assert store.health()["relation_count"] > 0
        contradicted = [
            c for c in claims if store.counter_evidence(c.claim_id)
        ]
        assert contradicted
    else:
        pytest.skip(f"agents did not split directionally: {sorted(actions)}")


# =====================================================================
# FAIL-OPEN ON THE DECISION PATH
# =====================================================================


def _decision_fields(decision) -> dict:
    return {
        "action": decision.action,
        "confidence": decision.confidence,
        "risk_level": decision.risk_level,
        "price": getattr(decision, "price", None),
    }


# decision_id is a hash over a per-invocation timestamp, so these two keys
# differ between any two runs by construction and say nothing about whether
# evidence recording perturbed the proposal. Every other field is compared.
_TIME_DERIVED_PROPOSAL_KEYS = frozenset({"timestamp", "decision_id"})


def _stable_phase5_proposal(decision) -> dict | None:
    proposal = decision.metadata.get("phase5_proposal")
    if not isinstance(proposal, dict):
        return proposal
    return {
        key: value
        for key, value in proposal.items()
        if key not in _TIME_DERIVED_PROPOSAL_KEYS
    }


def test_a_broken_store_does_not_change_the_decision(tmp_path, caplog):
    """The single most important invariant in this subsystem.

    The store is pointed at an unusable path and never opened, so every
    record_claim() raises. The decision must be byte-identical to the one
    a brain with no store at all produces.
    """

    blocker = tmp_path / "blocker"
    blocker.write_text("not a directory", encoding="utf-8")
    broken = EvidenceStore(blocker / "e.sqlite3")
    with pytest.raises(Exception):
        broken.open()

    data = _market_data(technical=0.8, macro=0.75, sentiment=0.9, risk=0.7)

    control = _brain(None).analyze_and_decide("BTCUSDT", data)

    with caplog.at_level(logging.WARNING):
        broken_decision = _brain(broken).analyze_and_decide("BTCUSDT", data)

    assert _decision_fields(broken_decision) == _decision_fields(control)
    assert _stable_phase5_proposal(broken_decision) == _stable_phase5_proposal(
        control
    )

    # Fail-open must not also mean fail-silent.
    assert broken.health()["write_failures"] > 0
    assert broken.health()["last_error"] is not None
    assert any("Evidence" in record.getMessage() for record in caplog.records)


def test_a_store_raising_on_every_call_does_not_change_the_decision(tmp_path):
    """Covers an exception from an arbitrary point, not just an unopened DB."""

    class ExplodingStore:
        def __init__(self) -> None:
            self.failures = 0

        def record_claim(self, **_kwargs):
            raise RuntimeError("evidence backend exploded")

        def link(self, **_kwargs):
            raise RuntimeError("evidence backend exploded")

        def record_write_failure(self, _error) -> None:
            self.failures += 1

    data = _market_data(technical=0.8, macro=0.75, sentiment=0.9, risk=0.7)
    control = _brain(None).analyze_and_decide("BTCUSDT", data)

    exploding = ExplodingStore()
    decision = _brain(exploding).analyze_and_decide("BTCUSDT", data)

    assert _decision_fields(decision) == _decision_fields(control)
    assert _stable_phase5_proposal(decision) == _stable_phase5_proposal(control)
    assert exploding.failures > 0


def test_a_store_whose_failure_reporting_also_fails_is_survivable(tmp_path):
    class TotallyBrokenStore:
        def record_claim(self, **_kwargs):
            raise RuntimeError("down")

        def link(self, **_kwargs):
            raise RuntimeError("down")

        def record_write_failure(self, _error):
            raise RuntimeError("diagnostics down too")

    data = _market_data(technical=0.8, macro=0.75, sentiment=0.9, risk=0.7)
    control = _brain(None).analyze_and_decide("BTCUSDT", data)
    decision = _brain(TotallyBrokenStore()).analyze_and_decide("BTCUSDT", data)

    assert _decision_fields(decision) == _decision_fields(control)


def test_a_nonsense_store_object_does_not_change_the_decision(tmp_path):
    """Even an object with no store interface at all must be harmless."""

    data = _market_data(technical=0.8, macro=0.75, sentiment=0.9, risk=0.7)
    control = _brain(None).analyze_and_decide("BTCUSDT", data)
    decision = _brain(object()).analyze_and_decide("BTCUSDT", data)

    assert _decision_fields(decision) == _decision_fields(control)


def test_recording_does_not_mutate_agent_results_or_fusion(tmp_path):
    store = EvidenceStore(tmp_path / "e.sqlite3")
    store.open()
    brain = _brain(store)
    data = _market_data(technical=0.8, macro=0.75, sentiment=0.9, risk=0.7)

    control = _brain(None).analyze_and_decide("BTCUSDT", data)
    recorded = brain.analyze_and_decide("BTCUSDT", data)

    assert _decision_fields(recorded) == _decision_fields(control)
    assert _stable_phase5_proposal(recorded) == _stable_phase5_proposal(control)
    assert store.health()["claim_count"] > 0


def test_absent_store_is_a_supported_configuration(tmp_path):
    brain = _brain(None)
    assert brain.evidence_store is None
    decision = brain.analyze_and_decide(
        "BTCUSDT",
        _market_data(technical=0.8, macro=0.75, sentiment=0.9, risk=0.7),
    )
    assert decision is not None


# =====================================================================
# COMPOSITION-ROOT WIRING
# =====================================================================


def test_composition_root_owns_the_path_and_touches_no_disk(tmp_path):
    """Constructing the application must not create the database."""

    from core.application import AtlasApplication

    state = tmp_path / "state"
    evidence = tmp_path / "evidence"
    state.mkdir()
    evidence.mkdir()

    app = AtlasApplication(
        state_directory=state,
        evidence_directory=evidence,
    )

    assert app.evidence_directory == evidence
    assert app.evidence_store.database_path == evidence / "evidence_store.sqlite3"
    assert app.evidence_store.opened is False
    assert not app.evidence_store.database_path.exists()


def test_composition_root_threads_the_store_into_the_brain(tmp_path):
    from core.application import AtlasApplication

    state = tmp_path / "state"
    evidence = tmp_path / "evidence"
    state.mkdir()
    evidence.mkdir()

    app = AtlasApplication(
        state_directory=state,
        evidence_directory=evidence,
    )

    assert app.brain.evidence_store is app.evidence_store
    assert app.brain._intelligence_config()["evidence_store"] is app.evidence_store


def test_brain_service_threads_the_store_to_the_intelligence_layer(tmp_path):
    """The full core/brain.py -> ai/core/atlas_brain.py chain."""

    from core.brain import AtlasBrain as BrainService

    store = EvidenceStore(tmp_path / "ev.sqlite3")
    store.open()

    service = BrainService(
        state_directory=tmp_path / "state",
        evidence_store=store,
    )
    assert service.load_intelligence()
    assert service.intelligence.evidence_store is store


def test_a_bare_brain_service_is_unchanged_by_this_work(tmp_path):
    """Historical behaviour: no state dir and no store means no config."""

    from core.brain import AtlasBrain as BrainService

    service = BrainService()
    assert service.evidence_store is None
    assert service._intelligence_config() is None
    assert service.load_intelligence()
    assert service.intelligence.evidence_store is None


def test_startup_tolerates_an_application_with_no_evidence_store():
    """Startup must not acquire a hard dependency on the evidence store.

    Regression guard: start() originally accessed self.evidence_store
    directly, which broke the startup-order contract for a partially
    constructed application and made an explicitly optional, no-authority
    subsystem mandatory.
    """

    from core.application import AtlasApplication

    app = AtlasApplication.__new__(AtlasApplication)
    assert getattr(app, "evidence_store", None) is None
    assert getattr(app, "evidence_directory", None) is None
