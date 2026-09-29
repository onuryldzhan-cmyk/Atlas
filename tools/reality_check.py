"""Reality check of Atlas's own trades: is its confidence calibrated, and how bad can it get?

  python -m tools.reality_check
  python -m tools.reality_check --json

Read-only over the closed-position archive and the audit log.

* Confidence calibration: each closed trade is joined to the RISK_APPROVED
  confidence it was opened with; per confidence band, the trades, win rate
  after fees and net expectancy. "Confidence" is Atlas's score, not a
  probability of profit; this is how we find out what it is worth.
* Monte Carlo stress: the net P/L sequence is resampled (bootstrap, fixed
  seed) and replayed with worse execution (extra cost per trade). It
  reports the median, 95th and 99th percentile maximum drawdown and the
  chance that the next N trades lose money.
* Cost check: the gross edge per trade against the estimated round-trip cost.

Nothing here changes the runtime. Fewer than MIN_SAMPLE trades is
reported as insufficient, never as a result.
"""

from __future__ import annotations

import argparse
import json
import random
import sys
from decimal import Decimal
from pathlib import Path
from typing import Any

from ai.core.intelligence.trade_evidence import net_pnl

MIN_SAMPLE = 10
BANDS = ((0, 50), (50, 60), (60, 70), (70, 80), (80, 90), (90, 101))  # owner MEGA 1 §12 buckets
EXTRA_COST_BPS = (0, 10, 20)  # worse execution per trade, in basis points of the entry notional


def calibration(records: list[dict], approvals: dict[str, list[dict]]) -> list[dict[str, Any]]:
    from tools.paper_position_report import entry_approval

    rows: dict[tuple[int, int], list[Decimal]] = {b: [] for b in BANDS}
    unattributed = 0
    for r in records:
        appr = entry_approval(approvals.get(r.get("symbol", ""), []), r.get("opened_at"))
        conf = appr.get("confidence") if appr else None
        if not isinstance(conf, (int, float)):
            unattributed += 1
            continue
        band = next(b for b in BANDS if b[0] <= conf < b[1])
        rows[band].append(net_pnl(r))
    out = []
    for (lo, hi), nets in rows.items():
        n = len(nets)
        out.append({"band": f"{lo}-{min(hi, 100)}", "trades": n,
                    "win_rate_after_fees": None if not n else round(sum(1 for x in nets if x > 0) / n, 3),
                    "net_expectancy": None if not n else round(float(sum(nets) / n), 4),
                    "win_rate_95ci": None if not n else wilson(sum(1 for x in nets if x > 0), n),
                    "verdict": "INSUFFICIENT" if n < MIN_SAMPLE else "MEASURED"})
    out.append({"band": "confidence unknown", "trades": unattributed})
    return out


def wilson(wins: int, n: int, z: float = 1.96) -> list[float]:
    """95 % Wilson interval of the win rate: keeps the uncertainty of a small bucket visible."""
    p = wins / n
    denom = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / denom
    half = z * ((p * (1 - p) / n + z * z / (4 * n * n)) ** 0.5) / denom
    return [round(max(0.0, centre - half), 3), round(min(1.0, centre + half), 3)]


def max_drawdown(pnls: list[float]) -> float:
    peak = equity = worst = 0.0
    for x in pnls:
        equity += x
        peak = max(peak, equity)
        worst = min(worst, equity - peak)
    return worst


def monte_carlo(records: list[dict], runs: int = 2000, horizon: int = 50, seed: int = 7) -> list[dict[str, Any]]:
    base = [(float(net_pnl(r)), float(Decimal(str(r["cost_quote"])))) for r in records]
    if not base:
        return []
    rng = random.Random(seed)
    out = []
    for bps in EXTRA_COST_BPS:
        dds, finals = [], []
        for _ in range(runs):
            path = [p - notional * bps / 10000 for p, notional in (rng.choice(base) for _ in range(horizon))]
            dds.append(max_drawdown(path))
            finals.append(sum(path))
        dds.sort()
        out.append({"extra_cost_bps": bps, "horizon_trades": horizon,
                    "median_max_drawdown": round(dds[len(dds) // 2], 2),
                    "p95_max_drawdown": round(dds[int(len(dds) * 0.05)], 2),
                    "p99_max_drawdown": round(dds[int(len(dds) * 0.01)], 2),
                    "chance_of_loss": round(sum(1 for f in finals if f < 0) / runs, 3)})
    return out


def cost_check(records: list[dict]) -> dict[str, Any]:
    if not records:
        return {"trades": 0}
    gross = [float(Decimal(str(r["gross_pnl"]))) for r in records]
    net = [float(net_pnl(r)) for r in records]
    n = len(records)
    return {"trades": n, "avg_gross_per_trade": round(sum(gross) / n, 4),
            "avg_cost_per_trade": round((sum(gross) - sum(net)) / n, 4),
            "avg_net_per_trade": round(sum(net) / n, 4),
            "edge_covers_costs": sum(net) > 0}


def var_es(records: list[dict], levels: tuple[float, ...] = (0.95, 0.99)) -> dict[str, Any]:
    """Historical per-trade VaR and Expected Shortfall of net P/L (loss shown as a positive number).

    Method: empirical quantile of Atlas's own closed-trade net P/L, no
    distribution assumed. With fewer than MIN_SAMPLE trades it is reported
    INSUFFICIENT; the tail beyond the worst observed trade is UNKNOWN, so the
    99 % figure from a small sample understates tail risk (stated, not hidden).
    """
    nets = sorted(float(net_pnl(r)) for r in records)
    n = len(nets)
    out: dict[str, Any] = {"method": "historical, per trade, net of estimated fees", "trades": n,
                           "verdict": "MEASURED" if n >= MIN_SAMPLE else "INSUFFICIENT",
                           "worst_observed": round(-nets[0], 4) if n else None,
                           "tail_note": "losses worse than the worst observed trade are not represented"}
    for lv in levels:
        if not n:
            out[f"var_{int(lv * 100)}"] = out[f"es_{int(lv * 100)}"] = None
            continue
        k = max(1, int((1 - lv) * n))
        tail = nets[:k]
        out[f"var_{int(lv * 100)}"] = round(-tail[-1], 4)
        out[f"es_{int(lv * 100)}"] = round(-sum(tail) / len(tail), 4)
    return out


def run(records: list[dict], approvals: dict[str, list[dict]]) -> dict[str, Any]:
    n = len(records)
    return {"trades": n, "sample_ok": n >= MIN_SAMPLE, "calibration": calibration(records, approvals),
            "monte_carlo": monte_carlo(records), "costs": cost_check(records), "var_es": var_es(records),
            "note": "PAPER fills; fees estimated at 0.1%/side; resampling assumes future trades look like past ones"}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    from core.application import EXECUTION_AUDIT_EVENT_FILE, EXECUTION_CLOSED_POSITIONS_FILE, resolve_state_directory
    from tools.exp001_report import load_closed
    from tools.paper_position_report import approvals_by_symbol

    root = resolve_state_directory()
    out = run(load_closed(root / EXECUTION_CLOSED_POSITIONS_FILE), approvals_by_symbol(root / EXECUTION_AUDIT_EVENT_FILE))
    if args.json:
        print(json.dumps(out, ensure_ascii=False, indent=2))
        return 0
    print(f"ATLAS GERÇEKLİK KONTROLÜ — {out['trades']} kapanan işlem" + ("" if out["sample_ok"] else f" (örnek < {MIN_SAMPLE}: sonuç değil, gözlem)"))
    print("\n[güven kalibrasyonu: Atlas'ın güveni gerçekte ne getirdi?]")
    for row in out["calibration"]:
        print(f"  güven {row['band']:<18} {row['trades']:>3} işlem  " + (
            f"kazanma {row['win_rate_after_fees']} (%95 aralık {row['win_rate_95ci']})  beklenti {row['net_expectancy']}  {row['verdict']}" if row.get("win_rate_after_fees") is not None else ""))
    print("\n[Monte Carlo: sonraki 50 işlemde en kötü durumlar, daha kötü dolum senaryolarıyla]")
    for row in out["monte_carlo"]:
        print(f"  +{row['extra_cost_bps']:>2} bp  medyan düşüş {row['median_max_drawdown']:>8}  %95 {row['p95_max_drawdown']:>8}  "
              f"%99 {row['p99_max_drawdown']:>8}  zarar ihtimali {row['chance_of_loss']:.0%}")
    c = out["costs"]
    if c.get("trades"):
        print(f"\n[maliyet] işlem başı brüt {c['avg_gross_per_trade']}  maliyet {c['avg_cost_per_trade']}  net {c['avg_net_per_trade']}  "
              f"-> {'kenar maliyeti karşılıyor' if c['edge_covers_costs'] else 'KENAR MALİYETİ KARŞILAMIYOR'}")
    v = out["var_es"]
    if v["trades"]:
        print(f"\n[VaR / ES, {v['method']}] %95 VaR {v['var_95']}  ES {v['es_95']}  |  %99 VaR {v['var_99']}  ES {v['es_99']}  "
              f"| en kötü işlem {v['worst_observed']}  ({v['verdict']}; {v['tail_note']})")
    print("\n" + out["note"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
