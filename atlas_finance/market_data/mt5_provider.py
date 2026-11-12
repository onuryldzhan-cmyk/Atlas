"""MetaTrader 5 market-data provider (Task 018, registry v5.102): forex prices and candles for Atlas.

Implements ``MarketDataProviderProtocol`` (provider_name, connected, connect, disconnect, get_price, get_candles), so
the existing feed, candle processing and MarketLoop consume forex bars the way they consumed Binance bars.

Security boundary
-----------------
- Market data only: this module never calls order_send, order_check or any position function.
- Demo accounts only: ``connect`` refuses a terminal logged in to a contest or real account (live authority DENIED).
- No credentials: it attaches to the terminal's current login (``initialize()`` with no arguments); no password,
  login or server name is read, stored or logged here.

MetaTrader 5 facts this relies on
---------------------------------
The ``MetaTrader5`` package (MetaQuotes, MIT, PyPI 5.0.6231) runs on Windows only, next to a running terminal.
Function, field and constant names were checked against that package (ACCOUNT_TRADE_MODE_DEMO = 0, TIMEFRAME_H1 =
1 | 0x4000, ...). The exact call semantics below follow the MQL5 documentation, which could not be fetched in the
build environment, so they are UNKNOWN until checked on the owner's terminal:
- ``copy_rates_from_pos(symbol, timeframe, start_pos, count)``; position 0 is the bar still forming, so reading from
  position 1 returns closed bars only.
- Bar and tick times are seconds in the broker's *server* time, not UTC. The offset is taken from configuration, or
  measured at connect from a fresh tick while the market is open; without either the provider refuses to connect.
Volumes: forex is traded over the counter and has no exchange volume. ``volume`` is the tick count (number of price
changes), labelled ``volume_kind = "TICK"``; no quote volume is invented.
"""

from __future__ import annotations

import importlib
import math
from collections.abc import Callable, Mapping, Sequence
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

from atlas_finance.forex.instruments import FOREX_UNIVERSE, ForexInstrument, ForexInstrumentError
from atlas_finance.forex.sessions import is_forex_market_open
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
from atlas_finance.market_data.models import MarketCandle, MarketPrice

PROVIDER_NAME = "mt5"
TIMEFRAMES: Mapping[str, tuple[str, int]] = {          # Atlas timeframe -> (MT5 constant, seconds)
    "1m": ("TIMEFRAME_M1", 60), "5m": ("TIMEFRAME_M5", 300), "15m": ("TIMEFRAME_M15", 900),
    "30m": ("TIMEFRAME_M30", 1800), "1h": ("TIMEFRAME_H1", 3600), "4h": ("TIMEFRAME_H4", 14400),
    "1d": ("TIMEFRAME_D1", 86400),
}
MAXIMUM_CANDLE_LIMIT = 1000
OFFSET_TOLERANCE_SECONDS = 300      # a measured offset must sit within 5 minutes of a whole hour
MAX_TICK_AGE_SECONDS = 300          # and come from a tick at most 5 minutes old (after removing the offset)
MAX_CLOCK_LEAD_SECONDS = 60         # a tick may sit at most 1 minute ahead of this machine's clock


def _number(value: Any, what: str, error: type[Exception]) -> float:
    """A finite float from an int, float or numpy scalar; never from a bool or text."""
    if isinstance(value, (bool, str, bytes)) or value is None:
        raise error(f"{what} is not a number: {value!r}")
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise error(f"{what} is not a number: {value!r}") from exc
    if not math.isfinite(number):
        raise error(f"{what} is not finite: {value!r}")
    return number


def _load_mt5() -> Any:
    try:
        return importlib.import_module("MetaTrader5")
    except ImportError as exc:
        raise MarketDataConfigurationError(
            "The MetaTrader5 package is not installed. It runs on Windows only: 'pip install MetaTrader5', with a "
            "MetaTrader 5 terminal running and logged in to a DEMO account.") from exc


class Mt5MarketDataProvider:
    """Read-only forex market data from a running MetaTrader 5 terminal logged in to a demo account."""

    def __init__(self, *, symbols: Sequence[str] = FOREX_UNIVERSE, server_utc_offset_hours: int | None = None,
                 mt5_module: Any | None = None, clock: Callable[[], datetime] | None = None) -> None:
        if server_utc_offset_hours is not None and (isinstance(server_utc_offset_hours, bool)
                                                    or not isinstance(server_utc_offset_hours, int)
                                                    or not -12 <= server_utc_offset_hours <= 14):
            raise MarketDataConfigurationError("server_utc_offset_hours must be an integer from -12 to 14")
        if not symbols:
            raise MarketDataConfigurationError("at least one symbol is required")
        self._symbols = tuple(dict.fromkeys(str(s).upper() for s in symbols))
        self._configured_offset = server_utc_offset_hours
        self._mt5 = mt5_module
        self._clock = clock or (lambda: datetime.now(UTC))
        self._connected = False
        self._offset_hours: int | None = None
        self._instruments: dict[str, ForexInstrument] = {}

    # ---------------------------------------------------------------- protocol properties

    @property
    def provider_name(self) -> str:
        return PROVIDER_NAME

    @property
    def connected(self) -> bool:
        return self._connected

    @property
    def maximum_candle_limit(self) -> int:
        return MAXIMUM_CANDLE_LIMIT

    @property
    def supported_timeframes(self) -> tuple[str, ...]:
        return tuple(TIMEFRAMES)

    @property
    def instruments(self) -> Mapping[str, ForexInstrument]:
        return dict(self._instruments)

    @property
    def server_utc_offset_hours(self) -> int | None:
        return self._offset_hours

    # ---------------------------------------------------------------- lifecycle

    def connect(self) -> bool:
        mt5 = self._mt5 if self._mt5 is not None else _load_mt5()
        self._mt5 = mt5
        if not mt5.initialize():
            raise MarketDataConnectionError(f"MetaTrader 5 initialize failed: {mt5.last_error()}")
        try:
            account = mt5.account_info()
            if account is None:
                raise MarketDataConnectionError(f"MetaTrader 5 has no logged-in account: {mt5.last_error()}")
            if getattr(account, "trade_mode", None) != mt5.ACCOUNT_TRADE_MODE_DEMO:
                raise MarketDataConfigurationError(
                    "The MetaTrader 5 terminal is not logged in to a DEMO account; Atlas refuses contest and real "
                    "accounts (live authority DENIED).")
            instruments = {}
            for symbol in self._symbols:
                if not mt5.symbol_select(symbol, True):
                    raise InvalidSymbolError(f"{symbol} is not available on this MetaTrader 5 server")
                info = mt5.symbol_info(symbol)
                if info is None:
                    raise InvalidSymbolError(f"{symbol}: symbol_info returned nothing")
                try:
                    instruments[symbol] = ForexInstrument.from_symbol_info(info)
                except ForexInstrumentError as exc:
                    raise InvalidSymbolError(str(exc)) from exc
            offset = self._configured_offset if self._configured_offset is not None else self._measure_offset()
        except Exception:
            mt5.shutdown()
            raise
        self._instruments, self._offset_hours, self._connected = instruments, offset, True
        return True

    def disconnect(self) -> None:
        if self._mt5 is not None and self._connected:
            self._mt5.shutdown()
        self._connected = False

    def _measure_offset(self) -> int:
        """Server-time offset from a fresh tick: (tick time - UTC now), which must sit near a whole hour."""
        now = self._clock()
        if not is_forex_market_open(now):
            raise MarketDataConfigurationError(
                "The forex market is closed, so the server-time offset cannot be measured from a fresh tick; set "
                "server_utc_offset_hours explicitly.")
        tick = self._mt5.symbol_info_tick(self._symbols[0])
        tick_time = _number(getattr(tick, "time", None) if tick is not None else None, "tick time",
                            MarketDataConfigurationError)
        difference = tick_time - now.timestamp()
        hours = round(difference / 3600)
        residual = difference - hours * 3600       # minus the tick's age, after removing the offset
        if not -12 <= hours <= 14 or not -min(MAX_TICK_AGE_SECONDS, OFFSET_TOLERANCE_SECONDS) <= residual \
                <= MAX_CLOCK_LEAD_SECONDS:
            raise MarketDataConfigurationError(
                f"server-time offset could not be measured reliably ({difference:.0f} s); set "
                "server_utc_offset_hours explicitly.")
        return hours

    def _require(self, symbol: str) -> tuple[Any, str, ForexInstrument]:
        if not self._connected:
            raise MarketDataProviderUnavailableError("MetaTrader 5 provider is not connected")
        key = str(symbol).upper()
        if key not in self._instruments:
            raise InvalidSymbolError(f"{symbol!r} is not in this provider's forex universe {self._symbols}")
        return self._mt5, key, self._instruments[key]

    def _to_utc(self, server_seconds: Any, field: str) -> datetime:
        seconds = _number(server_seconds, field, MarketDataResponseError)
        if seconds != int(seconds) or seconds <= 0:
            raise MarketDataResponseError(f"{field} must be a positive whole number of seconds: {server_seconds!r}")
        return datetime.fromtimestamp(int(seconds) - self._offset_hours * 3600, UTC)

    # ---------------------------------------------------------------- data

    def get_price(self, symbol: str) -> MarketPrice:
        """The latest bid (MT5 bars are built from bid prices), with ask and spread in the metadata."""
        mt5, key, instrument = self._require(symbol)
        tick = mt5.symbol_info_tick(key)
        if tick is None:
            raise MarketDataRequestError(f"{key}: no tick: {mt5.last_error()}")
        bid = _number(getattr(tick, "bid", None), f"{key} bid", InvalidPriceError)
        ask = _number(getattr(tick, "ask", None), f"{key} ask", InvalidPriceError)
        if bid <= 0 or ask <= 0:
            raise InvalidPriceError(f"{key}: bid and ask must be positive, got {bid}/{ask}")
        if ask < bid:
            raise InvalidPriceError(f"{key}: ask {ask} below bid {bid}")
        observed = self._to_utc(getattr(tick, "time", None), "tick time")
        spread_pips = (Decimal(str(ask)) - Decimal(str(bid))) / instrument.pip_size
        return MarketPrice(key, bid, PROVIDER_NAME, self._clock(), observed,
                           {"bid": bid, "ask": ask, "spread_pips": float(spread_pips),
                            "server_utc_offset_hours": self._offset_hours})

    def get_candles(self, symbol: str, timeframe: str = "5m", limit: int = 100) -> Sequence[MarketCandle]:
        """Closed bars only, oldest first, open/close times in UTC (close = open + interval - 1 ms, as before)."""
        mt5, key, _ = self._require(symbol)
        if timeframe not in TIMEFRAMES:
            raise InvalidTimeframeError(f"{timeframe!r} is not one of {tuple(TIMEFRAMES)}")
        if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= MAXIMUM_CANDLE_LIMIT:
            raise InvalidCandleLimitError(f"limit must be an integer from 1 to {MAXIMUM_CANDLE_LIMIT}")
        constant, seconds = TIMEFRAMES[timeframe]
        rates = mt5.copy_rates_from_pos(key, getattr(mt5, constant), 1, limit)   # position 0 is still forming
        if rates is None:
            raise MarketDataRequestError(f"{key} {timeframe}: copy_rates_from_pos failed: {mt5.last_error()}")
        now = self._clock()
        interval = timedelta(seconds=seconds)
        candles: list[MarketCandle] = []
        for row in rates:
            open_time = self._to_utc(row["time"], "bar time")
            close_time = open_time + interval - timedelta(milliseconds=1)
            if close_time >= now:
                continue        # never hand on a bar that has not closed
            prices = {field: _number(row[field], f"{key} {timeframe} {field}", InvalidCandleError)
                      for field in ("open", "high", "low", "close")}
            if min(prices.values()) <= 0:
                raise InvalidCandleError(f"{key} {timeframe}: prices must be positive at {open_time}")
            if prices["high"] < max(prices["open"], prices["close"]) or \
                    prices["low"] > min(prices["open"], prices["close"]):
                raise InvalidCandleError(f"{key} {timeframe}: high/low do not contain open/close at {open_time}")
            tick_volume = _number(row["tick_volume"], f"{key} {timeframe} tick_volume", InvalidCandleError)
            if tick_volume < 0:
                raise InvalidCandleError(f"{key} {timeframe}: tick volume must be a non-negative number")
            if candles and open_time <= candles[-1].open_time:
                raise MarketDataResponseError(f"{key} {timeframe}: bars are not strictly increasing in time")
            candles.append(MarketCandle(key, timeframe, open_time, close_time, prices["open"], prices["high"],
                                        prices["low"], prices["close"], tick_volume, PROVIDER_NAME, True,
                                        {"volume_kind": "TICK", "tick_volume": tick_volume,
                                         "spread_points": _number(row["spread"], f"{key} spread",
                                                                  InvalidCandleError),
                                         "server_utc_offset_hours": self._offset_hours}))
        return candles


QUOTE_MAX_AGE_SECONDS = 60      # a fill quote older than this is not a price (Task 021)


class Mt5QuoteFillProvider:
    """PAPER fill price from the MT5 top of book: a BUY fills at the ask, a SELL at the bid (Task 021, v5.104).

    The ``paper_fill_provider`` contract of ``ExecutionManager`` (the BOOK fill model): a callable
    ``(symbol, side, quote_notional) -> Decimal | None`` that never raises; None rejects the order. The spread is
    paid on every fill this way. MT5 exposes no depth here, so the notional is not walked through a book: the
    top-of-book quote is used for any size (major-pair sizes at this capital are far below top-of-book liquidity -
    an assumption, not a measurement). A quote older than QUOTE_MAX_AGE_SECONDS, or one that cannot be read, is no
    price.
    """

    def __init__(self, provider: Mt5MarketDataProvider, *, clock: Callable[[], datetime] | None = None,
                 max_age_seconds: float = QUOTE_MAX_AGE_SECONDS) -> None:
        self._provider = provider
        self._clock = clock or (lambda: datetime.now(UTC))
        self._max_age = timedelta(seconds=float(max_age_seconds))

    def __call__(self, symbol: str, side: str, notional: Decimal) -> Decimal | None:
        try:
            side = str(side).upper()
            if side not in ("BUY", "SELL"):
                return None
            quote = self._provider.get_price(symbol)
            observed = quote.source_timestamp
            if observed is None or not (timedelta(0) - timedelta(seconds=MAX_CLOCK_LEAD_SECONDS)
                                        <= self._clock() - observed <= self._max_age):
                return None
            value = quote.metadata["ask"] if side == "BUY" else quote.price
            price = Decimal(str(value))
            return price if price.is_finite() and price > 0 else None
        except Exception:   # fail closed: any failure is "no price", and the order is rejected
            return None


__all__ = ["MAXIMUM_CANDLE_LIMIT", "PROVIDER_NAME", "QUOTE_MAX_AGE_SECONDS", "TIMEFRAMES", "Mt5MarketDataProvider",
           "Mt5QuoteFillProvider"]
