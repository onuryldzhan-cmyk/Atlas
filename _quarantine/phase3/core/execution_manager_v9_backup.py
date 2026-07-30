"""
Atlas Execution Manager v9.0

Unified execution orchestration.

Single execution gateway for Atlas.

Flow:

Decision
   |
Adapter
   |
Validator
   |
Risk
   |
Capital
   |
PaperTrader
   |
Memory

"""


import logging

from datetime import datetime, timezone


from core.decision_adapter import DecisionAdapter



logger = logging.getLogger(
    "AtlasAI.Execution"
)



class ExecutionManager:


    VERSION = "9.0"



    def __init__(

        self,

        paper_trader=None,

        capital_manager=None,

        risk_engine=None,

        validator=None,

        trade_memory=None

    ):



        self.paper_trader = paper_trader

        self.capital_manager = capital_manager

        self.risk_engine = risk_engine

        self.validator = validator

        self.trade_memory = trade_memory


        self.adapter = DecisionAdapter()



        logger.info(
            "Execution Manager v9.0 initialized"
        )




    # =====================================
    # MAIN EXECUTION
    # =====================================


    def execute(

        self,

        decision,

        market_state=None

    ):


        decision = self.adapter.adapt(
            decision
        )


        if not decision:


            return {


                "status":
                "FAILED",


                "reason":
                "Invalid decision"

            }




        action = decision["action"]

        symbol = decision["symbol"]



        logger.info(

            f"[ATLAS EXECUTION] {action} {symbol}"

        )





        #
        # VALIDATION
        #


        if self.validator:


            result = self.validator.validate(
                decision
            )


            if not result["approved"]:


                return {


                    "status":
                    "BLOCKED",


                    "layer":
                    "VALIDATOR",


                    "reason":
                    result.get(
                        "reasons"
                    )

                }




        #
        # ONLY BUY
        #


        if action != "BUY":


            return {


                "status":
                "NO_EXECUTION",


                "action":
                action

            }





        #
        # PRICE
        #


        price = decision.get(
            "price"
        )


        if market_state:


            price = market_state.get(

                "price",

                price

            )



        if not price:


            return {


                "status":
                "FAILED",


                "reason":
                "Missing price"

            }




        #
        # CAPITAL
        #


        amount = 100



        if self.capital_manager:


            allocation = self.capital_manager.allocate(

                symbol,

                decision["confidence"],

                price

            )


            if not allocation.get(
                "success"
            ):


                return allocation



            amount = allocation["amount"]





        #
        # PAPER EXECUTION
        #


        execution = None



        if self.paper_trader:


            execution = self.paper_trader.open_trade(

                symbol,

                price,

                amount

            )





        #
        # MEMORY
        #


        trade = {


            "symbol":
            symbol,


            "action":
            action,


            "price":
            price,


            "amount":
            amount,


            "confidence":
            decision["confidence"],


            "time":
            datetime.now(
                timezone.utc
            ).isoformat()

        }




        if self.trade_memory:


            self.trade_memory.remember(
                trade
            )





        return {


            "status":
            "EXECUTED",


            "trade":
            trade,


            "paper":
            execution

        }





    def status(self):


        return {


            "version":
            self.VERSION,


            "adapter":
            self.adapter.status(),


            "paper":
            self.paper_trader is not None,


            "risk":
            self.risk_engine is not None

        }