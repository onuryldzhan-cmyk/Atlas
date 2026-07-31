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


def _normalize_key(key: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", key.strip().lower()).strip("_")


def _is_sensitive_key(key: str) -> bool:
    normalized = _normalize_key(key)
    return normalized in _SENSITIVE_KEYS or any(
        normalized.endswith(suffix) for suffix in _SENSITIVE_SUFFIXES
    )


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
    _stack: set[int] | None = None,
) -> Any:
    try:
        if key is not None and _is_sensitive_key(key):
            return REDACTED_VALUE
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
                value.value, key=key, _depth=_depth + 1, _stack=_stack
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
                        item, _depth=_depth + 1, _stack=stack
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
                    to_dict(), _depth=_depth + 1, _stack=stack
                )
            except Exception:
                return REDACTED_ERROR
            finally:
                stack.discard(object_id)

        if hasattr(value, "__dict__"):
            stack.add(object_id)
            try:
                return sanitize_sensitive_data(
                    vars(value), _depth=_depth + 1, _stack=stack
                )
            except Exception:
                return REDACTED_OBJECT
            finally:
                stack.discard(object_id)

        return f"{REDACTED_OBJECT}:{type(value).__name__}"
    except Exception:
        return REDACTED_ERROR


def sanitize_sensitive_mapping(
    value: Mapping[str, Any] | None,
) -> dict[str, Any]:
    sanitized = sanitize_sensitive_data(value or {})
    return sanitized if isinstance(sanitized, dict) else {"value": sanitized}
