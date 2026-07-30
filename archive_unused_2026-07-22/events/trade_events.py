"""
Trade Events
"""


from .base_event import BaseEvent



class TradeExecutedEvent(BaseEvent):


    def __init__(
            self,
            symbol,
            action,
            quantity,
            price
    ):

        super().__init__(
            "TRADE_EXECUTED"
        )


        self.symbol = symbol

        self.action = action

        self.quantity = quantity

        self.price = price