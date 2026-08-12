"""
============================================================
ATLAS AI DECISION ADAPTER v5.2
============================================================

Institutional Decision Normalization Gateway

Purpose
-------
Atlas intelligence components may return decisions as dictionaries,
dataclasses, Enum values, nested structures, or legacy objects.

DecisionAdapter converts these heterogeneous outputs into one stable,
execution-ready contract.

Canonical Decision Contract
---------------------------
{
    "action": "BUY | SELL | HOLD",
    "symbol": "BTCUSDT",
    "confidence": 70.60,
    "strategy": "Atlas",
    "risk_level": "MEDIUM",
    "price": 65000.00,
    "created_at": "UTC ISO-8601",
    "metadata": {...}
}

Responsibilities
----------------
- Normalize dictionaries, dataclasses and Python objects
- Normalize Enum action and risk values
- Resolve legacy and nested field names
- Prioritize final Decision Builder confidence
- Convert confidence from 0-1 or 0-100 scale
- Preserve source metadata
- Produce deterministic execution contracts
- Record conversion errors and diagnostics

Architecture
------------
Atlas Brain
    |
Decision Builder
    |
Decision Adapter
    |
Execution Manager
    |
Risk / Capital / Position / Execution

============================================================
"""

from __future__ import annotations

import logging

from dataclasses import asdict, is_dataclass
from datetime import UTC, datetime
from collections.abc import Mapping
from enum import Enum
from math import isfinite
from typing import Any, ClassVar

from atlas_security import sanitize_sensitive_mapping

from core.execution_models import normalize_risk


logger = logging.getLogger(
    "AtlasAI.DecisionAdapter"
)


class DecisionAdapter:
    """
    Canonical boundary between Atlas intelligence and execution layers.

    No Brain-specific object or Enum value should pass beyond this layer.
    """

    VERSION: ClassVar[str] = "5.2"
    NAME: ClassVar[str] = "DecisionAdapter"

    VALID_ACTIONS: ClassVar[frozenset[str]] = frozenset(
        {
            "BUY",
            "SELL",
            "HOLD",
        }
    )

    ACTION_ALIASES: ClassVar[dict[str, str]] = {
        # BUY
        "BUY": "BUY",
        "LONG": "BUY",
        "OPEN_LONG": "BUY",
        "ENTER_LONG": "BUY",
        "GO_LONG": "BUY",

        # SELL
        "SELL": "SELL",
        "SHORT": "SELL",
        "OPEN_SHORT": "SELL",
        "ENTER_SHORT": "SELL",
        "GO_SHORT": "SELL",
        "CLOSE": "SELL",
        "CLOSE_LONG": "SELL",
        "EXIT": "SELL",

        # HOLD
        "HOLD": "HOLD",
        "WAIT": "HOLD",
        "NEUTRAL": "HOLD",
        "NONE": "HOLD",
        "NO_ACTION": "HOLD",
        "SKIP": "HOLD",
        "PASS": "HOLD",
    }

    VALID_RISK_LEVELS: ClassVar[frozenset[str]] = frozenset(
        {
            "LOW",
            "MEDIUM",
            "HIGH",
            "CRITICAL",
        }
    )

    RISK_KEYS: ClassVar[tuple[str, ...]] = (
        "risk_level",
        "risk",
        "risk_category",
    )

    # Legacy absence default.  Applies only when no risk value is supplied.
    ABSENT_RISK_LEVEL: ClassVar[str] = "MEDIUM"

    # Present-but-unrecognized classification.  Non-executable downstream.
    UNSUPPORTED_RISK_LEVEL: ClassVar[str] = "UNKNOWN"

    # Final Decision Builder confidence values must be checked
    # before intermediate intelligence confidence values.
    CONFIDENCE_KEYS: ClassVar[tuple[str, ...]] = (
        "final_confidence",
        "decision_confidence",
        "execution_confidence",
        "approved_confidence",
        "final_confidence_percentage",
        "final_confidence_percent",
        "confidence_percentage",
        "confidence_percent",
        "confidence_score",
        "confidence",
        "probability",
        "score",
    )

    CONFIDENCE_CONTAINER_KEYS: ClassVar[tuple[str, ...]] = (
        "decision_result",
        "final_result",
        "result",
        "decision_data",
        "output",
        "payload",
        "details",
        "metrics",
        "scores",
        "analysis",
    )

    CONFIDENCE_VALUE_KEYS: ClassVar[tuple[str, ...]] = (
        "final",
        "final_value",
        "decision",
        "approved",
        "adjusted",
        "weighted",
        "combined",
        "overall",
        "percentage",
        "percent",
        "score",
        "value",
        "result",
    )

    ACTION_KEYS: ClassVar[tuple[str, ...]] = (
        "action",
        "decision",
        "signal",
        "side",
        "final_action",
        "final_decision",
        "recommendation",
    )

    SYMBOL_KEYS: ClassVar[tuple[str, ...]] = (
        "symbol",
        "asset",
        "ticker",
        "instrument",
    )

    PRICE_KEYS: ClassVar[tuple[str, ...]] = (
        "price",
        "entry_price",
        "market_price",
        "current_price",
        "last_price",
    )

    def __init__(self) -> None:
        self.converted: int = 0
        self.failed: int = 0
        self.errors: list[dict[str, Any]] = []

    # =========================================================
    # PUBLIC API
    # =========================================================

    @classmethod
    def convert(
        cls,
        decision: Any,
        *,
        phase5_proposal: Any = None,
    ) -> dict[str, Any] | None:
        """
        Convert one decision using a temporary adapter instance.
        """

        return cls().normalize(
            decision,
            phase5_proposal=phase5_proposal,
        )

    def normalize(
        self,
        decision: Any,
        *,
        phase5_proposal: Any = None,
    ) -> dict[str, Any] | None:
        """
        Convert an arbitrary Atlas decision into canonical format.

        ``phase5_proposal`` is an optional, shadow-only advisory record
        (e.g. ``CanonicalDecision.audit_record()`` output). It is never
        used to derive action, confidence, price, or risk_level - it is
        only preserved as opaque metadata under "phase5_proposal".
        """

        try:
            if decision is None:
                logger.warning(
                    "Decision normalization skipped: decision is None"
                )
                return None

            source = self.to_dict(
                decision
            )

            if source is None:
                self.failed += 1
                return None

            normalized = self.build_schema(
                source,
                phase5_proposal=phase5_proposal,
            )

            self.converted += 1

            return normalized

        except Exception as exc:
            self.failed += 1

            self._record_error(
                phase="normalize",
                error=exc,
            )

            logger.exception(
                "Decision normalization failed"
            )

            return None

    # =========================================================
    # OBJECT CONVERSION
    # =========================================================

    @staticmethod
    def to_dict(
        decision: Any,
    ) -> dict[str, Any] | None:
        """
        Convert supported decision formats into a dictionary.
        """

        if isinstance(
            decision,
            dict,
        ):
            return dict(
                decision
            )

        if is_dataclass(
            decision
        ):
            converted = asdict(
                decision
            )

            if isinstance(
                converted,
                dict,
            ):
                return converted

        to_dict_method = getattr(
            decision,
            "to_dict",
            None,
        )

        if callable(
            to_dict_method
        ):
            converted = to_dict_method()

            if isinstance(
                converted,
                dict,
            ):
                return dict(
                    converted
                )

        if hasattr(
            decision,
            "__dict__",
        ):
            return dict(
                vars(
                    decision
                )
            )

        logger.error(
            "Unsupported decision object: %s",
            type(
                decision
            ).__name__,
        )

        return None

    # =========================================================
    # CANONICAL SCHEMA
    # =========================================================

    def build_schema(
        self,
        data: dict[str, Any],
        *,
        phase5_proposal: Any = None,
    ) -> dict[str, Any]:
        """
        Build the execution-ready Atlas decision contract.
        """

        action = self.get_action(
            data
        )

        symbol = self.get_symbol(
            data
        )

        confidence = self.get_confidence(
            data
        )

        price = self.get_price(
            data
        )

        risk_level = self.get_risk_level(
            data
        )

        strategy = self.get_strategy(
            data
        )

        created_at = self.get_created_at(
            data
        )

        metadata = self.build_metadata(
            data=data,
            action=action,
            confidence=confidence,
            phase5_proposal=phase5_proposal,
            raw_risk_level=self.get_raw_risk_level(
                data
            ),
        )

        return {
            "action": action,
            "symbol": symbol,
            "confidence": confidence,
            "strategy": strategy,
            "risk_level": risk_level,
            "price": price,
            "created_at": created_at,
            "metadata": metadata,
        }

    # =========================================================
    # ACTION NORMALIZATION
    # =========================================================

    def get_action(
        self,
        data: dict[str, Any],
    ) -> str:
        """
        Extract and normalize BUY, SELL or HOLD.
        """

        raw_action = self._first_value(
            data=data,
            keys=self.ACTION_KEYS,
            default="HOLD",
        )

        normalized_value = self._normalize_enum_or_string(
            raw_action
        )

        action = self.ACTION_ALIASES.get(
            normalized_value,
            "HOLD",
        )

        if (
            normalized_value
            and normalized_value not in self.ACTION_ALIASES
        ):
            logger.warning(
                "Unknown decision action normalized to HOLD: %r",
                raw_action,
            )

        return action

    # =========================================================
    # SYMBOL NORMALIZATION
    # =========================================================

    def get_symbol(
        self,
        data: dict[str, Any],
    ) -> str:
        """
        Extract and normalize the trading symbol.
        """

        for key in self.SYMBOL_KEYS:
            value = data.get(
                key
            )

            if value:
                return str(
                    value
                ).strip().upper()

        for container_name in (
            "order",
            "market_state",
            "market_data",
            "payload",
        ):
            container = self._as_mapping(
                data.get(
                    container_name
                )
            )

            if container is None:
                continue

            for key in self.SYMBOL_KEYS:
                value = container.get(
                    key
                )

                if value:
                    return str(
                        value
                    ).strip().upper()

        return "UNKNOWN"

    # =========================================================
    # CONFIDENCE NORMALIZATION
    # =========================================================

    @classmethod
    def get_confidence(
        cls,
        data: dict[str, Any],
    ) -> float:
        """
        Extract final decision confidence and return 0-100 percentage.

        Priority:
        1. final_confidence
        2. decision_confidence
        3. execution_confidence
        4. approved_confidence
        5. generic confidence fields
        """

        raw_value = cls._find_confidence_value(
            source=data,
            depth=0,
        )

        return cls._confidence_to_percent(
            raw_value
        )

    @classmethod
    def _find_confidence_value(
        cls,
        source: Any,
        depth: int,
    ) -> Any:
        """
        Search confidence values without confusing unrelated scores.
        """

        if source is None or depth > 6:
            return None

        if isinstance(
            source,
            Enum,
        ):
            return source.value

        if isinstance(
            source,
            (
                int,
                float,
                str,
            ),
        ):
            return source

        mapping = cls._as_mapping(
            source
        )

        if mapping is None:
            return None

        # First priority: exact confidence fields.
        for key in cls.CONFIDENCE_KEYS:
            if key not in mapping:
                continue

            value = mapping.get(
                key
            )

            candidate = cls._extract_confidence_candidate(
                value=value,
                depth=depth + 1,
            )

            if candidate is not None:
                return candidate

        # Second priority: known decision-result containers.
        for container_key in cls.CONFIDENCE_CONTAINER_KEYS:
            if container_key not in mapping:
                continue

            candidate = cls._find_confidence_value(
                source=mapping[
                    container_key
                ],
                depth=depth + 1,
            )

            if candidate is not None:
                return candidate

        return None

    @classmethod
    def _extract_confidence_candidate(
        cls,
        value: Any,
        depth: int,
    ) -> Any:
        """
        Extract a numeric confidence candidate from one field value.
        """

        if value is None or depth > 6:
            return None

        if isinstance(
            value,
            Enum,
        ):
            return value.value

        if isinstance(
            value,
            (
                int,
                float,
                str,
            ),
        ):
            return value

        mapping = cls._as_mapping(
            value
        )

        if mapping is None:
            return None

        for key in cls.CONFIDENCE_VALUE_KEYS:
            if key not in mapping:
                continue

            candidate = cls._extract_confidence_candidate(
                value=mapping[
                    key
                ],
                depth=depth + 1,
            )

            if candidate is not None:
                return candidate

        return cls._find_confidence_value(
            source=mapping,
            depth=depth + 1,
        )

    @staticmethod
    def _confidence_to_percent(
        value: Any,
    ) -> float:
        """
        Convert confidence from 0-1 or 0-100 into bounded percentage.
        """

        if value is None:
            return 0.0

        if isinstance(
            value,
            Enum,
        ):
            value = value.value

        if isinstance(
            value,
            str,
        ):
            value = value.strip().replace(
                "%",
                "",
            )

        try:
            confidence = float(
                value
            )

        except (
            TypeError,
            ValueError,
        ):
            return 0.0

        if not isfinite(
            confidence
        ):
            return 0.0

        if 0 <= confidence <= 1:
            confidence *= 100

        return round(
            max(
                0.0,
                min(
                    confidence,
                    100.0,
                ),
            ),
            2,
        )

    # =========================================================
    # PRICE NORMALIZATION
    # =========================================================

    def get_price(
        self,
        data: dict[str, Any],
    ) -> float:
        """
        Extract a positive market or entry price.
        """

        for key in self.PRICE_KEYS:
            price = self._positive_float(
                data.get(
                    key
                )
            )

            if price is not None:
                return price

        for container_name in (
            "market_state",
            "market_data",
            "order",
            "payload",
        ):
            container = self._as_mapping(
                data.get(
                    container_name
                )
            )

            if container is None:
                continue

            for key in self.PRICE_KEYS:
                price = self._positive_float(
                    container.get(
                        key
                    )
                )

                if price is not None:
                    return price

        return 0.0

    # =========================================================
    # RISK NORMALIZATION
    # =========================================================

    def get_risk_level(
        self,
        data: dict[str, Any],
    ) -> str:
        """
        Extract LOW, MEDIUM, HIGH, CRITICAL or UNKNOWN risk.

        Absence and unsupported values are deliberately different states:

        - no risk field / ``None`` / empty -> ``MEDIUM``
          (frozen legacy compatibility default)
        - present but unsupported value -> ``UNKNOWN``

        An unrecognized classification must not inherit the executable
        ``MEDIUM`` default; downstream admission owns what happens next.
        This layer normalizes syntax only and never grants permission.
        """

        raw_risk = self._first_value(
            data=data,
            keys=self.RISK_KEYS,
            default=None,
        )

        if raw_risk is None:
            return self.ABSENT_RISK_LEVEL

        normalized_value = self._normalize_enum_or_string(
            raw_risk
        )

        if not normalized_value:
            return self.ABSENT_RISK_LEVEL

        # Vocabulary resolution is delegated to the canonical syntactic
        # normalizer so every construction path shares one contract.
        risk_level = normalize_risk(
            normalized_value
        )

        if (
            risk_level == self.UNSUPPORTED_RISK_LEVEL
            and normalized_value != self.UNSUPPORTED_RISK_LEVEL
        ):
            logger.warning(
                "Unsupported decision risk level normalized to %s: %r",
                self.UNSUPPORTED_RISK_LEVEL,
                raw_risk,
            )

        return risk_level

    def get_raw_risk_level(
        self,
        data: dict[str, Any],
    ) -> str | None:
        """
        Return the original risk value when it is present but unsupported.

        Diagnostics only.  It exists so an ``EXTREME`` classification is not
        lost once the canonical value becomes ``UNKNOWN``; it must never be
        consulted for admission.
        """

        raw_risk = self._first_value(
            data=data,
            keys=self.RISK_KEYS,
            default=None,
        )

        if raw_risk is None:
            return None

        if self.get_risk_level(
            data
        ) != self.UNSUPPORTED_RISK_LEVEL:
            return None

        original = str(
            raw_risk
        ).strip()

        if (
            not original
            or original.upper() == self.UNSUPPORTED_RISK_LEVEL
        ):
            return None

        return original

    # =========================================================
    # STRATEGY NORMALIZATION
    # =========================================================

    @staticmethod
    def get_strategy(
        data: dict[str, Any],
    ) -> str:
        """
        Extract the strategy identifier.
        """

        value = data.get(
            "strategy",
            data.get(
                "strategy_name",
                "Atlas",
            ),
        )

        strategy = str(
            value
        ).strip()

        return strategy or "Atlas"

    # =========================================================
    # TIMESTAMP NORMALIZATION
    # =========================================================

    @staticmethod
    def get_created_at(
        data: dict[str, Any],
    ) -> str:
        """
        Preserve an existing timestamp or generate UTC ISO-8601.
        """

        value = data.get(
            "created_at",
            data.get(
                "timestamp"
            ),
        )

        if isinstance(
            value,
            datetime,
        ):
            if value.tzinfo is None:
                value = value.replace(
                    tzinfo=UTC
                )

            return value.astimezone(
                UTC
            ).isoformat()

        if value:
            return str(
                value
            )

        return datetime.now(
            UTC
        ).isoformat()

    # =========================================================
    # METADATA
    # =========================================================

    def build_metadata(
        self,
        *,
        data: dict[str, Any],
        action: str,
        confidence: float,
        phase5_proposal: Any = None,
        raw_risk_level: str | None = None,
    ) -> dict[str, Any]:
        """
        Preserve source metadata and append adapter diagnostics.

        ``raw_risk_level`` is recorded only when an explicit risk value was
        unsupported and therefore normalized to ``UNKNOWN``.  It is a
        diagnostic breadcrumb; no admission decision may read it.
        """

        source_metadata = data.get(
            "metadata",
            {},
        )

        if isinstance(
            source_metadata,
            dict,
        ):
            metadata = dict(
                source_metadata
            )

        else:
            metadata = {
                "original_metadata": repr(
                    source_metadata
                )
            }

        metadata.update(
            {
                "adapter_name": self.NAME,
                "adapter_version": self.VERSION,
                "normalized_at": datetime.now(
                    UTC
                ).isoformat(),
                "normalized_action": action,
                "normalized_confidence": confidence,
                "source_fields": sorted(
                    str(
                        key
                    )
                    for key in data.keys()
                ),
            }
        )

        if raw_risk_level:
            metadata["raw_risk_level"] = raw_risk_level

        shadow_proposal = self._extract_phase5_proposal(
            phase5_proposal
        )

        if shadow_proposal is not None:
            metadata["phase5_proposal"] = shadow_proposal

        return sanitize_sensitive_mapping(
            metadata
        )

    # =========================================================
    # PHASE-5 SHADOW-ONLY ADVISORY METADATA
    # =========================================================

    @staticmethod
    def _extract_phase5_proposal(
        phase5_proposal: Any,
    ) -> dict[str, Any] | None:
        """
        Resolve an opaque Phase-5 advisory record for shadow metadata only.

        This never contributes to action, confidence, price, risk_level,
        sizing, routing, or execution eligibility. Malformed or absent
        input fails safe by returning None (no metadata key is added).
        """

        if phase5_proposal is None:
            return None

        try:
            audit_record = getattr(
                phase5_proposal,
                "audit_record",
                None,
            )

            if callable(
                audit_record
            ):
                record = audit_record()

            else:
                record = phase5_proposal

            if isinstance(
                record,
                dict,
            ):
                return dict(
                    record
                )

            if isinstance(
                record,
                Mapping,
            ):
                return dict(
                    record
                )

            logger.warning(
                "Phase-5 proposal ignored: unsupported type %s",
                type(
                    phase5_proposal
                ).__name__,
            )

            return None

        except Exception:
            logger.exception(
                "Phase-5 proposal extraction failed; ignoring proposal"
            )

            return None

    # =========================================================
    # HELPERS
    # =========================================================

    @staticmethod
    def _normalize_enum_or_string(
        value: Any,
    ) -> str:
        """
        Normalize Enum and dotted values such as DecisionAction.BUY.

        Only genuine ``Enum`` instances receive Enum semantics. Arbitrary
        objects that merely expose a ``.value`` (or ``.name``) attribute are
        never granted Enum extraction: that duck-typed path let a spoofed
        object impersonate a trusted classification (NBF-6). Anything that
        is not an ``Enum`` falls through to plain string representation,
        exactly like any other unsupported value.
        """

        if isinstance(
            value,
            Enum,
        ):
            enum_value = value.value

            value = (
                enum_value
                if isinstance(
                    enum_value,
                    str,
                )
                else value.name
            )

        normalized = str(
            value
        ).strip().upper()

        if "." in normalized:
            normalized = normalized.rsplit(
                ".",
                maxsplit=1,
            )[-1]

        if ":" in normalized:
            normalized = normalized.split(
                ":",
                maxsplit=1,
            )[0]

        return normalized.strip(
            " <>\"'"
        )

    @staticmethod
    def _first_value(
        *,
        data: dict[str, Any],
        keys: tuple[str, ...],
        default: Any,
    ) -> Any:
        """
        Return the first non-null field in priority order.
        """

        for key in keys:
            if (
                key in data
                and data[
                    key
                ] is not None
            ):
                return data[
                    key
                ]

        return default

    @staticmethod
    def _as_mapping(
        value: Any,
    ) -> dict[str, Any] | None:
        """
        Convert a nested value into a dictionary when supported.
        """

        if isinstance(
            value,
            dict,
        ):
            return value

        if is_dataclass(
            value
        ):
            converted = asdict(
                value
            )

            if isinstance(
                converted,
                dict,
            ):
                return converted

        if hasattr(
            value,
            "__dict__",
        ):
            return dict(
                vars(
                    value
                )
            )

        return None

    @staticmethod
    def _positive_float(
        value: Any,
    ) -> float | None:
        """
        Return a finite positive float or None.
        """

        try:
            number = float(
                value
            )

        except (
            TypeError,
            ValueError,
        ):
            return None

        if (
            not isfinite(
                number
            )
            or number <= 0
        ):
            return None

        return number

    # =========================================================
    # ERROR MANAGEMENT
    # =========================================================

    def _record_error(
        self,
        *,
        phase: str,
        error: Exception,
    ) -> None:
        """
        Store bounded adapter diagnostics.
        """

        self.errors.append(
            {
                "timestamp": datetime.now(
                    UTC
                ).isoformat(),
                "phase": phase,
                "type": type(
                    error
                ).__name__,
                "error": str(
                    error
                ),
            }
        )

        if len(
            self.errors
        ) > 100:
            del self.errors[
                :-100
            ]

    # =========================================================
    # HEALTH
    # =========================================================

    def health(
        self,
    ) -> dict[str, Any]:
        """
        Return concise component health information.
        """

        return {
            "healthy": self.failed == 0,
            "version": self.VERSION,
            "converted": self.converted,
            "failed": self.failed,
        }

    # =========================================================
    # STATUS
    # =========================================================

    def status(
        self,
    ) -> dict[str, Any]:
        """
        Return complete adapter diagnostics.
        """

        return {
            "name": self.NAME,
            "version": self.VERSION,
            "converted": self.converted,
            "failed": self.failed,
            "valid_actions": sorted(
                self.VALID_ACTIONS
            ),
            "errors": {
                "count": len(
                    self.errors
                ),
                "latest": (
                    self.errors[-1]
                    if self.errors
                    else None
                ),
            },
        }

    # =========================================================
    # RESET
    # =========================================================

    def reset(
        self,
    ) -> None:
        """
        Reset runtime statistics.
        """

        self.converted = 0
        self.failed = 0
        self.errors.clear()

    # =========================================================
    # REPRESENTATION
    # =========================================================

    def __repr__(
        self,
    ) -> str:
        return (
            f"<{self.NAME} "
            f"version={self.VERSION} "
            f"converted={self.converted} "
            f"failed={self.failed}>"
        )
