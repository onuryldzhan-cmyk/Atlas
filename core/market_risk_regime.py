"""
============================================================
ATLAS MARKET RISK REGIME PROVIDER v1.0.0
============================================================

Project Atlas AI

Realized-volatility regime classifier for the AgentFusion ``risk`` agent
(``market_risk`` evidence slot), authorized by registry v4.79
(GRANT-BACKLOG001-MACRO-RISK-IMPLEMENTATION).

This is a fusion-input evidence producer only. It is not, and must never
become, a risk gate: it has no connection to ``core/risk_engine.py``, the
risk_check path, capital reservation, or ExecutionManager. It reads the
closed candles MarketLoop has already fetched for the cycle and returns
plain values; it performs no I/O and contacts no data source.

Method (owner decision: three-zone regime split at ~p20 / ~p80)
---------------------------------------------------------------
1. One-period log returns ``r_i = ln(close_i / close_{i-1})`` over the
   closed candles, oldest to newest.
2. Realized volatility of a window is the root mean square of its
   ``WINDOW_RETURNS`` returns (the standard zero-mean realized-volatility
   estimator; no annualization - only relative ranking is used).
3. The current value is the window ending on the newest return. The
   reference distribution is every earlier overlapping window in the same
   candle set (the trailing history), so the current window is never
   compared against itself.
4. p20 / p80 are the 20th / 80th percentiles of that reference set
   (``statistics.quantiles(..., n=5, method="inclusive")``, i.e. linear
   interpolation between order statistics).
5. current > p80 -> HIGH; current < p20 -> LOW; otherwise NEUTRAL. Both
   comparisons are strict, so a flat market (every window zero) is NEUTRAL.

The regime is relative to the trailing window of candles MarketLoop fetches
(200 one-minute candles, i.e. roughly the last three hours), not to a
long-run history. That is a property of the owner's "no new data source"
decision; it is recorded, with the measured base rate of each zone, in this
package's registry result record (v4.80).

Fail-closed contract
--------------------
``assess()`` never raises and never invents a number. Too few candles for a
stable percentile, a non-finite or non-positive close, a non-integer or
non-increasing open time, unevenly spaced candles (a gap), or any unexpected
exception yields ``available=False`` with no values and a reason code.

Architecture
------------
Pure calculator, stdlib only. Classified L3 by the generic ``core/*`` rule,
alongside ``core/technical_analyzer.py``, which consumes the same candles.
Only plain values derived from it ever reach WorldAnalysisEngine (L4).

============================================================
"""

from __future__ import annotations

import logging
import math
import statistics

from dataclasses import dataclass
from typing import Any, Final


logger = logging.getLogger(
    "AtlasAI.MarketRiskRegime"
)


# Returns per realized-volatility window (30 one-minute returns).
WINDOW_RETURNS: Final[int] = 30

# Minimum number of trailing reference windows before a percentile is
# considered stable enough to vote on. With WINDOW_RETURNS=30 this needs at
# least 131 closed candles; MarketLoop fetches 200.
MIN_REFERENCE_WINDOWS: Final[int] = 100

MIN_CLOSED_CANDLES: Final[int] = WINDOW_RETURNS + MIN_REFERENCE_WINDOWS + 1

REGIME_HIGH: Final[str] = "HIGH"
REGIME_LOW: Final[str] = "LOW"
REGIME_NEUTRAL: Final[str] = "NEUTRAL"

REASON_OK: Final[str] = "OK"
REASON_INSUFFICIENT_HISTORY: Final[str] = "INSUFFICIENT_HISTORY"
REASON_MALFORMED_CANDLES: Final[str] = "MALFORMED_CANDLES"
REASON_CANDLE_GAP: Final[str] = "CANDLE_GAP"
REASON_UNEXPECTED_ERROR: Final[str] = "UNEXPECTED_ERROR"


class _AssessmentError(ValueError):
    def __init__(self, reason: str, detail: str) -> None:
        super().__init__(f"{reason}: {detail}")
        self.reason = reason


@dataclass(frozen=True)
class MarketRiskRegimeReading:
    """One assessment. Every value is None whenever ``available`` is False."""

    available: bool
    regime: str | None
    realized_volatility: float | None
    p20: float | None
    p80: float | None
    reference_windows: int | None
    reason: str

    @classmethod
    def unavailable(cls, reason: str) -> MarketRiskRegimeReading:
        return cls(
            available=False,
            regime=None,
            realized_volatility=None,
            p20=None,
            p80=None,
            reference_windows=None,
            reason=reason,
        )


# ---------------------------------------------------------------------------
# Pure helpers
# ---------------------------------------------------------------------------


def classify_volatility_regime(current: Any, p20: Any, p80: Any) -> str:
    """Three-zone split. Raises ValueError on non-finite or unordered input."""

    values = (current, p20, p80)
    if any(
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not math.isfinite(value)
        or value < 0
        for value in values
    ):
        raise ValueError("volatility inputs must be finite, non-negative numbers")

    if p20 > p80:
        raise ValueError("p20 must not exceed p80")

    if current > p80:
        return REGIME_HIGH

    if current < p20:
        return REGIME_LOW

    return REGIME_NEUTRAL


def _closes(candles: Any) -> list[float]:
    if not isinstance(candles, (list, tuple)):
        raise _AssessmentError(REASON_MALFORMED_CANDLES, "candles is not a list")

    if len(candles) < MIN_CLOSED_CANDLES:
        raise _AssessmentError(
            REASON_INSUFFICIENT_HISTORY,
            f"{len(candles)} closed candles, {MIN_CLOSED_CANDLES} required",
        )

    closes: list[float] = []
    open_times: list[int] = []

    for candle in candles:
        if not isinstance(candle, dict):
            raise _AssessmentError(REASON_MALFORMED_CANDLES, "candle is not a dict")

        close = candle.get("close")
        open_time = candle.get("open_time")

        if (
            isinstance(close, bool)
            or not isinstance(close, (int, float))
            or not math.isfinite(close)
            or close <= 0
        ):
            raise _AssessmentError(REASON_MALFORMED_CANDLES, "close is not a positive number")

        if type(open_time) is not int:
            raise _AssessmentError(REASON_MALFORMED_CANDLES, "open_time is not an int")

        closes.append(float(close))
        open_times.append(open_time)

    spacing = open_times[1] - open_times[0]
    if spacing <= 0:
        raise _AssessmentError(REASON_MALFORMED_CANDLES, "open_time is not increasing")

    for earlier, later in zip(open_times, open_times[1:]):
        step = later - earlier
        if step <= 0:
            raise _AssessmentError(REASON_MALFORMED_CANDLES, "open_time is not increasing")
        if step != spacing:
            raise _AssessmentError(REASON_CANDLE_GAP, "candles are not evenly spaced")

    return closes


def _rolling_realized_volatility(closes: list[float]) -> list[float]:
    returns = [
        math.log(later / earlier)
        for earlier, later in zip(closes, closes[1:])
    ]

    squares = [value * value for value in returns]
    window_sum = math.fsum(squares[:WINDOW_RETURNS])
    volatilities = [math.sqrt(window_sum / WINDOW_RETURNS)]

    # Recomputed with fsum per window rather than a running sum, so no
    # floating-point drift can accumulate across ~170 windows.
    for end in range(WINDOW_RETURNS + 1, len(squares) + 1):
        window_sum = math.fsum(squares[end - WINDOW_RETURNS:end])
        volatilities.append(math.sqrt(window_sum / WINDOW_RETURNS))

    return volatilities


# ---------------------------------------------------------------------------
# Provider
# ---------------------------------------------------------------------------


class MarketRiskRegimeProvider:
    """Stateless realized-volatility regime classifier. Performs no I/O."""

    VERSION = "1.0.0"

    def assess(self, closed_candles: Any) -> MarketRiskRegimeReading:
        """Classify the newest window's regime. Never raises."""

        try:
            closes = _closes(closed_candles)
            volatilities = _rolling_realized_volatility(closes)

            current = volatilities[-1]
            reference = volatilities[:-1]

            if len(reference) < MIN_REFERENCE_WINDOWS:
                raise _AssessmentError(
                    REASON_INSUFFICIENT_HISTORY,
                    f"{len(reference)} reference windows, "
                    f"{MIN_REFERENCE_WINDOWS} required",
                )

            quintiles = statistics.quantiles(reference, n=5, method="inclusive")
            p20, p80 = quintiles[0], quintiles[3]

            regime = classify_volatility_regime(current, p20, p80)
        except _AssessmentError as error:
            logger.debug("Market risk regime unavailable: %s", error)
            return MarketRiskRegimeReading.unavailable(error.reason)
        except Exception as error:
            logger.warning(
                "Market risk regime failed unexpectedly: %s",
                type(error).__name__,
            )
            return MarketRiskRegimeReading.unavailable(REASON_UNEXPECTED_ERROR)

        return MarketRiskRegimeReading(
            available=True,
            regime=regime,
            realized_volatility=current,
            p20=p20,
            p80=p80,
            reference_windows=len(reference),
            reason=REASON_OK,
        )
