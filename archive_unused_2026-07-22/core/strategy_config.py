"""
core/strategy_config.py

Tüm strateji parametrelerini merkezi olarak yönetir.
Döngüsel import hatası giderildi.
"""

from dataclasses import dataclass
from typing import Dict, Any, List

@dataclass(frozen=True)
class StrategyParams:
    name: str
    weight: float
    rsi_low: int
    rsi_high: int
    adx_threshold: int
    volatility_limit: float

class StrategyConfig:
    SCALPING = "Scalping"
    MOMENTUM = "Momentum"
    TREND_FOLLOWING = "Trend_Following"
    MEAN_REVERSION = "Mean_Reversion"
    SMC = "Smart_Money_Concepts"
    ICT = "ICT_Order_Flow"
    GRID = "Grid_Trading"
    BREAKOUT = "Breakout"

    _default_params = {
        SCALPING: StrategyParams(name=SCALPING, weight=1.0, rsi_low=30, rsi_high=70, adx_threshold=25, volatility_limit=0.02),
        MOMENTUM: StrategyParams(name=MOMENTUM, weight=1.0, rsi_low=25, rsi_high=75, adx_threshold=40, volatility_limit=0.03),
        TREND_FOLLOWING: StrategyParams(name=TREND_FOLLOWING, weight=1.0, rsi_low=20, rsi_high=80, adx_threshold=30, volatility_limit=0.04),
        MEAN_REVERSION: StrategyParams(name=MEAN_REVERSION, weight=1.2, rsi_low=20, rsi_high=80, adx_threshold=20, volatility_limit=0.05),
        SMC: StrategyParams(name=SMC, weight=1.5, rsi_low=25, rsi_high=70, adx_threshold=35, volatility_limit=0.02),
        ICT: StrategyParams(name=ICT, weight=1.5, rsi_low=30, rsi_high=65, adx_threshold=30, volatility_limit=0.02),
        GRID: StrategyParams(name=GRID, weight=0.8, rsi_low=40, rsi_high=60, adx_threshold=20, volatility_limit=0.01),
        BREAKOUT: StrategyParams(name=BREAKOUT, weight=1.3, rsi_low=30, rsi_high=70, adx_threshold=45, volatility_limit=0.05),
    }

    @classmethod
    def get_params(cls, strategy_name: str) -> StrategyParams:
        return cls._default_params.get(strategy_name, StrategyParams(name="Unknown", weight=1.0, rsi_low=30, rsi_high=70, adx_threshold=25, volatility_limit=0.03))

    @classmethod
    def get_all_strategies(cls) -> List[str]:
        return list(cls._default_params.keys())

    @classmethod
    def get_weights(cls) -> Dict[str, float]:
        return {name: p.weight for name, p in cls._default_params.items()}

    @classmethod
    def get_decision_thresholds(cls) -> Dict[str, int]:
        return {"BUY": 70, "SELL": 30, "NEUTRAL": 50}