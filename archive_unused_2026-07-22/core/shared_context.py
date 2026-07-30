"""
Atlas Shared Context
Professional Context Object
"""

from dataclasses import dataclass, field
from typing import Any, Dict, List


@dataclass
class SharedContext:

    # ======================================
    # BASIC
    # ======================================

    symbol: str = ""
    timeframe: str = ""
    timestamp: str = ""

    # ======================================
    # PRICE
    # ======================================

    price: float = 0.0

    candles: list = field(default_factory=list)

    # ======================================
    # ANALYSIS
    # ======================================

    technical: Dict[str, Any] = field(default_factory=dict)

    market: Dict[str, Any] = field(default_factory=dict)

    regime: Dict[str, Any] = field(default_factory=dict)

    strategy: Dict[str, Any] = field(default_factory=dict)

    confidence: float = 0.0

    decision: Dict[str, Any] = field(default_factory=dict)

    opportunity: Dict[str, Any] = field(default_factory=dict)

    risk: Dict[str, Any] = field(default_factory=dict)

    pattern: Dict[str, Any] = field(default_factory=dict)

    outcome: Dict[str, Any] = field(default_factory=dict)

    learning: Dict[str, Any] = field(default_factory=dict)

    performance: Dict[str, Any] = field(default_factory=dict)

    # ======================================
    # FUTURE MODULES
    # ======================================

    news: Dict[str, Any] = field(default_factory=dict)

    macro: Dict[str, Any] = field(default_factory=dict)

    orderbook: Dict[str, Any] = field(default_factory=dict)

    sentiment: Dict[str, Any] = field(default_factory=dict)

    portfolio: Dict[str, Any] = field(default_factory=dict)

    execution: Dict[str, Any] = field(default_factory=dict)

    metadata: Dict[str, Any] = field(default_factory=dict)

    errors: List[str] = field(default_factory=list)

    # ======================================

    def reset(self):

        self.technical.clear()
        self.market.clear()
        self.regime.clear()
        self.strategy.clear()
        self.decision.clear()
        self.opportunity.clear()
        self.risk.clear()
        self.pattern.clear()
        self.outcome.clear()
        self.learning.clear()
        self.performance.clear()
        self.news.clear()
        self.macro.clear()
        self.orderbook.clear()
        self.sentiment.clear()
        self.portfolio.clear()
        self.execution.clear()
        self.metadata.clear()
        self.errors.clear()

        self.price = 0.0
        self.candles = []
        self.confidence = 0.0