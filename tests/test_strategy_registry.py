"""Strategy lifecycle: forward only with evidence; no certification, no production."""

import copy

import pytest

from atlas_org import strategy_registry as SR


def test_checked_in_registry_is_valid():
    reg = SR.load()
    assert {s["id"] for s in reg["strategies"]} >= {"atlas-fusion", "regime-filter-trend-up"}
    assert all(s["status"] not in SR.NEEDS_CERTIFICATION for s in reg["strategies"])


def _one(status_path):
    hist = [{"status": st, "at": f"2026-09-{i + 10:02d}", "evidence": "x"} for i, st in enumerate(status_path)]
    spec = {f: "x" for f in SR.SPEC_FIELDS}
    return {"live_authority": "DENIED", "strategies": [
        {"id": "s", "version": "v1", "environment": "PAPER", "status": status_path[-1], "history": hist, "specification": spec}]}


def test_skipping_a_stage_is_illegal():
    with pytest.raises(SR.StrategyRegistryError, match="illegal transition"):
        SR.validate(_one(["DISCOVERED", "DEFINED", "PAPER"]))


def test_certification_requires_owner_and_independent_audit():
    path = list(SR.STAGES[:SR.STAGES.index("CERTIFIED") + 1])
    with pytest.raises(SR.StrategyRegistryError, match="certification"):
        SR.validate(_one(path))
    reg = _one(path)
    reg["strategies"][0]["certification"] = {"owner_approved_proposal": "P-1", "independent_audit": "A-1"}
    SR.validate(reg)


def test_suspended_can_only_return_to_paper_and_deprecated_is_final():
    SR.validate(_one(["DISCOVERED", "SUSPENDED", "PAPER"]))
    with pytest.raises(SR.StrategyRegistryError):
        SR.validate(_one(["DISCOVERED", "SUSPENDED", "ENABLED"]))
    with pytest.raises(SR.StrategyRegistryError):
        SR.validate(_one(["DISCOVERED", "DEPRECATED", "SUSPENDED"]))


def test_every_transition_needs_evidence_and_a_spec():
    reg = _one(["DISCOVERED", "DEFINED"])
    reg["strategies"][0]["history"][1]["evidence"] = ""
    with pytest.raises(SR.StrategyRegistryError, match="evidence"):
        SR.validate(reg)
    reg = _one(["DISCOVERED", "DEFINED"])
    del reg["strategies"][0]["specification"]["invalidation"]
    with pytest.raises(SR.StrategyRegistryError, match="specification"):
        SR.validate(reg)


def test_duplicate_version_rejected():
    reg = _one(["DISCOVERED"])
    reg["strategies"].append(copy.deepcopy(reg["strategies"][0]))
    with pytest.raises(SR.StrategyRegistryError, match="duplicate"):
        SR.validate(reg)
