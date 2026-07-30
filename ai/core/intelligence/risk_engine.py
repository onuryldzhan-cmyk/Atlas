"""
Atlas AI Risk Engine v10.0

Professional risk calculation layer.

Responsibilities:

- Convert confidence into risk level
- Protect weak decisions
- Calculate dynamic risk score
- Prepare risk metadata
- Separate risk logic from brain

Atlas Brain should never calculate risk directly.

"""


from __future__ import annotations


from dataclasses import dataclass
from enum import Enum



# =====================================================
# RISK TYPES
# =====================================================


class RiskCategory(Enum):

    LOW = "LOW"

    MEDIUM = "MEDIUM"

    HIGH = "HIGH"

    CRITICAL = "CRITICAL"




# =====================================================
# RISK RESULT
# =====================================================


@dataclass
class RiskResult:


    level: RiskCategory


    score: float


    reason: str



    def to_dict(self):

        return {

            "level":
                self.level.value,


            "score":
                round(
                    self.score,
                    3
                ),


            "reason":
                self.reason

        }





# =====================================================
# RISK ENGINE
# =====================================================



class RiskEngine:



    VERSION = "10.0"



    def __init__(
        self,
        config=None
    ):


        self.config = config or {}



        print(
            "[RISK] Atlas Risk Engine v10.0 initialized"
        )





    # =================================================
    # MAIN RISK CALCULATION
    # =================================================


    def calculate(
        self,
        confidence: float,
        volatility: float = 0.5,
        market_health: float = 0.5
    ) -> RiskResult:



        """
        confidence:
            0 - 1


        volatility:
            0 - 1


        market_health:
            0 - 1

        """



        confidence = self._normalize(
            confidence
        )


        volatility = self._normalize(
            volatility
        )


        market_health = self._normalize(
            market_health
        )



        # Risk formula

        risk_score = (

            (1-confidence) * 0.5

            +

            volatility * 0.3

            +

            (1-market_health) * 0.2

        )



        risk_score = round(
            risk_score,
            3
        )



        level = self._classify(
            risk_score
        )



        return RiskResult(

            level=level,


            score=risk_score,


            reason=self._reason(
                level,
                risk_score
            )

        )






    # =================================================
    # CLASSIFICATION
    # =================================================


    def _classify(
        self,
        score
    ):



        if score < 0.25:


            return RiskCategory.LOW



        elif score < 0.50:


            return RiskCategory.MEDIUM



        elif score < 0.75:


            return RiskCategory.HIGH



        else:


            return RiskCategory.CRITICAL





    # =================================================
    # HELPERS
    # =================================================


    def _normalize(
        self,
        value
    ):


        try:

            value=float(value)


        except Exception:


            value=0.5



        return max(

            0,

            min(

                value,

                1

            )

        )





    def _reason(
        self,
        level,
        score
    ):


        return (

            f"Risk classified as "
            f"{level.value} "
            f"with score {score}"

        )