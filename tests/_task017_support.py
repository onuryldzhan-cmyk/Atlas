"""Deterministic synthetic fixtures for the Task 017 unified-analysis tests (no network, no clock)."""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace
from typing import Any, Callable

from core.market_cycle import INTERVAL_MS

from tools.unified_analysis.market_intelligence import MarketInputs

CUTOFF = 1_760_000_000_000 // 3_600_000 * 3_600_000   # an exact 1h boundary
AS_OF = datetime.fromtimestamp(CUTOFF / 1000, UTC)


def rows(tf: str, n: int, cutoff: int = CUTOFF, drift: float = 0.002, vol: float = 0.004, start: float = 100.0,
         quote_scale: float = 100_000.0, wiggle: float = 1.7) -> list[list[Any]]:
    """n closed kline rows ending at the last boundary before ``cutoff``."""
    step = INTERVAL_MS[tf]
    out, price = [], start
    for i in range(n):
        open_ms = cutoff - (n - i) * step
        close = price * (1 + drift + vol * math.sin(i * wiggle))
        high, low = max(price, close) * 1.002, min(price, close) * 0.998
        out.append([open_ms, price, high, low, close, 1000.0, open_ms + step - 1, 1000.0 * close * quote_scale / 100])
        price = close
    return out


def klines(drift: float = 0.002, cutoff: int = CUTOFF, **kw: Any) -> dict[str, list[list[Any]]]:
    return {"1h": rows("1h", 500, cutoff, drift, **kw), "4h": rows("4h", 200, cutoff, drift * 2, **kw),
            "1d": rows("1d", 200, cutoff, drift * 4, **kw)}


def context(fng: int = 50, ten_year_bp: int = 3, funding: str = "0.0001", band: str = "NEUTRAL") -> dict[str, Any]:
    return {"funding": {"available": True, "rate": funding, "band": band, "reason": "OK"},
            "fear_greed": SimpleNamespace(available=True, value=fng, observed_at=AS_OF - timedelta(hours=3), reason="OK"),
            "treasury": SimpleNamespace(available=True, observed_date=(AS_OF - timedelta(days=2)).date(),
                                        ten_year_change_bp=ten_year_bp, curve_spread_bp=40, reason="OK")}


def inputs(drift: float = 0.002, *, source: str = "binance_spot_klines", with_context: bool = True,
           k: dict | None = None, symbol: str = "BTCUSDT", **ctx: Any) -> MarketInputs:
    extra = context(**ctx) if with_context else {}
    return MarketInputs(symbol, CUTOFF, AS_OF, source, k if k is not None else klines(drift), **extra)


@dataclass
class FakeAsk:
    """Scripted model: answers by the schema it is asked with; records every call."""

    narrative: Any = None
    prosecutor: Any = None
    juror: Callable[[str], Any] | Any = None
    calls: list[tuple[str, str]] = field(default_factory=list)

    def __call__(self, system: str, prompt: str, schema: dict) -> Any:
        props = schema.get("properties", {})
        if "findings" in props:
            kind, answer = "narrative", self.narrative
        elif "charges" in props:
            kind, answer = "prosecutor", self.prosecutor
        else:
            kind, answer = "juror", self.juror(system) if callable(self.juror) else self.juror
        self.calls.append((kind, system))
        if answer is None:
            return SimpleNamespace(status="ABSTAIN", data=None, reason="UNAVAILABLE (scripted)", cost_usd=Decimal("0"))
        return SimpleNamespace(status="OK", data=answer, reason="", cost_usd=Decimal("0.01"))
