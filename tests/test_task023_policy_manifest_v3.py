"""Task 023 (registry v5.106): policy manifest v3 and the forex weekend close.

Owner 2026-10-26/27: open forex positions are closed in the last 30 minutes before the Friday 17:00 New York close
through the exit guard (ENFORCE, that one WEEKEND_CLOSE rule, FOREX only); CRYPTO keeps the guard as before
(OBSERVE, no rules, not run from the cycle). Manifest v2 stays sealed and is still verified by its own rules
(tests/test_phase2_g1_policy_manifest.py, tests/test_phase2_g2_exp002_grant.py)."""

from __future__ import annotations

import copy
import json
import shutil
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

import pytest

from atlas_finance.forex.sessions import WEEKEND_CLOSE_MINUTES, is_forex_pre_close
from core import policy_manifest as pm
from core.application import AtlasApplication
from core.exit_guard import (
    ENFORCE,
    EXIT_NOT_TRIGGERED,
    EXIT_PENDING_PRICE,
    EXIT_TRIGGERED,
    OBSERVE,
    RULE_MAX_LOSS_PCT,
    RULE_WEEKEND_CLOSE,
    ExitGuard,
    ExitRule,
    Mark,
)
from core.market_loop import MarketLoop
from tests.intelligence.test_task009_regime_tracking import Brain, Execution, Feed
from tests.test_block5c_upstream_sizing_authority import seed_state

ROOT = Path(__file__).resolve().parents[1]
V3 = "governance/policy/ATLAS_POLICY_MANIFEST_v3.json"


def manifest() -> dict:
    return json.loads((ROOT / V3).read_text(encoding="utf-8"))


def runtime_for(market: str) -> dict:
    """What main.py builds for ``market``, as manifest v3 pins it."""
    out = {}
    for name, spec in manifest()["policy"].items():
        if isinstance(spec, dict) and "by_market" in spec:
            out[name] = spec["by_market"][market]
        elif isinstance(spec, dict):
            out[name] = spec["one_of"][0]
        else:
            out[name] = spec
    out["market"] = market
    return out


# ---------------------------------------------------------------- the committed chain


def test_v3_is_the_active_manifest_and_v2_stays_sealed():
    assert pm.MANIFEST_PATH == ROOT / V3 and pm.EXPECTED_MANIFEST_VERSION == 3
    assert pm.MANIFEST_V2_PATH == ROOT / "governance/policy/ATLAS_POLICY_MANIFEST_v2.json"
    v2 = json.loads(pm.MANIFEST_V2_PATH.read_text(encoding="utf-8"))
    assert v2["manifest_version"] == 2 and v2["policy"]["exit_guard_mode"] == "OBSERVE"


@pytest.mark.parametrize("market", ["CRYPTO", "FOREX"])
def test_the_committed_v3_chain_verifies_for_both_markets(market):
    check = pm.verify(runtime_for(market))
    assert check.status == pm.MATCH and not check.block_new_risk, check.to_dict()
    assert check.registry_id == pm.V3_EXPECTED_REGISTRY_ID and check.proposal_id == pm.V3_EXPECTED_PROPOSAL_ID
    assert check.owner_approval == f"{pm.OWNER_RATIFIED}:{pm.V3_RATIFICATION_REGISTRY_ID}"


def test_v3_covers_every_switch_and_pins_paper():
    policy = manifest()["policy"]
    assert set(policy) == set(pm.CRITICAL_SWITCHES_V3)
    assert policy["execution_mode"] == "PAPER" and policy["live_execution_enabled"] is False
    assert policy["exit_guard_mode"] == {"by_market": {"CRYPTO": "OBSERVE", "FOREX": "ENFORCE"}}
    assert policy["exit_guard_rules"] == {"by_market": {"CRYPTO": 0, "FOREX": 1}}
    assert policy["forex_weekend_close_minutes"] == WEEKEND_CLOSE_MINUTES == 30
    assert policy["forex_paper_fee_rate"] == "0.001"                    # unchanged until measured on MT5


def test_the_ratification_registry_pins_these_bytes_and_is_sealed_in_code():
    record = json.loads((ROOT / pm.V3_RATIFICATION_REGISTRY_PATH).read_text(encoding="utf-8"))
    ratification = record[pm.V3_RATIFICATION_RECORD_KEY]
    assert ratification["status"] == "RATIFIED" and ratification["live_effect"] == "NONE"
    assert ratification["manifest_pin"] == {"manifest_file_sha256": pm.file_sha256((ROOT / V3).read_bytes()),
                                            "manifest_version": 3}
    assert pm.file_sha256((ROOT / pm.V3_RATIFICATION_REGISTRY_PATH).read_bytes()) == \
        pm.V3_RATIFICATION_REGISTRY_SHA256


# ---------------------------------------------------------------- by market


@pytest.mark.parametrize("market, switch, value", [
    ("FOREX", "exit_guard_mode", "OBSERVE"), ("FOREX", "exit_guard_rules", 0),
    ("CRYPTO", "exit_guard_mode", "ENFORCE"), ("CRYPTO", "exit_guard_rules", 1),
    ("FOREX", "forex_weekend_close_minutes", 15), ("FOREX", "forex_paper_fee_rate", "0.0001"),
])
def test_a_switch_that_differs_for_its_market_blocks_new_risk(market, switch, value):
    runtime = {**runtime_for(market), switch: value}
    check = pm.verify(runtime)
    assert check.status == pm.POLICY_MISMATCH and check.block_new_risk
    assert [m[0] for m in check.mismatches] == [switch]


@pytest.mark.parametrize("market", ["STOCKS", None, pm.UNREADABLE, 1])
def test_an_unknown_or_unreadable_market_never_matches(market):
    runtime = {**runtime_for("CRYPTO"), "market": market}
    check = pm.verify(runtime)
    assert check.status == pm.POLICY_MISMATCH
    assert {"market", "exit_guard_mode", "exit_guard_rules"} <= {m[0] for m in check.mismatches}


def test_a_nested_by_market_value_never_matches():
    assert pm._matches({"by_market": {"FOREX": {"one_of": ["ENFORCE"]}}}, "ENFORCE", "FOREX") is False
    assert pm._matches({"by_market": {"FOREX": "ENFORCE"}, "x": 1}, "ENFORCE", "FOREX") is False
    assert pm._matches({"by_market": ["FOREX"]}, "ENFORCE", "FOREX") is False


# ---------------------------------------------------------------- tampering (on a copy of the repository files)


def repo_copy(tmp_path) -> Path:
    for rel in (V3, pm.V3_RATIFICATION_REGISTRY_PATH, "governance/current/ATLAS_MILESTONE_REGISTRY_v5.105.json",
                pm.EXPECTED_GRANT_REGISTRY_PATH):
        (tmp_path / rel).parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / rel, tmp_path / rel)
    return tmp_path


def rewrite(path: Path, edit, *, reseal=True):
    data = json.loads(path.read_text(encoding="utf-8"))
    edit(data)
    if reseal:
        data["integrity"] = {"algorithm": "sha256", "digest": pm.integrity_digest(data)}
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def test_the_copied_chain_verifies(tmp_path):
    repo = repo_copy(tmp_path)
    assert pm.verify(runtime_for("FOREX"), repo / V3, repository_root=repo).status == pm.MATCH


@pytest.mark.parametrize("edit, reseal, status", [
    (lambda d: d["policy"].__setitem__("forex_weekend_close_minutes", 5), False, pm.INTEGRITY_FAILED),
    (lambda d: d["policy"].__setitem__("forex_weekend_close_minutes", 5), True, pm.GRANT_MISMATCH),  # bytes moved
    (lambda d: d.__setitem__("registry_id", "ATLAS_MILESTONE_REGISTRY_v5.84"), True, pm.REGISTRY_MISMATCH),
    (lambda d: d.__setitem__("proposal_id", "OTHER"), True, pm.PROPOSAL_MISMATCH),
    (lambda d: d.__setitem__("ratification", {"registry_id": "x", "registry_path": "y"}), True, pm.GRANT_MISSING),
    (lambda d: d["policy"].pop("market"), True, pm.MALFORMED),
    (lambda d: d["policy"].__setitem__("execution_mode", "LIVE"), True, pm.LIVE_REFUSED),
    (lambda d: d["policy"].__setitem__("live_execution_enabled", True), True, pm.LIVE_REFUSED),
])
def test_an_edited_v3_manifest_blocks_new_risk(tmp_path, edit, reseal, status):
    repo = repo_copy(tmp_path)
    rewrite(repo / V3, edit, reseal=reseal)
    check = pm.verify(runtime_for("FOREX"), repo / V3, repository_root=repo)
    assert check.status == status and check.block_new_risk


@pytest.mark.parametrize("edit, status", [
    (lambda d: d[pm.V3_RATIFICATION_RECORD_KEY].__setitem__("status", "PENDING"), pm.GRANT_MISSING),
    (lambda d: d[pm.V3_RATIFICATION_RECORD_KEY]["manifest_pin"].__setitem__("manifest_version", 2),
     pm.GRANT_MISMATCH),
    (lambda d: d[pm.V3_RATIFICATION_RECORD_KEY].__setitem__("live_effect", "LIVE"), pm.GRANT_MISMATCH),
    (lambda d: d.__setitem__("note", "edited"), pm.GRANT_MISMATCH),           # the sealed file changed
    (lambda d: d.pop(pm.V3_RATIFICATION_RECORD_KEY), pm.GRANT_MISSING),
])
def test_an_edited_ratification_registry_blocks_new_risk(tmp_path, edit, status):
    repo = repo_copy(tmp_path)
    path = repo / pm.V3_RATIFICATION_REGISTRY_PATH
    data = json.loads(path.read_text(encoding="utf-8"))
    edit(data)
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    assert pm.verify(runtime_for("FOREX"), repo / V3, repository_root=repo).status == status


def test_exp002_parameters_are_still_bound_to_the_sealed_v585_grant(tmp_path):
    repo = repo_copy(tmp_path)
    rewrite(repo / V3, lambda d: d["policy"].__setitem__("exp002_max_admissions", 31))
    # the edited manifest moves its bytes too; pin them so only the EXP-002 comparison is left to fail
    reg = repo / pm.V3_RATIFICATION_REGISTRY_PATH
    data = json.loads(reg.read_text(encoding="utf-8"))
    data[pm.V3_RATIFICATION_RECORD_KEY]["manifest_pin"]["manifest_file_sha256"] = pm.file_sha256(
        (repo / V3).read_bytes())
    reg.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    original = pm.V3_RATIFICATION_REGISTRY_SHA256
    try:
        pm.V3_RATIFICATION_REGISTRY_SHA256 = pm.file_sha256(reg.read_bytes())
        check = pm.verify({**runtime_for("FOREX"), "exp002_max_admissions": 31}, repo / V3, repository_root=repo)
    finally:
        pm.V3_RATIFICATION_REGISTRY_SHA256 = original
    assert check.status == pm.GRANT_MISMATCH and "EXP-002" in check.detail


# ---------------------------------------------------------------- the real application, built as main.py builds it


def main_kwargs(tmp_path, monkeypatch) -> dict:
    from tests.test_phase2_g2_exp002_grant import production_kwargs

    return production_kwargs(tmp_path, monkeypatch)


@pytest.mark.parametrize("market", ["CRYPTO", "FOREX"])
def test_the_application_built_as_main_py_matches_v3(tmp_path, monkeypatch, market):
    import main

    kwargs = main_kwargs(tmp_path, monkeypatch)
    app = AtlasApplication(**{**kwargs, "state_directory": seed_state(tmp_path / "state"), "market": market})
    try:
        check = main.apply_policy_manifest(app)
        assert check.status == pm.MATCH, check.to_dict()
        assert app.execution.policy_manifest_block is None
        runtime = pm.runtime_policy(app)
        assert runtime["market"] == market and runtime["forex_weekend_close_minutes"] == 30
        expected = ("ENFORCE", 1) if market == "FOREX" else ("OBSERVE", 0)
        assert (runtime["exit_guard_mode"], runtime["exit_guard_rules"]) == expected
    finally:
        app.stop()


# ---------------------------------------------------------------- the WEEKEND_CLOSE rule


def at(text):
    return datetime.fromisoformat(text).replace(tzinfo=UTC)


def weekend_rule(window=is_forex_pre_close):
    return ExitRule("forex-weekend-close", RULE_WEEKEND_CLOSE, None, minutes=30, in_window=window)


class Book:
    def __init__(self, positions):
        self.positions = positions

    def snapshot(self):
        return {"positions": self.positions}


class Manager:
    def __init__(self):
        self.calls = []

    def execute(self, decision, _):
        self.calls.append(decision)
        return {"status": "COMPLETED"}


POSITION = {"EURUSD": {"base_quantity": "2000", "average_entry_price": "1.08", "position_id": "p1",
                       "opened_at": "2026-10-30T10:00:00+00:00", "mark_price": "1.081"}}


def guard_at(moment, rules=None, mode=ENFORCE, positions=POSITION):
    manager = Manager()
    guard = ExitGuard(manager, Book(positions), rules=rules if rules is not None else (weekend_rule(),), mode=mode,
                      clock=lambda: at(moment).timestamp())
    return guard, manager


def fresh(moment, price="1.0805"):
    return {"EURUSD": Mark(Decimal(price), at(moment).timestamp())}


@pytest.mark.parametrize("moment, triggered", [
    ("2026-10-30T20:29:59", False), ("2026-10-30T20:30:00", True),      # EDT: close 21:00 UTC
    ("2026-10-30T20:59:59", True), ("2026-11-13T21:30:00", True),       # EST: close 22:00 UTC
    ("2026-11-13T21:29:59", False), ("2026-10-28T20:45:00", False),     # Wednesday
])
def test_open_positions_are_closed_in_the_last_30_minutes(moment, triggered):
    guard, manager = guard_at(moment)
    outcome = guard.run_once(fresh(moment))[0]
    assert (outcome["state"] == EXIT_TRIGGERED) is triggered
    if triggered:
        sell = manager.calls[0]
        assert sell["action"] == "SELL" and sell["reduce_only"] is True and sell["exit_rule_id"] == "forex-weekend-close"
        assert outcome["detail"]["window_minutes"] == 30
    else:
        assert manager.calls == [] and outcome["state"] == EXIT_NOT_TRIGGERED


def test_never_on_a_stale_or_missing_price():
    moment = "2026-10-30T20:45:00"
    guard, manager = guard_at(moment)
    stale = {"EURUSD": Mark(Decimal("1.08"), at(moment).timestamp() - 3600)}
    for marks in ({}, stale):
        assert guard.run_once(marks)[0]["state"] == EXIT_PENDING_PRICE
    assert manager.calls == []


def test_the_same_position_gets_the_same_request_every_cycle():
    moment = "2026-10-30T20:45:00"
    guard, manager = guard_at(moment)
    guard.run_once(fresh(moment))
    guard.run_once(fresh(moment))
    assert len(manager.calls) == 2 and manager.calls[0]["request_id"] == manager.calls[1]["request_id"]


@pytest.mark.parametrize("window", [lambda now, minutes: 1 / 0, lambda now, minutes: None,
                                    lambda now, minutes: "yes", lambda now: True])
def test_an_unsure_window_check_exits(window):
    moment = "2026-10-28T12:00:00"
    guard, manager = guard_at(moment, rules=(weekend_rule(window),))
    assert guard.run_once(fresh(moment))[0]["state"] == EXIT_TRIGGERED and len(manager.calls) == 1


def test_observe_mode_never_submits():
    moment = "2026-10-30T20:45:00"
    guard, manager = guard_at(moment, mode=OBSERVE)
    assert guard.run_once(fresh(moment))[0]["outcome"] == "OBSERVED" and manager.calls == []


@pytest.mark.parametrize("kwargs, message", [
    ({"kind": RULE_WEEKEND_CLOSE, "threshold": Decimal("0.05"), "minutes": 30, "in_window": lambda n, m: True},
     "no threshold"),
    ({"kind": RULE_WEEKEND_CLOSE, "threshold": None, "minutes": 0, "in_window": lambda n, m: True}, "minutes"),
    ({"kind": RULE_WEEKEND_CLOSE, "threshold": None, "minutes": True, "in_window": lambda n, m: True}, "minutes"),
    ({"kind": RULE_WEEKEND_CLOSE, "threshold": None, "minutes": 30, "in_window": None}, "in_window"),
    ({"kind": RULE_MAX_LOSS_PCT, "threshold": Decimal("0.05"), "minutes": 30}, "no minutes"),
    ({"kind": "TIME_STOP", "threshold": None}, "unsupported"),
])
def test_rule_validation(kwargs, message):
    with pytest.raises(ValueError, match=message):
        ExitRule("r", **kwargs)


def test_the_max_loss_rule_is_unchanged():
    moment = "2026-10-28T12:00:00"
    rule = ExitRule("stop", RULE_MAX_LOSS_PCT, Decimal("0.05"))
    guard, manager = guard_at(moment, rules=(rule,))
    assert guard.run_once(fresh(moment, "1.07"))[0]["state"] == EXIT_NOT_TRIGGERED
    assert guard.run_once(fresh(moment, "1.02"))[0]["state"] == EXIT_TRIGGERED


# ---------------------------------------------------------------- wiring


def test_the_cycle_runs_the_guard_once_before_any_symbol():
    order = []
    loop = MarketLoop(brain=Brain(), market_feed=Feed(), execution=Execution(), symbols=["EURUSD", "GBPUSD"])
    loop.running = True
    loop.process_symbol = lambda symbol, processing_cutoff=None: order.append(symbol)
    loop.exit_guard_runner = lambda cutoff: order.append(("guard", cutoff.tzinfo is not None))
    loop.run_cycle()
    assert order == [("guard", True), "EURUSD", "GBPUSD"]


def test_a_failing_guard_never_stops_the_cycle():
    order = []
    loop = MarketLoop(brain=Brain(), market_feed=Feed(), execution=Execution(), symbols=["EURUSD"])
    loop.running = True
    loop.process_symbol = lambda symbol, processing_cutoff=None: order.append(symbol)
    loop.exit_guard_runner = lambda cutoff: 1 / 0
    loop.run_cycle()
    assert order == ["EURUSD"]


@pytest.mark.parametrize("market", ["CRYPTO", "FOREX"])
def test_only_forex_runs_the_weekend_close_guard(tmp_path, market):
    app = AtlasApplication(state_directory=seed_state(tmp_path / "state"), market=market)
    try:
        guard = app.exit_guard
        if market == "FOREX":
            assert guard.mode == ENFORCE and [r.kind for r in guard.rules] == [RULE_WEEKEND_CLOSE]
            assert guard.rules[0].minutes == 30 and app.market_loop.exit_guard_runner is not None
        else:
            assert guard.mode == OBSERVE and guard.rules == () and app.market_loop.exit_guard_runner is None
    finally:
        app.stop()


def test_the_window_is_the_rule_s_own_minutes():
    seen = []
    rule = ExitRule("w", RULE_WEEKEND_CLOSE, None, minutes=17, in_window=lambda now, minutes: seen.append(minutes))
    guard, _ = guard_at("2026-10-28T12:00:00", rules=(rule,))
    guard.run_once(fresh("2026-10-28T12:00:00"))
    assert seen == [17]


def forex_app(tmp_path):
    return AtlasApplication(state_directory=seed_state(tmp_path / "state"), market="FOREX")


def test_the_forex_runner_stamps_each_mark_with_its_own_candle_time(tmp_path, monkeypatch):
    app = forex_app(tmp_path)
    try:
        seen = {}
        open_ms = int(at("2026-10-30T20:44:00").timestamp() * 1000)
        app.market_loop.recent_candles = {"EURUSD": ((open_ms, 1.08, 1.081, 1.079, 1.0805),), "GBPUSD": ()}
        monkeypatch.setattr(app.exit_guard, "run_once", lambda marks: seen.update(marks=marks) or [])
        app.market_loop.exit_guard_runner(at("2026-10-30T20:45:00"))
        assert seen["marks"] == {"EURUSD": Mark(Decimal("1.0805"), open_ms / 1000)}
    finally:
        app.stop()


@pytest.mark.parametrize("candle_offset_s, state", [(-60, EXIT_TRIGGERED), (-300, EXIT_PENDING_PRICE),
                                                    (30, EXIT_PENDING_PRICE)])
def test_a_stale_or_future_candle_never_drives_an_exit(tmp_path, candle_offset_s, state):
    # review T023-F2: the guard's own age check sees the candle's real time, so a future candle is refused
    moment = at("2026-10-30T20:45:00")
    guard, manager = guard_at("2026-10-30T20:45:00")
    marks = {"EURUSD": Mark(Decimal("1.0805"), moment.timestamp() + candle_offset_s)}
    assert guard.run_once(marks)[0]["state"] == state
    assert (len(manager.calls) == 1) is (state == EXIT_TRIGGERED)


def test_a_forex_guard_the_cycle_does_not_run_blocks_new_risk(tmp_path, monkeypatch):
    import main

    kwargs = main_kwargs(tmp_path, monkeypatch)
    app = AtlasApplication(**{**kwargs, "state_directory": seed_state(tmp_path / "state"), "market": "FOREX"})
    try:
        assert main.apply_policy_manifest(app).status == pm.MATCH
        app.market_loop.exit_guard_runner = None                              # review T023-F1
        check = pm.verify(pm.runtime_policy(app))
        assert check.status == pm.POLICY_MISMATCH and "forex_weekend_close_minutes" in [m[0] for m in check.mismatches]
        app.market_loop.exit_guard_runner = lambda cutoff: None               # a runner of some other guard
        assert pm.verify(pm.runtime_policy(app)).status == pm.POLICY_MISMATCH
    finally:
        app.stop()
