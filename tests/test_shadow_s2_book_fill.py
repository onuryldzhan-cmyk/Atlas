"""Shadow stage S2 (owner approval 2026-10-02): PAPER fills priced against the live order book.

The mode stays PAPER (nothing is sent). With a provider a fill is the book VWAP for the
order's notional, rounded against Atlas; no price means REJECT, never a fallback to the
last price. Without a provider the historical fill is unchanged. Config: ATLAS_FILL_MODEL.
"""
from __future__ import annotations

from decimal import Decimal as D

import pytest

from atlas_finance.market_data.order_book_provider import OrderBookFillProvider, book_fill_price, walk_vwap
from core.atlas_config import AtlasConfigError, load_config
from tests.test_block5e_fee_settlement_accounting import application

BOOK = {"bids": [["99", "5"], ["98", "100"]], "asks": [["101", "5"], ["102", "100"]]}


# ----------------------------------------------------------------- provider
def test_vwap_walks_the_correct_side_and_refuses_thin_or_bad_books():
    assert book_fill_price(BOOK, "BUY", D("1000")) == D("1000") / (D(5) + D(495) / D(102))
    assert book_fill_price(BOOK, "SELL", D("1000")) == D("1000") / (D(5) + D(505) / D(98))
    assert book_fill_price(BOOK, "BUY", D("10000000")) is None          # deeper than the book
    assert book_fill_price({"bids": [["101", "1"]], "asks": [["100", "1"]]}, "BUY", D("10")) is None  # crossed
    assert book_fill_price({}, "BUY", D("10")) is None
    assert book_fill_price(BOOK, "HOLD", D("10")) is None
    for bad in (D("0"), D("-1"), D("NaN")):
        assert walk_vwap(BOOK["asks"], bad) is None
    assert walk_vwap([["x", "1"]], D("1")) is None


def test_provider_never_raises():
    def boom(symbol):
        raise OSError("network down")

    assert OrderBookFillProvider(boom)("BTCUSDT", "BUY", D("100")) is None
    assert OrderBookFillProvider(lambda s: BOOK)("BTCUSDT", "buy", D("100")) == D("101")


# ----------------------------------------------------------------- execution
def _run(tmp_path, provider):
    app = application(tmp_path)
    app.execution.start()
    app.execution.paper_fill_provider = provider
    m = app.execution
    buy = m.execute({"symbol": "BTCUSDT", "action": "BUY", "price": 10.0, "amount": 1000,
                     "confidence": 90.0, "risk": "MEDIUM", "request_id": "b1"})
    return app, m, buy


def test_book_fill_prices_buy_and_sell_from_the_book(tmp_path):
    calls = []

    def provider(symbol, side, notional):
        calls.append((symbol, side, notional))
        return D("10.05") if side == "BUY" else D("9.95")

    app, m, buy = _run(tmp_path, provider)
    assert buy["status"] == "PAPER_EXECUTED" and buy["commit_outcome"] == "COMMITTED", buy
    assert D(str(buy["filled_price"])) == D("10.05")
    assert calls[0][:2] == ("BTCUSDT", "BUY") and calls[0][2] > 0
    sell = m.execute({"symbol": "BTCUSDT", "action": "SELL", "price": 10.0, "amount": 0,
                      "confidence": 90.0, "risk": "MEDIUM", "request_id": "s1"})
    assert sell["status"] == "PAPER_EXECUTED", sell
    assert D(str(sell["filled_price"])) == D("9.95") and calls[1][1] == "SELL"
    assert "BTCUSDT" not in app.portfolio_foundation.snapshot()["positions"]


@pytest.mark.parametrize("answer", [None, D("NaN"), D("0"), 10.05, "boom"])
def test_no_valid_book_price_rejects_and_books_nothing(tmp_path, answer):
    def provider(symbol, side, notional):
        if answer == "boom":
            raise RuntimeError("provider bug")
        return answer

    app, _, buy = _run(tmp_path, provider)
    assert buy["status"] != "PAPER_EXECUTED", buy
    assert "SHADOW_BOOK_PRICE_UNAVAILABLE" in str(buy) and buy.get("commit_outcome") == "NOT_COMMITTED"
    assert "BTCUSDT" not in app.portfolio_foundation.snapshot()["positions"]
    assert app.execution.reservation_ledger.get("b1").status.name == "RELEASED"  # capital is given back


def test_without_provider_the_paper_fill_is_unchanged(tmp_path):
    _, _, buy = _run(tmp_path, None)
    assert D(str(buy["filled_price"])) == D("10")


# ----------------------------------------------------------------- config
def _env(tmp_path, **extra):
    (tmp_path / "state").mkdir(exist_ok=True)
    return {"ATLAS_STATE_DIRECTORY": str(tmp_path / "state"), **extra}


def test_config_defaults_to_last_price_and_accepts_book_only_in_a_shadow_directory(tmp_path, monkeypatch):
    for k, v in _env(tmp_path).items():
        monkeypatch.setenv(k, v)
    cfg = load_config(dict(_env(tmp_path)), execution_mode="PAPER", paper_confidence_experiment=False)
    assert cfg.fill_model == "LAST_PRICE"
    with pytest.raises(AtlasConfigError, match="shadow"):
        load_config(_env(tmp_path, ATLAS_FILL_MODEL="BOOK"), execution_mode="PAPER", paper_confidence_experiment=False)
    (tmp_path / "AtlasState" / "shadow").mkdir(parents=True)
    shadow = {"ATLAS_STATE_DIRECTORY": str(tmp_path / "AtlasState" / "shadow"), "ATLAS_FILL_MODEL": "book"}
    monkeypatch.setenv("ATLAS_STATE_DIRECTORY", shadow["ATLAS_STATE_DIRECTORY"])
    cfg = load_config(shadow, execution_mode="PAPER", paper_confidence_experiment=False)
    assert cfg.fill_model == "BOOK" and cfg.execution_mode == "PAPER"


def test_config_refuses_unknown_model_and_book_without_explicit_state(tmp_path, monkeypatch):
    monkeypatch.delenv("ATLAS_STATE_DIRECTORY", raising=False)
    with pytest.raises(AtlasConfigError, match="ATLAS_FILL_MODEL"):
        load_config({"ATLAS_FILL_MODEL": "MAGIC"}, execution_mode="PAPER", paper_confidence_experiment=False)
    with pytest.raises(AtlasConfigError, match="needs its own"):
        load_config({"ATLAS_FILL_MODEL": "BOOK"}, execution_mode="PAPER", paper_confidence_experiment=False)
    with pytest.raises(AtlasConfigError, match="only PAPER"):
        load_config({}, execution_mode="LIVE", paper_confidence_experiment=False)  # unchanged invariant


def test_a_hung_book_lookup_is_abandoned_at_the_deadline():
    import threading
    import time

    gate = threading.Event()

    def hang(symbol):
        gate.wait(5)
        return BOOK

    started = time.monotonic()
    assert OrderBookFillProvider(hang, deadline_seconds=0.2)("BTCUSDT", "BUY", D("100")) is None
    assert time.monotonic() - started < 2
    gate.set()


def test_config_requires_a_folder_named_exactly_shadow(tmp_path, monkeypatch):
    (tmp_path / "old_shadowpaper").mkdir()
    env = {"ATLAS_STATE_DIRECTORY": str(tmp_path / "old_shadowpaper"), "ATLAS_FILL_MODEL": "BOOK"}
    monkeypatch.setenv("ATLAS_STATE_DIRECTORY", env["ATLAS_STATE_DIRECTORY"])
    with pytest.raises(AtlasConfigError, match="named 'shadow'"):
        load_config(env, execution_mode="PAPER", paper_confidence_experiment=False)


def test_book_price_far_above_the_request_never_settles_above_the_allocation(tmp_path):
    app, _, buy = _run(tmp_path, lambda symbol, side, notional: D("12.5") if side == "BUY" else D("9"))
    if buy["status"] == "PAPER_EXECUTED":
        reservation = app.execution.reservation_ledger.get("b1")
        assert reservation.amount <= D("1000")
        pos = app.portfolio_foundation.snapshot()["positions"]["BTCUSDT"]
        assert D(str(pos["base_quantity"])) * D("12.5") <= D("1000")
    else:
        assert buy.get("commit_outcome") == "NOT_COMMITTED"


def test_partial_sell_is_priced_for_the_amount_sold_not_the_whole_holding(tmp_path):
    seen = []

    def provider(symbol, side, notional):
        seen.append((side, notional))
        return D("10")

    app, m, buy = _run(tmp_path, provider)
    assert buy["status"] == "PAPER_EXECUTED", buy
    held = D(str(app.portfolio_foundation.snapshot()["positions"]["BTCUSDT"]["base_quantity"]))
    m.execute({"symbol": "BTCUSDT", "action": "SELL", "price": 10.0, "amount": 300,
               "confidence": 90.0, "risk": "MEDIUM", "request_id": "s1"})
    sells = [n for side, n in seen if side == "SELL"]
    assert sells and sells[0] < held * D("10")  # less than the whole position's notional
