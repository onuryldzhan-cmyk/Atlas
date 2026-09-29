"""
ATLAS REASONING ENGINE v2.1

Advanced market reasoning layer.

Responsibilities:

- Evaluate technical structure
- Evaluate macro environment
- Evaluate sentiment
- Generate normalized BUY / SELL / HOLD decisions
- Provide confidence scoring
- Store reasoning history

"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import List, Dict
from enum import Enum
import json
import os

from atlas_security import sanitize_sensitive_mapping

import logging as _logging

# Diagnostics go to the log, not stdout (registry v5.50: 20 coins x every cycle flooded the console).
_log = _logging.getLogger(__name__)


class DecisionType(Enum):

    BUY = "buy"
    SELL = "sell"
    HOLD = "hold"


class ConfidenceLevel(Enum):

    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"



@dataclass
class ReasoningStep:

    step_id: int

    description: str

    evidence: List[str] = field(
        default_factory=list
    )

    confidence: ConfidenceLevel = (
        ConfidenceLevel.MEDIUM
    )

    timestamp: datetime = field(
        default_factory=datetime.now
    )



@dataclass
class Decision:

    decision_type: DecisionType

    symbol: str

    confidence: float = 0.0

    reasoning_steps: List[ReasoningStep] = field(
        default_factory=list
    )

    risk_assessment: Dict = field(
        default_factory=dict
    )

    timestamp: datetime = field(
        default_factory=datetime.now
    )


    def to_dict(self):

        return sanitize_sensitive_mapping(
            {

                "decision_type":
                    self.decision_type.value,

                "symbol":
                    self.symbol,

                "confidence":
                    self.confidence,

                "reasoning_steps":
                [

                    {

                        "step_id":
                            x.step_id,

                        "description":
                            x.description,

                        "evidence":
                            x.evidence,

                        "confidence":
                            x.confidence.value

                    }

                    for x in self.reasoning_steps

                ],

                "risk_assessment":
                    self.risk_assessment,

                "timestamp":
                    self.timestamp.isoformat()

            }
        )



class AtlasReasoningEngine:


    def __init__(
        self,
        data_dir="memory_data"
    ):


        self.data_dir = data_dir


        self.decisions = []


        self._ensure_data_dir()


        _log.debug(
            "[REASONING] Atlas Reasoning Engine v2.1 baslatildi"
        )



    def _ensure_data_dir(self):

        if not os.path.exists(
            self.data_dir
        ):

            os.makedirs(
                self.data_dir
            )
    # ==================================================
    # MAIN MARKET ANALYSIS
    # ==================================================

    def analyze_market(
        self,
        symbol: str,
        technical_data: Dict,
        macro_data: Dict = None,
        sentiment_data: Dict = None
    ):


        steps = []

        total_score = 0.0


        # ----------------------------------
        # TECHNICAL ANALYSIS
        # ----------------------------------

        technical_score = self._evaluate_technical(
            technical_data
        )


        steps.append(

            ReasoningStep(

                step_id=1,

                description=
                    "Technical market evaluation",

                evidence=[

                    f"RSI: {technical_data.get('rsi')}",

                    f"MACD: {technical_data.get('macd')}",

                    f"Trend: {technical_data.get('trend')}"

                ],

                confidence=

                    ConfidenceLevel.HIGH

                    if technical_score >= 0.7

                    else ConfidenceLevel.MEDIUM

            )

        )


        # Teknik analiz ana ağırlık

        total_score += (
            technical_score * 0.60
        )



        # ----------------------------------
        # MACRO ANALYSIS
        # ----------------------------------

        if macro_data:


            macro_score = self._evaluate_macro(
                macro_data
            )


            steps.append(

                ReasoningStep(

                    step_id=2,

                    description=
                        "Macro environment evaluation",

                    evidence=[

                        f"FED: {macro_data.get('fed_policy')}",

                        f"Inflation: {macro_data.get('inflation')}"

                    ]

                )

            )


            total_score += (
                macro_score * 0.20
            )


        else:


            total_score += 0.10




        # ----------------------------------
        # SENTIMENT ANALYSIS
        # ----------------------------------

        if sentiment_data:


            sentiment_score = self._evaluate_sentiment(
                sentiment_data
            )


            steps.append(

                ReasoningStep(

                    step_id=3,

                    description=
                        "Market sentiment evaluation",

                    evidence=[

                        f"FearGreed: {sentiment_data.get('fear_greed')}"

                    ]

                )

            )


            total_score += (
                sentiment_score * 0.20
            )


        else:


            total_score += 0.10




        # Normalize

        total_score = max(

            0.0,

            min(

                total_score,

                1.0

            )

        )



        decision_type = self._determine_decision(

            total_score,

            technical_data

        )




        decision = Decision(

            decision_type=
                decision_type,

            symbol=
                symbol,

            confidence=
                round(
                    total_score,
                    2
                ),

            reasoning_steps=
                steps,

            risk_assessment={

                "max_loss_pct":
                    2,

                "position_size_pct":
                    round(
                        total_score * 15,
                        2
                    ),

                "timeframe":
                    "intraday"

            }

        )



        self.decisions.append(
            decision
        )



        _log.debug(

            f"[REASONING] {symbol} -> "
            f"{decision_type.value.upper()} "
            f"confidence={total_score:.2f}"

        )


        return decision





    # ==================================================
    # TECHNICAL SCORE
    # ==================================================

    def _evaluate_technical(
        self,
        data: Dict
    ):


        score = 0.50



        rsi = data.get(
            "rsi",
            50
        )


        macd = data.get(
            "macd",
            0
        )


        trend = str(

            data.get(
                "trend",
                ""

            )

        ).lower()



        # RSI

        if rsi < 35:

            score += 0.15


        elif rsi > 70:

            score -= 0.15



        # MACD

        if macd > 0:

            score += 0.10


        elif macd < 0:

            score -= 0.10



        # Trend

        if trend == "bullish":

            score += 0.20


        elif trend == "bearish":

            score -= 0.20




        return max(

            0,

            min(

                score,

                1

            )

        )
    # ==================================================
    # MACRO SCORE
    # ==================================================

    def _evaluate_macro(
        self,
        data: Dict
    ):


        score = 0.50


        fed = str(

            data.get(
                "fed_policy",
                "neutral"
            )

        ).lower()



        inflation = data.get(
            "inflation",
            2
        )



        if fed == "dovish":

            score += 0.20


        elif fed == "hawkish":

            score -= 0.20




        if inflation > 5:

            score -= 0.15



        elif inflation < 3:

            score += 0.10




        return max(

            0,

            min(

                score,

                1

            )

        )




    # ==================================================
    # SENTIMENT SCORE
    # ==================================================

    def _evaluate_sentiment(
        self,
        data: Dict
    ):


        score = 0.50


        fear_greed = data.get(
            "fear_greed",
            50
        )



        # Extreme fear = opportunity

        if fear_greed < 25:

            score += 0.20



        elif fear_greed > 80:

            score -= 0.20



        return max(

            0,

            min(

                score,

                1

            )

        )




    # ==================================================
    # DECISION ENGINE
    # ==================================================

    def _determine_decision(
        self,
        score: float,
        technical_data: Dict
    ):


        trend = str(

            technical_data.get(
                "trend",
                ""
            )

        ).lower()



        if score >= 0.65:


            return DecisionType.BUY



        if score <= 0.35:


            return DecisionType.SELL




        # Trend destekliyorsa HOLD yerine BUY adayı

        if (

            trend == "bullish"

            and score >= 0.55

        ):

            return DecisionType.BUY




        if (

            trend == "bearish"

            and score <= 0.45

        ):

            return DecisionType.SELL




        return DecisionType.HOLD




    # ==================================================
    # HISTORY
    # ==================================================

    def get_decision_history(
        self,
        symbol=None
    ):


        if symbol:


            return [

                d

                for d in self.decisions

                if d.symbol == symbol

            ]



        return self.decisions




    # ==================================================
    # SAVE
    # ==================================================

    def save(
        self,
        filepath=None
    ):


        if filepath is None:

            filepath = os.path.join(

                self.data_dir,

                "atlas_reasoning.json"

            )



        data = {


            "decisions":

                [

                    d.to_dict()

                    for d in self.decisions

                ],


            "saved":

                datetime.now().isoformat()

        }



        with open(

            filepath,

            "w",

            encoding="utf-8"

        ) as f:


            json.dump(

                data,

                f,

                indent=2,

                ensure_ascii=False

            )



        _log.debug(

            f"[REASONING] Saved {filepath}"

        )




    # ==================================================
    # LOAD
    # ==================================================

    def load(
        self,
        filepath=None
    ):


        if filepath is None:


            filepath = os.path.join(

                self.data_dir,

                "atlas_reasoning.json"

            )



        try:


            with open(

                filepath,

                "r",

                encoding="utf-8"

            ) as f:


                json.load(f)



            _log.debug(

                f"[REASONING] Loaded {filepath}"

            )


            return True



        except FileNotFoundError:


            return False





# ==================================================
# DIRECT TEST
# ==================================================

if __name__ == "__main__":


    _log.debug("=" * 60)

    _log.debug(
        "ATLAS REASONING ENGINE v2.1 TEST"
    )

    _log.debug("=" * 60)



    engine = AtlasReasoningEngine()



    result = engine.analyze_market(

        "BTCUSDT",

        {

            "rsi": 32,

            "macd": 100,

            "trend": "BULLISH"

        },

        {

            "fed_policy":
                "dovish",

            "inflation":
                2.2

        },

        {

            "fear_greed":
                20

        }

    )



    print()

    _log.debug(

        result.to_dict()

    )


    engine.save()
