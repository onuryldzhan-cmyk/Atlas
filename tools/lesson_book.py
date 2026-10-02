"""Read-only lesson book from a replay signals CSV (tools.backtest_replay --signals-out).

Groups every BUY/SELL decision by action x market regime x confidence band and states,
per group, how often buying at that moment won after fees within 60 / 240 minutes.
A group with fewer than MIN_SAMPLES decisions is INSUFFICIENT, never a lesson.
Research evidence only: nothing here changes how Atlas trades.

python -m tools.lesson_book replay_30d_signals.csv
python -m tools.lesson_book replay_30d_signals.csv --by symbol
"""
from __future__ import annotations

import argparse
import csv
from collections import defaultdict
from decimal import Decimal

MIN_SAMPLES = 30
BAND = 5  # confidence band width in points


def band(conf: str) -> str:
    c = int(Decimal(conf) // BAND * BAND)
    return f"{c}-{c + BAND}"


def build(rows: list[dict], by: str = "regime") -> list[dict]:
    groups: dict[tuple, list[dict]] = defaultdict(list)
    for r in rows:
        groups[(r["action"], r.get(by) or "UNKNOWN", band(r["confidence"]))].append(r)
    out = []
    for (action, key, conf_band), items in sorted(groups.items()):
        line = {"action": action, by: key, "confidence": conf_band, "n": len(items)}
        for h in ("net_60m", "net_240m"):
            vals = [Decimal(x[h]) for x in items if x.get(h)]
            # BUY wins when buying beat fees; SELL is "right" when buying would have lost.
            wins = sum(1 for v in vals if (v > 0) == (action == "BUY"))
            line[f"{h}_win"] = round(wins / len(vals), 3) if vals else None
            line[f"{h}_avg_pct"] = round(float(sum(vals) / len(vals)) * 100, 3) if vals else None
        line["verdict"] = "MEASURED" if len(items) >= MIN_SAMPLES else "INSUFFICIENT"
        out.append(line)
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("path")
    ap.add_argument("--by", default="regime", choices=["regime", "symbol", "bucket"])
    args = ap.parse_args(argv)
    with open(args.path, encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    print(f"{len(rows)} decisions; win = BUY beat fees (SELL: buying would have lost); "
          f"groups under {MIN_SAMPLES} are INSUFFICIENT")
    print(f"{'action':6} {args.by:12} {'conf':7} {'n':>5}  {'win60':>6} {'avg60%':>7}  {'win240':>6} {'avg240%':>8}  verdict")
    for g in build(rows, args.by):
        f = lambda v: "-" if v is None else v  # noqa: E731
        print(f"{g['action']:6} {g[args.by]:12} {g['confidence']:7} {g['n']:>5}  {f(g['net_60m_win']):>6} "
              f"{f(g['net_60m_avg_pct']):>7}  {f(g['net_240m_win']):>6} {f(g['net_240m_avg_pct']):>8}  {g['verdict']}")
    print("Research evidence only. A MEASURED group is a candidate lesson, not a rule; it still needs a "
          "walk-forward check and the owner's approval before it may influence trading.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
