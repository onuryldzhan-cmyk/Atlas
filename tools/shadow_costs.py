"""Shadow stage S1 (owner 2026-10-02): what would a real order have paid? Observe-only.

Paper fills at the last price with 0 slippage, so it never pays the bid/ask
spread or the order book depth. Each agent cycle this samples the live
public order book (Binance /api/v3/depth) of every watched coin and records,
for a trade of a given size, the cost of a market BUY (walking the asks) and a
market SELL (walking the bids) against the mid price, in basis points.
`report()` re-prices the closed Paper trades with those costs: Paper net vs
estimated Shadow net, side by side.

Ideas: NautilusTrader sandbox and hummingbot paper trading (orders matched
against the live book, nothing sent to the venue). Design:
docs/research/2026-10-02_shadow_stage_design.md (S1 only; S2/S3 need the owner).

Authority: research evidence only. It never changes a fill, a gate or an
order. A book that cannot be read, or is too thin for the size, is recorded
as missing - never estimated.

    python -m tools.shadow_costs report
"""
from __future__ import annotations

import csv
import json
import statistics
import sys
import time
import urllib.request
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any, Callable

DEPTH_URL = "https://api.binance.com/api/v3/depth?symbol={symbol}&limit=100"
COLUMNS = ("time", "symbol", "notional", "mid", "spread_bps", "buy_bps", "sell_bps")
DEFAULT_NOTIONAL = Decimal("1000")  # used only when there are no closed trades to size from (labelled in the output)

Fetcher = Callable[[str], dict]


def fetch_depth(symbol: str) -> dict:
    with urllib.request.urlopen(DEPTH_URL.format(symbol=symbol), timeout=10) as response:
        return json.loads(response.read(2_000_000))


def _walk(levels: list, notional: Decimal) -> Decimal | None:
    """Volume-weighted price of spending `notional` quote along the levels; None if the book is too thin."""
    left, qty = notional, Decimal(0)
    for price_s, size_s in levels:
        price, size = Decimal(str(price_s)), Decimal(str(size_s))
        if price <= 0 or size <= 0:
            return None
        take = min(left, price * size)
        qty += take / price
        left -= take
        if left <= 0:
            return notional / qty
    return None


def book_cost(depth: dict, notional: Decimal) -> dict[str, Any] | None:
    """Spread and market-order cost (bps vs mid) for one side each; None for a malformed or empty book."""
    try:
        bids, asks = depth["bids"], depth["asks"]
        best_bid, best_ask = Decimal(str(bids[0][0])), Decimal(str(asks[0][0]))
    except (KeyError, IndexError, TypeError, ValueError, ArithmeticError):
        return None
    if best_bid <= 0 or best_ask <= best_bid:
        return None
    mid = (best_bid + best_ask) / 2
    buy, sell = _walk(asks, notional), _walk(bids, notional)
    bps = lambda x: None if x is None else round(float(x * 10000), 2)  # noqa: E731
    return {"mid": mid, "spread_bps": bps((best_ask - best_bid) / mid),
            "buy_bps": bps((buy - mid) / mid) if buy else None,
            "sell_bps": bps((mid - sell) / mid) if sell else None}


def _paths(research_dir: Path) -> Path:
    d = research_dir / "shadow"
    d.mkdir(parents=True, exist_ok=True)
    return d / "book_costs.csv"


def typical_notional(closed: list[dict]) -> tuple[Decimal, bool]:
    """Median entry size of the closed Paper trades; (DEFAULT_NOTIONAL, False) when there are none."""
    sizes = [Decimal(str(r["cost_quote"])) for r in closed if r.get("cost_quote")]
    return (Decimal(str(statistics.median(sizes))), True) if sizes else (DEFAULT_NOTIONAL, False)


def run(research_dir: Path, symbols: list[str], notional: Decimal, *, fetch: Fetcher = fetch_depth,
        now: datetime | None = None) -> dict[str, Any]:
    stamp = (now or datetime.now(UTC)).isoformat()
    rows, missing = [], []
    for symbol in symbols:
        try:
            cost = book_cost(fetch(symbol), notional)
        except (OSError, ValueError):
            cost = None
        if cost is None:
            missing.append(symbol)
            continue
        rows.append([stamp, symbol, str(notional), str(cost["mid"]), cost["spread_bps"],
                     "" if cost["buy_bps"] is None else cost["buy_bps"],
                     "" if cost["sell_bps"] is None else cost["sell_bps"]])
    if rows:
        path = _paths(research_dir)
        new = not path.exists()
        with path.open("a", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            if new:
                w.writerow(COLUMNS)
            w.writerows(rows)
    if not rows:
        return {"verdict": "WARN", "summary": f"emir defteri okunamadı ({len(missing)} coin); değer uydurulmadı"}
    rt = [float(r[5]) + float(r[6]) for r in rows if r[5] != "" and r[6] != ""]
    med = f"{statistics.median(rt):.1f}" if rt else "N/A"
    return {"verdict": "OK", "summary": f"{len(rows)} coin defteri ölçüldü ({notional} USDT); medyan gidiş-dönüş "
                                        f"ek maliyet {med} bps" + (f"; okunamayan: {', '.join(missing)}" if missing else "")}


def median_costs(research_dir: Path) -> dict[str, dict[str, float]]:
    """Per symbol: median buy and sell cost (bps) over every sample; symbols without both sides are left out."""
    path = research_dir / "shadow" / "book_costs.csv"
    if not path.exists():
        return {}
    acc: dict[str, tuple[list[float], list[float]]] = {}
    with path.open(encoding="utf-8") as f:
        for r in csv.DictReader(f):
            if r["buy_bps"] and r["sell_bps"]:
                b, s = acc.setdefault(r["symbol"], ([], []))
                b.append(float(r["buy_bps"]))
                s.append(float(r["sell_bps"]))
    return {sym: {"buy_bps": statistics.median(b), "sell_bps": statistics.median(s), "samples": len(b)}
            for sym, (b, s) in acc.items()}


def report(closed: list[dict], costs: dict[str, dict[str, float]]) -> dict[str, Any]:
    """Re-price closed Paper trades with the measured round-trip book cost; unmeasured coins are counted, not guessed."""
    from ai.core.intelligence.trade_evidence import net_pnl

    paper = shadow = Decimal(0)
    priced = unpriced = 0
    for r in closed:
        c = costs.get(r.get("symbol", ""))
        if c is None or not r.get("cost_quote"):
            unpriced += 1
            continue
        net = net_pnl(r)
        extra = Decimal(str(r["cost_quote"])) * Decimal(str(c["buy_bps"] + c["sell_bps"])) / Decimal(10000)
        paper += net
        shadow += net - extra
        priced += 1
    return {"trades_priced": priced, "trades_unpriced": unpriced, "paper_net": round(float(paper), 2),
            "shadow_net_estimate": round(float(shadow), 2), "book_cost": round(float(paper - shadow), 2)}


def main(argv: list[str] | None = None) -> int:
    from core.application import resolve_state_directory
    from tools.agent_cycle import _archive_path
    from tools.exp001_report import load_closed

    if (argv if argv is not None else sys.argv[1:]) != ["report"]:
        print(__doc__.strip().splitlines()[-1].strip())
        return 2
    research = resolve_state_directory() / "research"
    costs = median_costs(research)
    if not costs:
        print("no order book samples yet (the shadow_costs agent records them every cycle)")
        return 1
    out = report(load_closed(_archive_path()), costs)
    print(f"closed Paper trades re-priced: {out['trades_priced']} (no book sample for the coin: {out['trades_unpriced']})")
    print(f"Paper net: {out['paper_net']} USDT   Shadow net (estimate, with spread + depth): {out['shadow_net_estimate']} USDT")
    print(f"book cost Paper does not pay: {out['book_cost']} USDT")
    for sym, c in sorted(costs.items()):
        print(f"  {sym:10} buy {c['buy_bps']:6.2f} bps  sell {c['sell_bps']:6.2f} bps  ({c['samples']} samples)")
    print("Estimate only: a book snapshot is not the exact fill. Nothing in Paper or the gates was changed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
