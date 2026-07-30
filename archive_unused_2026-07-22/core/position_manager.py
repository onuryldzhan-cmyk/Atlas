"""
Atlas AI Position Manager v1

Central position management layer.
"""

from __future__ import annotations

from datetime import datetime
from typing import Dict, Optional, List
import uuid


class PositionManager:

    def __init__(self):
        self.positions: Dict[str, dict] = {}

    def open_position(
        self,
        symbol: str,
        side: str,
        entry_price: float,
        position_size: float,
        stop_loss: float,
        take_profit: float,
        confidence: float,
        risk_amount: float
    ) -> dict:

        if self.has_open_position(symbol):
            raise ValueError(
                f"{symbol} için zaten açık pozisyon var."
            )

        trade = {
            "id": str(uuid.uuid4()),
            "symbol": symbol,
            "side": side,
            "entry_price": entry_price,
            "current_price": entry_price,
            "position_size": position_size,
            "stop_loss": stop_loss,
            "take_profit": take_profit,
            "confidence": confidence,
            "risk_amount": risk_amount,
            "opened_at": datetime.now().isoformat(),
            "closed_at": None,
            "status": "OPEN",
            "pnl": 0.0
        }

        self.positions[symbol] = trade

        return trade

    def close_position(
        self,
        symbol: str,
        exit_price: float
    ) -> Optional[dict]:

        trade = self.positions.get(symbol)

        if trade is None:
            return None

        trade["current_price"] = exit_price

        trade["closed_at"] = datetime.now().isoformat()

        trade["status"] = "CLOSED"

        trade["pnl"] = self.calculate_pnl(
            symbol,
            exit_price
        )

        return trade

    def update_price(
        self,
        symbol: str,
        current_price: float
    ):

        trade = self.positions.get(symbol)

        if trade is None:
            return

        trade["current_price"] = current_price

        trade["pnl"] = self.calculate_pnl(
            symbol,
            current_price
        )

    def calculate_pnl(
        self,
        symbol: str,
        current_price: float
    ) -> float:

        trade = self.positions.get(symbol)

        if trade is None:
            return 0.0

        entry = trade["entry_price"]
        size = trade["position_size"]

        if trade["side"] == "BUY":
            pnl = (current_price - entry) * size
        else:
            pnl = (entry - current_price) * size

        return round(pnl, 2)

    def has_open_position(
        self,
        symbol: str
    ) -> bool:

        trade = self.positions.get(symbol)

        if trade is None:
            return False

        return trade["status"] == "OPEN"

    def get_position(
        self,
        symbol: str
    ) -> Optional[dict]:

        return self.positions.get(symbol)

    def get_open_positions(self) -> List[dict]:

        return [
            trade
            for trade in self.positions.values()
            if trade["status"] == "OPEN"
        ]

    def total_open_positions(self) -> int:

        return len(
            self.get_open_positions()
        )

    def total_risk(self) -> float:

        total = 0.0

        for trade in self.get_open_positions():
            total += trade["risk_amount"]

        return round(total, 2)

    def total_unrealized_pnl(self) -> float:

        total = 0.0

        for trade in self.get_open_positions():
            total += trade["pnl"]

        return round(total, 2)

    def summary(self) -> dict:

        return {
            "open_positions": self.total_open_positions(),
            "total_risk": self.total_risk(),
            "unrealized_pnl": self.total_unrealized_pnl()
        }