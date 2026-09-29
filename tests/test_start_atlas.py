"""Launcher: agents run while Atlas runs and stop with it; an agent error never escapes."""

from __future__ import annotations

import threading

from tools.start_atlas import agent_loop


def test_agent_loop_runs_until_stopped_and_survives_errors():
    stop = threading.Event()
    calls = []

    def cycle():
        calls.append(1)
        if len(calls) == 1:
            raise RuntimeError("archive locked")
        if len(calls) >= 3:
            stop.set()
        return {"record_id": "AC-0001", "results": [{"verdict": "OK"}]}

    agent_loop(stop, every_minutes=0, run_cycle=cycle, first_delay=0)
    assert len(calls) == 3


def test_agent_loop_does_nothing_if_atlas_stops_first():
    stop = threading.Event()
    stop.set()
    agent_loop(stop, every_minutes=60, run_cycle=lambda: (_ for _ in ()).throw(AssertionError("ran")), first_delay=5)
