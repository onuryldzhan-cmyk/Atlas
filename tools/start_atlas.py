"""Start Atlas and its agents together with one command.

  python -m tools.start_atlas                 # Atlas (supervised) + agents (each on its own clock)
  python -m tools.start_atlas --every 5       # how often the scheduler checks whose turn it is

Atlas runs exactly as with `python atlas_supervisor.py` (same process, same Ctrl+C behaviour). Owner
2026-10-03 ("will the system crash?"): the agents run beside it as their own, lower-priority process
(`python -m tools.agent_cycle --every N --parent-watch`), so nothing they do can take Atlas down or starve
its market loop of CPU (Atlas's supervisor restarts Atlas when its heartbeat is 30 s late):

* the first start waits FIRST_CYCLE_DELAY_S, so Atlas's own startup has the machine;
* an agent process that exits while Atlas runs is restarted up to 5 times after a growing pause (30 s, 1, 2,
  5, 10 min: atlas_supervisor.RestartPolicy, a run of 30 min forgives earlier exits), then given up; Atlas
  keeps running either way;
* no heartbeat for AGENT_HANG_S: the agent process is stopped, which counts as an exit; only the time up to its
  last heartbeat counts as healthy, so a runner that hangs again and again is given up (audit M3);
* a stop asks first (Ctrl+Break on Windows, SIGTERM elsewhere): the runner stops at its next safe point, between
  agents. After AGENT_STOP_GRACE_S it is killed, which can cut a long model call short (safe: no record is being
  written then) and, on Windows, also ends what the agents started in their group (a model call, a background
  strategy comparison, whose marker expires after 6 h). Then the record locks the killed process held are
  released (each names its PID);
* only one agent runner can run (an OS lock): while another holds it, this launcher looks again every
  ALREADY_RUNNING_RETRY_S instead of giving up (audit L2);
* Atlas is started before any agent code is imported, so broken agent code can never keep Atlas from
  starting (audit M4);
* if this launcher dies, the agent process sees its stdin close and stops by itself.
"""

from __future__ import annotations

import argparse
import os
import signal
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Callable

ROOT = Path(__file__).resolve().parents[1]
FIRST_CYCLE_DELAY_S = 120
# A tick runs agents one after another; one agent is flagged at 5 min and a model call times out at 6, so
# a runner silent this long is stuck, not busy.
AGENT_HANG_S = 45 * 60
AGENT_STOP_GRACE_S = 20.0
POLL_S = 1.0
ALREADY_RUNNING_EXIT = 3  # tools.agent_cycle.ALREADY_RUNNING_EXIT (kept literal: no import before it is needed)
ALREADY_RUNNING_RETRY_S = 300.0
STOP_SIGNAL = getattr(signal, "CTRL_BREAK_EVENT", signal.SIGTERM)


def agent_restart_policy() -> Any:
    """Atlas's own bounded restart rule, with slower pauses: the agents are advisory, Atlas is not."""
    from atlas_supervisor import RestartPolicy

    return RestartPolicy(max_attempts=5, backoff_seconds=(30.0, 60.0, 120.0, 300.0, 600.0), healthy_run_seconds=1800.0)


def minutes(value: str) -> float:
    """--every: a finite number of minutes in (0, 1440] (audit L3). Kept here so no agent code is imported first."""
    try:
        n = float(value)
    except ValueError:
        raise argparse.ArgumentTypeError(f"{value!r} is not a number of minutes")
    if not (0 < n <= 1440):  # also false for NaN
        raise argparse.ArgumentTypeError(f"--every must be more than 0 and at most 1440 minutes, not {value}")
    return n


def agent_command(every: float) -> list[str]:
    return [sys.executable, "-m", "tools.agent_cycle", "--every", f"{every:g}", "--parent-watch"]


def spawn_agents(cmd: list[str]) -> subprocess.Popen:
    """Own process group (a stop reaches only the agents) at a lower CPU priority than Atlas."""
    kwargs: dict[str, Any] = {"cwd": str(ROOT), "stdin": subprocess.PIPE}
    if os.name == "nt":
        kwargs["creationflags"] = (getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)  # Windows-only names,
                                   | getattr(subprocess, "BELOW_NORMAL_PRIORITY_CLASS", 0))  # as atlas_supervisor
    else:
        kwargs["start_new_session"] = True
    proc = subprocess.Popen(cmd, **kwargs)
    if os.name != "nt":
        try:
            os.setpriority(os.PRIO_PROCESS, proc.pid, 10)  # inherited by what the agents start
        except (OSError, AttributeError):
            pass
    return proc


class AgentSupervisor:
    """Keeps the agent process alive while Atlas runs, and never lets it take Atlas down."""

    def __init__(self, cmd: list[str], heartbeat: Path | None, records_dir: Path, *,
                 spawn: Callable[[list[str]], Any] = spawn_agents, policy: Any = None,
                 clock: Callable[[], float] = time.monotonic, wall: Callable[[], float] = time.time,
                 log: Callable[[str], Any] = lambda line: print(line, flush=True)) -> None:
        self.cmd, self.records_dir = cmd, Path(records_dir)
        self.heartbeat = Path(heartbeat) if heartbeat is not None else None  # None: no hang check
        self.spawn, self.policy = spawn, policy or agent_restart_policy()
        self.clock, self.wall, self.log = clock, wall, log
        self.proc: Any = None
        self.attempt = 0
        self.started: float | None = None  # monotonic start of the current process
        self.started_wall = 0.0
        self.next_start = 0.0
        self.gave_up = False
        self.busy_logged = False

    def poll(self) -> None:
        """One look: start, notice an exit or a hang, schedule the restart. Never raises for the agents."""
        if self.gave_up:
            return
        now = self.clock()
        if self.proc is None:
            if now >= self.next_start:
                self._start(now)
            return
        code = self.proc.poll()
        if code is None:
            last_beat = self._last_beat()
            if self.wall() - last_beat > AGENT_HANG_S:
                self.log(f"[AJANLAR] {AGENT_HANG_S // 60} dk boyunca kalp atışı yok: ajan süreci durduruluyor")
                self._kill(self.proc)
                # audit M3: only the time up to its last heartbeat was healthy - a quick hang is a quick exit
                self._exited(now, "asılı kaldı", healthy_s=max(0.0, last_beat - self.started_wall))
            return
        self._released(self.proc)
        if code == ALREADY_RUNNING_EXIT:
            # audit L2: another runner (a second launcher, or a one-shot run) holds the lock; look again later
            self.proc, self.next_start = None, now + ALREADY_RUNNING_RETRY_S
            if not self.busy_logged:
                self.log("[AJANLAR] başka bir ajan çalıştırıcısı açık; ajanlar onunla çalışıyor. "
                         f"Bu başlatıcı {ALREADY_RUNNING_RETRY_S / 60:g} dk'da bir tekrar bakacak (Atlas çalışıyor)")
                self.busy_logged = True
            return
        self.busy_logged = False
        self._exited(now, f"çıkış kodu {code}")

    def _start(self, now: float) -> None:
        try:
            self.proc = self.spawn(self.cmd)
        except OSError as exc:
            self.proc = None
            self.started = now
            self._exited(now, f"başlatılamadı: {exc}")
            return
        self.started, self.started_wall = now, self.wall()
        self.log(f"[AJANLAR] ajan süreci başladı (pid {self.proc.pid}, Atlas'tan düşük öncelikte)")

    def _last_beat(self) -> float:
        """Wall time of the runner's last heartbeat (never before its start); now when there is no heartbeat path."""
        if self.heartbeat is None:
            return self.wall()  # no path: no hang is ever invented
        try:
            last = self.heartbeat.stat().st_mtime
        except OSError:
            last = 0.0
        return max(last, self.started_wall)

    def _exited(self, now: float, why: str, healthy_s: float | None = None) -> None:
        ran = (now - self.started if self.started is not None else 0.0) if healthy_s is None else healthy_s
        if self.policy.resets_counter(ran):
            self.attempt = 0
        self.attempt += 1
        self.proc = None
        if self.policy.exhausted(self.attempt):
            self.gave_up = True
            self.log(f"[AJANLAR] ajan süreci art arda durdu ({why}); yeniden başlatılmayacak. Atlas çalışmaya devam "
                     "ediyor. Sorun incelendikten sonra başlatıcıyı yeniden açın.")
            return
        delay = self.policy.backoff_for(self.attempt)
        self.next_start = now + delay
        self.log(f"[AJANLAR] ajan süreci durdu ({why}); {delay:g} sn sonra yeniden başlatılacak "
                 f"(deneme {self.attempt}/{self.policy.max_attempts})")

    def stop(self) -> None:
        """Ask, wait AGENT_STOP_GRACE_S, then kill; release what a killed process left behind."""
        proc, self.proc = self.proc, None
        if proc is None:
            return
        if proc.poll() is None:
            try:
                proc.send_signal(STOP_SIGNAL)
            except OSError:
                pass
            try:
                proc.wait(timeout=AGENT_STOP_GRACE_S)
            except subprocess.TimeoutExpired:
                self._kill(proc)
                return
        self._released(proc)

    def _kill(self, proc: Any) -> None:
        try:
            proc.kill()
        except OSError:
            pass
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            return  # still alive: its locks are left alone
        self._released(proc)

    def _released(self, proc: Any) -> None:
        """After the process is gone: close our end of its stdin and drop record locks naming its PID (and an
        empty lock it may have created just before it died, before it could write its PID - audit L7)."""
        if proc.poll() is None:
            return
        stdin = getattr(proc, "stdin", None)
        if stdin is not None:
            try:
                stdin.close()
            except OSError:
                pass
        try:
            from tools.atlas_org_cli import release_locks_of

            removed = release_locks_of(self.records_dir, proc.pid, empty_since=self.started_wall or None)
        except Exception as exc:  # noqa: BLE001 - agent code must never break the launcher's loop
            self.log(f"[AJANLAR] kayıt kilitleri kontrol edilemedi: {type(exc).__name__}")
            return
        if removed:
            self.log(f"[AJANLAR] durdurulan sürecin kayıt kilitleri bırakıldı: {', '.join(removed)}")


def _agent_supervisor(every: float) -> AgentSupervisor:
    from tools import atlas_org_cli as cli
    from tools.agent_cycle import HEARTBEAT_FILE, runner_dir

    try:
        heartbeat: Path | None = runner_dir(create=False) / HEARTBEAT_FILE
    except Exception as exc:  # noqa: BLE001 - the state directory is Atlas's to validate; Atlas still starts
        heartbeat = None
        print(f"[AJANLAR] durum dizini çözülemedi ({type(exc).__name__}); asılı kalma denetimi kapalı", flush=True)
    return AgentSupervisor(agent_command(every), heartbeat, cli.RECORDS_DIR)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--every", type=minutes, default=5.0, help="scheduler tick in minutes (each agent keeps its own clock)")
    args = parser.parse_args(argv)
    # Atlas first (audit M4): nothing from the agents is imported before Atlas is running.
    atlas = subprocess.Popen([sys.executable, str(ROOT / "atlas_supervisor.py")], cwd=str(ROOT))
    agents: AgentSupervisor | None
    try:
        agents = _agent_supervisor(args.every)
        print(f"[AJANLAR] Atlas ile birlikte çalışacak: ayrı ve düşük öncelikli bir süreçte, ilk kontrol "
              f"{FIRST_CYCLE_DELAY_S // 60} dk sonra, sonra her {args.every:g} dk'da sırası gelen ajanlar.", flush=True)
    except Exception as exc:  # noqa: BLE001 - broken agent code: Atlas runs on without agents
        agents = None
        print(f"[AJANLAR] başlatılamadı ({type(exc).__name__}: {exc}); Atlas ajansız çalışmaya devam ediyor", flush=True)
    began = time.monotonic()
    try:
        while atlas.poll() is None:
            if agents is not None and time.monotonic() - began >= FIRST_CYCLE_DELAY_S:
                try:
                    agents.poll()
                except Exception as exc:  # noqa: BLE001 - the launcher keeps watching Atlas whatever the agents do
                    print(f"[AJANLAR] denetim hatası ({type(exc).__name__}: {exc}); ajanlar durduruluyor", flush=True)
                    agents.stop()
                    agents = None
            time.sleep(POLL_S)
        code = atlas.returncode
    except KeyboardInterrupt:  # Ctrl+C reaches the supervisor too: stop the agents, then wait for Atlas's clean stop
        if agents is not None:
            agents.stop()
        code = atlas.wait()
    finally:
        if agents is not None:
            agents.stop()
    return code


if __name__ == "__main__":
    raise SystemExit(main())
