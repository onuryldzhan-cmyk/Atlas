"""Task 5 finding: NaN / infinite OHLCV values must be rejected (NaN compares False and slipped through)."""

import pytest

from core.candle_processor import CandleProcessor


GOOD = {"open": 10, "high": 11, "low": 9, "close": 10.5, "volume": 5}


@pytest.mark.parametrize("field", ["open", "high", "low", "close", "volume"])
@pytest.mark.parametrize("bad", [float("nan"), float("inf"), float("-inf")])
def test_non_finite_values_are_invalid(field, bad):
    proc = CandleProcessor()
    candle = {**GOOD, field: bad}
    assert proc._is_valid(candle) is False


def test_good_candle_still_valid():
    assert CandleProcessor()._is_valid(dict(GOOD)) is True
