"""Registry v4.79: TreasuryYieldProvider (L2) fetch / parse / cache / fail-closed.

No test here touches the network: every provider gets an injected transport,
and the repository-root conftest guard makes the default transport fail.
"""

from __future__ import annotations

import ast
import inspect

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from enum import IntEnum

import pytest

import atlas_finance.market_data.treasury_yield_provider as module
from atlas_finance.market_data.treasury_yield_provider import (
    LOOKBACK_TRADING_DAYS,
    MOVE_FALLING,
    MOVE_FLAT,
    MOVE_RISING,
    REASON_FUTURE_TIMESTAMP,
    REASON_HTTP_ERROR,
    REASON_INSUFFICIENT_HISTORY,
    REASON_LOOKBACK_SPAN_EXCEEDED,
    REASON_MALFORMED_RESPONSE,
    REASON_MISSING_FIELD,
    REASON_NETWORK_ERROR,
    REASON_OK,
    REASON_RESPONSE_TOO_LARGE,
    REASON_STALE,
    REASON_TIMEOUT,
    REASON_UNEXPECTED_ERROR,
    REASON_VALUE_OUT_OF_RANGE,
    TreasuryYieldProvider,
    TreasuryYieldResponseError,
    _TransportError,
    classify_ten_year_move,
    parse_treasury_yield_csv,
)


# The live header, verified 2026-09-25.
HEADER = ('Date,"1 Mo","1.5 Month","2 Mo","3 Mo","4 Mo","6 Mo","1 Yr","2 Yr",'
          '"3 Yr","5 Yr","7 Yr","10 Yr","20 Yr","30 Yr"')

NOW = datetime(2026, 9, 25, 12, tzinfo=UTC)


def business_days(end: date, count: int) -> list[date]:
    days, current = [], end
    while len(days) < count:
        if current.weekday() < 5:
            days.append(current)
        current -= timedelta(days=1)
    return days


def row(day: date, two: str, ten: str) -> str:
    return (f"{day:%m/%d/%Y},4.01,4.10,4.18,4.24,4.33,4.34,4.51,{two},"
            f"4.99,5.03,5.10,{ten},5.53,5.47")


def csv_body(rows: list[str], *, header: str = HEADER, bom: bool = False) -> bytes:
    text = "\r\n".join([header, *rows]) + "\r\n"
    return (b"\xef\xbb\xbf" if bom else b"") + text.encode("utf-8")


def year_body(end: date, count: int, *, ten_latest="5.18", ten_back="4.66",
              two_latest="4.87") -> bytes:
    rows = []
    for index, day in enumerate(business_days(end, count)):
        if index == 0:
            rows.append(row(day, two_latest, ten_latest))
        elif index == LOOKBACK_TRADING_DAYS:
            rows.append(row(day, "4.70", ten_back))
        else:
            rows.append(row(day, "4.80", "5.00"))
    return csv_body(rows)


class Transport:
    """Serves bodies per requested year; records every URL."""

    def __init__(self, bodies) -> None:
        self.bodies = bodies
        self.urls = []

    def __call__(self, url, timeout):
        self.urls.append((url, timeout))
        year = int(url.split("daily-treasury-rates.csv/")[1].split("/")[0])
        result = self.bodies[year]
        if isinstance(result, BaseException):
            raise result
        return result


class Clock:
    def __init__(self, now: datetime) -> None:
        self.now = now

    def __call__(self) -> datetime:
        return self.now


def provider(bodies, now=NOW, **kwargs):
    transport = Transport(bodies)
    clock = Clock(now)
    return TreasuryYieldProvider(transport=transport, clock=clock, **kwargs), transport, clock


# ---------------------------------------------------------------------------
# Move classification
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(("change", "move"), [
    (25, MOVE_RISING), (52, MOVE_RISING), (24, MOVE_FLAT), (0, MOVE_FLAT),
    (-24, MOVE_FLAT), (-25, MOVE_FALLING), (-80, MOVE_FALLING),
])
def test_move_classification_boundaries(change, move):
    assert classify_ten_year_move(change) == move


class _Bp(IntEnum):
    BIG = 30


@pytest.mark.parametrize("bad", [True, False, 25.0, "25", None, _Bp.BIG, Decimal("25")])
def test_move_classification_accepts_only_plain_int(bad):
    with pytest.raises(ValueError):
        classify_ten_year_move(bad)


# ---------------------------------------------------------------------------
# Parser
# ---------------------------------------------------------------------------


def test_parser_reads_the_live_shape_newest_first():
    rows = parse_treasury_yield_csv(year_body(date(2026, 9, 24), 30), expected_year=2026)

    assert len(rows) == 30
    assert rows[0].observed_date == date(2026, 9, 24)
    assert rows[0].ten_year == Decimal("5.18")
    assert rows[0].two_year == Decimal("4.87")
    assert all(a.observed_date > b.observed_date for a, b in zip(rows, rows[1:]))


def test_parser_accepts_a_byte_order_mark():
    rows = parse_treasury_yield_csv(
        csv_body([row(date(2026, 9, 24), "4.87", "5.18")], bom=True), expected_year=2026)
    assert rows[0].ten_year == Decimal("5.18")


def test_header_only_year_is_valid_and_empty():
    assert parse_treasury_yield_csv(csv_body([]), expected_year=2027) == []


GOOD = row(date(2026, 9, 24), "4.87", "5.18")
OLDER = row(date(2026, 9, 23), "4.85", "5.11")


@pytest.mark.parametrize(("body", "reason"), [
    (b"", REASON_MALFORMED_RESPONSE),
    (b"\xff\xfe\x00", REASON_MALFORMED_RESPONSE),
    (b"<html>maintenance</html>", REASON_MALFORMED_RESPONSE),
    (csv_body([GOOD], header=HEADER.replace('"10 Yr",', "")), REASON_MISSING_FIELD),
    (csv_body([GOOD], header=HEADER.replace('"2 Yr"', '"2 Year"')), REASON_MISSING_FIELD),
    (csv_body([GOOD], header=HEADER + ',"10 Yr"'), REASON_MISSING_FIELD),
    (csv_body([GOOD], header=HEADER.replace("Date", "Day")), REASON_MALFORMED_RESPONSE),
    (csv_body([row(date(2026, 9, 24), "4.87", "")]), REASON_MISSING_FIELD),
    (csv_body([row(date(2026, 9, 24), "", "5.18")]), REASON_MISSING_FIELD),
    (csv_body([row(date(2026, 9, 24), "4.87", "N/A")]), REASON_MALFORMED_RESPONSE),
    (csv_body([row(date(2026, 9, 24), "4.87", "5.185")]), REASON_MALFORMED_RESPONSE),
    (csv_body([row(date(2026, 9, 24), "4.87", " 5.18")]), REASON_MALFORMED_RESPONSE),
    (csv_body([row(date(2026, 9, 24), "4.87", "5e0")]), REASON_MALFORMED_RESPONSE),
    (csv_body([row(date(2026, 9, 24), "4.87", "26.00")]), REASON_VALUE_OUT_OF_RANGE),
    (csv_body([row(date(2026, 9, 24), "-6.00", "5.18")]), REASON_VALUE_OUT_OF_RANGE),
    (csv_body([GOOD.replace("09/24/2026", "2026-09-24")]), REASON_MALFORMED_RESPONSE),
    (csv_body([GOOD.replace("09/24/2026", "02/30/2026")]), REASON_MALFORMED_RESPONSE),
    (csv_body([GOOD.replace("09/24/2026", "09/24/2025")]), REASON_MALFORMED_RESPONSE),
    (csv_body([OLDER, GOOD]), REASON_MALFORMED_RESPONSE),
    (csv_body([GOOD, GOOD]), REASON_MALFORMED_RESPONSE),
    (csv_body([GOOD + ",5.00"]), REASON_MALFORMED_RESPONSE),
    (csv_body([GOOD.rsplit(",", 1)[0]]), REASON_MALFORMED_RESPONSE),
    (csv_body(['09/24/2026,"4.01']), REASON_MALFORMED_RESPONSE),
])
def test_parser_refuses_every_deviation(body, reason):
    with pytest.raises(TreasuryYieldResponseError) as caught:
        parse_treasury_yield_csv(body, expected_year=2026)
    assert caught.value.reason == reason


def test_parser_refuses_too_many_rows():
    body = year_body(date(2026, 12, 31), module.MAX_ROWS + 1)
    with pytest.raises(TreasuryYieldResponseError) as caught:
        parse_treasury_yield_csv(body, expected_year=2026)
    assert caught.value.reason == REASON_MALFORMED_RESPONSE


# ---------------------------------------------------------------------------
# Provider: values, cache, retry, freshness
# ---------------------------------------------------------------------------


def test_available_reading_has_exact_basis_points():
    tsy, transport, _ = provider({2026: year_body(date(2026, 9, 24), 183)})
    reading = tsy.get_reading()

    assert reading.available is True
    assert reading.reason == REASON_OK
    assert reading.observed_date == date(2026, 9, 24)
    assert reading.lookback_date == business_days(date(2026, 9, 24), 21)[20]
    assert reading.ten_year_yield == Decimal("5.18")
    assert reading.two_year_yield == Decimal("4.87")
    assert reading.ten_year_change_bp == 52
    assert reading.curve_spread_bp == 31
    assert type(reading.ten_year_change_bp) is int and type(reading.curve_spread_bp) is int
    assert len(transport.urls) == 1
    url, timeout = transport.urls[0]
    assert url.startswith("https://home.treasury.gov/")
    assert "/2026/" in url and "field_tdr_date_value=2026" in url
    assert timeout == module.DEFAULT_TIMEOUT_SECONDS


def test_inverted_curve_gives_negative_spread():
    body = year_body(date(2026, 9, 24), 40, ten_latest="4.00", two_latest="4.50")
    reading = provider({2026: body})[0].get_reading()
    assert reading.curve_spread_bp == -50


def test_cache_contacts_the_network_once_per_refresh_interval():
    tsy, transport, clock = provider({2026: year_body(date(2026, 9, 24), 60)})

    for minutes in range(0, 6 * 60, 7):
        clock.now = NOW + timedelta(minutes=minutes)
        assert tsy.get_reading().available

    assert len(transport.urls) == 1

    clock.now = NOW + module.DEFAULT_REFRESH_INTERVAL
    assert tsy.get_reading().available
    assert len(transport.urls) == 2


def test_failure_is_cached_for_the_retry_interval_then_retried():
    tsy, transport, clock = provider({2026: _TransportError(REASON_TIMEOUT, "x")})

    assert tsy.get_reading().reason == REASON_TIMEOUT
    clock.now = NOW + module.DEFAULT_RETRY_INTERVAL - timedelta(seconds=1)
    assert tsy.get_reading().reason == REASON_TIMEOUT
    assert len(transport.urls) == 1

    transport.bodies[2026] = year_body(date(2026, 9, 24), 60)
    clock.now = NOW + module.DEFAULT_RETRY_INTERVAL
    assert tsy.get_reading().available
    assert len(transport.urls) == 2


def test_failed_refresh_never_falls_back_to_the_previous_value():
    tsy, transport, clock = provider({2026: year_body(date(2026, 9, 24), 60)})
    assert tsy.get_reading().available

    transport.bodies[2026] = _TransportError(REASON_HTTP_ERROR, "503")
    clock.now = NOW + module.DEFAULT_REFRESH_INTERVAL
    reading = tsy.get_reading()

    assert reading.available is False
    assert reading.reason == REASON_HTTP_ERROR
    assert reading.ten_year_change_bp is None and reading.curve_spread_bp is None


def test_cached_value_turns_stale_without_a_refetch():
    tsy, transport, clock = provider(
        {2026: year_body(date(2026, 9, 24), 60)},
        refresh_interval=timedelta(days=30),
    )
    assert tsy.get_reading().available

    # 7 days after the row's own 00:00 UTC date is still fresh; one second
    # more is stale - measured on the row's date, not on the fetch time.
    clock.now = datetime(2026, 10, 1, tzinfo=UTC)
    assert tsy.get_reading().available
    clock.now = datetime(2026, 10, 1, 0, 0, 1, tzinfo=UTC)
    reading = tsy.get_reading()
    assert reading.reason == REASON_STALE and reading.ten_year_change_bp is None
    assert len(transport.urls) == 1


def test_a_long_weekend_is_not_stale():
    # Thanksgiving: Wednesday's row is still the newest the next Tuesday.
    body = year_body(date(2026, 11, 25), 60)
    reading = provider({2026: body}, now=datetime(2026, 12, 1, 9, tzinfo=UTC))[0].get_reading()
    assert reading.available is True


def test_future_dated_row_is_refused():
    body = year_body(date(2026, 9, 28), 60)
    reading = provider({2026: body})[0].get_reading()
    assert reading.reason == REASON_FUTURE_TIMESTAMP and reading.available is False


def test_clock_moving_backwards_forces_a_refetch():
    tsy, transport, clock = provider({2026: year_body(date(2026, 9, 24), 60)})
    tsy.get_reading()
    clock.now = NOW - timedelta(minutes=1)
    tsy.get_reading()
    assert len(transport.urls) == 2


# ---------------------------------------------------------------------------
# Provider: lookback history and the year boundary
# ---------------------------------------------------------------------------


def test_exactly_lookback_plus_one_rows_is_enough():
    body = year_body(date(2026, 9, 24), LOOKBACK_TRADING_DAYS + 1)
    tsy, transport, _ = provider({2026: body})
    assert tsy.get_reading().available
    assert len(transport.urls) == 1


def test_early_january_supplements_from_the_previous_year():
    now = datetime(2027, 1, 8, 12, tzinfo=UTC)
    current = year_body(date(2027, 1, 7), 5, ten_latest="5.00")
    previous = year_body(date(2026, 12, 31), 250, ten_latest="4.90")
    tsy, transport, _ = provider({2027: current, 2026: previous}, now=now)

    reading = tsy.get_reading()

    assert reading.available is True
    assert reading.observed_date == date(2027, 1, 7)
    assert [("/2027/" in url, "/2026/" in url) for url, _ in transport.urls] == [
        (True, False), (False, True)]
    # 20 rows back: 5 rows of 2027, then index 15 of 2026, which is a
    # "5.00" filler row -> 5.00 - 5.00.
    assert reading.lookback_date.year == 2026
    assert reading.ten_year_change_bp == 0


def test_header_only_new_year_uses_the_previous_year():
    now = datetime(2027, 1, 1, 18, tzinfo=UTC)
    previous = year_body(date(2026, 12, 31), 250)
    reading = provider({2027: csv_body([]), 2026: previous}, now=now)[0].get_reading()
    assert reading.available is True and reading.observed_date == date(2026, 12, 31)


def test_previous_year_failure_is_unavailable_not_partial():
    now = datetime(2027, 1, 8, 12, tzinfo=UTC)
    current = year_body(date(2027, 1, 7), 5)
    reading = provider({2027: current, 2026: _TransportError(REASON_NETWORK_ERROR, "x")},
                       now=now)[0].get_reading()
    assert reading.available is False and reading.reason == REASON_NETWORK_ERROR


def test_a_short_file_mid_year_is_not_spliced_onto_the_previous_year():
    # Audit F-1: 5 well-formed September rows are a truncated response, not
    # a year boundary. Splicing 2025 would report a ~9-month move as a
    # 20-trading-day move.
    tsy, transport, _ = provider({2026: year_body(date(2026, 9, 24), 5),
                                  2025: year_body(date(2025, 12, 31), 250)})
    reading = tsy.get_reading()

    assert reading.available is False
    assert reading.reason == REASON_INSUFFICIENT_HISTORY
    assert len(transport.urls) == 1 and "/2026/" in transport.urls[0][0]


def test_missing_rows_inside_the_lookback_are_refused():
    # Audit F-1: a well-formed single-year file with a hole between rows.
    days = business_days(date(2026, 9, 24), 10) + business_days(date(2026, 2, 27), 30)
    rows = [row(day, "4.80", "5.00") for day in days]
    reading = provider({2026: csv_body(rows)})[0].get_reading()

    assert reading.available is False
    assert reading.reason == REASON_LOOKBACK_SPAN_EXCEEDED
    assert reading.ten_year_change_bp is None


def test_the_longest_normal_lookback_span_is_accepted():
    # Thanksgiving + Christmas inside one lookback: 20 rows back from
    # 2026-12-31 over business days minus both holidays is still <= 35 days.
    days = [d for d in business_days(date(2026, 12, 31), 30)
            if d not in (date(2026, 12, 25), date(2026, 11, 26))]
    result = provider({2026: csv_body([row(d, "4.80", "5.00") for d in days])},
                      now=datetime(2026, 12, 31, 23, tzinfo=UTC))[0].get_reading()
    assert result.available is True
    assert (result.observed_date - result.lookback_date).days <= 35


def test_too_few_rows_even_with_the_previous_year_is_insufficient_history():
    now = datetime(2027, 1, 8, 12, tzinfo=UTC)
    reading = provider({2027: year_body(date(2027, 1, 7), 5),
                        2026: year_body(date(2026, 12, 31), 10)}, now=now)[0].get_reading()
    assert reading.reason == REASON_INSUFFICIENT_HISTORY and reading.available is False


# ---------------------------------------------------------------------------
# Provider: never raises, never fabricates
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(("result", "reason"), [
    (_TransportError(REASON_NETWORK_ERROR, "x"), REASON_NETWORK_ERROR),
    (_TransportError(REASON_TIMEOUT, "x"), REASON_TIMEOUT),
    (_TransportError(REASON_HTTP_ERROR, "x"), REASON_HTTP_ERROR),
    (RuntimeError("boom"), REASON_UNEXPECTED_ERROR),
    (KeyError("x"), REASON_UNEXPECTED_ERROR),
    ("not bytes", REASON_MALFORMED_RESPONSE),
    (None, REASON_MALFORMED_RESPONSE),
    pytest.param(b"x" * (module.MAX_RESPONSE_BYTES + 1), REASON_RESPONSE_TOO_LARGE,
                 id="oversized-body"),
    (b"garbage", REASON_MALFORMED_RESPONSE),
])
def test_every_failure_is_unavailable_with_no_values(result, reason):
    reading = provider({2026: result})[0].get_reading()

    assert reading.available is False
    assert reading.reason == reason
    assert (reading.observed_date, reading.ten_year_yield, reading.two_year_yield,
            reading.ten_year_change_bp, reading.curve_spread_bp) == (None,) * 5


def test_a_raising_clock_never_escapes():
    def clock():
        raise RuntimeError("clock")

    tsy = TreasuryYieldProvider(transport=Transport({}), clock=clock)
    reading = tsy.get_reading()
    assert reading.available is False and reading.reason == REASON_UNEXPECTED_ERROR


def test_construction_performs_no_io():
    transport = Transport({})
    TreasuryYieldProvider(transport=transport)
    assert transport.urls == []


def test_default_transport_is_guarded_under_pytest():
    reading = TreasuryYieldProvider(clock=Clock(NOW)).get_reading()
    assert reading.available is False and reading.reason == REASON_NETWORK_ERROR


def test_provider_imports_only_the_standard_library():
    tree = ast.parse(inspect.getsource(module))
    modules = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            modules.add((node.module or "").split(".")[0])
    assert modules <= {"__future__", "csv", "io", "logging", "re", "threading", "urllib",
                       "collections", "dataclasses", "datetime", "decimal", "typing"}
