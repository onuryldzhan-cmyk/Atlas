"""Phase-2 G2: the EXP-002 registry grant and the manifest v2 parameter pins.

Chain (one direction, no circular checksum):
  registry v5.84 (sealed; pins manifest v1 and is pinned by manifest v2)
  manifest v2    (pins v5.84 by sha256, names the grant registry without a hash)
  registry v5.85 (carries the EXP-002 grant; pins manifest v2's exact bytes)

Changing any EXP-002 parameter in the runtime, the manifest or the grant, or
removing the grant, is BLOCK_NEW_RISK. Nothing is ever applied from the manifest.
"""

from __future__ import annotations

import copy
import hashlib
import json
import shutil
from pathlib import Path

import pytest

from core import policy_manifest as pm
from tests.test_block5c_upstream_sizing_authority import (
    application,
    execution_enabled_loop,
    seed_state,
)

ROOT = Path(__file__).resolve().parents[1]
V84 = "governance/current/ATLAS_MILESTONE_REGISTRY_v5.84.json"
V85 = "governance/current/ATLAS_MILESTONE_REGISTRY_v5.85.json"
V1 = "governance/policy/ATLAS_POLICY_MANIFEST_v1.json"
V2 = "governance/policy/ATLAS_POLICY_MANIFEST_v2.json"


def load(rel: str) -> dict:
    return json.loads((ROOT / rel).read_text(encoding="utf-8"))


def sha(rel: str) -> str:
    return hashlib.sha256((ROOT / rel).read_bytes()).hexdigest()


def runtime_matching_manifest() -> dict:
    return {k: (v["one_of"][0] if isinstance(v, dict) else v) for k, v in load(V2)["policy"].items()}


@pytest.fixture
def repo(tmp_path) -> Path:
    """A scratch copy of the governance files verify() reads, so the real ones are never touched."""
    for rel in (V84, V85, V2):
        target = tmp_path / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / rel, target)
    return tmp_path


def verify_in(repo: Path, runtime=None):
    return pm.verify(runtime if runtime is not None else runtime_matching_manifest(), repo / V2,
                     repository_root=repo)


def rewrite_manifest(repo: Path, mutate) -> None:
    path = repo / V2
    data = json.loads(path.read_text(encoding="utf-8"))
    mutate(data)
    data["integrity"] = {"algorithm": "sha256", "digest": pm.integrity_digest(data)}
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def rewrite_grant_registry(repo: Path, mutate) -> None:
    path = repo / V85
    data = json.loads(path.read_text(encoding="utf-8"))
    mutate(data)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")


def repin(repo: Path) -> None:
    """Re-pin the (possibly edited) manifest in the scratch grant registry - what a governed change does."""
    manifest_bytes = (repo / V2).read_bytes()

    def mutate(data):
        data["exp002_grant"]["manifest_pin"]["manifest_file_sha256"] = hashlib.sha256(manifest_bytes).hexdigest()

    rewrite_grant_registry(repo, mutate)


# --- the committed chain ------------------------------------------------------------------------


def test_committed_chain_verifies_and_reports_registry_ratification():
    check = pm.verify(runtime_matching_manifest())
    assert check.status == pm.MATCH and not check.block_new_risk
    assert check.owner_approval == f"{pm.OWNER_RATIFIED}:{pm.EXPECTED_GRANT_REGISTRY_ID}"
    assert check.to_dict()["manifest_version"] == 2


def test_grant_records_the_exact_owner_scope():
    grant = load(V85)["exp002_grant"]
    assert grant["grant_id"] == pm.EXPECTED_GRANT_ID and grant["status"] == "GRANTED"
    p = grant["parameters"]
    assert (p["exp002_experiment_id"], p["exp002_buckets"], p["exp002_minimum_confidence"]) == (
        "EXP-002", ["MEDIUM"], "0.62")
    assert (p["exp002_global_minimum_confidence"], p["exp002_max_admissions"]) == ("0.6", 30)
    assert (p["exp002_starts_at"], p["exp002_ends_at"]) == ("2026-10-02T00:00:00+00:00", "2026-10-16T00:00:00+00:00")
    assert p["exp002_sizing_mode"] == "HIGH_BUCKET_LIMITS"
    assert p["exp002_paper_only"] is True and p["exp002_funding_sentiment_off"] is True
    assert grant["live_effect"] == "NONE" and "LIVE trading or any live effect" in grant["policy_scope"]["not_authorized"]
    assert "ExitGuard activation" in grant["policy_scope"]["not_authorized"]
    for rel in ("proposals/2026-10-01_sentiment_second_source_and_exp002_DESIGN.md",
                "docs/audits/INDEPENDENT_AUDIT_FUNDING_SENTIMENT_EXP002_2026-10-01.md"):
        assert (ROOT / rel.split(" ")[0]).is_file()
        assert rel in (grant["references"]["design_proposal"], grant["references"]["independent_audit"].split(" (")[0])


def test_chain_checksums_are_one_directional_and_historical_files_are_sealed():
    v84, v85, v2 = load(V84), load(V85), load(V2)
    # v5.85 pins manifest v2's exact bytes and the sealed v5.84.
    assert v85["exp002_grant"]["manifest_pin"]["manifest_file_sha256"] == sha(V2)
    assert v85["exp002_grant"]["manifest_pin"]["manifest_integrity_digest"] == v2["integrity"]["digest"]
    assert v85["exp002_grant"]["predecessor_registry_sha256"] == sha(V84)
    assert v85["supersedes"] == "ATLAS_MILESTONE_REGISTRY_v5.84.json"
    # manifest v2 pins v5.84 and names v5.85 WITHOUT a hash: no cycle.
    assert v2["registry_sha256"] == sha(V84) and v2["registry_id"] == "ATLAS_MILESTONE_REGISTRY_v5.84"
    assert set(v2["grant"]) == {"grant_id", "grant_registry_id", "grant_registry_path"}
    assert sha(V85) not in json.dumps(v2)
    # v5.84 still pins the unchanged manifest v1.
    ratified = v84["phase2_governance_closeout_2026_10_03"]["owner_decision_2_policy_manifest_ratification"]
    assert ratified["manifest_file_sha256"] == sha(V1)
    # The EXP-002 grant exists only in the successor, never in a sealed record.
    assert "exp002_grant" not in v84


def test_manifest_v2_covers_every_exp002_switch_and_stays_paper_only():
    policy = load(V2)["policy"]
    assert set(policy) == set(pm.CRITICAL_SWITCHES) and set(pm.EXP002_SWITCHES) <= set(policy)
    assert policy["execution_mode"] == "PAPER" and policy["live_execution_enabled"] is False
    assert policy["exit_guard_mode"] == "OBSERVE" and policy["exit_guard_rules"] == 0
    assert policy["funding_sentiment"] is False


# --- parameter changes fail ------------------------------------------------------------------------


@pytest.mark.parametrize("switch,value", [
    ("exp002_minimum_confidence", "0.60"),          # floor
    ("exp002_buckets", ["MEDIUM", "HIGH"]),         # bucket
    ("exp002_max_admissions", 31),                  # cap
    ("exp002_starts_at", "2026-10-01T00:00:00+00:00"),
    ("exp002_ends_at", "2026-10-17T00:00:00+00:00"),
    ("exp002_sizing_mode", "MEDIUM_BUCKET_LIMITS"),
    ("exp002_sizing_max_allocation_pct", "0.25"),
    ("exp002_sizing_exposure_ceiling_pct", "0.4"),
    ("exp002_medium_default_floor", "0.6"),
    ("exp002_global_minimum_confidence", "0.5"),
    ("exp002_paper_only", False),
    ("exp002_funding_sentiment_off", False),
    ("exp002_enabled", False),
    ("exp002_experiment_id", "EXP-001"),
])
def test_changed_exp002_runtime_parameter_blocks_new_risk(switch, value):
    runtime = runtime_matching_manifest()
    runtime[switch] = value
    check = pm.verify(runtime)
    assert check.status == pm.POLICY_MISMATCH and check.block_new_risk
    assert check.block_reason == "POLICY_MANIFEST_POLICY_MISMATCH"
    assert [m[0] for m in check.mismatches] == [switch]


# --- the real application: EXP-002 wiring ---------------------------------------------------------


def exp002_app(tmp_path, **kwargs):
    from core.application import AtlasApplication

    return AtlasApplication(
        state_directory=seed_state(tmp_path / "state"),
        paper_confidence_experiment=True, paper_confidence_experiment_id="EXP-002", **kwargs,
    )


def exp002_view(runtime: dict) -> dict:
    return {k: runtime[k] for k in pm.EXP002_SWITCHES}


def test_real_application_exp002_parameters_equal_the_manifest_and_the_grant(tmp_path):
    app = exp002_app(tmp_path)
    assert app.risk_engine.experiment is not None and app.risk_engine.experiment.experiment_id == "EXP-002"
    runtime = pm.runtime_policy(app)
    assert exp002_view(runtime) == {k: load(V2)["policy"][k] for k in pm.EXP002_SWITCHES}
    assert exp002_view(runtime) == load(V85)["exp002_grant"]["parameters"]


def test_editing_the_experiment_constants_is_detected(tmp_path, monkeypatch):
    import dataclasses

    from core import risk_engine

    original = risk_engine.PAPER_CONFIDENCE_EXPERIMENTS["EXP-002"]
    for field, value in (("minimum_confidence", risk_engine.Decimal("0.61")), ("max_admissions", 40),
                         ("buckets", frozenset({risk_engine.RiskBucket.MEDIUM, risk_engine.RiskBucket.HIGH}))):
        edited = dataclasses.replace(original, **{field: value})
        monkeypatch.setitem(risk_engine.PAPER_CONFIDENCE_EXPERIMENTS, "EXP-002", edited)
        runtime = pm.runtime_policy(exp002_app(tmp_path / field))
        mismatched = {s for s in pm.EXP002_SWITCHES if runtime[s] != load(V2)["policy"][s]}
        assert mismatched, field
    monkeypatch.setitem(risk_engine.PAPER_CONFIDENCE_EXPERIMENTS, "EXP-002", original)


def test_editing_the_sizing_bucket_or_bucket_limits_is_detected(tmp_path, monkeypatch):
    from core import risk_engine

    monkeypatch.setattr(risk_engine, "EXPERIMENT_SIZING_BUCKET", risk_engine.RiskBucket.MEDIUM)
    runtime = pm.runtime_policy(exp002_app(tmp_path))
    assert runtime["exp002_sizing_mode"] == "MEDIUM_BUCKET_LIMITS"
    assert pm.verify({**runtime_matching_manifest(), **exp002_view(runtime)}).status == pm.POLICY_MISMATCH


def test_live_cannot_be_enabled_through_exp002(tmp_path):
    from core.application import AtlasApplication

    app = AtlasApplication(execution_mode="LIVE", state_directory=seed_state(tmp_path / "state"),
                           paper_confidence_experiment=True, paper_confidence_experiment_id="EXP-002")
    assert app.risk_engine.experiment is None            # the experiment attaches in PAPER only
    runtime = pm.runtime_policy(app)
    assert runtime["exp002_paper_only"] is False and runtime["live_execution_enabled"] is False
    check = pm.verify({**runtime_matching_manifest(), **runtime})
    assert check.status == pm.POLICY_MISMATCH and check.block_new_risk


def test_a_grant_or_manifest_naming_live_or_non_paper_is_refused(repo):
    rewrite_manifest(repo, lambda d: d["policy"].update(execution_mode="LIVE"))
    assert verify_in(repo).status == pm.LIVE_REFUSED
    rewrite_manifest(repo, lambda d: d["policy"].update(execution_mode="PAPER", exp002_paper_only=False))
    repin(repo)
    assert verify_in(repo).status == pm.GRANT_MISMATCH   # the grant says PAPER-only


# --- grant and chain failures all block ---------------------------------------------------------------


def test_missing_grant_registry_blocks(repo):
    (repo / V85).unlink()
    check = verify_in(repo)
    assert check.status == pm.GRANT_MISSING and check.block_new_risk


def test_grant_record_absent_or_not_granted_blocks(repo):
    rewrite_grant_registry(repo, lambda d: d.pop("exp002_grant"))
    assert verify_in(repo).status == pm.GRANT_MISSING
    shutil.copyfile(ROOT / V85, repo / V85)
    rewrite_grant_registry(repo, lambda d: d["exp002_grant"].update(status="PROPOSED"))
    assert verify_in(repo).status == pm.GRANT_MISSING


def test_manifest_without_the_grant_reference_blocks(repo):
    rewrite_manifest(repo, lambda d: d.pop("grant"))
    assert verify_in(repo).status == pm.MALFORMED          # a required field
    shutil.copyfile(ROOT / V2, repo / V2)
    rewrite_manifest(repo, lambda d: d["grant"].update(grant_id="GRANT-OTHER"))
    assert verify_in(repo).status == pm.GRANT_MISSING


def test_registry_manifest_mismatch_blocks_new_risk(repo):
    """The manifest was edited (and re-sealed) but the grant registry still pins the old bytes."""
    rewrite_manifest(repo, lambda d: d["policy"].update(exp002_minimum_confidence="0.60"))
    runtime = {**runtime_matching_manifest(), "exp002_minimum_confidence": "0.60"}   # runtime agrees with the edit
    check = verify_in(repo, runtime)
    assert check.status == pm.GRANT_MISMATCH and check.block_new_risk
    assert check.block_reason == "POLICY_MANIFEST_GRANT_MISMATCH"


def test_grant_parameters_differing_from_the_manifest_block(repo):
    rewrite_grant_registry(repo, lambda d: d["exp002_grant"]["parameters"].update(exp002_max_admissions=31))
    assert verify_in(repo).status == pm.GRANT_MISMATCH
    shutil.copyfile(ROOT / V85, repo / V85)
    rewrite_grant_registry(repo, lambda d: d["exp002_grant"]["parameters"].pop("exp002_enabled"))
    assert verify_in(repo).status == pm.GRANT_MISMATCH


def test_base_registry_changed_after_pinning_blocks(repo):
    (repo / V84).write_text((repo / V84).read_text(encoding="utf-8") + " ", encoding="utf-8")
    assert verify_in(repo).status == pm.REGISTRY_MISMATCH


def test_only_a_coordinated_governed_change_matches(repo):
    """Edit manifest + re-pin in the grant + a runtime that agrees: the one legitimate path."""
    rewrite_manifest(repo, lambda d: d["policy"].update(exp002_max_admissions=40))
    rewrite_grant_registry(repo, lambda d: d["exp002_grant"]["parameters"].update(exp002_max_admissions=40))
    repin(repo)
    runtime = {**runtime_matching_manifest(), "exp002_max_admissions": 40}
    assert verify_in(repo, runtime).status == pm.MATCH
    assert verify_in(repo).status == pm.POLICY_MISMATCH   # the real runtime (30) no longer matches


def test_verification_is_read_only_and_applies_nothing(repo):
    before = {p: p.read_bytes() for p in repo.rglob("*") if p.is_file()}
    verify_in(repo)
    assert {p: p.read_bytes() for p in repo.rglob("*") if p.is_file()} == before


# --- reduce-only behaviour unchanged ------------------------------------------------------------------


def test_exp002_mismatch_blocks_buy_but_reduce_only_sell_still_executes(tmp_path):
    import main

    app = application(tmp_path)
    app.execution.start()
    assert execution_enabled_loop(app, "BUY").process_symbol("BTCUSDT")["status"] == "PAPER_EXECUTED"

    check = main.apply_policy_manifest(app)     # a test-built app differs from production policy
    assert check.status == pm.POLICY_MISMATCH
    assert any(m[0].startswith("exp002_") for m in check.mismatches)
    blocked = execution_enabled_loop(app, "BUY", epoch=1).process_symbol("BTCUSDT")
    assert blocked["status"] != "PAPER_EXECUTED" and "POLICY_MANIFEST_POLICY_MISMATCH" in json.dumps(blocked, default=str)

    sold = execution_enabled_loop(app, "SELL", epoch=2).process_symbol("BTCUSDT")
    assert sold["status"] == "PAPER_EXECUTED"
    assert "BTCUSDT" not in app.portfolio_foundation.snapshot()["positions"]
    app.stop()


def test_degraded_audit_latch_policy_is_unchanged_by_the_manifest():
    """The DEGRADED latch lives in ExecutionManager/AuditEventStore; the manifest module never touches it."""
    source = (ROOT / "core" / "policy_manifest.py").read_text(encoding="utf-8")
    assert "audit_persistence" not in source and "write_failures" not in source
    assert copy.deepcopy(pm.MATCH) == "MATCH"
