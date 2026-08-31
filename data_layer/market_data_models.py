"""Canonical market-data contract foundation: time semantics, provenance,
and dataset identity value objects.

This is a companion, additive bounded context. It does not modify, import,
or subclass atlas_finance.market_data.models (MarketPrice/MarketCandle) or
the execution-domain records in data_layer.models (OrderRecord/
ExecutionRecord/PositionRecord). It reuses only the generic UTC-normalization
helper (utc_text) and the shared IntegrityViolation exception so market-data
timestamps fail closed the same way execution-domain timestamps already do,
instead of introducing a second, contradictory normalization behavior.

Token normalization policy (frozen for Package 1)
------------------------------------------------
source, venue:
    stripped and case-folded to lowercase. Case variants of the same
    provider/venue name denote the same logical dataset, so BINANCE,
    binance, and Binance must converge to one identity_digest().
instrument:
    stripped and upper-cased via normalize_instrument(); the canonical
    instrument form is upper case.
timeframe:
    stripped only, and deliberately CASE-SENSITIVE. Timeframe grammar is
    domain-specific -- "5m" and "5M" may legitimately denote five minutes
    and five months -- so this module must not assume an equivalence it
    cannot justify. "5m" and "5M" therefore remain distinguishable logical
    datasets unless a future domain-specific timeframe validator explicitly
    defines their equivalence.
schema_version, transform_version:
    stripped only, case preserved. Version strings are opaque identifiers
    supplied by their producer and are compared byte-for-byte.

Not wired into any runtime composition path. See
data_layer/market_data_contracts.py for the companion repository Protocol
seams.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Any

from .contracts import IntegrityViolation
from .models import utc_text

_TOKEN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,63}$")
_INSTRUMENT = re.compile(r"^[A-Z0-9]{2,24}$")
_SHA256_HEX = re.compile(r"^[0-9a-f]{64}$")


def _required_token(value: Any, name: str, *, casefold: bool = False) -> str:
    """Validate an opaque identifier token.

    casefold=True applies the source/venue case-folding rule documented in
    the module docstring. It is deliberately not the default: timeframe,
    schema_version, and transform_version must keep their case.
    """

    text = str(value).strip() if value is not None else ""
    if casefold:
        text = text.casefold()
    if not _TOKEN.fullmatch(text):
        raise IntegrityViolation(f"invalid {name}")
    return text


def normalize_instrument(value: str) -> str:
    text = str(value).strip().upper()
    if not _INSTRUMENT.fullmatch(text):
        raise IntegrityViolation("invalid instrument identifier")
    return text


def sha256_hex(value: str, name: str = "content_hash") -> str:
    """Canonicalize a SHA-256 digest to lowercase hex, rejecting anything else.

    Lowercase is the canonical stored form: an upper-case but otherwise
    valid digest is accepted and folded to lowercase so that the same digest
    written in either case compares and keys identically.
    """

    text = str(value).strip().lower()
    if not _SHA256_HEX.fullmatch(text):
        raise IntegrityViolation(f"invalid {name}: must be a 64-character lowercase hex SHA-256 digest")
    return text


def compute_content_digest(payload: Any) -> str:
    """Deterministic SHA-256 digest of a JSON-safe payload, for manifest content identity."""
    canonical_json = json.dumps(payload, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(canonical_json.encode("utf-8")).hexdigest()


class TimeSemantic(str, Enum):
    """Closed vocabulary of what a market-data timestamp means.

    EVENT_TIME: When the observed market event actually occurred (e.g. a
        candle's close).
    SOURCE_TIME: The timestamp assigned by the upstream provider/exchange.
    INGESTION_TIME: When Atlas first admitted the record into its own
        pipeline.
    PROCESSING_TIME: When Atlas last transformed/derived the record.
    RECEIVED_TIME: When the local process received the record over the wire.
    SNAPSHOT_TIME: When a point-in-time view (e.g. a manifest) was captured.
    """

    EVENT_TIME = "EVENT_TIME"
    SOURCE_TIME = "SOURCE_TIME"
    INGESTION_TIME = "INGESTION_TIME"
    PROCESSING_TIME = "PROCESSING_TIME"
    RECEIVED_TIME = "RECEIVED_TIME"
    SNAPSHOT_TIME = "SNAPSHOT_TIME"


@dataclass(frozen=True, slots=True)
class DataTimestamp:
    """An immutable UTC instant bound to its explicit TimeSemantic.

    Naive datetimes are rejected; timezone-aware datetimes are normalized to
    UTC via data_layer.models.utc_text, the same fail-closed helper the
    execution-domain records already use.
    """

    value: datetime | str
    semantic: TimeSemantic

    def __post_init__(self) -> None:
        try:
            normalized_semantic = TimeSemantic(self.semantic)
        except ValueError as exc:
            raise IntegrityViolation("invalid time semantic") from exc
        object.__setattr__(self, "semantic", normalized_semantic)
        text = utc_text(self.value)
        object.__setattr__(self, "value", datetime.fromisoformat(text.replace("Z", "+00:00")))

    def isoformat(self) -> str:
        return utc_text(self.value)

    def as_dict(self) -> dict[str, str]:
        return {"value": self.isoformat(), "semantic": self.semantic.value}

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "DataTimestamp":
        return cls(value=data["value"], semantic=data["semantic"])


def _require_event_time(timestamp: Any, name: str) -> DataTimestamp:
    """Require an EVENT_TIME DataTimestamp, failing closed on anything else.

    Comparing a wall-clock timestamp (INGESTION_TIME, RECEIVED_TIME,
    PROCESSING_TIME, SNAPSHOT_TIME) or a provider-assigned SOURCE_TIME
    against an event-time boundary is a category error: the two measure
    different things and their ordering carries no market meaning. Callers
    must convert deliberately rather than have this module guess.
    """

    if not isinstance(timestamp, DataTimestamp):
        raise IntegrityViolation(f"{name} must be a DataTimestamp")
    if timestamp.semantic is not TimeSemantic.EVENT_TIME:
        raise IntegrityViolation(f"{name} must use EVENT_TIME semantics")
    return timestamp


def candle_closed_as_of(close_time: DataTimestamp, evaluation_cutoff: DataTimestamp) -> bool:
    """Evaluate candle closure from explicit inputs only; never reads ambient now().

    Boundary rule (frozen Package-1 semantic, INCLUSIVE):

        evaluation_cutoff <  close_time -> False
        evaluation_cutoff == close_time -> True
        evaluation_cutoff >  close_time -> True

    A candle whose close instant has exactly been reached is CLOSED. The
    close instant is the last instant the candle covers, so an evaluation
    standing precisely on it observes a finished candle, not a partial one.

    Both inputs must carry EVENT_TIME semantics. Any other semantic raises
    IntegrityViolation rather than being silently compared.

    Not wired into core/candle_processor.py; the live candle path keeps its
    existing closure computation for Block 4 Package 1.
    """

    _require_event_time(close_time, "close_time")
    _require_event_time(evaluation_cutoff, "evaluation_cutoff")
    return close_time.value <= evaluation_cutoff.value


class MarketDataQualityStatus(str, Enum):
    """Closed vocabulary of contract-level market-data quality states.

    Deliberately named to avoid analysis.evidence_status.MarketDataEvidenceStatus,
    which answers a different question (whether a producer had any real
    evidence to offer at all). This enum instead classifies the state of one
    already-ingested market-data record.
    """

    OK = "OK"
    MISSING = "MISSING"
    STALE = "STALE"
    MALFORMED = "MALFORMED"
    DUPLICATE = "DUPLICATE"
    OUT_OF_ORDER = "OUT_OF_ORDER"
    PARTIAL = "PARTIAL"
    FUTURE_DATED = "FUTURE_DATED"
    SOURCE_UNAVAILABLE = "SOURCE_UNAVAILABLE"


@dataclass(frozen=True, slots=True)
class DataProvenance:
    """Immutable record-level provenance for one ingested market-data record.

    Carries no decision confidence, risk, strategy, execution authority, or
    credentials -- only where a record came from and whether its content is
    intact.

    record_content_hash is the cryptographic digest asserted for the
    canonical record/content this provenance object describes. It is
    record-level and is a different granularity from
    DatasetManifest.content_hash, which digests a whole dataset build; the
    two are never expected to be equal and must not be compared.

    upstream_identity_digest may reference an upstream
    DatasetIdentity.identity_digest() without copying its (mutable, larger)
    raw content. It is how a derived dataset points at what it was derived
    from: a derived dataset still gets its own identity and its own
    provenance, and the manifest consistency invariant applies to it
    unchanged.
    """

    source: str
    venue: str
    schema_version: str
    ingested_at: DataTimestamp
    record_content_hash: str
    upstream_identity_digest: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "source", _required_token(self.source, "source", casefold=True))
        object.__setattr__(self, "venue", _required_token(self.venue, "venue", casefold=True))
        object.__setattr__(self, "schema_version", _required_token(self.schema_version, "schema_version"))
        if not isinstance(self.ingested_at, DataTimestamp):
            raise IntegrityViolation("ingested_at must be a DataTimestamp")
        if self.ingested_at.semantic is not TimeSemantic.INGESTION_TIME:
            raise IntegrityViolation("provenance ingested_at must use INGESTION_TIME semantics")
        object.__setattr__(
            self, "record_content_hash", sha256_hex(self.record_content_hash, "record_content_hash"),
        )
        if self.upstream_identity_digest is not None:
            object.__setattr__(
                self, "upstream_identity_digest",
                sha256_hex(self.upstream_identity_digest, "upstream_identity_digest"),
            )


@dataclass(frozen=True, slots=True)
class DatasetIdentity:
    """Deterministic logical identity of a dataset window.

    Incorporates only reproducibility-relevant inputs: source, venue,
    canonical-sorted instrument universe, time range, timeframe, schema
    version, and transform version. Wall-clock ingestion time, file paths,
    cache paths, and random identifiers must never appear here -- two
    datasets built from the same logical inputs, at different times or from
    different cache paths, must produce the same identity_digest().

    range_start and range_end both describe when the covered market events
    occurred, so both must carry EVENT_TIME semantics; any other semantic
    raises IntegrityViolation. range_start must not be after range_end. An
    empty-width window (range_start == range_end) is permitted: it is a
    legitimate point-in-time dataset request, not a malformed one.

    Token normalization follows the frozen policy in the module docstring:
    source/venue case-fold, instruments upper-case, and timeframe /
    schema_version / transform_version keep their case.
    """

    source: str
    venue: str
    instruments: tuple[str, ...]
    range_start: DataTimestamp
    range_end: DataTimestamp
    timeframe: str
    schema_version: str
    transform_version: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "source", _required_token(self.source, "source", casefold=True))
        object.__setattr__(self, "venue", _required_token(self.venue, "venue", casefold=True))
        if not self.instruments:
            raise IntegrityViolation("dataset instrument universe cannot be empty")
        normalized_instruments = [normalize_instrument(i) for i in self.instruments]
        if len(set(normalized_instruments)) != len(normalized_instruments):
            raise IntegrityViolation("dataset instrument universe contains duplicates")
        object.__setattr__(self, "instruments", tuple(sorted(normalized_instruments)))
        _require_event_time(self.range_start, "range_start")
        _require_event_time(self.range_end, "range_end")
        if self.range_start.value > self.range_end.value:
            raise IntegrityViolation("range_start must not be after range_end")
        object.__setattr__(self, "timeframe", _required_token(self.timeframe, "timeframe"))
        object.__setattr__(self, "schema_version", _required_token(self.schema_version, "schema_version"))
        object.__setattr__(self, "transform_version", _required_token(self.transform_version, "transform_version"))

    def canonical_payload(self) -> dict[str, Any]:
        return {
            "source": self.source,
            "venue": self.venue,
            "instruments": list(self.instruments),
            "range_start": self.range_start.isoformat(),
            "range_end": self.range_end.isoformat(),
            "timeframe": self.timeframe,
            "schema_version": self.schema_version,
            "transform_version": self.transform_version,
        }

    def identity_digest(self) -> str:
        """SHA-256 over the key-sorted, separator-canonical JSON payload.

        sort_keys=True is load-bearing: without it the digest would depend
        on this method's dict literal ordering, so a purely cosmetic field
        reordering would silently re-identify every existing dataset.
        """

        canonical_json = json.dumps(self.canonical_payload(), sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(canonical_json.encode("utf-8")).hexdigest()


@dataclass(frozen=True, slots=True)
class DatasetManifest:
    """Immutable content/manifest digest binding for one dataset build.

    Separate from DatasetIdentity: content_hash identifies actual content,
    while identity.identity_digest() identifies the reproducible logical
    inputs that produced it. Differing schema/transform/content must not
    silently collide -- both digests are computed independently and neither
    is derived from the other.

    content_hash here is dataset-level. DataProvenance.record_content_hash
    is record-level. They are different granularities and are never asserted
    to be equal.

    The manifest's provenance must describe the same dataset its identity
    describes, so source, venue, and schema_version must agree between the
    two. A derived dataset does not weaken this: it carries its own identity
    and its own provenance (both naming the deriving pipeline), and points
    at what it was derived from through provenance.upstream_identity_digest.
    """

    identity: DatasetIdentity
    content_hash: str
    record_count: int
    provenance: DataProvenance
    generated_at: DataTimestamp

    def __post_init__(self) -> None:
        if not isinstance(self.identity, DatasetIdentity):
            raise IntegrityViolation("manifest identity must be a DatasetIdentity")
        object.__setattr__(self, "content_hash", sha256_hex(self.content_hash))
        if not isinstance(self.record_count, int) or isinstance(self.record_count, bool) or self.record_count < 0:
            raise IntegrityViolation("invalid record_count")
        if not isinstance(self.provenance, DataProvenance):
            raise IntegrityViolation("manifest provenance must be a DataProvenance")
        if self.provenance.source != self.identity.source:
            raise IntegrityViolation("manifest provenance source must match dataset identity source")
        if self.provenance.venue != self.identity.venue:
            raise IntegrityViolation("manifest provenance venue must match dataset identity venue")
        if self.provenance.schema_version != self.identity.schema_version:
            raise IntegrityViolation(
                "manifest provenance schema_version must match dataset identity schema_version"
            )
        if not isinstance(self.generated_at, DataTimestamp):
            raise IntegrityViolation("generated_at must be a DataTimestamp")
        if self.generated_at.semantic is not TimeSemantic.SNAPSHOT_TIME:
            raise IntegrityViolation("manifest generated_at must use SNAPSHOT_TIME semantics")

    @property
    def logical_identity_digest(self) -> str:
        return self.identity.identity_digest()


__all__ = [
    "DataProvenance",
    "DataTimestamp",
    "DatasetIdentity",
    "DatasetManifest",
    "MarketDataQualityStatus",
    "TimeSemantic",
    "candle_closed_as_of",
    "compute_content_digest",
    "normalize_instrument",
    "sha256_hex",
]
