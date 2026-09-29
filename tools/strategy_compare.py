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
}
REFERENCE = "gerçekçi dolum (referans)"


def split(data: dict[str, list[list]], windows: int) -> list[dict[str, list[list]]]:
    length = min(len(rows) for rows in data.values())
    size = length // windows
    if size <= bt.WINDOW + 60:
        raise ValueError(f"window too short: {size} candles; use more --days or fewer --windows")
    return [{s: rows[i * size:(i + 1) * size] for s, rows in data.items()} for i in range(windows)]


def compare(data: dict[str, list[list]], windows: int, step: int, exp001: bool,
            brain_factory=None, variants: dict[str, dict[str, Any]] = VARIANTS) -> dict[str, Any]:
    parts = split(data, windows)
    table: dict[str, list[dict[str, Any]]] = {}
    for name, kw in variants.items():
        table[name] = [bt.summarize(bt.replay(part, step=step, exp001=exp001, brain_factory=brain_factory, **kw))
                       for part in parts]
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
    parser.add_argument("--symbols", default=",".join(bt.DEFAULT_SYMBOLS))
    parser.add_argument("--symbols-file", default=None, help="JSON with a 'symbols' list (config/universe_selection.json)")
    parser.add_argument("--no-exp001", action="store_true", help="replay without the EXP-001 floor")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    logging.getLogger("AtlasAI.MarketLoop").setLevel(logging.ERROR)
    symbols = [s.strip().upper() for s in args.symbols.split(",") if s.strip()]
    if args.symbols_file:
        symbols = json.loads(Path(args.symbols_file).read_text(encoding="utf-8"))["symbols"]
    if fetch is None:
        from tools.measure_volatility_ceiling import fetch_page as fetch
    data = {}
    for symbol in symbols:
        print(f"downloading {symbol} ({args.days} days)...", file=sys.stderr, flush=True)
        data[symbol] = bt._history(symbol, args.days, fetch)
    print(f"replaying {len(VARIANTS)} variants x {args.windows} windows (this takes a while)...", file=sys.stderr, flush=True)
    result = compare(data, args.windows, args.step, not args.no_exp001)
    if args.json:
        print(json.dumps(result, default=str, ensure_ascii=False, indent=2))
        return 0
    print(f"STRATEJİ KARŞILAŞTIRMASI — {len(symbols)} coin, {args.days} gün, {args.windows} pencere, "
          f"makro/sentiment hariç, ücret %0.1/taraf")
    header = "".join(f"  pencere {i + 1:<17}" for i in range(args.windows))
    print(f"{'strateji':<28}{header}  karar")
    for name, rows in result["table"].items():
        cells = "".join(f"  net {Decimal(r['net_pnl']):>8.2f} dd {Decimal(r['max_drawdown']):>6.2f}" for r in rows)
        print(f"{name:<28}{cells}  {result['verdicts'][name]}")
    print("\nBETTER = her pencerede gerçekçi referanstan daha iyi net ve daha kötü olmayan en büyük düşüş. "
          "Araştırma kanıtıdır; hiçbir şey değiştirilmedi.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
