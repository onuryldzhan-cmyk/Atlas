"""Pick Atlas's 20 coins from real Binance data: 8 trend, 8 medium risk, 4 high risk.

  python -m tools.select_universe                 # show the selection and write it
  python tools/refresh_venue_instrument_rules.py --symbols-file config/universe_selection.json

Owner decision 2026-09-29 (registry v5.51): "şu an trende olan 8 coin, orta
risk 8 coin ve yükselişte olabilecek ama riskli 4 coin". The picks are
never guessed: they come from Binance's public 24 h tickers, its
exchangeInfo (only TRADING USDT spot pairs) and 7 daily candles per
candidate, by fixed, printed rules:

* excluded: stablecoins, fiat-like and leveraged tokens (UP/DOWN/BULL/BEAR);
  anything below MIN_QUOTE_VOLUME_USD of 24 h volume (too thin to fill);
* TREND (8): among the TOP_LIQUID most-traded pairs, the highest 7-day
  return, positive only;
* MEDIUM (8): the next most-traded pairs whose 7-day daily volatility is at
  most MEDIUM_MAX_VOL, by volume;
* HIGH (4): the strongest positive 7-day momentum among the remaining pairs
  that still clear the volume floor;
* coins Atlas currently holds are always kept (dropping one would halt
  execution fail-closed on its missing rule); they replace HIGH, then MEDIUM
  picks so the total stays 20.

Categories are a selection lens only: RiskEngine still sizes every trade by
its own volatility regime, and every limit (max 5 positions, 80 % exposure)
is unchanged. The result and every number behind it are written to
config/universe_selection.json for review before the rules refresh.
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
import urllib.request
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Callable

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "config" / "universe_selection.json"
BASE_URL = "https://api.binance.com"
TOTAL, N_TREND, N_MEDIUM, N_HIGH = 20, 8, 8, 4
TOP_LIQUID = 30
MIN_QUOTE_VOLUME_USD = 20_000_000
MEDIUM_MAX_VOL = 0.06
STABLE = {"USDC", "FDUSD", "TUSD", "USDP", "DAI", "BUSD", "EUR", "EURI", "AEUR", "USDE", "USD1", "PAXG", "XUSD", "BFUSD", "RLUSD"}
LEVERAGED_SUFFIX = ("UP", "DOWN", "BULL", "BEAR")

Getter = Callable[[str], Any]


def http_get(path: str) -> Any:
    with urllib.request.urlopen(BASE_URL + path, timeout=20) as response:
        return json.loads(response.read().decode("utf-8"))


def eligible(exchange_info: dict, tickers: list[dict]) -> list[dict]:
    trading = {s["symbol"]: s["baseAsset"] for s in exchange_info.get("symbols", [])
               if s.get("status") == "TRADING" and s.get("quoteAsset") == "USDT"
               and s.get("isSpotTradingAllowed", True)}
    out = []
    for t in tickers:
        symbol = t.get("symbol")
        base = trading.get(symbol)
        if not base or base in STABLE or base.endswith(LEVERAGED_SUFFIX):
            continue
        volume = float(t.get("quoteVolume") or 0)
        if volume < MIN_QUOTE_VOLUME_USD:
            continue
        out.append({"symbol": symbol, "base": base, "quote_volume_24h": round(volume), "change_24h_pct": float(t.get("priceChangePercent") or 0)})
    return sorted(out, key=lambda c: -c["quote_volume_24h"])


def with_weekly_stats(candidates: list[dict], get: Getter) -> list[dict]:
    for i, c in enumerate(candidates, 1):
        print(f"  {i}/{len(candidates)} {c['symbol']} ...", file=sys.stderr, flush=True)
        rows = get(f"/api/v3/klines?symbol={c['symbol']}&interval=1d&limit=8")
        closes = [float(r[4]) for r in rows]
        if len(closes) < 8 or closes[0] <= 0:
            c["return_7d"], c["volatility_7d"] = None, None
            continue
        rets = [closes[i] / closes[i - 1] - 1 for i in range(1, len(closes))]
        c["return_7d"] = round(closes[-1] / closes[0] - 1, 4)
        c["volatility_7d"] = round(statistics.pstdev(rets), 4)
    return [c for c in candidates if c["return_7d"] is not None]


def select(candidates: list[dict], held: set[str] = frozenset()) -> dict[str, list[dict]]:
    chosen: set[str] = set()

    def take(pool: list[dict], n: int) -> list[dict]:
        picked = [c for c in pool if c["symbol"] not in chosen][:n]
        chosen.update(c["symbol"] for c in picked)
        return picked

    liquid = candidates[:TOP_LIQUID]
    trend = take(sorted([c for c in liquid if c["return_7d"] > 0], key=lambda c: -c["return_7d"]), N_TREND)
    medium = take([c for c in candidates if c["volatility_7d"] <= MEDIUM_MAX_VOL], N_MEDIUM)
    high = take(sorted([c for c in candidates if c["return_7d"] > 0], key=lambda c: -c["return_7d"]), N_HIGH)
    kept = [c for c in candidates if c["symbol"] in held and c["symbol"] not in chosen]
    kept += [{"symbol": s, "note": "held; not in today's candidates"} for s in sorted(held - {c["symbol"] for c in candidates})]
    for _ in kept:  # held coins displace HIGH first, then MEDIUM, then TREND
        for group in (high, medium, trend):
            if group:
                group.pop()
                break
    return {"TREND": trend, "MEDIUM": medium, "HIGH": high, "HELD_KEPT": kept}


def held_symbols() -> set[str]:
    try:
        from core.application import EXECUTION_FINANCIAL_STATE_FILE, resolve_state_directory

        state = json.loads((resolve_state_directory() / EXECUTION_FINANCIAL_STATE_FILE).read_text(encoding="utf-8"))
        return set(state.get("positions", {}))
    except (OSError, ValueError):
        return set()


def main(argv: list[str] | None = None, get: Getter = http_get) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--output", default=str(OUTPUT))
    args = parser.parse_args(argv)
    try:
        print("Binance'ten veri çekiliyor (birkaç dakika sürebilir; Ctrl+C'ye basma)...", file=sys.stderr, flush=True)
        info, tickers = get("/api/v3/exchangeInfo"), get("/api/v3/ticker/24hr")
        candidates = with_weekly_stats(eligible(info, tickers)[:80], get)
    except Exception as exc:  # network / venue failure: nothing is written
        print(f"REFUSED: Binance data unavailable ({type(exc).__name__}: {exc}); nothing written", file=sys.stderr)
        return 1
    groups = select(candidates, held_symbols())
    symbols = sorted({c["symbol"] for g in groups.values() for c in g})
    if len(symbols) > TOTAL:
        print(f"REFUSED: {len(symbols)} symbols > {TOTAL}", file=sys.stderr)
        return 1
    record = {"generated_at": datetime.now(UTC).isoformat(), "source": BASE_URL + " (ticker/24hr, exchangeInfo, klines 1d)",
              "rules": {"top_liquid": TOP_LIQUID, "min_quote_volume_usd": MIN_QUOTE_VOLUME_USD,
                        "medium_max_daily_vol_7d": MEDIUM_MAX_VOL}, "groups": groups, "symbols": symbols}
    Path(args.output).write_text(json.dumps(record, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    labels = {"TREND": "Trend (8)", "MEDIUM": "Orta risk (8)", "HIGH": "Yüksek risk, yükseliş potansiyeli (4)", "HELD_KEPT": "Elde tutulan, korunan"}
    for key, items in groups.items():
        if items:
            print(f"\n{labels[key]}:")
            for c in items:
                extra = (f"7g {c['return_7d']:+.1%}  oynaklık {c['volatility_7d']:.1%}  hacim {c['quote_volume_24h'] / 1e6:,.0f}M$"
                         if "return_7d" in c else c.get("note", ""))
                print(f"  {c['symbol']:<12} {extra}")
    print(f"\n{len(symbols)} coin yazıldı: {args.output}")
    print("Sonraki adım: python tools/refresh_venue_instrument_rules.py --symbols-file config/universe_selection.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
