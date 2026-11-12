"""Deterministic indicator implementations: the single trusted source the specialists AND verification use.

Every function reads closed bars only (oldest first) and returns None when the input cannot support the value
(too short, non-finite, non-positive): an indicator is never guessed. EMA is core.market_cycle's, so the regime
classifier and these indicators agree on it.
"""

from __future__ import annotations

import math
from typing import Sequence

from core.market_cycle import ema as _ema

RSI_PERIOD = 14
ATR_PERIOD = 14
EMA_FAST = 20
EMA_SLOW = 50
RETURN_BARS = 20
SWING_BARS = 24


def _finite(values: Sequence[float]) -> bool:
    return all(isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v) for v in values)


def ema_last(closes: Sequence[float], span: int) -> float | None:
    if len(closes) < span or not _finite(closes):
        return None
    value = _ema(list(closes), span)[-1]
    return value if math.isfinite(value) else None


def rsi(closes: Sequence[float], period: int = RSI_PERIOD) -> float | None:
    """Wilder's RSI of the last close. A series with no movement at all is 50 (neither side)."""
    if len(closes) < period + 1 or not _finite(closes):
        return None
    deltas = [b - a for a, b in zip(closes, closes[1:])]
    gain = sum(max(d, 0.0) for d in deltas[:period]) / period
    loss = sum(max(-d, 0.0) for d in deltas[:period]) / period
    for d in deltas[period:]:
        gain = (gain * (period - 1) + max(d, 0.0)) / period
        loss = (loss * (period - 1) + max(-d, 0.0)) / period
    if gain == 0 and loss == 0:
        return 50.0
    if loss == 0:
        return 100.0
    return 100.0 - 100.0 / (1.0 + gain / loss)


def atr(highs: Sequence[float], lows: Sequence[float], closes: Sequence[float], period: int = ATR_PERIOD) -> float | None:
    """Wilder's average true range of the last bar."""
    n = len(closes)
    if n < period + 1 or len(highs) != n or len(lows) != n or not _finite([*highs, *lows, *closes]):
        return None
    trs = [max(h - l, abs(h - pc), abs(l - pc)) for h, l, pc in zip(highs[1:], lows[1:], closes[:-1])]
    value = sum(trs[:period]) / period
    for tr in trs[period:]:
        value = (value * (period - 1) + tr) / period
    return value


def pct_change(closes: Sequence[float], bars: int = RETURN_BARS) -> float | None:
    if len(closes) < bars + 1 or not _finite(closes) or closes[-1 - bars] <= 0:
        return None
    return closes[-1] / closes[-1 - bars] - 1.0


def swing_low(lows: Sequence[float], bars: int = SWING_BARS) -> float | None:
    if len(lows) < bars or not _finite(lows[-bars:]):
        return None
    return min(lows[-bars:])


def swing_high(highs: Sequence[float], bars: int = SWING_BARS) -> float | None:
    if len(highs) < bars or not _finite(highs[-bars:]):
        return None
    return max(highs[-bars:])


def window_sum(values: Sequence[float], bars: int) -> float | None:
    if len(values) < bars or not _finite(values[-bars:]):
        return None
    return float(sum(values[-bars:]))
