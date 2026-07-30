"""
============================================================
ATLAS INTELLIGENCE CORE v7.0
============================================================

Central AI Orchestrator

Flow:

Market Data
      |
Market Intelligence
      |
Market Pipeline
      |
Decision Engine
      |
Execution Manager
      |
Position Controller
      |
Learning Memory


============================================================
"""


import logging

from datetime import datetime, UTC



logger = logging.getLogger(
    "AtlasAI.IntelligenceCore"
)





class IntelligenceCore:


    VERSION = "7.0"




    def __init__(

        self,

        pipeline=None,

        decision_engine=None,

        execution_manager=None,

        position_controller=None,

        memory=None

    ):


        self.pipeline = pipeline

        self.decision_engine = decision_engine

        self.execution_manager = execution_manager

        self.position_controller = position_controller

        self.memory = memory



        logger.info(
            "Atlas Intelligence Core v7.0 initialized"
        )





    # =====================================================
    # MAIN LOOP
    # =====================================================


    def run(

        self,

        symbols=None

    ):



        timestamp = datetime.now(
            UTC
        ).isoformat()



        if not self.pipeline:


            raise RuntimeError(
                "Market Pipeline not connected"
            )



        # -----------------------------
        # MARKET ANALYSIS
        # -----------------------------


        analysis = self.pipeline.analyze_market(

            symbols

        )



        opportunities = analysis.get(

            "opportunities",

            []

        )





        # -----------------------------
        # DECISION
        # -----------------------------


        decision = self.create_decision(

            opportunities

        )




        # -----------------------------
        # EXECUTION
        # -----------------------------


        execution = {

            "status":
            "NOT_EXECUTED"

        }



        if self.execution_manager:



            try:


                execution = self.execution_manager.execute(

                    decision

                )


            except Exception as e:



                logger.exception(
                    "Execution error"
                )


                execution = {

                    "status":
                    "FAILED",

                    "error":
                    str(e)

                }







        # -----------------------------
        # MEMORY
        # -----------------------------


        if self.memory:


            try:


                self.memory.store(

                    {

                    "analysis":
                    analysis,

                    "decision":
                    decision,

                    "execution":
                    execution,

                    "time":
                    timestamp

                    }

                )


            except Exception:



                logger.warning(
                    "Memory write failed"
                )







        return {


            "time":
            timestamp,


            "analysis":
            analysis,


            "decision":
            decision,


            "execution":
            execution,


            "positions":

            self.position_controller.status()

            if self.position_controller

            else None


        }





    # =====================================================
    # DECISION
    # =====================================================


    def create_decision(

        self,

        opportunities

    ):



        if self.decision_engine:


            return self.decision_engine.decide(

                opportunities

            )





        if not opportunities:


            return {


                "action":
                "HOLD",


                "reason":
                [

                    "No opportunity"

                ]

            }





        best = max(

            opportunities,

            key=lambda x:

            x.get(
                "score",
                0
            )

        )



        score = best.get(

            "score",

            0

        )





        if score < 60:



            return {


                "action":

                "HOLD",



                "reason":

                [

                    "Low confidence"

                ]

            }





        return {


            "action":

            "BUY",



            "symbol":

            best["symbol"],



            "price":

            best.get(

                "price",

                0

            ),



            "confidence":

            score,



            "strategy":

            "MOMENTUM",



            "risk":

            "medium",



            "reason":

            [

                "Strong opportunity"

            ]

        }





    # =====================================================
    # STATUS
    # =====================================================


    def status(self):


        return {


            "version":

            self.VERSION,



            "pipeline":

            self.pipeline is not None,



            "decision_engine":

            self.decision_engine is not None,



            "execution":

            self.execution_manager is not None,



            "position":

            self.position_controller is not None,



            "memory":

            self.memory is not None

        }