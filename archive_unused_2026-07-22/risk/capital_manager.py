"""
Atlas AI v5.1
Capital Manager

Görevler:
- Sermaye yönetimi
- Risk kontrolü
- PositionManager entegrasyonu
- PnL takibi
- Paper Trading altyapısı
"""


from typing import Dict


from risk.position_manager import PositionManager




class CapitalManager:



    def __init__(
        self,
        initial_capital: float = 10000
    ):


        self.initial_capital = initial_capital

        self.cash_balance = initial_capital


        self.realized_pnl = 0.0


        self.total_trades = 0

        self.win_count = 0

        self.loss_count = 0



        self.daily_loss = 0.0


        self.max_daily_loss = (
            initial_capital * 0.05
        )


        self.max_positions = 5



        self.position_manager = (
            PositionManager()
        )



        print(
            "💰 Atlas CapitalManager v5.1 hazır"
        )


        print(
            f"Sermaye: {initial_capital:.2f} USDT"
        )





    def available_capital(self):

        return self.cash_balance





    def open_trade(
        self,
        symbol,
        price,
        amount,
        side="LONG",
        risk_level="medium",
        confidence=0
    ):



        if len(
            self.position_manager.positions
        ) >= self.max_positions:


            return {

                "success":False,

                "reason":
                "Max pozisyon limiti"

            }





        cost = (
            price *
            amount
        )



        if cost > self.cash_balance:


            return {

                "success":False,

                "reason":
                "Yetersiz bakiye"

            }




        position = (
            self.position_manager
            .create_position(
                symbol,
                price,
                amount,
                side,
                risk_level,
                confidence
            )
        )



        self.cash_balance -= cost


        self.total_trades += 1




        return {


            "success":True,


            "position":
            position.to_dict(),


            "cash":
            self.cash_balance


        }






    def close_trade(
        self,
        position_id,
        exit_price,
        reason="MANUAL"
    ):


        position = (
            self.position_manager
            .get_position(position_id)
        )


        if not position:


            return {

                "success":False,

                "reason":
                "Pozisyon yok"

            }





        pnl = position.calculate_pnl(
            exit_price
        )



        returned_value = (
            position.amount *
            exit_price
        )



        self.cash_balance += (
            returned_value
        )



        self.realized_pnl += pnl



        if pnl >= 0:

            self.win_count += 1

        else:

            self.loss_count += 1

            self.daily_loss += abs(pnl)





        self.position_manager.close_position(
            position_id,
            exit_price,
            reason
        )




        return {


            "success":True,


            "symbol":
            position.symbol,


            "pnl":
            pnl,


            "cash":
            self.cash_balance

        }






    def portfolio_value(
        self,
        prices:Dict[str,float]
    ):


        value = self.cash_balance



        for position in (
            self.position_manager.positions.values()
        ):


            if position.symbol in prices:


                value += (
                    position.amount *
                    prices[position.symbol]
                )



        return value





    def report(
        self,
        prices=None
    ):


        value = (

            self.portfolio_value(prices)

            if prices

            else self.cash_balance

        )



        win_rate = (

            self.win_count /
            self.total_trades

            if self.total_trades

            else 0

        )



        return {


            "initial":
            self.initial_capital,


            "cash":
            self.cash_balance,


            "portfolio_value":
            value,


            "realized_pnl":
            self.realized_pnl,


            "trades":
            self.total_trades,


            "win_rate":
            win_rate*100,


            "open_positions":
            len(
                self.position_manager.positions
            )


        }