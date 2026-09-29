"""Live PAPER portfolio view (registry v5.40): real book + real prices, nothing invented."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal as D

from core.execution_models import ExecutionResult
from core.execution_portfolio_foundation import (
    AppliedExecutionArchiveStore,
    ClosedPositionArchiveStore,
    ExecutionPortfolioFoundation,
    FinancialStateStore,
)
from observability import portfolio_view

NOW = datetime(2026, 9, 29, 12, 0, tzinfo=UTC)


def _foundation(tmp_path):
    store = FinancialStateStore(tmp_path / "fs.json")
    store.initialize(D("1000"))
    f = ExecutionPortfolioFoundation(store, applied_archive=AppliedExecutionArchiveStore(tmp_path / "a.jsonl"),
                                     closed_archive=ClosedPositionArchiveStore(tmp_path / "c.jsonl"))
    f.set_reserved_capital(D("0"))
    return f


def _fill(action, symbol, base, price, fee, eid):
    return ExecutionResult(success=True, status="PAPER_EXECUTED", execution_id=eid, position_id=f"long:{symbol}",
                           symbol=symbol, action=action, filled_price=price, filled_base_quantity=D(str(base)),
                           filled_quote_notional=D(str(price)) * D(str(base)), fee_amount=D(str(fee)),
                           fee_currency="USDT", idempotency_key=eid, provenance_ref="test")


def _book(tmp_path):
    f = _foundation(tmp_path)
    kw = dict(risk_authorized=True, reservation_confirmed=True)
    f.apply_confirmed(_fill("BUY", "BTCUSDT", "2", 100, "0.2", "e1"), expected_position_version=None, **kw)
    f.apply_confirmed(_fill("SELL", "BTCUSDT", "1", 110, "0.11", "e2"), expected_position_version=1, **kw)
    f.apply_confirmed(_fill("BUY", "ETHUSDT", "10", 20, "0.2", "e3"), expected_position_version=None, **kw)
    return f.snapshot()


def test_starting_capital_is_derived_exactly_from_the_real_book(tmp_path):
    view = portfolio_view.build(_book(tmp_path), {"BTCUSDT": 120, "ETHUSDT": 18}, NOW.isoformat(), now=NOW)
    assert view["starting_capital"] == "1000.00"
    # BTC: 1 left at cost 100, now 120 -> +20; ETH: 10 at cost 200, now 180 -> -20
    assert view["unrealized_pnl"] == "0.00"
    # realized: +10 gross on the half sold, fees 0.2 + 0.11 + 0.2 = 0.51
    assert view["realized_net_pnl"] == "9.49"
    assert view["equity"] == "1009.49" and view["total_pnl"] == "9.49" and view["total_pnl_pct"] == "0.95"
    rows = {r["symbol"]: r for r in view["positions"]}
    assert rows["BTCUSDT"]["unrealized_pnl"] == "20.00" and rows["BTCUSDT"]["unrealized_pct"] == "20.00"
    assert rows["ETHUSDT"]["unrealized_pnl"] == "-20.00"
    assert view["prices_stale"] is False and view["mode"] == "PAPER"


def test_missing_price_is_never_guessed(tmp_path):
    view = portfolio_view.build(_book(tmp_path), {"BTCUSDT": 120}, NOW.isoformat(), now=NOW)
    assert view["equity"] is None and view["total_pnl"] is None and view["unrealized_pnl"] is None
    assert "ETHUSDT" in view["incomplete_reason"]
    assert {r["symbol"]: r["price"] for r in view["positions"]}["ETHUSDT"] is None
    assert view["realized_net_pnl"] == "9.49"  # what is known is still shown


def test_old_or_unknown_price_time_is_flagged_stale(tmp_path):
    old = (NOW - timedelta(minutes=10)).isoformat()
    book = _book(tmp_path)
    assert portfolio_view.build(book, {"BTCUSDT": 1, "ETHUSDT": 1}, old, now=NOW)["prices_stale"] is True
    assert portfolio_view.build(book, {"BTCUSDT": 1, "ETHUSDT": 1}, None, now=NOW)["prices_stale"] is True


def test_empty_book_and_incomplete_snapshot(tmp_path):
    empty = portfolio_view.build(_foundation(tmp_path).snapshot(), {}, NOW.isoformat(), now=NOW)
    assert empty["starting_capital"] == "1000.00" and empty["total_pnl"] == "0.00" and empty["positions"] == []
    assert portfolio_view.build({"cash": "1"}, {}, None)["available"] is False


def test_route_is_read_only_and_reports_unattached_runtime():
    from fastapi.testclient import TestClient

    import web_app

    client = TestClient(web_app.create_app())
    r = client.get("/api/portfolio")
    assert r.status_code in (200, 403)
    if r.status_code == 200:
        assert r.json() == {"available": False, "reason": "PORTFOLIO_FOUNDATION_NOT_ATTACHED"}
    assert client.post("/api/portfolio").status_code == 405
