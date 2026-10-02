"""
Order book fill provider (Shadow stage S2, owner approval 2026-10-02).

PAPER fills at the last price plus a fixed adverse slippage. In the Shadow
fill model (``ATLAS_FILL_MODEL=BOOK``) a PAPER fill is instead priced against
the live public order book: a BUY walks the asks, a SELL walks the bids, for
the order's quote notional, and the fill is the volume-weighted price.
Ideas: NautilusTrader's sandbox (live data, simulated matching, nothing sent
to the venue) and hummingbot paper trading against the live book.

Fail-closed contract
--------------------
``__call__`` never raises and never invents a price. A network error,
malformed or crossed book, non-positive level, or a book too thin for the
notional returns ``None``; the execution manager then REJECTS the order. It
never falls back to the last price.

Security boundary
-----------------
One unauthenticated HTTPS GET to a fixed public endpoint per fill; no key,
no secret, no order is ever sent. Layer L2 (``atlas_finance/*``).
"""

from __future__ import annotations

import json
import urllib.request
from decimal import Decimal, InvalidOperation
from typing import Any, Callable, Final

DEPTH_URL: Final[str] = "https://api.binance.com/api/v3/depth?symbol={symbol}&limit=100"
MAX_BODY_BYTES: Final[int] = 2_000_000
TIMEOUT_SECONDS: Final[float] = 5.0


def _fetch_depth(symbol: str) -> dict:
    if not symbol.isalnum():
        raise ValueError("symbol must be alphanumeric")
    with urllib.request.urlopen(DEPTH_URL.format(symbol=symbol), timeout=TIMEOUT_SECONDS) as response:
        body = response.read(MAX_BODY_BYTES + 1)
    if len(body) > MAX_BODY_BYTES:
        raise ValueError("depth body too large")
    return json.loads(body)


def walk_vwap(levels: Any, notional: Decimal) -> Decimal | None:
    """Volume-weighted price of spending ``notional`` quote along ``levels``; None when thin or malformed."""
    if not isinstance(notional, Decimal) or not notional.is_finite() or notional <= 0:
        return None
    try:
        left, quantity = notional, Decimal(0)
        for price_s, size_s in levels:
            price, size = Decimal(str(price_s)), Decimal(str(size_s))
            if not price.is_finite() or not size.is_finite() or price <= 0 or size <= 0:
                return None
            take = min(left, price * size)
            quantity += take / price
            left -= take
            if left <= 0:
                return notional / quantity
    except (TypeError, ValueError, InvalidOperation, ArithmeticError):
        return None
    return None


def book_fill_price(depth: Any, side: str, notional: Decimal) -> Decimal | None:
    """BUY walks the asks, SELL walks the bids; a crossed or empty book gives None."""
    try:
        bids, asks = depth["bids"], depth["asks"]
        best_bid, best_ask = Decimal(str(bids[0][0])), Decimal(str(asks[0][0]))
    except (KeyError, IndexError, TypeError, ValueError, InvalidOperation):
        return None
    if not best_bid.is_finite() or not best_ask.is_finite() or best_bid <= 0 or best_ask <= best_bid:
        return None
    if side == "BUY":
        return walk_vwap(asks, notional)
    if side == "SELL":
        return walk_vwap(bids, notional)
    return None


class OrderBookFillProvider:
    """Callable ``(symbol, side, quote_notional) -> Decimal | None``; never raises."""

    def __init__(self, fetch: Callable[[str], dict] = _fetch_depth) -> None:
        self._fetch = fetch

    def __call__(self, symbol: str, side: str, notional: Decimal) -> Decimal | None:
        try:
            return book_fill_price(self._fetch(str(symbol)), str(side).upper(), notional)
        except Exception:  # fail closed: any failure is "no price", the order is rejected
            return None
