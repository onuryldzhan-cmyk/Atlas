"""
Atlas AI v5.1
Position Engine

Görevler:
- LONG / SHORT pozisyon yönetimi
- Trailing stop
- Partial close
- PnL hesaplama
- Position serialization
"""


from dataclasses import dataclass, field
from typing import Dict, Any
from datetime import datetime
import uuid



@dataclass
class Position:


    symbol: str

    entry_price: float

    amount: float


    side: str = "LONG"

    risk_level: str = "medium"

    confidence_at_entry: float = 0.0



    position_id: str = field(
        default_factory=lambda:
        str(uuid.uuid4())[:8]
    )


    created_at: str = field(
        default_factory=lambda:
        datetime.now().isoformat()
    )


    updated_at: str = field(
        default_factory=lambda:
        datetime.now().isoformat()
    )



    # Risk sistemi

    stop_loss_price: float = 0.0

    trailing_stop_enabled: bool = True

    trailing_stop_percent: float = 0.005


    highest_price: float = 0.0

    lowest_price: float = 0.0

    current_stop_price: float = 0.0



    # Kapanış bilgileri

    exit_price: float = 0.0

    exit_reason: str = ""

    realized_pnl: float = 0.0

    fee_paid: float = 0.0



    status: str = "OPEN"




    def __post_init__(self):

        self.highest_price = self.entry_price

        self.lowest_price = self.entry_price


        self._initialize_stop()




    def _initialize_stop(self):

        stop_percent = 0.005


        if self.side == "LONG":

            self.stop_loss_price = (
                self.entry_price *
                (1-stop_percent)
            )


        else:

            self.stop_loss_price = (
                self.entry_price *
                (1+stop_percent)
            )


        self.current_stop_price = (
            self.stop_loss_price
        )





    def update_price(
        self,
        price: float
    ):

        self.updated_at = (
            datetime.now().isoformat()
        )


        if self.side == "LONG":


            if price > self.highest_price:

                self.highest_price = price


                new_stop = (
                    self.highest_price *
                    (1-self.trailing_stop_percent)
                )


                if new_stop > self.current_stop_price:

                    self.current_stop_price = new_stop



        else:


            if price < self.lowest_price:

                self.lowest_price = price


                new_stop = (
                    self.lowest_price *
                    (1+self.trailing_stop_percent)
                )


                if new_stop < self.current_stop_price:

                    self.current_stop_price = new_stop





    def check_stop(
        self,
        price: float
    ):


        self.update_price(price)


        if self.side == "LONG":

            return price <= self.current_stop_price


        return price >= self.current_stop_price





    def calculate_pnl(
        self,
        current_price: float,
        amount=None
    ):


        if amount is None:

            amount = self.amount



        if self.side == "LONG":

            return (
                current_price -
                self.entry_price
            ) * amount


        else:

            return (
                self.entry_price -
                current_price
            ) * amount





    def close(
        self,
        price: float,
        reason: str = "MANUAL",
        fee: float = 0.0
    ):


        pnl = self.calculate_pnl(price)


        self.exit_price = price

        self.exit_reason = reason

        self.realized_pnl = pnl

        self.fee_paid = fee

        self.status = "CLOSED"

        self.amount = 0



        return pnl





    def partial_close(
        self,
        percent: float
    ):


        close_amount = (
            self.amount *
            percent
        )


        self.amount -= close_amount


        return close_amount





    def is_closed(self):

        return self.status == "CLOSED"





    def to_dict(self):

        return {


            "position_id":
            self.position_id,


            "symbol":
            self.symbol,


            "entry_price":
            self.entry_price,


            "amount":
            self.amount,


            "side":
            self.side,


            "risk_level":
            self.risk_level,


            "confidence":
            self.confidence_at_entry,


            "stop":
            self.current_stop_price,


            "status":
            self.status,


            "created_at":
            self.created_at,


            "exit_price":
            self.exit_price,


            "exit_reason":
            self.exit_reason,


            "realized_pnl":
            self.realized_pnl

        }