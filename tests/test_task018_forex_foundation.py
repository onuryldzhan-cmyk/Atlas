"""Task 018 (registry v5.102): forex foundations and the MetaTrader 5 demo-only market-data provider.

The MetaTrader5 package runs on Windows only, so every test drives the provider through a scripted fake module that
mirrors the package's verified names and constants (ACCOUNT_TRADE_MODE_DEMO = 0, TIMEFRAME_H1 = 1 | 0x4000, ...).
"""

from __future__ import annotations

import ast
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

import pytest

from atlas_finance.forex import FOREX_UNIVERSE, ForexInstrument, ForexInstrumentError
from atlas_finance.forex.sessions import is_forex_market_open, new_york_utc_offset_hours, next_forex_open
from atlas_finance.market_data.contracts import MarketDataProviderProtocol
from atlas_finance.market_data.exceptions import (
    InvalidCandleError,
    InvalidCandleLimitError,
    InvalidPriceError,
    InvalidSymbolError,
    InvalidTimeframeError,
    MarketDataConfigurationError,
    MarketDataConnectionError,
    MarketDataProviderUnavailableError,
    MarketDataRequestError,
    MarketDataResponseError,
)
from atlas_finance.market_data.mt5_provider import Mt5MarketDataProvider

UTC_ = UTC


def at(text: str) -> datetime:
    return datetime.fromisoformat(text).replace(tzinfo=UTC)


# ---------------------------------------------------------------- sessions


@pytest.mark.parametrize("moment, offset", [
    ("2026-03-08T06:59:59", -5), ("2026-03-08T07:00:00", -4),          # DST starts 2nd Sunday of March 02:00 EST
    ("2026-11-01T05:59:59", -4), ("2026-11-01T06:00:00", -5),          # DST ends 1st Sunday of November 02:00 EDT
    ("2026-07-01T12:00:00", -4), ("2026-01-15T12:00:00", -5),
])
def test_new_york_offset_follows_us_daylight_saving(moment, offset):
    assert new_york_utc_offset_hours(at(moment)) == offset


@pytest.mark.parametrize("moment, is_open", [
    # summer (EDT): opens Sunday 21:00 UTC, closes Friday 21:00 UTC
    ("2026-10-25T20:59:59", False), ("2026-10-25T21:00:00", True),
    ("2026-10-30T20:59:59", True), ("2026-10-30T21:00:00", False),
    ("2026-10-31T12:00:00", False),                                    # Saturday
    ("2026-10-27T03:00:00", True),                                     # Tuesday night
    # winter (EST): opens Sunday 22:00 UTC, closes Friday 22:00 UTC
    ("2026-11-08T21:59:59", False), ("2026-11-08T22:00:00", True),
    ("2026-11-13T21:59:59", True), ("2026-11-13T22:00:00", False),
])
def test_forex_week_runs_sunday_to_friday_17_00_new_york(moment, is_open):
    assert is_forex_market_open(at(moment)) is is_open


def test_next_open_is_the_sunday_open_or_now():
    assert next_forex_open(at("2026-10-31T12:00:00")) == at("2026-11-01T22:00:00")   # DST ended that morning
    assert next_forex_open(at("2026-10-28T09:30:00")) == at("2026-10-28T09:30:00")
    with pytest.raises(ValueError):
        new_york_utc_offset_hours(datetime(2026, 1, 1))                               # naive time refused


# ---------------------------------------------------------------- instruments


def symbol_info(name="EURUSD", **over):
    base = dict(name=name, currency_base=name[:3], currency_profit=name[3:], digits=5, point=0.00001,
                trade_contract_size=100000.0, volume_min=0.01, volume_step=0.01, volume_max=100.0)
    base.update(over)
    return SimpleNamespace(**base)


def test_an_instrument_carries_pip_lot_and_contract_size():
    eur = ForexInstrument.from_symbol_info(symbol_info())
    assert (eur.base, eur.quote, eur.pip_size, eur.contract_size) == ("EUR", "USD", Decimal("0.0001"),
                                                                      Decimal("100000.0"))
    assert eur.units(Decimal("0.5")) == Decimal("50000")
    assert eur.lots_for_units(Decimal("12345")) == Decimal("0.12")             # rounded down to the step
    assert eur.lots_for_units(Decimal("999")) == 0                             # below the 0.01-lot minimum
    assert eur.lots_for_units(Decimal("1e9")) == Decimal("100.0")              # never above the maximum
    assert eur.pip_value(Decimal("100000")) == Decimal("10.0000")              # 10 USD per pip per standard lot
    three = ForexInstrument.from_symbol_info(symbol_info("GBPUSD", digits=3, point=0.001))
    assert three.pip_size == Decimal("0.010")


@pytest.mark.parametrize("over, message", [
    ({"name": "USDJPY", "currency_base": "USD", "currency_profit": "JPY"}, "not the account currency"),
    ({"name": "XAUUSD", "currency_base": "XAU", "currency_profit": "USD"}, "fiat"),
    ({"name": "BTCUSD", "currency_base": "BTC", "currency_profit": "USD"}, "fiat"),
    ({"name": "EURUSD.m"}, "six-letter"),
    ({"currency_base": "GBP"}, "do not form"),
    ({"digits": True}, "digits"), ({"digits": 9}, "digits"), ({"point": 0.0001}, "does not match"),
    ({"volume_step": 0}, "volume_step"), ({"volume_min": 0.001}, "inconsistent"),
    ({"volume_max": 0.005}, "inconsistent"), ({"trade_contract_size": "x"}, "not a number"),
    ({"trade_contract_size": float("nan")}, "finite"), ({"point": True}, "bool"),
])
def test_malformed_or_unsupported_instruments_are_refused(over, message):
    with pytest.raises(ForexInstrumentError, match=message):
        ForexInstrument.from_symbol_info(symbol_info(**over))


def test_the_default_universe_is_usd_quoted_fiat_pairs():
    assert FOREX_UNIVERSE and all(len(s) == 6 and s.endswith("USD") for s in FOREX_UNIVERSE)


# ---------------------------------------------------------------- MT5 provider (scripted fake terminal)

NOW = at("2026-10-28T10:30:20")             # a Wednesday, market open
SERVER_OFFSET = 3                           # broker server time UTC+3


class FakeMt5:
    ACCOUNT_TRADE_MODE_DEMO, ACCOUNT_TRADE_MODE_CONTEST, ACCOUNT_TRADE_MODE_REAL = 0, 1, 2
    TIMEFRAME_M1, TIMEFRAME_M5, TIMEFRAME_M15, TIMEFRAME_M30 = 1, 5, 15, 30
    TIMEFRAME_H1, TIMEFRAME_H4, TIMEFRAME_D1 = 1 | 0x4000, 4 | 0x4000, 24 | 0x4000

    def __init__(self, *, trade_mode=0, init_ok=True, account=True, tick_age=2, rates=None, missing=()):
        self.trade_mode, self.init_ok, self.account, self.tick_age = trade_mode, init_ok, account, tick_age
        self.rates, self.missing = rates, set(missing)
        self.calls: list[tuple] = []
        self.shutdowns = 0

    def initialize(self, *args, **kwargs):
        self.calls.append(("initialize", args, kwargs))
        return self.init_ok

    def shutdown(self):
        self.shutdowns += 1

    def last_error(self):
        return (-1, "scripted")

    def account_info(self):
        return SimpleNamespace(trade_mode=self.trade_mode, currency="USD", leverage=100) if self.account else None

    def symbol_select(self, symbol, enable):
        return symbol not in self.missing

    def symbol_info(self, symbol):
        return symbol_info(symbol)

    def symbol_info_tick(self, symbol):
        server_now = int(NOW.timestamp()) + SERVER_OFFSET * 3600
        return SimpleNamespace(time=server_now - self.tick_age, bid=1.08345, ask=1.08357)

    def copy_rates_from_pos(self, symbol, timeframe, start, count):
        self.calls.append(("copy_rates_from_pos", symbol, timeframe, start, count))
        return self.rates


def server_bar(utc_open: datetime, o=1.0800, h=1.0810, l=1.0790, c=1.0805, tick_volume=1234, spread=12):
    return {"time": int(utc_open.timestamp()) + SERVER_OFFSET * 3600, "open": o, "high": h, "low": l, "close": c,
            "tick_volume": tick_volume, "spread": spread, "real_volume": 0}


def provider(fake=None, **kw):
    return Mt5MarketDataProvider(mt5_module=fake or FakeMt5(), clock=lambda: NOW, **kw)


def test_the_provider_satisfies_the_market_data_contract():
    p = provider()
    assert isinstance(p, MarketDataProviderProtocol) or all(
        hasattr(p, name) for name in ("provider_name", "connected", "connect", "disconnect", "get_price",
                                      "get_candles"))
    assert p.provider_name == "mt5" and p.connected is False


@pytest.mark.parametrize("mode", [1, 2])
def test_contest_and_real_accounts_are_refused_and_the_terminal_released(mode):
    fake = FakeMt5(trade_mode=mode)
    with pytest.raises(MarketDataConfigurationError, match="DEMO"):
        provider(fake).connect()
    assert fake.shutdowns == 1


def test_a_demo_account_connects_without_credentials_and_measures_the_server_offset():
    fake = FakeMt5()
    p = provider(fake)
    assert p.connect() is True and p.connected
    assert ("initialize", (), {}) in fake.calls                      # the terminal's own login: no credentials
    assert p.server_utc_offset_hours == SERVER_OFFSET
    assert set(p.instruments) == set(FOREX_UNIVERSE)
    p.disconnect()
    assert not p.connected and fake.shutdowns == 1


@pytest.mark.parametrize("fake, error", [
    (FakeMt5(init_ok=False), MarketDataConnectionError), (FakeMt5(account=False), MarketDataConnectionError),
    (FakeMt5(missing={"GBPUSD"}), InvalidSymbolError), (FakeMt5(tick_age=900), MarketDataConfigurationError),
])
def test_connection_failures_are_refused_and_release_the_terminal(fake, error):
    with pytest.raises(error):
        provider(fake).connect()
    assert fake.shutdowns == (0 if error is MarketDataConnectionError and not fake.init_ok else 1)


def test_the_offset_is_never_guessed_while_the_market_is_closed():
    saturday = at("2026-10-31T12:00:00")
    with pytest.raises(MarketDataConfigurationError, match="closed"):
        Mt5MarketDataProvider(mt5_module=FakeMt5(), clock=lambda: saturday).connect()
    p = Mt5MarketDataProvider(mt5_module=FakeMt5(), clock=lambda: saturday, server_utc_offset_hours=2)
    assert p.connect() and p.server_utc_offset_hours == 2


@pytest.mark.parametrize("bad", [True, 15, -13, 2.5, "3"])
def test_a_configured_offset_must_be_a_whole_hour_in_range(bad):
    with pytest.raises(MarketDataConfigurationError):
        Mt5MarketDataProvider(mt5_module=FakeMt5(), server_utc_offset_hours=bad)


def test_the_package_missing_is_a_clear_configuration_error(monkeypatch):
    import importlib

    real = importlib.import_module

    def no_mt5(name, *args, **kwargs):
        if name == "MetaTrader5":
            raise ImportError("no MetaTrader5 here")
        return real(name, *args, **kwargs)

    monkeypatch.setattr(importlib, "import_module", no_mt5)
    with pytest.raises(MarketDataConfigurationError, match="Windows"):
        Mt5MarketDataProvider(clock=lambda: NOW).connect()


def test_candles_are_closed_bars_in_utc_oldest_first_with_tick_volume():
    hour = timedelta(hours=1)
    opens = [at("2026-10-28T07:00:00") + i * hour for i in range(4)]             # 07, 08, 09, 10 (forming)
    fake = FakeMt5(rates=[server_bar(t) for t in opens])
    p = provider(fake)
    p.connect()
    candles = p.get_candles("eurusd", "1h", 4)
    assert ("copy_rates_from_pos", "EURUSD", FakeMt5.TIMEFRAME_H1, 1, 4) in fake.calls   # from position 1
    assert [c.open_time for c in candles] == opens[:3]                         # the 10:00 bar has not closed
    first = candles[0]
    assert first.close_time == opens[0] + hour - timedelta(milliseconds=1) and first.closed
    assert first.volume == 1234.0 and first.metadata["volume_kind"] == "TICK"
    assert "quote_volume" not in first.metadata                                # no invented exchange volume
    assert first.provider == "mt5" and first.symbol == "EURUSD"


@pytest.mark.parametrize("bar, error", [
    (dict(h=1.0700), InvalidCandleError), (dict(l=1.0900), InvalidCandleError), (dict(o=0.0), InvalidCandleError),
    (dict(c=float("nan")), InvalidCandleError), (dict(o=True), InvalidCandleError), (dict(c="1.08"), InvalidCandleError),
    (dict(tick_volume=-1), InvalidCandleError),
])
def test_malformed_bars_are_refused(bar, error):
    p = provider(FakeMt5(rates=[server_bar(at("2026-10-28T07:00:00"), **bar)]))
    p.connect()
    with pytest.raises(error):
        p.get_candles("EURUSD", "1h", 1)


def test_bars_out_of_order_or_duplicated_are_refused():
    t = at("2026-10-28T07:00:00")
    for rates in ([server_bar(t), server_bar(t)], [server_bar(t + timedelta(hours=1)), server_bar(t)]):
        p = provider(FakeMt5(rates=rates))
        p.connect()
        with pytest.raises(MarketDataResponseError):
            p.get_candles("EURUSD", "1h", 2)


def test_request_validation_and_failures():
    p = provider(FakeMt5(rates=None))
    with pytest.raises(MarketDataProviderUnavailableError):
        p.get_candles("EURUSD", "1h", 10)
    p.connect()
    with pytest.raises(InvalidSymbolError):
        p.get_candles("BTCUSDT", "1h", 10)
    with pytest.raises(InvalidTimeframeError):
        p.get_candles("EURUSD", "2h", 10)
    for limit in (0, 1001, True, 1.5):
        with pytest.raises(InvalidCandleLimitError):
            p.get_candles("EURUSD", "1h", limit)
    with pytest.raises(MarketDataRequestError):
        p.get_candles("EURUSD", "1h", 10)                                      # copy_rates returned None


def test_price_is_the_bid_with_ask_and_spread_in_pips():
    p = provider()
    p.connect()
    price = p.get_price("EURUSD")
    assert price.price == 1.08345 and price.metadata["ask"] == 1.08357
    assert price.metadata["spread_pips"] == pytest.approx(1.2)
    assert price.source_timestamp == NOW.replace(microsecond=0) - timedelta(seconds=2)


@pytest.mark.parametrize("bid, ask", [(1.1, 1.0), (0.0, 1.0), (True, 1.0), (float("inf"), 1.0), ("1.1", 1.2)])
def test_bad_quotes_are_refused(bid, ask, monkeypatch):
    fake = FakeMt5()
    p = provider(fake)
    p.connect()
    monkeypatch.setattr(fake, "symbol_info_tick", lambda s: SimpleNamespace(time=int(NOW.timestamp()), bid=bid,
                                                                           ask=ask))
    with pytest.raises(InvalidPriceError):
        p.get_price("EURUSD")


def test_the_provider_has_no_order_path():
    tree = ast.parse(Path("atlas_finance/market_data/mt5_provider.py").read_text(encoding="utf-8"))
    used = {node.attr for node in ast.walk(tree) if isinstance(node, ast.Attribute)}
    assert not used & {"order_send", "order_check", "positions_get", "orders_get", "Buy", "Sell", "Close", "login"}
