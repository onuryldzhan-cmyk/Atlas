"""What Atlas learns from its own trades: performance attribution over the real archive.

  python -m tools.performance_report
  python -m tools.performance_report --record   # also write it to Atlas Memory

Reads the durable closed-position archive (the financial-truth authority;
read-only) and groups every closed PAPER trade by coin, holding time and
UTC hour. For each group: trades, win rate after estimated fees with a
Wilson 95 % interval, estimated net P/L and the share of it eaten by fees.

Evidence rules (CLAUDE.md rule 3 - never raise confidence without evidence):
* a group needs at least MIN_SAMPLE trades before anything is concluded;
* "WEAK" only when estimated net < 0 AND the whole win-rate interval is
  below 50 %; "STRONG" only when net > 0 AND the whole interval is above 50 %;
  everything else is "INCONCLUSIVE".
The report changes nothing in the runtime. A lesson becomes behaviour only
through a proposal the owner approves (e.g. a minimum holding time, which
tools/backtest_replay.py --min-hold can test first).
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from decimal import Decimal
from pathlib import Path
from typing import Any

from tools.exp001_report import estimated_fees, holding_hours, load_closed, wilson_interval

MIN_SAMPLE = 10
HOLD_BUCKETS = ((0.25, "<15 dk"), (1.0, "15-60 dk"), (4.0, "1-4 saat"), (24.0, "4-24 saat"), (float("inf"), ">1 gün"))


def _hold_bucket(record: dict) -> str:
    hours = holding_hours(record)
    if hours is None:
        return "bilinmiyor"
    return next(label for limit, label in HOLD_BUCKETS if hours < limit)


def _hour_block(record: dict) -> str:
    stamp = str(record.get("opened_at", ""))
    try:
        hour = int(stamp[11:13])
    except ValueError:
        return "bilinmiyor"
    start = hour // 4 * 4
    return f"{start:02d}-{start + 4:02d} UTC"


def _group_stats(records: list[dict]) -> dict[str, Any]:
    n = len(records)
    nets = [Decimal(str(r["gross_pnl"])) - estimated_fees(r) for r in records]
    fees = sum((estimated_fees(r) for r in records), Decimal("0"))
    gross = sum((Decimal(str(r["gross_pnl"])) for r in records), Decimal("0"))
    wins = sum(1 for x in nets if x > 0)
    low, high = wilson_interval(wins, n) if n else (0.0, 0.0)
    net = sum(nets, Decimal("0"))
    if n < MIN_SAMPLE:
        verdict = "INCONCLUSIVE (sample < %d)" % MIN_SAMPLE
    elif net < 0 and high < 0.5:
        verdict = "WEAK"
    elif net > 0 and low > 0.5:
        verdict = "STRONG"
    else:
        verdict = "INCONCLUSIVE"
    return {"trades": n, "wins_after_fees": wins, "win_rate_after_fees": round(wins / n, 3) if n else None,
            "win_rate_ci95": [round(low, 3), round(high, 3)], "est_net_pnl": str(net.quantize(Decimal("0.01"))),
            "gross_pnl": str(gross.quantize(Decimal("0.01"))), "est_fees": str(fees.quantize(Decimal("0.01"))),
            "verdict": verdict}


def trader_book(records: list[dict]) -> dict[str, Any]:
    """Per coin, the metrics the runtime memory uses (BRAIN-MEM-001): expectancy after fees, profit factor, streak."""

    from ai.core.intelligence.trade_evidence import symbol_evidence

    return {s: symbol_evidence(records, s) for s in sorted({r.get("symbol", "?") for r in records})}


def _false_discovery_filter(tables: dict[str, dict[str, dict[str, Any]]]) -> None:
    """2026-10-02: ~30 groups (coins x holding times x hours) are tested at once, so a per-group 95 % interval
    alone calls some of them WEAK or STRONG by luck. Every group with a full sample gets a binomial p-value on
    its after-fee win count and all of them one Benjamini-Hochberg correction; a WEAK/STRONG verdict whose
    q exceeds FDR_Q becomes INCONCLUSIVE. Only ever removes claims (never adds one)."""
    from tools.fdr import FDR_Q, bh_qvalues, binom_two_sided_p

    tested = [stats for table in tables.values() for stats in table.values() if stats["trades"] >= MIN_SAMPLE]
    for stats, q in zip(tested, bh_qvalues([binom_two_sided_p(s["wins_after_fees"], s["trades"]) for s in tested])):
        stats["q_fdr"] = round(q, 4)
        if stats["verdict"] in ("WEAK", "STRONG") and q > FDR_Q:
            stats["verdict"] = f"INCONCLUSIVE (FDR q={q:.2f})"


def analyse(records: list[dict]) -> dict[str, Any]:
    groups: dict[str, dict[str, list[dict]]] = {"coin": defaultdict(list), "holding_time": defaultdict(list),
                                                 "hour_utc": defaultdict(list)}
    for r in records:
        groups["coin"][r.get("symbol", "?")].append(r)
        groups["holding_time"][_hold_bucket(r)].append(r)
        groups["hour_utc"][_hour_block(r)].append(r)
    report = {"total": _group_stats(records) if records else {"trades": 0},
              "by": {name: {key: _group_stats(rs) for key, rs in sorted(g.items())} for name, g in groups.items()}}
    _false_discovery_filter(report["by"])
    lessons = []
    for name, table in report["by"].items():
        for key, stats in table.items():
            if stats["verdict"] in ("WEAK", "STRONG"):
                lessons.append(f"{name}={key}: {stats['verdict']} ({stats['trades']} işlem, net {stats['est_net_pnl']}, "
                               f"kazanma %{stats['win_rate_after_fees'] * 100:.0f} [{stats['win_rate_ci95'][0]:.0%}-{stats['win_rate_ci95'][1]:.0%}])")
    total = report["total"]
    if total.get("trades") and Decimal(total["gross_pnl"]) != 0:
        share = Decimal(total["est_fees"]) / abs(Decimal(total["gross_pnl"]))
        if share > Decimal("0.5"):
            lessons.append(f"ücretler brüt kâr/zararın %{share * 100:.0f}'i: işlem sıklığı (al-sat dönüşü) maliyeti belirliyor")
    report["trader_book"] = trader_book(records)
    report["lessons"] = lessons or ["henüz güvenilir bir ders yok: örnek yetersiz ya da sonuçlar kararsız"]
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--archive", default=None, help="closed-position archive (default: the state directory's)")
    parser.add_argument("--record", action="store_true", help="also write the result to Atlas Memory (RESEARCH authority)")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    if args.archive:
        path = Path(args.archive)
    else:
        from core.application import EXECUTION_CLOSED_POSITIONS_FILE, resolve_state_directory

        path = resolve_state_directory() / EXECUTION_CLOSED_POSITIONS_FILE
    if not path.is_file():
        print(f"no closed-position archive at {path}", file=sys.stderr)
        return 1
    report = analyse(load_closed(path))
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print(f"ATLAS PERFORMANS RAPORU — {report['total'].get('trades', 0)} kapanan işlem (PAPER, tahmini ücret düşülmüş)")
        for name, table in report["by"].items():
            print(f"\n[{name}]")
            for key, s in table.items():
                print(f"  {key:<14} {s['trades']:>4} işlem  net {s['est_net_pnl']:>10}  ücret {s['est_fees']:>8}  "
                      f"kazanma {s['win_rate_after_fees'] if s['win_rate_after_fees'] is not None else '-'}  {s['verdict']}")
        print("\n[trader defteri: işlem başı net beklenti, kâr faktörü, en uzun kayıp serisi, hafıza etkisi]")
        for sym, b in report["trader_book"].items():
            if not b.get("available"):
                print(f"  {sym:<14} okunamadı ({b.get('reason')})")
                continue
            pf = "-" if b["profit_factor"] is None else f"{b['profit_factor']:.2f}"
            effect = "AL güveni -5" if b["effect"] < 0 else f"yok (en az {b['min_trades']} işlem ve kanıtlı zarar gerekir)"
            print(f"  {sym:<14} {b['trades']:>3} işlem  beklenti {b['net_expectancy']:>8.2f}  kâr faktörü {pf:>5}  "
                  f"kayıp serisi {b['longest_losing_streak']}  etki: {effect}")
        print("\nDERSLER (kanıt eşiği: en az %d işlem, güven aralığı 50%%'nin tamamen altında/üstünde):" % MIN_SAMPLE)
        for lesson in report["lessons"]:
            print("  - " + lesson)
        print("\nRapor hiçbir şeyi değiştirmez; bir ders ancak sahibin onayladığı bir öneriyle davranışa dönüşür.")
    if args.record:
        from tools import atlas_org_cli as cli

        existing = {r["record_id"] for r in cli.read_log(cli.RECORDS_DIR / cli.MEMORY_LOG)}
        cli.add_memory_record(cli.RECORDS_DIR, {
            "record_id": f"PR-{len(existing) + 1:04d}", "type": "EXPERIMENTS", "authority": "RESEARCH",
            "title": f"Performans raporu: {report['total'].get('trades', 0)} işlem",
            "body": json.dumps(report, ensure_ascii=False)[:20000],
            "author": "quant_research", "source": f"tools/performance_report.py over {path.name}"})
        print("Atlas Hafızası'na kaydedildi (RESEARCH, yetkili karar değil).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
