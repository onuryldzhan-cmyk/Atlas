"""
Atlas Execution Manager v7.0

Professional execution orchestration layer.

Responsibilities:

- Receive AI decisions
- Normalize decisions
- Validate risk
- Allocate capital
- Execute paper trades
- Sync portfolio
- Record trades
- Prepare live execution layer

Architecture:

Atlas Brain
      |
      v
Decision
      |
      v
Execution Manager
      |
      +---- Capital Manager
      |
      +---- Paper Trader
      |
      +---- Trade Memory
      |
      v
Position
"""


from __future__ import annotations


import logging
from datetime import datetime, timezone



logger = logging.getLogger(
    "AtlasAI.Execution"
)



class ExecutionManager:


    VERSION = "7.0"



    def __init__(

        self,

        paper_trader=None,

        capital_manager=None,

        profit_manager=None,

        position_lifecycle=None,

        trade_memory=None,

        mode="PAPER"

    ):


        self.paper_trader = paper_trader

        self.capital_manager = capital_manager

        self.profit_manager = profit_manager

        self.position_lifecycle = position_lifecycle

        self.trade_memory = trade_memory

        self.mode = mode



        logger.info(
            f"Execution Manager v{self.VERSION} initialized"
        )



    # ==================================================
    # MAIN EXECUTION ROUTER
    # ==================================================


    def execute(

        self,

        decision,

        market_state=None

    ):


        decision = self.normalize_decision(
            decision
        )


        if not decision:


            return {

                "status":"FAILED",

                "reason":"Invalid decision"

            }




        action = decision.get(
            "action",
            "HOLD"
        )


        symbol = decision.get(
            "symbol"
        )



        logger.info(

            f"[EXECUTION] {symbol} {action}"

        )




        if action == "BUY":


            return self.open_position(

                decision,

                market_state

            )



        if action in (

            "SELL",

            "CLOSE"

        ):


            return self.close_position(

                symbol

            )



        return {


            "status":"HOLD",

            "symbol":symbol,

            "confidence":

                decision.get(
                    "confidence",
                    0
                )


        }




    # ==================================================
    # NORMALIZER
    # ==================================================


    def normalize_decision(

        self,

        decision

    ):


        if decision is None:

            return None



        if hasattr(

            decision,

            "to_dict"

        ):


            return decision.to_dict()



        if isinstance(

            decision,

            dict

        ):


            return decision



        logger.warning(

            f"Unknown decision {type(decision)}"

        )


        return None





    # ==================================================
    # OPEN POSITION
    # ==================================================


    def open_position(

        self,

        decision,

        market_state=None

    ):


        symbol = decision.get(
            "symbol"
        )


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


                "status":"FAILED",

                "reason":"Missing price"


            }




        if self.has_position(symbol):


            return {


                "status":"BLOCKED",

                "reason":
                "Position exists"

            }





        confidence=float(

            decision.get(

                "confidence",

                0

            )

        )



        risk = decision.get(

            "risk_level",

            "medium"

        ).lower()



        allocation = None



        if self.capital_manager:


            allocation = self.capital_manager.allocate(

                symbol,

                confidence,

                price

            )



            if not allocation.get(
                "success"
            ):


                return {


                    "status":"FAILED",

                    "reason":

                    allocation.get(
                        "error"
                    )

                }




            amount = allocation["amount"]



        else:


            amount = 0



        if amount <= 0:


            return {


                "status":"FAILED",

                "reason":"Invalid amount"

            }





        trade = {


            "symbol":

                symbol,


            "side":

                "LONG",


            "price":

                float(price),


            "amount":

                float(amount),


            "confidence":

                confidence,


            "risk":

                risk,


            "time":

                datetime.now(

                    timezone.utc

                ).isoformat()


        }





        # PAPER EXECUTION

        result=None



        if self.paper_trader:


            result = self.paper_trader.open_trade(

                symbol,

                price,

                amount

            )





        # MEMORY


        if self.trade_memory:


            try:


                self.trade_memory.record_entry(

                    trade

                )


            except Exception as e:


                logger.warning(

                    f"Memory error {e}"

                )





        logger.info(

            f"[OPENED] {symbol} amount={amount}"

        )



        return {


            "status":"OPENED",

            "trade":trade,

            "result":result,

            "allocation":allocation


        }





    # ==================================================
    # CLOSE POSITION
    # ==================================================


    def close_position(

        self,

        symbol

    ):



        if not self.paper_trader:


            return {


                "status":"FAILED"

            }




        result = self.paper_trader.close_trade(

            symbol

        )



        logger.info(

            f"[CLOSED] {symbol}"

        )



        return {


            "status":"CLOSED",

            "symbol":symbol,

            "result":result

        }





    # ==================================================
    # POSITION CHECK
    # ==================================================


    def has_position(

        self,

        symbol

    ):



        if not self.paper_trader:

            return False



        try:


            return symbol in self.paper_trader.positions



        except Exception:


            return False





    # ==================================================
    # STATUS
    # ==================================================


    def status(self):


        return {


            "version":

                self.VERSION,


            "mode":

                self.mode,


            "paper":

                self.paper_trader is not None,


            "capital":

                self.capital_manager is not None

        }