"""Task 021 (registry v5.104): the forex spread cost model - with ATLAS_FILL_MODEL=BOOK in FOREX, a PAPER BUY fills
at the MT5 ask and a SELL at the bid, so the spread is paid on every fill; no fresh quote rejects the order."""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal
from types import SimpleNamespace

import pytest

from atlas_finance.market_data.mt5_provider import Mt5MarketDataProvider, Mt5QuoteFillProvider
from atlas_finance.market_data.order_book_provider import OrderBookFillProvider
from core.application import AtlasApplication
from tests.test_block5c_upstream_sizing_authority import seed_state
from tests.test_task018_forex_foundation import NOW, FakeMt5


def fill(fake=None, *, clock=lambda: NOW, connect=True, **kw):
    provider = Mt5MarketDataProvider(mt5_module=fake or FakeMt5(), clock=clock)
    if connect:
        provider.connect()
    return Mt5QuoteFillProvider(provider, clock=clock, **kw)


def test_a_buy_pays_the_ask_and_a_sell_receives_the_bid():
    quotes = fill()
    assert quotes("EURUSD", "BUY", Decimal("1000")) == Decimal("1.08357")
    assert quotes("EURUSD", "sell", Decimal("1000")) == Decimal("1.08345")
    assert quotes("EURUSD", "BUY", Decimal("1000")) - quotes("EURUSD", "SELL", Decimal("1000")) == Decimal("0.00012")


@pytest.mark.parametrize("age_seconds, priced", [(0, True), (60, True), (61, False), (3600, False), (-60, True),
                                                 (-61, False)])
def test_a_stale_or_future_quote_is_no_price(age_seconds, priced):
    fake = FakeMt5(tick_age=2)
    quotes = fill(fake)
    # the fake tick is 2 s old at NOW; read it at NOW + (age - 2) s
    later = NOW + timedelta(seconds=age_seconds - 2)
    quotes._clock = lambda: later
    assert (quotes("EURUSD", "BUY", Decimal("1")) is not None) is priced


@pytest.mark.parametrize("case", ["disconnected", "raises", "bad side", "unknown symbol", "bad quote"])
def test_anything_unknown_is_no_price_and_never_raises(case, monkeypatch):
    fake = FakeMt5()
    quotes = fill(fake, connect=case != "disconnected")
    if case == "raises":
        monkeypatch.setattr(fake, "symbol_info_tick", lambda symbol: 1 / 0)
    if case == "bad quote":
        monkeypatch.setattr(fake, "symbol_info_tick",
                            lambda symbol: SimpleNamespace(time=int(NOW.timestamp()) + 3 * 3600, bid=1.1, ask=1.0))
    side = "HOLD" if case == "bad side" else "BUY"
    symbol = "USDJPY" if case == "unknown symbol" else "EURUSD"
    assert quotes(symbol, side, Decimal("1000")) is None


# ---------------------------------------------------------------- wiring


@pytest.mark.parametrize("market, model, expected", [
    ("FOREX", "BOOK", Mt5QuoteFillProvider), ("CRYPTO", "BOOK", OrderBookFillProvider),
    ("FOREX", "LAST_PRICE", type(None)), ("CRYPTO", "LAST_PRICE", type(None)),
])
def test_the_book_fill_reads_the_market_s_own_quotes(tmp_path, market, model, expected):
    app = AtlasApplication(state_directory=seed_state(tmp_path / "state"), market=market, paper_fill_model=model)
    try:
        provider = getattr(app.execution, "paper_fill_provider", None)
        assert isinstance(provider, expected)
        if isinstance(provider, Mt5QuoteFillProvider):
            assert provider._provider is app.market_feed.provider          # one terminal connection, demo only
    finally:
        app.stop()


# ---------------------------------------------------------------- through the execution manager's fill path


def manager_with(price):
    app_execution = SimpleNamespace(paper_fill_provider=lambda symbol, side, notional: price,
                                    instrument_rules={"EURUSD": SimpleNamespace(price_tick=Decimal("0.00001"))})
    from core.execution_manager import ExecutionManager

    return ExecutionManager._shadow_book_fill_price.__get__(app_execution)


def request(action="BUY"):
    return SimpleNamespace(action=action, symbol="EURUSD", approved_quote_allocation=Decimal("2500"),
                           price=1.0834)


def test_the_manager_fills_at_the_quote_rounded_against_atlas_and_rejects_without_one():
    assert manager_with(Decimal("1.083571"))(request("BUY")) == pytest.approx(1.08358)   # ceiling for a BUY
    assert manager_with(None)(request("BUY")) is None                                    # rejected, never last price
