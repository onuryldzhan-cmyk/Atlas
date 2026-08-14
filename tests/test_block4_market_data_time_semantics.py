"""Block 4 / Package 1: TimeSemantic vocabulary and DataTimestamp value object.

Covers TIME-1 (timestamps are timezone-explicit), TIME-2 (semantic is
explicit), and TIME-3 (candle closure evaluated from explicit inputs, never
ambient now()).
"""

from __future__ import annotations

import dataclasses
import inspect
from datetime import UTC, datetime, timedelta, timezone

import pytest

from data_layer.contracts import IntegrityViolation
from data_layer.market_data_models import (
    DataTimestamp,
    TimeSemantic,
    candle_closed_as_of,
)

NOW = datetime(2026, 8, 14, 12, 0, tzinfo=UTC)


def test_closed_vocabulary_has_exactly_six_semantics():
    assert {member.value for member in TimeSemantic} == {
        "EVENT_TIME", "SOURCE_TIME", "INGESTION_TIME",
        "PROCESSING_TIME", "RECEIVED_TIME", "SNAPSHOT_TIME",
    }


def test_naive_datetime_is_rejected():
    with pytest.raises(IntegrityViolation):
        DataTimestamp(value=datetime(2026, 8, 14, 12, 0), semantic=TimeSemantic.EVENT_TIME)


def test_aware_non_utc_datetime_is_normalized_to_utc():
    plus_three = datetime(2026, 8, 14, 15, 0, tzinfo=timezone(timedelta(hours=3)))
    ts = DataTimestamp(value=plus_three, semantic=TimeSemantic.EVENT_TIME)
    assert ts.value == NOW
    assert ts.isoformat() == "2026-08-14T12:00:00Z"


def test_serialization_is_iso8601_utc_with_z_suffix():
    ts = DataTimestamp(value=NOW, semantic=TimeSemantic.SOURCE_TIME)
    assert ts.isoformat().endswith("Z")
    assert "+00:00" not in ts.isoformat()


def test_roundtrip_through_dict():
    ts = DataTimestamp(value=NOW, semantic=TimeSemantic.RECEIVED_TIME)
    restored = DataTimestamp.from_dict(ts.as_dict())
    assert restored == ts


def test_invalid_semantic_is_rejected():
    with pytest.raises(IntegrityViolation):
        DataTimestamp(value=NOW, semantic="NOT_A_REAL_SEMANTIC")


def test_semantic_is_explicit_not_inferred_from_a_field_name():
    # The exact same instant carries different, independently meaningful semantics.
    event = DataTimestamp(value=NOW, semantic=TimeSemantic.EVENT_TIME)
    ingestion = DataTimestamp(value=NOW, semantic=TimeSemantic.INGESTION_TIME)
    assert event.value == ingestion.value
    assert event.semantic != ingestion.semantic


def test_data_timestamp_is_immutable():
    ts = DataTimestamp(value=NOW, semantic=TimeSemantic.EVENT_TIME)
    with pytest.raises(dataclasses.FrozenInstanceError):
        ts.value = NOW + timedelta(hours=1)


def test_candle_closed_as_of_uses_only_explicit_inputs():
    close_time = DataTimestamp(value=NOW, semantic=TimeSemantic.EVENT_TIME)
    cutoff_after = DataTimestamp(value=NOW + timedelta(seconds=1), semantic=TimeSemantic.EVENT_TIME)
    cutoff_before = DataTimestamp(value=NOW - timedelta(seconds=1), semantic=TimeSemantic.EVENT_TIME)
    assert candle_closed_as_of(close_time, cutoff_after) is True
    assert candle_closed_as_of(close_time, cutoff_before) is False


# -- frozen boundary rule: the close instant is INCLUSIVE -----------------------

def test_cutoff_before_close_is_not_closed():
    close_time = DataTimestamp(value=NOW, semantic=TimeSemantic.EVENT_TIME)
    cutoff = DataTimestamp(value=NOW - timedelta(microseconds=1), semantic=TimeSemantic.EVENT_TIME)
    assert candle_closed_as_of(close_time, cutoff) is False


def test_cutoff_exactly_at_close_is_closed():
    # Permanent pin of the frozen INCLUSIVE boundary: mutating the
    # implementation's `<=` to `<` must fail here. The close instant is the
    # last instant the candle covers, so standing exactly on it observes a
    # finished candle.
    close_time = DataTimestamp(value=NOW, semantic=TimeSemantic.EVENT_TIME)
    cutoff = DataTimestamp(value=NOW, semantic=TimeSemantic.EVENT_TIME)
    assert candle_closed_as_of(close_time, cutoff) is True


def test_cutoff_exactly_at_close_is_closed_across_timezone_representations():
    # The boundary is an instant, not a wall-clock string: the same instant
    # expressed in a non-UTC offset must still land exactly on the boundary.
    close_time = DataTimestamp(value=NOW, semantic=TimeSemantic.EVENT_TIME)
    same_instant_plus_three = DataTimestamp(
        value=datetime(2026, 8, 14, 15, 0, tzinfo=timezone(timedelta(hours=3))),
        semantic=TimeSemantic.EVENT_TIME,
    )
    assert candle_closed_as_of(close_time, same_instant_plus_three) is True


def test_cutoff_after_close_is_closed():
    close_time = DataTimestamp(value=NOW, semantic=TimeSemantic.EVENT_TIME)
    cutoff = DataTimestamp(value=NOW + timedelta(microseconds=1), semantic=TimeSemantic.EVENT_TIME)
    assert candle_closed_as_of(close_time, cutoff) is True


# -- both operands must be EVENT_TIME ------------------------------------------

@pytest.mark.parametrize(
    "wrong_semantic",
    [
        TimeSemantic.SOURCE_TIME,
        TimeSemantic.INGESTION_TIME,
        TimeSemantic.PROCESSING_TIME,
        TimeSemantic.RECEIVED_TIME,
        TimeSemantic.SNAPSHOT_TIME,
    ],
)
def test_close_time_with_a_non_event_time_semantic_is_rejected(wrong_semantic):
    close_time = DataTimestamp(value=NOW, semantic=wrong_semantic)
    cutoff = DataTimestamp(value=NOW, semantic=TimeSemantic.EVENT_TIME)
    with pytest.raises(IntegrityViolation):
        candle_closed_as_of(close_time, cutoff)


@pytest.mark.parametrize(
    "wrong_semantic",
    [
        TimeSemantic.SOURCE_TIME,
        TimeSemantic.INGESTION_TIME,
        TimeSemantic.PROCESSING_TIME,
        TimeSemantic.RECEIVED_TIME,
        TimeSemantic.SNAPSHOT_TIME,
    ],
)
def test_evaluation_cutoff_with_a_non_event_time_semantic_is_rejected(wrong_semantic):
    close_time = DataTimestamp(value=NOW, semantic=TimeSemantic.EVENT_TIME)
    cutoff = DataTimestamp(value=NOW, semantic=wrong_semantic)
    with pytest.raises(IntegrityViolation):
        candle_closed_as_of(close_time, cutoff)


def test_candle_closure_operands_must_be_data_timestamps_not_raw_datetimes():
    close_time = DataTimestamp(value=NOW, semantic=TimeSemantic.EVENT_TIME)
    with pytest.raises(IntegrityViolation):
        candle_closed_as_of(NOW, close_time)
    with pytest.raises(IntegrityViolation):
        candle_closed_as_of(close_time, NOW)


def test_candle_closed_as_of_does_not_read_ambient_clock():
    # datetime.datetime is an immutable builtin (its now/utcnow cannot be
    # monkeypatched), so this is a static counterfactual over the function's
    # *code*, not its docstring: no clock call may appear, only the two
    # explicit DataTimestamp inputs.
    import ast

    tree = ast.parse(inspect.getsource(candle_closed_as_of))
    function_body = tree.body[0].body
    clock_call_names = {"now", "utcnow", "time"}
    for node in ast.walk(ast.Module(body=function_body, type_ignores=[])):
        if isinstance(node, ast.Call):
            called_name = node.func.attr if isinstance(node.func, ast.Attribute) else getattr(node.func, "id", None)
            assert called_name not in clock_call_names
