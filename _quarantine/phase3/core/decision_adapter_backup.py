"""
============================================================
ATLAS AI DECISION ADAPTER v5.0
============================================================

Canonical Decision Normalization Layer

Responsibilities
----------------
- Convert AI decision objects into dictionaries
- Support dictionaries, dataclasses and ordinary objects
- Normalize Python Enum decision values
- Support legacy decision field names
- Normalize action aliases
- Normalize confidence into percentage scale
- Preserve decision metadata
- Produce one canonical Atlas decision schema

Canonical Output
----------------
{
    "action": "BUY | SELL | HOLD",
    "symbol": "BTCUSDT",
    "confidence": 70.6,
    "strategy": "Atlas",
    "risk_level": "MEDIUM",
    "price": 65000.0,
    "created_at": "...",
    "metadata": {...}
}

Flow
----
Atlas Brain
    |
Decision Builder
    |
Decision Adapter
    |
Risk Engine
    |
Execution Manager

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
    """
    Convert heterogeneous Atlas Brain outputs into one stable schema.
    """

    VERSION = "5.0"
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

    def __init__(self) -> None:
        self.converted = 0
        self.failed = 0
        self.errors: list[dict[str, Any]] = []

    # =========================================================
    # PUBLIC CONVERSION
    # =========================================================

    @classmethod
    def convert(
        cls,
        decision: Any,
    ) -> dict[str, Any] | None:
        """
        Normalize one decision using a temporary adapter instance.
        """

        return cls().normalize(
            decision
        )

    # =========================================================
    # NORMALIZATION
    # =========================================================

    def normalize(
        self,
        decision: Any,
    ) -> dict[str, Any] | None:
        """
        Normalize a Brain decision into the canonical Atlas schema.
        """

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

    # =========================================================
    # OBJECT CONVERSION
    # =========================================================

    @staticmethod
    def to_dict(
        decision: Any,
    ) -> dict[str, Any] | None:
        """
        Convert supported decision objects into a dictionary.
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

    # =========================================================
    # CANONICAL SCHEMA
    # =========================================================

    def build_schema(
        self,
        data: dict[str, Any],
    ) -> dict[str, Any]:
        """
        Build the canonical Atlas decision dictionary.
        """

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

    # =========================================================
    # ACTION
    # =========================================================

    def get_action(
        self,
        data: dict[str, Any],
    ) -> str:
        """
        Extract and normalize the decision action.

        Supported examples:
        - DecisionAction.BUY
        - "DecisionAction.BUY"
        - "BUY"
        - "LONG"
        - {"decision": "SELL"}
        - {"signal": "HOLD"}
        """

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
        """
        Convert Enum and dotted action representations into plain text.
        """

        if isinstance(
            value,
            Enum,
        ):
            enum_value = value.value

            if isinstance(
                enum_value,
                str,
            ):
                value = enum_value
            else:
                value = value.name

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

        # Handles:
        # DecisionAction.BUY
        # Action.SELL
        # atlas.decision.HOLD
        if "." in action:
            action = action.rsplit(
                ".",
                maxsplit=1,
            )[-1]

        # Handles:
        # <DecisionAction.BUY: 'BUY'>
        if ":" in action:
            action = action.split(
                ":",
                maxsplit=1,
            )[0]

        action = action.strip(
            " <>\"'"
        )

        return action

    # =========================================================
    # SYMBOL
    # =========================================================

    @staticmethod
    def get_symbol(
        data: dict[str, Any],
    ) -> str:
        """
        Extract and normalize the trading symbol.
        """

        symbol = data.get(
            "symbol"
        )

        if symbol:
            return str(
                symbol
            ).strip().upper()

        order = data.get(
            "order",
            {},
        )

        if isinstance(
            order,
            dict,
        ):
            symbol = order.get(
                "symbol"
            )

            if symbol:
                return str(
                    symbol
                ).strip().upper()

        market_state = data.get(
            "market_state",
            {},
        )

        if isinstance(
            market_state,
            dict,
        ):
            symbol = market_state.get(
                "symbol"
            )

            if symbol:
                return str(
                    symbol
                ).strip().upper()

        return "UNKNOWN"

    # =========================================================
    # CONFIDENCE
    # =========================================================

    @staticmethod
    def get_confidence(
        data: dict[str, Any],
    ) -> float:
        """
        Normalize confidence to the 0-100 percentage scale.

        Supported examples:
        - 0.706 -> 70.6
        - 70.6  -> 70.6
        - "70.6%" -> 70.6
        """

        value = data.get(
            "confidence",
            data.get(
                "confidence_score",
                data.get(
                    "probability",
                    0,
                ),
            ),
        )

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

    # =========================================================
    # PRICE
    # =========================================================

    @staticmethod
    def get_price(
        data: dict[str, Any],
    ) -> float:
        """
        Extract the decision or market price.
        """

        candidates = (
            data.get(
                "price"
            ),
            data.get(
                "entry_price"
            ),
            data.get(
                "market_price"
            ),
        )

        for candidate in candidates:
            try:
                price = float(
                    candidate
                )

                if price > 0:
                    return price

            except (
                TypeError,
                ValueError,
            ):
                continue

        market_state = data.get(
            "market_state",
            {},
        )

        if isinstance(
            market_state,
            dict,
        ):
            try:
                return max(
                    0.0,
                    float(
                        market_state.get(
                            "price",
                            0,
                        )
                    ),
                )

            except (
                TypeError,
                ValueError,
            ):
                pass

        return 0.0

    # =========================================================
    # RISK LEVEL
    # =========================================================

    @staticmethod
    def get_risk_level(
        data: dict[str, Any],
    ) -> str:
        """
        Extract and normalize decision risk level.
        """

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
            risk_level = "MEDIUM"

        return risk_level

    # =========================================================
    # FIELD HELPER
    # =========================================================

    @staticmethod
    def _first_value(
        data: dict[str, Any],
        keys: tuple[str, ...],
        *,
        default: Any = None,
    ) -> Any:
        """
        Return the first present, non-null dictionary value.
        """

        for key in keys:
            if key in data and data[
                key
            ] is not None:
                return data[
                    key
                ]

        return default

    # =========================================================
    # STATUS
    # =========================================================

    def status(self) -> dict[str, Any]:
        """
        Return adapter diagnostics.
        """

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

    # =========================================================
    # REPRESENTATION
    # =========================================================

    def __repr__(self) -> str:
        return (
            f"<{self.NAME} "
            f"version={self.VERSION} "
            f"converted={self.converted} "
            f"failed={self.failed}>"
        )