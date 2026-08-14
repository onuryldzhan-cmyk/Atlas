"""Block 4 / Package 1: MarketDataQualityStatus closed vocabulary.

Covers DATA-1 (missing != zero), DATA-2 (unavailable != neutral), DATA-4
(future-dated has an explicit fail-closed state), and the naming
distinction from analysis.evidence_status.MarketDataEvidenceStatus.
"""

from __future__ import annotations

import pytest

from data_layer.market_data_models import MarketDataQualityStatus


def test_closed_vocabulary_has_exactly_nine_states():
    assert {member.value for member in MarketDataQualityStatus} == {
        "OK", "MISSING", "STALE", "MALFORMED", "DUPLICATE",
        "OUT_OF_ORDER", "PARTIAL", "FUTURE_DATED", "SOURCE_UNAVAILABLE",
    }


def test_missing_is_distinct_from_ok_and_from_a_numeric_zero():
    # A mutation collapsing MISSING into OK (treating "no data" as
    # equivalent to a valid reading) must make this fail.
    assert MarketDataQualityStatus.MISSING is not MarketDataQualityStatus.OK
    assert MarketDataQualityStatus.MISSING.value != "0"
    assert MarketDataQualityStatus.MISSING.value not in ("0", 0, 0.0)


def test_source_unavailable_is_distinct_from_ok():
    # A mutation collapsing SOURCE_UNAVAILABLE into OK (treating "no
    # provider" as a neutral reading) must make this fail.
    assert MarketDataQualityStatus.SOURCE_UNAVAILABLE is not MarketDataQualityStatus.OK


def test_future_dated_is_an_explicit_distinct_state():
    assert MarketDataQualityStatus.FUTURE_DATED is not MarketDataQualityStatus.OK
    assert MarketDataQualityStatus.FUTURE_DATED.value == "FUTURE_DATED"


def test_malformed_is_distinct_from_every_other_member():
    others = [member for member in MarketDataQualityStatus if member is not MarketDataQualityStatus.MALFORMED]
    assert MarketDataQualityStatus.MALFORMED not in others
    assert all(MarketDataQualityStatus.MALFORMED != member for member in others)


def test_vocabulary_is_closed_against_unknown_strings():
    # The real fail-closed property: an unrecognised marker cannot be
    # coerced into a member. This is NOT the same as "membership is exact" --
    # MarketDataQualityStatus is a str subclass, so equality with its own
    # value string is True by design (pinned below). What must never happen
    # is a value outside the vocabulary resolving to a status at all.
    for unknown in ("MALFORMED_ISH", "ok", "", "UNKNOWN", "0"):
        with pytest.raises(ValueError):
            MarketDataQualityStatus(unknown)


def test_str_subclass_equality_is_by_value_not_by_identity():
    # Documented, deliberate consequence of the str mixin: comparing a
    # member to its own value string succeeds, and to any other status'
    # value string fails. Pinned so the mixin is never removed or widened
    # by accident.
    assert MarketDataQualityStatus.MALFORMED == "MALFORMED"
    assert MarketDataQualityStatus.MALFORMED != "OK"
    assert MarketDataQualityStatus.MALFORMED != MarketDataQualityStatus.OK.value


def test_market_data_quality_status_is_not_the_evidence_status_enum():
    from analysis.evidence_status import MarketDataEvidenceStatus

    assert MarketDataQualityStatus is not MarketDataEvidenceStatus
    assert set(MarketDataQualityStatus.__members__) != set(MarketDataEvidenceStatus.__members__)
