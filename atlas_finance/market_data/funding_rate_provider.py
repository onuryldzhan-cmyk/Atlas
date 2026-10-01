"""Binance USD-M perpetual funding rate as sentiment evidence (owner choice 2026-10-01, design C).

proposals/2026-10-01_sentiment_second_source_and_exp002_DESIGN.md

Public endpoint, no key: https://fapi.binance.com/fapi/v1/premiumIndex
(registered in config/data_sources.json). One request returns every perpetual;
the result is cached for CACHE_S, so the market loop's per-symbol lookups never
hit the network every cycle.

Fail-closed: any transport error, malformed body, non-finite value or a cache
older than STALE_S makes the rate for every symbol unavailable (None). A
missing rate never becomes 0 and never becomes a vote.
"""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from decimal import Decimal, InvalidOperation
from typing import Any, Callable

ENDPOINT = "https://fapi.binance.com/fapi/v1/premiumIndex"
CACHE_S = 600
STALE_S = 1800
MAX_RESPONSE_BYTES = 2_000_000
# Neutral band fixed in advance: |funding per 8h| below 0.03 % carries no directional read.
CROWDED_THRESHOLD = Decimal("0.0003")
BAND_CROWDED_LONG = "CROWDED_LONG"
BAND_CROWDED_SHORT = "CROWDED_SHORT"
BAND_NEUTRAL = "NEUTRAL"


def classify(rate: Decimal) -> str:
    if rate >= CROWDED_THRESHOLD:
        return BAND_CROWDED_LONG
    if rate <= -CROWDED_THRESHOLD:
        return BAND_CROWDED_SHORT
    return BAND_NEUTRAL


def parse(body: bytes) -> dict[str, Decimal]:
    """symbol -> lastFundingRate. Raises ValueError on anything malformed."""
    data = json.loads(body)
    if not isinstance(data, list):
        raise ValueError("premiumIndex body must be a list")
    out: dict[str, Decimal] = {}
    for row in data:
        if not isinstance(row, dict):
            raise ValueError("premiumIndex row must be an object")
        symbol, raw = row.get("symbol"), row.get("lastFundingRate")
        if not isinstance(symbol, str) or not isinstance(raw, str) or not raw.strip():
            continue  # delivery contracts carry no funding rate
        try:
            rate = Decimal(raw)
        except InvalidOperation as exc:
            raise ValueError(f"bad funding rate for {symbol}") from exc
        if not rate.is_finite() or abs(rate) > Decimal("0.05"):
            raise ValueError(f"implausible funding rate for {symbol}: {raw}")
        out[symbol] = rate
    return out


def _urllib_transport(url: str, timeout: float) -> bytes:
    request = urllib.request.Request(url, headers={"Accept": "application/json",
                                                   "User-Agent": "AtlasAI-FundingRateProvider/1.0"}, method="GET")
    with urllib.request.urlopen(request, timeout=timeout) as response:
        if getattr(response, "status", None) != 200:
            raise urllib.error.URLError(f"HTTP {getattr(response, 'status', None)}")
        body = response.read(MAX_RESPONSE_BYTES + 1)
    if len(body) > MAX_RESPONSE_BYTES:
        raise ValueError("response too large")
    return body


class FundingRateProvider:
    def __init__(self, transport: Callable[[str, float], bytes] | None = None,
                 clock: Callable[[], float] | None = None, timeout: float = 5.0) -> None:
        self._transport = transport or _urllib_transport
        self._clock = clock or time.time
        self._timeout = timeout
        self._rates: dict[str, Decimal] = {}
        self._fetched_at: float | None = None
        self._last_attempt: float | None = None
        self.last_error: str | None = None

    def rate(self, symbol: str) -> dict[str, Any]:
        """{'available': bool, 'rate': str|None, 'band': str|None, 'reason': str}. Never raises."""
        now = self._clock()
        try:
            if self._last_attempt is None or now - self._last_attempt >= CACHE_S:
                self._last_attempt = now
                self._rates = parse(self._transport(ENDPOINT, self._timeout))
                self._fetched_at = now
                self.last_error = None
        except Exception as exc:  # fail closed; keep the last good cache only while it is fresh
            self.last_error = type(exc).__name__
        if self._fetched_at is None or now - self._fetched_at > STALE_S:
            return {"available": False, "rate": None, "band": None, "reason": self.last_error or "STALE"}
        rate = self._rates.get(str(symbol).upper())
        if rate is None:
            return {"available": False, "rate": None, "band": None, "reason": "NO_PERPETUAL"}
        return {"available": True, "rate": str(rate), "band": classify(rate), "reason": "OK"}
