"""
============================================================
ATLAS AI EXECUTION CONTRACTS v2.0
============================================================

Execution Layer Contracts

Every execution backend MUST implement the same API.

Supported engines

- Paper
- Live
- Backtest
- Simulation
- Replay

============================================================
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Protocol

from core.execution_models import (
    ExecutionRequest,
    ExecutionResult,
)


# ==========================================================
# MAIN EXECUTION CONTRACT
# ==========================================================

class ExecutionEngine(ABC):

    @property
    @abstractmethod
    def name(self) -> str:
        """Engine name"""

    @property
    @abstractmethod
    def mode(self) -> str:
        """Execution mode"""

    @abstractmethod
    def execute(
        self,
        request: ExecutionRequest,
    ) -> ExecutionResult:
        """
        Execute one order.
        """

    @abstractmethod
    def health(self) -> dict:
        """
        Component health information.
        """

    @abstractmethod
    def status(self) -> dict:
        """
        Runtime statistics.
        """

    @abstractmethod
    def reset(self) -> None:
        """
        Reset runtime state.
        """


# ==========================================================
# OPTIONAL PROTOCOLS
# ==========================================================

class SupportsHealth(Protocol):

    def health(self) -> dict:
        ...


class SupportsStatus(Protocol):

    def status(self) -> dict:
        ...


class SupportsReset(Protocol):

    def reset(self) -> None:
        ...


class SupportsDiagnostics(Protocol):

    def diagnostics(self) -> dict:
        ...