"""Write config/instrument_rules_mt5.json from a MetaTrader 5 demo terminal (Task 019, registry v5.103).

Manual, operator-run tool for the forex market (ATLAS_MARKET=FOREX). It connects through
``Mt5MarketDataProvider`` - demo accounts only, no credentials, no order function - reads each pair's
``symbol_info`` and writes the venue-neutral instrument rules the runtime loads in forex mode:

    python -m tools.refresh_mt5_instrument_rules                      # default forex universe
    python -m tools.refresh_mt5_instrument_rules --symbols EURUSD GBPUSD
    python -m tools.refresh_mt5_instrument_rules --server-utc-offset 2  # when the market is closed

The file is written with the same validate / write-temp / fsync / reload / os.replace sequence and the same
withheld venue maxima as tools/refresh_venue_instrument_rules.py (whose helpers it reuses), then a diff is
printed. It never runs git: the operator reviews the change and commits it. Runs on Windows only, next to a
running MetaTrader 5 terminal logged in to a demo account.
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path

from atlas_finance.forex.instruments import FOREX_UNIVERSE, ForexInstrument
from atlas_finance.market_data.mt5_provider import Mt5MarketDataProvider
from core.application import FOREX_INSTRUMENT_RULES_PATH
from core.instrument_rules import INSTRUMENT_RULES_SCHEMA_VERSION, InstrumentRules, InstrumentRuleset
from tools.refresh_venue_instrument_rules import (
    _print_diff,
    _read_bytes_if_present,
    _write_withheld_document,
)

SOURCE = "MetaTrader5.symbol_info"


def build_ruleset(instruments: Mapping[str, ForexInstrument], *, retrieved_at: datetime) -> InstrumentRuleset:
    """Validated rules (no venue maxima) for the given instruments; every rule carries the same provenance."""
    stamp = retrieved_at.astimezone(UTC).isoformat().replace("+00:00", "Z")
    rules = {}
    for symbol, instrument in instruments.items():
        rules[symbol] = InstrumentRules(**instrument.instrument_rule_fields(), source=SOURCE,
                                        source_version=f"mt5-symbol_info-{stamp}", retrieved_at=stamp)
    return InstrumentRuleset(rules, schema_version=INSTRUMENT_RULES_SCHEMA_VERSION)


def document_for(ruleset: InstrumentRuleset, *, retrieved_at: datetime) -> dict:
    stamp = retrieved_at.astimezone(UTC).isoformat().replace("+00:00", "Z")
    return {
        "schema_version": ruleset.schema_version,
        "provenance": {
            "venue": "MT5",
            "source": SOURCE,
            "retrieved_at": stamp,
            "transport": "METATRADER5_TERMINAL_DEMO",
            "symbol_count": len(ruleset.symbols),
            "venue_upper_bounds_modelled": False,
            "min_notional_note": "MT5 has no minimum notional; 0.01 quote currency, so min_quantity binds",
        },
        "rules": [ruleset.rules[symbol].to_dict() for symbol in ruleset.symbols],
    }


def refresh_mt5_instrument_rules(*, symbols: Sequence[str] = FOREX_UNIVERSE,
                                 destination: Path = FOREX_INSTRUMENT_RULES_PATH,
                                 server_utc_offset_hours: int | None = None,
                                 provider: Mt5MarketDataProvider | None = None,
                                 now: datetime | None = None) -> InstrumentRuleset:
    provider = provider or Mt5MarketDataProvider(symbols=symbols, server_utc_offset_hours=server_utc_offset_hours)
    provider.connect()
    try:
        instruments = provider.instruments
    finally:
        provider.disconnect()
    retrieved_at = now or datetime.now(UTC)
    ruleset = build_ruleset(instruments, retrieved_at=retrieved_at)
    target = Path(destination)
    before = _read_bytes_if_present(target)
    _write_withheld_document(document_for(ruleset, retrieved_at=retrieved_at), target=target, expected=ruleset)
    _print_diff(before=before, after=_read_bytes_if_present(target), destination=target)
    return ruleset


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--symbols", nargs="+", default=list(FOREX_UNIVERSE))
    parser.add_argument("--destination", type=Path, default=FOREX_INSTRUMENT_RULES_PATH)
    parser.add_argument("--server-utc-offset", type=int, default=None,
                        help="broker server time offset in hours; needed when the market is closed")
    args = parser.parse_args(argv)
    try:
        ruleset = refresh_mt5_instrument_rules(symbols=args.symbols, destination=args.destination,
                                               server_utc_offset_hours=args.server_utc_offset)
    except Exception as exc:
        print(f"refused: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1
    print(f"wrote {len(ruleset.symbols)} MT5 instrument rules to {args.destination}; review and commit it")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
