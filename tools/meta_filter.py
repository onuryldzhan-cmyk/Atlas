"""Read-only meta-filter (owner option B, 'fewer but better trades'), no new dependencies.

Meta-labeling in its simplest honest form: the primary model (Atlas) proposes BUY
signals; a secondary filter decides which of them to take. The filter here is a
lookup learnt on the OLDER part of the experience (train) - take a BUY only in a
regime x confidence-band group that was MEASURED and profitable after fees at the
chosen horizon - and it is judged only on the NEWER part (test), which it never saw.

python -m tools.meta_filter <signals.csv> [--horizon 1440] [--fee-bps 10] [--train 0.7]

Research evidence only: a filter that wins on the test part is a candidate for an
owner-approved proposal, never a rule by itself.
"""
from __future__ import annotations

import argparse
import csv
from decimal import Decimal

from tools import lesson_book as lb


def evaluate(rows: list[dict], *, horizon: int = 1440, fee_bps: int | None = None, slippage_bps: int = 5,
             train: float = 0.7) -> dict:
    rows = sorted((r for r in rows if r["action"] == "BUY"), key=lambda r: r["time"])
    cut = int(len(rows) * train)
    train_rows, test_rows = rows[:cut], rows[cut:]
    key = f"net_{horizon}m"
    groups = lb.build(train_rows, "regime", slippage_bps, fee_bps)
    keep = {(g["regime"], g["confidence"]) for g in groups
            if g["verdict"] == "MEASURED" and (g.get(f"{key}_avg_pct") or 0) > 0}
    slip = Decimal(slippage_bps) / Decimal(10000)
    fee = Decimal(fee_bps) / Decimal(10000) if fee_bps is not None else None

    def stats(items):
        vals = [v for v in (lb._value(r, horizon, "BUY", slip, fee) for r in items) if v is not None]
        if not vals:
            return {"n": 0, "win": None, "avg_pct": None}
        return {"n": len(vals), "win": round(sum(1 for v in vals if v > 0) / len(vals), 3),
                "avg_pct": round(float(sum(vals) / len(vals)) * 100, 3)}

    taken = [r for r in test_rows if (r.get("regime") or "UNKNOWN", lb.band(r["confidence"])) in keep]
    return {"train_buys": len(train_rows), "test_buys": len(test_rows), "kept_groups": sorted(keep),
            "test_all": stats(test_rows), "test_filtered": stats(taken)}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("path")
    ap.add_argument("--horizon", type=int, default=1440, choices=lb.HORIZONS)
    ap.add_argument("--fee-bps", type=int, default=None)
    ap.add_argument("--slippage-bps", type=int, default=5)
    ap.add_argument("--train", type=float, default=0.7)
    args = ap.parse_args(argv)
    with open(args.path, encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    if not any(r.get(f"net_{args.horizon}m") for r in rows):
        print(f"no {args.horizon}m outcomes in this file (older replays only have 60/240); try --horizon 240")
        return 0
    out = evaluate(rows, horizon=args.horizon, fee_bps=args.fee_bps, slippage_bps=args.slippage_bps, train=args.train)
    print(f"BUY signals: train {out['train_buys']} (older) / test {out['test_buys']} (newer, unseen)")
    print(f"filter learnt on train keeps groups: {out['kept_groups'] or 'none (no profitable MEASURED group)'}")
    a, b = out["test_all"], out["test_filtered"]
    print(f"test, take every BUY : n={a['n']} win={a['win']} avg={a['avg_pct']}%")
    print(f"test, filtered BUYs  : n={b['n']} win={b['win']} avg={b['avg_pct']}%")
    print("Research evidence only. Overlapping 15-minute signals: the effective sample is smaller than n.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
