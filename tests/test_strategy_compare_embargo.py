"""Roadmap C-3: embargo between comparison windows; 0 keeps the historical split."""

import pytest

from tools import strategy_compare as sc
from tools.strategy_compare import split


def data(n=3000):
    return {"BTCUSDT": [[i] for i in range(n)], "ETHUSDT": [[i] for i in range(n)]}


def test_zero_embargo_is_the_historical_split():
    parts = split(data(), 3)
    assert [p["BTCUSDT"][0][0] for p in parts] == [0, 1000, 2000]
    assert sum(len(p["BTCUSDT"]) for p in parts) == 3000


def test_embargo_leaves_a_gap_and_never_overlaps():
    parts = split(data(), 3, embargo=100)
    starts = [p["BTCUSDT"][0][0] for p in parts]
    ends = [p["BTCUSDT"][-1][0] for p in parts]
    assert starts == [0, 1100, 2100]
    assert all(ends[i] < starts[i + 1] - 99 for i in range(2))


def test_embargo_that_leaves_too_little_data_is_refused():
    with pytest.raises(ValueError):
        split(data(), 3, embargo=1000 - sc.bt.WINDOW - 60)
    with pytest.raises(ValueError):
        split(data(), 3, embargo=-1)


def test_every_verdict_variant_uses_realistic_fills():
    for name, kw in sc.VARIANTS.items():
        if name != sc.REFERENCE and kw.get("slippage_bps"):
            assert kw.get("next_open_fill") is True, name
