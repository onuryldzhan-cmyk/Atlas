"""
Atlas Execution Bridge v6.0

Connects:

Decision Layer
        |
        |
Execution Layer


Responsibilities:
- Validate Atlas decisions
- Convert decisions into trade requests
- Send orders to PaperTrader
- Return execution results
"""


from __future__ import annotations


import logging
from typing import Dict, Any



class ExecutionBridge:
    """
    Atlas execution connector.

    This layer does not create decisions.
    It only executes approved decisions.
    """



    def __init__(
        self,
        paper_trader=None
    ):


        self.paper_trader = paper_trader


        self.logger = logging.getLogger(
            "AtlasAI.Execution"
        )


        self.logger.info(
            "Execution Bridge v6.0 initialized."
        )




    def connect(
        self,
        paper_trader
    ):


        """
        Attach PaperTrader dynamically.
        """


        self.paper_trader = paper_trader


        self.logger.info(
            "PaperTrader connected to Execution Bridge."
        )





    def execute(
        self,
        decision
    ) -> Dict[str, Any]:


        """
        Execute Atlas Decision object.
        """



        if self.paper_trader is None:


            self.logger.warning(
                "PaperTrader is not connected."
            )


            return {


                "status":
                    "EXECUTION_OFFLINE",



                "reason":
                    "PaperTrader missing"


            }





        if not decision.is_trade_signal():


            return {


                "status":
                    "NO_TRADE",



                "reason":
                    "Decision action is not BUY or SELL"


            }





        action = decision.action.value



        symbol = decision.symbol




        position_size = (

            decision.metadata.get(

                "position_size_pct",

                0

            )

        )




        try:


            result = self.paper_trader.open_trade(

                symbol,

                action,

                position_size

            )




            return {


                "status":

                    "EXECUTED" if result else "FAILED",



                "symbol":

                    symbol,



                "action":

                    action,



                "size":

                    position_size


            }




        except Exception as e:


            self.logger.error(

                f"Execution error: {e}"

            )


            return {


                "status":

                    "ERROR",



                "error":

                    str(e)


            }





    def status(self):


        return {


            "paper_trader_connected":

                self.paper_trader is not None


        }