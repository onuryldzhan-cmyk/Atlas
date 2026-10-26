"""Forex domain foundations (Task 018, registry v5.102).

Atlas moves from crypto to forex (owner decision 2026-10-25). This package holds the forex-specific facts the rest of
the system needs: instrument units (pip, lot, contract size) and the weekly trading session. It reads no data and
places no orders.
"""

from atlas_finance.forex.instruments import (
    ACCOUNT_CURRENCY,
    FOREX_UNIVERSE,
    ForexInstrument,
    ForexInstrumentError,
)
from atlas_finance.forex.sessions import (
    is_forex_market_open,
    is_forex_pre_close,
    new_york_utc_offset_hours,
    next_forex_open,
)

__all__ = [
    "ACCOUNT_CURRENCY",
    "FOREX_UNIVERSE",
    "ForexInstrument",
    "ForexInstrumentError",
    "is_forex_market_open",
    "is_forex_pre_close",
    "new_york_utc_offset_hours",
    "next_forex_open",
]
