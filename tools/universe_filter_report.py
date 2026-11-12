"""Which watched coins would freqtrade-style pairlist filters remove? Report only (owner 2026-10-02).

Applies four filters modelled on freqtrade's pairlist plugins (freqtrade/freqtrade,
docs "Pairlists") to the coins in config/universe_selection.json:

  AgeFilter            listed fewer than MIN_DAYS_LISTED daily candles
  VolatilityFilter     10-day volatility (std of daily log returns x sqrt(10)) outside [MIN_VOL, MAX_VOL]
  RangeStabilityFilter 10-day (highest high - lowest low) / lowest low above MAX_RANGE
  SpreadFilter         live best ask / best bid - 1 above MAX_SPREAD (0.5 %, freqtrade's default)

Nothing is changed: the trading universe, config and gates stay as they are. A coin
whose data cannot be read is reported as UNKNOWN for that filter, never passed.

    python -m tools.universe_filter_report
"""
from __future__ import annotations

import json
import math
import sys
import urllib.request
from decimal import Decimal
from pathlib import Path
from typing import Any, Callable

KLINES_URL = "https://api.binance.com/api/v3/klines?symbol={symbol}&interval=1d&limit=60"
MIN_DAYS_LISTED = 10      # freqtrade AgeFilter default
LOOKBACK = 10             # freqtrade VolatilityFilter / RangeStabilityFilter default lookback_period (1d)
MIN_VOL, MAX_VOL = 0.05, 0.50   # freqtrade documented example values
MAX_RANGE = 0.99                # freqtrade RangeStabilityFilter documented example max_rate_of_change
MAX_SPREAD = 0.005              # freqtrade SpreadFilter default max_spread_ratio

KlineFetcher = Callable[[str], list]
DepthFetcher = Callable[[str], dict]


def _klines(symbol: str) -> list:
    with urllib.request.urlopen(KLINES_URL.format(symbol=symbol), timeout=15) as response:
        return json.loads(response.read(2_000_000))


def _depth(symbol: str) -> dict:
    from tools.shadow_costs import fetch_depth

    return fetch_depth(symbol)


def evaluate_symbol(symbol: str, klines: list | None, depth: dict | None) -> dict[str, Any]:
    out: dict[str, Any] = {"symbol": symbol}
    if klines is None:
        out.update(age="UNKNOWN", volatility="UNKNOWN", range="UNKNOWN")
    else:
        days = len(klines)
        out["days_listed_seen"] = days
        out["age"] = "REMOVE" if days < MIN_DAYS_LISTED else "KEEP"
        closes = [float(k[4]) for k in klines[-(LOOKBACK + 1):]]
        if len(closes) < LOOKBACK + 1 or min(closes) <= 0:
            out["volatility"] = out["range"] = "UNKNOWN"
        else:
            rets = [math.log(b / a) for a, b in zip(closes, closes[1:])]
            mean = math.fsum(rets) / len(rets)
            vol = math.sqrt(math.fsum((r - mean) ** 2 for r in rets) / (len(rets) - 1)) * math.sqrt(LOOKBACK)
            window = klines[-LOOKBACK:]
            low, high = min(float(k[3]) for k in window), max(float(k[2]) for k in window)
            rng = (high - low) / low if low > 0 else None
            out["volatility_10d"] = round(vol, 3)
            out["volatility"] = "KEEP" if MIN_VOL <= vol <= MAX_VOL else "REMOVE"
            out["range_10d"] = None if rng is None else round(rng, 3)
            out["range"] = "UNKNOWN" if rng is None else ("REMOVE" if rng > MAX_RANGE else "KEEP")
    try:
        bid, ask = Decimal(str(depth["bids"][0][0])), Decimal(str(depth["asks"][0][0]))
        spread = float(ask / bid - 1) if bid > 0 and ask > bid else None
    except (TypeError, KeyError, IndexError, ValueError, ArithmeticError):
        spread = None
    out["spread_pct"] = None if spread is None else round(spread * 100, 4)
    out["spread"] = "UNKNOWN" if spread is None else ("REMOVE" if spread > MAX_SPREAD else "KEEP")
    filters = ("age", "volatility", "range", "spread")
    out["removed_by"] = [f for f in filters if out[f] == "REMOVE"]
    out["unknown"] = [f for f in filters if out[f] == "UNKNOWN"]
    return out


def report(symbols: list[str], klines: KlineFetcher = _klines, depth: DepthFetcher = _depth) -> list[dict[str, Any]]:
    rows = []
    for symbol in symbols:
        try:
            k = klines(symbol)
        except (OSError, ValueError):
            k = None
        try:
            d = depth(symbol)
        except (OSError, ValueError):
            d = None
        rows.append(evaluate_symbol(symbol, k, d))
    return rows


def main(argv: list[str] | None = None) -> int:
    symbols = json.loads((Path(__file__).resolve().parents[1] / "config" / "universe_selection.json")
                         .read_text(encoding="utf-8"))["symbols"]
    rows = report(symbols)
    print(f"{'coin':10} {'days':>5} {'vol10d':>7} {'range10d':>9} {'spread%':>8}  verdict")
    for r in rows:
        verdict = ("REMOVE: " + ", ".join(r["removed_by"])) if r["removed_by"] else "keep"
        if r["unknown"]:
            verdict += f"  (unknown: {', '.join(r['unknown'])})"
        print(f"{r['symbol']:10} {str(r.get('days_listed_seen', '-')):>5} {str(r.get('volatility_10d', '-')):>7} "
              f"{str(r.get('range_10d', '-')):>9} {str(r['spread_pct']):>8}  {verdict}")
    removed = [r["symbol"] for r in rows if r["removed_by"]]
    print(f"would remove {len(removed)} of {len(rows)}: {', '.join(removed) or 'none'}")
    print("Report only: config/universe_selection.json and every gate are unchanged.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
