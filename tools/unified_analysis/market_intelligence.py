"""Market intelligence layer: Binance-first inputs, validated into a causal, provenance-carrying snapshot.

Bars are validated by core.market_cycle.closed_bars, the same causal pipeline the runtime regime gate uses: only
bars closed strictly before the cutoff, no gap, no duplicate, no stale feed, no non-finite close. A timeframe that
fails is UNUSABLE with its reason; nothing is interpolated. External context (funding, Fear & Greed, treasury
yields) comes from Atlas's existing providers in atlas_finance.market_data, never from upstream stock-market tools.

Collectors are the only functions here that touch the network or disk; build_snapshot is pure.
"""

from __future__ import annotations

import hashlib
import json
import math
import sqlite3
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Callable, Mapping

from core.market_cycle import INTERVAL_MS, classify, closed_bars

from tools.unified_analysis import indicators as ind
from tools.unified_analysis.contracts import SourceRef

TIMEFRAMES = ("1h", "4h", "1d")
PRIMARY_TIMEFRAME = "1h"
FETCH_LIMITS = {"1h": 500, "4h": 200, "1d": 200}
MIN_BARS = 60                                   # EMA 50 plus margin; core.market_cycle needs 52 for a regime
SENTIMENT_MAX_AGE = timedelta(hours=36)         # Fear & Greed is daily
MACRO_MAX_AGE = timedelta(days=5)               # treasury yields are business-daily
FUTURE_TOLERANCE = timedelta(seconds=5)


@dataclass(frozen=True)
class MarketInputs:
    """Everything one analysis may read, gathered before it starts (so a run can be replayed from its inputs)."""

    symbol: str
    cutoff_ms: int
    fetched_at: datetime
    source: str
    klines: Mapping[str, Any]                   # timeframe -> Binance kline rows (or None when the fetch failed)
    funding: Mapping[str, Any] | None = None    # FundingRateProvider.rate() result
    fear_greed: Any | None = None               # FearGreedReading
    treasury: Any | None = None                 # TreasuryYieldReading
    fetch_errors: Mapping[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class TimeframeView:
    timeframe: str
    usable: bool
    reason: str | None
    open_ms: tuple[int, ...] = ()
    highs: tuple[float, ...] = ()
    lows: tuple[float, ...] = ()
    closes: tuple[float, ...] = ()
    quote_volumes: tuple[float, ...] = ()
    last_close_ms: int | None = None
    regime: Mapping[str, Any] = field(default_factory=dict)
    digest: str = ""

    def metric(self, name: str) -> float | None:
        """The trusted value of one metric, recomputed from the bars (verification calls this)."""
        if not self.usable:
            return None
        fn = METRICS.get(name)
        if fn is None:
            return None
        value = fn(self)
        return value if isinstance(value, (int, float)) and math.isfinite(value) else None


def _atr_pct(v: TimeframeView) -> float | None:
    a = ind.atr(v.highs, v.lows, v.closes)
    return None if a is None else a / v.closes[-1]


METRICS: dict[str, Callable[[TimeframeView], float | None]] = {
    "close": lambda v: v.closes[-1],
    "rsi_14": lambda v: ind.rsi(v.closes),
    "ema_20": lambda v: ind.ema_last(v.closes, ind.EMA_FAST),
    "ema_50": lambda v: ind.ema_last(v.closes, ind.EMA_SLOW),
    "return_20": lambda v: ind.pct_change(v.closes, ind.RETURN_BARS),
    "atr_14": lambda v: ind.atr(v.highs, v.lows, v.closes),
    "atr_pct_14": _atr_pct,
    "swing_low_24": lambda v: ind.swing_low(v.lows),
    "swing_high_24": lambda v: ind.swing_high(v.highs),
    "quote_volume_24": lambda v: ind.window_sum(v.quote_volumes, 24),
    "quote_volume_168": lambda v: ind.window_sum(v.quote_volumes, 168),
    # recomputed from the closes, not read back from the snapshot's own regime record
    "efficiency_ratio": lambda v: classify(list(v.closes)).get("efficiency_ratio"),
    "vol_percentile": lambda v: classify(list(v.closes)).get("vol_percentile"),
}


@dataclass(frozen=True)
class MarketSnapshot:
    symbol: str
    cutoff_ms: int                              # bar boundary: only bars closed before it are used
    as_of: datetime                             # decision time: no source may be observed after it
    views: Mapping[str, TimeframeView]
    sources: tuple[SourceRef, ...]
    problems: tuple[str, ...]
    funding: Mapping[str, Any] | None
    fear_greed: Mapping[str, Any] | None        # {"value", "observed_at"} when usable
    treasury: Mapping[str, Any] | None          # {"ten_year_change_bp", "curve_spread_bp", "observed_at"}
    source_name: str = ""
    entry_from_ms: int = 0                      # the first bar boundary at or after the decision time (settlement)

    @property
    def usable(self) -> bool:
        view = self.views.get(PRIMARY_TIMEFRAME)
        return bool(view and view.usable)

    def view(self, timeframe: str) -> TimeframeView | None:
        return self.views.get(timeframe)

    def source_id(self, kind: str) -> str:
        return f"{self.symbol}:{kind}"


def _ms_to_dt(ms: int) -> datetime:
    return datetime.fromtimestamp(ms / 1000, tz=UTC)


def _float(value: Any) -> float:
    if isinstance(value, bool):
        raise ValueError("bool is not a number")
    out = float(value)
    if not math.isfinite(out):
        raise ValueError("non-finite")
    return out


def _view(timeframe: str, rows: Any, cutoff_ms: int) -> TimeframeView:
    if rows is None:
        return TimeframeView(timeframe, False, "FETCH_FAILED")
    bars, reason = closed_bars(rows, interval=timeframe, cutoff_ms=cutoff_ms)
    if bars is None:
        return TimeframeView(timeframe, False, reason)
    if len(bars) < MIN_BARS:
        return TimeframeView(timeframe, False, f"TOO_FEW_BARS ({len(bars)} < {MIN_BARS})")
    by_open: dict[int, Any] = {}
    for row in rows:
        by_open[int(row[0])] = row
    highs, lows, closes, quotes = [], [], [], []
    try:
        for bar in bars:
            row = by_open[bar.open_ms]
            high, low, close, volume = _float(row[2]), _float(row[3]), _float(row[4]), _float(row[5])
            if not (0 < low <= min(close, _float(row[1])) and high >= max(close, _float(row[1]))) or volume < 0:
                return TimeframeView(timeframe, False, "INCONSISTENT_OHLC")
            quote = _float(row[7]) if len(row) > 7 and row[7] is not None else volume * close
            if quote < 0:
                return TimeframeView(timeframe, False, "NEGATIVE_VOLUME")
            highs.append(high); lows.append(low); closes.append(close); quotes.append(quote)
    except (TypeError, ValueError, IndexError, KeyError):
        return TimeframeView(timeframe, False, "MALFORMED_ROW")
    canonical = json.dumps([[b.open_ms, h, l, c, q] for b, h, l, c, q in zip(bars, highs, lows, closes, quotes)],
                           separators=(",", ":"))
    return TimeframeView(
        timeframe=timeframe, usable=True, reason=None, open_ms=tuple(b.open_ms for b in bars),
        highs=tuple(highs), lows=tuple(lows), closes=tuple(closes), quote_volumes=tuple(quotes),
        last_close_ms=bars[-1].close_ms, regime=classify(list(closes)),
        digest=hashlib.sha256(canonical.encode()).hexdigest())


def _reading_field(reading: Any, name: str) -> Any:
    return reading.get(name) if isinstance(reading, Mapping) else getattr(reading, name, None)


def build_snapshot(inputs: MarketInputs) -> MarketSnapshot:
    """Pure: validate every input against the cutoff and attach provenance. Never raises on bad data.

    Two moments (review F3): the bar ``cutoff_ms`` (a primary-timeframe boundary) and the decision time, which is
    the fetch time. A live run fetches inside the hour after its cutoff, so context read at fetch time (funding)
    is legitimate for the decision but would be look-ahead against the bar boundary. Every context source is
    therefore checked against the decision time, and settlement starts at the first boundary at or after it
    (``entry_from_ms``), never at the earlier cutoff. A replay's decision time is its cutoff.
    """
    cutoff_ms = inputs.cutoff_ms
    step = INTERVAL_MS[PRIMARY_TIMEFRAME]
    problems: list[str] = []
    fetched_at = inputs.fetched_at if isinstance(inputs.fetched_at, datetime) and inputs.fetched_at.tzinfo else None
    as_of = fetched_at if fetched_at is not None else _ms_to_dt(cutoff_ms)
    decision_ms = int(as_of.timestamp() * 1000)
    if fetched_at is None:
        problems.append("FETCHED_AT_MISSING_OR_NAIVE")
    elif decision_ms < cutoff_ms - FUTURE_TOLERANCE.total_seconds() * 1000:
        problems.append("CUTOFF_AFTER_FETCH")  # the data cannot describe a moment after it was fetched
    elif decision_ms - cutoff_ms >= step:
        problems.append("FETCH_LONG_AFTER_CUTOFF")  # the decision would use bars older than the last closed one
    entry_from_ms = cutoff_ms if decision_ms <= cutoff_ms else cutoff_ms + step
    untrusted = fetched_at is None or "CUTOFF_AFTER_FETCH" in problems or "FETCH_LONG_AFTER_CUTOFF" in problems
    views: dict[str, TimeframeView] = {}
    sources: list[SourceRef] = []
    for tf in TIMEFRAMES:
        view = _view(tf, inputs.klines.get(tf), cutoff_ms)
        if untrusted:
            view = TimeframeView(tf, False, "UNTRUSTED_FETCH_TIME")
        views[tf] = view
        if not view.usable:
            problems.append(f"{tf}:{view.reason}{' (' + inputs.fetch_errors[tf] + ')' if tf in inputs.fetch_errors else ''}")
            continue
        sources.append(SourceRef(
            source_id=f"{inputs.symbol}:bars:{tf}", source=inputs.source, symbol=inputs.symbol, timeframe=tf,
            observed_at=_ms_to_dt(view.last_close_ms), fetched_at=fetched_at,
            reference=f"bars {tf} {view.open_ms[0]}..{view.open_ms[-1]} n={len(view.open_ms)} sha256:{view.digest}"))

    funding = None
    if isinstance(inputs.funding, Mapping) and inputs.funding.get("available") and fetched_at is not None:
        try:
            rate = float(inputs.funding["rate"])
            if math.isfinite(rate) and abs(rate) < 0.05:
                funding = {"rate": rate, "band": inputs.funding.get("band")}
                sources.append(SourceRef(f"{inputs.symbol}:funding", "binance_futures_premium_index", inputs.symbol,
                                         None, fetched_at, fetched_at, "fapi/v1/premiumIndex lastFundingRate"))
            else:
                problems.append("funding:IMPLAUSIBLE")
        except (KeyError, TypeError, ValueError):
            problems.append("funding:MALFORMED")
    elif inputs.funding is not None:
        problems.append(f"funding:{_reading_field(inputs.funding, 'reason') or 'UNAVAILABLE'}")

    fear_greed = None
    if inputs.fear_greed is not None:
        observed = _reading_field(inputs.fear_greed, "observed_at")
        value = _reading_field(inputs.fear_greed, "value")
        if not _reading_field(inputs.fear_greed, "available"):
            problems.append(f"fear_greed:{_reading_field(inputs.fear_greed, 'reason') or 'UNAVAILABLE'}")
        elif not isinstance(observed, datetime) or observed.tzinfo is None or isinstance(value, bool) \
                or not isinstance(value, int) or not 0 <= value <= 100:
            problems.append("fear_greed:MALFORMED")
        elif observed > as_of + FUTURE_TOLERANCE:
            problems.append("fear_greed:AFTER_CUTOFF")  # look-ahead: never used for an earlier cutoff
        elif as_of - observed > SENTIMENT_MAX_AGE:
            problems.append("fear_greed:STALE")
        else:
            fear_greed = {"value": value, "observed_at": observed}
            sources.append(SourceRef("market:fear_greed", "alternative.me_fng", None, None, observed, fetched_at,
                                     "crypto Fear & Greed index (market-wide)"))

    treasury = None
    if inputs.treasury is not None:
        day = _reading_field(inputs.treasury, "observed_date")
        change = _reading_field(inputs.treasury, "ten_year_change_bp")
        spread = _reading_field(inputs.treasury, "curve_spread_bp")
        if not _reading_field(inputs.treasury, "available"):
            problems.append(f"treasury:{_reading_field(inputs.treasury, 'reason') or 'UNAVAILABLE'}")
        elif day is None or not isinstance(change, int) or isinstance(change, bool) or not isinstance(spread, int):
            problems.append("treasury:MALFORMED")
        else:
            # a daily yield is known only once its day has ended: the conservative observation time
            observed = datetime(day.year, day.month, day.day, tzinfo=UTC) + timedelta(days=1)
            if observed > as_of + FUTURE_TOLERANCE:
                problems.append("treasury:AFTER_CUTOFF")
            elif as_of - observed > MACRO_MAX_AGE:
                problems.append("treasury:STALE")
            else:
                treasury = {"ten_year_change_bp": change, "curve_spread_bp": spread, "observed_at": observed}
                sources.append(SourceRef("macro:treasury", "us_treasury_par_yields", None, None, observed, fetched_at,
                                         f"10y change {change} bp, 10y-2y {spread} bp"))
    return MarketSnapshot(inputs.symbol, cutoff_ms, as_of, views, tuple(sources), tuple(problems), funding,
                          fear_greed, treasury, inputs.source, entry_from_ms)


# =============================================================================
# Collectors (I/O): the only network / disk access of the package
# =============================================================================


def floor_cutoff(now: datetime, timeframe: str = PRIMARY_TIMEFRAME) -> int:
    """The analysis cutoff: the last closed boundary of the primary timeframe at or before ``now``."""
    step = INTERVAL_MS[timeframe]
    return int(now.timestamp() * 1000) // step * step


def collect_binance(symbol: str, *, now: datetime | None = None, http_get: Callable[[str], Any] | None = None,
                    funding_provider: Any = None, fear_greed_provider: Any = None,
                    treasury_provider: Any = None, context: bool = True) -> MarketInputs:
    """Live Binance spot klines plus Atlas's context providers. Every failure is recorded, never raised."""
    if http_get is None:
        from tools.select_universe import http_get as _http_get
        http_get = _http_get
    now = now or datetime.now(UTC)
    klines: dict[str, Any] = {}
    errors: dict[str, str] = {}
    for tf in TIMEFRAMES:
        try:
            klines[tf] = http_get(f"/api/v3/klines?symbol={symbol}&interval={tf}&limit={FETCH_LIMITS[tf]}")
        except Exception as exc:  # network, HTTP, JSON: the timeframe is unusable, the reason is kept
            klines[tf] = None
            errors[tf] = type(exc).__name__
    fetched_at = now
    funding = fear_greed = treasury = None
    if context:
        from atlas_finance.market_data.fear_greed_provider import FearGreedProvider
        from atlas_finance.market_data.funding_rate_provider import FundingRateProvider
        from atlas_finance.market_data.treasury_yield_provider import TreasuryYieldProvider

        for name, make, call in (("funding", funding_provider or FundingRateProvider, lambda p: p.rate(symbol)),
                                 ("fear_greed", fear_greed_provider or FearGreedProvider, lambda p: p.get_reading()),
                                 ("treasury", treasury_provider or TreasuryYieldProvider, lambda p: p.get_reading())):
            try:
                provider = make() if callable(make) and isinstance(make, type) else make
                value = call(provider)
            except Exception as exc:
                value = {"available": False, "reason": type(exc).__name__}
            if name == "funding":
                funding = value
            elif name == "fear_greed":
                fear_greed = value
            else:
                treasury = value
    return MarketInputs(symbol, floor_cutoff(now), fetched_at, "binance_spot_klines", klines, funding, fear_greed,
                        treasury, errors)


class ArchiveUnavailable(RuntimeError):
    pass


def read_archive_rows(database: Path, symbol: str, timeframe: str, start_ms: int, end_ms: int) -> list[list[Any]]:
    """Kline-shaped rows from the market archive, read immutably (no lock, no side file; see tools/soak_report.py)."""
    if not database.is_file():
        raise ArchiveUnavailable(f"no market archive at {database}")
    log = database.with_name(database.name + "-wal")
    if log.exists() and log.stat().st_size > 0:
        raise ArchiveUnavailable(f"market archive {database} has an unfinished write-ahead log")
    step = INTERVAL_MS[timeframe]
    try:
        connection = sqlite3.connect(f"{database.resolve().as_uri()}?mode=ro&immutable=1", uri=True)
        try:
            rows = connection.execute(
                "SELECT open_time_ms, open, high, low, close, volume, close_time_ms, quote_volume FROM market_data_bars "
                "WHERE symbol = ? AND timeframe = ? AND open_time_ms BETWEEN ? AND ? ORDER BY open_time_ms",
                (symbol, timeframe, start_ms, end_ms)).fetchall()
        finally:
            connection.close()
    except sqlite3.Error as exc:
        raise ArchiveUnavailable(f"market archive {database}: {exc}") from exc
    return [[o, op, h, lo, c, v, ct if ct is not None else o + step - 1, q] for o, op, h, lo, c, v, ct, q in rows]


def collect_archive(database: Path, symbol: str, cutoff_ms: int) -> MarketInputs:
    """Historical inputs at ``cutoff_ms`` from the archive. No point-in-time history exists in Atlas for funding,
    sentiment or macro, so those are absent (their specialists abstain) rather than taken from today: look-ahead."""
    klines: dict[str, Any] = {}
    errors: dict[str, str] = {}
    for tf in TIMEFRAMES:
        step = INTERVAL_MS[tf]
        try:
            klines[tf] = read_archive_rows(database, symbol, tf, cutoff_ms - FETCH_LIMITS[tf] * step, cutoff_ms)
        except ArchiveUnavailable as exc:
            klines[tf] = None
            errors[tf] = str(exc)[:200]
    return MarketInputs(symbol, cutoff_ms, _ms_to_dt(cutoff_ms), "market_archive", klines, fetch_errors=errors)
