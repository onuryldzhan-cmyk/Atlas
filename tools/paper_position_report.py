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
import re
import sys
import urllib.request
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any

from core.application import (
    EXECUTION_AUDIT_EVENT_FILE,
    EXECUTION_FINANCIAL_STATE_FILE,
    resolve_state_directory,
)

TICKER_URL = "https://api.binance.com/api/v3/ticker/price?symbol={symbol}"


# Phase-2 F1: canonical trade attribution. A position's id is minted from its
# opening request alone (core.execution_portfolio_foundation.mint_long_position_id:
# ``long:<symbol>:<sha256(request_id)>``) and every RISK_APPROVED audit event
# carries that request_id as its aggregate_id, so the entry approval of a
# position is found by exact identity, never by time. Only a record whose
# position_id predates that minting (or is missing) may use the LEGACY
# timestamp fallback, and only when it is unambiguous; anything else is
# UNATTRIBUTED - the nearest record in time is never chosen.
UNATTRIBUTED = "UNATTRIBUTED"
EXACT = "EXACT"
LEGACY_TIMESTAMP = "LEGACY_TIMESTAMP"
LEGACY_WINDOW = timedelta(minutes=3)
_CANONICAL_POSITION_ID = re.compile(r"^long:(?P<symbol>[A-Za-z0-9._-]+):[0-9a-f]{64}$")


def is_canonical_position_id(position_id: Any) -> bool:
    """True when ``position_id`` was minted from an opening request_id (exact attribution possible)."""

    return isinstance(position_id, str) and _CANONICAL_POSITION_ID.fullmatch(position_id) is not None


def opened_by(position_id: Any, request_id: Any) -> bool:
    """Exactly: did the request ``request_id`` open the position ``position_id``?"""

    from core.execution_portfolio_foundation import mint_long_position_id

    match = _CANONICAL_POSITION_ID.fullmatch(position_id) if isinstance(position_id, str) else None
    if match is None or not isinstance(request_id, str) or not request_id:
        return False
    try:
        return mint_long_position_id(match.group("symbol"), request_id) == position_id
    except ValueError:
        return False


def _when(value: Any) -> datetime | None:
    try:
        moment = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    return moment if moment.tzinfo else moment.replace(tzinfo=timezone.utc)


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
            if not isinstance(event, dict) or event.get("event_type") != "RISK_APPROVED":
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
                "risk_approval_event_id": event.get("event_id"),
            })
    return found


_APPROVAL_FACTS = ("experiment_id", "confidence", "risk")


def entry_approval(approvals: list[dict], opened_at: str | None, position_id: str | None = None) -> dict | None:
    """The RISK_APPROVED BUY that admitted a position, or None (UNATTRIBUTED).

    Canonical: the approval whose request_id minted ``position_id`` (``attribution``
    = EXACT). If such a position has no matching approval, it is UNATTRIBUTED -
    there is no fallback to time for a record that carries the canonical chain.

    LEGACY (explicit, ``attribution`` = LEGACY_TIMESTAMP): only for a record
    without a canonical position_id, and only when exactly one approval lies
    within LEGACY_WINDOW of ``opened_at`` (the approval can be written a few
    milliseconds after the fill). Two candidates, or none, is UNATTRIBUTED:
    the closer one is never picked.
    """

    if is_canonical_position_id(position_id):
        exact = [a for a in approvals if opened_by(position_id, a.get("request_id"))]
        if not exact:
            return None
        # The same request replayed may be audited twice; it is still one
        # approval only if the recorded facts agree.
        if any(tuple(a.get(k) for k in _APPROVAL_FACTS) != tuple(exact[0].get(k) for k in _APPROVAL_FACTS)
               for a in exact[1:]):
            return None
        return {**exact[0], "attribution": EXACT}

    opened = _when(opened_at) if opened_at else None
    if opened is None:
        return None
    candidates = []
    for approval in approvals:
        moment = _when(approval.get("timestamp"))
        if moment is not None and abs(moment - opened) <= LEGACY_WINDOW:
            candidates.append(approval)
    if len(candidates) != 1:
        return None
    return {**candidates[0], "attribution": LEGACY_TIMESTAMP}


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
    total_pnl_open = Decimal("0")
    priced_all = True

    for symbol in sorted(positions):
        position = positions[symbol]
        base = Decimal(str(position["base_quantity"]))
        cost = Decimal(str(position["cost_quote"]))
        entry = Decimal(str(position["average_entry_price"]))
        approval = entry_approval(approvals.get(symbol, []), position.get("opened_at"), position.get("position_id"))
        price = None if args.no_price else live_price(symbol)

        short = position.get("side") == "SHORT"   # Task 026
        print(f"{symbol}{'  (SHORT)' if short else ''}")
        print(f"  opened_at:   {position.get('opened_at')}")
        print(f"  quantity:    {base}")
        print(f"  entry price: {entry}")
        print(f"  cost:        {cost}")
        if approval:
            print(f"  admitted:    confidence={approval.get('confidence')} risk={approval.get('risk')} "
                  f"experiment={approval.get('experiment_id') or 'none (policy floor)'} "
                  f"[{approval['attribution']}]")
        else:
            print(f"  admitted:    {UNATTRIBUTED} - no RISK_APPROVED BUY matches this position exactly")

        total_cost += cost
        if price is None:
            priced_all = False
            print("  price now:   unavailable")
        else:
            value = base * price
            pnl = cost - value if short else value - cost
            pct = (pnl / cost * 100) if cost else Decimal("0")
            total_value += value
            total_pnl_open += pnl
            print(f"  price now:   {price}")
            print(f"  P&L:         {pnl:.2f} ({pct:.2f}%)  [fees on exit not included]")
        print()

    print(f"total cost: {total_cost:.2f}")
    if positions and priced_all:
        total_pnl = total_pnl_open   # Task 026: a short's P&L is cost - value
        print(f"total value now: {total_value:.2f}  unrealized P&L: {total_pnl:.2f}")
    elif positions:
        print("total P&L: not shown - at least one price was unavailable")
    return 0


if __name__ == "__main__":
    sys.exit(main())
