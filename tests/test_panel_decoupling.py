"""The operator panel never decides whether trading runs (registry v5.15).

With a restart hook (atlas_service.build_process supplies one), a panel
that fails to start or dies is logged, trading continues, and the panel is
retried every SUBORDINATE_RESTART_INTERVAL_SECONDS. Without a hook the
original contract (exit 1) is unchanged - see test_merged_process_composition.
"""

from __future__ import annotations

import threading

import pytest

import main
from main import AtlasProcess
from tests.test_merged_process_composition import _RecordingApplication, _process_with


@pytest.fixture(autouse=True)
def fast_retry(monkeypatch):
    monkeypatch.setattr(main, "SUBORDINATE_RESTART_INTERVAL_SECONDS", 0.0)


def _run_for(process: AtlasProcess, seconds: float) -> None:
    timer = threading.Timer(seconds, process.shutdown_event.set)
    timer.start()
    try:
        process.run_forever()
    finally:
        timer.cancel()


def test_a_dead_panel_is_restarted_and_trading_never_stops():
    alive = {"value": False}
    restarts = []

    def restart():
        restarts.append(1)
        alive["value"] = True

    process = AtlasProcess(is_subordinate_alive=lambda: alive["value"], restart_subordinate=restart)
    process.application = _RecordingApplication()

    _run_for(process, 3.5)

    assert process.exit_code == 0
    assert process.shutdown_reason == ""
    assert restarts == [1]
    assert process._subordinate_down is False


def test_a_failing_restart_keeps_trading_and_keeps_retrying():
    attempts = []

    def restart():
        attempts.append(1)
        raise RuntimeError("port 8000 in use")

    process = AtlasProcess(is_subordinate_alive=lambda: False, restart_subordinate=restart)
    process.application = _RecordingApplication()

    _run_for(process, 4.5)

    assert process.exit_code == 0
    assert len(attempts) >= 2
    assert process._subordinate_down is True


def test_a_panel_that_fails_to_start_does_not_stop_atlas(monkeypatch):
    application = _RecordingApplication()
    restarted = []

    def failing_start(_app):
        raise RuntimeError("port already in use")

    process = _process_with(
        monkeypatch, application,
        on_started=failing_start,
        restart_subordinate=lambda: restarted.append(1),
    )
    timer = threading.Timer(2.5, process.shutdown_event.set)
    timer.start()
    try:
        exit_code = process.execute()
    finally:
        timer.cancel()

    assert exit_code == 0
    assert restarted, "the panel was never retried"
    assert application.stop_calls == 1


def test_a_trading_stop_still_ends_the_process_even_with_a_panel_hook():
    """Decoupling is one-way: the runtime stopping still stops Atlas."""

    process = AtlasProcess(is_subordinate_alive=lambda: True, restart_subordinate=lambda: None)
    application = _RecordingApplication()
    application.running = False
    process.application = application

    _run_for(process, 3.0)

    assert process.exit_code == 1
    assert process.shutdown_reason == "AtlasApplication stopped unexpectedly"


def test_a_slow_restart_never_blocks_the_main_loop_heartbeat(monkeypatch):
    """Audit MEDIUM: a restart waiting out its timeouts must not starve the
    supervisor heartbeat (the main loop writes it once per tick)."""

    release = threading.Event()
    heartbeats = []

    def slow_restart():
        release.wait(10)  # a start/stop timeout in progress

    process = AtlasProcess(is_subordinate_alive=lambda: False, restart_subordinate=slow_restart)
    process.application = _RecordingApplication()
    monkeypatch.setattr(process, "_write_heartbeat", lambda: heartbeats.append(1))

    _run_for(process, 4.5)
    release.set()

    # ~4 ticks while the restart is stuck: the loop kept beating.
    assert len(heartbeats) >= 3
    assert process.exit_code == 0


def test_a_real_web_server_restarts_after_dying_and_serves_again():
    """Audit LOW: the restart path exercised against a real uvicorn server,
    not fakes. It starts, serves, dies, is restarted by build_process's
    restart hook against the same runtime, and serves again."""

    import urllib.request

    from atlas_service import AtlasWebServer, build_process
    from tests.test_merged_process_composition import _StubRuntime, _free_port

    port = _free_port()
    web_server = AtlasWebServer(port=port, startup_timeout=20.0)
    process = build_process(server=web_server)
    runtime = _StubRuntime()

    def get_health() -> int:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/health", timeout=5) as response:
            return response.status

    process.on_started(runtime)  # type: ignore[arg-type]
    try:
        assert get_health() == 200

        # The panel dies on its own (not via stop()).
        dying = web_server.thread
        web_server.server.should_exit = True
        dying.join(timeout=10)
        assert web_server.is_alive() is False

        process.restart_subordinate()

        assert web_server.is_alive() is True
        assert web_server.thread is not dying
        assert get_health() == 200
    finally:
        web_server.stop()
