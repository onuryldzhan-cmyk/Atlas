"""Measure candidate absolute volatility ceilings for the LOW risk level.

Read-only research tool for the risk_level proposal
(governance/ATLAS_RISK_LEVEL_FROM_VOLATILITY_REGIME_PROPOSAL_v1.0.md, open
question A2): LOW may be granted only if the current realized volatility
is below a fixed ceiling, and that ceiling must be MEASURED, not guessed.

It fetches historical closed 1-minute candles from the Binance public
klines endpoint (no credentials), computes realized volatility with the
exact estimator the risk agent uses (core/market_risk_regime.py:
30-return RMS of log returns), and reports per symbol:

- the distribution of realized volatility (p10 ... p90);
- for each candidate ceiling (a percentile of that distribution), how
  often the absolute test alone passes, and how often it passes together
  with the relative 3-hour LOW regime (A1 + A2), replayed minute by minute.

It writes nothing and changes no setting. Choosing a ceiling is an owner
decision recorded in a successor registry.

Usage:
  python -m tools.measure_volatility_ceiling [--days 30] [--symbols BTCUSDT,ETHUSDT] [--json]
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
import time
import urllib.request
from collections.abc import Callable, Sequence

from core.market_risk_regime import (
    MIN_REFERENCE_WINDOWS,
    REGIME_LOW,
    WINDOW_RETURNS,
    _rolling_realized_volatility,
    classify_volatility_regime,
)

DEFAULT_SYMBOLS = ("BTCUSDT", "ETHUSDT", "BNBUSDT", "SOLUSDT", "XRPUSDT")
KLINES_URL = (
    "https://api.binance.com/api/v3/klines"
    "?symbol={symbol}&interval=1m&startTime={start}&limit=1000"
)
MINUTE_MS = 60_000
# MarketLoop's trailing window: 200 candles -> 199 returns -> 170 windows.
LIVE_CANDLES = 200
CANDIDATE_PERCENTILES = (10, 20, 30, 40, 50)

Fetcher = Callable[[str, int], list[list]]


def fetch_page(symbol: str, start_ms: int) -> list[list]:
    url = KLINES_URL.format(symbol=symbol, start=start_ms)
    with urllib.request.urlopen(url, timeout=15) as response:
        return json.loads(response.read())


def fetch_closes(symbol: str, days: int, fetch: Fetcher = fetch_page,
                 now_ms: int | None = None) -> list[float]:
    """Closed 1-minute closes, oldest first, contiguous (stops at a gap)."""

    now_ms = now_ms if now_ms is not None else int(time.time() * 1000)
    start = now_ms - days * 24 * 60 * MINUTE_MS
    closes: list[float] = []
    last_open: int | None = None

    while start < now_ms:
        page = fetch(symbol, start)
        if not page:
            break
        for row in page:
            open_time, close_time = int(row[0]), int(row[6])
            if close_time >= now_ms:  # still forming
                return closes
            if last_open is not None and open_time != last_open + MINUTE_MS:
                closes.clear()  # a gap: restart so every window is contiguous
            closes.append(float(row[4]))
            last_open = open_time
        start = int(page[-1][0]) + MINUTE_MS

    return closes


def percentile(values: Sequence[float], pct: int) -> float:
    return statistics.quantiles(values, n=100, method="inclusive")[pct - 1]


def replay_relative_low(vols: Sequence[float]) -> list[bool]:
    """Minute-by-minute replay of the live 3-hour relative regime.

    At each minute the current window is compared against the windows
    MarketLoop would have in its trailing 200-candle view.
    """

    per_view = LIVE_CANDLES - 1 - WINDOW_RETURNS + 1  # windows in one live view
    flags: list[bool] = []
    for end in range(per_view, len(vols) + 1):
        view = vols[end - per_view:end]
        current, reference = view[-1], view[:-1]
        if len(reference) < MIN_REFERENCE_WINDOWS:
            flags.append(False)
            continue
        quintiles = statistics.quantiles(reference, n=5, method="inclusive")
        flags.append(classify_volatility_regime(current, quintiles[0], quintiles[3]) == REGIME_LOW)
    return flags


def measure(symbol: str, closes: Sequence[float]) -> dict:
    vols = _rolling_realized_volatility(list(closes))
    if len(vols) < 1000:
        return {"symbol": symbol, "available": False,
                "reason": f"only {len(vols)} windows; need >= 1000"}

    relative = replay_relative_low(vols)
    aligned = vols[len(vols) - len(relative):]
    distribution = {f"p{p}": percentile(vols, p) for p in range(10, 100, 10)}

    candidates = []
    for pct in CANDIDATE_PERCENTILES:
        ceiling = percentile(vols, pct)
        below = sum(v < ceiling for v in aligned)
        both = sum(r and v < ceiling for r, v in zip(relative, aligned))
        candidates.append({
            "percentile": pct,
            "ceiling": ceiling,
            "absolute_pass_share": below / len(aligned),
            "a1_and_a2_share": both / len(aligned),
        })

    return {
        "symbol": symbol,
        "available": True,
        "minutes": len(closes),
        "windows": len(vols),
        "relative_low_share": sum(relative) / len(relative),
        "distribution": distribution,
        "candidates": candidates,
    }


def main(argv: list[str] | None = None, fetch: Fetcher = fetch_page) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--days", type=int, default=30)
    parser.add_argument("--symbols", default=",".join(DEFAULT_SYMBOLS))
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)

    results = []
    for symbol in [s.strip().upper() for s in args.symbols.split(",") if s.strip()]:
        # progress on stderr so --json output stays clean
        print(f"downloading {symbol} ({args.days} days of 1m candles)...", file=sys.stderr, flush=True)
        try:
            results.append(measure(symbol, fetch_closes(symbol, args.days, fetch)))
        except Exception as exc:
            results.append({"symbol": symbol, "available": False,
                            "reason": f"{type(exc).__name__}: {exc}"})

    if args.json:
        print(json.dumps({"days": args.days, "window_returns": WINDOW_RETURNS,
                          "results": results}, indent=2))
        return 0

    print(f"realized volatility = RMS of {WINDOW_RETURNS} one-minute log returns; "
          f"history = {args.days} days")
    for result in results:
        print()
        if not result["available"]:
            print(f"{result['symbol']}: unavailable - {result['reason']}")
            continue
        dist = result["distribution"]
        print(f"{result['symbol']}  ({result['minutes']} minutes)")
        print("  distribution: " + "  ".join(f"{k}={v:.6f}" for k, v in dist.items()))
        print(f"  relative 3h LOW alone (A1): {result['relative_low_share']:.1%} of minutes")
        print("  candidate ceiling   A2 alone   A1 and A2")
        for c in result["candidates"]:
            print(f"  p{c['percentile']:<3} {c['ceiling']:.6f}   "
                  f"{c['absolute_pass_share']:7.1%}   {c['a1_and_a2_share']:8.1%}")
    print()
    print("Nothing was changed. Pick a ceiling (or none) as an owner decision.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
