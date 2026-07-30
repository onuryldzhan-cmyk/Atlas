"""
============================================================
ATLAS AI EXECUTION ROUTER v1.0
============================================================

Execution routing abstraction.

Routes orders between:

PAPER
LIVE


Responsibilities:

- Engine selection
- Mode control
- Execution fallback
- Health monitoring


============================================================
"""


from datetime import datetime, UTC
import logging


logger = logging.getLogger(
    "AtlasAI.ExecutionRouter"
)



class ExecutionRouter:


    VERSION = "1.0"



    def __init__(

        self,

        paper_engine=None,

        live_engine=None,

        mode="PAPER"

    ):


        self.paper_engine = paper_engine

        self.live_engine = live_engine

        self.mode = mode.upper()


        self.executions = []

        self.errors = []



        logger.info(
            "Execution Router v1.0 initialized"
        )



    # ==================================================
    # ENGINE SELECTOR
    # ==================================================


    def engine(self):


        if self.mode == "LIVE":


            return self.live_engine


        return self.paper_engine



    # ==================================================
    # BUY ROUTE
    # ==================================================


    def buy(

        self,

        symbol,

        price,

        amount,

        strategy,

        confidence

    ):


        engine = self.engine()



        if engine is None:


            return {

                "status":
                "FAILED",

                "reason":
                "Execution engine unavailable"

            }



        try:


            result = engine.buy(

                symbol,

                price,

                amount,

                strategy,

                confidence

            )



            event={


                "type":
                "BUY",


                "symbol":
                symbol,


                "mode":
                self.mode,


                "time":
                datetime.now(
                    UTC
                ).isoformat()


            }


            self.executions.append(
                event
            )



            return result



        except Exception as e:


            self.errors.append(

                str(e)

            )


            logger.exception(
                "BUY routing failed"
            )


            return {

                "status":
                "ERROR",

                "error":
                str(e)

            }



    # ==================================================
    # SELL ROUTE
    # ==================================================


    def sell(

        self,

        symbol,

        price

    ):


        engine=self.engine()


        if engine is None:


            return {

                "status":
                "FAILED",

                "reason":
                "Engine unavailable"

            }



        return engine.sell(

            symbol,

            price

        )



    # ==================================================
    # STATUS
    # ==================================================


    def status(self):


        return {


            "version":
            self.VERSION,


            "mode":
            self.mode,


            "paper_engine":
            self.paper_engine is not None,


            "live_engine":
            self.live_engine is not None,


            "executions":
            len(
                self.executions
            ),


            "errors":
            len(
                self.errors
            )

        }



    def health(self):


        return {


            "healthy":
            len(
                self.errors
            ) == 0,


            "mode":
            self.mode,


            "active_engine":
            type(
                self.engine()
            ).__name__
            if self.engine()
            else None

        }