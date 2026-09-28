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
# ADVISORY RISK SCORER
# =====================================================
#
# Renamed from RiskEngine (Package 2A, E1): core.risk_engine.RiskEngine is
# the canonical execution/admission risk authority. This class is the
# intelligence-layer advisory/research risk scorer and must not be confused
# with it. No semantic behavior change.



class AdvisoryRiskScorer:



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

# =====================================================
# REGIME-DERIVED DECISION RISK LEVEL (registry v5.22)
# =====================================================
#
# Owner grant 2026-09-28 ("Evet, kodla"), design in
# governance/ATLAS_RISK_LEVEL_FROM_VOLATILITY_REGIME_PROPOSAL_v1.0.md
# (Phase A = A1 + A2 + Macro cap; A3 deferred).
#
# The decision's risk_level (which selects the canonical RiskEngine bucket)
# comes from the measured market-risk regime, not from confidence:
#
#   regime HIGH, or any missing/unavailable/malformed input  -> HIGH
#   regime NEUTRAL                                          -> MEDIUM
#   regime LOW, but not below the absolute ceiling (A2)     -> MEDIUM
#   regime LOW and below the ceiling, Macro not HOLD/BUY    -> MEDIUM
#   regime LOW and below the ceiling, Macro HOLD/BUY        -> LOW
#
# NB-4: removing any evidence can only raise the level, never lower it.
# The ceilings are pinned here and in registry v5.20 (owner chose p30 of
# 30 days of 1-minute realized volatility, same estimator as
# core/market_risk_regime.py). No config/env: a change needs a governed
# change. A symbol without a pinned ceiling can never be LOW.

LOW_VOLATILITY_CEILINGS = {
    "BTCUSDT": 0.000277,
    "ETHUSDT": 0.000388,
    "BNBUSDT": 0.000340,
    "SOLUSDT": 0.000520,
    "XRPUSDT": 0.000582,
}

_REGIME_TO_LEVEL = {
    "LOW": RiskCategory.LOW,
    "NEUTRAL": RiskCategory.MEDIUM,
    "HIGH": RiskCategory.HIGH,
}

_REGIME_SCORES = {
    RiskCategory.LOW: 0.25,
    RiskCategory.MEDIUM: 0.5,
    RiskCategory.HIGH: 0.75,
}


def _finite_non_negative(value) -> bool:
    import math

    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(value)
        and value >= 0
    )


def regime_risk_result(market_data, symbol) -> RiskResult:
    """Decision risk level from the volatility regime; never raises."""

    def result(level: RiskCategory, reason: str) -> RiskResult:
        return RiskResult(level=level, score=_REGIME_SCORES[level], reason=reason)

    try:
        if not isinstance(market_data, dict):
            return result(RiskCategory.HIGH, "REGIME_INPUT_MALFORMED")

        status = market_data.get("evidence_status")
        status = status if isinstance(status, dict) else {}
        evidence = market_data.get("market_risk_evidence")

        if status.get("market_risk") != "AVAILABLE" or not isinstance(evidence, dict):
            return result(RiskCategory.HIGH, "REGIME_UNAVAILABLE")

        regime = evidence.get("regime")
        level = _REGIME_TO_LEVEL.get(regime) if isinstance(regime, str) else None
        if level is None:
            return result(RiskCategory.HIGH, "REGIME_UNKNOWN")

        if level is not RiskCategory.LOW:
            return result(level, f"REGIME_{regime}")

        # A2: absolute ceiling for this symbol.
        ceiling = LOW_VOLATILITY_CEILINGS.get(str(symbol or "").strip().upper())
        current = evidence.get("realized_volatility")
        if ceiling is None or not _finite_non_negative(current) or not current < ceiling:
            return result(RiskCategory.MEDIUM, "REGIME_LOW_ABOVE_ABSOLUTE_CEILING")

        # Macro cap: only an available, non-SELL Macro keeps LOW.
        macro = market_data.get("macro_evidence")
        macro_vote = macro.get("vote") if isinstance(macro, dict) else None
        if status.get("macro") != "AVAILABLE" or macro_vote not in ("HOLD", "BUY"):
            return result(RiskCategory.MEDIUM, "REGIME_LOW_MACRO_CAP")

        return result(RiskCategory.LOW, "REGIME_LOW_BELOW_CEILING_MACRO_OK")

    except Exception:
        return result(RiskCategory.HIGH, "REGIME_EVALUATION_FAILED")
