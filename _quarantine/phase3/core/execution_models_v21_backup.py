"""
============================================================
ATLAS EXECUTION MODELS v21.0
============================================================

Unified Execution Data Contracts

Used by:

- Paper Execution Engine
- Live Execution Engine
- Backtest Engine
- Exchange Adapters

============================================================
"""


from __future__ import annotations


from dataclasses import dataclass, field
from typing import Any
from datetime import datetime, UTC



# ==========================================================
# REQUEST
# ==========================================================


@dataclass
class ExecutionRequest:


    symbol: str


    action: str


    price: float


    amount: float


    strategy: str = "Unknown"


    confidence: float = 0.0


    risk: str = "MEDIUM"


    metadata: dict[str, Any] = field(
        default_factory=dict
    )



    def normalized_action(self):

        return self.action.upper()




# ==========================================================
# RESULT
# ==========================================================


@dataclass
class ExecutionResult:


    success: bool


    status: str


    message: str



    execution_id: str | None = None


    position_id: str | None = None



    symbol: str | None = None


    action: str | None = None



    filled_price: float | None = None


    filled_amount: float | None = None



    fee: float = 0.0



    pnl: float = 0.0



    metadata: dict[str, Any] = field(
        default_factory=dict
    )



    timestamp: str = field(
        default_factory=lambda:
        datetime.now(
            UTC
        ).isoformat()
    )