"""Data health check (registry v5.45): real book checks, realism, never writes to the book."""

from __future__ import annotations

import hashlib
import json
from decimal import Decimal as D

from core.application import (EXECUTION_APPLIED_EXECUTIONS_FILE, EXECUTION_CLOSED_POSITIONS_FILE,
                              EXECUTION_FINANCIAL_STATE_FILE)
from core.execution_models import ExecutionResult
from core.execution_portfolio_foundation import (AppliedExecutionArchiveStore, ClosedPositionArchiveStore,
                                                 ExecutionPortfolioFoundation, FinancialStateStore)
from tools import data_health_check as dhc


def _fill(action, base, price, fee, eid, pid="long:BTCUSDT:1"):
    return ExecutionResult(success=True, status="PAPER_EXECUTED", execution_id=eid, position_id=pid,
                           symbol="BTCUSDT", action=action, filled_price=price, filled_base_quantity=D(base),
                           filled_quote_notional=D(str(price)) * D(base), fee_amount=D(fee), fee_currency="USDT",
                           idempotency_key=eid, provenance_ref="t")


def _book(d, exit_price=110):
    store = FinancialStateStore(d / EXECUTION_FINANCIAL_STATE_FILE)
    store.initialize(D("1000"))
    f = ExecutionPortfolioFoundation(store, applied_archive=AppliedExecutionArchiveStore(d / EXECUTION_APPLIED_EXECUTIONS_FILE),
                                     closed_archive=ClosedPositionArchiveStore(d / EXECUTION_CLOSED_POSITIONS_FILE))
    f.set_reserved_capital(D("0"))
    kw = dict(risk_authorized=True, reservation_confirmed=True)
    f.apply_confirmed(_fill("BUY", "1", 100, "0.1", "e1"), expected_position_version=None, **kw)
    f.apply_confirmed(_fill("SELL", "1", exit_price, "0.11", "e2"), expected_position_version=1, **kw)
    f.apply_confirmed(_fill("BUY", "2", 100, "0.2", "e3", pid="long:BTCUSDT:2"), expected_position_version=None, **kw)


def _digest(d):
    return {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(d.iterdir())}


def test_healthy_book_is_ok_and_never_modified(tmp_path):
    _book(tmp_path)
    before = _digest(tmp_path)
    results = {r["check"]: r for r in dhc.check_financial_state(tmp_path)}
    assert results["financial_state"]["status"] == "OK" and "starting capital 1000.00" in results["financial_state"]["detail"]
    assert results["trade_realism"]["status"] == "OK"
    assert _digest(tmp_path) == before


def test_unrealistic_trade_is_flagged(tmp_path):
    _book(tmp_path, exit_price=400)  # +300 % on one trade = bad data
    realism = {r["check"]: r for r in dhc.check_financial_state(tmp_path)}["trade_realism"]
    assert realism["status"] == "FAIL" and "moves more than" in realism["detail"]


def test_tampered_book_fails(tmp_path):
    _book(tmp_path)
    path = tmp_path / EXECUTION_FINANCIAL_STATE_FILE
    state = json.loads(path.read_text())
    state["cash"] = "-5"
    path.write_text(json.dumps(state))
    result = dhc.check_financial_state(tmp_path)[0]
    assert result["status"] == "FAIL"


def test_missing_state_is_unknown_not_ok(tmp_path):
    assert dhc.check_financial_state(tmp_path)[0]["status"] == "UNKNOWN"


def test_exit_code_counts_unknown_as_not_ok(tmp_path, monkeypatch):
    monkeypatch.delenv("ATLAS_LOG_DIRECTORY", raising=False)
    assert dhc.main(["--state-dir", str(tmp_path)]) in (1, 2)
