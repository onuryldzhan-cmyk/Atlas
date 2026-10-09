"""Audit P4-CLOSURE-003 F-5: malformed text or timestamps are refused input, never a halt.

Both research managers promise that malformed caller input is refused without
halting and without writing; a halt is reserved for integrity failures. A lone
surrogate (unserialisable as UTF-8) or an instant that overflows on UTC
conversion used to raise an unexpected error and halt the manager.
"""

from __future__ import annotations

import pytest

from research.experiment_manager import ExperimentError, ExperimentManager
from research.hypothesis_registry import HypothesisRegistry
from research.knowledge_manager import KnowledgeInputError, KnowledgeManager
from tests.test_research_hypothesis_registry import make_preregistration

LONE_SURROGATE = "x\ud800"
OK_TIME = "2026-10-01T00:00:00+00:00"


def _km_with_claim():
    km = KnowledgeManager()
    src = km.register_source(kind="NEWS", uri="news://a", retrieved_at=OK_TIME)
    cid = km.register_claim(statement="s", author="author_a", source_ids=(src,))
    return km, src, cid


@pytest.mark.parametrize("call", [
    lambda km, s, c: km.register_source(kind="NEWS", uri="news://" + LONE_SURROGATE, retrieved_at=OK_TIME),
    lambda km, s, c: km.register_source(kind="NEWS", uri="news://b", retrieved_at="9999-12-31T23:59:59-23:59"),
    lambda km, s, c: km.register_source(kind="NEWS", uri="news://b", retrieved_at="0001-01-01T00:00:00+23:59"),
    lambda km, s, c: km.register_claim(statement=LONE_SURROGATE, author="a", source_ids=(s,)),
    lambda km, s, c: km.add_evidence(claim_id=c, stance="SUPPORTS", source_id=s, submitter="x",
                                     description=LONE_SURROGATE, content_digest="a" * 64),
    lambda km, s, c: km.withdraw_evidence(
        evidence_id=km.add_evidence(claim_id=c, stance="SUPPORTS", source_id=s, submitter="x", description="d"),
        actor="x", reason=LONE_SURROGATE),
], ids=["uri", "tz-overflow-high", "tz-overflow-low", "statement", "description", "withdraw-reason"])
def test_knowledge_manager_refuses_without_halting(call):
    km, src, cid = _km_with_claim()
    with pytest.raises(KnowledgeInputError):
        call(km, src, cid)
    assert not km.halted
    km.verify_log()  # still usable, chain intact


def test_knowledge_manager_still_accepts_ordinary_non_ascii_text():
    km, src, _ = _km_with_claim()
    km.register_claim(statement="Bitcoin yükseliş eğiliminde — çok kısa vadeli", author="author_a", source_ids=(src,))
    assert not km.halted


def test_experiment_manager_refuses_an_unserialisable_abort_reason_without_halting(tmp_path):
    registry = HypothesisRegistry(registry_path=tmp_path / "h.json")
    registry.register(make_preregistration(hypothesis_id="HYP-0001"))
    manager = ExperimentManager(registry=registry)
    manager.register_experiment("HYP-0001")
    before = len(manager.log)
    with pytest.raises(ExperimentError):
        manager.abort("HYP-0001", reason=LONE_SURROGATE)
    assert not manager.halted and len(manager.log) == before
    assert manager.abort("HYP-0001", reason="vendor outage — veri yok").status.value == "ABORTED"
