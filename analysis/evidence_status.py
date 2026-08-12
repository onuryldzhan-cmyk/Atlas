"""
Atlas Analysis Layer
Market-Data Evidence Status v1.0

Closed vocabulary describing whether a market_data field represents
genuinely observed evidence, or something else (no provider, provider
failure, rejected input).

This is a baseline/producer-side concept and is intentionally separate
from core.decision_intelligence.EvidenceStatus (the Phase-5 shadow
fusion evidence-quality enum: VALID / STALE / INVALID). The two answer
different questions - Phase-5's EvidenceStatus judges the freshness/
validity of an already-accepted Evidence item, while this enum records
whether a producer had any real evidence to offer in the first place -
and must not be imported into or conflated with each other, so the
baseline and Phase-5 paths stay architecturally independent.
"""

from __future__ import annotations

from enum import Enum


class MarketDataEvidenceStatus(str, Enum):
    """
    Status of one market_data field's evidence.

    AVAILABLE:
        The value was derived from real, successfully parsed input.

    UNAVAILABLE_NO_PROVIDER:
        No production-grade data source exists for this field yet.

    UNAVAILABLE_PROVIDER_ERROR:
        A provider exists but failed to produce a value for this cycle.

    REJECTED_MALFORMED:
        Input for this field was present but could not be parsed/used.
    """

    AVAILABLE = "AVAILABLE"
    UNAVAILABLE_NO_PROVIDER = "UNAVAILABLE_NO_PROVIDER"
    UNAVAILABLE_PROVIDER_ERROR = "UNAVAILABLE_PROVIDER_ERROR"
    REJECTED_MALFORMED = "REJECTED_MALFORMED"
