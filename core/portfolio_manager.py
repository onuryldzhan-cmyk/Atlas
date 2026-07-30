"""
============================================================
ATLAS PORTFOLIO MANAGER v1.0
============================================================

Professional Portfolio Management Layer


Responsibilities
----------------

- Track positions
- Manage exposure
- Calculate allocation
- Risk distribution
- Portfolio statistics
- Health monitoring


Architecture


Capital Allocator

        |
        v

Portfolio Manager

        |
        +----------------+
        |                |
        v                v

 Position Book     Risk Analyzer


============================================================
"""


from __future__ import annotations


import logging


from datetime import datetime, UTC



logger = logging.getLogger(
    "AtlasAI.PortfolioManager"
)



class PortfolioManager:


    VERSION = "1.0"


    NAME = "PortfolioManager"



    def __init__(

        self,

        total_capital: float = 10000.0,

    ):


        self.total_capital = float(
            total_capital
        )


        self.cash = float(
            total_capital
        )


        self.positions = {}



        self.trade_history = []



        self.started = datetime.now(
            UTC
        ).isoformat()



        logger.info(

            "Portfolio Manager v1.0 initialized"

        )



    # =====================================================
    # TIME
    # =====================================================


    def now(self):

        return datetime.now(
            UTC
        ).isoformat()



    # =====================================================
    # POSITION CHECK
    # =====================================================


    def has_position(

        self,

        symbol: str

    ):


        return symbol in self.positions



    def get_position(

        self,

        symbol: str

    ):


        return self.positions.get(
            symbol
        )
    # =====================================================
    # OPEN POSITION
    # =====================================================


    def open_position(

        self,

        symbol: str,

        amount: float,

        price: float,

        risk: str = "MEDIUM",

        strategy: str = "Atlas",

        confidence: float = 0.0,

    ):


        if self.has_position(symbol):


            return {


                "success":

                    False,


                "message":

                    "Position already exists"


            }



        if amount <= 0:


            return {


                "success":

                    False,


                "message":

                    "Invalid amount"


            }



        if amount > self.cash:


            return {


                "success":

                    False,


                "message":

                    "Insufficient cash"


            }



        position = {


            "symbol":

                symbol,


            "amount":

                float(amount),


            "entry_price":

                float(price),


            "risk":

                risk,


            "strategy":

                strategy,


            "confidence":

                confidence,


            "status":

                "OPEN",


            "opened_at":

                self.now(),


        }



        self.positions[symbol] = position



        self.cash -= amount



        self.trade_history.append(

            {


                "type":

                    "OPEN",


                "symbol":

                    symbol,


                "amount":

                    amount,


                "price":

                    price,


                "time":

                    self.now()


            }

        )



        return {


            "success":

                True,


            "position":

                position


        }



    # =====================================================
    # CLOSE POSITION
    # =====================================================


    def close_position(

        self,

        symbol: str,

        exit_price: float,

    ):


        position = self.get_position(
            symbol
        )


        if position is None:


            return {


                "success":

                    False,


                "message":

                    "Position not found"


            }



        amount = position["amount"]



        entry_price = position["entry_price"]



        quantity = (

            amount

            /

            entry_price

        )



        pnl = (

            exit_price

            -

            entry_price

        ) * quantity



        self.cash += (

            amount

            +

            pnl

        )



        position["exit_price"] = (

            exit_price

        )


        position["pnl"] = round(

            pnl,

            8

        )


        position["status"] = "CLOSED"



        position["closed_at"] = (

            self.now()

        )



        self.trade_history.append(

            {


                "type":

                    "CLOSE",


                "symbol":

                    symbol,


                "pnl":

                    pnl,


                "time":

                    self.now()


            }

        )



        del self.positions[symbol]



        return {


            "success":

                True,


            "pnl":

                round(

                    pnl,

                    8

                )


        }
    # =====================================================
    # TOTAL EXPOSURE
    # =====================================================


    def total_exposure(self):


        return round(

            sum(

                position["amount"]

                for position

                in self.positions.values()

            ),

            2

        )



    # =====================================================
    # PORTFOLIO VALUE
    # =====================================================


    def portfolio_value(self):


        return round(

            self.cash

            +

            self.total_exposure(),

            2

        )



    # =====================================================
    # EXPOSURE RATIO
    # =====================================================


    def exposure_ratio(self):


        if self.total_capital <= 0:

            return 0.0



        return round(

            (

                self.total_exposure()

                /

                self.total_capital

            )

            *

            100,

            2

        )



    # =====================================================
    # POSITION ALLOCATION
    # =====================================================


    def allocation(self):


        result = {}



        for symbol, position in self.positions.items():


            percentage = (

                position["amount"]

                /

                self.total_capital

            ) * 100



            result[symbol] = {


                "capital":

                    position["amount"],


                "percentage":

                    round(

                        percentage,

                        2

                    ),


                "risk":

                    position["risk"],


            }



        return result



    # =====================================================
    # RISK DISTRIBUTION
    # =====================================================


    def risk_distribution(self):


        distribution = {


            "LOW":0,


            "MEDIUM":0,


            "HIGH":0,


        }



        for position in self.positions.values():


            risk = position.get(

                "risk",

                "MEDIUM"

            )



            if risk not in distribution:

                risk = "MEDIUM"



            distribution[risk] += (

                position["amount"]

            )



        return distribution



    # =====================================================
    # PORTFOLIO HEALTH
    # =====================================================


    def health_score(self):


        score = 100



        exposure = self.exposure_ratio()



        if exposure > 80:


            score -= 30



        elif exposure > 60:


            score -= 15



        positions = len(

            self.positions

        )



        if positions == 0:


            score -= 10



        if positions > 10:


            score -= 20



        return max(

            0,

            score

        )
    # =====================================================
    # STATUS
    # =====================================================


    def status(self):


        return {


            "version":

                self.VERSION,


            "component":

                self.NAME,


            "total_capital":

                self.total_capital,


            "cash":

                round(

                    self.cash,

                    2

                ),


            "exposure":

                self.total_exposure(),


            "portfolio_value":

                self.portfolio_value(),


            "positions":

                len(self.positions),


            "health_score":

                self.health_score(),


        }



    # =====================================================
    # HEALTH
    # =====================================================


    def health(self):


        return {


            "healthy":

                self.cash >= 0,


            "component":

                self.NAME,


            "version":

                self.VERSION,


            "positions":

                len(self.positions),


            "portfolio_value":

                self.portfolio_value(),


            "health_score":

                self.health_score(),


        }



    # =====================================================
    # DIAGNOSTICS
    # =====================================================


    def diagnostics(self):


        return {


            "component":

                self.NAME,


            "version":

                self.VERSION,


            "statistics":{


                "positions":

                    len(self.positions),


                "trades":

                    len(self.trade_history),


                "exposure":

                    self.total_exposure(),


                "exposure_ratio":

                    self.exposure_ratio(),


            },


            "risk_distribution":

                self.risk_distribution(),


            "allocation":

                self.allocation(),


        }



    # =====================================================
    # SNAPSHOT
    # =====================================================


    def snapshot(self):


        return {


            "version":

                self.VERSION,


            "total_capital":

                self.total_capital,


            "cash":

                self.cash,


            "positions":

                dict(

                    self.positions

                ),


            "trade_history":

                list(

                    self.trade_history

                ),


        }



    # =====================================================
    # EXPORT STATE
    # =====================================================


    def export_state(self):


        return self.snapshot()



    # =====================================================
    # IMPORT STATE
    # =====================================================


    def import_state(

        self,

        state: dict

    ):


        self.total_capital = state.get(

            "total_capital",

            self.total_capital

        )


        self.cash = state.get(

            "cash",

            self.cash

        )


        self.positions = dict(

            state.get(

                "positions",

                {}

            )

        )


        self.trade_history = list(

            state.get(

                "trade_history",

                []

            )

        )



    # =====================================================
    # RESET
    # =====================================================


    def reset(self):


        self.cash = self.total_capital


        self.positions.clear()


        self.trade_history.clear()



        logger.warning(

            "Portfolio Manager reset"

        )



    # =====================================================
    # MAGIC METHODS
    # =====================================================


    def __repr__(self):


        return (

            f"<PortfolioManager "

            f"capital={self.total_capital} "

            f"positions={len(self.positions)}>"

        )



    def __str__(self):


        return (

            f"{self.NAME} "

            f"v{self.VERSION}"

        )