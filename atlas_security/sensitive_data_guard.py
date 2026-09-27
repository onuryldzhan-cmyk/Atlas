"""Fail-closed sanitization for Atlas output boundaries."""

from __future__ import annotations

import re

from collections.abc import Mapping
from dataclasses import fields, is_dataclass
from datetime import date, datetime, time
from enum import Enum
from pathlib import Path
from typing import Any
from uuid import UUID


REDACTED_VALUE = "[REDACTED]"
REDACTED_BINARY = "[REDACTED_BINARY]"
REDACTED_CYCLE = "[REDACTED_CYCLE]"
REDACTED_DEPTH = "[REDACTED_MAX_DEPTH]"
REDACTED_OBJECT = "[REDACTED_OBJECT]"
REDACTED_ERROR = "[REDACTION_ERROR]"

MAX_DEPTH = 16
MAX_COLLECTION_ITEMS = 10_000
MAX_TEXT_LENGTH = 100_000

_SENSITIVE_KEYS = frozenset({
    "api_key", "apikey", "authorization", "auth_token",
    "access_key", "access_token", "refresh_token", "token", "secret",
    "client_secret", "password", "passwd", "credential",
    "credentials", "private_key", "email", "phone", "telephone",
    "address", "passport", "national_id", "identity_number",
    "date_of_birth", "birth_date", "customer_id", "iban", "swift",
    "bank_account", "account_number", "card_number", "credit_card",
    "cvv", "wallet_address", "wallet_private_key", "payment_details",
})

_SENSITIVE_SUFFIXES = tuple(
    "_" + key for key in _SENSITIVE_KEYS if not key.startswith("_")
)

_PRIVATE_KEY_PATTERN = re.compile(
    r"-----BEGIN\s+[^\r\n-]*PRIVATE KEY-----.*?"
    r"-----END\s+[^\r\n-]*PRIVATE KEY-----",
    re.IGNORECASE | re.DOTALL,
)
_BEARER_PATTERN = re.compile(
    r"\bBearer\s+[A-Za-z0-9._~+/=-]{6,}", re.IGNORECASE
)
_EMAIL_PATTERN = re.compile(
    r"(?<![A-Za-z0-9._%+-])[A-Za-z0-9._%+-]+@"
    r"[A-Za-z0-9.-]+\.[A-Za-z]{2,}(?![A-Za-z0-9._%+-])"
)
_IBAN_PATTERN = re.compile(
    r"\b[A-Z]{2}\d{2}(?:[ ]?[A-Z0-9]){11,30}\b", re.IGNORECASE
)
_CREDENTIAL_ASSIGNMENT_PATTERN = re.compile(
    r"\b(api[ _-]?key|secret|token|password|passwd|credential|"
    r"authorization|private[ _-]?key|access[ _-]?key|"
    r"access[ _-]?token|refresh[ _-]?token)"
    r"\s*[:=]\s*(?:\"[^\"]*\"|'[^']*'|[^\s,;}\]]+)",
    re.IGNORECASE,
)
_CARD_CANDIDATE_PATTERN = re.compile(r"(?<!\d)(?:\d[ -]?){12,18}\d(?!\d)")

#: Structural bounds shared by every opaque machine identifier in Atlas.
#: `core.model_provider_contracts.machine_identifier` imports these, so the
#: preserving validators on both sides of the dependency can never drift.
MAX_IDENTIFIER_LENGTH = 200
FORBIDDEN_IDENTIFIER_CHARACTERS = "\r\n\t\x00"

#: Field names whose value is opaque machine identity in the execution
#: authorities (transaction journal, idempotency store, audit events).
#: Identity's only job is to equal itself - recovery compares these
#: byte-exact - and the card detector below rewrites them: a candle
#: ``request_id`` such as ``BTCUSDT|open:1786112160000|SELL`` carries a
#: 13-digit Luhn-valid run about 10% of the time, a uuid4 about 0.23%.
#: Preserved only by `sanitize_sensitive_data(..., preserve_identifiers=True)`.
OPAQUE_IDENTIFIER_KEYS = frozenset({
    "request_id", "execution_id", "idempotency_key",
    "execution_fingerprint", "candle_identity", "position_id",
    "order_id", "trade_id",
})

#: Field names whose value is a SHA-256 hexdigest, preserved under the same
#: switch but only when it is exactly 64 lowercase hex characters.
DIGEST_KEYS = frozenset({"instrument_rules_digest"})

_SHA256_HEX_PATTERN = re.compile(r"[0-9a-f]{64}")

#: Field names whose value is a journal provenance reference, preserved under
#: the same switch but only in the one shape the execution authorities write:
#: ``transaction-journal:<request_id>``, where ``<request_id>`` itself passes
#: every rule an `OPAQUE_IDENTIFIER_KEYS` value must pass. The prefix is not
#: counted against `MAX_IDENTIFIER_LENGTH`; the embedded identifier is.
PROVENANCE_REF_KEYS = frozenset({"provenance_ref"})
PROVENANCE_REF_PREFIX = "transaction-journal:"

#: The preservation privilege (never validity) is further limited to the
#: characters Atlas's own identifiers use: uuid4, candle ids
#: (``SYMBOL|open:<ms>|SIDE``) and venue order/trade ids. A value outside it -
#: an email, ``key=value``, anything with whitespace - is not rejected; it is
#: simply redacted as before, so an identity key name can never become an
#: unsanitized channel for free text.
_PRESERVABLE_IDENTIFIER_PATTERN = re.compile(r"[A-Za-z0-9|:._-]+")


def _normalize_key(key: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", key.strip().lower()).strip("_")


def _is_sensitive_key(key: str) -> bool:
    normalized = _normalize_key(key)
    return normalized in _SENSITIVE_KEYS or any(
        normalized.endswith(suffix) for suffix in _SENSITIVE_SUFFIXES
    )


def is_opaque_machine_identifier(value: Any) -> bool:
    """Whether `value` is structurally a valid opaque machine identifier.

    The same rules `machine_identifier` enforces - a non-empty string, no
    surrounding whitespace, bounded length, no control characters - as a
    predicate. Nothing is coerced or repaired: a value that fails is not
    preserved and goes through ordinary redaction instead.
    """
    return (
        isinstance(value, str)
        and bool(value)
        and value.strip() == value
        and len(value) <= MAX_IDENTIFIER_LENGTH
        and not any(ch in value for ch in FORBIDDEN_IDENTIFIER_CHARACTERS)
    )


def _is_preservable_identifier(value: Any) -> bool:
    return bool(
        is_opaque_machine_identifier(value)
        and _PRESERVABLE_IDENTIFIER_PATTERN.fullmatch(value)
    )


def _preserved_identifier(key: str | None, value: Any) -> str | None:
    """The byte-exact value to keep for an identity field, else None."""
    if key in OPAQUE_IDENTIFIER_KEYS:
        if isinstance(value, UUID):
            return str(value)
        if _is_preservable_identifier(value):
            return value
    elif key in DIGEST_KEYS:
        if isinstance(value, str) and _SHA256_HEX_PATTERN.fullmatch(value):
            return value
    elif key in PROVENANCE_REF_KEYS:
        if (
            isinstance(value, str)
            and value.startswith(PROVENANCE_REF_PREFIX)
            and _is_preservable_identifier(value[len(PROVENANCE_REF_PREFIX):])
        ):
            return value
    return None


def _passes_luhn(candidate: str) -> bool:
    digits = [int(ch) for ch in candidate if ch.isdigit()]
    if not 13 <= len(digits) <= 19:
        return False
    checksum = 0
    parity = len(digits) % 2
    for index, digit in enumerate(digits):
        value = digit
        if index % 2 == parity:
            value *= 2
            if value > 9:
                value -= 9
        checksum += value
    return checksum % 10 == 0


def _redact_card_candidates(text: str) -> str:
    return _CARD_CANDIDATE_PATTERN.sub(
        lambda match: REDACTED_VALUE if _passes_luhn(match.group(0)) else match.group(0),
        text,
    )


def sanitize_sensitive_text(value: str) -> str:
    text = value[:MAX_TEXT_LENGTH]
    text = _PRIVATE_KEY_PATTERN.sub(REDACTED_VALUE, text)
    text = _BEARER_PATTERN.sub("Bearer " + REDACTED_VALUE, text)
    text = _CREDENTIAL_ASSIGNMENT_PATTERN.sub(
        lambda match: f"{match.group(1)}={REDACTED_VALUE}", text
    )
    text = _EMAIL_PATTERN.sub(REDACTED_VALUE, text)
    text = _IBAN_PATTERN.sub(REDACTED_VALUE, text)
    text = _redact_card_candidates(text)
    if len(value) > MAX_TEXT_LENGTH:
        text += "[TRUNCATED]"
    return text


def _safe_key(value: Any) -> str:
    if isinstance(value, str):
        return sanitize_sensitive_text(value)
    if isinstance(value, (int, float, bool, UUID)):
        return str(value)
    return f"[KEY:{type(value).__name__}]"


def sanitize_sensitive_data(
    value: Any, *, key: str | None = None, _depth: int = 0,
    _stack: set[int] | None = None, preserve_identifiers: bool = False,
) -> Any:
    """Recursively redact sensitive content from `value`.

    With ``preserve_identifiers=True`` a value held under one of
    `OPAQUE_IDENTIFIER_KEYS`, `DIGEST_KEYS` or `PROVENANCE_REF_KEYS` is
    returned byte-exact when it
    is structurally valid for its class, and redacted exactly as before when
    it is not. Only the execution authorities opt in; every other caller
    and every other field keeps the full redaction behavior. A sensitive
    key name still wins (the two key sets are disjoint by construction).
    """
    try:
        if key is not None and _is_sensitive_key(key):
            return REDACTED_VALUE
        if preserve_identifiers and key is not None:
            preserved = _preserved_identifier(key, value)
            if preserved is not None:
                return preserved
        if _depth > MAX_DEPTH:
            return REDACTED_DEPTH
        if value is None or isinstance(value, (bool, int, float)):
            return value
        if isinstance(value, str):
            return sanitize_sensitive_text(value)
        if isinstance(value, bytes):
            return REDACTED_BINARY
        if isinstance(value, (datetime, date, time)):
            return value.isoformat()
        if isinstance(value, (UUID, Path)):
            return sanitize_sensitive_text(str(value))
        if isinstance(value, Enum):
            return sanitize_sensitive_data(
                value.value, key=key, _depth=_depth + 1, _stack=_stack,
                preserve_identifiers=preserve_identifiers,
            )

        stack = _stack if _stack is not None else set()
        object_id = id(value)
        if object_id in stack:
            return REDACTED_CYCLE

        if isinstance(value, Mapping):
            stack.add(object_id)
            try:
                result: dict[str, Any] = {}
                for index, (raw_key, nested_value) in enumerate(value.items()):
                    if index >= MAX_COLLECTION_ITEMS:
                        result["[TRUNCATED]"] = True
                        break
                    normalized_key = _safe_key(raw_key)
                    result[normalized_key] = sanitize_sensitive_data(
                        nested_value, key=normalized_key,
                        _depth=_depth + 1, _stack=stack,
                        preserve_identifiers=preserve_identifiers,
                    )
                return result
            finally:
                stack.discard(object_id)

        if isinstance(value, (list, tuple, set, frozenset)):
            stack.add(object_id)
            try:
                result_list: list[Any] = []
                for index, item in enumerate(value):
                    if index >= MAX_COLLECTION_ITEMS:
                        result_list.append("[TRUNCATED]")
                        break
                    result_list.append(sanitize_sensitive_data(
                        item, _depth=_depth + 1, _stack=stack,
                        preserve_identifiers=preserve_identifiers,
                    ))
                return result_list
            finally:
                stack.discard(object_id)

        if is_dataclass(value) and not isinstance(value, type):
            stack.add(object_id)
            try:
                return {
                    field.name: sanitize_sensitive_data(
                        getattr(value, field.name), key=field.name,
                        _depth=_depth + 1, _stack=stack,
                        preserve_identifiers=preserve_identifiers,
                    )
                    for field in fields(value)
                }
            finally:
                stack.discard(object_id)

        to_dict = getattr(value, "to_dict", None)
        if callable(to_dict):
            stack.add(object_id)
            try:
                return sanitize_sensitive_data(
                    to_dict(), _depth=_depth + 1, _stack=stack,
                    preserve_identifiers=preserve_identifiers,
                )
            except Exception:
                return REDACTED_ERROR
            finally:
                stack.discard(object_id)

        if hasattr(value, "__dict__"):
            stack.add(object_id)
            try:
                return sanitize_sensitive_data(
                    vars(value), _depth=_depth + 1, _stack=stack,
                    preserve_identifiers=preserve_identifiers,
                )
            except Exception:
                return REDACTED_OBJECT
            finally:
                stack.discard(object_id)

        return f"{REDACTED_OBJECT}:{type(value).__name__}"
    except Exception:
        return REDACTED_ERROR


if any(_is_sensitive_key(name) for name in OPAQUE_IDENTIFIER_KEYS | DIGEST_KEYS):
    raise RuntimeError("an identity key must never also be a sensitive key")


def sanitize_sensitive_mapping(
    value: Mapping[str, Any] | None,
) -> dict[str, Any]:
    sanitized = sanitize_sensitive_data(value or {})
    return sanitized if isinstance(sanitized, dict) else {"value": sanitized}
