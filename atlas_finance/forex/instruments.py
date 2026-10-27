"""Forex instrument model: pip, lot and contract size, built from a MetaTrader 5 ``symbol_info`` record.

Units. Atlas keeps quantities in units of the base currency (1 standard lot of EURUSD = trade_contract_size = 100,000
EUR), so quantity x price is the notional in the quote currency, exactly as the crypto runtime used base asset x
quote price. The first forex universe is therefore USD-quoted pairs only: their notional is already in the account
currency (USD) and the existing risk and capital arithmetic stays valid. Pairs quoted in another currency (USDJPY,
EURGBP) need a conversion rate and are refused until that is built (deferred, registry v5.102).

Leverage is not modelled here: the runtime pays the full notional from capital (1:1), the most conservative setting.
Any leverage is an owner decision.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from decimal import ROUND_DOWN, Decimal, InvalidOperation
from typing import Any

ACCOUNT_CURRENCY = "USD"
# Task 025 (registry v5.108, policy manifest v4), owner 2026-10-26: account leverage 1:2 ('1:2 (Önerilen)') and a
# stop-out at a 100 % margin level ('%100 (Önerilen)'). PAPER only.
FOREX_LEVERAGE = 2
STOP_OUT_MARGIN_LEVEL = Decimal("1")
# USD-quoted majors: notional in the account currency, deep liquidity, tight spreads
FOREX_UNIVERSE = ("EURUSD", "GBPUSD", "AUDUSD", "NZDUSD")

_PAIR = re.compile(r"^[A-Z]{6}$")
MT5_MIN_NOTIONAL = "0.01"   # not an MT5 concept: one cent, so min_quantity binds (Task 019)
# fiat currencies only: metals (XAU, XAG), indices and crypto CFDs are not forex pairs
FIAT_CURRENCIES = frozenset({"USD", "EUR", "GBP", "JPY", "CHF", "CAD", "AUD", "NZD", "SEK", "NOK", "DKK", "SGD",
                             "HKD", "TRY", "PLN", "MXN", "ZAR", "CNH", "CZK", "HUF"})


class ForexInstrumentError(ValueError):
    """A symbol record is malformed or describes an instrument Atlas does not support."""


def _decimal(value: Any, name: str) -> Decimal:
    if isinstance(value, bool):
        raise ForexInstrumentError(f"{name} must be a number, not a bool")
    try:
        number = Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError) as exc:
        raise ForexInstrumentError(f"{name} is not a number: {value!r}") from exc
    if not number.is_finite() or number <= 0:
        raise ForexInstrumentError(f"{name} must be finite and positive: {value!r}")
    return number


@dataclass(frozen=True)
class ForexInstrument:
    symbol: str
    base: str
    quote: str
    digits: int
    point: Decimal
    contract_size: Decimal      # base-currency units in one lot
    volume_min: Decimal         # lots
    volume_step: Decimal        # lots
    volume_max: Decimal         # lots

    @property
    def pip_size(self) -> Decimal:
        """One pip: 0.0001 for 5-digit quotes (EURUSD 1.08345), 0.01 for 3-digit (USDJPY 151.234)."""
        return self.point * 10 if self.digits in (3, 5) else self.point

    def units(self, lots: Decimal) -> Decimal:
        return Decimal(lots) * self.contract_size

    def lots_for_units(self, units: Decimal) -> Decimal:
        """The largest tradable lot size not above ``units`` (rounded down to the volume step); 0 below the minimum."""
        lots = (Decimal(units) / self.contract_size / self.volume_step).to_integral_value(ROUND_DOWN) * self.volume_step
        if lots < self.volume_min:
            return Decimal("0")
        return min(lots, self.volume_max)

    def pip_value(self, units: Decimal) -> Decimal:
        """Value of one pip for ``units`` of base currency, in the quote currency (= account currency here)."""
        return Decimal(units) * self.pip_size

    def instrument_rule_fields(self) -> dict[str, str]:
        """The venue-neutral ``InstrumentRules`` fields for this pair, in base-currency units (Task 019).

        quantity_step and min_quantity are the MT5 volume step and minimum in lots times the contract size; price_tick
        is the point. MT5 has no minimum notional: the field is set to one cent of the quote currency, so the
        minimum quantity is the bound that binds. Venue maxima are not returned (withheld, as for every venue).
        """
        return {
            "venue": "MT5",
            "symbol": self.symbol,
            "base_asset": self.base,
            "quote_asset": self.quote,
            "quantity_step": format(self.volume_step * self.contract_size, "f"),
            "min_quantity": format(self.volume_min * self.contract_size, "f"),
            "min_notional": MT5_MIN_NOTIONAL,
            "price_tick": format(self.point, "f"),
        }

    @classmethod
    def from_symbol_info(cls, info: Any) -> ForexInstrument:
        """Build from an MT5 ``symbol_info`` record (attribute access). Refuses anything outside the supported set."""
        name = str(getattr(info, "name", ""))
        if not _PAIR.match(name):
            raise ForexInstrumentError(f"{name!r} is not a six-letter currency pair")
        base, quote = str(getattr(info, "currency_base", "")), str(getattr(info, "currency_profit", ""))
        if base + quote != name:
            raise ForexInstrumentError(f"{name}: base {base!r} and profit currency {quote!r} do not form the symbol")
        if base not in FIAT_CURRENCIES or quote not in FIAT_CURRENCIES or base == quote:
            raise ForexInstrumentError(f"{name}: not a pair of two different fiat currencies")
        if quote != ACCOUNT_CURRENCY:
            raise ForexInstrumentError(f"{name}: quote currency {quote} is not the account currency "
                                       f"{ACCOUNT_CURRENCY} (conversion not built yet)")
        digits = getattr(info, "digits", None)
        if not isinstance(digits, int) or isinstance(digits, bool) or not 0 <= digits <= 8:
            raise ForexInstrumentError(f"{name}: digits must be an integer 0..8, got {digits!r}")
        point = _decimal(getattr(info, "point", None), "point")
        if point != Decimal(1).scaleb(-digits):
            raise ForexInstrumentError(f"{name}: point {point} does not match {digits} digits")
        volume_min = _decimal(getattr(info, "volume_min", None), "volume_min")
        volume_step = _decimal(getattr(info, "volume_step", None), "volume_step")
        volume_max = _decimal(getattr(info, "volume_max", None), "volume_max")
        if volume_min < volume_step or volume_max < volume_min:
            raise ForexInstrumentError(f"{name}: inconsistent volume limits {volume_min}/{volume_step}/{volume_max}")
        return cls(name, base, quote, digits, point, _decimal(getattr(info, "trade_contract_size", None),
                                                               "trade_contract_size"),
                   volume_min, volume_step, volume_max)
