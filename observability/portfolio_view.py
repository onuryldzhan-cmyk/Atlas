"""Live PAPER portfolio view: capital and P/L from the durable book and real prices.

Inputs are already-read data: the durable book's ``snapshot()`` (cash,
committed cost, fees, realized P/L, open positions) and the latest real
market price per symbol from MarketLoop's last decisions (Binance candle
closes). Nothing is estimated or filled in:

* starting capital is derived exactly from the book's own identity
  (cash + committed + fees - realized gross = initial cash; every open debits
  notional + fee, every close credits notional - fee);
* a position without a current price is shown with its price marked missing,
  and totals that would need it are reported as incomplete, never guessed;
* prices older than ``STALE_AFTER_S`` are flagged stale.

Owner request 2026-09-29 ("sermaye ve kar zarar oranını gerçek zamanlı sahte
olmayan verilerle görmek istiyorum"), registry v5.40. Pure: no I/O.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from typing import Any

STALE_AFTER_S = 120
Q = Decimal("0.01")


def _d(value: Any) -> Decimal | None:
    try:
        out = Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        return None
    return out if out.is_finite() else None


def _age_seconds(stamp: Any, now: datetime) -> float | None:
    if not stamp:
        return None
    try:
        when = datetime.fromisoformat(str(stamp).replace("Z", "+00:00"))
    except ValueError:
        return None
    if when.tzinfo is None:
        when = when.replace(tzinfo=UTC)
    return max(0.0, (now - when).total_seconds())


def _fmt(value: Decimal | None, places: Decimal = Q) -> str | None:
    return None if value is None else str(value.quantize(places))


def build(snapshot: dict[str, Any], prices: dict[str, Any], price_time: Any,
          now: datetime | None = None) -> dict[str, Any]:
    now = now or datetime.now(UTC)
    cash, fees = _d(snapshot.get("cash")), _d(snapshot.get("fees"))
    committed, realized_gross = _d(snapshot.get("committed_capital")), _d(snapshot.get("realized_gross_pnl"))
    realized_net = _d(snapshot.get("realized_net_pnl"))
    if None in (cash, fees, committed, realized_gross, realized_net):
        return {"available": False, "reason": "PORTFOLIO_SNAPSHOT_INCOMPLETE"}
    starting = cash + committed + fees - realized_gross
    age = _age_seconds(price_time, now)
    stale = age is None or age > STALE_AFTER_S

    positions, market_value, unrealized, missing = [], Decimal("0"), Decimal("0"), []
    for symbol, pos in sorted((snapshot.get("positions") or {}).items()):
        qty, cost = _d(pos.get("base_quantity")), _d(pos.get("cost_quote"))
        avg = _d(pos.get("average_entry_price"))
        price = _d(prices.get(symbol))
        row = {"symbol": symbol, "quantity": str(qty) if qty is not None else None,
               "average_entry_price": str(avg) if avg is not None else None,
               "cost": _fmt(cost), "opened_at": pos.get("opened_at")}
        if qty is None or cost is None or price is None or price <= 0:
            missing.append(symbol)
            row.update(price=None, market_value=None, unrealized_pnl=None, unrealized_pct=None)
        else:
            value = qty * price
            pnl = value - cost
            market_value += value
            unrealized += pnl
            row.update(price=str(price), market_value=_fmt(value), unrealized_pnl=_fmt(pnl),
                       unrealized_pct=_fmt(pnl / cost * 100) if cost else None)
        positions.append(row)

    complete = not missing
    equity = cash + market_value if complete else None
    total_pnl = equity - starting if equity is not None else None
    return {
        "available": True,
        "mode": "PAPER",
        "live_authority": "DENIED",
        "source": "durable book (execution_portfolio_foundation) + MarketLoop real candle-close prices",
        "starting_capital": _fmt(starting),
        "cash": _fmt(cash),
        "available_capital": _fmt(_d(snapshot.get("available_capital"))),
        "invested_cost": _fmt(committed),
        "market_value": _fmt(market_value) if complete else None,
        "equity": _fmt(equity),
        "realized_net_pnl": _fmt(realized_net),
        "unrealized_pnl": _fmt(unrealized) if complete else None,
        "total_pnl": _fmt(total_pnl),
        "total_pnl_pct": _fmt(total_pnl / starting * 100) if total_pnl is not None and starting > 0 else None,
        "fees": _fmt(fees),
        "exposure_pct": _fmt(market_value / equity * 100) if complete and equity else None,
        "positions": positions,
        "prices_as_of": str(price_time) if price_time else None,
        "price_age_seconds": round(age, 1) if age is not None else None,
        "prices_stale": stale,
        "incomplete_reason": f"no current price for {', '.join(missing)}" if missing else None,
    }
