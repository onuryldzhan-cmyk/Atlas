"""Phase-2 G1: policy manifest / governance integrity.

The runtime's critical switches are compared with the versioned manifest under
governance/current/. Any mismatch - missing, malformed, tampered, wrong registry
or proposal, a changed switch - is BLOCK_NEW_RISK: new BUYs are refused while
reduce-only SELLs stay governed by B1. Nothing is ever applied from the
manifest, and no manifest can enable LIVE.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from core import policy_manifest as pm
from tests.test_block5c_upstream_sizing_authority import application, execution_enabled_loop

ROOT = Path(__file__).resolve().parents[1]



@pytest.fixture(autouse=True)
def _the_sealed_v2_chain(monkeypatch):
    """Task 023 (registry v5.106): this module pins the sealed manifest v2 chain; the active manifest is v3
    (tests/test_task023_policy_manifest_v3.py). Every check here still runs against v2's own file and rules."""
    monkeypatch.setattr(pm, "MANIFEST_PATH", pm.MANIFEST_V2_PATH)


def manifest() -> dict:
    return json.loads(pm.MANIFEST_PATH.read_text(encoding="utf-8"))


def production_like_runtime() -> dict:
    """What main.py builds, as the manifest pins it (fill model: the default)."""
    data = manifest()["policy"]
    return {k: (v["one_of"][0] if isinstance(v, dict) else v) for k, v in data.items()}


def write(tmp_path, data, *, reseal=True) -> Path:
    if reseal:
        data["integrity"] = {"algorithm": "sha256", "digest": pm.integrity_digest(data)}
    path = tmp_path / "manifest.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    return path


# --- the committed manifest ------------------------------------------------------------------------


def test_committed_manifest_is_valid_and_matches_main_py_runtime_policy():
    check = pm.verify(production_like_runtime())
    assert check.status == pm.MATCH and not check.block_new_risk and check.block_reason is None
    assert check.registry_id == pm.EXPECTED_REGISTRY_ID and check.proposal_id == pm.EXPECTED_PROPOSAL_ID
    # v2: the manifest's own text is never trusted; approval is reported only because the
    # successor registry's EXP-002 grant exists, is GRANTED and pins this manifest's bytes.
    assert check.owner_approval == f"{pm.OWNER_RATIFIED}:{pm.EXPECTED_GRANT_REGISTRY_ID}"


def test_committed_manifest_covers_every_critical_switch_and_pins_paper():
    policy = manifest()["policy"]
    assert set(policy) == set(pm.CRITICAL_SWITCHES)
    assert policy["execution_mode"] == "PAPER" and policy["live_execution_enabled"] is False
    assert policy["exit_guard_mode"] == "OBSERVE" and policy["exit_guard_rules"] == 0


def test_main_py_constructs_exactly_the_manifest_policy(tmp_path, monkeypatch):
    """The literals at main.py's one call site are what the manifest pins."""
    import main

    monkeypatch.setenv("ATLAS_STATE_DIRECTORY", str(tmp_path / "state"))
    captured = {}

    class Probe:
        def __init__(self, **kwargs):
            captured.update(kwargs)
            raise RuntimeError("stop after construction arguments are known")

    monkeypatch.setattr(main, "AtlasApplication", Probe)
    runtime = main.AtlasProcess()
    monkeypatch.setattr(runtime, "_validate_configuration", lambda: True)
    monkeypatch.setattr(runtime, "_acquire_instance_lock", lambda: True)
    with pytest.raises(RuntimeError, match="stop after"):
        runtime.start()
    policy = manifest()["policy"]
    assert captured["execution_mode"] == policy["execution_mode"]
    assert captured["paper_confidence_experiment"] is policy["paper_confidence_experiment"]
    assert captured["paper_confidence_experiment_id"] == policy["paper_confidence_experiment_id"]
    assert captured["count_unrealized_in_daily_loss"] is policy["count_unrealized_in_daily_loss"]
    assert captured["sleeves_enabled"] is policy["sleeves_enabled"]
    assert pm._decimal_text(captured["paper_slippage_bps"]) == policy["paper_slippage_bps"]
    assert pm._decimal_text(captured["paper_fee_rate"]) == policy["paper_fee_rate"]
    assert captured["order_lifecycle_observe"] is policy["order_lifecycle_observe"]
    assert captured.get("funding_sentiment", False) is policy["funding_sentiment"]
    assert captured.get("fusion_full_weight_denominator", False) is policy["fusion_full_weight_denominator"]


# --- failure modes all block new risk ----------------------------------------------------------------


def test_missing_manifest_blocks(tmp_path):
    check = pm.verify(production_like_runtime(), tmp_path / "absent.json")
    assert check.status == pm.MISSING and check.block_new_risk
    assert check.to_dict()["decision"] == pm.BLOCK_NEW_RISK


@pytest.mark.parametrize("text", ["", "not json", "[]", "{}", json.dumps({"policy": {}})])
def test_malformed_manifest_blocks(tmp_path, text):
    path = tmp_path / "m.json"
    path.write_text(text, encoding="utf-8")
    assert pm.verify(production_like_runtime(), path).status == pm.MALFORMED


def test_missing_or_unknown_switch_is_malformed(tmp_path):
    data = manifest()
    del data["policy"]["sleeves_enabled"]
    assert pm.verify(production_like_runtime(), write(tmp_path, data)).status == pm.MALFORMED
    data = manifest()
    data["policy"]["new_switch"] = True
    assert pm.verify(production_like_runtime(), write(tmp_path, data)).status == pm.MALFORMED


def test_tampered_manifest_fails_integrity(tmp_path):
    data = manifest()
    data["policy"]["paper_slippage_bps"] = "0"
    assert pm.verify(production_like_runtime(), write(tmp_path, data, reseal=False)).status == pm.INTEGRITY_FAILED


def test_registry_mismatch_blocks(tmp_path):
    data = manifest()
    data["registry_id"] = "ATLAS_MILESTONE_REGISTRY_v5.82"
    assert pm.verify(production_like_runtime(), write(tmp_path, data)).status == pm.REGISTRY_MISMATCH
    data = manifest()
    data["registry_sha256"] = "0" * 64
    assert pm.verify(production_like_runtime(), write(tmp_path, data)).status == pm.REGISTRY_MISMATCH
    data = manifest()
    data["registry_path"] = "../outside/ATLAS_MILESTONE_REGISTRY_v5.83.json"
    assert pm.verify(production_like_runtime(), write(tmp_path, data)).status == pm.REGISTRY_MISMATCH


def test_proposal_mismatch_blocks(tmp_path):
    data = manifest()
    data["proposal_id"] = "SOME-OTHER-PROPOSAL"
    assert pm.verify(production_like_runtime(), write(tmp_path, data)).status == pm.PROPOSAL_MISMATCH


@pytest.mark.parametrize("switch,value", [
    ("sleeves_enabled", False), ("paper_slippage_bps", "0"), ("paper_confidence_experiment_id", "EXP-001"),
    ("global_minimum_confidence", "0.5"), ("exit_guard_mode", "ENFORCE"), ("exit_guard_rules", 1),
    ("risk_policy_version", "other"), ("paper_fill_model", "MID"), ("count_unrealized_in_daily_loss", 1),
])
def test_changed_runtime_switch_blocks(switch, value):
    runtime = production_like_runtime()
    runtime[switch] = value
    check = pm.verify(runtime)
    assert check.status == pm.POLICY_MISMATCH and check.block_new_risk
    assert [m[0] for m in check.mismatches] == [switch]


def test_unreadable_runtime_switch_never_matches():
    runtime = production_like_runtime()
    runtime["sleeves_enabled"] = pm.UNREADABLE
    assert pm.verify(runtime).status == pm.POLICY_MISMATCH
    runtime = production_like_runtime()
    del runtime["paper_fee_rate"]
    assert pm.verify(runtime).status == pm.POLICY_MISMATCH


def test_operator_selectable_fill_model_is_accepted_only_within_its_listed_values():
    runtime = production_like_runtime()
    for allowed in manifest()["policy"]["paper_fill_model"]["one_of"]:
        runtime["paper_fill_model"] = allowed
        assert pm.verify(runtime).status == pm.MATCH


# --- PAPER invariant ---------------------------------------------------------------------------------


@pytest.mark.parametrize("field,value", [("execution_mode", "LIVE"), ("live_execution_enabled", True)])
def test_a_manifest_can_never_authorise_live(tmp_path, field, value):
    data = manifest()
    data["policy"][field] = value
    runtime = production_like_runtime()
    runtime[field] = value       # even when the runtime agrees with it
    assert pm.verify(runtime, write(tmp_path, data)).status == pm.LIVE_REFUSED


def test_a_live_runtime_against_the_paper_manifest_blocks():
    runtime = production_like_runtime()
    runtime["execution_mode"] = "LIVE"
    assert pm.verify(runtime).status == pm.POLICY_MISMATCH


def test_verification_never_writes_or_changes_the_runtime(tmp_path):
    app = application(tmp_path)
    before = pm.runtime_policy(app)
    snapshot = copy.deepcopy(before)
    files = {p: p.read_bytes() for p in (tmp_path / "state").rglob("*") if p.is_file()}
    manifest_bytes = pm.MANIFEST_PATH.read_bytes()
    pm.verify(before)
    assert pm.runtime_policy(app) == snapshot and app.execution_mode == "PAPER"
    assert {p: p.read_bytes() for p in (tmp_path / "state").rglob("*") if p.is_file()} == files
    assert pm.MANIFEST_PATH.read_bytes() == manifest_bytes


def test_runtime_policy_reads_the_application_and_a_test_app_does_not_match():
    """A default-built (test) application differs from production: it must not pass as approved."""
    import tempfile

    with tempfile.TemporaryDirectory() as d:
        app = application(Path(d))
        runtime = pm.runtime_policy(app)
    # Task 023: the runtime also reads manifest v3's forex switches; it still covers every v2 switch
    assert set(pm.CRITICAL_SWITCHES) <= set(runtime) and set(runtime) == set(pm.CRITICAL_SWITCHES_V4)   # Task 025: the v4 runtime keys
    assert runtime["execution_mode"] == "PAPER" and runtime["live_execution_enabled"] is False
    assert pm.verify(runtime).status == pm.POLICY_MISMATCH


# --- enforcement: BLOCK_NEW_RISK, reduce-only exits remain ------------------------------------------


def test_policy_mismatch_blocks_new_buy_but_a_reduce_only_sell_still_executes(tmp_path):
    app = application(tmp_path)
    app.execution.start()
    assert execution_enabled_loop(app, "BUY").process_symbol("BTCUSDT")["status"] == "PAPER_EXECUTED"

    app.execution.set_policy_manifest_block("POLICY_MANIFEST_POLICY_MISMATCH")
    blocked = execution_enabled_loop(app, "BUY", epoch=1).process_symbol("BTCUSDT")
    assert blocked["status"] != "PAPER_EXECUTED"
    assert "POLICY_MANIFEST_POLICY_MISMATCH" in json.dumps(blocked, default=str)
    health = app.health()
    assert health["system_health"]["safe_to_trade"] is False
    assert health["system_health"]["policy_manifest"] == "POLICY_MANIFEST_POLICY_MISMATCH"

    sold = execution_enabled_loop(app, "SELL", epoch=2).process_symbol("BTCUSDT")
    assert sold["status"] == "PAPER_EXECUTED"
    assert "BTCUSDT" not in app.portfolio_foundation.snapshot()["positions"]
    app.stop()


def test_clearing_is_explicit_and_a_non_string_block_is_refused(tmp_path):
    app = application(tmp_path)
    with pytest.raises(ValueError):
        app.execution.set_policy_manifest_block(True)
    app.execution.set_policy_manifest_block("POLICY_MANIFEST_MISSING")
    assert app.execution.health()["operational_state"]["policy_manifest_block"] == "POLICY_MANIFEST_MISSING"
    app.execution.set_policy_manifest_block(None)
    assert app.execution.health()["operational_state"]["policy_manifest_block"] is None


def test_main_applies_the_check_as_a_block_never_as_configuration(tmp_path, monkeypatch):
    import main

    app = application(tmp_path)
    before = pm.runtime_policy(app)
    main.apply_policy_manifest(app, path=tmp_path / "absent.json")
    assert app.execution.policy_manifest_block == "POLICY_MANIFEST_MISSING"
    assert pm.runtime_policy(app) == before          # nothing applied, nothing enabled


def test_main_refuses_to_start_when_the_check_cannot_be_applied(monkeypatch):
    """Fail-closed: an application whose block cannot be set never starts."""
    import main

    started = []

    class NoExecution:
        def __init__(self, **kwargs):
            pass

        def start(self):
            started.append(True)
            return True

    monkeypatch.setattr(main, "AtlasApplication", NoExecution)
    process = main.AtlasProcess()
    monkeypatch.setattr(process, "_validate_configuration", lambda: True)
    monkeypatch.setattr(process, "_acquire_instance_lock", lambda: True)
    assert process.start() is False
    assert started == [] and process.exit_code == 1
    assert "Policy manifest check could not be applied" in process.shutdown_reason


def test_registry_ratification_pins_the_manifest_so_a_silent_edit_is_detected():
    """Owner ratification (2026-10-03) lives in a successor registry record that pins the manifest bytes."""
    import hashlib

    record = json.loads((ROOT / "governance/current/ATLAS_MILESTONE_REGISTRY_v5.84.json").read_text(encoding="utf-8"))
    ratified = record["phase2_governance_closeout_2026_10_03"]["owner_decision_2_policy_manifest_ratification"]
    assert ratified["decision"] == "RATIFIED"
    # v5.84 ratified manifest v1, which stays sealed and unchanged; v2 is pinned by v5.85.
    v1 = ROOT / "governance/policy/ATLAS_POLICY_MANIFEST_v1.json"
    assert ratified["manifest_file_sha256"] == hashlib.sha256(v1.read_bytes()).hexdigest()
    assert ratified["manifest_integrity_digest"] == json.loads(v1.read_text(encoding="utf-8"))["integrity"]["digest"]
    assert ratified["proposal_id"] == pm.EXPECTED_PROPOSAL_ID
    assert record["supersedes"] == "ATLAS_MILESTONE_REGISTRY_v5.83.json"
    assert record["phase2_governance_closeout_2026_10_03"]["exp002_audit"]["registry_status"].startswith("UNKNOWN")
