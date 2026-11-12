"""Phase-2 D1: health / readiness / liveness.

The model is a pure function (core.system_health.assess); the integration
tests run a real AtlasApplication on tmp_path state.
"""

from __future__ import annotations

import json
import time

import pytest

import atlas_supervisor
import web_app
from atlas_supervisor import ProcessSupervisor, loop_stalled
from core import system_health as sh
from tests.test_block2_risk_service_composition_wiring import seed_valid_state
from tests.test_risk_accounting_day_auto_rollover import _app


@pytest.fixture(autouse=True)
def _isolated_roots(monkeypatch):
    monkeypatch.delenv("ATLAS_LOG_DIRECTORY", raising=False)


HEALTHY = dict(
    running=True, loop_thread_alive=True, loop_progress_age_seconds=1.0,
    loop_interval_seconds=10, market_data_stale=False, execution_running=True,
    execution_halted=False, recovery_required=False,
    audit_persistence_state="HEALTHY", brain_healthy=True,
)


def _with(**changes):
    return sh.assess({**HEALTHY, **changes})


def test_all_ok_is_ready_and_safe():
    result = sh.assess(HEALTHY)
    assert result["system_state"] == sh.READY
    assert result["safe_to_trade"] and result["safe_to_reduce"] and result["system_ready"]


def test_process_alive_but_loop_stalled():
    result = _with(loop_progress_age_seconds=10_000)
    assert result["process_alive"] == sh.OK
    assert result["loop_progressing"] == sh.FAILED
    assert result["system_state"] == sh.STALLED
    assert not result["safe_to_trade"] and not result["safe_to_reduce"]


def test_dead_loop_thread_is_failed_even_with_recent_progress():
    assert _with(loop_running=True, loop_thread_alive=False)["loop_progressing"] == sh.FAILED


def test_loop_not_started_is_starting_not_stalled():
    result = _with(loop_running=False, loop_thread_alive=False)
    assert result["loop_progressing"] == sh.UNKNOWN
    assert result["system_state"] == sh.STARTING


def test_loop_alive_but_market_feed_stale():
    result = _with(market_data_stale=True)
    assert result["loop_progressing"] == sh.OK
    assert result["market_data_healthy"] == sh.DEGRADED
    assert result["system_state"] == sh.DEGRADED_NEW_RISK_BLOCKED
    # Stale price: neither new risk nor a blind exit.
    assert not result["safe_to_trade"] and not result["safe_to_reduce"]


def test_audit_degraded_blocks_trade_not_reduce():
    result = _with(audit_persistence_state="DEGRADED")
    assert result["audit_healthy"] == sh.DEGRADED
    assert result["system_state"] == sh.DEGRADED_NEW_RISK_BLOCKED
    assert not result["safe_to_trade"]
    assert result["safe_to_reduce"]


def test_audit_recovery_required_is_recovery_state():
    result = _with(audit_persistence_state="RECOVERY_REQUIRED")
    assert result["system_state"] == sh.RECOVERY_REQUIRED
    # A poisoned audit writer cannot record the realized-P&L write-ahead
    # event, so ExecutionManager refuses exits too (B2).
    assert not result["safe_to_reduce"]


def test_execution_unavailable():
    result = _with(execution_running=False)
    assert result["execution_healthy"] == sh.FAILED
    assert not result["safe_to_reduce"]


def test_execution_recovery_required():
    result = _with(recovery_required=True)
    assert result["system_state"] == sh.RECOVERY_REQUIRED
    assert not result["safe_to_reduce"] and not result["safe_to_trade"]


def test_brain_degraded_blocks_new_risk_only():
    result = _with(brain_healthy=False)
    assert result["brain_healthy"] == sh.DEGRADED
    assert not result["safe_to_trade"] and result["safe_to_reduce"]


@pytest.mark.parametrize(
    "field",
    ["running", "loop_progress_age_seconds", "market_data_stale",
     "execution_running", "audit_persistence_state", "brain_healthy"],
)
def test_unknown_is_never_healthy(field):
    inputs = dict(HEALTHY)
    inputs.pop(field)
    result = sh.assess(inputs)
    assert not result["safe_to_trade"]
    assert result["system_state"] != sh.READY


@pytest.mark.parametrize("garbage", [None, "x", 7, {"running": "yes"},
                                     {"loop_progress_age_seconds": float("nan")}])
def test_malformed_inputs_never_raise_or_read_healthy(garbage):
    result = sh.assess(garbage)
    assert result["safe_to_trade"] is False
    assert result["system_state"] != sh.READY


# ------------------------------------------------------------ integration


def test_application_health_reports_system_health(tmp_path):
    state_dir = tmp_path / "state"
    seed_valid_state(state_dir)
    app = _app(state_dir)

    health = app.health()

    assert "system_health" in health
    system = health["system_health"]
    # MarketLoop is not started in this harness: unknown/STARTING, never OK.
    assert system["loop_progressing"] == sh.UNKNOWN
    assert system["system_state"] == sh.STARTING
    assert system["safe_to_trade"] is False
    assert system["audit_healthy"] == sh.OK
    json.dumps(health)  # /api/health returns it verbatim


def test_market_loop_progress_is_reported_after_a_cycle(tmp_path):
    state_dir = tmp_path / "state"
    seed_valid_state(state_dir)
    app = _app(state_dir)
    loop = app.market_loop
    loop.last_loop_progress_monotonic = time.monotonic()

    health = loop.health()
    assert 0 <= health["loop_progress_age_seconds"] < 5
    # Progress alone is not enough while the loop is not running.
    assert app.health()["system_health"]["loop_progressing"] == sh.UNKNOWN


def test_api_status_allowlist_publishes_system_health_codes_only():
    status = {"health": {"system_health": {
        "system_state": "READY", "safe_to_trade": True,
        "audit_healthy": "/etc/passwd leaked", "unexpected": "x",
    }}}
    public = web_app._public_runtime_status(status)
    system = public["health"]["system_health"]
    assert system["system_state"] == "READY"
    assert system["safe_to_trade"] is True
    assert system["audit_healthy"] is None
    assert "unexpected" not in system


# ------------------------------------------------------------ supervisor


def test_loop_stalled_reads_the_heartbeat_payload():
    assert loop_stalled({"loop_progress_age_seconds": 1, "loop_interval_seconds": 10}) is False
    assert loop_stalled({"loop_progress_age_seconds": 10_000, "loop_interval_seconds": 10}) is True
    assert loop_stalled({"written_at": 1}) is None
    assert loop_stalled(None) is None


def test_supervisor_only_observes_a_stall(tmp_path, caplog):
    payloads = iter([
        {"loop_progress_age_seconds": 10_000, "loop_interval_seconds": 10},
        {"loop_progress_age_seconds": 10_000, "loop_interval_seconds": 10},
        {"loop_progress_age_seconds": 1, "loop_interval_seconds": 10},
    ])
    supervisor = ProcessSupervisor(
        launch=lambda env: None, epoch="a" * 32,
        heartbeat_file=tmp_path / "hb.json",
        heartbeat_payload=lambda path: next(payloads),
    )
    assert atlas_supervisor.LOOP_STALL_POLICY == "OBSERVE"

    with caplog.at_level("INFO"):
        supervisor._observe_loop_stall()
        supervisor._observe_loop_stall()  # same verdict: not re-logged
        supervisor._observe_loop_stall()

    assert [r.getMessage().split(" (")[0] for r in caplog.records].count(
        "Atlas process is alive but MarketLoop is not progressing") == 1
    assert "MarketLoop progressing again" in caplog.text
    assert supervisor.child is None  # nothing was stopped or launched


def test_main_heartbeat_carries_loop_progress(tmp_path):
    import main

    process = main.AtlasProcess.__new__(main.AtlasProcess)

    class _Loop:
        last_loop_progress_monotonic = time.monotonic() - 2
        interval = 10

    class _App:
        market_loop = _Loop()

    process.application = _App()
    payload = process._loop_progress_payload()
    assert 1 <= payload["loop_progress_age_seconds"] < 10
    assert payload["loop_interval_seconds"] == 10

    process.application = None
    assert process._loop_progress_payload()["loop_progress_age_seconds"] is None
