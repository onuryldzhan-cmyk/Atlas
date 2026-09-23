"""BACKLOG-001 / registry v4.66: Fear & Greed provider is fail-closed.

Every test drives the real ``FearGreedProvider`` through an injected
transport - no test here touches the network. The single property that
matters most is that no failure path ever yields a value: a reading is either
``available=True`` with a validated, fresh value, or ``available=False`` with
``value=None`` and a reason code.
"""

from __future__ import annotations

import ast
import inspect
import json
import urllib.error
import urllib.request

from datetime import UTC, datetime, timedelta
from enum import IntEnum
from pathlib import Path

import pytest

from atlas_finance.market_data import fear_greed_provider as fg
from atlas_finance.market_data.fear_greed_provider import (
    FearGreedProvider,
    FearGreedReading,
    classify_fear_greed_band,
    parse_fear_greed_response,
)

# Bound at import time, before the repository-root conftest's autouse guard
# replaces the module attribute for each test, so the real transport's own
# error mapping can still be exercised (against a patched urlopen).
REAL_URLLIB_TRANSPORT = fg._urllib_transport

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]

# The exact body api.alternative.me returned when fetched live on
# 2026-09-23 (registry v4.66 session), whitespace included.
LIVE_BODY_2026_09_23 = (
    b'{\n\t"name": "Fear and Greed Index",\n\t"data": [\n\t\t{\n'
    b'\t\t\t"value": "71",\n\t\t\t"value_classification": "Greed",\n'
    b'\t\t\t"timestamp": "1790121600",\n\t\t\t"time_until_update": "26315"\n'
    b'\t\t}\n\t],\n\t"metadata": {\n\t\t"error": null\n\t}\n}'
)
LIVE_OBSERVED_AT = datetime(2026, 9, 23, tzinfo=UTC)
LIVE_FETCHED_AT = datetime(2026, 9, 23, 16, 41, 25, tzinfo=UTC)


def body(value="71", timestamp="1790121600", **extra) -> bytes:
    entry = {"value": value, "value_classification": "Greed", "timestamp": timestamp}
    entry.update(extra)
    return json.dumps({"name": "Fear and Greed Index", "data": [entry],
                       "metadata": {"error": None}}).encode()


class Clock:
    def __init__(self, now: datetime) -> None:
        self.now = now

    def __call__(self) -> datetime:
        return self.now

    def advance(self, **delta) -> None:
        self.now = self.now + timedelta(**delta)


class Transport:
    """Scripted transport: each call pops the next outcome."""

    def __init__(self, *outcomes) -> None:
        self.outcomes = list(outcomes)
        self.calls: list[tuple[str, float]] = []

    def __call__(self, url: str, timeout: float) -> bytes:
        self.calls.append((url, timeout))
        outcome = self.outcomes.pop(0) if len(self.outcomes) > 1 else self.outcomes[0]
        if isinstance(outcome, BaseException):
            raise outcome
        return outcome


def provider(transport, now=LIVE_FETCHED_AT, **kwargs):
    clock = Clock(now)
    return FearGreedProvider(transport=transport, clock=clock, **kwargs), clock


def assert_unavailable(reading: FearGreedReading, reason: str) -> None:
    assert reading.available is False
    assert reading.value is None
    assert reading.observed_at is None
    assert reading.reason == reason


# ---------------------------------------------------------------------------
# Parsing the real response shape
# ---------------------------------------------------------------------------


def test_live_response_shape_parses_to_its_exact_value_and_day():
    assert parse_fear_greed_response(LIVE_BODY_2026_09_23) == (71, LIVE_OBSERVED_AT)


def test_live_response_through_provider_is_available():
    transport = Transport(LIVE_BODY_2026_09_23)
    fear_greed, _ = provider(transport)

    reading = fear_greed.get_reading()

    assert reading == FearGreedReading(
        available=True, value=71, observed_at=LIVE_OBSERVED_AT,
        fetched_at=LIVE_FETCHED_AT, reason=fg.REASON_OK,
    )
    assert transport.calls == [(fg.FEAR_GREED_ENDPOINT, fg.DEFAULT_TIMEOUT_SECONDS)]


def test_json_integer_fields_are_accepted():
    assert parse_fear_greed_response(body(value=18, timestamp=1790121600)) == (18, LIVE_OBSERVED_AT)


def test_value_classification_is_not_required_or_trusted():
    # The band is derived from the number, never from the provider's label.
    document = {"data": [{"value": "10", "timestamp": "1790121600"}]}
    assert parse_fear_greed_response(json.dumps(document).encode()) == (10, LIVE_OBSERVED_AT)


# ---------------------------------------------------------------------------
# Every fail-closed path
# ---------------------------------------------------------------------------


MALFORMED_BODIES = [
    (b"not json", fg.REASON_MALFORMED_RESPONSE),
    (b"\xff\xfe\x00", fg.REASON_MALFORMED_RESPONSE),
    (b"[]", fg.REASON_MALFORMED_RESPONSE),
    (b'"71"', fg.REASON_MALFORMED_RESPONSE),
    (json.dumps({"data": [], "metadata": {"error": None}}).encode(), fg.REASON_MALFORMED_RESPONSE),
    (json.dumps({"data": {"value": "71"}}).encode(), fg.REASON_MALFORMED_RESPONSE),
    (json.dumps({"data": ["71"]}).encode(), fg.REASON_MALFORMED_RESPONSE),
    (json.dumps({"metadata": {"error": None}}).encode(), fg.REASON_MISSING_FIELD),
    (json.dumps({"data": [{"timestamp": "1790121600"}]}).encode(), fg.REASON_MISSING_FIELD),
    (json.dumps({"data": [{"value": "71"}]}).encode(), fg.REASON_MISSING_FIELD),
    (body(value=None), fg.REASON_MISSING_FIELD),
    (body(timestamp=None), fg.REASON_MISSING_FIELD),
    (json.dumps({"data": [{"value": "71", "timestamp": "1790121600"}],
                 "metadata": {"error": "rate limited"}}).encode(), fg.REASON_PROVIDER_REPORTED_ERROR),
    (json.dumps({"data": [{"value": "71", "timestamp": "1790121600"}],
                 "metadata": "oops"}).encode(), fg.REASON_MALFORMED_RESPONSE),
    (body(value="abc"), fg.REASON_MALFORMED_RESPONSE),
    (body(value="71.5"), fg.REASON_MALFORMED_RESPONSE),
    (body(value=71.0), fg.REASON_MALFORMED_RESPONSE),
    (body(value="-5"), fg.REASON_MALFORMED_RESPONSE),
    (body(value=-5), fg.REASON_MALFORMED_RESPONSE),
    (body(value=" 71"), fg.REASON_MALFORMED_RESPONSE),
    (body(value=""), fg.REASON_MALFORMED_RESPONSE),
    (body(value=True), fg.REASON_MALFORMED_RESPONSE),
    (body(value="101"), fg.REASON_VALUE_OUT_OF_RANGE),
    (body(value=1000), fg.REASON_VALUE_OUT_OF_RANGE),
    (body(timestamp="yesterday"), fg.REASON_MALFORMED_RESPONSE),
    (body(timestamp=1790121600.0), fg.REASON_MALFORMED_RESPONSE),
    (body(timestamp="999999999999"), fg.REASON_MALFORMED_RESPONSE),
]


@pytest.mark.parametrize(("raw", "reason"), MALFORMED_BODIES)
def test_malformed_responses_never_yield_a_value(raw, reason):
    with pytest.raises(fg.FearGreedResponseError) as caught:
        parse_fear_greed_response(raw)
    assert caught.value.reason == reason

    fear_greed, _ = provider(Transport(raw))
    assert_unavailable(fear_greed.get_reading(), reason)


@pytest.mark.parametrize("reason", [fg.REASON_NETWORK_ERROR, fg.REASON_TIMEOUT, fg.REASON_HTTP_ERROR])
def test_transport_failures_never_yield_a_value(reason):
    fear_greed, _ = provider(Transport(fg._TransportError(reason, "boom")))
    assert_unavailable(fear_greed.get_reading(), reason)


@pytest.mark.parametrize("error", [RuntimeError("boom"), KeyError("x"), ValueError("x"), OSError("x")])
def test_unexpected_transport_exceptions_are_contained(error):
    fear_greed, _ = provider(Transport(error))
    assert_unavailable(fear_greed.get_reading(), fg.REASON_UNEXPECTED_ERROR)


def test_non_bytes_transport_result_is_rejected():
    fear_greed, _ = provider(Transport("71"))
    assert_unavailable(fear_greed.get_reading(), fg.REASON_MALFORMED_RESPONSE)


def test_oversized_body_is_rejected_before_parsing():
    fear_greed, _ = provider(Transport(b" " * (fg.MAX_RESPONSE_BYTES + 1)))
    assert_unavailable(fear_greed.get_reading(), fg.REASON_RESPONSE_TOO_LARGE)


def test_a_broken_clock_is_contained():
    def clock():
        raise RuntimeError("clock failure")

    fear_greed = FearGreedProvider(transport=Transport(LIVE_BODY_2026_09_23), clock=clock)
    assert_unavailable(fear_greed.get_reading(), fg.REASON_UNEXPECTED_ERROR)


def test_a_naive_clock_is_contained_rather_than_compared():
    fear_greed = FearGreedProvider(
        transport=Transport(LIVE_BODY_2026_09_23),
        clock=lambda: datetime(2026, 9, 23, 12, 0),
    )
    assert_unavailable(fear_greed.get_reading(), fg.REASON_UNEXPECTED_ERROR)


# ---------------------------------------------------------------------------
# Freshness
# ---------------------------------------------------------------------------


def test_value_just_inside_the_26h_ceiling_is_available():
    fear_greed, _ = provider(Transport(LIVE_BODY_2026_09_23),
                             now=LIVE_OBSERVED_AT + timedelta(hours=26))
    assert fear_greed.get_reading().value == 71


def test_value_older_than_26h_is_stale_not_presented_as_fresh():
    fear_greed, _ = provider(Transport(LIVE_BODY_2026_09_23),
                             now=LIVE_OBSERVED_AT + timedelta(hours=26, seconds=1))
    reading = fear_greed.get_reading()
    assert_unavailable(reading, fg.REASON_STALE)
    assert reading.fetched_at == LIVE_OBSERVED_AT + timedelta(hours=26, seconds=1)


def test_cached_value_goes_stale_without_a_refetch():
    transport = Transport(LIVE_BODY_2026_09_23)
    fear_greed, clock = provider(transport, now=LIVE_OBSERVED_AT + timedelta(hours=25, minutes=30))
    assert fear_greed.get_reading().value == 71

    clock.advance(minutes=45)  # inside the 1h refresh interval, now 26h15m old

    assert_unavailable(fear_greed.get_reading(), fg.REASON_STALE)
    assert len(transport.calls) == 1


def test_future_timestamp_beyond_skew_is_rejected():
    fear_greed, _ = provider(Transport(LIVE_BODY_2026_09_23),
                             now=LIVE_OBSERVED_AT - timedelta(minutes=6))
    assert_unavailable(fear_greed.get_reading(), fg.REASON_FUTURE_TIMESTAMP)


def test_future_timestamp_within_skew_is_tolerated():
    fear_greed, _ = provider(Transport(LIVE_BODY_2026_09_23),
                             now=LIVE_OBSERVED_AT - timedelta(minutes=4))
    assert fear_greed.get_reading().value == 71


# ---------------------------------------------------------------------------
# Cache
# ---------------------------------------------------------------------------


def test_construction_performs_no_io():
    transport = Transport(LIVE_BODY_2026_09_23)
    FearGreedProvider(transport=transport)
    assert transport.calls == []


def test_network_is_contacted_once_per_refresh_interval():
    transport = Transport(LIVE_BODY_2026_09_23)
    fear_greed, clock = provider(transport)

    for _ in range(360):  # one hour of 10s cycles
        assert fear_greed.get_reading().value == 71
        clock.advance(seconds=10)
    assert len(transport.calls) == 1

    fear_greed.get_reading()
    assert len(transport.calls) == 2


def test_failure_is_retried_only_after_the_retry_interval():
    transport = Transport(fg._TransportError(fg.REASON_TIMEOUT, "slow"), LIVE_BODY_2026_09_23)
    fear_greed, clock = provider(transport)

    assert_unavailable(fear_greed.get_reading(), fg.REASON_TIMEOUT)
    clock.advance(minutes=4, seconds=59)
    assert_unavailable(fear_greed.get_reading(), fg.REASON_TIMEOUT)
    assert len(transport.calls) == 1

    clock.advance(seconds=1)
    assert fear_greed.get_reading().value == 71
    assert len(transport.calls) == 2


def test_failed_refresh_never_falls_back_to_the_previous_value():
    transport = Transport(LIVE_BODY_2026_09_23, fg._TransportError(fg.REASON_NETWORK_ERROR, "down"))
    fear_greed, clock = provider(transport)
    assert fear_greed.get_reading().value == 71

    clock.advance(hours=1)

    assert_unavailable(fear_greed.get_reading(), fg.REASON_NETWORK_ERROR)


def test_clock_moving_backwards_forces_a_refetch():
    transport = Transport(LIVE_BODY_2026_09_23)
    fear_greed, clock = provider(transport)
    fear_greed.get_reading()

    clock.advance(minutes=-1)
    fear_greed.get_reading()

    assert len(transport.calls) == 2


# ---------------------------------------------------------------------------
# Band classification
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(("value", "band"), [
    (0, "FEAR"), (24, "FEAR"),
    (25, "NEUTRAL"), (50, "NEUTRAL"), (74, "NEUTRAL"),
    (75, "GREED"), (100, "GREED"),
])
def test_band_boundaries(value, band):
    assert classify_fear_greed_band(value) == band


class _IntFlavour(IntEnum):
    TEN = 10


@pytest.mark.parametrize("value", [-1, 101, True, False, 24.0, "24", None, 24.5, _IntFlavour.TEN])
def test_band_classifier_rejects_anything_the_parser_would_not_accept(value):
    with pytest.raises(ValueError):
        classify_fear_greed_band(value)


def test_thresholds_are_the_owner_confirmed_values():
    assert (fg.FEAR_THRESHOLD, fg.GREED_THRESHOLD) == (25, 75)


# ---------------------------------------------------------------------------
# Real urllib transport error mapping (urlopen patched, no network)
# ---------------------------------------------------------------------------


class FakeResponse:
    def __init__(self, status=200, payload=LIVE_BODY_2026_09_23):
        self.status = status
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def read(self, limit=-1):
        return self.payload if limit < 0 else self.payload[:limit]


def test_the_imported_transport_is_the_real_one():
    assert REAL_URLLIB_TRANSPORT.__name__ == "_urllib_transport"
    assert REAL_URLLIB_TRANSPORT.__module__ == fg.__name__


def test_real_transport_sends_no_credentials(monkeypatch):
    seen = {}

    def urlopen(request, timeout):
        seen["request"], seen["timeout"] = request, timeout
        return FakeResponse()

    monkeypatch.setattr(urllib.request, "urlopen", urlopen)

    assert REAL_URLLIB_TRANSPORT(fg.FEAR_GREED_ENDPOINT, 5.0) == LIVE_BODY_2026_09_23
    request = seen["request"]
    assert request.get_method() == "GET"
    assert request.full_url == "https://api.alternative.me/fng/?limit=1&format=json"
    assert {name.lower() for name in request.headers} == {"accept", "user-agent"}
    assert seen["timeout"] == 5.0


@pytest.mark.parametrize(("error", "reason"), [
    (urllib.error.HTTPError("u", 503, "down", {}, None), fg.REASON_HTTP_ERROR),
    (urllib.error.URLError(TimeoutError()), fg.REASON_TIMEOUT),
    (urllib.error.URLError(ConnectionRefusedError()), fg.REASON_NETWORK_ERROR),
    (TimeoutError(), fg.REASON_TIMEOUT),
    (ConnectionResetError(), fg.REASON_NETWORK_ERROR),
])
def test_real_transport_maps_errors_to_reason_codes(monkeypatch, error, reason):
    def urlopen(request, timeout):
        raise error

    monkeypatch.setattr(urllib.request, "urlopen", urlopen)

    with pytest.raises(fg._TransportError) as caught:
        REAL_URLLIB_TRANSPORT(fg.FEAR_GREED_ENDPOINT, 5.0)
    assert caught.value.reason == reason


def test_real_transport_rejects_non_200_and_oversized(monkeypatch):
    monkeypatch.setattr(urllib.request, "urlopen", lambda r, timeout: FakeResponse(status=204))
    with pytest.raises(fg._TransportError) as caught:
        REAL_URLLIB_TRANSPORT(fg.FEAR_GREED_ENDPOINT, 5.0)
    assert caught.value.reason == fg.REASON_HTTP_ERROR

    big = b"x" * (fg.MAX_RESPONSE_BYTES + 10)
    monkeypatch.setattr(urllib.request, "urlopen", lambda r, timeout: FakeResponse(payload=big))
    with pytest.raises(fg._TransportError) as caught:
        REAL_URLLIB_TRANSPORT(fg.FEAR_GREED_ENDPOINT, 5.0)
    assert caught.value.reason == fg.REASON_RESPONSE_TOO_LARGE


# ---------------------------------------------------------------------------
# Test-suite network guard (repository-root conftest.py)
# ---------------------------------------------------------------------------


def test_default_transport_is_blocked_under_pytest(monkeypatch):
    def urlopen(*args, **kwargs):
        raise AssertionError("the test suite must never reach the network")

    monkeypatch.setattr(urllib.request, "urlopen", urlopen)

    reading = FearGreedProvider().get_reading()

    assert_unavailable(reading, fg.REASON_NETWORK_ERROR)


# ---------------------------------------------------------------------------
# Static guarantees
# ---------------------------------------------------------------------------


def test_provider_uses_only_the_standard_library():
    tree = ast.parse(inspect.getsource(fg))
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            imported.add((node.module or "").split(".")[0])
    assert imported <= {"__future__", "json", "logging", "re", "threading", "urllib",
                        "collections", "dataclasses", "datetime", "typing"}


def test_provider_source_carries_no_credential_handling():
    source = inspect.getsource(fg).lower()
    for marker in ("authorization", "api_key", "apikey", "x-api", "bearer", "os.environ", "getenv"):
        assert marker not in source
    assert fg.FEAR_GREED_ENDPOINT.startswith("https://api.alternative.me/")
