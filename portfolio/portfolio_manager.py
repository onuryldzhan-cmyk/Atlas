"""
Atlas AI Portfolio Manager v7.0

Professional Portfolio Controller

Responsibilities:
- Capital management
- Position lifecycle
- Risk integration
- Paper trading compatibility
- Database synchronization
"""


from typing import Dict, List, Optional

from core.database import DatabaseManager
from portfolio.capital_manager import CapitalManager



class PortfolioManager:


    def __init__(self, initial_capital=10000.0):


        self.initial_capital = initial_capital


        self.db = DatabaseManager()


        # TEK SERMAYE MOTORU
        self.capital_manager = CapitalManager(
            initial_capital
        )


        self.positions = {}


        self.load_positions()



    # ==================================================
    # LOAD
    # ==================================================

    def load_positions(self):


        try:

            trades = self.db.get_open_trades()


            for trade in trades:

                self.positions[
                    trade["symbol"]
                ] = trade



            print(
                f"[PORTFOLIO] "
                f"{len(self.positions)} pozisyon yüklendi."
            )


        except Exception as e:


            print(
                f"[PORTFOLIO LOAD ERROR] {e}"
            )



    # ==================================================
    # OPEN TRADE
    # PaperTrader compatibility
    # ==================================================

    def open_trade(
        self,
        symbol,
        action,
        entry,
        stop_loss,
        take_profit,
        size,
        confidence=50
    ):


        side = (
            "LONG"
            if action=="BUY"
            else "SHORT"
        )



        result = self.capital_manager.open_position(

            symbol=symbol,

            price=entry,

            amount=size,

            confidence=confidence,

            side=side
        )



        if not result["success"]:


            print(
                "[PORTFOLIO BLOCKED]",
                result["error"]
            )

            return False



        self.positions[symbol] = {


            "symbol":symbol,

            "action":action,

            "entry":entry,

            "size":size,

            "stop_loss":stop_loss,

            "take_profit":take_profit

        }



        print(
            f"[PORTFOLIO OPEN] "
            f"{symbol} {action}"
        )


        return True





    # ==================================================
    # BACKWARD COMPATIBILITY
    # ==================================================

    def add_position(
        self,
        symbol,
        action,
        entry,
        stop_loss,
        take_profit,
        size
    ):


        return self.open_trade(

            symbol,

            action,

            entry,

            stop_loss,

            take_profit,

            size

        )




    # ==================================================
    # CLOSE TRADE
    # ==================================================

    def close_trade(
        self,
        symbol=None,
        profit=0.0,
        **kwargs
    ):


        # eski PaperTrader çağrısı:
        #
        # close_trade(profit)
        #
        if isinstance(symbol,(int,float)):

            profit = symbol


            if self.positions:

                symbol = list(
                    self.positions.keys()
                )[0]


        if symbol is None:

            return False



        if symbol in self.positions:


            del self.positions[symbol]



        print(

            f"[PORTFOLIO CLOSE] "
            f"{symbol} "
            f"PNL:{profit:.2f}"

        )


        return True




    # ==================================================
    # POSITION CHECK
    # ==================================================

    def has_position(
        self,
        symbol
    ):


        return symbol in self.positions




    def get_position(
        self,
        symbol
    ):


        return self.positions.get(
            symbol
        )




    def get_open_positions(self):


        return list(
            self.positions.values()
        )




    # ==================================================
    # RISK REPORT
    # ==================================================

    def report(self):


        return self.capital_manager.get_available_capital()




    # ==================================================
    # PERFORMANCE
    # ==================================================

    def performance(self):


        return {


            "capital":

                self.capital_manager.total_capital,


            "open_positions":

                len(self.positions),


            "trades":

                self.capital_manager.total_trades,


            "wins":

                self.capital_manager.win_count,


            "losses":

                self.capital_manager.loss_count

        }




    # ==================================================
    # RESET
    # ==================================================

    def reset(self):


        self.positions={}


        self.capital_manager.reset_daily()



    # ==================================================
    # MAGIC
    # ==================================================

    def __len__(self):

        return len(
            self.positions
        )



    def __repr__(self):


        return (

            "<Atlas PortfolioManager v7.0 | "

            f"Positions={len(self.positions)} | "

            f"Capital={self.capital_manager.total_capital}>"

        )