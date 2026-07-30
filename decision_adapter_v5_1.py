"""
============================================================
ATLAS AI DECISION ADAPTER v5.1
============================================================

Canonical Decision Normalization Layer

Responsibilities
----------------
- Convert dictionaries, dataclasses and ordinary objects
- Normalize Python Enum decision values
- Support legacy and nested decision field names
- Normalize confidence into percentage scale
- Preserve decision metadata
- Produce one canonical Atlas decision schema

============================================================
"""

from __future__ import annotations

import logging

from dataclasses import asdict, is_dataclass
from datetime import UTC, datetime
from enum import Enum
from typing import Any


logger = logging.getLogger(
    "AtlasAI.DecisionAdapter"
)


class DecisionAdapter:

    VERSION = "5.1"
    NAME = "DecisionAdapter"

    ACTION_ALIASES = {
        "BUY": "BUY",
        "LONG": "BUY",
        "OPEN_LONG": "BUY",
        "ENTER_LONG": "BUY",
        "SELL": "SELL",
        "SHORT": "SELL",
        "OPEN_SHORT": "SELL",
        "ENTER_SHORT": "SELL",
        "CLOSE": "SELL",
        "CLOSE_LONG": "SELL",
        "EXIT": "SELL",
        "HOLD": "HOLD",
        "WAIT": "HOLD",
        "NEUTRAL": "HOLD",
        "NONE": "HOLD",
        "NO_ACTION": "HOLD",
        "SKIP": "HOLD",
    }

    CONFIDENCE_KEYS = (
        "confidence",
        "final_confidence",
        "decision_confidence",
        "confidence_score",
        "confidence_percent",
        "confidence_percentage",
        "probability",
        "score",
    )

    def __init__(self) -> None:
        self.converted = 0
        self.failed = 0
        self.errors: list[dict[str, Any]] = []

    @classmethod
    def convert(
        cls,
        decision: Any,
    ) -> dict[str, Any] | None:
        return cls().normalize(
            decision
        )

    def normalize(
        self,
        decision: Any,
    ) -> dict[str, Any] | None:

        try:
            if decision is None:
                return None

            data = self.to_dict(
                decision
            )

            if data is None:
                return None

            result = self.build_schema(
                data
            )

            self.converted += 1

            return result

        except Exception as exc:
            self.failed += 1

            self.errors.append(
                {
                    "time": datetime.now(
                        UTC
                    ).isoformat(),
                    "type": type(
                        exc
                    ).__name__,
                    "error": str(
                        exc
                    ),
                }
            )

            logger.exception(
                "Decision normalization failed"
            )

            return None

    @staticmethod
    def to_dict(
        decision: Any,
    ) -> dict[str, Any] | None:

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
                return converted

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
            "Unsupported decision type: %s",
            type(
                decision
            ).__name__,
        )

        return None

    def build_schema(
        self,
        data: dict[str, Any],
    ) -> dict[str, Any]:

        existing_metadata = data.get(
            "metadata",
            {},
        )

        if not isinstance(
            existing_metadata,
            dict,
        ):
            existing_metadata = {
                "original_metadata": repr(
                    existing_metadata
                )
            }

        metadata = dict(
            existing_metadata
        )

        metadata.update(
            {
                "adapter_version": self.VERSION,
                "source": self.NAME,
                "normalized_at": datetime.now(
                    UTC
                ).isoformat(),
                "source_fields": sorted(
                    str(key)
                    for key in data.keys()
                ),
            }
        )

        return {
            "action": self.get_action(
                data
            ),
            "symbol": self.get_symbol(
                data
            ),
            "confidence": self.get_confidence(
                data
            ),
            "strategy": str(
                data.get(
                    "strategy",
                    data.get(
                        "strategy_name",
                        "Atlas",
                    ),
                )
            ),
            "risk_level": self.get_risk_level(
                data
            ),
            "price": self.get_price(
                data
            ),
            "created_at": str(
                data.get(
                    "created_at",
                    data.get(
                        "timestamp",
                        datetime.now(
                            UTC
                        ).isoformat(),
                    ),
                )
            ),
            "metadata": metadata,
        }

    def get_action(
        self,
        data: dict[str, Any],
    ) -> str:

        raw_action = self._first_value(
            data,
            (
                "action",
                "decision",
                "signal",
                "side",
                "final_action",
                "final_decision",
                "recommendation",
            ),
            default="HOLD",
        )

        action = self._normalize_action_value(
            raw_action
        )

        normalized = self.ACTION_ALIASES.get(
            action
        )

        if normalized is not None:
            return normalized

        logger.warning(
            "Unknown decision action normalized to HOLD: %r",
            raw_action,
        )

        return "HOLD"

    @staticmethod
    def _normalize_action_value(
        value: Any,
    ) -> str:

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

        elif hasattr(
            value,
            "value",
        ):
            possible_value = getattr(
                value,
                "value",
                None,
            )

            if isinstance(
                possible_value,
                str,
            ):
                value = possible_value

        action = str(
            value
        ).strip().upper()

        if "." in action:
            action = action.rsplit(
                ".",
                maxsplit=1,
            )[-1]

        if ":" in action:
            action = action.split(
                ":",
                maxsplit=1,
            )[0]

        return action.strip(
            " <>\"'"
        )

    @staticmethod
    def get_symbol(
        data: dict[str, Any],
    ) -> str:

        for key in (
            "symbol",
            "asset",
            "ticker",
        ):
            symbol = data.get(
                key
            )

            if symbol:
                return str(
                    symbol
                ).strip().upper()

        for container_key in (
            "order",
            "market_state",
            "market_data",
        ):
            container = data.get(
                container_key,
                {},
            )

            if isinstance(
                container,
                dict,
            ):
                symbol = container.get(
                    "symbol"
                )

                if symbol:
                    return str(
                        symbol
                    ).strip().upper()

        return "UNKNOWN"

    @classmethod
    def get_confidence(
        cls,
        data: dict[str, Any],
    ) -> float:
        """
        Locate confidence in flat, nested, dataclass or object formats.

        Examples:
            0.706
            70.6
            "70.6%"
            {"score": 0.706}
            {"value": 70.6}
            {"confidence": {"final": 70.6}}
        """

        raw_value = cls._find_confidence_value(
            data
        )

        return cls._confidence_to_percent(
            raw_value
        )

    @classmethod
    def _find_confidence_value(
        cls,
        source: Any,
        depth: int = 0,
    ) -> Any:

        if depth > 5 or source is None:
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

        if is_dataclass(
            source
        ):
            source = asdict(
                source
            )

        elif (
            not isinstance(
                source,
                dict,
            )
            and hasattr(
                source,
                "__dict__",
            )
        ):
            source = vars(
                source
            )

        if not isinstance(
            source,
            dict,
        ):
            return None

        # First priority: known confidence fields.
        for key in cls.CONFIDENCE_KEYS:
            if key not in source:
                continue

            value = source.get(
                key
            )

            if value is None:
                continue

            if isinstance(
                value,
                dict,
            ):
                for nested_key in (
                    "value",
                    "score",
                    "percent",
                    "percentage",
                    "final",
                    "combined",
                    "overall",
                    "adjusted",
                    "weighted",
                    "result",
                ):
                    if nested_key in value:
                        candidate = cls._find_confidence_value(
                            value[
                                nested_key
                            ],
                            depth + 1,
                        )

                        if candidate is not None:
                            return candidate

            candidate = cls._find_confidence_value(
                value,
                depth + 1,
            )

            if candidate is not None:
                return candidate

        # Second priority: likely decision result containers.
        for container_key in (
            "result",
            "decision_result",
            "final_result",
            "decision_data",
            "analysis",
            "output",
            "payload",
            "details",
            "metrics",
            "scores",
        ):
            if container_key not in source:
                continue

            candidate = cls._find_confidence_value(
                source[
                    container_key
                ],
                depth + 1,
            )

            if candidate is not None:
                return candidate

        return None

    @staticmethod
    def _confidence_to_percent(
        value: Any,
    ) -> float:

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

    @staticmethod
    def get_price(
        data: dict[str, Any],
    ) -> float:

        for key in (
            "price",
            "entry_price",
            "market_price",
            "current_price",
        ):
            try:
                price = float(
                    data.get(
                        key,
                        0,
                    )
                )

                if price > 0:
                    return price

            except (
                TypeError,
                ValueError,
            ):
                continue

        for container_key in (
            "market_state",
            "market_data",
            "order",
        ):
            container = data.get(
                container_key,
                {},
            )

            if not isinstance(
                container,
                dict,
            ):
                continue

            try:
                price = float(
                    container.get(
                        "price",
                        0,
                    )
                )

                if price > 0:
                    return price

            except (
                TypeError,
                ValueError,
            ):
                continue

        return 0.0

    @staticmethod
    def get_risk_level(
        data: dict[str, Any],
    ) -> str:

        value = data.get(
            "risk_level",
            data.get(
                "risk",
                "MEDIUM",
            ),
        )

        if isinstance(
            value,
            Enum,
        ):
            value = value.value

        risk_level = str(
            value
        ).strip().upper()

        if "." in risk_level:
            risk_level = risk_level.rsplit(
                ".",
                maxsplit=1,
            )[-1]

        if risk_level not in {
            "LOW",
            "MEDIUM",
            "HIGH",
            "CRITICAL",
        }:
            return "MEDIUM"

        return risk_level

    @staticmethod
    def _first_value(
        data: dict[str, Any],
        keys: tuple[str, ...],
        *,
        default: Any = None,
    ) -> Any:

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

    def status(
        self,
    ) -> dict[str, Any]:

        return {
            "name": self.NAME,
            "version": self.VERSION,
            "converted": self.converted,
            "failed": self.failed,
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

    def __repr__(
        self,
    ) -> str:

        return (
            f"<{self.NAME} "
            f"version={self.VERSION} "
            f"converted={self.converted} "
            f"failed={self.failed}>"
        )
