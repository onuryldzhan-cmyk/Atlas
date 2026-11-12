"""Forex replay and strategy comparison (Task 030, registry v5.113). RESEARCH ONLY.

Owner 2026-11-12: 'Forex verisiyle test (Önerilen)'. This replays the real decision chain (MarketLoop + AtlasBrain +
RiskEngine, exactly as ``tools/backtest_replay.py`` does for crypto) over forex 1-minute history, with the forex
rules the runtime has:

- the brain sees BID candles (MetaTrader 5 candles are BID candles);
- a buy fills at the next minute's ASK open, a sell at the next minute's BID open, so every round trip pays the
  spread that was really quoted;
- the session: no minute outside the forex week is replayed, no new risk in the last 60 minutes before a close,
  every open position is closed 30 minutes before a close (``atlas_finance.forex.sessions``);
- the margin book: margin = notional / leverage, new risk spends only cash less any unrealized loss, and a margin
  level of 100 % or below closes everything, largest loss first;
- shorts: a SELL of a pair not held opens a short and a BUY covers it; a short passes the same gates as a long;
- the risk policy main.py runs: open losses count in the daily-loss limit, capital sleeves are on, and RiskEngine is
  handed the marked equity (realized equity less any open loss) and the open P&L.
The stop-out and the close-out are checked on every replayed minute and fill at the next minute's open.

What it is NOT:
- It is not evidence. No study is registered, so every result is EXPLORATORY and ``evidence_eligible`` is False.
- It orders nothing and changes no runtime state.
- Commission and swap are UNKNOWN until the owner's MetaTrader 5 test; ``commission_rate`` and ``spread_mult`` are
  stated assumptions for sensitivity, never measured values. Swap (overnight financing) is not modelled.
- The history is Dukascopy's (an ECN feed, tighter than most retail brokers). It is downloaded to a cache outside
  the repository and never committed.
- The runtime's regime gate and the Brain's trade memory are not replayed (a fresh, empty memory per run).

Known differences from the runtime (independent audit, Task 030), each of which can move the figures:
- Costs. The PAPER runtime today charges the crypto fee (0.1 % a side) and 5 bps slippage on forex too. The replay's
  default charges the quoted spread only; the runtime's cost is one of the comparison's variants.
- An order is sized on the decision candle's BID close and filled at the next minute's quote, so a fill can exceed
  the approved allocation by the spread and the one-minute move.
- "1-hour" bars for the trend average and ATR are 60 consecutive replayed minutes; across a weekend or a data gap
  they are not clock hours.
- The ATR stop is checked at each decision step, not every minute.
- A closure with no priced minute inside the 30-minute close-out window leaves the position open (the runtime holds
  too, and alerts); the replay counts it as ``held_over_close``.
- Sizing is the bucket's ceiling (exposure capital x the bucket's share); whether the runtime sizes every order at
  exactly that is UNKNOWN.
- Parallel runs (``--jobs``) are not covered by a test.
"""

from __future__ import annotations

import argparse
import contextlib
import io
import json
import logging
import lzma
import os
import struct
import sys
import tempfile
import time
import urllib.request
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from decimal import ROUND_DOWN, Decimal
from pathlib import Path
from typing import Any, Callable

from atlas_finance.forex.instruments import FOREX_LEVERAGE, FOREX_UNIVERSE, STOP_OUT_MARGIN_LEVEL
from atlas_finance.forex.sessions import (
    PRE_CLOSE_MINUTES,
    WEEKEND_CLOSE_MINUTES,
    is_forex_market_open,
    is_forex_pre_close,
)
from core.execution_models import normalize_risk
from core.market_loop import MarketLoop
from core.market_risk_regime import MarketRiskRegimeProvider
from core.risk_engine import PositionExposure, RiskEngine, RiskPolicy, RiskRequest, RiskState
from tools import backtest_replay as bt

DATAFEED = "https://datafeed.dukascopy.com/datafeed"
_RECORD = struct.Struct(">5If")   # seconds from the day's start, open, close, low, high (x 1e5), volume
PRICE_SCALE = Decimal("100000")   # the four USD-quoted majors; a JPY pair would need 1e3 and is refused
MINUTE_MS = 60_000
BID_OPEN, BID_CLOSE, CLOSE_MS, ASK_OPEN, ASK_CLOSE = 1, 4, 6, 7, 10
ZERO = Decimal("0")
CLOSURE_GAP_MS = 60 * MINUTE_MS   # a gap this long between replayed minutes is a market closure
EXPLORATORY = "EXPLORATORY"

Opener = Callable[[str], bytes]


# ---------------------------------------------------------------- history


def decode_bi5(blob: bytes, day: date) -> list[tuple[int, str, str, str, str, float]]:
    """One day's 1-minute candles as (open_ms, open, high, low, close, volume). An empty file is a day with no data."""

    if not blob:
        return []
    raw = lzma.decompress(blob)
    if len(raw) % _RECORD.size:
        raise ValueError(f"bi5 payload of {len(raw)} bytes is not a whole number of records")
    start = int(datetime(day.year, day.month, day.day, tzinfo=UTC).timestamp()) * 1000
    rows = []
    for seconds, o, c, low, h, volume in _RECORD.iter_unpack(raw):
        if min(o, c, low, h) <= 0 or not low <= min(o, c) <= max(o, c) <= h:
            raise ValueError(f"bi5 candle at second {seconds} is not a valid candle")
        o, h, low, c = (f"{Decimal(v) / PRICE_SCALE:.5f}" for v in (o, h, low, c))
        rows.append((start + seconds * 1000, o, h, low, c, float(volume)))
    return rows


def day_url(pair: str, day: date, side: str) -> str:
    return f"{DATAFEED}/{pair}/{day.year}/{day.month - 1:02d}/{day.day:02d}/{side}_candles_min_1.bi5"


def _http(url: str) -> bytes:
    for attempt in range(4):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "research"}), timeout=30) as r:
                return r.read()
        except Exception:
            if attempt == 3:
                raise
            time.sleep(2 ** attempt)
    raise AssertionError("unreachable")


def fetch_day(pair: str, day: date, side: str, cache: Path, opener: Opener = _http) -> bytes:
    """The raw day file, from the cache when present. The cache lives outside the repository."""

    path = Path(cache) / pair / f"{day.isoformat()}_{side}.bi5"
    if path.exists():
        return path.read_bytes()
    if day >= datetime.now(UTC).date():
        raise ValueError(f"{day} is not a completed UTC day; a partial day is never cached")
    blob = opener(day_url(pair, day, side))
    path.parent.mkdir(parents=True, exist_ok=True)
    partial = path.with_suffix(".part")
    partial.write_bytes(blob)
    partial.replace(path)   # a download cut short never leaves a half file under the final name
    return blob


def missing_weekdays(rows: list[list], first: date, last: date) -> list[str]:
    """Monday-to-Friday UTC days in the period with no replayable minute (a holiday, or data that is missing)."""

    have = {datetime.fromtimestamp(int(r[0]) / 1000, UTC).date() for r in rows}
    days = (first + timedelta(days=n) for n in range((last - first).days + 1))
    return [d.isoformat() for d in days if d.weekday() < 5 and d not in have]


def history(pair: str, first: date, last: date, cache: Path, opener: Opener = _http) -> list[list]:
    """Rows ``[open_ms, bid o, h, l, c, volume, close_ms, ask o, h, l, c]`` for every minute of the forex week
    that has both a BID and an ASK candle with ask >= bid. Minutes outside the session are dropped."""

    if pair not in FOREX_UNIVERSE:
        raise ValueError(f"{pair} is not in the forex universe {FOREX_UNIVERSE}")
    rows: list[list] = []
    day = first
    while day <= last:
        bid = decode_bi5(fetch_day(pair, day, "BID", cache, opener), day)
        ask = {r[0]: r for r in decode_bi5(fetch_day(pair, day, "ASK", cache, opener), day)}
        for open_ms, o, h, low, c, volume in bid:
            other = ask.get(open_ms)
            if other is None or Decimal(other[1]) < Decimal(o) or Decimal(other[4]) < Decimal(c):
                continue
            if not is_forex_market_open(datetime.fromtimestamp(open_ms / 1000, UTC)):
                continue
            rows.append([open_ms, o, h, low, c, volume, open_ms + MINUTE_MS - 1, *other[1:5]])
        day += timedelta(days=1)
    return rows


# ---------------------------------------------------------------- replay


@dataclass
class FxTrade(bt.Trade):
    """A forex position's lifetime. ``cost`` is the entry notional; for a short it is what the sale brought in."""

    side: str = "LONG"
    spread_cost: Decimal = ZERO     # half the quoted spread on each fill (already inside ``net``)
    slippage_cost: Decimal = ZERO   # the assumed slippage on each fill (already inside ``net``)

    @property
    def net(self) -> Decimal:
        gross = self.quantity * self.exit_price - self.cost
        return (gross if self.side == "LONG" else -gross) - self.entry_fee - self.exit_fee


@dataclass
class FxResult(bt.Result):
    """``bt.Result`` plus the margin book's closing figures (open positions still hold their margin)."""

    status: str = EXPLORATORY       # a replay is never evidence
    evidence_eligible: bool = False
    cash: Decimal = ZERO
    equity: Decimal = ZERO          # realized only
    max_drawdown: Decimal = ZERO    # of the marked equity (cash + margin + open P&L), checked every held minute
    stop_outs: int = 0
    weekend_closes: list[str] = field(default_factory=list)   # the moments a close-out ran
    held_over_close: int = 0        # positions carried through a closure: no priced minute in the close-out window


@dataclass
class _Open:
    symbol: str
    side: str
    bucket: str
    qty: Decimal
    entry: Decimal            # fill price
    margin: Decimal
    fee: Decimal
    spread_cost: Decimal
    slippage_cost: Decimal
    when: str
    entry_ms: int
    confidence: Decimal
    stop: Decimal | None = None

    @property
    def notional(self) -> Decimal:
        return self.qty * self.entry

    def unrealized(self, bid: Decimal, ask: Decimal) -> Decimal:
        """Against the price the position would close at: a long at the BID, a short at the ASK."""
        return self.qty * (bid - self.entry) if self.side == "LONG" else self.qty * (self.entry - ask)


def _quotes(row: list, open_: bool, spread_mult: Decimal) -> tuple[Decimal, Decimal]:
    """(bid, ask) of a row's open or close, the spread widened around the mid by ``spread_mult``."""
    bid = Decimal(str(row[BID_OPEN if open_ else BID_CLOSE]))
    ask = Decimal(str(row[ASK_OPEN if open_ else ASK_CLOSE]))
    if spread_mult != 1:
        mid, half = (bid + ask) / 2, (ask - bid) / 2 * spread_mult
        bid, ask = mid - half, mid + half
    return bid, ask


def replay(data: dict[str, list[list]], *, step: int = 15, brain_factory=None, capital: Decimal = bt.CAPITAL,
           leverage: int = FOREX_LEVERAGE, shorts: bool = True, commission_rate: Decimal | float | str = 0,
           spread_mult: Decimal | float | str = 1, slippage_bps: int = 0, min_hold_min: int = 0,
           exit_confirm: int = 1, trend_ema_hours: int = 0, atr_stop: Decimal | float = 0,
           risk_per_trade: Decimal | float = 0, cost_gate: Decimal | float = 0,
           fusion_fix: bool = False) -> FxResult:
    """Replay ``data`` (rows from ``history``). The defaults are the forex runtime's rules with the quoted spread
    as the only cost. Research switches mirror ``tools.backtest_replay.replay`` and are side-aware:

    - ``min_hold_min`` / ``exit_confirm``: a signal exit waits for the position's age / that many exit signals in a
      row. Protective exits (stop, close-out, stop-out) never wait.
    - ``trend_ema_hours``: a long only above, a short only below, the EMA of that many completed 1-hour closes.
    - ``atr_stop``: exit after two closes beyond entry -/+ atr_stop x ATR(14, 1-hour), fixed at entry.
    - ``risk_per_trade`` (needs ``atr_stop``): size so that a stop loses at most that fraction of equity.
    - ``cost_gate``: new risk only when 2 x ATR / price is at least cost_gate x the round-trip cost.
    Shorts need a margin book: ``shorts=True`` with ``leverage=1`` is refused, as RiskPolicy refuses it.

    The brain decides every ``step`` minutes. The stop-out and the close-out are checked on every replayed minute,
    as the runtime's exit guard checks them every cycle."""

    if brain_factory is None:
        from ai.core.atlas_brain import AtlasBrain
        brain_factory = AtlasBrain
    if fusion_fix:
        base_factory = brain_factory

        def brain_factory():
            brain = base_factory()
            fusion = getattr(brain, "agents", None)
            if fusion is not None:
                fusion.full_weight_denominator = True
            return brain
    capital = Decimal(str(capital))
    # the switches main.py turns on for the real runtime: open losses count in the daily-loss limit, capital sleeves
    policy = RiskPolicy(total_capital=capital, quote_currencies=("USD",), leverage=leverage, shorts_enabled=shorts,
                        count_unrealized_in_daily_loss=True, sleeves_enabled=True)
    risk = RiskEngine(policy)
    commission, spread_mult = Decimal(str(commission_rate)), Decimal(str(spread_mult))
    slip = Decimal(slippage_bps) / Decimal(10000)
    atr_stop, risk_per_trade, cost_gate = (Decimal(str(v)) for v in (atr_stop, risk_per_trade, cost_gate))
    if commission < 0 or spread_mult < 0 or slip < 0:
        raise ValueError("costs must not be negative")
    if step < 1:
        raise ValueError("step must be at least 1 minute")
    result = FxResult()
    data = bt._align(data)
    length = min((len(rows) for rows in data.values()), default=0)
    clock = next(iter(data.values()), [])
    ledger = {"cash": capital, "equity": capital, "peak": capital, "marked_peak": capital}
    realized_by_day: dict[str, Decimal] = {}
    holdings: dict[str, _Open] = {}
    streak: dict[str, tuple[str, int]] = {}

    def count(table: dict[str, int], code: str) -> None:
        table[code] = table.get(code, 0) + 1

    def close(pos: _Open, bid: Decimal, ask: Decimal, day: str, when: str, reason: str) -> None:
        quote = bid if pos.side == "LONG" else ask
        fill = quote * (1 - slip) if pos.side == "LONG" else quote * (1 + slip)
        fee = pos.qty * fill * commission
        gross = pos.qty * (fill - pos.entry) if pos.side == "LONG" else pos.qty * (pos.entry - fill)
        realized = gross - pos.fee - fee
        ledger["cash"] += pos.margin + gross - fee
        ledger["equity"] += realized
        ledger["peak"] = max(ledger["peak"], ledger["equity"])
        realized_by_day[day] = realized_by_day.get(day, ZERO) + realized
        result.trades.append(FxTrade(
            pos.symbol, pos.when, pos.entry, pos.qty, pos.notional, pos.fee, pos.bucket, False, when, fill, fee,
            reason, pos.confidence, "UNKNOWN", pos.side, pos.spread_cost + pos.qty * (ask - bid) / 2,
            pos.slippage_cost + pos.qty * quote * slip))
        count(result.exit_reasons, reason)
        del holdings[pos.symbol]

    def marks(end: int) -> dict[str, tuple[Decimal, Decimal]]:
        return {s: _quotes(data[s][end - 1], False, spread_mult) for s in holdings}

    def floating(quotes: dict[str, tuple[Decimal, Decimal]]) -> dict[str, Decimal]:
        return {s: p.unrealized(*quotes[s]) for s, p in holdings.items()}

    def track(unrealized: Decimal) -> None:
        """The worst fall of the marked equity (cash + margin + open P&L) from its own peak."""
        marked = ledger["cash"] + sum((p.margin for p in holdings.values()), ZERO) + unrealized
        ledger["marked_peak"] = max(ledger["marked_peak"], marked)
        result.max_drawdown = max(result.max_drawdown, ledger["marked_peak"] - marked)

    def protect(end: int) -> None:
        """The stop-out and the close-out, on the minute that closed at row ``end - 1`` (never a later price to
        decide). The exit fills at the next minute's open; with no next minute, at that minute's own close."""
        row = clock[end - 1]
        close_ms = int(row[CLOSE_MS])
        cutoff = datetime.fromtimestamp((close_ms + 1000) / 1000, UTC)
        quotes = marks(end)
        unrealized = floating(quotes)
        total = sum(unrealized.values(), ZERO)
        used = sum((p.margin for p in holdings.values()), ZERO)
        reason = None
        if (ledger["cash"] + used + total) / used <= STOP_OUT_MARGIN_LEVEL:
            reason = "STOP_OUT"
            result.stop_outs += 1
        elif is_forex_pre_close(cutoff, WEEKEND_CLOSE_MINUTES) is not False:
            reason = "WEEKEND_CLOSE"
            result.weekend_closes.append(cutoff.isoformat())
        if reason:
            nxt_ok = end < length and int(clock[end][0]) == close_ms + 1
            for symbol in sorted(holdings, key=lambda s: unrealized[s]):   # largest loss first
                bid, ask = _quotes(data[symbol][end], True, spread_mult) if nxt_ok else quotes[symbol]
                close(holdings[symbol], bid, ask, cutoff.date().isoformat(), cutoff.isoformat(), reason)
            total = ZERO
        elif end < length and int(clock[end][0]) - close_ms > CLOSURE_GAP_MS:
            # the market closed (or the data stops) with no priced minute inside the close-out window: the runtime
            # would hold too (never a sale at a guessed price); it is counted, never hidden
            result.held_over_close += len(holdings)
        track(total)

    def state(day: str, quotes: dict[str, tuple[Decimal, Decimal]]) -> RiskState | None:
        """What the runtime hands RiskEngine: marked (never optimistic) equity and the open P&L."""
        positions = tuple(PositionExposure(p.symbol, p.qty, p.entry, p.notional, risk_bucket=p.bucket, side=p.side)
                          for p in holdings.values())
        committed = sum((p.quote_exposure for p in positions), ZERO)
        unrealized = sum(floating(quotes).values(), ZERO)
        equity = ledger["equity"] + min(unrealized, ZERO)
        if equity <= 0:
            return None
        return RiskState(positions, committed, realized_by_day.get(day, ZERO), ledger["peak"], equity,
                         True, datetime.now(UTC).date().isoformat(), policy.version, unrealized_pnl=unrealized)

    with tempfile.TemporaryDirectory() as scratch, contextlib.redirect_stdout(io.StringIO()):
        cwd = os.getcwd()
        os.chdir(scratch)  # AtlasBrain bootstraps CWD-relative memory files
        try:
            brain = bt._CapturingBrain(brain_factory())
            loops = {}
            for symbol in data:
                feed = bt._WindowFeed()
                loops[symbol] = (feed, MarketLoop(brain=brain, market_feed=feed, execution=None, symbols=[symbol],
                                                  market_risk_provider=MarketRiskRegimeProvider()))
            checked = bt.WINDOW - 1
            for end in range(bt.WINDOW, length, step):
                for minute in range(checked + 1, end + 1):
                    if holdings:
                        protect(minute)
                checked = end
                close_ms = int(clock[end - 1][CLOSE_MS])
                cutoff = datetime.fromtimestamp((close_ms + 1000) / 1000, UTC)
                day, when = cutoff.date().isoformat(), cutoff.isoformat()
                entry_blocked = is_forex_pre_close(cutoff, PRE_CLOSE_MINUTES) is not False

                for symbol, (feed, loop) in loops.items():
                    rows = data[symbol]
                    feed.rows = [r[:7] for r in rows[end - bt.WINDOW:end]]
                    price = Decimal(str(feed.rows[-1][BID_CLOSE]))
                    nxt = rows[end] if end < len(rows) else None
                    fillable = nxt is not None and int(nxt[0]) == close_ms + 1   # the next minute, not after a gap
                    pos = holdings.get(symbol)

                    if atr_stop > 0 and pos is not None and pos.stop is not None:
                        closes = [Decimal(str(r[BID_CLOSE])) for r in feed.rows[-bt.STOP_CONFIRM_CANDLES:]]
                        beyond = (all(c < pos.stop for c in closes) if pos.side == "LONG"
                                  else all(c > pos.stop for c in closes))
                        if beyond and fillable:
                            close(pos, *_quotes(nxt, True, spread_mult), day, when, "ATR_STOP")
                            pos = None

                    brain.last = None
                    loop.process_symbol(symbol, processing_cutoff=cutoff)
                    if brain.last is None:
                        continue
                    decision = loop.normalize_decision(raw_decision=brain.last, symbol=symbol,
                                                       price=float(price), market_data={})
                    if not decision:
                        continue
                    result.decisions += 1
                    action = decision.get("action")
                    confidence = Decimal(str(decision.get("confidence", 0)))
                    bucket = normalize_risk(decision.get("risk", decision.get("risk_level")))
                    previous = streak.get(symbol, ("", 0))
                    streak[symbol] = (action, previous[1] + 1 if previous[0] == action else 1)
                    if action not in ("BUY", "SELL") or not fillable:
                        continue
                    bid, ask = _quotes(nxt, True, spread_mult)

                    if pos is not None:
                        exits = action == ("SELL" if pos.side == "LONG" else "BUY")
                        if exits and confidence >= bt.EXECUTION_GATE:
                            if (close_ms - pos.entry_ms) / MINUTE_MS < min_hold_min or streak[symbol][1] < exit_confirm:
                                count(result.exit_reasons, "EXIT_DEFERRED")
                                continue
                            close(pos, bid, ask, day, when, "SELL_SIGNAL" if pos.side == "LONG" else "BUY_SIGNAL")
                        continue

                    # --- new risk: a BUY opens a long, a SELL opens a short (Task 026)
                    side = "LONG" if action == "BUY" else "SHORT"
                    if side == "SHORT" and not shorts:
                        continue
                    result.buy_signals += 1
                    if entry_blocked:
                        count(result.buy_rejections, "PRE_CLOSE")
                        continue
                    bars = bt._hourly_bars(rows, end) if (trend_ema_hours or atr_stop or cost_gate) else []
                    if trend_ema_hours:
                        ema = bt._ema([b[2] for b in bars], trend_ema_hours)
                        if ema is None or (price <= ema if side == "LONG" else price >= ema):
                            count(result.buy_rejections, "TREND_FILTER")
                            continue
                    if confidence < bt.EXECUTION_GATE:
                        count(result.buy_rejections, "EXECUTION_GATE")
                        continue
                    try:
                        sizing = risk.sizing_bucket(bucket, confidence / 100)
                    except Exception:
                        count(result.buy_rejections, f"BUCKET_{bucket}")
                        continue
                    amount = policy.exposure_capital * policy.buckets[sizing].max_allocation_pct   # notional
                    atr = bt._atr(bars) if (atr_stop or cost_gate) else None
                    if cost_gate:
                        # the spread known at the decision: the decision candle's own closing quotes
                        seen_bid, seen_ask = _quotes(rows[end - 1], False, spread_mult)
                        round_trip = (seen_ask - seen_bid) * 2 / (seen_ask + seen_bid) + 2 * commission + 2 * slip
                        if atr is None or 2 * atr / price < cost_gate * round_trip:
                            count(result.buy_rejections, "EXPECTED_MOVE_BELOW_COST")
                            continue
                    if atr_stop and atr is None:
                        count(result.buy_rejections, "ATR_UNAVAILABLE")
                        continue
                    if risk_per_trade and atr:
                        distance = atr_stop * atr / price
                        if distance > 0:
                            amount = min(amount, ledger["equity"] * risk_per_trade / distance)
                    # the margin book: new risk spends only cash less any unrealized loss (Task 025)
                    quotes = marks(end)
                    spendable = ledger["cash"] + min(sum(floating(quotes).values(), ZERO), ZERO)
                    amount = min(amount, spendable * leverage / (1 + commission * leverage))
                    base = (amount / price).quantize(Decimal("0.01"), rounding=ROUND_DOWN) if amount > 0 else ZERO
                    if base <= 0:
                        count(result.buy_rejections, "NO_CASH")
                        continue
                    current = state(day, quotes)
                    if current is None:
                        count(result.buy_rejections, "EQUITY_NOT_POSITIVE")
                        continue
                    request = RiskRequest(symbol=symbol, action=action, confidence=confidence / 100,
                                          requested_quote_allocation=base * price, execution_price=price,
                                          risk_bucket=bucket, base_quantity=base, position_side=side)
                    verdict = risk.evaluate(request, current)
                    if not verdict.approved:
                        count(result.buy_rejections, verdict.reason_code)
                        continue
                    quote = ask if side == "LONG" else bid
                    fill = quote * (1 + slip) if side == "LONG" else quote * (1 - slip)
                    notional = base * fill
                    fee = notional * commission
                    margin = notional / leverage
                    ledger["cash"] -= margin + fee
                    stop = None
                    if atr_stop and atr:
                        stop = price - atr_stop * atr if side == "LONG" else price + atr_stop * atr
                    holdings[symbol] = _Open(symbol, side, sizing.value, base, fill, margin, fee,
                                             base * (ask - bid) / 2, base * quote * slip, when, close_ms,
                                             confidence, stop)
                track(sum(floating(marks(end)).values(), ZERO))
            for minute in range(checked + 1, length + 1):
                if holdings:
                    protect(minute)
            # a position still open at the end is valued as if closed on the last quotes (never hidden)
            for symbol, pos in holdings.items():
                row = data[symbol][length - 1]
                bid, ask = _quotes(row, False, spread_mult)
                quote = bid if pos.side == "LONG" else ask
                fill = quote * (1 - slip) if pos.side == "LONG" else quote * (1 + slip)
                stamp = datetime.fromtimestamp(int(row[CLOSE_MS]) / 1000, UTC).isoformat()
                result.open_trades.append(FxTrade(
                    pos.symbol, pos.when, pos.entry, pos.qty, pos.notional, pos.fee, pos.bucket, False, "", ZERO,
                    ZERO, "", pos.confidence, "UNKNOWN", pos.side, pos.spread_cost, pos.slippage_cost))
                result.marked_open.append(FxTrade(
                    pos.symbol, pos.when, pos.entry, pos.qty, pos.notional, pos.fee, pos.bucket, False, stamp, fill,
                    pos.qty * fill * commission, "MARK_TO_MARKET", pos.confidence, "UNKNOWN", pos.side,
                    pos.spread_cost + pos.qty * (ask - bid) / 2, pos.slippage_cost + pos.qty * quote * slip))
            result.cash, result.equity = ledger["cash"], ledger["equity"]
        finally:
            os.chdir(cwd)
    return result


# ---------------------------------------------------------------- comparison

VARIANTS: dict[str, dict[str, Any]] = {
    "referans (gerçek spread, long+short, 1:2)": {},
    "sadece long (1:2)": {"shorts": False},
    "sadece long, kaldıraçsız (1:1)": {"shorts": False, "leverage": 1},
    "min tutma 60 dk": {"min_hold_min": 60},
    "çıkış onayı 2": {"exit_confirm": 2},
    "1s trend filtresi EMA20": {"trend_ema_hours": 20},
    "ATR stop 2x": {"atr_stop": 2},
    "ATR stop 2x + %1 risk": {"atr_stop": 2, "risk_per_trade": 0.01},
    "maliyet kapısı 3x": {"cost_gate": 3},
    "füzyon düzeltmesi": {"fusion_fix": True},
    # cost sensitivity: assumptions, not measurements (commission is UNKNOWN until the owner's MT5 test)
    "maliyet: spread x3 (perakende varsayımı)": {"spread_mult": 3},
    "maliyet: + komisyon 0.35 bps/yön (varsayım)": {"commission_rate": "0.000035"},
    "maliyet: runtime'ın bugünkü kripto ücreti (%0.1/yön + 5 bps)": {"commission_rate": "0.001", "slippage_bps": 5},
}
REFERENCE = "referans (gerçek spread, long+short, 1:2)"


def window_row(result: bt.Result) -> dict[str, Any]:
    """One variant on one window. Closed trades and window-end marks both count, so a held loser is not hidden."""

    trades = [*result.trades, *result.marked_open]
    nets = [t.net for t in trades]
    spread = sum((t.spread_cost for t in trades), ZERO)
    slippage = sum((t.slippage_cost for t in trades), ZERO)
    fees = sum((t.entry_fee + t.exit_fee for t in trades), ZERO)
    net = sum(nets, ZERO)
    return {"status": EXPLORATORY, "evidence_eligible": False,
            "decisions": result.decisions, "entry_signals": result.buy_signals, "trades": len(trades),
            "longs": sum(1 for t in trades if t.side == "LONG"), "shorts": sum(1 for t in trades if t.side == "SHORT"),
            "wins": sum(1 for n in nets if n > 0), "net_pnl": net, "before_costs": net + spread + slippage + fees,
            "spread_cost": spread, "slippage_cost": slippage, "commission": fees,
            "max_drawdown": getattr(result, "max_drawdown", ZERO),   # marked equity, checked every held minute
            "stop_outs": getattr(result, "stop_outs", 0), "held_over_close": getattr(result, "held_over_close", 0),
            "marked_open": len(result.marked_open), "exit_reasons": dict(sorted(result.exit_reasons.items())),
            "rejections": dict(sorted(result.buy_rejections.items()))}


def _one(job: tuple) -> dict[str, Any]:
    part, step, brain_factory, kw = job
    logging.getLogger("AtlasAI.MarketLoop").setLevel(logging.ERROR)
    return window_row(replay(part, step=step, brain_factory=brain_factory, **kw))


def compare(data: dict[str, list[list]], windows: int, step: int, *, brain_factory=None,
            variants: dict[str, dict[str, Any]] | None = None, jobs: int = 1, embargo: int = 0) -> dict[str, Any]:
    """Every variant on every window. No verdict is given: without a sealed registration the run is EXPLORATORY."""

    from tools.strategy_compare import dataset_manifest, split

    variants = VARIANTS if variants is None else variants
    data = bt._align(data)   # one clock for every pair before the windows are cut
    parts = split(data, windows, embargo)
    work = [(name, i, (part, step, brain_factory, kw)) for name, kw in variants.items() for i, part in enumerate(parts)]
    done: dict[tuple[str, int], dict[str, Any]] = {}
    if jobs > 1:
        from concurrent.futures import ProcessPoolExecutor, as_completed

        with ProcessPoolExecutor(max_workers=jobs) as pool:
            futures = {pool.submit(_one, job): (name, i) for name, i, job in work}
            for n, future in enumerate(as_completed(futures), 1):
                done[futures[future]] = future.result()
                print(f"  {n}/{len(work)} bitti ({futures[future][0]})", file=sys.stderr, flush=True)
    else:
        for name, i, job in work:
            done[(name, i)] = _one(job)
    return {"study": {"status": EXPLORATORY, "evidence_eligible": False, "reason": "NO_SEALED_PREREGISTRATION"},
            "windows": windows, "step_minutes": step, "embargo": embargo, "dataset": dataset_manifest(data),
            "variants": {name: dict(kw) for name, kw in variants.items()},
            "table": {name: [done[(name, i)] for i in range(len(parts))] for name in variants},
            "multiple_testing": {"variants": len(variants),
                                 "note": "the best of many variants can be luck; nothing here is a verdict"}}


def render(result: dict[str, Any]) -> str:
    lines = ["FOREX STRATEGY COMPARISON - EXPLORATORY, NOT EVIDENCE (no sealed registration; commission and swap UNKNOWN)",
             f"windows: {result['windows']}  step: {result['step_minutes']} min  "
             f"dataset: {result['dataset']['dataset_sha256'][:16]}", ""]
    head = (f"{'variant':<62}{'trades':>7}{'L/S':>9}{'win%':>6}{'before':>10}{'spread':>9}{'slip':>8}{'comm.':>9}"
            f"{'net':>10}{'maxDD*':>9}  per-window net")
    lines.append(head)
    for name, rows in result["table"].items():
        trades = sum(r["trades"] for r in rows)
        total = {k: sum((Decimal(str(r[k])) for r in rows), ZERO) for k in ("before_costs", "spread_cost", "slippage_cost", "commission", "net_pnl")}
        wins = sum(r["wins"] for r in rows)
        lines.append(
            f"{name:<62}{trades:>7}{sum(r['longs'] for r in rows):>5}/{sum(r['shorts'] for r in rows):<3}"
            f"{(100 * wins / trades if trades else 0):>6.0f}{total['before_costs']:>10.2f}{total['spread_cost']:>9.2f}"
            f"{total['slippage_cost']:>8.2f}{total['commission']:>9.2f}{total['net_pnl']:>10.2f}{max(Decimal(str(r['max_drawdown'])) for r in rows):>9.2f}  "
            + " ".join(f"{Decimal(str(r['net_pnl'])):+.2f}" for r in rows))
    lines.append("")
    lines.append("* maxDD: the worst fall of the marked equity (cash + margin + open P&L) inside one window.")
    held = sum(r.get("held_over_close", 0) for rows in result["table"].values() for r in rows)
    if held:
        lines.append(f"WARNING: {held} position(s) were carried through a market closure (no priced minute in the "
                     "close-out window).")
    return "\n".join(lines)


def main(argv: list[str] | None = None, opener: Opener = _http) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--cache", required=True, help="directory for the downloaded history, outside the repository")
    parser.add_argument("--first", required=True, help="first UTC day, YYYY-MM-DD")
    parser.add_argument("--last", required=True, help="last UTC day, YYYY-MM-DD")
    parser.add_argument("--symbols", nargs="+", default=list(FOREX_UNIVERSE))
    parser.add_argument("--windows", type=int, default=3)
    parser.add_argument("--step", type=int, default=15)
    parser.add_argument("--embargo", type=int, default=0)
    parser.add_argument("--jobs", type=int, default=1)
    parser.add_argument("--output", help="write the full result as JSON here (outside the repository)")
    args = parser.parse_args(argv)
    cache = Path(args.cache).resolve()
    repo = Path(__file__).resolve().parents[1]
    for path in (cache, Path(args.output).resolve() if args.output else None):
        if path is not None and (path == repo or repo in path.parents):
            parser.error("the history cache and the output must be outside the repository (the data is not ours to commit)")
    first, last = date.fromisoformat(args.first), date.fromisoformat(args.last)
    data = {symbol: history(symbol, first, last, cache, opener) for symbol in args.symbols}
    result = compare(data, args.windows, args.step, jobs=args.jobs, embargo=args.embargo)
    result["period"] = {"first": args.first, "last": args.last, "symbols": list(args.symbols), "source": "Dukascopy",
                        "weekdays_without_data": {s: missing_weekdays(rows, first, last) for s, rows in data.items()}}
    print(render(result))
    for symbol, days in result["period"]["weekdays_without_data"].items():
        if days:
            print(f"{symbol}: no data on {len(days)} weekday(s): {', '.join(days)}")
    if args.output:
        Path(args.output).write_text(json.dumps(result, indent=1, default=str, ensure_ascii=False), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
