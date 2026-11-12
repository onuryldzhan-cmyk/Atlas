"""Shared input validation and source provenance for the Strategic Scout (Task 011).

Everything the scout evaluates arrives from outside Atlas: a person or the
``atlas-dashboard-scout`` agent copies it from a repository page, a paper or a
post. It is therefore untrusted data. This module parses it strictly and never
interprets it: a URL is stored, never fetched; free text is stored, never
executed or followed as an instruction. A field of the wrong type is refused
rather than coerced, because coercion (``"false"`` -> ``True``, ``1`` -> ``True``)
is how a malformed record would slip past a fail-closed check.

This module performs no I/O and imports nothing outside the standard library
(ADR-0009).
"""

from __future__ import annotations

import hashlib
import json
import math
import re
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Any, Mapping

#: Every scout output carries these tags. Scout findings are exploratory
#: research leads: never evidence, never a signal, never a rule change.
EXPLORATORY = "EXPLORATORY"
AUTHORITY_NONE = "NONE"

#: The largest count accepted; anything larger is not a real maintainer, trade or dependency count.
MAX_COUNT = 10**12

#: The longest free-text field accepted. External text is data; there is no
#: reason to keep pages of it, and a bound keeps reports reviewable.
MAX_TEXT_LENGTH = 4000

_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
_ALLOWED_URL_SCHEMES = ("https://", "http://")


class ScoutInputError(ValueError):
    """An external record is malformed; it is refused, never repaired."""


class SourceType(str, Enum):
    """Where an external finding came from."""

    REPOSITORY = "REPOSITORY"
    PAPER = "PAPER"
    DOCUMENTATION = "DOCUMENTATION"
    PACKAGE_INDEX = "PACKAGE_INDEX"
    ARTICLE = "ARTICLE"
    SOCIAL = "SOCIAL"


def require_mapping(payload: Any, what: str) -> Mapping[str, Any]:
    if not isinstance(payload, Mapping):
        raise ScoutInputError(f"{what} must be a mapping, got {type(payload).__name__}")
    return payload


def reject_unknown_keys(payload: Mapping[str, Any], allowed: frozenset[str], what: str) -> None:
    unknown = sorted(str(key) for key in payload if key not in allowed)
    if unknown:
        raise ScoutInputError(f"{what} has unknown field(s) {unknown}")


def _has_control_character(value: str) -> bool:
    return any(ord(ch) < 0x20 or 0x7F <= ord(ch) < 0xA0 or ch in "\u2028\u2029" for ch in value)


def clean_text(value: Any, key: str, *, single_line: bool = False) -> str:
    """A non-empty, bounded, UTF-8-encodable string. ``single_line`` also refuses control
    characters, for label-like fields that end up in log lines and reasons."""
    if not isinstance(value, str) or not value.strip():
        raise ScoutInputError(f"{key} must be a non-empty string")
    if len(value) > MAX_TEXT_LENGTH:
        raise ScoutInputError(f"{key} is longer than {MAX_TEXT_LENGTH} characters")
    try:
        value.encode("utf-8")
    except UnicodeEncodeError as exc:
        raise ScoutInputError(f"{key} is not valid Unicode text") from exc
    if single_line and _has_control_character(value):
        raise ScoutInputError(f"{key} must be a single line without control characters")
    return value.strip()


def text(payload: Mapping[str, Any], key: str, *, required: bool = True, single_line: bool = False) -> str | None:
    value = payload.get(key)
    if value is None:
        if required:
            raise ScoutInputError(f"{key} is required")
        return None
    return clean_text(value, key, single_line=single_line)


def identifier(payload: Mapping[str, Any], key: str) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or not _ID_PATTERN.fullmatch(value):
        raise ScoutInputError(f"{key} must match {_ID_PATTERN.pattern}")
    return value


def optional_bool(payload: Mapping[str, Any], key: str) -> bool | None:
    """``None`` means *not assessed*; only a real bool counts as an answer."""
    value = payload.get(key)
    if value is None or isinstance(value, bool):
        return value
    raise ScoutInputError(f"{key} must be true, false or null, got {type(value).__name__}")


def optional_count(payload: Mapping[str, Any], key: str) -> int | None:
    value = payload.get(key)
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int) or not 0 <= value <= MAX_COUNT:
        raise ScoutInputError(f"{key} must be an integer between 0 and {MAX_COUNT}, or null")
    return value


def optional_amount(payload: Mapping[str, Any], key: str) -> float | None:
    value = payload.get(key)
    if value is None:
        return None
    return finite_amount(value, key)


def finite_amount(value: Any, key: str) -> float:
    """A finite, non-negative number; an int too large for a float is refused, not raised past the caller."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ScoutInputError(f"{key} must be a number")
    try:
        amount = float(value)
    except OverflowError as exc:
        raise ScoutInputError(f"{key} is too large") from exc
    if not math.isfinite(amount) or amount < 0:
        raise ScoutInputError(f"{key} must be finite and non-negative")
    return amount


def text_set(values: Any, what: str) -> frozenset[str]:
    """A collection of non-empty strings. A bare string is refused: iterating it would yield characters."""
    if isinstance(values, (str, bytes)) or isinstance(values, Mapping):
        raise ScoutInputError(f"{what} must be a collection of strings, not a single value")
    try:
        items = tuple(values)
    except TypeError as exc:
        raise ScoutInputError(f"{what} must be a collection of strings") from exc
    return frozenset(clean_text(item, f"{what} entry", single_line=True) for item in items)


def record_digest(payload: Any) -> str:
    """A content digest for an input record, so ordering-free ids exist even for malformed input."""
    try:
        return sha256_hex(payload)
    except (TypeError, ValueError, RecursionError):  # review 22 L-2: a hostile record never aborts a run
        return hashlib.sha256(f"unserializable:{type(payload).__name__}".encode("utf-8")).hexdigest()


def optional_text_tuple(payload: Mapping[str, Any], key: str, *, single_line: bool = False) -> tuple[str, ...] | None:
    """A list of non-empty strings. ``None`` (absent) differs from ``[]`` (assessed, none)."""
    value = payload.get(key)
    if value is None:
        return None
    if isinstance(value, (str, bytes)) or not isinstance(value, (list, tuple)):
        raise ScoutInputError(f"{key} must be a list of strings or null")
    return tuple(clean_text(item, f"{key} entry", single_line=single_line) for item in value)


def parse_utc(value: Any, key: str) -> datetime:
    """A timezone-aware ISO-8601 timestamp; a naive one is ambiguous and refused."""
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value)
        except ValueError as exc:
            raise ScoutInputError(f"{key} is not an ISO-8601 timestamp: {value!r}") from exc
    else:
        raise ScoutInputError(f"{key} must be an ISO-8601 timestamp")
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ScoutInputError(f"{key} must carry a timezone")
    return parsed


def optional_utc(payload: Mapping[str, Any], key: str) -> datetime | None:
    value = payload.get(key)
    return None if value is None else parse_utc(value, key)


def canonical_json(payload: Any) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)


def sha256_hex(payload: Any) -> str:
    return hashlib.sha256(canonical_json(payload).encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class SourceRecord:
    """Where a finding came from, who recorded it and when. The URL is never fetched."""

    url: str
    source_type: SourceType
    retrieved_at: datetime
    retrieved_by: str

    _FIELDS = frozenset({"url", "source_type", "retrieved_at", "retrieved_by"})

    @classmethod
    def from_dict(cls, payload: Any) -> "SourceRecord":
        payload = require_mapping(payload, "source")
        reject_unknown_keys(payload, cls._FIELDS, "source")
        url = text(payload, "url")
        if not url.lower().startswith(_ALLOWED_URL_SCHEMES) or any(ch.isspace() for ch in url):
            raise ScoutInputError("source.url must be an http(s) URL without whitespace")
        try:
            source_type = SourceType(payload.get("source_type"))
        except ValueError as exc:
            raise ScoutInputError(f"source.source_type must be one of {[t.value for t in SourceType]}") from exc
        return cls(
            url=url,
            source_type=source_type,
            retrieved_at=parse_utc(payload.get("retrieved_at"), "source.retrieved_at"),
            retrieved_by=text(payload, "retrieved_by", single_line=True),
        )

    def as_dict(self) -> dict[str, Any]:
        return {
            "url": self.url,
            "source_type": self.source_type.value,
            "retrieved_at": self.retrieved_at.isoformat(),
            "retrieved_by": self.retrieved_by,
        }
