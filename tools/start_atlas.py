"""Start Atlas and its agents together with one command.

  python -m tools.start_atlas                 # Atlas (supervised) + agent cycle every 60 minutes
  python -m tools.start_atlas --every 30

Atlas runs exactly as with `python atlas_supervisor.py` (same process, same
Ctrl+C behaviour). While it is alive, this launcher runs the rule-based
agent cycle (tools.agent_cycle) in the background: the first cycle two
minutes after start, then every --every minutes. The agents never touch the
runtime, execution or money; when Atlas stops, the agents stop too.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
import threading
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FIRST_CYCLE_DELAY_S = 120


def agent_loop(stop: threading.Event, every_minutes: float, run_cycle=None, first_delay: float = FIRST_CYCLE_DELAY_S) -> None:
    if run_cycle is None:
        from tools.agent_cycle import run_cycle
    if stop.wait(first_delay):
        return
    while not stop.is_set():
        try:
            out = run_cycle()
            ok = sum(1 for r in out["results"] if r["verdict"] == "OK")
            print(f"[AJANLAR] {out['record_id']}: {ok}/{len(out['results'])} ajan sorunsuz", flush=True)
        except Exception as exc:  # the agents must never take Atlas down
            print(f"[AJANLAR] döngü hatası: {type(exc).__name__}: {exc}", flush=True)
        if stop.wait(every_minutes * 60):
            return


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--every", type=float, default=60.0, help="agent cycle interval in minutes")
    args = parser.parse_args(argv)
    stop = threading.Event()
    agents = threading.Thread(target=agent_loop, args=(stop, args.every), daemon=True, name="atlas-agents")
    atlas = subprocess.Popen([sys.executable, str(ROOT / "atlas_supervisor.py")], cwd=str(ROOT))
    agents.start()
    print(f"[AJANLAR] Atlas ile birlikte çalışacak: ilk döngü {FIRST_CYCLE_DELAY_S // 60} dk sonra, sonra her {args.every:g} dk.", flush=True)
    try:
        code = atlas.wait()
    except KeyboardInterrupt:  # Ctrl+C reaches the supervisor too; wait for its clean shutdown
        code = atlas.wait()
    stop.set()
    return code


if __name__ == "__main__":
    raise SystemExit(main())
