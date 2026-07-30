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


        if isinstance(
            self.risk_level,
            str
        ):

            self.risk_level = RiskLevel(
                self.risk_level.upper()
            )


        self.confidence = max(

            0,

            min(

                float(self.confidence),

                100

            )

        )





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

            self.risk_level = RiskLevel(
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