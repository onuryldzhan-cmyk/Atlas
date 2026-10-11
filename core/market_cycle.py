"""Market regime identification and cycle tracking (Task 009, registry v5.93).

One classifier for replay and runtime (owner decision 2026-10-10): the regime taxonomy and
``classify`` that research has used since v2 (``tools.regime_engine``) live here, in a pure,
runtime-importable module; ``tools.regime_engine`` re-exports them, so replay, research and
the runtime gate call the same function. Regimes, decided in this order:

  PANIC       close fell more than PANIC_DROP over PANIC_BARS bars AND volatility in its top decile
  HIGH_VOL    volatility above its own 80th percentile
  TREND_UP    efficiency ratio >= TREND_ER and the slow EMA slope is up
  TREND_DOWN  efficiency ratio >= TREND_ER and the slow EMA slope is down
  SIDEWAYS    efficiency ratio <= SIDEWAYS_ER
  TRANSITION  everything in between (no clear state)
  UNKNOWN     too few, gapped, stale, non-finite or otherwise unusable bars (never guessed)

Causality: ``classify`` reads only the closes it is given. ``closed_bars`` admits only bars
whose close time is strictly before the cutoff (the still-forming bar is dropped) and
``assert_causal`` re-checks that invariant before anything is classified, so bar t+1 can
never influence the regime at t.

Hysteresis (``RegimeTracker``): entering a restrictive regime (UNKNOWN, PANIC, HIGH_VOL) is
immediate - smoothing never delays risk-off; any other change needs ``confirm_bars``
consecutive closed bars agreeing on the new regime and ``min_dwell_bars`` in the current one.

Multi-timeframe anchor (``anchored_regime``): higher-timeframe regimes bound the tactical
one - an UNKNOWN, PANIC or HIGH_VOL anchor overrides it, and a tactical TREND_UP against a
TREND_DOWN anchor is only TRANSITION.

Permissibility (``PERMISSIBILITY``): an immutable archetype x regime matrix of scale factors
in [0, 1]; a regime absent from an archetype's row (and UNKNOWN, always) is refused. The
scales are uncalibrated defaults (registry v5.93 UNKNOWN); a scale only ever shrinks a size.

This module performs no I/O and holds no global state.
"""

from __future__ import annotations

import math
import threading
from dataclasses import dataclass, field
from decimal import Decimal
from types import MappingProxyType
from typing import Any, Callable, Mapping, Sequence

WINDOW = 24            # bars for the efficiency ratio (24 x 1h = one day)
EMA_SLOW = 50
TREND_ER = 0.35
SIDEWAYS_ER = 0.15
VOL_WINDOW = 24
VOL_HISTORY = 24 * 20  # percentiles over ~20 days of 1h bars
PANIC_BARS = 6
PANIC_DROP = 0.06
MINIMUM_CLOSES = max(WINDOW, EMA_SLOW, VOL_WINDOW) + 2

UNKNOWN = "UNKNOWN"
REGIMES = ("PANIC", "HIGH_VOL", "TREND_UP", "TREND_DOWN", "SIDEWAYS", "TRANSITION", UNKNOWN)
RESTRICTIVE_REGIMES = frozenset({UNKNOWN, "PANIC", "HIGH_VOL"})

INTERVAL_MS = MappingProxyType({"1h": 3_600_000, "4h": 14_400_000, "1d": 86_400_000})


# =============================================================================
# The classifier (shared with tools.regime_engine)
# =============================================================================


def efficiency_ratio(closes: list[float], window: int = WINDOW) -> float | None:
    if len(closes) <= window:
        return None
    seg = closes[-window - 1:]
    path = sum(abs(b - a) for a, b in zip(seg, seg[1:]))
    return 0.0 if path == 0 else abs(seg[-1] - seg[0]) / path


def ema(values: list[float], span: int) -> list[float]:
    k, out = 2 / (span + 1), []
    for v in values:
        out.append(v if not out else out[-1] + k * (v - out[-1]))
    return out


def rolling_vol(closes: list[float], window: int = VOL_WINDOW) -> list[float]:
    rets = [b / a - 1 for a, b in zip(closes, closes[1:]) if a > 0]
    return [_pstdev(rets[i - window:i]) for i in range(window, len(rets) + 1)]


def _pstdev(xs: list[float]) -> float:
    """Population stdev in floats (two-pass, fsum). statistics.pstdev computes with exact
    Fractions and made one market_regime cycle take 329 s (2026-10-02); labels are unchanged
    (tests/test_regime_engine.py compares both on random series)."""
    n = len(xs)
    m = math.fsum(xs) / n
    return math.sqrt(math.fsum((x - m) ** 2 for x in xs) / n)


def _usable(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value) and value > 0


def classify(closes: list[float]) -> dict[str, Any]:
    """The regime of the LAST close in ``closes`` (closed bars, oldest first)."""
    need = MINIMUM_CLOSES
    if len(closes) < need or any(isinstance(c, (int, float)) and not isinstance(c, bool) and c <= 0
                                 for c in closes):
        return {"regime": UNKNOWN, "reason": f"needs >= {need} positive closes, got {len(closes)}"}
    if not all(_usable(c) for c in closes):
        # Task 009 (review vector C): NaN/inf/non-numeric closes are UNKNOWN, never a regime.
        return {"regime": UNKNOWN, "reason": "non-finite or non-numeric close"}
    er = efficiency_ratio(closes)
    vols = rolling_vol(closes)[-VOL_HISTORY:]
    now_vol = vols[-1]
    ranked = sorted(vols)
    pct = sum(1 for v in ranked if v < now_vol) / len(ranked)  # strictly below: a flat history is not "high"
    slow = ema(closes, EMA_SLOW)
    slope = slow[-1] / slow[-6] - 1 if slow[-6] > 0 else 0.0
    drop = closes[-1] / closes[-1 - PANIC_BARS] - 1
    if not all(math.isfinite(x) for x in (er, now_vol, pct, slope, drop)):
        return {"regime": UNKNOWN, "reason": "non-finite indicator"}
    facts = {"efficiency_ratio": round(er, 3), "vol_percentile": round(pct, 2),
             "ema_slope_5": round(slope, 4), f"move_{PANIC_BARS}_bars": round(drop, 4)}
    if drop <= -PANIC_DROP and pct >= 0.9:
        regime = "PANIC"
    elif pct >= 0.8:
        regime = "HIGH_VOL"
    elif er >= TREND_ER and slope > 0:
        regime = "TREND_UP"
    elif er >= TREND_ER and slope < 0:
        regime = "TREND_DOWN"
    elif er <= SIDEWAYS_ER:
        regime = "SIDEWAYS"
    else:
        regime = "TRANSITION"
    return {"regime": regime, **facts}


# =============================================================================
# Causal closed-bar pipeline
# =============================================================================


class CausalityError(ValueError):
    """A bar that had not closed by the cutoff reached the classifier."""


@dataclass(frozen=True)
class Bar:
    open_ms: int
    close_ms: int
    close: float


def assert_causal(bars: Sequence[Bar], cutoff_ms: int) -> None:
    """The explicit causal invariant: every classified bar closed strictly before the cutoff."""
    for bar in bars:
        if bar.close_ms >= cutoff_ms:
            raise CausalityError(f"bar opened at {bar.open_ms} closes at {bar.close_ms} >= cutoff {cutoff_ms}")


def closed_bars(rows: Any, *, interval: str, cutoff_ms: int) -> tuple[list[Bar] | None, str | None]:
    """Validated, strictly closed bars of one timeframe, oldest first, or (None, reason).

    Rows are kline rows ``[open_ms, open, high, low, close, volume, close_ms, ...]``. A bar
    counts as closed only when its whole interval ended at or before ``cutoff_ms`` and its
    close time (the interval end) is strictly before it; later bars (the forming one) are
    dropped. A close time that is not the bar's own interval end is refused.
    Duplicate, unordered or unevenly spaced (gapped) bars, a non-finite or non-positive close,
    or a newest closed bar older than one interval before the cutoff (a stale feed) make the
    whole series unusable: nothing is interpolated or guessed.
    """
    step = INTERVAL_MS.get(interval)
    if step is None:
        return None, "UNSUPPORTED_INTERVAL"
    if isinstance(cutoff_ms, bool) or not isinstance(cutoff_ms, int):
        return None, "INVALID_CUTOFF"
    if not isinstance(rows, (list, tuple)):
        return None, "NO_ROWS"
    bars: list[Bar] = []
    for row in rows:
        try:
            open_ms, close_ms = row[0], row[6]
            if isinstance(open_ms, bool) or isinstance(close_ms, bool):
                return None, "MALFORMED_ROW"
            open_ms, close_ms = int(open_ms), int(close_ms)
            close = float(row[4])
        except (TypeError, ValueError, IndexError, OverflowError):
            return None, "MALFORMED_ROW"
        if not math.isfinite(close) or close <= 0:
            return None, "NON_FINITE_CLOSE"
        if not open_ms + step - 1 <= close_ms <= open_ms + step:
            # review F5: a close time that is not the bar's own interval end (e.g. a provider
            # falling back to the open time) cannot prove the bar has closed.
            return None, "INCONSISTENT_CLOSE_TIME"
        if open_ms + step <= cutoff_ms and close_ms < cutoff_ms:
            bars.append(Bar(open_ms, close_ms, close))
    for previous, current in zip(bars, bars[1:]):
        if current.open_ms <= previous.open_ms:
            return None, "UNORDERED_OR_DUPLICATE"
        if current.open_ms - previous.open_ms != step:
            return None, "GAP"
    if not bars:
        return None, "NO_CLOSED_BARS"
    if cutoff_ms - bars[-1].close_ms > step:
        return None, "STALE"
    return bars, None


def classify_closed(rows: Any, *, interval: str, cutoff_ms: int) -> dict[str, Any]:
    """The regime at ``cutoff_ms`` from closed bars of one timeframe; UNKNOWN on any defect."""
    bars, reason = closed_bars(rows, interval=interval, cutoff_ms=cutoff_ms)
    if bars is None:
        return {"regime": UNKNOWN, "reason": reason, "bar_open_ms": None}
    assert_causal(bars, cutoff_ms)
    result = classify([bar.close for bar in bars])
    return {**result, "bar_open_ms": bars[-1].open_ms, "bars": len(bars)}


# =============================================================================
# Hysteresis
# =============================================================================


@dataclass(frozen=True)
class HysteresisPolicy:
    confirm_bars: int = 2
    min_dwell_bars: int = 3

    def __post_init__(self) -> None:
        for name in ("confirm_bars", "min_dwell_bars"):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int) or value < 1:
                raise ValueError(f"{name} must be a positive integer")


class RegimeTracker:
    """Smoothed regime of one (symbol, timeframe); updated at most once per closed bar.

    ``immediate`` is the set of regimes entered at once (default: UNKNOWN, PANIC, HIGH_VOL);
    the market-cycle tracker adds every regime its strategy archetype refuses, so a refusal
    is never smoothed away (review F8). A state contradicted by ``confirm_bars +
    min_dwell_bars`` consecutive closed bars that never agree on a successor decays to
    TRANSITION, so no state can outlive its evidence indefinitely.
    """

    def __init__(self, policy: HysteresisPolicy | None = None,
                 immediate: frozenset[str] | None = None) -> None:
        self.policy = policy if policy is not None else HysteresisPolicy()
        self.immediate = frozenset(immediate) | RESTRICTIVE_REGIMES if immediate is not None else RESTRICTIVE_REGIMES
        self.disagreement = 0
        self.state = UNKNOWN
        self.candidate: str | None = None
        self.candidate_count = 0
        self.bars_in_state = 0
        self.last_bar_open_ms: int | None = None
        self.transitions = 0

    def _switch(self, regime: str) -> None:
        if regime != self.state:
            self.transitions += 1
        self.state = regime
        self.candidate, self.candidate_count, self.bars_in_state, self.disagreement = None, 0, 0, 0

    def update(self, raw: str, bar_open_ms: int | None) -> str:
        raw = raw if raw in REGIMES else UNKNOWN
        if bar_open_ms is None:  # no usable closed bar: fail closed at once
            if self.state != UNKNOWN:
                self._switch(UNKNOWN)
            return self.state
        if self.last_bar_open_ms is not None and bar_open_ms <= self.last_bar_open_ms:
            return self.state  # the same (or an older) bar: idempotent, never time-travel
        self.last_bar_open_ms = bar_open_ms
        if raw == self.state:
            self.candidate, self.candidate_count, self.disagreement = None, 0, 0
            self.bars_in_state += 1
            return self.state
        if raw in self.immediate:  # risk-off (and any refusal) is never delayed
            self._switch(raw)
            return self.state
        if raw == self.candidate:
            self.candidate_count += 1
        else:
            self.candidate, self.candidate_count = raw, 1
        self.bars_in_state += 1
        self.disagreement += 1
        if self.candidate_count >= self.policy.confirm_bars and self.bars_in_state >= self.policy.min_dwell_bars:
            self._switch(raw)
        elif (self.disagreement >= self.policy.confirm_bars + self.policy.min_dwell_bars
              and self.state != "TRANSITION"):
            self._switch("TRANSITION")  # contradicted for too long without a confirmed successor
        return self.state

    def snapshot(self) -> dict[str, Any]:
        return {"state": self.state, "candidate": self.candidate, "candidate_count": self.candidate_count,
                "bars_in_state": self.bars_in_state, "transitions": self.transitions,
                "last_bar_open_ms": self.last_bar_open_ms}


# =============================================================================
# Multi-timeframe anchor and permissibility
# =============================================================================


def anchored_regime(tactical: str, anchors: Mapping[str, str]) -> tuple[str, str | None]:
    """The tactical regime bounded by higher-timeframe anchors: (regime, reason or None)."""
    for timeframe, anchor in anchors.items():
        if anchor not in REGIMES or anchor == UNKNOWN:
            return UNKNOWN, f"ANCHOR_{timeframe}_UNKNOWN"
    for restrictive in ("PANIC", "HIGH_VOL"):
        for timeframe, anchor in anchors.items():
            if anchor == restrictive:
                return restrictive, f"ANCHOR_{timeframe}_{restrictive}"
    if tactical not in REGIMES:
        return UNKNOWN, "TACTICAL_UNKNOWN"
    if tactical == "TREND_UP" and any(anchor == "TREND_DOWN" for anchor in anchors.values()):
        return "TRANSITION", "TACTICAL_TREND_UP_AGAINST_TREND_DOWN_ANCHOR"
    return tactical, None


STRATEGY_ARCHETYPES = ("TREND_FOLLOWING", "MOMENTUM", "BREAKOUT", "MEAN_REVERSION")

PERMISSIBILITY: Mapping[str, Mapping[str, Decimal]] = MappingProxyType({
    "TREND_FOLLOWING": MappingProxyType({"TREND_UP": Decimal("1")}),
    "MOMENTUM": MappingProxyType({"TREND_UP": Decimal("1"), "TRANSITION": Decimal("0.5")}),
    "BREAKOUT": MappingProxyType({"TREND_UP": Decimal("1"), "HIGH_VOL": Decimal("0.5")}),
    "MEAN_REVERSION": MappingProxyType({"SIDEWAYS": Decimal("1"), "TRANSITION": Decimal("0.5")}),
})


@dataclass(frozen=True)
class RegimePermission:
    allowed: bool
    scale: Decimal
    reason: str


def permission(archetype: str, regime: str) -> RegimePermission:
    """Whether a new entry of ``archetype`` is allowed in ``regime``, and its size scale in [0, 1]."""
    row = PERMISSIBILITY.get(archetype)
    if row is None:
        return RegimePermission(False, Decimal("0"), "UNKNOWN_STRATEGY_ARCHETYPE")
    if regime == UNKNOWN or regime not in REGIMES:
        return RegimePermission(False, Decimal("0"), "REGIME_UNKNOWN")
    scale = row.get(regime, Decimal("0"))
    if scale <= 0:
        return RegimePermission(False, Decimal("0"), "REGIME_NOT_PERMITTED")
    return RegimePermission(True, scale, "REGIME_PERMITTED" if scale == 1 else "REGIME_MARGINAL")


# =============================================================================
# Per-symbol cycle tracking (runtime observer)
# =============================================================================

# 1h: 720 closed bars + the forming one (the regime-filter draft's 30-day lookback; review F9). The
# windowed replay classifies a shorter history (see DRAFT_EVIDENCE_GATE).
DEFAULT_BAR_LIMITS = MappingProxyType({"1h": 721, "4h": 200, "1d": 120})
FETCH_RETRY_MS = 300_000


@dataclass(frozen=True)
class RegimeGateConfig:
    """MarketLoop's regime configuration. ``enabled`` (the BUY gate) defaults to OFF."""

    enabled: bool = False
    archetype: str = "TREND_FOLLOWING"
    tactical: str = "1h"
    anchors: tuple[str, ...] = ("4h", "1d")
    policy: HysteresisPolicy = field(default_factory=HysteresisPolicy)

    def __post_init__(self) -> None:
        if not isinstance(self.enabled, bool):
            raise ValueError("enabled must be a bool")
        if self.archetype not in PERMISSIBILITY:
            raise ValueError(f"unknown strategy archetype {self.archetype!r}")
        timeframes = (self.tactical, *self.anchors)
        if any(tf not in INTERVAL_MS for tf in timeframes) or len(set(timeframes)) != len(timeframes):
            raise ValueError("timeframes must be distinct members of INTERVAL_MS")
        if any(INTERVAL_MS[a] <= INTERVAL_MS[self.tactical] for a in self.anchors):
            raise ValueError("anchors must be higher timeframes than the tactical one")


class MarketCycleTracker:
    """Closed-bar regime tracking for many symbols; ``observe`` never raises.

    ``fetch(symbol, interval, limit)`` returns kline rows. Each (symbol, timeframe) is
    re-fetched only when a newer bar should have closed (or ``FETCH_RETRY_MS`` after a
    failure), so the extra load is about one request per symbol per bar; fetches run outside
    the tracker lock (review F7). Only trackers and the latest results are kept (no raw
    bars): memory is bounded by the symbol count.

    A data fault (a failed fetch or unusable bars) shows that timeframe as UNKNOWN while it
    lasts but does not reset its smoothed regime; the next good fetch first replays every
    closed bar the tracker missed (causally, oldest first), so a provider blip never costs
    days of UNKNOWN (review F2). A cutoff earlier than the symbol's last one is UNKNOWN: state
    built from later bars is never reused for an earlier time (review F6).
    """

    def __init__(self, fetch: Callable[[str, str, int], Any], config: RegimeGateConfig | None = None) -> None:
        self.config = config if config is not None else RegimeGateConfig()
        self._fetch = fetch
        self._lock = threading.Lock()
        self._immediate = frozenset(r for r in REGIMES if not permission(self.config.archetype, r).allowed)
        self._trackers: dict[tuple[str, str], RegimeTracker] = {}
        self._latest: dict[tuple[str, str], dict[str, Any]] = {}
        self._next_due_ms: dict[tuple[str, str], int] = {}
        self._last_cutoff_ms: dict[str, int] = {}
        self._snapshots: dict[str, dict[str, Any]] = {}

    @property
    def timeframes(self) -> tuple[str, ...]:
        return (self.config.tactical, *self.config.anchors)

    def _replay(self, tracker: RegimeTracker, bars: Sequence[Bar]) -> None:
        """Feed the tracker every closed bar it has not seen, oldest first (warm start included)."""
        closes = [bar.close for bar in bars]
        depth = self.config.policy.confirm_bars + self.config.policy.min_dwell_bars + 1
        seen = tracker.last_bar_open_ms
        missed = [i for i, bar in enumerate(bars) if seen is None or bar.open_ms > seen]
        if seen is None:
            missed = missed[-(depth + 1):]  # a new tracker: warm start from the last few bars
        for i in missed:
            tracker.update(classify(closes[:i + 1])["regime"], bars[i].open_ms)

    def _apply(self, symbol: str, interval: str, rows: Any, error: Exception | None, cutoff_ms: int) -> None:
        """Fold one fetch outcome into the tracker (caller holds the lock)."""
        key = (symbol, interval)
        if error is not None:
            result = {"regime": UNKNOWN, "reason": type(error).__name__, "bar_open_ms": None}
            bars = None
        else:
            bars, reason = closed_bars(rows, interval=interval, cutoff_ms=cutoff_ms)
            if bars is None:
                result = {"regime": UNKNOWN, "reason": reason, "bar_open_ms": None}
            else:
                assert_causal(bars, cutoff_ms)
                result = {**classify([bar.close for bar in bars]), "bar_open_ms": bars[-1].open_ms,
                          "bars": len(bars)}
        self._latest[key] = result
        if bars is None:  # a data fault: shown UNKNOWN, the smoothed state is kept
            self._next_due_ms[key] = cutoff_ms + FETCH_RETRY_MS
            return
        tracker = self._trackers.get(key)
        if tracker is None:
            tracker = self._trackers[key] = RegimeTracker(self.config.policy, self._immediate)
        self._replay(tracker, bars)
        self._next_due_ms[key] = bars[-1].open_ms + 2 * INTERVAL_MS[interval]

    def _state(self, symbol: str, interval: str, cutoff_ms: int) -> str:
        latest = self._latest.get((symbol, interval))
        tracker = self._trackers.get((symbol, interval))
        if latest is None or tracker is None or latest.get("bar_open_ms") is None:
            return UNKNOWN
        if cutoff_ms - (int(latest["bar_open_ms"]) + INTERVAL_MS[interval]) > INTERVAL_MS[interval]:
            return UNKNOWN  # the cached bar is no longer the latest closed one
        return tracker.state

    def observe(self, symbol: str, cutoff_ms: int) -> dict[str, Any]:
        """Update and return the symbol's regime snapshot at ``cutoff_ms``."""
        symbol = str(symbol).strip().upper()
        try:
            with self._lock:
                previous = self._last_cutoff_ms.get(symbol)
                if previous is not None and cutoff_ms < previous:
                    snapshot = {"regime": UNKNOWN, "anchor_reason": "CUTOFF_REGRESSED", "observed_at_ms": cutoff_ms}
                    self._snapshots[symbol] = snapshot
                    return dict(snapshot)
                self._last_cutoff_ms[symbol] = cutoff_ms
                due = [tf for tf in self.timeframes if cutoff_ms >= self._next_due_ms.get((symbol, tf), 0)]
            fetched: list[tuple[str, Any, Exception | None]] = []
            for interval in due:  # network I/O outside the lock
                try:
                    fetched.append((interval, self._fetch(symbol, interval, DEFAULT_BAR_LIMITS[interval]), None))
                except Exception as exc:  # a fetch failure is a data fault, never a regime
                    fetched.append((interval, None, exc))
            with self._lock:
                if self._last_cutoff_ms.get(symbol) != cutoff_ms:
                    # a later observation of this symbol overtook this one; keep its state
                    found = self._snapshots.get(symbol)
                    return dict(found) if found is not None else {"regime": UNKNOWN, "observed_at_ms": cutoff_ms}
                for interval, rows, error in fetched:
                    try:
                        self._apply(symbol, interval, rows, error, cutoff_ms)
                    except Exception as exc:  # e.g. a causality violation: that timeframe is UNKNOWN
                        self._latest[(symbol, interval)] = {"regime": UNKNOWN, "reason": type(exc).__name__,
                                                            "bar_open_ms": None}
                        self._next_due_ms[(symbol, interval)] = cutoff_ms + FETCH_RETRY_MS
                states = {tf: self._state(symbol, tf, cutoff_ms) for tf in self.timeframes}
                regime, reason = anchored_regime(states[self.config.tactical],
                                                 {tf: states[tf] for tf in self.config.anchors})
                snapshot = {
                    "regime": regime,
                    "anchor_reason": reason,
                    "states": states,
                    "raw": {tf: self._latest.get((symbol, tf), {}).get("regime", UNKNOWN) for tf in self.timeframes},
                    "reasons": {tf: self._latest.get((symbol, tf), {}).get("reason") for tf in self.timeframes},
                    "transitions": {tf: self._trackers[(symbol, tf)].transitions if (symbol, tf) in self._trackers
                                    else 0 for tf in self.timeframes},
                    "observed_at_ms": cutoff_ms,
                }
                self._snapshots[symbol] = snapshot
                return dict(snapshot)
        except Exception as exc:  # defensive: an observer defect is UNKNOWN, never a crash
            snapshot = {"regime": UNKNOWN, "anchor_reason": f"OBSERVER_ERROR:{type(exc).__name__}",
                        "observed_at_ms": cutoff_ms}
            with self._lock:
                self._snapshots[symbol] = snapshot
            return dict(snapshot)

    def snapshot(self, symbol: str) -> dict[str, Any] | None:
        with self._lock:
            found = self._snapshots.get(str(symbol).strip().upper())
            return dict(found) if found is not None else None

    def status(self) -> dict[str, Any]:
        with self._lock:
            return {"gate_enabled": self.config.enabled, "archetype": self.config.archetype,
                    "timeframes": list(self.timeframes),
                    "hysteresis": {"confirm_bars": self.config.policy.confirm_bars,
                                   "min_dwell_bars": self.config.policy.min_dwell_bars},
                    "symbols": {s: dict(v) for s, v in sorted(self._snapshots.items())}}


# Review F3 / review 16 M1: the runtime configuration closest to the rule the regime-filter
# draft's pre-registered evidence bar measures (raw 1H classify, BUY only in TREND_UP, no
# hysteresis, no anchors). Hysteresis with confirm = dwell = 1 and the archetype's refusals
# entered immediately reproduces raw classify of the clock-aligned closed 1H bars on every bar.
# It is NOT the measured rule itself: tools.backtest_replay builds its hourly bars as rolling
# 60-minute chunks ending at the decision minute (strategy_compare decides every 15 minutes, off
# the clock hour), so the replay's last bar carries up-to-the-minute prices while the runtime's
# last closed kline can be up to 59 minutes old. The two agree only at clock-aligned decision
# minutes, and even there only with equal history: strategy_compare replays each window on its
# own (7-day windows by default), so the replay classifies at most the window's hours (UNKNOWN for
# the first ~51) while the runtime classifies the last 720 closed bars. Clearing that bar therefore
# does not validate this (or any) runtime configuration; the runtime rule needs evidence measured
# on clock-aligned closed bars with the same 720-bar history before the gate is switched on.
DRAFT_EVIDENCE_GATE = RegimeGateConfig(enabled=True, archetype="TREND_FOLLOWING", tactical="1h", anchors=(),
                                       policy=HysteresisPolicy(confirm_bars=1, min_dwell_bars=1))
