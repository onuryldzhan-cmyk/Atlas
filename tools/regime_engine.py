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
1 = straight line, 0 = pure chop. Pure functions over OHLC rows; research only,
nothing here reaches the runtime. The strategy router will read these regimes
only after a proposal the owner approves.
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
from typing import Any

WINDOW = 24            # bars for the efficiency ratio (24 x 1h = one day)
EMA_SLOW = 50
TREND_ER = 0.35
SIDEWAYS_ER = 0.15
VOL_WINDOW = 24
VOL_HISTORY = 24 * 20  # percentiles over ~20 days of 1h bars
PANIC_BARS = 6
PANIC_DROP = 0.06


def efficiency_ratio(closes: list[float], window: int = WINDOW) -> float | None:
    if len(closes) <= window:
        return None
    seg = closes[-window - 1:]
    path = sum(abs(b - a) for a, b in zip(seg, seg[1:]))
    return 0.0 if path == 0 else abs(seg[-1] - seg[0]) / path


def ema(values: list[float], span: int) -> list[float]:
    k, out = 2 / (span + 1), []
    for v in values:
        out.append(v if not out else out[-1] + k * (v - out[-1]))
    return out


def rolling_vol(closes: list[float], window: int = VOL_WINDOW) -> list[float]:
    rets = [b / a - 1 for a, b in zip(closes, closes[1:]) if a > 0]
    return [statistics.pstdev(rets[i - window:i]) for i in range(window, len(rets) + 1)]


def classify(closes: list[float]) -> dict[str, Any]:
    need = max(WINDOW, EMA_SLOW, VOL_WINDOW) + 2
    if len(closes) < need or any(c <= 0 for c in closes):
        return {"regime": "UNKNOWN", "reason": f"needs >= {need} positive closes, got {len(closes)}"}
    er = efficiency_ratio(closes)
    vols = rolling_vol(closes)[-VOL_HISTORY:]
    now_vol = vols[-1]
    ranked = sorted(vols)
    pct = sum(1 for v in ranked if v < now_vol) / len(ranked)  # strictly below: a flat history is not "high"
    slow = ema(closes, EMA_SLOW)
    slope = slow[-1] / slow[-6] - 1 if slow[-6] > 0 else 0.0
    drop = closes[-1] / closes[-1 - PANIC_BARS] - 1
    facts = {"efficiency_ratio": round(er, 3), "vol_percentile": round(pct, 2),
             "ema_slope_5": round(slope, 4), f"move_{PANIC_BARS}_bars": round(drop, 4)}
    if drop <= -PANIC_DROP and pct >= 0.9:
        regime = "PANIC"
    elif pct >= 0.8:
        regime = "HIGH_VOL"
    elif er >= TREND_ER and slope > 0:
        regime = "TREND_UP"
    elif er >= TREND_ER and slope < 0:
        regime = "TREND_DOWN"
    elif er <= SIDEWAYS_ER:
        regime = "SIDEWAYS"
    else:
        regime = "TRANSITION"
    return {"regime": regime, **facts}


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
