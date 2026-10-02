"""Read-only: list governance tasks by status, with the step block reasons.

python -m tools.task_status            (counts + every BLOCKED task)
python -m tools.task_status --all      (every task)
"""
from __future__ import annotations

import argparse
from collections import Counter
from pathlib import Path

from atlas_org import tasks as T
from tools import atlas_org_cli as cli

LOG = Path("governance/records") / cli.TASKS_LOG


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--all", action="store_true")
    args = ap.parse_args(argv)
    if not LOG.exists():
        print(f"görev kaydı yok: {LOG}")
        return 0
    state = T.replay(cli.read_log(LOG))
    print(dict(Counter(str(t.get("status")) for t in state.values())))
    for tid, t in sorted(state.items()):
        if args.all or t.get("status") == "BLOCKED":
            reasons = "; ".join(f"adım {st.get('index')}: {st.get('block_reason')}" for st in t.get("steps") or []
                                if st.get("block_reason")) or "-"
            print(f"{tid} | {t.get('status')} | {str(t.get('request'))[:70]} | {reasons[:200]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
