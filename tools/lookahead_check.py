"""Look-ahead check for the replay (core proposal #6; idea from freqtrade lookahead-analysis, no code copied).

  python -m tools.lookahead_check --dataset ds.json [--cut 0.7]

Runs the same replay twice: on the data truncated at a cut point, and on the full data. Every
trade that CLOSED before the cut must be identical in both runs. If extra future candles change
a past trade, the strategy is reading data it could not have had at decision time (look-ahead).
Research only: nothing in the runtime changes.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from tools import backtest_replay as bt


def _key(t: Any) -> tuple:
    return (t.symbol, t.entry_time, str(t.entry_price), str(t.quantity), t.exit_time, str(t.exit_price), t.exit_reason)


def check(data: dict[str, list[list]], cut: float = 0.7, **replay_kw) -> dict[str, Any]:
    if not 0.2 <= cut < 1:
        raise ValueError("cut must be in [0.2, 1)")
    length = min(len(rows) for rows in data.values())
    n = int(length * cut)
    cut_ms = min(int(rows[n - 1][0]) for rows in data.values())
    short = bt.replay({s: rows[:n] for s, rows in data.items()}, **replay_kw)
    full = bt.replay(data, **replay_kw)

    def closed_before(result):
        return sorted(_key(t) for t in result.trades if t.exit_time and _ms(t.exit_time) <= cut_ms)

    a, b = closed_before(short), closed_before(full)
    diff = sorted(set(a) ^ set(b))
    return {"cut_index": n, "compared_trades": len(a), "mismatches": diff[:20],
            "verdict": "NO_LOOKAHEAD_DETECTED" if not diff else "LOOKAHEAD_SUSPECTED",
            "note": "only trades closed before the cut are compared; zero compared trades proves nothing"}


def _ms(stamp: str) -> int:
    from datetime import datetime
    try:
        return int(datetime.fromisoformat(str(stamp).replace("Z", "+00:00")).timestamp() * 1000)
    except ValueError:
        return int(stamp)


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--dataset", required=True)
    p.add_argument("--cut", type=float, default=0.7)
    p.add_argument("--step", type=int, default=15)
    args = p.parse_args(argv)
    try:
        raw = json.loads(Path(args.dataset).read_text(encoding="utf-8"))
        data = raw.get("candles", raw) if isinstance(raw, dict) else raw
        out = check(data, args.cut, step=args.step)
    except (OSError, ValueError) as exc:
        print(f"HATA: {exc}")
        return 2
    print(json.dumps(out, indent=2, ensure_ascii=False))
    return 0 if out["verdict"] == "NO_LOOKAHEAD_DETECTED" else 1


if __name__ == "__main__":
    raise SystemExit(main())
