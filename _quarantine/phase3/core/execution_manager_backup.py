"""
Atlas AI Execution Manager v1.0

Connects:
Decision Layer
        |
        v
Execution Layer
        |
        v
Paper Trader

No intelligence here.
Only execution routing.
"""


import logging


from core.paper_trader import PaperTrader


logger = logging.getLogger(
    "AtlasAI.Execution"
)



class ExecutionManager:


    def __init__(
        self,
        database
    ):

        self.logger = logger


        self.paper_trader = PaperTrader(
            database
        )


        self.logger.info(
            "Execution Manager initialized."
        )



    def execute(
        self,
        decision
    ):


        if decision is None:

            return {

                "status":
                    "NO_DECISION"

            }



        action = (
            decision.action.value
        )


        symbol = (
            decision.symbol
        )


        confidence = (
            decision.confidence
        )



        if action not in (
            "BUY",
            "SELL"
        ):


            return {

                "status":
                    "SKIPPED",

                "reason":
                    "No trade action",

                "action":
                    action

            }



        if confidence < 50:


            return {

                "status":
                    "SKIPPED",

                "reason":
                    "Confidence too low",

                "confidence":
                    confidence

            }



        size = (
            decision.metadata
            .get(
                "position_size_pct",
                1
            )
        )



        opened = self.paper_trader.open_trade(

            symbol,

            action,

            size

        )



        if opened:


            result = {

                "status":
                    "EXECUTED",

                "mode":
                    "PAPER",

                "symbol":
                    symbol,

                "action":
                    action,

                "size":
                    size

            }


        else:


            result = {

                "status":
                    "FAILED",

                "symbol":
                    symbol

            }



        return result