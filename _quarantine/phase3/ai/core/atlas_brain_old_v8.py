"""
Atlas AI Intelligence Brain v8.0

Central intelligence decision engine.

Pipeline:

Market Data
        |
        v
World Model
        |
        v
Multi Agent System
        |
        v
Weighted Intelligence Fusion
        |
        v
Decision Object
        |
        v
Execution Manager


Responsibilities:

- Analyze market state
- Combine multiple intelligence sources
- Calculate confidence
- Generate normalized decisions
- Protect against weak signals
- Provide learning feedback

"""


from __future__ import annotations


from datetime import datetime
from typing import Dict, List


from core.decision import (
    Decision,
    DecisionAction,
    RiskLevel
)



# =====================================================
# MODULE LOADING
# =====================================================


MODULES_AVAILABLE = False



try:

    from .atlas_memory_core import (
        AtlasMemoryCore
    )

    from .atlas_reasoning_engine import (
        AtlasReasoningEngine
    )

    from .atlas_world_model import (
        AtlasWorldModel
    )

    from .atlas_multi_agent import (
        AtlasMultiAgent
    )


    MODULES_AVAILABLE = True



except Exception as e:


    print(
        f"[ATLAS BRAIN] Module load error {e}"
    )





# =====================================================
# ATLAS INTELLIGENCE BRAIN
# =====================================================



class AtlasBrain:


    """
    Atlas Intelligence Core v8.0

    Generates decisions only.

    Execution is external.
    """



    # minimum confidence for trade

    MIN_TRADE_CONFIDENCE = 0.55



    # Intelligence weights

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



        self.status = (
            "initializing"
        )



        self.session_id = (

            datetime.now()
            .strftime(
                "atlas_%Y%m%d_%H%M%S"
            )

        )



        self.memory = None

        self.reasoning = None

        self.world = None

        self.multi_agent = None



        self.initialize_modules()



        self.status = "active"



        print(
            "[ATLAS BRAIN] Intelligence Brain v8.0 active"
        )





    # =================================================
    # MODULE INITIALIZATION
    # =================================================



    def initialize_modules(self):


        if not MODULES_AVAILABLE:


            print(
                "[ATLAS BRAIN] Modules unavailable"
            )

            return




        self.memory = AtlasMemoryCore(

            data_dir="memory_data"

        )



        self.reasoning = AtlasReasoningEngine(

            data_dir="memory_data"

        )



        self.world = AtlasWorldModel(

            data_dir="memory_data"

        )



        self.multi_agent = AtlasMultiAgent(

            data_dir="memory_data"

        )



        print(
            "[ATLAS BRAIN] Intelligence modules loaded"
        )





    # =================================================
    # STATUS
    # =================================================



    def get_system_status(self):


        return {


            "brain":

                "Atlas Intelligence v8.0",



            "status":

                self.status,



            "modules":

            {


                "memory":

                    self.memory is not None,


                "reasoning":

                    self.reasoning is not None,


                "world":

                    self.world is not None,


                "multi_agent":

                    self.multi_agent is not None

            },



            "session":

                self.session_id,


            "time":

                datetime.now().isoformat()

        }





    # =================================================
    # MAIN PIPELINE
    # =================================================



    def analyze_and_decide(
        self,
        symbol: str,
        market_data: Dict
    ):


        print()

        print("=" * 60)

        print(
            f"ATLAS INTELLIGENCE v8.0 : {symbol}"
        )

        print("=" * 60)




        world = self.world_analysis(
            symbol
        )



        agents = self.agent_analysis(
            symbol,
            market_data
        )



        reasoning = self.reasoning_analysis(
            symbol,
            market_data
        )



        memory = self.memory_analysis()



        decision = self.fuse_decision(

            symbol,

            agents,

            reasoning,

            memory

        )



        print(
            decision.summary()
        )



        return decision
    # =================================================
    # WORLD MODEL ANALYSIS
    # =================================================


    def world_analysis(
        self,
        symbol
    ):


        impacts = {}


        if self.world:


            try:


                asset = symbol.replace(
                    "USDT",
                    ""
                )


                impacts = self.world.get_impact_chain(

                    asset,

                    depth=2

                )


            except Exception:


                impacts = {}



        print(
            f"[WORLD] {len(impacts)} related assets"
        )


        return impacts





    # =================================================
    # MULTI AGENT ANALYSIS
    # =================================================


    def agent_analysis(
        self,
        symbol,
        market_data
    ):


        agents = {}



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



            if score >= 0.60:


                action = "BUY"



            elif score <= 0.40:


                action = "SELL"



            else:


                action = "HOLD"





            agents[name] = {


                "action":

                    action,


                "score":

                    round(
                        score,
                        2
                    )


            }



            print(

                f"[AGENT] {name}: {action} {score:.2f}"

            )



            if self.multi_agent:


                try:


                    self.multi_agent.generate_signal(

                        name,

                        symbol,

                        action.lower(),

                        score,

                        "Atlas v8.0"

                    )


                except Exception:


                    pass





        return agents






    # =================================================
    # MOMENTUM CALCULATOR
    # =================================================


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



        score = 0.5



        if trend == "BULLISH":


            score += 0.20



        elif trend == "BEARISH":


            score -= 0.20




        if rsi < 35:


            score += 0.10



        elif rsi > 70:


            score -= 0.10




        return max(

            0,

            min(

                score,

                1

            )

        )






    # =================================================
    # REASONING ENGINE
    # =================================================


    def reasoning_analysis(
        self,
        symbol,
        market_data
    ):



        if not self.reasoning:


            return {


                "action":

                    "HOLD",


                "confidence":

                    0

            }






        technical = {


            "rsi":

                market_data.get(
                    "rsi",
                    50
                ),



            "trend":

                market_data.get(
                    "trend",
                    "SIDEWAYS"
                ),



            "macd":

                market_data.get(
                    "macd",
                    0
                )

        }





        macro = {


            "fed_policy":

                market_data.get(
                    "fed_policy",
                    "neutral"
                ),



            "inflation":

                market_data.get(
                    "inflation",
                    2
                )

        }





        sentiment = {


            "fear_greed":

                market_data.get(
                    "fear_greed",
                    50
                )

        }





        try:


            result = self.reasoning.analyze_market(

                symbol,

                technical,

                macro,

                sentiment

            )



            action = (

                result.decision_type.value.upper()

            )



            confidence = float(

                result.confidence

            )



        except Exception as e:


            print(

                f"[REASONING ERROR] {e}"

            )


            action = "HOLD"


            confidence = 0




        print(

            f"[REASONING] {action} {confidence:.2f}"

        )




        return {


            "action":

                action,


            "confidence":

                confidence

        }
    # =================================================
    # MEMORY ANALYSIS
    # =================================================


    def memory_analysis(self):


        if not self.memory:


            return {


                "trades":

                    0,


                "win_rate":

                    0,


                "effect":

                    0

            }





        try:


            trades = len(

                self.memory.trades

            )


            win_rate = self.memory.get_win_rate()



        except Exception:


            trades = 0

            win_rate = 0






        effect = 0




        if trades >= 10:


            if win_rate >= 60:


                effect = 0.05



            elif win_rate < 40:


                effect = -0.05






        print(

            f"[MEMORY] trades={trades} winrate={win_rate}"

        )




        return {


            "trades":

                trades,


            "win_rate":

                win_rate,


            "effect":

                effect

        }






    #     # =================================================
    # DECISION FUSION v9.0
    #
    # Professional Intelligence Aggregation Layer
    #
    # Features:
    #
    # - Multi agent weighted voting
    # - Reasoning engine priority
    # - Confidence normalization
    # - Market uncertainty protection
    # - Memory feedback adjustment
    # - Risk aware decision output
    #
    # =================================================


    def fuse_decision(
        self,
        symbol,
        agents,
        reasoning,
        memory
    ):


        buy_score = 0.0

        sell_score = 0.0

        neutral_score = 0.0



        # =================================================
        # AGENT INTELLIGENCE FUSION
        # =================================================


        for name, data in agents.items():


            weight = self.WEIGHTS.get(
                name,
                0
            )


            score = float(
                data.get(
                    "score",
                    0.5
                )
            )


            action = data.get(
                "action",
                "HOLD"
            )



            if action == "BUY":


                buy_score += (

                    score *

                    weight

                )



            elif action == "SELL":


                sell_score += (

                    (1-score) *

                    weight

                )



            else:


                neutral_score += (

                    0.5 *

                    weight

                )





        # =================================================
        # REASONING ENGINE BOOST
        #
        # Deep reasoning receives higher priority
        #
        # =================================================


        reasoning_action = reasoning.get(

            "action",

            "HOLD"

        )


        reasoning_confidence = float(

            reasoning.get(

                "confidence",

                0

            )

        )



        REASONING_WEIGHT = 0.35



        if reasoning_action == "BUY":


            buy_score += (

                reasoning_confidence *

                REASONING_WEIGHT

            )



        elif reasoning_action == "SELL":


            sell_score += (

                reasoning_confidence *

                REASONING_WEIGHT

            )



        else:


            neutral_score += (

                0.5 *

                REASONING_WEIGHT

            )







        # =================================================
        # MEMORY ADAPTATION
        # =================================================


        memory_effect = float(

            memory.get(

                "effect",

                0

            )

        )





        if memory_effect > 0:


            buy_score += memory_effect

            sell_score += memory_effect



        elif memory_effect < 0:


            neutral_score += abs(

                memory_effect

            )







        # =================================================
        # NORMALIZATION
        # =================================================


        total = (

            buy_score +

            sell_score +

            neutral_score

        )



        if total <= 0:


            winner = "HOLD"

            confidence = 0



        else:


            buy_probability = (

                buy_score /

                total

            )


            sell_probability = (

                sell_score /

                total

            )


            hold_probability = (

                neutral_score /

                total

            )




            scores = {


                "BUY":

                round(

                    buy_probability,

                    3

                ),



                "SELL":

                round(

                    sell_probability,

                    3

                ),



                "HOLD":

                round(

                    hold_probability,

                    3

                )


            }




            winner = max(

                scores,

                key=scores.get

            )



            confidence = scores[winner]






        # =================================================
        # MARKET SAFETY FILTER
        # =================================================


        MIN_CONFIDENCE = 0.55



        if confidence < MIN_CONFIDENCE:


            winner = "HOLD"







        # =================================================
        # ACTION CONVERSION
        # =================================================


        if winner == "BUY":


            action = DecisionAction.BUY



        elif winner == "SELL":


            action = DecisionAction.SELL



        else:


            action = DecisionAction.HOLD







        # =================================================
        # RISK CALCULATION
        # =================================================


        risk = self.calculate_risk(

            confidence

        )







        # =================================================
        # DECISION OBJECT
        # =================================================


        decision = Decision(


            action=action,


            symbol=symbol,


            confidence=round(

                confidence * 100,

                2

            ),



            reasoning=(

                "Atlas v9 weighted intelligence fusion"

            ),



            risk_level=risk,



            strategy=(

                "Atlas_v9_MultiAgent"

            ),



            metadata={


                "scores": {


                    "buy":

                    round(

                        buy_score,

                        3

                    ),


                    "sell":

                    round(

                        sell_score,

                        3

                    ),


                    "hold":

                    round(

                        neutral_score,

                        3

                    )


                },


                "agents":

                agents,



                "reasoning":

                reasoning,



                "memory":

                memory,



                "timestamp":

                datetime.now().isoformat()


            }


        )







        print(

            f"[FUSION v9] "

            f"{decision.action.value} "

            f"confidence={decision.confidence}%"

        )





        return decision