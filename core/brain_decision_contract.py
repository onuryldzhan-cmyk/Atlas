"""Task 012 (registry v5.96): the typed Brain -> MarketLoop decision contract.

MarketLoop normalizes every Brain decision (DecisionAdapter, then normalize_decision) and then
validates the result against ``BrainDecisionPayload`` before any execution gate sees it. A
decision that fails is dropped fail-closed: it is never routed, and MarketLoop logs and publishes
DECISION_CONTRACT_REJECTED with the violation code. A decision that passes is routed exactly as
before; the contract only reads it and never rewrites it.

The frozen dataclass is the only runtime validator. ``brain_decision_payload.schema.json``, next
to this module, documents the same contract as JSON Schema (draft 2020-12); the tests hold the two
to the same field cases. Two differences are documentation-only: created_at is parsed with
Python's datetime.fromisoformat, which accepts more ISO 8601 forms than the schema's RFC 3339
"date-time", and the schema's ECMA non-whitespace pattern differs from str.strip on a few characters
(some control characters and U+FEFF). No
schema library is a runtime dependency.

Staleness (owner decision 2026-10-16): a decision created more than MAX_DECISION_AGE before the
check, or more than MAX_CLOCK_SKEW after it, is rejected for BUY and SELL alike; a rejected
decision is decided afresh on the next cycle. created_at is the time the Brain built the
decision object, after its analysis, so this rule refuses replayed or cached decisions and clock
steps; it does not limit how long the Brain takes, nor how old the market data is (MarketLoop's
separate candle-age gate does that for BUY). The contract grants nothing: risk, capital and
execution gates downstream are unchanged.
"""
from __future__ import annotations

import math
import re
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

ACTIONS: tuple[str, ...] = ("BUY", "SELL", "HOLD")
RISK_LEVELS: tuple[str, ...] = ("LOW", "MEDIUM", "HIGH", "CRITICAL", "UNKNOWN")
REQUIRED_FIELDS: tuple[str, ...] = (
    "action", "symbol", "confidence", "strategy", "risk_level", "price", "created_at", "metadata",
)
MAX_DECISION_AGE = timedelta(seconds=180)
MAX_CLOCK_SKEW = timedelta(seconds=5)
SYMBOL_PATTERN = re.compile(r"[A-Z0-9][A-Z0-9_./-]*")


class ContractViolation(ValueError):
    """A decision that breaks the contract; ``code`` is the stable reason recorded in the audit event."""

    def __init__(self, code: str, detail: str = "") -> None:
        self.code = code
        super().__init__(f"{code}: {detail}" if detail else code)


def _number(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    try:
        number = float(value)
    except OverflowError:
        return None
    return number if math.isfinite(number) else None


def _label(value: Any) -> str | None:
    return value if isinstance(value, str) and value.strip() else None


@dataclass(frozen=True, slots=True)
class BrainDecisionPayload:
    """The validated, immutable view of one normalized Brain decision."""

    action: str
    symbol: str
    confidence: float
    strategy: str
    risk_level: str
    price: float
    created_at: datetime

    @classmethod
    def from_decision(
        cls,
        decision: Any,
        *,
        expected_symbol: str,
        now: datetime,
    ) -> BrainDecisionPayload:
        """Validate a normalized decision; raise ContractViolation on the first broken rule."""
        if now.utcoffset() is None:
            raise ValueError("now must be timezone-aware")
        if not isinstance(decision, Mapping):
            raise ContractViolation("NOT_A_MAPPING", type(decision).__name__)
        for name in REQUIRED_FIELDS:
            if name not in decision:
                raise ContractViolation("MISSING_FIELD", name)

        action = decision["action"]
        if not isinstance(action, str) or action not in ACTIONS:
            raise ContractViolation("ACTION_INVALID", repr(action))
        symbol = decision["symbol"]
        if not isinstance(symbol, str) or SYMBOL_PATTERN.fullmatch(symbol) is None:
            raise ContractViolation("SYMBOL_INVALID", repr(decision["symbol"]))
        if symbol != expected_symbol:
            raise ContractViolation("SYMBOL_MISMATCH", f"{symbol} != {expected_symbol}")
        confidence = _number(decision["confidence"])
        if confidence is None or not 0.0 <= confidence <= 100.0:
            raise ContractViolation("CONFIDENCE_INVALID", repr(decision["confidence"]))
        if _label(decision["strategy"]) is None:
            raise ContractViolation("STRATEGY_INVALID", repr(decision["strategy"]))
        risk_level = decision["risk_level"]
        if not isinstance(risk_level, str) or risk_level not in RISK_LEVELS:
            raise ContractViolation("RISK_LEVEL_INVALID", repr(risk_level))
        price = _number(decision["price"])
        if price is None or price <= 0.0:
            raise ContractViolation("PRICE_INVALID", repr(decision["price"]))
        if not isinstance(decision["metadata"], dict):
            raise ContractViolation("METADATA_INVALID", type(decision["metadata"]).__name__)

        stamp = decision["created_at"]
        try:
            created_at = datetime.fromisoformat(stamp) if isinstance(stamp, str) else None
        except ValueError:
            created_at = None
        if created_at is None or created_at.utcoffset() is None:
            raise ContractViolation("CREATED_AT_INVALID", repr(stamp))
        if now - created_at > MAX_DECISION_AGE:
            raise ContractViolation("DECISION_STALE", f"created_at {stamp} is older than {MAX_DECISION_AGE}")
        if created_at - now > MAX_CLOCK_SKEW:
            raise ContractViolation("DECISION_FROM_FUTURE", f"created_at {stamp} is after {now.isoformat()}")

        return cls(
            action=action,
            symbol=symbol,
            confidence=confidence,
            strategy=decision["strategy"],
            risk_level=risk_level,
            price=price,
            created_at=created_at,
        )
