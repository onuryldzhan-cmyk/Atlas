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
  CANDIDATE (< MIN_PROVISIONAL), PROVISIONAL (>= MIN_PROVISIONAL),
  VALIDATED only when an owner-signed AUTHORITATIVE memory record (current,
  owner_verified) names the lesson id in ``related_decision``. A winning lesson carries no effect:
  memory is evidence, never a decision (CLAUDE.md rule 3).
* **Contradiction** = the older and newer halves of a lesson's trades
  point in opposite directions, each with at least MIN_HALF trades. Status
  becomes CONTESTED; both halves are shown, nothing is deleted.

Pure: callers pass already-read records. No I/O.
"""

from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import Any, Iterable

MIN_PROVISIONAL = 10
MIN_HALF = 5
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
        out.append({"id": f"EXP-{len(out) + 1:04d}", "symbol": r.get("symbol"), "environment": ENVIRONMENT,
                    "regime": regime_at(timeline, str(r.get("symbol")), r.get("opened_at")),
                    "opened_at": r.get("opened_at"), "closed_at": r.get("closed_at"),
                    "net_pnl": str(net.quantize(Decimal("0.0001"))), "outcome": "WIN" if net > 0 else "LOSS"})
    return sorted(out, key=lambda e: str(e["closed_at"] or ""))


def _lesson(lid: str, subject: str, exps: list[dict[str, Any]], validated: set[str]) -> dict[str, Any]:
    nets = [Decimal(e["net_pnl"]) for e in exps]
    n = len(nets)
    exp = sum(nets) / n
    half = n // 2
    old, new = nets[:half], nets[half:]
    contested = (len(old) >= MIN_HALF and len(new) >= MIN_HALF
                 and (sum(old) > 0) != (sum(new) > 0))
    status = ("CONTESTED" if contested else "VALIDATED" if lid in validated and n >= MIN_PROVISIONAL
              else "PROVISIONAL" if n >= MIN_PROVISIONAL else "CANDIDATE")
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
    counts: dict[str, int] = {}
    for lesson in lessons:
        counts[lesson["status"]] = counts.get(lesson["status"], 0) + 1
    return {"available": True, "environment": ENVIRONMENT, "experiences": exps[-50:], "experience_count": len(exps),
            "lessons": lessons, "lesson_status_counts": counts,
            "contradictions": [x for x in lessons if x["status"] == "CONTESTED"],
            "rules": {"min_provisional": MIN_PROVISIONAL, "min_half": MIN_HALF,
                      "validated": "only by an owner-signed AUTHORITATIVE memory record with related_decision = lesson id",
                      "effect": "none: lessons are evidence, never a decision or a confidence change"}}
