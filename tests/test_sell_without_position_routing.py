"""SELL of an unheld symbol: own reason code + MarketLoop HOLD routing.

Owner decision (registry v5.04, "Ikisini birlikte"):

* ExecutionManager refuses an *unsized* SELL of a symbol the durable book
  does not hold with ``NO_POSITION_TO_SELL`` instead of the misleading
  ``INVALID_FINANCIAL_INPUT``; nothing is admitted or reserved.
* MarketLoop treats a SELL decision for a symbol the ready durable book
  provably does not hold as HOLD: it is skipped and counted, never routed.
  Any doubt about the book (missing, not ready, unreadable) routes the
  decision unchanged so ExecutionManager stays the authority.
"""
from __future__ import annotations

from decimal import Decimal as D

import pytest

from core.execution_manager import ExecutionManager
from core.execution_models import ExecutionRequest
from tests.test_block5b_single_sizing_authority import (
    assert_no_execution_residue,
    buy,
    sell,
)
from tests.test_block5c_upstream_sizing_authority import (
    application,
    execution_enabled_loop,
)


@pytest.fixture
def flat_app(tmp_path):
    app = application(tmp_path)
    app.execution.start()
    return app


@pytest.fixture
def holding_app(tmp_path):
    app = application(tmp_path, positions=[("BTCUSDT", "10", "10")])
    app.paper_trader.open_trade("BTCUSDT", 10, 100)
    app.execution.start()
    return app


# ---------------------------------------------------------------- helper


@pytest.mark.parametrize("amount", [0, "0", "0.0", D("0"), 0.0])
def test_unsized_sell_is_detected(amount):
    assert ExecutionManager._is_unsized_sell_of_unheld_symbol(sell(amount=amount)) is True


@pytest.mark.parametrize("amount", [1, "40", "-1", "NaN", "Infinity", "abc", None])
def test_sized_or_malformed_sell_is_not_treated_as_unsized(amount):
    request = sell()
    request.amount = amount
    assert ExecutionManager._is_unsized_sell_of_unheld_symbol(request) is False


def test_buy_is_never_treated_as_unsized_sell():
    assert ExecutionManager._is_unsized_sell_of_unheld_symbol(buy(amount=0)) is False


def test_reduce_only_sell_is_not_treated_as_unsized():
    request = sell(amount=0)
    request.reduce_only = True
    assert ExecutionManager._is_unsized_sell_of_unheld_symbol(request) is False


def test_sell_with_proposed_allocation_is_not_treated_as_unsized():
    request = sell(amount=0)
    request.proposed_quote_allocation = D("5")
    assert ExecutionManager._is_unsized_sell_of_unheld_symbol(request) is False


# ---------------------------------------------------------------- risk_check


def test_unsized_flat_sell_is_refused_as_no_position(flat_app):
    decision = flat_app.execution.risk_check(sell(amount=0))
    assert decision["approved"] is False
    assert decision["reason"] == "NO_POSITION_TO_SELL"
    assert decision["reason"] != "INVALID_FINANCIAL_INPUT"
    assert_no_execution_residue(flat_app)


def test_sized_flat_sell_keeps_its_existing_refusal(flat_app):
    decision = flat_app.execution.risk_check(sell(amount=40))
    assert decision["approved"] is False
    assert decision["reason"] == "NON_RISK_REDUCING_SELL"
    assert_no_execution_residue(flat_app)


@pytest.mark.parametrize("amount, reason", [
    ("-1", "INVALID_FINANCIAL_INPUT"),
    ("Infinity", "INVALID_FINANCIAL_INPUT"),
    ("NaN", "RISK_STATE_RESTORATION_FAILED"),
    ("abc", "RISK_STATE_RESTORATION_FAILED"),
])
def test_malformed_sell_amount_keeps_its_pre_existing_refusal(flat_app, amount, reason):
    request = sell()
    request.amount = amount
    decision = flat_app.execution.risk_check(request)
    assert decision["approved"] is False
    assert decision["reason"] == reason


def test_held_sell_is_still_admitted_as_risk_reduction(holding_app):
    decision = holding_app.execution.risk_check(sell(amount=0))
    assert decision["approved"] is True, decision
    assert holding_app.execution.last_risk_decision["reason_code"] == "RISK_REDUCTION_APPROVED"


# ---------------------------------------------------------------- MarketLoop


def _count_execute(app, monkeypatch):
    calls = []
    original = app.execution.execute

    def spy(decision, *args, **kwargs):
        calls.append(decision)
        return original(decision, *args, **kwargs)

    monkeypatch.setattr(app.execution, "execute", spy)
    return calls


def test_loop_skips_flat_sell_as_hold(flat_app, monkeypatch):
    calls = _count_execute(flat_app, monkeypatch)
    loop = execution_enabled_loop(flat_app, "SELL")
    result = loop.process_symbol("BTCUSDT")
    assert result["status"] == "SKIPPED"
    assert result["reason"] == "NO_POSITION_TO_SELL"
    assert calls == []
    assert loop.metrics["sell_without_position_skipped"] == 1
    assert_no_execution_residue(flat_app)


def test_loop_routes_held_sell(holding_app, monkeypatch):
    calls = _count_execute(holding_app, monkeypatch)
    loop = execution_enabled_loop(holding_app, "SELL")
    result = loop.process_symbol("BTCUSDT")
    assert len(calls) == 1
    assert result["status"] == "PAPER_EXECUTED"
    assert loop.metrics["sell_without_position_skipped"] == 0


def test_loop_buy_is_unaffected(flat_app, monkeypatch):
    calls = _count_execute(flat_app, monkeypatch)
    loop = execution_enabled_loop(flat_app, "BUY")
    loop.process_symbol("BTCUSDT")
    assert len(calls) == 1
    assert loop.metrics["sell_without_position_skipped"] == 0


class _NotReady:
    ready = False

    def snapshot(self):
        return {"positions": {}}


class _Raises:
    ready = True

    def snapshot(self):
        raise RuntimeError("unreadable")


class _NonDict:
    ready = True

    def snapshot(self):
        return {"positions": ["BTCUSDT"]}


@pytest.mark.parametrize("foundation", [None, _NotReady(), _Raises(), _NonDict()])
def test_doubt_about_the_book_never_skips(flat_app, monkeypatch, foundation):
    loop = execution_enabled_loop(flat_app, "SELL")
    monkeypatch.setattr(flat_app.execution, "portfolio_foundation", foundation, raising=False)
    assert loop._sell_symbol_known_flat("BTCUSDT") is False


def test_known_flat_true_for_ready_book_without_symbol(flat_app):
    assert execution_enabled_loop(flat_app, "SELL")._sell_symbol_known_flat("BTCUSDT") is True


def test_known_flat_false_for_held_symbol(holding_app):
    assert execution_enabled_loop(holding_app, "SELL")._sell_symbol_known_flat("BTCUSDT") is False


class _LowercaseKey:
    ready = True

    def snapshot(self):
        return {"positions": {" btcusdt ": {"base_quantity": "1"}}}


def test_differently_cased_stored_key_still_counts_as_held(flat_app, monkeypatch):
    loop = execution_enabled_loop(flat_app, "SELL")
    monkeypatch.setattr(flat_app.execution, "portfolio_foundation", _LowercaseKey(), raising=False)
    assert loop._sell_symbol_known_flat("BTCUSDT") is False
