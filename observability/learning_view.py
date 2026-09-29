"""Learning view: experiences, lessons and contradictions derived from Atlas's own closed trades.

Owner specification 2026-09-30 (experience & institutional memory), items
C1-C4 of proposals/2026-09-30_ui_hq_memory_owner_specs_evaluation.md.

Nothing here is stored or overwritten: every figure is recomputed from the
canonical sources on each read, so there is no second truth to drift.

* **Experience** = one closed trade, tagged with its environment (always
  PAPER today: live authority is DENIED) and the market regime the
  ``market_regime`` agent last recorded for that coin *before* the trade
  opened. A later record is never used (no look-ahead); no record means
  regime UNKNOWN, never a guess.
* **Lesson** = net expectancy after fees of a group (per coin, per regime).
  Status is earned by sample size, never by outcome:
  PROPOSED (< MIN_PROVISIONAL), VALIDATING (>= MIN_PROVISIONAL), EXPIRED (not
  observed for EXPIRE_DAYS), CONFIRMED only when an owner-signed AUTHORITATIVE memory record (current,
  owner_verified) names the lesson id in ``related_decision``. A winning lesson carries no effect:
  memory is evidence, never a decision (CLAUDE.md rule 3).
* **Contradiction** = the older and newer halves of a lesson's trades
  point in opposite directions, each with at least MIN_HALF trades. Status
  becomes CONTESTED; both halves are shown, nothing is deleted.

Pure: callers pass already-read records. No I/O.
"""

from __future__ import annotations

import hashlib
import json
import math
from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import Any, Iterable

MIN_PROVISIONAL = 10
MIN_HALF = 5
EXPIRE_DAYS = 30  # a lesson not observed for this long (relative to the newest trade) is EXPIRED, not deleted
FEE_RATE_PER_SIDE = Decimal("0.001")  # same estimate as ai/core/intelligence/trade_evidence.py
ENVIRONMENT = "PAPER"


def _net(record: dict[str, Any]) -> Decimal:
    entry = Decimal(str(record["cost_quote"]))
    gross = Decimal(str(record["gross_pnl"]))
    return gross - FEE_RATE_PER_SIDE * (entry + max(entry + gross, Decimal("0")))


def regime_timeline(memory_records: Iterable[dict[str, Any]]) -> list[tuple[str, dict[str, str]]]:
    """(created_at, {symbol: regime}) from market_regime records, oldest first."""
    import json

    out = []
    for r in memory_records:
        if r.get("author") != "market_regime":
            continue
        try:
            coins = json.loads(r.get("body") or "{}").get("coins") or {}
        except (ValueError, AttributeError):
            continue
        out.append((str(r.get("created_at") or ""), {s: str(v.get("regime")) for s, v in coins.items() if isinstance(v, dict)}))
    return sorted(out, key=lambda x: x[0])


def regime_at(timeline: list[tuple[str, dict[str, str]]], symbol: str, when: str | None) -> str:
    if not when:
        return "UNKNOWN"
    found = "UNKNOWN"
    for stamp, coins in timeline:
        if stamp > when:  # a record written after the trade opened would be look-ahead
            break
        if symbol in coins:
            found = coins[symbol]
    return found


def experiences(closed: Iterable[dict[str, Any]], memory_records: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    timeline = regime_timeline(memory_records)
    out, seen = [], set()
    for r in closed:
        key = r.get("position_id") or (r.get("symbol"), r.get("opened_at"), r.get("closed_at"))
        if key in seen:  # duplicate archive rows are counted once
            continue
        seen.add(key)
        try:
            net = _net(r)
        except (KeyError, InvalidOperation, TypeError, ValueError):
            continue
        gross = Decimal(str(r["gross_pnl"]))
        cost = Decimal(str(r["cost_quote"]))
        exp = {"id": f"EXP-{len(out) + 1:04d}", "position_id": r.get("position_id"), "symbol": r.get("symbol"),
               "environment": ENVIRONMENT, "regime": regime_at(timeline, str(r.get("symbol")), r.get("opened_at")),
               "opened_at": r.get("opened_at"), "closed_at": r.get("closed_at"),
               "notional": str(cost), "gross_pnl": str(gross),
               "net_pnl": str(net.quantize(Decimal("0.0001"))), "outcome": "WIN" if net > 0 else "LOSS"}
        exp["analysis"] = post_trade(exp, gross, net, cost)
        exp["fingerprint"] = fingerprint(r)
        out.append(exp)
    return sorted(out, key=lambda e: str(e["closed_at"] or ""))


def fingerprint(record: dict[str, Any]) -> str:
    """Content hash of the archive row: a silently edited outcome gets a different fingerprint."""
    keys = ("position_id", "symbol", "cost_quote", "gross_pnl", "opened_at", "closed_at")
    return hashlib.sha256(json.dumps({k: str(record.get(k)) for k in keys}, sort_keys=True).encode()).hexdigest()[:16]


def _minutes(a: Any, b: Any) -> float | None:
    try:
        return round((datetime.fromisoformat(str(b)) - datetime.fromisoformat(str(a))).total_seconds() / 60, 1)
    except ValueError:
        return None


def post_trade(exp: dict[str, Any], gross: Decimal, net: Decimal, cost: Decimal) -> dict[str, Any]:
    """Hindsight facts about one closed trade. Evidence only; it cannot change any decision."""
    fees = gross - net
    return {"holding_minutes": _minutes(exp["opened_at"], exp["closed_at"]),
            "gross_return_pct": str((gross / cost * 100).quantize(Decimal("0.001"))) if cost else None,
            "fee_impact": str(fees.quantize(Decimal("0.0001"))),
            "fees_turned_win_into_loss": gross > 0 >= net,
            "direction_right": gross > 0,
            "worth_taking_in_hindsight": net > 0,
            # Counterfactuals (MEGA 1 §13): computed, never recorded as executions.
            "counterfactual": {"no_trade_net": "0", "no_trade_vs_actual": str((-net).quantize(Decimal("0.0001"))),
                               "fee_free_net": str(gross), "label": "COUNTERFACTUAL (not an execution result)"},
            "not_measured": ["slippage (PAPER fill model)", "max adverse/favourable excursion (no intratrade path stored)",
                             "entry confidence (joined offline by tools/reality_check)"]}


def metrics(nets: list[Decimal]) -> dict[str, Any]:
    """Book metrics after fees. Below MIN_PROVISIONAL trades they are reported as INSUFFICIENT, not as results."""
    n = len(nets)
    if not n:
        return {"trades": 0, "verdict": "NO_DATA"}
    wins, losses = [x for x in nets if x > 0], [x for x in nets if x <= 0]
    total = sum(nets, Decimal("0"))
    equity = peak = max_dd = Decimal("0")
    streak = longest = 0
    for x in nets:
        equity += x
        peak = max(peak, equity)
        max_dd = max(max_dd, peak - equity)
        streak = streak + 1 if x <= 0 else 0
        longest = max(longest, streak)
    f = [float(x) for x in nets]
    mean = sum(f) / n
    sd = math.sqrt(sum((x - mean) ** 2 for x in f) / (n - 1)) if n > 1 else None
    down = [x for x in f if x < 0]
    dsd = math.sqrt(sum(x * x for x in down) / len(down)) if down else None
    q = lambda d: str(d.quantize(Decimal("0.0001")))
    return {"trades": n, "net_total": q(total), "expectancy": q(total / n),
            "win_rate": round(len(wins) / n, 4),
            "avg_win": q(sum(wins, Decimal("0")) / len(wins)) if wins else None,
            "avg_loss": q(sum(losses, Decimal("0")) / len(losses)) if losses else None,
            "profit_factor": round(float(sum(wins, Decimal("0")) / -sum(losses, Decimal("0"))), 4) if losses and sum(losses, Decimal("0")) < 0 else None,
            "sharpe_per_trade": round(mean / sd, 4) if sd else None,
            "sortino_per_trade": round(mean / dsd, 4) if dsd else None,
            "max_drawdown": q(max_dd), "recovery_factor": round(float(total / max_dd), 4) if max_dd > 0 else None,
            "longest_losing_streak": longest,
            "verdict": "MEASURED" if n >= MIN_PROVISIONAL else "INSUFFICIENT"}


def _lesson(lid: str, subject: str, exps: list[dict[str, Any]], validated: set[str]) -> dict[str, Any]:
    nets = [Decimal(e["net_pnl"]) for e in exps]
    n = len(nets)
    exp = sum(nets) / n
    half = n // 2
    old, new = nets[:half], nets[half:]
    contested = (len(old) >= MIN_HALF and len(new) >= MIN_HALF
                 and (sum(old) > 0) != (sum(new) > 0))
    status = ("CONTESTED" if contested else "CONFIRMED" if lid in validated and n >= MIN_PROVISIONAL
              else "VALIDATING" if n >= MIN_PROVISIONAL else "PROPOSED")
    direction = "kazandırıyor" if exp > 0 else "kaybettiriyor"
    return {"id": lid, "subject": subject, "environment": ENVIRONMENT,
            "statement": f"{subject}: işlem başına net {exp:.2f} $ ({direction})" + ("" if n >= MIN_PROVISIONAL else ", örnek az"),
            "sample_size": n, "supporting": sum(1 for x in nets if (x > 0) == (exp > 0)),
            "contradicting": sum(1 for x in nets if (x > 0) != (exp > 0)),
            "net_expectancy": str(exp.quantize(Decimal("0.0001"))),
            "first_observed": exps[0]["closed_at"], "last_observed": exps[-1]["closed_at"],
            "status": status, "evidence": [e["id"] for e in exps],
            "halves": {"older": str(sum(old).quantize(Decimal("0.01"))), "newer": str(sum(new).quantize(Decimal("0.01")))} if contested else None}


def build(closed: Iterable[dict[str, Any]], memory_records: Iterable[dict[str, Any]]) -> dict[str, Any]:
    mem = list(memory_records)
    exps = experiences(closed, mem)
    validated = {str(r.get("related_decision")) for r in mem
                 if r.get("authority") == "AUTHORITATIVE" and r.get("owner_verified") is True
                 and str(r.get("related_decision") or "").startswith("L-") and r.get("status", "CURRENT") == "CURRENT"}
    groups: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for e in exps:
        groups.setdefault(("COIN", str(e["symbol"])), []).append(e)
        groups.setdefault(("REGIME", str(e["regime"])), []).append(e)
    lessons = [_lesson(f"L-{kind}-{name}", f"{'coin' if kind == 'COIN' else 'rejim'} {name}", g, validated)
               for (kind, name), g in sorted(groups.items())]
    if exps:  # strategy decay (task 11): the whole book as one lesson, older vs newer half
        lessons.append(_lesson("L-BOOK-ALL", "tüm defter (strateji çürümesi)", exps, validated))
    newest = max((str(e["closed_at"]) for e in exps), default=None)
    for lesson in lessons:
        age = _minutes(lesson["last_observed"], newest) if newest else None
        if age is not None and age > EXPIRE_DAYS * 1440 and lesson["status"] != "CONFIRMED":
            lesson["status"] = "EXPIRED"
    counts: dict[str, int] = {}
    for lesson in lessons:
        counts[lesson["status"]] = counts.get(lesson["status"], 0) + 1
    return {"available": True, "environment": ENVIRONMENT, "experiences": exps[-50:], "experience_count": len(exps),
            "book_metrics": metrics([Decimal(e["net_pnl"]) for e in exps]),
            "lessons": lessons, "lesson_status_counts": counts,
            "contradictions": [x for x in lessons if x["status"] == "CONTESTED"],
            "rules": {"min_provisional": MIN_PROVISIONAL, "min_half": MIN_HALF,
                      "validated": "only by an owner-signed AUTHORITATIVE memory record with related_decision = lesson id",
                      "effect": "none: lessons are evidence, never a decision or a confidence change"}}
