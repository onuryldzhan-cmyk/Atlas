"""
============================================================
ATLAS PAPER EXECUTION ENGINE v22.0
============================================================

Institutional Grade Paper Trading Execution Layer


Purpose
-------

Production simulation engine for Atlas AI.


Features
--------

✓ Order execution
✓ Portfolio accounting
✓ Position lifecycle
✓ Fee calculation
✓ PnL tracking
✓ Trade ledger
✓ Execution ledger
✓ Event hooks
✓ Diagnostics
✓ State recovery
✓ Risk metadata support


Architecture
------------


Decision Engine

        |
        v

Execution Controller

        |
        v

PaperExecutionEngine

        |
        +------------+
        |            |
        v            v

 Portfolio       Learning


============================================================
"""


from __future__ import annotations


import logging
import uuid


from datetime import datetime, UTC
from decimal import Decimal
from typing import Any, Callable


from core.execution_contracts import (
    ExecutionEngine,
)


from core.execution_models import (
    ExecutionRequest,
    ExecutionResult,
)



logger = logging.getLogger(
    "AtlasAI.PaperExecutionEngine"
)




class PaperExecutionEngine(
    ExecutionEngine
):


    VERSION = "22.0"


    ENGINE_NAME = (
        "PaperExecutionEngine"
    )


    ENGINE_MODE = (
        "PAPER"
    )



    # =====================================================
    # INITIALIZATION
    # =====================================================


    def __init__(
        self,
        initial_balance: float = 10000.0,
        fee_rate: float = 0.001,
    ):


        self.initial_balance = Decimal(
            str(initial_balance)
        )


        self.balance = Decimal(
            str(initial_balance)
        )


        self.fee_rate = Decimal(
            str(fee_rate)
        )



        self.positions: dict[
            str,
            dict[str, Any]
        ] = {}



        self.trade_history: list[
            dict[str, Any]
        ] = []



        self.execution_history: list[
            dict[str, Any]
        ] = []



        self.event_hooks: list[
            Callable
        ] = []



        self.executions = 0


        self.errors = 0



        self.started = (
            self.now()
        )



        logger.info(
            "Atlas Paper Execution Engine v22.0 started"
        )



    # =====================================================
    # BASIC INFORMATION
    # =====================================================


    @property
    def name(self):

        return self.ENGINE_NAME



    @property
    def mode(self):

        return self.ENGINE_MODE



    @staticmethod
    def now():

        return datetime.now(
            UTC
        ).isoformat()



    def create_id(self):

        return str(
            uuid.uuid4()
        )



    # =====================================================
    # VALIDATION
    # =====================================================


    def validate_request(
        self,
        request: ExecutionRequest,
    ) -> tuple[bool,str]:


        if not request.symbol:

            return (
                False,
                "Missing symbol"
            )



        action = (
            request.action.upper()
        )



        if action not in (
            "BUY",
            "SELL",
        ):

            return (
                False,
                "Invalid action"
            )



        if request.price <= 0:

            return (
                False,
                "Invalid price"
            )



        if request.amount <= 0:

            return (
                False,
                "Invalid amount"
            )



        return (
            True,
            ""
        )



    # =====================================================
    # FEE ENGINE
    # =====================================================


    def calculate_fee(
        self,
        amount: float,
    ):


        fee = (

            Decimal(
                str(amount)
            )

            *

            self.fee_rate

        )


        return float(
            round(
                fee,
                8
            )
        )



    # =====================================================
    # POSITION HELPERS
    # =====================================================


    def has_position(
        self,
        symbol:str,
    ):


        return (
            symbol
            in
            self.positions
        )



    def get_position(
        self,
        symbol:str,
    ):


        return self.positions.get(
            symbol
        )



    def save_trade(
        self,
        data:dict,
    ):


        self.trade_history.append(
            data
        )



    def save_execution(
        self,
        data:dict,
    ):


        self.execution_history.append(
            data
        )
            # =====================================================
    # EVENT SYSTEM
    # =====================================================


    def add_event_hook(
        self,
        callback: Callable,
    ):


        if callback not in self.event_hooks:

            self.event_hooks.append(
                callback
            )



    def emit_event(
        self,
        event:dict,
    ):


        for hook in self.event_hooks:

            try:

                hook(event)

            except Exception as exc:

                logger.error(
                    "Event hook error: %s",
                    exc
                )



    # =====================================================
    # MAIN EXECUTION ROUTER
    # =====================================================


    def execute(
        self,
        request: ExecutionRequest,
    ) -> ExecutionResult:


        valid, message = (
            self.validate_request(
                request
            )
        )



        if not valid:


            self.errors += 1


            return ExecutionResult(

                success=False,

                status="REJECTED",

                message=message,

            )



        action = (
            request.action.upper()
        )



        if action == "BUY":

            return self._buy(
                request
            )



        if action == "SELL":

            return self._sell(
                request
            )



        self.errors += 1



        return ExecutionResult(

            success=False,

            status="ERROR",

            message="Unknown execution path",

        )



    # =====================================================
    # BUY EXECUTION
    # =====================================================


    def _buy(
        self,
        request: ExecutionRequest,
    ) -> ExecutionResult:



        if self.has_position(
            request.symbol
        ):


            return ExecutionResult(

                success=False,

                status="REJECTED",

                message="Position already exists",

            )



        fee = self.calculate_fee(
            request.amount
        )



        total_cost = (

            request.amount

            +

            fee

        )



        if total_cost > float(
            self.balance
        ):


            self.errors += 1


            return ExecutionResult(

                success=False,

                status="REJECTED",

                message="Insufficient balance",

            )



        self.balance -= Decimal(
            str(total_cost)
        )



        execution_id = (
            self.create_id()
        )


        position_id = (
            self.create_id()
        )



        position = {


            "position_id":

                position_id,


            "symbol":

                request.symbol,


            "action":

                "BUY",


            "entry_price":

                request.price,


            "amount":

                request.amount,


            "strategy":

                request.strategy,


            "confidence":

                request.confidence,


            "risk":

                request.risk,


            "fee":

                fee,


            "status":

                "OPEN",


            "opened_at":

                self.now(),

        }



        self.positions[
            request.symbol
        ] = position



        trade = {


            "execution_id":

                execution_id,


            "type":

                "BUY",


            "symbol":

                request.symbol,


            "price":

                request.price,


            "amount":

                request.amount,


            "fee":

                fee,


            "strategy":

                request.strategy,


            "time":

                self.now(),

        }



        self.save_trade(
            trade
        )



        execution = {


            "execution_id":

                execution_id,


            "status":

                "FILLED",


            "action":

                "BUY",


            "symbol":

                request.symbol,


            "time":

                self.now(),

        }



        self.save_execution(
            execution
        )



        self.emit_event({

            "event":

                "EXECUTION_FILLED",


            "action":

                "BUY",


            "symbol":

                request.symbol,


            "price":

                request.price,


            "amount":

                request.amount,


        })



        self.executions += 1



        logger.info(
            "BUY executed %s",
            request.symbol
        )



        return ExecutionResult(

            success=True,

            status="FILLED",

            message="BUY executed",

            execution_id=execution_id,

            position_id=position_id,

            symbol=request.symbol,

            action="BUY",

            filled_price=request.price,

            filled_amount=request.amount,

            fee=fee,

            pnl=0.0,

            metadata=position,

        )



    # =====================================================
    # SELL EXECUTION
    # =====================================================


    def _sell(
        self,
        request: ExecutionRequest,
    ) -> ExecutionResult:



        position = self.get_position(
            request.symbol
        )



        if position is None:


            self.errors += 1



            return ExecutionResult(

                success=False,

                status="REJECTED",

                message="Position not found",

            )



        fee = self.calculate_fee(
            request.amount
        )



        entry_price = (
            position[
                "entry_price"
            ]
        )



        quantity = (

            request.amount

            /

            request.price

        )



        pnl = (
            (
                request.price - entry_price
            )
            *
            quantity
        ) - fee



        self.balance += Decimal(

            str(

                request.amount

                -

                fee

            )

        )



        position.update({

            "exit_price":

                request.price,


            "closed_at":

                self.now(),


            "realized_pnl":

                round(
                    pnl,
                    8
                ),


            "status":

                "CLOSED",

        })



        execution_id = (
            self.create_id()
        )



        self.save_trade({

            "execution_id":

                execution_id,


            "type":

                "SELL",


            "symbol":

                request.symbol,


            "price":

                request.price,


            "amount":

                request.amount,


            "fee":

                fee,


            "pnl":

                pnl,


            "time":

                self.now(),

        })



        self.save_execution({

            "execution_id":

                execution_id,


            "status":

                "CLOSED",


            "action":

                "SELL",


            "symbol":

                request.symbol,


            "time":

                self.now(),

        })



        self.emit_event({

            "event":

                "TRADE_CLOSED",


            "symbol":

                request.symbol,


            "pnl":

                pnl,


        })



        self.executions += 1



        del self.positions[
            request.symbol
        ]



        logger.info(

            "SELL executed %s PNL=%s",

            request.symbol,

            pnl

        )



        return ExecutionResult(

            success=True,

            status="CLOSED",

            message="SELL executed",

            execution_id=execution_id,

            position_id=position[
                "position_id"
            ],

            symbol=request.symbol,

            action="SELL",

            filled_price=request.price,

            filled_amount=request.amount,

            fee=fee,

            pnl=pnl,

            metadata=position,

        )
            # =====================================================
    # PORTFOLIO INFORMATION
    # =====================================================


    @property
    def open_positions(self):

        return len(
            self.positions
        )



    @property
    def trade_count(self):

        return len(
            self.trade_history
        )



    @property
    def execution_count(self):

        return len(
            self.execution_history
        )



    @property
    def portfolio_value(self):

        """
        Current paper portfolio value.

        Future:
        - mark to market
        - unrealized pnl
        - live price feed
        """


        return round(

            float(
                self.balance
            ),

            2

        )



    # =====================================================
    # PNL STATISTICS
    # =====================================================


    def total_realized_pnl(self):


        total = 0.0


        for trade in self.trade_history:


            if trade.get(
                "type"
            ) == "SELL":


                total += trade.get(
                    "pnl",
                    0.0
                )


        return round(
            total,
            8
        )



    def winning_trades(self):


        count = 0


        for trade in self.trade_history:


            if trade.get(
                "type"
            ) == "SELL":


                if trade.get(
                    "pnl",
                    0
                ) > 0:


                    count += 1



        return count



    def losing_trades(self):


        count = 0


        for trade in self.trade_history:


            if trade.get(
                "type"
            ) == "SELL":


                if trade.get(
                    "pnl",
                    0
                ) < 0:


                    count += 1



        return count



    def win_rate(self):


        total = (

            self.winning_trades()

            +

            self.losing_trades()

        )


        if total == 0:

            return 0.0



        return round(

            (

                self.winning_trades()

                /

                total

            )

            *

            100,

            2

        )



    # =====================================================
    # STATUS
    # =====================================================


    def status(self):


        return {


            "version":

                self.VERSION,


            "engine":

                self.name,


            "mode":

                self.mode,


            "balance":

                float(
                    self.balance
                ),


            "portfolio_value":

                self.portfolio_value,


            "initial_balance":

                float(
                    self.initial_balance
                ),


            "fee_rate":

                float(
                    self.fee_rate
                ),


            "positions":

                self.open_positions,


            "trades":

                self.trade_count,


            "executions":

                self.execution_count,


            "realized_pnl":

                self.total_realized_pnl(),


            "win_rate":

                self.win_rate(),


            "errors":

                self.errors,

        }



    # =====================================================
    # HEALTH CHECK
    # =====================================================


    def health(self):


        return {


            "healthy":

                self.errors == 0,


            "engine":

                self.name,


            "mode":

                self.mode,


            "started":

                self.started,


            "balance":

                float(
                    self.balance
                ),


            "positions":

                self.open_positions,


            "executions":

                self.executions,


            "errors":

                self.errors,


        }



    # =====================================================
    # DIAGNOSTICS
    # =====================================================


    def diagnostics(self):


        return {


            "engine":

                self.name,


            "version":

                self.VERSION,


            "mode":

                self.mode,


            "healthy":

                self.errors == 0,



            "runtime":{


                "started":

                    self.started,


                "executions":

                    self.executions,


                "errors":

                    self.errors,


            },



            "portfolio":{


                "balance":

                    float(
                        self.balance
                    ),


                "positions":

                    self.open_positions,


                "realized_pnl":

                    self.total_realized_pnl(),


                "win_rate":

                    self.win_rate(),

            },



            "history":{


                "trades":

                    len(
                        self.trade_history
                    ),


                "executions":

                    len(
                        self.execution_history
                    ),

            },


            "configuration":{


                "initial_balance":

                    float(
                        self.initial_balance
                    ),


                "fee_rate":

                    float(
                        self.fee_rate
                    ),

            },


        }
            # =====================================================
    # SNAPSHOT
    # =====================================================


    def snapshot(self):


        return {


            "version":

                self.VERSION,


            "engine":

                self.name,


            "mode":

                self.mode,


            "balance":

                float(
                    self.balance
                ),


            "initial_balance":

                float(
                    self.initial_balance
                ),


            "fee_rate":

                float(
                    self.fee_rate
                ),


            "positions":

                dict(
                    self.positions
                ),


            "trade_history":

                list(
                    self.trade_history
                ),


            "execution_history":

                list(
                    self.execution_history
                ),


            "executions":

                self.executions,


            "errors":

                self.errors,


            "started":

                self.started,

        }



    # =====================================================
    # EXPORT STATE
    # =====================================================


    def export_state(self):

        return self.snapshot()



    # =====================================================
    # IMPORT / RECOVERY
    # =====================================================


    def import_state(
        self,
        state:dict,
    ):


        self.balance = Decimal(

            str(

                state.get(

                    "balance",

                    self.initial_balance

                )

            )

        )



        self.initial_balance = Decimal(

            str(

                state.get(

                    "initial_balance",

                    self.initial_balance

                )

            )

        )



        self.fee_rate = Decimal(

            str(

                state.get(

                    "fee_rate",

                    self.fee_rate

                )

            )

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



        self.execution_history = list(

            state.get(

                "execution_history",

                []

            )

        )



        self.executions = state.get(

            "executions",

            0

        )



        self.errors = state.get(

            "errors",

            0

        )



        self.started = state.get(

            "started",

            self.now()

        )



        logger.info(

            "Paper execution state restored"

        )



    # =====================================================
    # RESET ENGINE
    # =====================================================


    def reset(self):


        self.balance = (

            self.initial_balance

        )


        self.positions.clear()


        self.trade_history.clear()


        self.execution_history.clear()


        self.executions = 0


        self.errors = 0



        logger.warning(

            "Paper execution engine reset"

        )



    # =====================================================
    # OPEN POSITIONS REPORT
    # =====================================================


    def positions_report(self):


        return {


            "count":

                self.open_positions,


            "positions":

                list(

                    self.positions.values()

                ),

        }



    # =====================================================
    # MAGIC METHODS
    # =====================================================


    def __repr__(self):


        return (

            f"<{self.name} "

            f"version={self.VERSION} "

            f"mode={self.mode} "

            f"balance="

            f"{float(self.balance):.2f} "

            f"positions="

            f"{self.open_positions} "

            f"executions="

            f"{self.executions}>"

        )



    def __str__(self):


        return (

            f"{self.name} "

            f"[{self.mode}] "

            f"Balance="

            f"{float(self.balance):.2f}"

        )