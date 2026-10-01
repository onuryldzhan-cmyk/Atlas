"""Compare every strategy variant on the same real data, window by window.

  python -m tools.strategy_compare --days 21 --windows 3
  python -m tools.strategy_compare --days 21 --windows 3 --symbols-file config/universe_selection.json

Downloads the Binance 1-minute history ONCE and replays the real Atlas
decision chain (tools/backtest_replay.replay) for each variant on each
consecutive window (walk-forward style: a variant has to hold up in every
window, not just on average - docs/research/TRADING_STRATEGY_COMPARISON_2026-09-29.md
recommendation 6). All variants use realistic fills (slippage + next-candle
fill) except the explicit "today" baseline.

Verdict per variant: BETTER only if its net P/L beats the realistic
baseline in EVERY window and its worst drawdown is not larger; otherwise
NOT PROVEN. Research evidence only; nothing in the runtime changes.
"""

from __future__ import annotations

import argparse
import json
import os
import logging
import sys
from decimal import Decimal
from pathlib import Path
from typing import Any

from tools import backtest_replay as bt

REALISTIC = {"slippage_bps": 5, "next_open_fill": True}
VARIANTS: dict[str, dict[str, Any]] = {
    "bugün (iyimser dolum)": {},
    "gerçekçi dolum (referans)": dict(REALISTIC),
    "min tutma 60 dk": {**REALISTIC, "min_hold_min": 60},
    "satış onayı 2": {**REALISTIC, "sell_confirm": 2},
    "1s trend filtresi EMA20": {**REALISTIC, "trend_ema_hours": 20},
    "ATR stop 2x": {**REALISTIC, "atr_stop": 2},
    "ATR stop 2x + %1 risk": {**REALISTIC, "atr_stop": 2, "risk_per_trade": 0.01},
    "aşamalı + paylar": {**REALISTIC, "staged": True, "sleeves": True},
    "maliyet kapısı 3x": {**REALISTIC, "cost_gate": 3},
    "rejim filtresi (sadece TREND_UP)": {**REALISTIC, "regime_filter": True},
    "aşamalı + paylar + maliyet kapısı": {**REALISTIC, "staged": True, "sleeves": True, "cost_gate": 3},
    "rejim filtresi + aşamalı + paylar": {**REALISTIC, "regime_filter": True, "staged": True, "sleeves": True},
}
REFERENCE = "gerçekçi dolum (referans)"


def dataset_manifest(data: dict[str, list[list]]) -> dict[str, Any]:
    """Content hash + shape of the exact candles replayed (task 9 reproducibility)."""
    import hashlib

    per = {}
    h = hashlib.sha256()
    for sym in sorted(data):
        rows = data[sym]
        blob = json.dumps(rows, separators=(",", ":"), default=str).encode()
        h.update(sym.encode() + blob)
        per[sym] = {"rows": len(rows), "first_open": rows[0][0] if rows else None,
                    "last_open": rows[-1][0] if rows else None, "sha256": hashlib.sha256(blob).hexdigest()[:16]}
    return {"dataset_sha256": h.hexdigest(), "symbols": per}


def split(data: dict[str, list[list]], windows: int) -> list[dict[str, list[list]]]:
    length = min(len(rows) for rows in data.values())
    size = length // windows
    if size <= bt.WINDOW + 60:
        raise ValueError(f"window too short: {size} candles; use more --days or fewer --windows")
    return [{s: rows[i * size:(i + 1) * size] for s, rows in data.items()} for i in range(windows)]


def _one(job: tuple) -> dict[str, Any]:
    part, step, exp001, brain_factory, kw = job
    logging.getLogger("AtlasAI.MarketLoop").setLevel(logging.ERROR)
    return bt.summarize(bt.replay(part, step=step, exp001=exp001, brain_factory=brain_factory, **kw))


def compare(data: dict[str, list[list]], windows: int, step: int, exp001: bool,
            brain_factory=None, variants: dict[str, dict[str, Any]] = VARIANTS, jobs: int = 1) -> dict[str, Any]:
    """Every variant on every window. jobs > 1 runs the independent replays in parallel
    processes (same inputs, same deterministic results, just faster)."""
    parts = split(data, windows)
    work = [(name, i, (part, step, exp001, brain_factory, kw))
            for name, kw in variants.items() for i, part in enumerate(parts)]
    results: dict[tuple[str, int], dict[str, Any]] = {}
    total = len(work)
    if jobs > 1:
        from concurrent.futures import ProcessPoolExecutor, as_completed

        with ProcessPoolExecutor(max_workers=jobs) as pool:
            futures = {pool.submit(_one, job): (name, i) for name, i, job in work}
            for n, fut in enumerate(as_completed(futures), 1):
                results[futures[fut]] = fut.result()
                print(f"  {n}/{total} bitti ({futures[fut][0]}) - paralel {jobs}", file=sys.stderr, flush=True)
    else:
        for n, (name, i, job) in enumerate(work, 1):
            results[(name, i)] = _one(job)
            print(f"  {n}/{total} bitti ({name}) - Ctrl+C'ye basma", file=sys.stderr, flush=True)
    table = {name: [results[(name, i)] for i in range(len(parts))] for name in variants}
    ref = table[REFERENCE]
    verdicts = {}
    for name, rows in table.items():
        if name == REFERENCE or name not in variants or not variants[name].get("slippage_bps"):
            verdicts[name] = "-"
            continue
        beats = all(r["net_pnl"] > b["net_pnl"] for r, b in zip(rows, ref))
        no_worse_dd = max(r["max_drawdown"] for r in rows) <= max(b["max_drawdown"] for b in ref)
        verdicts[name] = "BETTER" if beats and no_worse_dd else "NOT PROVEN"
    return {"windows": windows, "table": table, "verdicts": verdicts}


def main(argv: list[str] | None = None, fetch=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--days", type=int, default=21)
    parser.add_argument("--windows", type=int, default=3)
    parser.add_argument("--step", type=int, default=15)
    parser.add_argument("--jobs", type=int, default=max(1, (os.cpu_count() or 2) - 1),
                        help="parallel processes (default: all cores but one)")
    parser.add_argument("--output", default=None, help="also write the JSON result here atomically (used by the research agent)")
    parser.add_argument("--quick", action="store_true", help="fast check: 14 days, 2 windows, step 30")
    parser.add_argument("--symbols", default=",".join(bt.DEFAULT_SYMBOLS))
    parser.add_argument("--symbols-file", default=None, help="JSON with a 'symbols' list (config/universe_selection.json)")
    parser.add_argument("--no-exp001", action="store_true", help="replay without the EXP-001 floor")
    parser.add_argument("--only", default=None, help="comma-separated words; run only variants whose name contains one (the reference always runs)")
    parser.add_argument("--save-dataset", default=None, help="write the downloaded candles to this JSON file")
    parser.add_argument("--dataset", default=None, help="replay a saved dataset instead of downloading (reproducible)")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    if args.quick:
        args.days, args.windows, args.step = 14, 2, 30
    variants = VARIANTS
    if args.only:
        words = [w.strip().lower() for w in args.only.split(",") if w.strip()]
        variants = {k: v for k, v in VARIANTS.items() if k == REFERENCE or any(w in k.lower() for w in words)}
    logging.getLogger("AtlasAI.MarketLoop").setLevel(logging.ERROR)
    symbols = [s.strip().upper() for s in args.symbols.split(",") if s.strip()]
    if args.symbols_file:
        symbols = json.loads(Path(args.symbols_file).read_text(encoding="utf-8"))["symbols"]
    if fetch is None:
        from tools.measure_volatility_ceiling import fetch_page as fetch
    if args.dataset:
        saved = json.loads(Path(args.dataset).read_text(encoding="utf-8"))
        data = saved["data"]
        if dataset_manifest(data)["dataset_sha256"] != saved["manifest"]["dataset_sha256"]:
            print("DATASET CORRUPTED: hash mismatch, refusing to replay", file=sys.stderr)
            return 2
    else:
        data = {}
        for symbol in symbols:
            print(f"downloading {symbol} ({args.days} days)...", file=sys.stderr, flush=True)
            data[symbol] = bt._history(symbol, args.days, fetch)
    manifest = dataset_manifest(data)
    if args.save_dataset:
        Path(args.save_dataset).write_text(json.dumps({"manifest": manifest, "data": data}, default=str), encoding="utf-8")
    print(f"replaying {len(variants)} variants x {args.windows} windows (this takes a while)...", file=sys.stderr, flush=True)
    result = compare(data, args.windows, args.step, not args.no_exp001, variants=variants, jobs=args.jobs)
    result["dataset"] = manifest
    if args.output:
        out = Path(args.output)
        tmp = out.with_suffix(".tmp")
        tmp.write_text(json.dumps({**result, "finished_at": __import__("datetime").datetime.now(__import__("datetime").timezone.utc).isoformat()},
                                  default=str, ensure_ascii=False), encoding="utf-8")
        os.replace(tmp, out)
    result["parameters"] = {"windows": args.windows, "step": args.step, "exp001": not args.no_exp001,
                            "variants": sorted(variants)}
    if args.json:
        print(json.dumps(result, default=str, ensure_ascii=False, indent=2))
        return 0
    print(f"STRATEJİ KARŞILAŞTIRMASI — {len(symbols)} coin, {args.days} gün, {args.windows} pencere, "
          f"makro/sentiment hariç, ücret %0.1/taraf")
    header = "".join(f"  pencere {i + 1:<17}" for i in range(args.windows))
    print(f"{'strateji':<28}{header}  karar")
    for name, rows in result["table"].items():
        cells = "".join(f"  net {Decimal(r['net_pnl']):>8.2f} dd {Decimal(r['max_drawdown']):>6.2f} n {r['closed_trades']:>3}/{r['open_at_end']}" for r in rows)
        print(f"{name:<28}{cells}  {result['verdicts'][name]}")
    print("\nBETTER = her pencerede gerçekçi referanstan daha iyi net ve daha kötü olmayan en büyük düşüş. "
          "n = kapanan/pencere sonunda açık işlem. Araştırma kanıtıdır; hiçbir şey değiştirilmedi.")
    print(f"Veri seti özeti (sha256): {manifest['dataset_sha256'][:16]} — aynı sonucu almak için --save-dataset / --dataset kullan.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
