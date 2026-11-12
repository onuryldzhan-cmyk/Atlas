"""Would freqtrade-style protections have helped? Observe-only replay of the closed PAPER trades.

Freqtrade (freqtrade/freqtrade, freqtrade/plugins/protections/) locks a coin - or all
coins - after recent losses so a strategy stops re-entering a market that keeps
hurting it. Atlas has a daily loss limit and drawdown levels (MaxDrawdown's job) but
no per-coin cooldown or loss lock. This replays the closed PAPER trades in entry
order and, for each entry, asks whether one of these rules would have blocked it
(parameters: the "Full example of Protections" in freqtrade's docs, 1h candles):

  COOLDOWN      no re-entry in a coin for 5 h after a trade in it closed
  LOSS_GUARD    4 losing trades (all coins) closed in the last 24 h -> no entry for 2 h
  LOW_PROFIT_6H a coin with >= 2 trades closed in 6 h and combined profit < 2 % -> locked 60 h
  LOW_PROFIT_24H a coin with >= 4 trades closed in 24 h and combined profit < 1 % -> locked 2 h

Losing = net P&L after fees < 0 (Atlas records no exit reason, so this is stricter
than freqtrade's stop-loss-only count). Report only: no gate, order or setting changes.
A blocked trade's net P&L is "avoided"; positive avoided means the rule would have helped.
Trades that came after a blocked one are replayed as they happened (no counterfactual chain).

    python -m tools.protections_report
"""
from __future__ import annotations

import sys
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any

H = timedelta(hours=1)


@dataclass(frozen=True)
class Rule:
    name: str
    lookback: timedelta
    trade_limit: int
    lock: timedelta
    per_coin: bool
    required_profit: Decimal | None = None  # LowProfit: combined ratio below this locks
    losing_only: bool = False               # LossGuard: count only losing trades


RULES = (
    Rule("COOLDOWN", 5 * H, 1, 5 * H, per_coin=True),
    Rule("LOSS_GUARD", 24 * H, 4, 2 * H, per_coin=False, losing_only=True),
    Rule("LOW_PROFIT_6H", 6 * H, 2, 60 * H, per_coin=True, required_profit=Decimal("0.02")),
    Rule("LOW_PROFIT_24H", 24 * H, 4, 2 * H, per_coin=True, required_profit=Decimal("0.01")),
)


def _ts(value: Any) -> datetime | None:
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None


def _prepare(closed: list[dict]) -> tuple[list[dict], int]:
    from ai.core.intelligence.trade_evidence import net_pnl

    out, skipped = [], 0
    for r in closed:
        opened, closed_at = _ts(r.get("opened_at")), _ts(r.get("closed_at"))
        try:
            cost = Decimal(str(r["cost_quote"]))
            net = net_pnl(r)
        except Exception:
            skipped += 1
            continue
        if opened is None or closed_at is None or cost <= 0:
            skipped += 1
            continue
        out.append({"symbol": r.get("symbol", ""), "opened": opened, "closed": closed_at, "net": net, "ratio": net / cost})
    return sorted(out, key=lambda t: t["opened"]), skipped


def _lock_end(rule: Rule, history: list[dict], at: datetime, symbol: str) -> datetime | None:
    """When the rule's lock for this entry would end, or None if it would not lock."""
    window = [t for t in history if at - rule.lookback <= t["closed"] <= at
              and (not rule.per_coin or t["symbol"] == symbol)]
    if rule.losing_only:
        window = [t for t in window if t["net"] < 0]
    if len(window) < rule.trade_limit:
        return None
    if rule.required_profit is not None and sum(t["ratio"] for t in window) >= rule.required_profit:
        return None
    end = max(t["closed"] for t in window) + rule.lock
    return end if end > at else None


def replay(closed: list[dict], rules: tuple[Rule, ...] = RULES) -> dict[str, Any]:
    trades, skipped = _prepare(closed)
    per_rule = {r.name: {"blocked": 0, "avoided_net": Decimal(0), "blocked_wins": 0} for r in rules}
    any_blocked = {"blocked": 0, "avoided_net": Decimal(0)}
    for i, t in enumerate(trades):
        history = [h for h in trades[:i] if h["closed"] <= t["opened"]]
        hit = False
        for rule in rules:
            if _lock_end(rule, history, t["opened"], t["symbol"]) is not None:
                s = per_rule[rule.name]
                s["blocked"] += 1
                s["avoided_net"] += -t["net"]
                s["blocked_wins"] += t["net"] > 0
                hit = True
        if hit:
            any_blocked["blocked"] += 1
            any_blocked["avoided_net"] += -t["net"]
    total = sum((t["net"] for t in trades), Decimal(0))
    return {"trades": len(trades), "skipped_malformed": skipped, "net_total": total,
            "rules": per_rule, "combined": any_blocked}


def main(argv: list[str] | None = None) -> int:
    from tools.agent_cycle import _archive_path
    from tools.exp001_report import load_closed

    out = replay(load_closed(_archive_path()))
    print(f"closed PAPER trades replayed: {out['trades']} (malformed, left out: {out['skipped_malformed']}); "
          f"net total {out['net_total']:.2f} USDT")
    print(f"{'rule':16} {'blocked':>8} {'of which winners':>17} {'net avoided USDT':>17}")
    for name, s in out["rules"].items():
        print(f"{name:16} {s['blocked']:>8} {s['blocked_wins']:>17} {s['avoided_net']:>17.2f}")
    c = out["combined"]
    print(f"{'ANY RULE':16} {c['blocked']:>8} {'':>17} {c['avoided_net']:>17.2f}")
    print("Positive 'net avoided' = the rule would have kept losses out; negative = it would have cut winners.")
    print("Observation only: no gate, order or setting was changed. Small samples decide nothing.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
