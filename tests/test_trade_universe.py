"""Trade universe = symbols with a real venue rule (registry v5.41, owner: 20 coins, real data only)."""

from __future__ import annotations

import json

import pytest

import main
from core.application import DEFAULT_INSTRUMENT_RULES_PATH
from tools import refresh_venue_instrument_rules as refresh


def test_universe_is_exactly_the_symbols_with_real_rules():
    shipped = json.loads(open(DEFAULT_INSTRUMENT_RULES_PATH, encoding="utf-8").read())
    assert main.trade_universe() == sorted(rule["symbol"] for rule in shipped["rules"])


def test_unreadable_rules_keep_the_fail_closed_default(tmp_path):
    assert main.trade_universe(tmp_path / "missing.json") is None


def test_more_than_twenty_symbols_is_refused(tmp_path):
    shipped = json.loads(open(DEFAULT_INSTRUMENT_RULES_PATH, encoding="utf-8").read())
    template = shipped["rules"][0]
    shipped["rules"] = [{**template, "symbol": f"C{i:02d}USDT", "base_asset": f"C{i:02d}"} for i in range(21)]
    path = tmp_path / "rules.json"
    path.write_text(json.dumps(shipped), encoding="utf-8")
    try:
        main.trade_universe(path)
    except ValueError as exc:
        assert "at most 20" in str(exc)
    else:  # the loader itself may refuse the synthetic rules (digest/provenance) - also fail-closed
        pytest.fail("21 symbols were accepted")


def test_owner_preset_has_twenty_distinct_usdt_pairs_including_the_current_five():
    preset = refresh.SYMBOL_PRESETS["owner-20"]
    assert len(set(preset)) == 20 and all(s.endswith("USDT") for s in preset)
    assert {"BTCUSDT", "ETHUSDT", "BNBUSDT", "SOLUSDT", "XRPUSDT"} <= set(preset)


def test_preset_is_passed_to_the_real_fetch(monkeypatch):
    seen = {}

    def fake_refresh(**kwargs):
        seen.update(kwargs)
        raise refresh.VenueMetadataError("stop here: no network in tests")

    monkeypatch.setattr(refresh, "refresh_venue_instrument_rules", fake_refresh)
    assert refresh.main(["--preset", "owner-20"]) == 1
    assert sorted(seen["symbols"]) == sorted(refresh.SYMBOL_PRESETS["owner-20"])
