"""
============================================================
ATLAS CAPITAL ALLOCATOR v3.0
============================================================

Professional Portfolio Capital Control System


Responsibilities
----------------

- Dynamic capital allocation
- Risk based sizing
- Position limits
- Exposure control
- Execution permission
- Portfolio diagnostics


Architecture

Decision Engine
        |
        v
Capital Allocator
        |
        v
Execution Controller


============================================================
"""


from __future__ import annotations


import logging



logger = logging.getLogger(
    "AtlasAI.CapitalAllocator"
)





class CapitalAllocator:



    VERSION = "3.0"



    def __init__(

        self,

        total_capital: float = 10000.0,

    ):


        self.total_capital = float(
            total_capital
        )


        self.available_capital = float(
            total_capital
        )


        self.used_capital = 0.0



        self.max_position_percent = 0.40


        self.cash_reserve_percent = 0.20



        self.max_positions = 5



        self.positions = {}



        self.executions = 0


        self.rejected = 0



        logger.info(

            "Capital Allocator v3.0 initialized"

        )



    # =====================================================
    # CAPITAL CHECK
    # =====================================================


    def can_execute(

        self,

        request,

    ):


        amount = float(
            request.amount
        )


        if amount > self.available_capital:


            self.rejected += 1


            return False



        if len(self.positions) >= self.max_positions:


            self.rejected += 1


            return False



        return True
    # =====================================================
    # RISK WEIGHT
    # =====================================================


    def risk_weight(
        self,
        risk: str,
    ) -> float:


        weights = {


            "LOW":

                0.40,


            "MEDIUM":

                0.30,


            "HIGH":

                0.20,


        }



        return weights.get(

            risk.upper(),

            0.25

        )



    # =====================================================
    # POSITION SIZE
    # =====================================================


    def calculate_position_size(

        self,

        confidence: float,

        risk: str,

    ) -> float:



        confidence_factor = (

            confidence

            /

            100

        )



        risk_factor = (

            self.risk_weight(
                risk
            )

        )



        size = (

            self.total_capital

            *

            confidence_factor

            *

            risk_factor

        )



        maximum = (

            self.total_capital

            *

            self.max_position_percent

        )



        size = min(

            size,

            maximum

        )



        return round(

            size,

            2

        )



    # =====================================================
    # ALLOCATE
    # =====================================================


    def allocate(

        self,

        opportunities,

    ):


        if not opportunities:


            return []



        available = (

            self.total_capital

            *

            (

                1 -

                self.cash_reserve_percent

            )

        )



        total_score = sum(

            item.get(

                "score",

                0

            )

            for item in opportunities

        )



        if total_score <= 0:


            return []



        allocations = []



        for item in opportunities:



            weight = (

                item.get(

                    "score",

                    0

                )

                /

                total_score

            )



            capital = (

                available

                *

                weight

            )



            maximum = (

                self.total_capital

                *

                self.max_position_percent

            )



            capital = min(

                capital,

                maximum

            )



            allocations.append(

                {


                    "symbol":

                        item.get(
                            "symbol"
                        ),


                    "capital":

                        round(
                            capital,
                            2
                        ),


                    "score":

                        item.get(
                            "score",
                            0
                        ),


                    "risk":

                        item.get(
                            "risk",
                            "MEDIUM"
                        ),


                }

            )



        return allocations



    # =====================================================
    # REGISTER POSITION
    # =====================================================


    def register_position(

        self,

        request,

    ):


        self.positions[

            request.symbol

        ] = {


            "symbol":

                request.symbol,


            "amount":

                request.amount,


            "risk":

                request.risk,


            "strategy":

                request.strategy,

        }



        self.used_capital += (

            request.amount

        )



        self.available_capital = (

            self.total_capital

            -

            self.used_capital

        )



        self.executions += 1
    # =====================================================
    # CLOSE POSITION
    # =====================================================


    def close_position(

        self,

        symbol: str,

    ):


        position = self.positions.get(

            symbol

        )



        if not position:


            return False



        amount = position.get(

            "amount",

            0

        )



        self.used_capital -= amount



        if self.used_capital < 0:


            self.used_capital = 0



        self.available_capital = (

            self.total_capital

            -

            self.used_capital

        )



        del self.positions[

            symbol

        ]



        return True



    # =====================================================
    # EXPOSURE
    # =====================================================


    def exposure(self):


        if self.total_capital <= 0:


            return 0.0



        return round(

            (

                self.used_capital

                /

                self.total_capital

            )

            *

            100,

            2

        )



    # =====================================================
    # AVAILABLE CAPITAL
    # =====================================================


    def get_available_capital(self):


        return round(

            self.available_capital,

            2

        )



    # =====================================================
    # PORTFOLIO
    # =====================================================


    def portfolio(self):


        return {


            "total_capital":

                self.total_capital,


            "used_capital":

                round(

                    self.used_capital,

                    2

                ),


            "available_capital":

                round(

                    self.available_capital,

                    2

                ),


            "exposure_percent":

                self.exposure(),


            "positions":

                len(

                    self.positions

                ),


        }



    # =====================================================
    # STATUS
    # =====================================================


    def status(self):


        return {


            "version":

                self.VERSION,


            "component":

                "CapitalAllocator",


            "total_capital":

                self.total_capital,


            "available":

                self.available_capital,


            "used":

                self.used_capital,


            "positions":

                len(

                    self.positions

                ),


            "executions":

                self.executions,


            "rejected":

                self.rejected,


        }



    # =====================================================
    # HEALTH
    # =====================================================


    def health(self):


        return {


            "healthy":

                True,


            "component":

                "CapitalAllocator",


            "version":

                self.VERSION,


            "available_capital":

                self.available_capital,


            "positions":

                len(

                    self.positions

                ),

        }



    # =====================================================
    # DIAGNOSTICS
    # =====================================================


    def diagnostics(self):


        return {


            "component":

                "CapitalAllocator",


            "version":

                self.VERSION,


            "configuration":{


                "max_position_percent":

                    self.max_position_percent,


                "cash_reserve_percent":

                    self.cash_reserve_percent,


                "max_positions":

                    self.max_positions,

            },


            "portfolio":

                self.portfolio(),


            "statistics":{


                "executions":

                    self.executions,


                "rejected":

                    self.rejected,

            },

        }