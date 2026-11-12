"""Universe selection (registry v5.51): 8 trend / 8 medium / 4 high from real-shaped Binance data."""

from __future__ import annotations

import json

from tools import refresh_venue_instrument_rules as refresh
from tools import select_universe as su


def _fake_binance():
    bases = [f"C{i:02d}" for i in range(40)] + ["USDC", "BTCUP", "FDUSD"]
    info = {"symbols": [{"symbol": f"{b}USDT", "baseAsset": b, "quoteAsset": "USDT", "status": "TRADING"} for b in bases]
            + [{"symbol": "OLDUSDT", "baseAsset": "OLD", "quoteAsset": "USDT", "status": "BREAK"}]}
    tickers = [{"symbol": f"{b}USDT", "quoteVolume": str(10_000_000_000 - i * 200_000_000), "priceChangePercent": "1"}
               for i, b in enumerate(bases)] + [{"symbol": "OLDUSDT", "quoteVolume": "9e12"},
                                                 {"symbol": "C39USDT", "quoteVolume": "1000"}]

    def get(path):
        if path.startswith("/api/v3/exchangeInfo"):
            return info
        if path.startswith("/api/v3/ticker/24hr"):
            return tickers
        idx = int(path.split("symbol=C")[1][:2])
        drift = (idx % 7 - 3) / 100          # -3 % .. +3 % per day
        wobble = 0.01 if idx % 2 else 0.12   # odd coins calm, even coins volatile
        closes, p = [], 100.0
        for d in range(8):
            p *= 1 + drift + (wobble if d % 2 else -wobble)
            closes.append(p)
        return [[0, 0, 0, 0, str(c)] for c in closes]
    return get


def test_selects_8_8_4_from_real_rules_and_excludes_bad_pairs(tmp_path, monkeypatch):
    monkeypatch.setattr(su, "held_symbols", lambda: set())
    out = tmp_path / "sel.json"
    assert su.main(["--output", str(out)], get=_fake_binance()) == 0
    record = json.loads(out.read_text())
    g = record["groups"]
    assert (len(g["TREND"]), len(g["MEDIUM"]), len(g["HIGH"])) == (8, 8, 4) and len(record["symbols"]) == 20
    assert not {"USDCUSDT", "BTCUPUSDT", "FDUSDUSDT", "OLDUSDT", "C39USDT"} & set(record["symbols"])
    assert all(c["return_7d"] > 0 for c in g["TREND"] + g["HIGH"])
    assert all(c["volatility_7d"] <= su.MEDIUM_MAX_VOL for c in g["MEDIUM"])


def test_held_coins_are_always_kept_and_total_stays_20(tmp_path, monkeypatch):
    monkeypatch.setattr(su, "held_symbols", lambda: {"C38USDT", "GONEUSDT"})
    out = tmp_path / "sel.json"
    assert su.main(["--output", str(out)], get=_fake_binance()) == 0
    record = json.loads(out.read_text())
    assert {"C38USDT", "GONEUSDT"} <= set(record["symbols"]) and len(record["symbols"]) == 20


def test_network_failure_writes_nothing(tmp_path):
    def broken(path):
        raise OSError("blocked")
    out = tmp_path / "sel.json"
    assert su.main(["--output", str(out)], get=broken) == 1 and not out.exists()


def test_refresh_reads_the_selection_file(tmp_path, monkeypatch):
    seen = {}

    def fake_refresh(**kwargs):
        seen.update(kwargs)
        raise refresh.VenueMetadataError("no network in tests")

    monkeypatch.setattr(refresh, "refresh_venue_instrument_rules", fake_refresh)
    path = tmp_path / "sel.json"
    path.write_text(json.dumps({"symbols": ["AUSDT", "BUSDT"]}))
    assert refresh.main(["--symbols-file", str(path)]) == 1 and seen["symbols"] == ["AUSDT", "BUSDT"]
    path.write_text("{}")
    assert refresh.main(["--symbols-file", str(path)]) == 1
