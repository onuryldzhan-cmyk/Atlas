"""
Atlas AI Agent Fusion Engine v10.0

Multi intelligence voting system.

Responsibilities:

- Collect independent intelligence signals
- Normalize agent scores
- Weighted voting
- Generate fusion result

Agents:

Technical
Momentum
Risk
Macro
Sentiment


Atlas Brain only orchestrates.

"""


from __future__ import annotations


from dataclasses import dataclass
from typing import Dict





# =====================================================
# RESULT MODEL
# =====================================================


@dataclass
class FusionResult:


    action: str


    confidence: float


    scores: Dict



    def to_dict(self):

        return {


            "action":
                self.action,


            "confidence":
                round(
                    self.confidence,
                    3
                ),


            "scores":
                self.scores

        }





# =====================================================
# AGENT FUSION ENGINE
# =====================================================



class AgentFusion:



    VERSION = "10.0"



    WEIGHTS = {


        "technical":
            0.40,


        "momentum":
            0.20,


        "risk":
            0.20,


        "macro":
            0.10,


        "sentiment":
            0.10

    }





    def __init__(
        self,
        config=None
    ):


        self.config = config or {}



        print(
            "[AGENTS] Agent Fusion Engine v10.0 initialized"
        )





    # =================================================
    # ANALYZE AGENTS
    # =================================================



    def evaluate(
        self,
        symbol,
        market_data
    ):


        signals = {}



        intelligence = {


            "technical":

                market_data.get(
                    "technical_score",
                    0.5
                ),



            "momentum":

                self.calculate_momentum(
                    market_data
                ),



            "risk":

                market_data.get(
                    "risk_score",
                    0.5
                ),



            "macro":

                market_data.get(
                    "macro_score",
                    0.5
                ),



            "sentiment":

                market_data.get(
                    "sentiment_score",
                    0.5
                )

        }




        for name, score in intelligence.items():


            action = self.score_to_action(
                score
            )



            signals[name] = {


                "action":
                    action,


                "score":
                    round(
                        score,
                        3
                    )

            }



            print(

                f"[AGENT] {name}: "
                f"{action} "
                f"{score:.2f}"

            )



        return signals






    # =================================================
    # FUSION
    # =================================================



    def fuse(
        self,
        signals
    ):



        buy = 0

        sell = 0

        hold = 0




        for name, data in signals.items():


            weight = self.WEIGHTS.get(
                name,
                0
            )


            score = data["score"]


            action = data["action"]




            if action == "BUY":


                buy += score * weight



            elif action == "SELL":


                sell += (1-score) * weight



            else:


                hold += 0.5 * weight






        total = (

            buy +

            sell +

            hold

        )



        if total == 0:


            return FusionResult(

                action="HOLD",

                confidence=0,

                scores={}

            )





        scores = {


            "BUY":

                round(
                    buy/total,
                    3
                ),



            "SELL":

                round(
                    sell/total,
                    3
                ),



            "HOLD":

                round(
                    hold/total,
                    3
                )

        }



        action=max(

            scores,

            key=scores.get

        )



        confidence=scores[action]



        return FusionResult(

            action=action,

            confidence=confidence,

            scores=scores

        )






    # =================================================
    # HELPERS
    # =================================================



    def score_to_action(
        self,
        score
    ):



        if score >= 0.60:


            return "BUY"



        elif score <= 0.40:


            return "SELL"



        return "HOLD"






    def calculate_momentum(
        self,
        market_data
    ):



        rsi = market_data.get(
            "rsi",
            50
        )


        trend = market_data.get(
            "trend",
            "SIDEWAYS"
        )



        score=0.5




        if trend=="BULLISH":


            score +=0.20




        elif trend=="BEARISH":


            score -=0.20





        if rsi <35:


            score +=0.10




        elif rsi>70:


            score -=0.10





        return max(

            0,

            min(

                score,

                1

            )

        )