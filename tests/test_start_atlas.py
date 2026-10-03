"""Launcher (owner 2026-10-03, "will the system crash?"): the agents run as their own lower-priority process
beside Atlas; an exit is restarted after a growing pause and given up after repeated exits, a hang is killed,
a stop asks first and kills last, a killed writer's record locks are released, and nothing reaches Atlas.

Replaces the 2026-10-02 tests of the thread-based agent_loop: the agents no longer run as a thread of the
launcher (a thread cannot be killed, given a lower priority or restarted, and dying with the launcher could
cut a record write). The properties those tests pinned - the agents run while Atlas runs, stop with it, and
an agent error never escapes - are pinned here for the process.
"""

from __future__ import annotations

import os
import subprocess
import sys
import time

import pytest

from tools import atlas_org_cli as cli
from tools import start_atlas as sa


class FakeProc:
    """Exits with `code` after `alive` polls (None: runs until killed); may ignore the polite stop."""

    _next_pid = 4000

    def __init__(self, code=1, alive=0, ignores_stop=False):
        FakeProc._next_pid += 1
        self.pid, self.code, self.alive, self.ignores_stop = FakeProc._next_pid, code, alive, ignores_stop
        self.returncode, self.signals, self.killed, self.stdin = None, [], False, None

    def poll(self):
        if self.returncode is None and self.code is not None:
            if self.alive <= 0:
                self.returncode = self.code
            self.alive -= 1
        return self.returncode

    def send_signal(self, sig):
        self.signals.append(sig)
        if not self.ignores_stop:
            self.returncode = 0

    def wait(self, timeout=None):
        if self.returncode is None:
            raise subprocess.TimeoutExpired("agents", timeout)
        return self.returncode

    def kill(self):
        self.killed, self.returncode = True, -9


def _supervisor(tmp_path, procs, clock, wall=None):
    spawned = []

    def spawn(cmd):
        proc = procs.pop(0)
        spawned.append(proc)
        return proc
    logs = []
    sup = sa.AgentSupervisor(["agents"], tmp_path / "heartbeat", tmp_path / "records", spawn=spawn,
                             clock=lambda: clock["t"], wall=wall or (lambda: clock["t"] + 1_000_000), log=logs.append)
    return sup, spawned, logs


def test_launcher_runs_the_agent_runner_with_parent_watch():
    cmd = sa.agent_command(5)
    assert cmd[1:4] == ["-m", "tools.agent_cycle", "--every"] and "--parent-watch" in cmd


def test_exits_are_restarted_with_growing_pauses_then_given_up(tmp_path):
    clock = {"t": 0.0}
    sup, spawned, logs = _supervisor(tmp_path, [FakeProc(code=1) for _ in range(7)], clock)
    pauses = []
    for _ in range(7):
        sup.poll()                                  # start
        sup.poll()                                  # notice the exit
        if sup.gave_up:
            break
        pauses.append(sup.next_start - clock["t"])
        clock["t"] = sup.next_start - 1
        sup.poll()                                  # one second early: no restart yet
        assert len(spawned) == len(pauses)
        clock["t"] = sup.next_start
    # RestartPolicy's meaning (the same as Atlas's supervisor): five restarts, then stop - six runs in all
    assert pauses == [30.0, 60.0, 120.0, 300.0, 600.0] and sup.gave_up and len(spawned) == 6
    sup.poll()
    assert len(spawned) == 6 and "yeniden başlatılmayacak" in logs[-1]   # given up; Atlas is not touched


def test_a_long_healthy_run_forgives_earlier_exits(tmp_path):
    clock = {"t": 0.0}
    sup, spawned, _ = _supervisor(tmp_path, [FakeProc(code=1), FakeProc(code=1)], clock)
    sup.poll(); sup.poll()
    assert sup.attempt == 1
    clock["t"] = sup.next_start
    sup.poll()
    clock["t"] += 1801                              # ran longer than healthy_run_seconds before exiting
    sup.poll()
    assert sup.attempt == 1 and not sup.gave_up


def test_a_hung_agent_process_is_killed_and_restarted(tmp_path):
    clock = {"t": 0.0}
    wall = {"t": 1_000_000.0}
    hung = FakeProc(code=None)
    sup, spawned, logs = _supervisor(tmp_path, [hung, FakeProc(code=None)], clock, wall=lambda: wall["t"])
    sup.poll()
    (tmp_path / "heartbeat").write_text("x")
    os.utime(tmp_path / "heartbeat", (wall["t"], wall["t"]))
    wall["t"] += sa.AGENT_HANG_S - 1
    sup.poll()
    assert not hung.killed                          # a long tick is not a hang
    wall["t"] += 2
    sup.poll()
    assert hung.killed and sup.proc is None and "kalp atışı yok" in logs[-2]
    clock["t"] = sup.next_start
    sup.poll()
    assert len(spawned) == 2


def test_a_second_runner_is_left_to_the_first(tmp_path):
    clock = {"t": 0.0}
    sup, spawned, logs = _supervisor(tmp_path, [FakeProc(code=sa.ALREADY_RUNNING_EXIT)], clock)
    sup.poll(); sup.poll()
    clock["t"] = 10_000
    sup.poll()
    assert sup.gave_up and len(spawned) == 1 and "zaten açık" in logs[-1]


def test_stop_asks_first_then_kills_and_releases_only_the_killed_writers_locks(tmp_path):
    records = tmp_path / "records"
    records.mkdir()
    clock = {"t": 0.0}
    polite = FakeProc(code=None)
    sup, _, _ = _supervisor(tmp_path, [polite], clock)
    sup.poll()
    sup.stop()
    assert polite.signals == [sa.STOP_SIGNAL] and not polite.killed   # asked and obeyed: not killed
    stubborn = FakeProc(code=None, ignores_stop=True)
    sup, _, logs = _supervisor(tmp_path, [stubborn], clock)
    sup.poll()
    (records / "memory.jsonl.lock").write_text(str(stubborn.pid))
    (records / "tasks.jsonl.lock").write_text("123456789")             # someone else's: kept
    sa.AGENT_STOP_GRACE_S, grace = 0.01, sa.AGENT_STOP_GRACE_S
    try:
        sup.stop()
    finally:
        sa.AGENT_STOP_GRACE_S = grace
    assert stubborn.killed and not (records / "memory.jsonl.lock").exists()
    assert (records / "tasks.jsonl.lock").exists() and "kayıt kilitleri bırakıldı" in logs[-1]


def test_record_lock_names_its_writer(tmp_path):
    with cli._lock(tmp_path / cli.MEMORY_LOG):
        assert (tmp_path / (cli.MEMORY_LOG + ".lock")).read_text() == str(os.getpid())
    assert not (tmp_path / (cli.MEMORY_LOG + ".lock")).exists()
    (tmp_path / "x.lock").write_text("held")                            # an old, PID-less lock is never touched
    assert cli.release_locks_of(tmp_path, os.getpid()) == [] and (tmp_path / "x.lock").exists()


@pytest.mark.skipif(os.name == "nt", reason="POSIX session / niceness checks; Windows uses CREATE_NEW_PROCESS_GROUP + BELOW_NORMAL")
def test_real_agent_process_runs_apart_at_lower_priority_and_stops_politely(tmp_path):
    script = ("import signal, sys, time\n"
              "signal.signal(signal.SIGTERM, lambda *a: sys.exit(0))\n"
              "print('up', flush=True)\n"
              "time.sleep(60)\n")
    proc = sa.spawn_agents([sys.executable, "-c", script])
    try:
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline and os.getpriority(os.PRIO_PROCESS, proc.pid) < 10:
            time.sleep(0.05)
        assert os.getsid(proc.pid) == proc.pid                          # own session: a terminal Ctrl+C is ours to forward
        assert os.getpriority(os.PRIO_PROCESS, proc.pid) >= 10          # below Atlas
        sup = sa.AgentSupervisor(["x"], tmp_path / "hb", tmp_path, spawn=lambda cmd: proc, log=lambda line: None)
        sup.poll()
        time.sleep(0.5)                                                 # let the child install its handler
        started = time.monotonic()
        sup.stop()
        assert proc.returncode == 0 and time.monotonic() - started < sa.AGENT_STOP_GRACE_S
    finally:
        if proc.poll() is None:
            proc.kill()
            proc.wait()


def test_without_a_heartbeat_path_atlas_still_starts_and_no_hang_is_invented(tmp_path):
    clock = {"t": 0.0}
    proc = FakeProc(code=None)
    sup = sa.AgentSupervisor(["agents"], None, tmp_path, spawn=lambda cmd: proc, clock=lambda: clock["t"],
                             wall=lambda: 10 ** 9 + clock["t"], log=lambda line: None)
    sup.poll()
    clock["t"] += 10 * sa.AGENT_HANG_S
    sup.poll()
    assert not proc.killed and sup.proc is proc


@pytest.mark.skipif(os.name == "nt", reason="POSIX stop signal; Windows uses CTRL_BREAK_EVENT to the agents' group")
def test_whole_chain_launcher_to_real_runner_stops_politely(tmp_path, monkeypatch):
    from tests.test_agent_runner import _RUNNER

    state, records = tmp_path / "state", tmp_path / "records"
    state.mkdir()
    monkeypatch.setenv("ATLAS_STATE_DIRECTORY", str(state))             # inherited by the child
    beat = state / "research" / "agent_runner" / "heartbeat"
    sup = sa.AgentSupervisor(["unused"], beat, records, log=lambda line: None,
                             spawn=lambda cmd: sa.spawn_agents([sys.executable, "-c", _RUNNER, str(records)]))
    sup.poll()
    proc = sup.proc
    try:
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline and not (records / cli.MEMORY_LOG).exists():
            sup.poll()
            time.sleep(0.1)
        assert beat.exists() and (records / cli.MEMORY_LOG).exists() and sup.proc is proc  # ran, alive, not "hung"
        sup.stop()
        assert proc.returncode == 0                                       # asked, finished, exited cleanly
    finally:
        if proc.poll() is None:
            proc.kill()
            proc.wait()
