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
import os
import sys
import tempfile
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal
from typing import Callable

from core.execution_manager import PAPER_FEE_RATE_PER_SIDE
from core.execution_models import normalize_risk
from core.market_loop import MarketLoop
from core.market_risk_regime import MarketRiskRegimeProvider
from core.risk_engine import (
    EXP001_PAPER_CONFIDENCE_EXPERIMENT,
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
    symbol: str
    entry_time: str
    entry_price: Decimal
    quantity: Decimal
    cost: Decimal
    entry_fee: Decimal
    bucket: str
    experiment: bool
    exit_time: str = ""
    exit_price: Decimal = Decimal("0")
    exit_fee: Decimal = Decimal("0")

    @property
    def net(self) -> Decimal:
        return self.quantity * self.exit_price - self.cost - self.entry_fee - self.exit_fee


@dataclass
class Result:
    trades: list[Trade] = field(default_factory=list)
    open_trades: list[Trade] = field(default_factory=list)
    decisions: int = 0
    buy_signals: int = 0
    buy_rejections: dict[str, int] = field(default_factory=dict)


def _state(positions=()) -> RiskState:
    return RiskState(tuple(positions), sum((p.quote_exposure for p in positions), Decimal("0")),
                     Decimal("0"), CAPITAL, CAPITAL, True, datetime.now(UTC).date().isoformat(),
                     RiskPolicy(total_capital=CAPITAL).version)


def replay(candles_by_symbol: dict[str, list[list]], *, step: int = 15, exp001: bool = False,
           brain_factory=None) -> Result:
    if brain_factory is None:
        from ai.core.atlas_brain import AtlasBrain
        brain_factory = AtlasBrain
    result = Result()
    fee_rate = PAPER_FEE_RATE_PER_SIDE
    risk = RiskEngine(RiskPolicy(total_capital=CAPITAL))
    if exp001:
        # the experiment is held open for the whole replay (its clock is
        # pinned to its start); its 50-admission cap still applies
        risk.attach_experiment(EXP001_PAPER_CONFIDENCE_EXPERIMENT, prior_admissions=0,
                               clock=lambda: EXP001_PAPER_CONFIDENCE_EXPERIMENT.starts_at)
    cash = CAPITAL

    with tempfile.TemporaryDirectory() as scratch, contextlib.redirect_stdout(io.StringIO()):
        cwd = os.getcwd()
        os.chdir(scratch)  # AtlasBrain bootstraps CWD-relative memory files
        try:
            brain = _CapturingBrain(brain_factory())
            for symbol, rows in candles_by_symbol.items():
                feed = _WindowFeed()
                loop = MarketLoop(brain=brain, market_feed=feed, execution=None, symbols=[symbol],
                                  market_risk_provider=MarketRiskRegimeProvider())
                holding: Trade | None = None
                for end in range(WINDOW, len(rows), step):
                    feed.rows = rows[end - WINDOW:end]
                    close_ms = int(feed.rows[-1][6])
                    cutoff = datetime.fromtimestamp((close_ms + 1000) / 1000, UTC)
                    brain.last = None
                    loop.process_symbol(symbol, processing_cutoff=cutoff)
                    if brain.last is None:
                        continue
                    decision = loop.normalize_decision(raw_decision=brain.last, symbol=symbol,
                                                       price=float(feed.rows[-1][4]), market_data={})
                    if not decision:
                        continue
                    result.decisions += 1
                    action = decision.get("action")
                    confidence = Decimal(str(decision.get("confidence", 0)))
                    bucket = normalize_risk(decision.get("risk", decision.get("risk_level")))
                    price = Decimal(str(feed.rows[-1][4]))
                    when = cutoff.isoformat()

                    if action == "SELL" and holding is not None and confidence >= EXECUTION_GATE:
                        holding.exit_time, holding.exit_price = when, price
                        holding.exit_fee = holding.quantity * price * fee_rate
                        cash += holding.quantity * price - holding.exit_fee
                        result.trades.append(holding)
                        holding = None
                    elif action == "BUY" and holding is None:
                        result.buy_signals += 1
                        if confidence < EXECUTION_GATE:
                            result.buy_rejections["EXECUTION_GATE"] = result.buy_rejections.get("EXECUTION_GATE", 0) + 1
                            continue
                        try:
                            sizing = risk.sizing_bucket(bucket, confidence / 100)
                        except Exception:
                            result.buy_rejections[f"BUCKET_{bucket}"] = result.buy_rejections.get(f"BUCKET_{bucket}", 0) + 1
                            continue
                        allocation = min(cash, CAPITAL * risk.policy.buckets[sizing].max_allocation_pct)
                        request = RiskRequest(symbol=symbol, action="BUY", confidence=confidence / 100,
                                              requested_quote_allocation=allocation, execution_price=price,
                                              risk_bucket=bucket, base_quantity=allocation / price)
                        verdict = risk.evaluate(request, _state())
                        if not verdict.approved:
                            result.buy_rejections[verdict.reason_code] = result.buy_rejections.get(verdict.reason_code, 0) + 1
                            continue
                        fee = allocation * fee_rate / (1 + fee_rate)
                        cost = allocation - fee
                        holding = Trade(symbol, when, price, cost / price, cost, fee, bucket,
                                        bool(verdict.experiment_id))
                        cash -= allocation
                if holding is not None:
                    result.open_trades.append(holding)
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
    }


def main(argv: list[str] | None = None, fetch: Fetcher | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--days", type=int, default=7)
    parser.add_argument("--step", type=int, default=15, help="minutes between replayed decisions")
    parser.add_argument("--symbols", default=",".join(DEFAULT_SYMBOLS))
    parser.add_argument("--exp001", action="store_true", help="apply the EXP-001 floor as during the experiment")
    args = parser.parse_args(argv)

    from tools.measure_volatility_ceiling import fetch_page

    fetch = fetch or fetch_page
    data = {}
    for symbol in [s.strip().upper() for s in args.symbols.split(",") if s.strip()]:
        print(f"downloading {symbol} ({args.days} days)...", file=sys.stderr, flush=True)
        data[symbol] = _history(symbol, args.days, fetch)
    print("replaying the real decision chain (this takes a few minutes)...", file=sys.stderr, flush=True)
    s = summarize(replay(data, step=args.step, exp001=args.exp001))

    print("MACRO-NEUTRAL REPLAY - macro and sentiment EXCLUDED; fills at candle close; "
          f"fee {PAPER_FEE_RATE_PER_SIDE:.1%}/side; no slippage")
    print(f"days={args.days} step={args.step}m symbols={','.join(data)} exp001={args.exp001}")
    print(f"decisions: {s['decisions']}  BUY signals: {s['buy_signals']}  rejected: {s['buy_rejections']}")
    print(f"closed trades: {s['closed_trades']} (open at end: {s['open_at_end']}, under EXP-001: {s['experiment_trades']})")
    if s["closed_trades"]:
        print(f"net wins: {s['wins_net']}/{s['closed_trades']}  net P&L: {s['net_pnl']:.2f}  "
              f"fees: {s['fees']:.2f}  max drawdown: {s['max_drawdown']:.2f}")
    print("Research evidence only. Not a promise of live results. Nothing was changed.")
    return 0


def _history(symbol: str, days: int, fetch: Fetcher) -> list[list]:
    import time

    now_ms = int(time.time() * 1000)
    start = now_ms - days * 24 * 60 * 60_000
    rows: list[list] = []
    while start < now_ms:
        page = fetch(symbol, start)
        if not page:
            break
        rows.extend(r for r in page if int(r[6]) < now_ms)
        start = int(page[-1][0]) + 60_000
    return rows


if __name__ == "__main__":
    sys.exit(main())
