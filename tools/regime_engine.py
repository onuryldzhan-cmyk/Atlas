"""Regime engine v2 (research): classify each coin's market regime from closed candles.

  python -m tools.regime_engine                      # 20-coin universe, 1h candles, last 30 days (Binance, owner machine)
  python -m tools.regime_engine --symbols BTCUSDT,ETHUSDT --json

Regimes (strategy-framework layer 2), decided in this order:

  PANIC         close fell more than PANIC_DROP over the last PANIC_BARS bars AND volatility is in its top decile
  HIGH_VOL      volatility above its own 80th percentile (the runtime's risk regime uses the same idea)
  TREND_UP      efficiency ratio >= TREND_ER and the slow EMA slope is up
  TREND_DOWN    efficiency ratio >= TREND_ER and the slow EMA slope is down
  SIDEWAYS      efficiency ratio <= SIDEWAYS_ER
  TRANSITION    everything in between (no clear state: the honest answer)

The efficiency ratio (Kaufman) is |net move| / sum(|bar moves|) over a window:
1 = straight line, 0 = pure chop. The classifier itself lives in core/market_cycle.py
(Task 009, registry v5.93) and is shared with the runtime regime gate, which stays
OFF until evidence measured on the runtime rule (v5.93 C-9), the policy manifest and an
owner decision.
"""

from __future__ import annotations

import argparse
import json
from typing import Any

# Task 009 (registry v5.93): the classifier moved to core.market_cycle so replay, research and the
# runtime regime gate share ONE function; the names below are re-exported unchanged.
from core.market_cycle import (  # noqa: E402,F401
    EMA_SLOW,
    PANIC_BARS,
    PANIC_DROP,
    SIDEWAYS_ER,
    TREND_ER,
    VOL_HISTORY,
    VOL_WINDOW,
    WINDOW,
    _pstdev,
    classify,
    efficiency_ratio,
    ema,
    rolling_vol,
)


def history(closes: list[float], step: int = 6) -> dict[str, int]:
    """How often each regime occurred over the series (sampled every `step` bars)."""
    counts: dict[str, int] = {}
    start = max(WINDOW, EMA_SLOW, VOL_WINDOW) + 2
    for end in range(start, len(closes) + 1, step):
        r = classify(closes[:end])["regime"]
        counts[r] = counts.get(r, 0) + 1
    return counts


def snapshot(symbols: list[str], fetch_closes) -> dict[str, dict[str, Any]]:
    """Current regime and 30-day history per coin; a failed download is UNKNOWN, never guessed."""
    out: dict[str, dict[str, Any]] = {}
    for sym in symbols:
        try:
            closes = fetch_closes(sym)
        except Exception as exc:
            out[sym] = {"regime": "UNKNOWN", "reason": type(exc).__name__}
            continue
        out[sym] = {**classify(closes), "history": history(closes)}
    return out


def binance_closes(symbol: str, days: int = 30) -> list[float]:
    from tools.select_universe import http_get

    rows = http_get(f"/api/v3/klines?symbol={symbol}&interval=1h&limit={min(1000, days * 24)}")
    return [float(r[4]) for r in rows[:-1]]  # drop the still-open candle


def load_symbols(path: str = "config/universe_selection.json") -> list[str]:
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    return [s if isinstance(s, str) else s["symbol"] for s in data.get("symbols", [])]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--symbols", default=None)
    parser.add_argument("--symbols-file", default="config/universe_selection.json")
    parser.add_argument("--days", type=int, default=30)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    if args.symbols:
        symbols = [x.strip().upper() for x in args.symbols.split(",") if x.strip()]
    else:
        symbols = load_symbols(args.symbols_file)
    out = snapshot(symbols, lambda sym: binance_closes(sym, args.days))
    if args.json:
        print(json.dumps(out, ensure_ascii=False, indent=2))
        return 0
    print(f"ATLAS REJİM MOTORU v2 (araştırma) — 1s mumlar, {args.days} gün")
    for sym, r in out.items():
        hist = ", ".join(f"{k} {v}" for k, v in sorted(r.get("history", {}).items(), key=lambda x: -x[1]))
        print(f"  {sym:<10} {r['regime']:<11} ER {r.get('efficiency_ratio', '-'):<6} vol% {r.get('vol_percentile', '-'):<5} | geçmiş: {hist}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
