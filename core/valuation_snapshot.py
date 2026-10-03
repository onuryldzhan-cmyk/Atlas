"""
============================================================
ATLAS VALUATION SNAPSHOT v1 (Phase-2 C1)
============================================================

One immutable mark-to-market view of the durable book, taken once per risk
decision, so drawdown, equity, sleeve capacity, exposure and daily loss are
all measured on the same basis.

Conservative (loss-only) marked equity::

    marked_equity = ledger_equity + min(total_unrealized_net, 0)

An open gain never raises equity (evidence of a profit is not realized
capital, NB-4); an open loss always lowers it.

Completeness: every held position needs a fresh, positive mark. Any missing
one makes the snapshot INCOMPLETE; then ``unrealized_net``,
``marked_equity`` and the market-side figures are ``None`` - never filled
with zero or with the cost basis. New risk must refuse an INCOMPLETE
snapshot; a risk reduction need not (it is decided before valuation).

Per-position unrealized net matches the existing F-3 / F-C definition
exactly: mark value - (cost_quote + entry_fees) - the fee a close would pay.
Realized P&L and the financial ledger are only read, never changed.
============================================================
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from typing import Any, Mapping

COMPLETE = "COMPLETE"
INCOMPLETE = "INCOMPLETE"

ZERO = Decimal("0")


def _dec(value: Any) -> Decimal | None:
    try:
        number = Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        return None
    return number if number.is_finite() else None


@dataclass(frozen=True)
class ValuationSnapshot:
    as_of: str
    completeness: str
    missing_marks: tuple[str, ...]
    marks: Mapping[str, Decimal]
    cost_basis: Decimal
    exposure_cost: Decimal
    realized_daily: Decimal
    ledger_equity: Decimal
    peak_equity: Decimal
    market_value: Decimal | None
    exposure_market: Decimal | None
    unrealized_net: Decimal | None
    marked_equity: Decimal | None
    drawdown: Decimal | None
    drawdown_pct: Decimal | None
    per_position: Mapping[str, Mapping[str, Decimal]] = field(default_factory=dict)

    @property
    def complete(self) -> bool:
        return self.completeness == COMPLETE

    def to_dict(self) -> dict[str, Any]:
        def text(value: Any) -> Any:
            return None if value is None else format(value, "f")

        return {
            "as_of": self.as_of,
            "completeness": self.completeness,
            "missing_marks": list(self.missing_marks),
            "marks": {k: text(v) for k, v in sorted(self.marks.items())},
            "cost_basis": text(self.cost_basis),
            "exposure_cost": text(self.exposure_cost),
            "market_value": text(self.market_value),
            "exposure_market": text(self.exposure_market),
            "unrealized_net": text(self.unrealized_net),
            "realized_daily": text(self.realized_daily),
            "ledger_equity": text(self.ledger_equity),
            "marked_equity": text(self.marked_equity),
            "peak_equity": text(self.peak_equity),
            "drawdown": text(self.drawdown),
            "drawdown_pct": text(self.drawdown_pct),
        }


def build_valuation_snapshot(
    *,
    book_positions: Mapping[str, Mapping[str, Any]],
    marks: Mapping[str, Any],
    ledger_equity: Decimal,
    peak_equity: Decimal,
    realized_daily: Decimal,
    close_fee_rate: Decimal | float | int | str = 0,
    as_of: str,
) -> ValuationSnapshot:
    """Value the durable book at ``marks``. Raises ValueError on a malformed book."""

    fee_rate = _dec(close_fee_rate)
    if fee_rate is None or fee_rate < ZERO:
        raise ValueError("close_fee_rate must be a non-negative number")

    clean_marks: dict[str, Decimal] = {}
    for symbol, price in dict(marks or {}).items():
        value = _dec(price)
        if value is not None and value > ZERO:
            clean_marks[str(symbol).upper()] = value

    cost_basis = ZERO
    exposure_cost = ZERO
    market_value = ZERO
    unrealized = ZERO
    missing: list[str] = []
    per_position: dict[str, dict[str, Decimal]] = {}

    for symbol, position in sorted(dict(book_positions or {}).items()):
        symbol = str(symbol).upper()
        base = _dec(position.get("base_quantity"))
        cost = _dec(position.get("cost_quote"))
        fees = _dec(position.get("entry_fees") or "0")
        book_mark = _dec(position.get("mark_price"))
        if None in (base, cost, fees, book_mark) or base <= ZERO:
            raise ValueError(f"malformed durable position for {symbol}")

        paid = cost + fees
        cost_basis += paid
        exposure_cost += base * book_mark

        price = clean_marks.get(symbol)
        if price is None:
            missing.append(symbol)
            continue

        value = price * base
        net = value - paid - value * fee_rate
        market_value += value
        unrealized += net
        per_position[symbol] = {"market_value": value, "unrealized_net": net}

    complete = not missing
    marked_equity = ledger_equity + min(unrealized, ZERO) if complete else None

    if marked_equity is not None and peak_equity > ZERO:
        drawdown = max(peak_equity - marked_equity, ZERO)
        drawdown_pct = drawdown / peak_equity
    elif marked_equity is not None:
        drawdown, drawdown_pct = ZERO, ZERO
    else:
        drawdown = drawdown_pct = None

    return ValuationSnapshot(
        as_of=as_of,
        completeness=COMPLETE if complete else INCOMPLETE,
        missing_marks=tuple(missing),
        marks=dict(clean_marks),
        cost_basis=cost_basis,
        exposure_cost=exposure_cost,
        realized_daily=realized_daily,
        ledger_equity=ledger_equity,
        peak_equity=peak_equity,
        market_value=market_value if complete else None,
        exposure_market=market_value if complete else None,
        unrealized_net=unrealized if complete else None,
        marked_equity=marked_equity,
        drawdown=drawdown,
        drawdown_pct=drawdown_pct,
        per_position=per_position,
    )
