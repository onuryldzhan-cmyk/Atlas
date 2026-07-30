"""
Atlas Position State
====================

Defines every lifecycle state a position can have.

This enum is shared by:

- Position
- PositionManager
- ExecutionManager
- PaperTrader
- PortfolioManager
- RiskEngine
- LearningEngine

Author:
Atlas AI v9
"""

from enum import Enum


class PositionState(str, Enum):
    """
    Lifecycle state of a trading position.
    """

    PENDING = "PENDING"

    OPEN = "OPEN"

    PARTIALLY_CLOSED = "PARTIALLY_CLOSED"

    CLOSING = "CLOSING"

    CLOSED = "CLOSED"

    CANCELLED = "CANCELLED"

    ERROR = "ERROR"

    def is_active(self) -> bool:
        """
        Position is still active.
        """
        return self in {
            PositionState.PENDING,
            PositionState.OPEN,
            PositionState.PARTIALLY_CLOSED,
            PositionState.CLOSING,
        }

    def is_finished(self) -> bool:
        """
        Position lifecycle completed.
        """
        return self in {
            PositionState.CLOSED,
            PositionState.CANCELLED,
            PositionState.ERROR,
        }