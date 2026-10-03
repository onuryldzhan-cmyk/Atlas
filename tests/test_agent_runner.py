"""The agent runner process (owner 2026-10-03): one at a time, a heartbeat while it works, a stop request
never cuts an agent in half, and it stops by itself when its launcher is gone."""

from __future__ import annotations

import io
import subprocess
import sys
import threading
from pathlib import Path

from core import instance_lock
from tools import agent_cycle as ac
from tools import atlas_org_cli as cli

ROOT = Path(__file__).resolve().parents[1]


def _isolate(tmp_path, monkeypatch, agents):
    state = tmp_path / "state"
    state.mkdir()
    monkeypatch.setenv("ATLAS_STATE_DIRECTORY", str(state))              # schedule, heartbeat, usage: all here
    monkeypatch.setattr(cli, "RECORDS_DIR", tmp_path / "records")         # never the repository's records
    monkeypatch.setattr(ac, "AGENTS", agents)
    monkeypatch.setattr(ac, "_input_paths", lambda d: {k: tmp_path / f"{k}.missing" for k in
                                                       ("archive", "audit", "memory", "proposals", "tasks")})
    return state


def test_only_one_agent_runner_runs_at_a_time(tmp_path, monkeypatch):
    ran = []
    _isolate(tmp_path, monkeypatch, (("a", "A", lambda d: ran.append(1) or {"verdict": "OK", "summary": "ok"}),))
    monkeypatch.setattr(instance_lock, "RETRY_SECONDS", 0.3)
    lock_dir = ac.runner_dir()
    holder = subprocess.Popen(
        [sys.executable, "-c", "import sys, time; from pathlib import Path; from core import instance_lock; "
                               "instance_lock.acquire(Path(sys.argv[1])); print('held', flush=True); time.sleep(30)",
         str(lock_dir)], cwd=str(ROOT), stdout=subprocess.PIPE, text=True)
    try:
        assert holder.stdout.readline().strip() == "held"
        assert ac.main([]) == ac.ALREADY_RUNNING_EXIT and ran == []        # refused, nothing ran
    finally:
        holder.kill()
        holder.wait()
    assert ac.main([]) == 0 and ran == [1]                                  # the OS dropped the dead holder's lock
    assert not instance_lock.held(lock_dir)                                 # and ours is released after the run


def test_runner_loop_beats_runs_what_is_due_and_releases_its_lock(tmp_path, monkeypatch):
    ran = []
    _isolate(tmp_path, monkeypatch, (("a", "A", lambda d: ran.append(1) or {"verdict": "OK", "summary": "ok"}),))
    monkeypatch.setattr(ac, "_sleep", lambda stop, seconds, **kw: True)    # one tick, then stop
    import signal
    before = signal.getsignal(signal.SIGTERM)
    assert ac.main(["--every", "5"]) == 0
    assert ran == [1] and (ac.runner_dir() / ac.HEARTBEAT_FILE).exists()
    assert not instance_lock.held(ac.runner_dir())
    assert signal.getsignal(signal.SIGTERM) == before                      # the caller's handlers are back


def test_a_stop_request_never_cuts_an_agent_in_half(tmp_path, monkeypatch):
    stop, ran, beats = threading.Event(), [], []

    def first(_):
        ran.append("first")
        stop.set()                                                          # a stop arrives while it works
        return {"verdict": "OK", "summary": "bitti"}

    monkeypatch.setattr(ac, "_input_paths", lambda d: {})
    out = ac.run_scheduled(tmp_path, (("x", "X", first), ("y", "Y", lambda d: ran.append("second"))),
                           state_path=tmp_path / "s.json", should_stop=stop.is_set, beat=lambda: beats.append(1))
    assert ran == ["first"] and out["results"][0]["summary"] == "bitti" and beats == [1]


def test_runner_stops_when_its_launcher_is_gone():
    for stream in (io.BytesIO(b""), io.BytesIO(b"noise")):
        stop = threading.Event()
        ac._watch_parent(stop, stream)                                      # EOF: the launcher's end closed
        assert stop.is_set()

    class Broken:
        def read(self, n):
            raise OSError("broken pipe")
    stop = threading.Event()
    ac._watch_parent(stop, Broken())
    assert stop.is_set()


def test_sleep_wakes_at_once_on_stop():
    stop = threading.Event()
    stop.set()
    assert ac._sleep(stop, 3600) is True


_RUNNER = """
import sys
from pathlib import Path
from tools import agent_cycle as ac, atlas_org_cli as cli
cli.RECORDS_DIR = Path(sys.argv[1])
ac._input_paths = lambda d: {}
ac.AGENTS = (("a", "A", lambda d: {"verdict": "OK", "summary": "calistim"}),)
raise SystemExit(ac.main(["--every", "0.02", "--parent-watch"]))
"""


def _real_runner(tmp_path):
    import os
    import time

    state, records = tmp_path / "state", tmp_path / "records"
    state.mkdir()
    proc = subprocess.Popen([sys.executable, "-c", _RUNNER, str(records)], cwd=str(ROOT), stdin=subprocess.PIPE,
                            stdout=subprocess.DEVNULL, env={**os.environ, "ATLAS_STATE_DIRECTORY": str(state)})
    beat = state / "research" / ac.RUNNER_DIR / ac.HEARTBEAT_FILE
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline and not (records / cli.MEMORY_LOG).exists():
        time.sleep(0.1)
    assert beat.exists() and (records / cli.MEMORY_LOG).exists(), "the runner never ticked"
    return proc


def test_real_runner_process_stops_when_its_launcher_closes_stdin(tmp_path):
    proc = _real_runner(tmp_path)
    try:
        proc.stdin.close()                                                  # the launcher is gone
        assert proc.wait(timeout=20) == 0                                   # finished its tick, then stopped
    finally:
        if proc.poll() is None:
            proc.kill()
            proc.wait()


def test_real_runner_process_stops_politely_on_the_stop_signal(tmp_path):
    import signal

    import pytest
    if not hasattr(signal, "SIGTERM") or sys.platform == "win32":
        pytest.skip("POSIX SIGTERM; Windows sends CTRL_BREAK_EVENT to the process group (SIGBREAK handler)")
    proc = _real_runner(tmp_path)
    try:
        proc.send_signal(signal.SIGTERM)
        assert proc.wait(timeout=20) == 0
    finally:
        if proc.poll() is None:
            proc.kill()
            proc.wait()
