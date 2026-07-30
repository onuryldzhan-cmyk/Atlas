"""
Atlas AI Interfaces v5.0

Defines contracts for Atlas modules.

Interfaces contain no business logic.
They only define expected behavior.
"""


from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Dict, Any, List



class MarketProvider(ABC):
    """
    Market data source contract.
    """


    @abstractmethod
    def get_price(
        self,
        symbol: str
    ) -> float:
        pass



    @abstractmethod
    def get_history(
        self,
        symbol: str,
        limit: int = 100
    ) -> List[float]:
        pass



class Analyzer(ABC):
    """
    Market analysis contract.
    """


    @abstractmethod
    def analyze(
        self,
        data: Dict[str, Any]
    ) -> Dict[str, Any]:
        pass



class Strategy(ABC):
    """
    Trading strategy contract.
    """


    @abstractmethod
    def generate_signal(
        self,
        analysis: Dict[str, Any]
    ) -> Dict[str, Any]:
        pass



class RiskManager(ABC):
    """
    Risk control contract.
    """


    @abstractmethod
    def calculate_risk(
        self,
        decision: Dict[str, Any]
    ) -> Dict[str, Any]:
        pass



class Executor(ABC):
    """
    Execution contract.
    """


    @abstractmethod
    def execute(
        self,
        order: Dict[str, Any]
    ) -> Dict[str, Any]:
        pass



class MemorySystem(ABC):
    """
    Learning memory contract.
    """


    @abstractmethod
    def remember(
        self,
        item: Dict[str, Any]
    ):
        pass



    @abstractmethod
    def recall(
        self,
        query: Dict[str, Any]
    ):
        pass