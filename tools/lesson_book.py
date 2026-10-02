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


FEE = Decimal("0.001")  # PAPER_FEE_RATE_PER_SIDE
HORIZONS = (5, 10, 60, 240, 1440)
BARRIER_MINUTES = (5, 10, 30)  # tools.backtest_replay.BARRIERS: take-profit / stop-loss / time limit


def _gross(net: Decimal, slip: Decimal) -> Decimal:
    """Undo fees and slippage: the raw price move. Used for SELL, which pays no round trip."""
    return (1 + net) * (1 + slip) * (1 + FEE) / ((1 - slip) * (1 - FEE)) - 1


def _value(row: dict, h: int, action: str, slip: Decimal, fee: Decimal | None) -> Decimal | None:
    """BUY: after-fee result; SELL: raw move. With `fee` and a raw column, BUY is re-priced at that fee."""
    raw = row.get(f"ret_{h}m")
    if action == "SELL":
        if raw:
            return Decimal(raw)
        return _gross(Decimal(row[f"net_{h}m"]), slip) if row.get(f"net_{h}m") else None
    if fee is not None and raw:
        return (1 + Decimal(raw)) * (1 - slip) * (1 - fee) / ((1 + slip) * (1 + fee)) - 1
    return Decimal(row[f"net_{h}m"]) if row.get(f"net_{h}m") else None


def _lbl(h: int) -> str:
    return "1d" if h == 1440 else f"{h}m"


def build(rows: list[dict], by: str = "regime", slippage_bps: int = 5, fee_bps: int | None = None) -> list[dict]:
    slip = Decimal(slippage_bps) / Decimal(10000)
    fee = Decimal(fee_bps) / Decimal(10000) if fee_bps is not None else None
    groups: dict[tuple, list[dict]] = defaultdict(list)
    for r in rows:
        groups[(r["action"], r.get(by) or "UNKNOWN", band(r["confidence"]))].append(r)
    out = []
    for (action, key, conf_band), items in sorted(groups.items()):
        line = {"action": action, by: key, "confidence": conf_band, "n": len(items)}
        for hm in HORIZONS:
            h = f"net_{hm}m"
            # BUY wins when buying beat fees. SELL is right when the PRICE fell (owner run 2026-10-02:
            # judging SELL by "buying lost after fees" counted fees as SELL skill).
            vals = [v for v in (_value(x, hm, action, slip, fee) for x in items) if v is not None]
            wins = sum(1 for v in vals if (v > 0) == (action == "BUY"))
            line[f"{h}_win"] = round(wins / len(vals), 3) if vals else None
            line[f"{h}_avg_pct"] = round(float(sum(vals) / len(vals)) * 100, 3) if vals else None
        if action == "BUY":  # barriers describe a long position: share that hit take-profit, avg after-fee result
            for m in BARRIER_MINUTES:
                hits = [x.get(f"tb_{m}m") for x in items if x.get(f"tb_{m}m")]
                nets = [Decimal(x[f"tbnet_{m}m"]) for x in items if x.get(f"tbnet_{m}m")]
                line[f"tb{m}_tp"] = round(hits.count("TP") / len(hits), 3) if hits else None
                line[f"tb{m}_avg_pct"] = round(float(sum(nets) / len(nets)) * 100, 3) if nets else None
        line["verdict"] = "MEASURED" if len(items) >= MIN_SAMPLES else "INSUFFICIENT"
        out.append(line)
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("path")
    ap.add_argument("--fee-bps", type=int, default=None,
                    help="re-price BUY at this fee per side (10 = 0.1%%; 7 = 0.075%% with BNB); needs ret_* columns")
    ap.add_argument("--slippage-bps", type=int, default=5, help="the slippage the replay used")
    ap.add_argument("--view", default="all", choices=["all", "long", "short"],
                    help="long = 1h/4h/1d table; short = 5/10-min and take-profit/stop-loss table")
    ap.add_argument("--by", default="regime", choices=["regime", "symbol", "bucket"])
    args = ap.parse_args(argv)
    with open(args.path, encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    print(f"{len(rows)} decisions; win = BUY beat fees+slippage; SELL win = price fell (SELL avg = raw move); "
          f"groups under {MIN_SAMPLES} are INSUFFICIENT")
    f = lambda v: "-" if v is None else v  # noqa: E731
    groups = build(rows, args.by, args.slippage_bps, args.fee_bps)
    if args.view in ("all", "long"):
        cols = [h for h in HORIZONS if h >= 60]
    else:
        cols = [h for h in HORIZONS if h < 60]
    head = "  ".join(f"{'win' + _lbl(h):>7} {'avg' + _lbl(h) + '%':>9}" for h in cols)
    print(f"{'action':6} {args.by:12} {'conf':7} {'n':>5}  {head}  verdict")
    for g in groups:
        body = "  ".join(f"{f(g[f'net_{h}m_win']):>7} {f(g[f'net_{h}m_avg_pct']):>9}" for h in cols)
        print(f"{g['action']:6} {g[args.by]:12} {g['confidence']:7} {g['n']:>5}  {body}  {g['verdict']}")
    if args.view in ("all", "short"):
        if args.view == "all":
            print("\nSHORT TRADES (5/10 min) and TAKE-PROFIT / STOP-LOSS barriers, BUY only")
            print(f"{'action':6} {args.by:12} {'conf':7} {'n':>5}  " + "  ".join(
                f"{'win' + _lbl(h):>7} {'avg' + _lbl(h) + '%':>9}" for h in HORIZONS if h < 60))
            for g in groups:
                if g["action"] == "BUY":
                    print(f"{g['action']:6} {g[args.by]:12} {g['confidence']:7} {g['n']:>5}  " + "  ".join(
                        f"{f(g[f'net_{h}m_win']):>7} {f(g[f'net_{h}m_avg_pct']):>9}" for h in HORIZONS if h < 60))
        print("barriers (take-profit/stop-loss/time): " + ", ".join(
            f"{m}m=+{tp}%/-{sl}%" for m, tp, sl in ((5, 0.4, 0.3), (10, 0.6, 0.4), (30, 1.0, 0.6))))
        print(f"{'regime/key':12} {'conf':7} {'n':>5}  " + "  ".join(f"{'TP' + str(m) + 'm':>7} {'avg' + str(m) + 'm%':>9}"
                                                              for m in BARRIER_MINUTES))
        for g in groups:
            if g["action"] == "BUY":
                print(f"{g[args.by]:12} {g['confidence']:7} {g['n']:>5}  " + "  ".join(
                    f"{f(g.get(f'tb{m}_tp')):>7} {f(g.get(f'tb{m}_avg_pct')):>9}" for m in BARRIER_MINUTES))
    print("Research evidence only. A MEASURED group is a candidate lesson, not a rule; it still needs a "
          "walk-forward check and the owner's approval before it may influence trading.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
