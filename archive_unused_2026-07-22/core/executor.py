"""
Atlas AI Executor v6.3

Autonomous Execution Layer

Decision
    ↓
Executor
    ↓
TradeTracker
    ↓
Portfolio
    ↓
Learning
"""

import logging
from datetime import datetime


logger = logging.getLogger("AtlasAI")



class Executor:


    def __init__(
        self,
        trader=None,
        trade_tracker=None,
        event_manager=None
    ):


        self.trader = trader

        self.trade_tracker = trade_tracker

        self.events = event_manager



    def execute(
        self,
        symbol,
        action,
        size,
        stop_loss,
        take_profit,
        confidence=0,
        strategy="UNKNOWN",
        regime="UNKNOWN"
    ):


        if action not in [

            "BUY",
            "SELL"

        ]:


            return {

                "success":False,

                "status":"REJECTED",

                "reason":"Invalid action"

            }



        try:


            logger.info(

                f"[EXECUTOR] {symbol} {action}"

            )



            trade_result = None



            # PAPER / LIVE TRADER

            if self.trader:


                trade_result = self.trader.open_trade(

                    symbol,

                    action,

                    size,

                    stop_loss,

                    take_profit

                )



            tracker_trade = None



            # TRACK LEARNING TRADE

            if self.trade_tracker:


                tracker_trade = self.trade_tracker.open_trade(

                    symbol=symbol,

                    action=action,

                    entry=size,

                    stop_loss=stop_loss,

                    take_profit=take_profit,

                    confidence=confidence,

                    strategy=strategy,

                    regime=regime

                )



            result = {


                "success":True,

                "status":"OPEN",

                "symbol":symbol,

                "action":action,

                "size":size,

                "stop_loss":stop_loss,

                "take_profit":take_profit,

                "confidence":confidence,

                "strategy":strategy,

                "regime":regime,

                "time":datetime.now().isoformat(),

                "tracker":tracker_trade,

                "broker":trade_result


            }



            if self.events:


                self.events.emit(

                    "TRADE_OPENED",

                    result

                )



            logger.info(

                f"[EXECUTOR] Trade opened {symbol}"

            )



            return result



        except Exception as e:


            logger.exception(e)


            return {


                "success":False,

                "status":"ERROR",

                "reason":str(e)


            }