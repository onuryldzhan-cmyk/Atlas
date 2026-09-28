"""tools/measure_volatility_ceiling.py: offline, deterministic checks."""

from __future__ import annotations

import math
import random

from core.market_risk_regime import _rolling_realized_volatility
from tools import measure_volatility_ceiling as tool

NOW = 1_800_000_000_000
MINUTE = 60_000


def synthetic_fetcher(minutes: int, *, gap_at: int | None = None, seed: int = 7):
    rng = random.Random(seed)
    start = NOW - minutes * MINUTE
    price, rows = 100.0, []
    for i in range(minutes):
        vol = 0.0005 if (i // 300) % 2 else 0.002  # calm and busy regimes
        price *= math.exp(rng.gauss(0, vol))
        open_time = start + i * MINUTE + (MINUTE if gap_at is not None and i >= gap_at else 0)
        rows.append([open_time, "0", "0", "0", repr(price), "0", open_time + MINUTE - 1])

    def fetch(symbol, start_ms):
        return [r for r in rows if r[0] >= start_ms][:1000]

    return fetch


def test_closes_are_contiguous_and_exclude_the_forming_candle():
    closes = tool.fetch_closes("BTCUSDT", 2, synthetic_fetcher(2 * 1440), now_ms=NOW)
    assert len(closes) == 2 * 1440  # every candle closed before NOW

    # Moved one minute earlier, the last candle is still forming at NOW.
    early = tool.fetch_closes("BTCUSDT", 2, synthetic_fetcher(2 * 1440), now_ms=NOW - MINUTE)
    assert len(early) == 2 * 1440 - 1


def test_a_gap_restarts_the_series():
    closes = tool.fetch_closes("BTCUSDT", 2, synthetic_fetcher(2 * 1440, gap_at=2000), now_ms=NOW)
    assert len(closes) < 2 * 1440 - 1000


def test_measure_uses_the_live_estimator_and_orders_candidates():
    closes = tool.fetch_closes("BTCUSDT", 3, synthetic_fetcher(3 * 1440), now_ms=NOW)
    result = tool.measure("BTCUSDT", closes)

    assert result["available"] is True
    assert result["windows"] == len(_rolling_realized_volatility(closes))
    ceilings = [c["ceiling"] for c in result["candidates"]]
    assert ceilings == sorted(ceilings)
    for c in result["candidates"]:
        assert 0 <= c["a1_and_a2_share"] <= c["absolute_pass_share"] <= 1
    # The calm regime exists, so some minutes pass A1 and A2 together.
    assert result["candidates"][-1]["a1_and_a2_share"] > 0


def test_too_little_history_is_unavailable_not_invented():
    closes = tool.fetch_closes("BTCUSDT", 1, synthetic_fetcher(500), now_ms=NOW)
    assert tool.measure("BTCUSDT", closes)["available"] is False


def test_main_prints_and_reports_a_fetch_failure_per_symbol(capsys):
    def broken(symbol, start):
        raise OSError("offline")

    assert tool.main(["--days", "1", "--symbols", "BTCUSDT"], fetch=broken) == 0
    assert "unavailable - OSError: offline" in capsys.readouterr().out
