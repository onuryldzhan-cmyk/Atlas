"""
Atlas AI Decision Model v7.0

Central decision contract.

Features:
- Dataclass based decision object
- Dictionary compatibility
- Execution layer ready
- Serialization support

"""

from __future__ import annotations


from dataclasses import dataclass, field
from enum import Enum
from datetime import datetime, timezone
from typing import Dict, Any





# =====================================================
# ACTION TYPES
# =====================================================


class DecisionAction(Enum):

    BUY = "BUY"
    SELL = "SELL"
    CLOSE = "CLOSE"
    HOLD = "HOLD"
    WAIT = "WAIT"





# =====================================================
# RISK TYPES
# =====================================================


class RiskLevel(Enum):

    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


_RISK_LEVEL_VALUES = frozenset(member.value for member in RiskLevel)


def _coerce_risk_level(value: Any) -> RiskLevel:
    """Canonicalize a raw ``risk_level`` input into the strict RiskLevel taxonomy.

    ``Decision.risk_level`` is a strict analytical domain field: every
    successfully constructed/mutated Decision must hold a real ``RiskLevel``
    member. Enum inputs (e.g. ``RiskCategory``, ``RiskBucket``) are trusted
    only when their semantic value resolves to a genuine RiskLevel member;
    arbitrary objects are never trusted merely because they expose ``.value``.
    """

    if isinstance(value, RiskLevel):
        return value

    if isinstance(value, Enum):
        raw = value.value if isinstance(value.value, str) else value.name
        if raw in _RISK_LEVEL_VALUES:
            return RiskLevel(raw)
        raise ValueError(
            f"Unsupported risk_level enum value: {value!r}"
        )

    if isinstance(value, str):
        normalized = value.upper()
        if normalized in _RISK_LEVEL_VALUES:
            return RiskLevel(normalized)
        raise ValueError(
            f"Unsupported risk_level string: {value!r}"
        )

    raise TypeError(
        f"risk_level must be a RiskLevel, a recognized Enum, or a string; "
        f"got {type(value).__name__}"
    )





# =====================================================
# DECISION OBJECT
# =====================================================


@dataclass
class Decision:


    action: DecisionAction


    symbol: str


    confidence: float


    reasoning: str



    risk_level: RiskLevel = RiskLevel.MEDIUM



    strategy: str = "Atlas"



    created_at: datetime = field(

        default_factory=lambda:

        datetime.now(timezone.utc)

    )



    metadata: Dict[str, Any] = field(

        default_factory=dict

    )





    # =================================================
    # NORMALIZATION
    # =================================================


    def __post_init__(self):


        if isinstance(
            self.action,
            str
        ):

            self.action = DecisionAction(
                self.action.upper()
            )


        self.risk_level = _coerce_risk_level(
            self.risk_level
        )


        # Clamp bounds are float literals, not int, so the result stays
        # float regardless of which operand max()/min() select: mixing
        # an int literal into either call silently reverts a value that
        # was just cast to float back to int whenever that literal is
        # the one selected (e.g. max(0, 0.0) -> 0, not 0.0).
        self.confidence = max(

            0.0,

            min(

                float(self.confidence),

                100.0

            )

        )





    # =================================================
    # LIFETIME TYPE INVARIANT (NBF-7)
    # =================================================


    def __setattr__(self, name, value):

        # __post_init__ already routes through _coerce_risk_level; this is
        # the choke point for every *other* write path (ordinary attribute
        # assignment), so the isinstance(risk_level, RiskLevel) invariant
        # holds for the object's entire lifetime, not just at construction.
        if name == "risk_level":
            value = _coerce_risk_level(value)

        super().__setattr__(name, value)


    # =================================================
    # DICT COMPATIBILITY LAYER
    # =================================================


    def __getitem__(self, key):

        return self.to_dict()[key]



    def __setitem__(self, key, value):


        if key == "action":

            self.action = DecisionAction(
                value
            )


        elif key == "risk_level":

            self.risk_level = _coerce_risk_level(
                value
            )


        elif hasattr(
            self,
            key
        ):

            setattr(

                self,

                key,

                value

            )


        else:

            self.metadata[key] = value





    def get(self, key, default=None):


        return self.to_dict().get(

            key,

            default

        )





    # =================================================
    # SIGNAL CHECKS
    # =================================================


    def is_trade_signal(self):

        return self.action in (

            DecisionAction.BUY,

            DecisionAction.SELL

        )





    def is_hold(self):

        return self.action in (

            DecisionAction.HOLD,

            DecisionAction.WAIT

        )





    # =================================================
    # EXECUTION HELPERS
    # =================================================


    def get_position_size(self):

        return self.metadata.get(

            "position_size_pct",

            0

        )



    def get_stop_loss(self):

        return self.metadata.get(

            "stop_loss_pct",

            None

        )



    def get_take_profit(self):

        return self.metadata.get(

            "take_profit_pct",

            None

        )





    # =================================================
    # SERIALIZATION
    # =================================================


    def to_dict(self):


        return {


            "action":

                self.action.value,


            "symbol":

                self.symbol,


            "confidence":

                self.confidence,


            "reasoning":

                self.reasoning,


            "risk_level":

                self.risk_level.value,


            "strategy":

                self.strategy,


            "created_at":

                self.created_at.isoformat(),


            "metadata":

                self.metadata


        }





    def summary(self):


        return (

            f"{self.symbol} | "

            f"{self.action.value} | "

            f"Confidence: "

            f"{self.confidence:.1f}% | "

            f"Risk: "

            f"{self.risk_level.value}"

        )





    def __str__(self):

        return self.summary()