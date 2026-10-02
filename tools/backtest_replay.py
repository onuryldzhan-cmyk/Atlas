"""Macro-neutral replay backtest of Atlas's real decision chain (Phase 4 research).

Registry v5.30 (owner, recommended option for Q5). Research tool only: it
never touches the runtime, the state root or any order path.

What is replayed - the REAL components, not a re-implementation:
  MarketLoop.process_symbol (technical analysis, closed-candle handling,
  realized-volatility regime) -> AtlasBrain.analyze_and_decide (fusion,
  confidence, regime-derived risk_level) -> RiskEngine.evaluate (policy
  floors, buckets, optional EXP-001) with RiskEngine.sizing_bucket sizing.

What is NOT available offline and is therefore stated, not faked:
  * macro and sentiment evidence are EXCLUDED (as when their providers are
    down - a real, tested runtime state). Missing Macro also caps the risk
    bucket above LOW (NB-4), so this replay is on the conservative side.
  * fills at the decision candle's close, no slippage; fee 0.1% per side
    (PAPER_FEE_RATE_PER_SIDE); SELL/BUY need confidence >= the execution
    gate (60) like the runtime.

Usage:
  python -m tools.backtest_replay [--days 7] [--step 15] [--symbols ...] [--exp001]
"""

from __future__ import annotations

import argparse
import contextlib
import io
import logging
import os
import sys
import tempfile
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import ROUND_DOWN, Decimal
from typing import Callable

from core.execution_manager import PAPER_FEE_RATE_PER_SIDE
from core.execution_models import normalize_risk
from core.market_loop import MarketLoop
from core.market_risk_regime import MarketRiskRegimeProvider
from core.risk_engine import (
    EXP001_PAPER_CONFIDENCE_EXPERIMENT,
    PositionExposure,
    RiskEngine,
    RiskPolicy,
    RiskRequest,
    RiskState,
)

WINDOW = 200                      # candles MarketLoop analyses per cycle
EXECUTION_GATE = Decimal("60")    # ExecutionManager minimum confidence (BUY and SELL)
CAPITAL = Decimal("10000")
DEFAULT_SYMBOLS = ("BTCUSDT", "ETHUSDT", "BNBUSDT", "SOLUSDT", "XRPUSDT")

Fetcher = Callable[[str, int], list[list]]


class _WindowFeed:
    def __init__(self) -> None:
        self.rows: list[list] = []

    def candles(self, symbol, interval="1m", limit=500):
        return self.rows[-limit:]


class _CapturingBrain:
    def __init__(self, brain) -> None:
        self.brain = brain
        self.last = None

    def analyze_and_decide(self, symbol, market_data):
        self.last = self.brain.analyze_and_decide(symbol, market_data)
        return self.last


@dataclass
class Trade:
    """One position lifetime (possibly several tranches in, several sells out)."""

    symbol: str
    entry_time: str
    entry_price: Decimal          # average entry
    quantity: Decimal             # total bought
    cost: Decimal                 # total quote spent on the asset (excl. fees)
    entry_fee: Decimal
    bucket: str
    experiment: bool
    exit_time: str = ""
    exit_price: Decimal = Decimal("0")   # average exit (proceeds / quantity)
    exit_fee: Decimal = Decimal("0")
    exit_reason: str = ""
    entry_confidence: Decimal = Decimal("0")  # lesson book (2026-10-02): what Atlas believed at entry
    entry_regime: str = "UNKNOWN"             # tools.regime_engine on the hourly closes known at entry

    @property
    def net(self) -> Decimal:
        return self.quantity * self.exit_price - self.cost - self.entry_fee - self.exit_fee


@dataclass
class Position:
    symbol: str
    bucket: str
    experiment: bool
    entry_time: str
    target_allocation: Decimal
    qty: Decimal = Decimal("0")          # currently held
    qty_bought: Decimal = Decimal("0")
    cost_total: Decimal = Decimal("0")
    fees_in: Decimal = Decimal("0")
    cost_open: Decimal = Decimal("0")    # cost basis of the held quantity
    fees_open: Decimal = Decimal("0")    # entry fees of the held quantity
    proceeds: Decimal = Decimal("0")
    fees_out: Decimal = Decimal("0")
    tranches: int = 0
    last_tranche_ms: int = 0
    peak: Decimal = Decimal("0")
    tp1: bool = False
    tp2: bool = False
    entry_ms: int = 0
    entry_confidence: Decimal = Decimal("0")
    entry_regime: str = "UNKNOWN"

    @property
    def avg_entry(self) -> Decimal:
        return self.cost_open / self.qty if self.qty > 0 else Decimal("0")

    def as_trade(self, exit_time: str = "", reason: str = "") -> Trade:
        exit_price = self.proceeds / self.qty_bought if self.qty_bought > 0 and exit_time else Decimal("0")
        return Trade(self.symbol, self.entry_time, self.cost_total / self.qty_bought if self.qty_bought else Decimal("0"),
                     self.qty_bought, self.cost_total, self.fees_in, self.bucket, self.experiment,
                     exit_time, exit_price, self.fees_out, reason, self.entry_confidence, self.entry_regime)


@dataclass
class Result:
    trades: list[Trade] = field(default_factory=list)
    open_trades: list[Trade] = field(default_factory=list)
    decisions: int = 0
    buy_signals: int = 0
    buy_rejections: dict[str, int] = field(default_factory=dict)
    tranche_adds: int = 0
    partial_sells: int = 0
    exit_reasons: dict[str, int] = field(default_factory=dict)
    signals: list[dict] = field(default_factory=list)  # record_signals=True: every BUY/SELL decision and its outcome


# Owner-approved parameters (registry v5.32, governance/ATLAS_STAGED_ENTRY_EXIT_PROPOSAL_v1.0.md)
TRANCHES = (Decimal("0.40"), Decimal("0.30"), Decimal("0.30"))
TRANCHE_MIN_GAP_MS = 15 * 60_000
TAKE_PROFIT_1 = Decimal("0.015")
TAKE_PROFIT_2 = Decimal("0.03")
TRAILING = Decimal("0.015")
HARD_STOP = Decimal("0.03")
STOP_CONFIRM_CANDLES = 2
# Owner: "10 TL -> 5 düşük / 3.5 orta / 1.5 yüksek" - capital sleeves across ALL symbols
SLEEVES = {"LOW": Decimal("0.50"), "MEDIUM": Decimal("0.35"), "HIGH": Decimal("0.15")}
# a remainder below the venue minimum notional (5 USDT) means the sleeve is full
SLEEVE_MIN_ORDER = Decimal("5")


def _state(holdings: dict, realized_today: Decimal, equity: Decimal, peak: Decimal, day: str,
           exclude: str | None = None) -> RiskState:
    """The durable-state view the runtime would hand RiskEngine (registry v5.31):
    every open position across symbols, today's realized net P&L and equity
    (realized-only: open positions are carried at cost, stated in the report)."""

    positions = tuple(
        PositionExposure(p.symbol, p.qty, p.avg_entry, p.qty * p.avg_entry)
        for p in holdings.values() if p.qty > 0 and p.symbol != exclude
    )
    committed = sum((p.quote_exposure for p in positions), Decimal("0"))
    return RiskState(positions, committed, realized_today, peak, equity, True, day,
                     RiskPolicy(total_capital=CAPITAL).version)


def _hourly_bars(rows: list[list], end: int) -> list[tuple[Decimal, Decimal, Decimal]]:
    """(high, low, close) of complete 60-minute bars ending at rows[end - 1] (no look-ahead)."""

    bars = []
    for stop in range(end, 59, -60):
        chunk = rows[stop - 60:stop]
        bars.append((max(Decimal(str(r[2])) for r in chunk), min(Decimal(str(r[3])) for r in chunk),
                     Decimal(str(chunk[-1][4]))))
    return list(reversed(bars))


def _entry_regime(bars: list[tuple[Decimal, Decimal, Decimal]]) -> str:
    """Regime label from closed hourly bars only (no lookahead); UNKNOWN when it cannot be classified."""
    from tools.regime_engine import classify

    try:
        return str(classify([float(b[2]) for b in bars]).get("regime", "UNKNOWN"))
    except Exception:  # noqa: BLE001 - a label failure must never stop the replay
        return "UNKNOWN"


SIGNAL_HORIZONS_MIN = (60, 240)  # outcome horizons for the lesson book
REGIME_LOOKBACK_MIN = 30 * 24 * 60  # regime from the last 30 days of closed hourly bars


def _signal_outcome(rows: list[list], end: int, price: Decimal, slip: Decimal, fee: Decimal) -> dict:
    """Net return after both fees and slippage of buying at this close and selling h minutes later.

    The outcome is a LABEL computed after the fact for research; the decision itself only ever saw
    rows[:end] (MarketLoop's cutoff). None when the series ends before the horizon.
    """
    out = {}
    for h in SIGNAL_HORIZONS_MIN:
        idx = end - 1 + h
        if idx >= len(rows):
            out[f"net_{h}m"] = None
            continue
        exit_px = Decimal(str(rows[idx][4]))
        gross_in = price * (1 + slip)
        out[f"net_{h}m"] = (exit_px * (1 - slip) * (1 - fee)) / (gross_in * (1 + fee)) - 1
    return out


def write_signals_csv(path: str, signals: list[dict]) -> int:
    import csv

    cols = ["symbol", "time", "action", "confidence", "bucket", "regime"] + [f"net_{h}m" for h in SIGNAL_HORIZONS_MIN]
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(cols)
        for sig in signals:
            w.writerow(["" if sig.get(c) is None else (format(sig[c], "f") if isinstance(sig[c], Decimal) else sig[c])
                        for c in cols])
    return len(signals)


def write_trades_csv(path: str, trades: list[Trade]) -> int:
    """One row per closed replay trade for the lesson book (net is after both fees)."""
    import csv

    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["symbol", "entry_time", "exit_time", "bucket", "entry_confidence", "entry_regime",
                    "exit_reason", "cost", "fees", "net"])
        for t in trades:
            w.writerow([t.symbol, t.entry_time, t.exit_time, t.bucket, format(t.entry_confidence, "f"), t.entry_regime,
                        t.exit_reason, format(t.cost, "f"), format(t.entry_fee + t.exit_fee, "f"), format(t.net, "f")])
    return len(trades)


def _ema(values: list[Decimal], period: int) -> Decimal | None:
    if len(values) < period:
        return None
    k = Decimal(2) / Decimal(period + 1)
    ema = sum(values[:period], Decimal("0")) / period
    for v in values[period:]:
        ema = v * k + ema * (1 - k)
    return ema


def _atr(bars: list[tuple[Decimal, Decimal, Decimal]], period: int = 14) -> Decimal | None:
    if len(bars) < period + 1:
        return None
    trs = [max(h - l, abs(h - bars[i - 1][2]), abs(l - bars[i - 1][2])) for i, (h, l, _) in enumerate(bars) if i > 0]
    return sum(trs[-period:], Decimal("0")) / period


def _align(candles_by_symbol: dict[str, list[list]]) -> dict[str, list[list]]:
    """Keep only minutes every symbol has, so all symbols step through the
    same clock (the runtime processes all symbols each cycle)."""

    common = None
    for rows in candles_by_symbol.values():
        opens = {int(r[0]) for r in rows}
        common = opens if common is None else common & opens
    common = common or set()
    return {s: [r for r in rows if int(r[0]) in common] for s, rows in candles_by_symbol.items()}


def replay(candles_by_symbol: dict[str, list[list]], *, step: int = 15, exp001: bool = False,
           staged: bool = False, sleeves: bool = False, brain_factory=None,
           slippage_bps: int = 0, next_open_fill: bool = False,
           min_hold_min: int = 0, sell_confirm: int = 1,
           trend_ema_hours: int = 0, atr_stop: Decimal | float = 0, risk_per_trade: Decimal | float = 0,
           cost_gate: Decimal | float = 0, regime_filter: bool = False,
           fusion_fix: bool = False, record_signals: bool = False) -> Result:
    """Baseline (staged=False, sleeves=False) = today's runtime behaviour.
    staged=True adds the approved tranche entries, take-profit ladder, trailing
    stop and confirmed hard stop; sleeves=True caps each risk bucket's total
    open cost across all symbols at 50/35/15% of capital.

    Realism (registry v5.47, research only): slippage_bps fills every order
    that many basis points against the trader; next_open_fill fills at the
    NEXT candle's open instead of the decision candle's close (the runtime
    acts after the candle closes). Strategy research: min_hold_min ignores a
    SELL signal until the position is that old; sell_confirm requires that
    many consecutive SELL decisions. Staged protective exits are unaffected.
    Strategy research (v5.53): trend_ema_hours > 0 allows a BUY only when the
    price is above the EMA of that many completed 1-hour closes; atr_stop > 0
    closes a position after STOP_CONFIRM_CANDLES closes below
    entry - atr_stop x ATR(14, 1-hour) fixed at entry; risk_per_trade > 0
    (needs atr_stop) sizes so a stop-out loses at most that fraction of
    equity, never above the bucket's own allocation (risk-reducing only).
    All defaults reproduce the baseline exactly."""

    if brain_factory is None:
        from ai.core.atlas_brain import AtlasBrain
        brain_factory = AtlasBrain
    if fusion_fix:
        # research: audit F-1 full-weight denominator (proposals/2026-10-01_fusion_dissent_confidence_DESIGN.md)
        base_factory = brain_factory

        def brain_factory():
            brain = base_factory()
            fusion = getattr(brain, "agents", None)
            if fusion is not None:
                fusion.full_weight_denominator = True
            return brain
    result = Result()
    fee_rate = PAPER_FEE_RATE_PER_SIDE
    risk = RiskEngine(RiskPolicy(total_capital=CAPITAL))
    if exp001:
        # the experiment is held open for the whole replay (its clock is
        # pinned to its start); its 50-admission cap still applies
        risk.attach_experiment(EXP001_PAPER_CONFIDENCE_EXPERIMENT, prior_admissions=0,
                               clock=lambda: EXP001_PAPER_CONFIDENCE_EXPERIMENT.starts_at)
    data = _align(candles_by_symbol)
    length = min((len(rows) for rows in data.values()), default=0)
    ledger = {"cash": CAPITAL, "equity": CAPITAL, "peak": CAPITAL}
    realized_by_day: dict[str, Decimal] = {}
    holdings: dict[str, Position] = {}
    sell_streak: dict[str, int] = {}
    slip = Decimal(slippage_bps) / Decimal(10000)
    regime_cache: dict[tuple[str, int], str] = {}
    atr_stop, risk_per_trade = Decimal(str(atr_stop)), Decimal(str(risk_per_trade))
    # cost_gate > 0 (research, strategy framework layer 1): a new BUY needs the
    # expected move - 2 x ATR(14, 1-hour) / price, a ~2-4 h horizon - to be at
    # least cost_gate x the round-trip cost (2 x fee + 2 x slippage)
    cost_gate = Decimal(str(cost_gate))
    # regime_filter (research): a new BUY only when tools.regime_engine
    # classifies the coin's completed 1-hour closes as TREND_UP
    stop_level: dict[str, Decimal] = {}

    def reject(code: str) -> None:
        result.buy_rejections[code] = result.buy_rejections.get(code, 0) + 1

    def sell(pos: Position, fraction: Decimal, price: Decimal, day: str, when: str, reason: str) -> None:
        qty = pos.qty if fraction >= 1 else pos.qty * fraction
        if qty <= 0:
            return
        share = qty / pos.qty
        cost_part, fee_in_part = pos.cost_open * share, pos.fees_open * share
        gross = qty * price
        fee = gross * fee_rate
        pos.qty -= qty
        pos.cost_open -= cost_part
        pos.fees_open -= fee_in_part
        pos.proceeds += gross
        pos.fees_out += fee
        ledger["cash"] += gross - fee
        realized = gross - fee - cost_part - fee_in_part
        realized_by_day[day] = realized_by_day.get(day, Decimal("0")) + realized
        ledger["equity"] += realized
        ledger["peak"] = max(ledger["peak"], ledger["equity"])
        if pos.qty <= 0 or fraction >= 1:
            pos.qty = Decimal("0")
            result.trades.append(pos.as_trade(when, reason))
            result.exit_reasons[reason] = result.exit_reasons.get(reason, 0) + 1
            del holdings[pos.symbol]
        else:
            result.partial_sells += 1

    def sleeve_room(bucket: str) -> Decimal:
        used = sum((p.cost_open + p.fees_open for p in holdings.values() if p.bucket == bucket), Decimal("0"))
        return CAPITAL * SLEEVES.get(bucket, Decimal("0")) - used

    with tempfile.TemporaryDirectory() as scratch, contextlib.redirect_stdout(io.StringIO()):
        cwd = os.getcwd()
        os.chdir(scratch)  # AtlasBrain bootstraps CWD-relative memory files
        try:
            brain = _CapturingBrain(brain_factory())
            loops = {}
            for symbol in data:
                feed = _WindowFeed()
                loops[symbol] = (feed, MarketLoop(brain=brain, market_feed=feed, execution=None, symbols=[symbol],
                                                  market_risk_provider=MarketRiskRegimeProvider()))
            for end in range(WINDOW, length, step):
                for symbol, (feed, loop) in loops.items():
                    feed.rows = data[symbol][end - WINDOW:end]
                    close_ms = int(feed.rows[-1][6])
                    cutoff = datetime.fromtimestamp((close_ms + 1000) / 1000, UTC)
                    day = cutoff.date().isoformat()
                    when = cutoff.isoformat()
                    price = Decimal(str(feed.rows[-1][4]))
                    if price <= 0:
                        continue  # a corrupt candle is skipped, never traded on
                    fill_ref = price
                    if next_open_fill:
                        if end >= len(data[symbol]):
                            continue  # no next candle to fill on
                        fill_ref = Decimal(str(data[symbol][end][1]))
                    buy_fill, sell_fill = fill_ref * (1 + slip), fill_ref * (1 - slip)

                    # --- staged exit monitor (deterministic, before the decision)
                    pos = holdings.get(symbol)
                    if staged and pos is not None:
                        avg = pos.avg_entry
                        closes = [Decimal(str(r[4])) for r in feed.rows[-STOP_CONFIRM_CANDLES:]]
                        if all(c < avg * (1 - HARD_STOP) for c in closes):
                            sell(pos, Decimal("1"), sell_fill, day, when, "HARD_STOP")
                            pos = None
                        else:
                            pos.peak = max(pos.peak, price)
                            if not pos.tp1 and price >= avg * (1 + TAKE_PROFIT_1):
                                pos.tp1 = True
                                sell(pos, Decimal(1) / Decimal(3), sell_fill, day, when, "TAKE_PROFIT_1")
                            elif pos.tp1 and not pos.tp2 and price >= avg * (1 + TAKE_PROFIT_2):
                                pos.tp2 = True
                                sell(pos, Decimal("0.5"), sell_fill, day, when, "TAKE_PROFIT_2")
                            elif pos.tp2 and price <= pos.peak * (1 - TRAILING):
                                sell(pos, Decimal("1"), sell_fill, day, when, "TRAILING_STOP")
                                pos = None

                    # --- ATR protective stop (research): fixed at entry, confirmed by closes
                    pos = holdings.get(symbol)
                    if atr_stop > 0 and pos is not None and symbol in stop_level:
                        closes = [Decimal(str(r[4])) for r in feed.rows[-STOP_CONFIRM_CANDLES:]]
                        if all(c < stop_level[symbol] for c in closes):
                            sell(pos, Decimal("1"), sell_fill, day, when, "ATR_STOP")
                            stop_level.pop(symbol, None)

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
                    pos = holdings.get(symbol)

                    if record_signals and action in ("BUY", "SELL"):
                        hour_key = (symbol, close_ms // 3_600_000)
                        if hour_key not in regime_cache:
                            lo = max(0, end - REGIME_LOOKBACK_MIN)
                            regime_cache[hour_key] = _entry_regime(_hourly_bars(data[symbol][lo:end], end - lo))
                        result.signals.append({"symbol": symbol, "time": when, "action": action,
                                               "confidence": confidence, "bucket": bucket,
                                               "regime": regime_cache[hour_key],
                                               **_signal_outcome(data[symbol], end, price, slip, fee_rate)})
                    sell_streak[symbol] = sell_streak.get(symbol, 0) + 1 if action == "SELL" else 0
                    if action == "SELL" and pos is not None and confidence >= EXECUTION_GATE:
                        held_min = (close_ms - pos.entry_ms) / 60_000
                        if held_min < min_hold_min or sell_streak[symbol] < sell_confirm:
                            result.exit_reasons["SELL_DEFERRED"] = result.exit_reasons.get("SELL_DEFERRED", 0) + 1
                            continue
                        sell(pos, Decimal("1"), sell_fill, day, when, "SELL_SIGNAL")
                        continue
                    if action != "BUY":
                        continue

                    is_add = pos is not None
                    if is_add:
                        if not staged or pos.tranches >= len(TRANCHES) or pos.tp1:
                            continue
                        if price < pos.avg_entry or close_ms - pos.last_tranche_ms < TRANCHE_MIN_GAP_MS:
                            continue
                    result.buy_signals += 1
                    bars = _hourly_bars(data[symbol], end) if (trend_ema_hours or atr_stop or cost_gate or regime_filter) else []
                    if trend_ema_hours and not is_add:
                        ema = _ema([b[2] for b in bars], trend_ema_hours)
                        if ema is None or price <= ema:
                            reject("TREND_FILTER")
                            continue
                    if confidence < EXECUTION_GATE:
                        reject("EXECUTION_GATE")
                        continue
                    try:
                        sizing = risk.sizing_bucket(bucket, confidence / 100)
                    except Exception:
                        reject(f"BUCKET_{bucket}")
                        continue
                    if is_add:
                        target = pos.target_allocation
                        amount = target * TRANCHES[pos.tranches]
                        sizing_name = pos.bucket
                    else:
                        target = CAPITAL * risk.policy.buckets[sizing].max_allocation_pct
                        amount = target * (TRANCHES[0] if staged else Decimal("1"))
                        sizing_name = sizing.value
                    if sleeves:
                        room = sleeve_room(sizing_name)
                        if room < SLEEVE_MIN_ORDER:
                            reject("SLEEVE_FULL")
                            continue
                        amount = min(amount, room)
                    if regime_filter and not is_add:
                        from tools.regime_engine import classify
                        if classify([float(b[2]) for b in bars])["regime"] != "TREND_UP":
                            reject("REGIME_NOT_TREND_UP")
                            continue
                    if cost_gate and not is_add:
                        gate_atr = _atr(bars)
                        round_trip = 2 * fee_rate + 2 * slip
                        if gate_atr is None or 2 * gate_atr / price < cost_gate * round_trip:
                            reject("EXPECTED_MOVE_BELOW_COST")
                            continue
                    atr = _atr(bars) if atr_stop else None
                    if atr_stop and atr is None:
                        reject("ATR_UNAVAILABLE")
                        continue
                    if risk_per_trade and atr and not is_add:
                        stop_distance = atr_stop * atr / price
                        if stop_distance > 0:
                            amount = min(amount, ledger["equity"] * risk_per_trade / stop_distance)
                    amount = min(amount, ledger["cash"])
                    # quantity x price must equal the requested allocation exactly
                    base = (amount / price).quantize(Decimal("0.00000001"), rounding=ROUND_DOWN)
                    amount = base * price
                    if base <= 0:
                        reject("NO_CASH")
                        continue
                    request = RiskRequest(symbol=symbol, action="BUY", confidence=confidence / 100,
                                          requested_quote_allocation=amount, execution_price=price,
                                          risk_bucket=bucket, base_quantity=base)
                    # RiskEngine checks the accounting day against the real UTC
                    # date; the daily realized P&L it limits is the replayed day's.
                    # An add-on tranche is evaluated as a new request for its own
                    # size (the runtime change will allow tranches explicitly).
                    state = _state(holdings, realized_by_day.get(day, Decimal("0")), ledger["equity"],
                                   ledger["peak"], datetime.now(UTC).date().isoformat(),
                                   exclude=symbol if is_add else None)
                    verdict = risk.evaluate(request, state)
                    if not verdict.approved:
                        reject(verdict.reason_code)
                        continue
                    fee = amount * fee_rate / (1 + fee_rate)
                    cost = amount - fee
                    if not is_add:
                        pos = Position(symbol, sizing_name, bool(verdict.experiment_id), when, target, peak=price,
                                       entry_ms=close_ms, entry_confidence=confidence,
                                       entry_regime=_entry_regime(bars or _hourly_bars(data[symbol], end)))
                        holdings[symbol] = pos
                    else:
                        result.tranche_adds += 1
                    pos.qty += cost / buy_fill
                    pos.qty_bought += cost / buy_fill
                    pos.cost_total += cost
                    pos.cost_open += cost
                    pos.fees_in += fee
                    pos.fees_open += fee
                    pos.tranches += 1
                    pos.last_tranche_ms = close_ms
                    if atr_stop and atr and not is_add:
                        stop_level[symbol] = price - atr_stop * atr
                    ledger["cash"] -= amount
            result.open_trades.extend(p.as_trade() for p in holdings.values())
        finally:
            os.chdir(cwd)
    return result


def summarize(result: Result) -> dict:
    nets = [t.net for t in result.trades]
    wins = sum(1 for n in nets if n > 0)
    equity, peak, max_dd = Decimal("0"), Decimal("0"), Decimal("0")
    for n in nets:
        equity += n
        peak = max(peak, equity)
        max_dd = max(max_dd, peak - equity)
    return {
        "decisions": result.decisions,
        "buy_signals": result.buy_signals,
        "buy_rejections": dict(sorted(result.buy_rejections.items())),
        "closed_trades": len(nets),
        "open_at_end": len(result.open_trades),
        "wins_net": wins,
        "net_pnl": sum(nets, Decimal("0")),
        "fees": sum((t.entry_fee + t.exit_fee for t in result.trades), Decimal("0")),
        "max_drawdown": max_dd,
        "experiment_trades": sum(1 for t in result.trades if t.experiment),
        "tranche_adds": result.tranche_adds,
        "partial_sells": result.partial_sells,
        "exit_reasons": dict(sorted(result.exit_reasons.items())),
    }


def main(argv: list[str] | None = None, fetch: Fetcher | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--days", type=int, default=7)
    parser.add_argument("--step", type=int, default=15, help="minutes between replayed decisions")
    parser.add_argument("--symbols", default=",".join(DEFAULT_SYMBOLS))
    parser.add_argument("--exp001", action="store_true", help="apply the EXP-001 floor as during the experiment")
    parser.add_argument("--staged", action="store_true",
                        help="owner-approved staged entries/exits: 3 tranches, +1.5%%/+3%% ladder, 1.5%% trailing, -3%% confirmed stop")
    parser.add_argument("--sleeves", action="store_true", help="cap each risk bucket at 50/35/15%% of capital across all symbols")
    parser.add_argument("--slippage-bps", type=int, default=0, help="fill every order this many basis points against you")
    parser.add_argument("--next-open-fill", action="store_true", help="fill at the next candle's open (realistic latency)")
    parser.add_argument("--min-hold", type=int, default=0, help="minutes before a SELL signal may close a position")
    parser.add_argument("--sell-confirm", type=int, default=1, help="consecutive SELL decisions required to close")
    parser.add_argument("--trend-ema", type=int, default=0, help="BUY only above the EMA of this many 1-hour closes")
    parser.add_argument("--atr-stop", type=float, default=0, help="protective stop at entry - K x ATR(14, 1h)")
    parser.add_argument("--signals-out", default=None,
                        help="write every BUY/SELL decision with its 60m/240m net outcome to this CSV (lesson book)")
    parser.add_argument("--trades-out", default=None, help="write every closed trade (confidence, regime, net) to this CSV")
    parser.add_argument("--risk-per-trade", type=float, default=0, help="max equity fraction lost at the ATR stop (needs --atr-stop)")
    args = parser.parse_args(argv)

    # The replay drives MarketLoop without an ExecutionManager on purpose, so
    # its per-decision "execution skipped: manager unavailable" warning is
    # expected noise here; it flooded the console and slowed the run.
    # Errors still surface.
    logging.getLogger("AtlasAI.MarketLoop").setLevel(logging.ERROR)

    from tools.measure_volatility_ceiling import fetch_page

    fetch = fetch or fetch_page
    data = {}
    for symbol in [s.strip().upper() for s in args.symbols.split(",") if s.strip()]:
        print(f"downloading {symbol} ({args.days} days)...", file=sys.stderr, flush=True)
        data[symbol] = _history(symbol, args.days, fetch)
    print("replaying the real decision chain (this takes a few minutes)...", file=sys.stderr, flush=True)
    result = replay(data, step=args.step, exp001=args.exp001, staged=args.staged, sleeves=args.sleeves,
                    slippage_bps=args.slippage_bps, next_open_fill=args.next_open_fill,
                    min_hold_min=args.min_hold, sell_confirm=args.sell_confirm,
                    trend_ema_hours=args.trend_ema, atr_stop=args.atr_stop, risk_per_trade=args.risk_per_trade,
                    record_signals=bool(args.signals_out))
    s = summarize(result)
    if args.signals_out:
        n = write_signals_csv(args.signals_out, result.signals)
        print(f"wrote {n} signals to {args.signals_out}", file=sys.stderr)
    if args.trades_out:
        n = write_trades_csv(args.trades_out, result.trades)
        print(f"wrote {n} closed trades to {args.trades_out}", file=sys.stderr)

    print("MACRO-NEUTRAL REPLAY - macro and sentiment EXCLUDED; fills at candle close; "
          f"fee {PAPER_FEE_RATE_PER_SIDE:.1%}/side; slippage {args.slippage_bps} bps; "
          f"fill at {'next candle open' if args.next_open_fill else 'decision candle close'}; symbols stepped on one clock with shared cash, "
          "open positions and daily realized P&L fed to RiskEngine (equity realized-only)")
    print(f"days={args.days} step={args.step}m symbols={','.join(data)} exp001={args.exp001} "
          f"staged={args.staged} sleeves={args.sleeves} min_hold={args.min_hold}m sell_confirm={args.sell_confirm} "
          f"trend_ema={args.trend_ema}h atr_stop={args.atr_stop} risk_per_trade={args.risk_per_trade}")
    print(f"decisions: {s['decisions']}  BUY signals: {s['buy_signals']}  rejected: {s['buy_rejections']}")
    print(f"closed trades: {s['closed_trades']} (open at end: {s['open_at_end']}, under EXP-001: {s['experiment_trades']})")
    if s["closed_trades"]:
        print(f"net wins: {s['wins_net']}/{s['closed_trades']}  net P&L: {s['net_pnl']:.2f}  "
              f"fees: {s['fees']:.2f}  max drawdown: {s['max_drawdown']:.2f}")
        print(f"exits: {s['exit_reasons']}  tranche adds: {s['tranche_adds']}  partial sells: {s['partial_sells']}")
    print("Research evidence only. Not a promise of live results. Nothing was changed.")
    return 0


def _history(symbol: str, days: int, fetch: Fetcher) -> list[list]:
    import time

    now_ms = int(time.time() * 1000)
    start = now_ms - days * 24 * 60 * 60_000
    rows: list[list] = []
    while start < now_ms:
        for attempt in range(4):  # the owner's network times out now and then: retry, then give up loudly
            try:
                page = fetch(symbol, start)
                break
            except OSError:
                if attempt == 3:
                    raise
                time.sleep(2 ** attempt * 2)
        if not page:
            break
        rows.extend(r for r in page if int(r[6]) < now_ms)
        start = int(page[-1][0]) + 60_000
    return rows


if __name__ == "__main__":
    sys.exit(main())
