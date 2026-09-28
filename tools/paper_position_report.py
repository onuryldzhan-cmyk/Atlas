"""Read-only report of open paper positions and how each was admitted.

For every position in the durable financial state it prints the entry,
the size, and - from the audit log - the confidence and the experiment
(e.g. EXP-001) under which the BUY was risk-approved. With a live price
(Binance public ticker, no credentials) it adds unrealized P&L.

It never writes: the state and audit files are only read, no lock is
taken, and it is safe to run while Atlas is running.

Usage:
  python -m tools.paper_position_report [--no-price]
"""

from __future__ import annotations

import argparse
import json
import sys
import urllib.request
from decimal import Decimal
from pathlib import Path

from core.application import (
    EXECUTION_AUDIT_EVENT_FILE,
    EXECUTION_FINANCIAL_STATE_FILE,
    resolve_state_directory,
)

TICKER_URL = "https://api.binance.com/api/v3/ticker/price?symbol={symbol}"


def approvals_by_symbol(audit_path: Path) -> dict[str, list[dict]]:
    """Every RISK_APPROVED BUY per symbol, oldest first."""

    found: dict[str, list[dict]] = {}
    if not audit_path.exists():
        return found

    with audit_path.open("r", encoding="utf-8") as file:
        for line in file:
            try:
                event = json.loads(line)
            except ValueError:
                continue
            if event.get("event_type") != "RISK_APPROVED":
                continue
            aggregate = str(event.get("aggregate_id", ""))
            symbol, _, rest = aggregate.partition("|")
            if not rest.endswith("|BUY"):
                continue
            payload = event.get("payload") or {}
            details = payload.get("details") or {}
            found.setdefault(symbol, []).append({
                "timestamp": event.get("timestamp"),
                "experiment_id": details.get("experiment_id"),
                "confidence": payload.get("confidence"),
                "risk": payload.get("risk"),
                "request_id": aggregate,
            })
    return found


def entry_approval(approvals: list[dict], opened_at: str | None) -> dict | None:
    """The latest approval at or before the position was opened."""

    if not approvals:
        return None
    if not opened_at:
        return approvals[-1]
    before = [a for a in approvals if str(a.get("timestamp") or "") <= opened_at]
    return (before or approvals)[-1]


def live_price(symbol: str) -> Decimal | None:
    try:
        with urllib.request.urlopen(TICKER_URL.format(symbol=symbol), timeout=5) as response:
            return Decimal(json.loads(response.read())["price"])
    except Exception:
        return None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--no-price", action="store_true", help="skip the live price lookup")
    args = parser.parse_args(argv)

    root = resolve_state_directory()
    state = json.loads((root / EXECUTION_FINANCIAL_STATE_FILE).read_text(encoding="utf-8"))
    positions = state.get("positions") or {}
    approvals = approvals_by_symbol(root / EXECUTION_AUDIT_EVENT_FILE)

    print(f"state root: {root}")
    print(f"cash: {state.get('cash')}")
    print(f"open positions: {len(positions)}")
    print()

    total_cost = Decimal("0")
    total_value = Decimal("0")
    priced_all = True

    for symbol in sorted(positions):
        position = positions[symbol]
        base = Decimal(str(position["base_quantity"]))
        cost = Decimal(str(position["cost_quote"]))
        entry = Decimal(str(position["average_entry_price"]))
        approval = entry_approval(approvals.get(symbol, []), position.get("opened_at"))
        price = None if args.no_price else live_price(symbol)

        print(f"{symbol}")
        print(f"  opened_at:   {position.get('opened_at')}")
        print(f"  quantity:    {base}")
        print(f"  entry price: {entry}")
        print(f"  cost:        {cost}")
        if approval:
            print(f"  admitted:    confidence={approval.get('confidence')} risk={approval.get('risk')} "
                  f"experiment={approval.get('experiment_id') or 'none (policy floor)'}")
        else:
            print("  admitted:    UNKNOWN - no RISK_APPROVED BUY found in the audit log")

        total_cost += cost
        if price is None:
            priced_all = False
            print("  price now:   unavailable")
        else:
            value = base * price
            pnl = value - cost
            pct = (pnl / cost * 100) if cost else Decimal("0")
            total_value += value
            print(f"  price now:   {price}")
            print(f"  P&L:         {pnl:.2f} ({pct:.2f}%)  [fees on exit not included]")
        print()

    print(f"total cost: {total_cost:.2f}")
    if positions and priced_all:
        total_pnl = total_value - total_cost
        print(f"total value now: {total_value:.2f}  unrealized P&L: {total_pnl:.2f}")
    elif positions:
        print("total P&L: not shown - at least one price was unavailable")
    return 0


if __name__ == "__main__":
    sys.exit(main())
