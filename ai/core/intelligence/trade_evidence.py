"""What Atlas's own closed trades say about one coin, the way a trader reads a book (BRAIN-MEM-001).

Pure functions over closed-position archive records (symbol, cost_quote,
gross_pnl, ...). The measure is net expectancy per trade after estimated
fees, not the win rate: a high win rate that fees turn into a loss is a
losing book.

The only effect this module can produce is caution. A coin with at least
MIN_TRADES closed trades whose net expectancy is negative gets
LOSING_EFFECT (a small push towards HOLD for new buys). A winning book never
raises confidence (CLAUDE.md rule 3, NB-4): anything short of proven loss,
including missing or unreadable data, has effect 0.
"""

from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import Any, Iterable

MIN_TRADES = 10
LOSING_EFFECT = -0.05
# Same assumption as tools/exp001_report.py (0.1 % per side); an estimate, not venue truth.
FEE_RATE_PER_SIDE = Decimal("0.001")


def net_pnl(record: dict[str, Any]) -> Decimal:
    """Gross P/L minus estimated entry and exit fees. Raises on malformed records."""

    entry = Decimal(str(record["cost_quote"]))
    gross = Decimal(str(record["gross_pnl"]))
    exit_value = entry + gross
    fees = FEE_RATE_PER_SIDE * (entry + max(exit_value, Decimal("0")))
    return gross - fees


def symbol_evidence(records: Iterable[dict[str, Any]], symbol: str) -> dict[str, Any]:
    """Trader metrics for one coin and the resulting (never positive) effect."""

    try:
        nets = [net_pnl(r) for r in records if isinstance(r, dict) and r.get("symbol") == symbol]
    except (KeyError, TypeError, ValueError, InvalidOperation):
        return {"symbol": symbol, "available": False, "reason": "MALFORMED_ARCHIVE_RECORD", "effect": 0.0}
    n = len(nets)
    wins = [x for x in nets if x > 0]
    losses = [x for x in nets if x <= 0]
    total = sum(nets, Decimal("0"))
    expectancy = total / n if n else None
    gross_loss = -sum(losses, Decimal("0"))
    streak = longest = 0
    for x in nets:
        streak = streak + 1 if x <= 0 else 0
        longest = max(longest, streak)
    effect = LOSING_EFFECT if n >= MIN_TRADES and expectancy is not None and expectancy < 0 else 0.0
    return {
        "symbol": symbol,
        "available": True,
        "trades": n,
        "net_total": float(total),
        "net_expectancy": None if expectancy is None else float(expectancy),
        "win_rate_after_fees": None if not n else round(len(wins) / n, 4),
        "profit_factor": None if not gross_loss else round(float(sum(wins, Decimal("0")) / gross_loss), 4),
        "longest_losing_streak": longest,
        "min_trades": MIN_TRADES,
        "effect": effect,
    }
