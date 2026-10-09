"""Fast-fail screening of candidate hypotheses on historical data (Task 005).

GRANT-TASK-005-HYPOTHESIS-GENERATION-SCREENING-RESEARCH-ONLY (registry v5.88).
Screening runs BEFORE registration, on historical data that ends before the
registration (owner decision 2026-10-09): it decides which generated candidates
are worth registering; the sealed window each registered hypothesis is later
tested on lies wholly after the registration and is never read here. A
screening result is exploratory, never evidence.

Stages, in fast-fail order (a candidate passes only when every stage PASSes):

1. ``integrity``     -- every candle is a well-formed 1-minute kline
                        (``validate_candle``: twelve columns, integer times,
                        finite positive prices with low <= open, close <= high,
                        non-negative volumes and trade count);
2. ``completeness``  -- exactly the screening span, one candle per minute;
3. ``zero_volume``   -- at most ``max_zero_volume_fraction`` of the candles
                        have zero base volume (illiquid or halted market);
4. ``minimum_trades``-- a quick exploratory replay of the candidate made at
                        least ``minimum_trades`` closed trades. Without a
                        trade count the stage is NOT_RUN, which does not pass.

This module holds no data, performs no I/O and imports nothing outside
``research/`` (ADR-0009).
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from enum import Enum
from typing import Any, Mapping, Sequence

MINUTE_MS = 60_000


class ScreeningError(ValueError):
    """The screening request itself is malformed (not a candidate failing a stage)."""


class StageVerdict(str, Enum):
    PASS = "PASS"
    FAIL = "FAIL"
    NOT_RUN = "NOT_RUN"


@dataclass(frozen=True, slots=True)
class StageResult:
    stage: str
    verdict: StageVerdict
    reason: str = ""

    @property
    def passed(self) -> bool:
        return self.verdict is StageVerdict.PASS

    def as_dict(self) -> dict[str, str]:
        return {"stage": self.stage, "verdict": self.verdict.value, "reason": self.reason}


def validate_candle(row: Any) -> int:
    """A Binance 1-minute kline, checked in full; returns its open time (ms) or raises ValueError.

    Twelve columns: integer open time (0) and close time (6) = open + 59 999 ms; finite,
    positive open/high/low/close (1-4) with low <= open, close <= high; finite, non-negative
    base volume (5), quote volume (7), taker buy base (9) and taker buy quote (10) volumes;
    a non-negative integer trade count (8). Column 11 is unused by Binance. This checks shape
    and internal consistency, not that the prices are genuine market data.
    """
    if not isinstance(row, (list, tuple)) or len(row) != 12:
        raise ValueError(f"a candle has 12 columns, got {row!r:.80}")
    integers = (row[0], row[6], row[8])
    if not all(isinstance(v, int) and not isinstance(v, bool) for v in integers):
        raise ValueError(f"open time, close time and trade count must be integers in {row!r:.80}")
    opened, closed, trades = integers
    if closed != opened + MINUTE_MS - 1 or trades < 0:
        raise ValueError(f"close time {closed} is not open time {opened} + 59999, or a negative trade count")
    try:
        o, h, low, c = (Decimal(str(v)) for v in row[1:5])
        volumes = [Decimal(str(row[i])) for i in (5, 7, 9, 10)]
    except (InvalidOperation, TypeError) as exc:
        raise ValueError(f"a non-numeric price or volume at {opened}") from exc
    if not all(v.is_finite() and v > 0 for v in (o, h, low, c)) or not all(v.is_finite() and v >= 0 for v in volumes):
        raise ValueError(f"non-finite or non-positive price, or a negative volume, at {opened}")
    if not low <= min(o, c) <= max(o, c) <= h:
        raise ValueError(f"inconsistent candle at {opened}: low {low}, open {o}, close {c}, high {h}")
    return opened


@dataclass(frozen=True, slots=True)
class ScreeningSpec:
    """What a screening run checks. ``end_ms`` must not be after ``cutoff_ms`` (the registration time)."""

    start_ms: int
    end_ms: int
    cutoff_ms: int
    max_zero_volume_fraction: Decimal = Decimal("0.05")
    minimum_trades: int = 30

    def __post_init__(self) -> None:
        for name in ("start_ms", "end_ms", "cutoff_ms", "minimum_trades"):
            value = getattr(self, name)
            if not isinstance(value, int) or isinstance(value, bool):
                raise ScreeningError(f"{name} must be an integer, got {value!r}")
        if self.start_ms % MINUTE_MS or self.end_ms % MINUTE_MS or not self.start_ms < self.end_ms:
            raise ScreeningError("the screening span must be whole minutes with start < end")
        if self.end_ms > self.cutoff_ms:
            raise ScreeningError("screening data must end before the registration: the sealed window is never screened")
        try:
            fraction = Decimal(str(self.max_zero_volume_fraction))
        except InvalidOperation as exc:
            raise ScreeningError("max_zero_volume_fraction must be a number") from exc
        if not fraction.is_finite() or not Decimal("0") <= fraction <= Decimal("1"):
            raise ScreeningError("max_zero_volume_fraction must lie in [0, 1]")
        object.__setattr__(self, "max_zero_volume_fraction", fraction)
        if self.minimum_trades < 0:
            raise ScreeningError("minimum_trades must be >= 0")


def screen_data(data: Mapping[str, Sequence[Any]], universe: Sequence[str], spec: ScreeningSpec) -> list[StageResult]:
    """Stages 1-3 for one universe; they do not depend on the candidate's arguments.

    Stops at the first failing stage (fast fail). Never raises for bad data: bad data FAILs.
    """
    if sorted(set(universe)) != sorted(universe) or not universe:
        raise ScreeningError(f"the universe must be non-empty without duplicates, got {list(universe)!r}")
    if set(data) != set(universe):
        return [StageResult("integrity", StageVerdict.FAIL,
                            f"data symbols {sorted(data)} are not the universe {sorted(universe)}")]
    for symbol in sorted(universe):
        rows = data[symbol]
        if not isinstance(rows, (list, tuple)):
            return [StageResult("integrity", StageVerdict.FAIL, f"{symbol}: candles are not a list")]
        try:
            opens = [validate_candle(row) for row in rows]
        except ValueError as exc:
            return [StageResult("integrity", StageVerdict.FAIL, f"{symbol}: {exc}")]
        if opens != list(range(spec.start_ms, spec.end_ms, MINUTE_MS)):
            expected = (spec.end_ms - spec.start_ms) // MINUTE_MS
            return [StageResult("integrity", StageVerdict.PASS),
                    StageResult("completeness", StageVerdict.FAIL,
                                f"{symbol}: {len(opens)} candles, expected exactly {expected} contiguous one-minute "
                                f"candles over the screening span")]
    results = [StageResult("integrity", StageVerdict.PASS), StageResult("completeness", StageVerdict.PASS)]
    for symbol in sorted(universe):
        rows = data[symbol]
        zero = sum(1 for row in rows if Decimal(str(row[5])) == 0)
        if Decimal(zero) > spec.max_zero_volume_fraction * len(rows):
            return results + [StageResult("zero_volume", StageVerdict.FAIL,
                                          f"{symbol}: {zero} of {len(rows)} candles have zero volume "
                                          f"(limit {spec.max_zero_volume_fraction})")]
    return results + [StageResult("zero_volume", StageVerdict.PASS)]


def screen_trades(trade_count: Any, spec: ScreeningSpec) -> StageResult:
    """Stage 4: the quick exploratory replay's closed-trade count, when one was made."""
    if trade_count is None:
        return StageResult("minimum_trades", StageVerdict.NOT_RUN, "no quick replay trade count")
    if not isinstance(trade_count, int) or isinstance(trade_count, bool) or trade_count < 0:
        return StageResult("minimum_trades", StageVerdict.FAIL, f"malformed trade count {trade_count!r}")
    if trade_count < spec.minimum_trades:
        return StageResult("minimum_trades", StageVerdict.FAIL,
                           f"{trade_count} closed trades in the quick replay (need {spec.minimum_trades})")
    return StageResult("minimum_trades", StageVerdict.PASS)


def passed(results: Sequence[StageResult]) -> bool:
    """A candidate passes only when every stage ran and PASSed (NOT_RUN does not pass)."""
    return bool(results) and all(r.passed for r in results) and \
        {r.stage for r in results} == {"integrity", "completeness", "zero_volume", "minimum_trades"}
