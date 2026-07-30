"""
Atlas AI System Configuration
Central Configuration Hub
Version: Atlas v7 Compatible
"""

import os

from pathlib import Path
from typing import Dict, List
from dataclasses import dataclass, field


# ==========================================================
# PROJECT PATHS
# ==========================================================

PROJECT_ROOT = Path(__file__).parent.parent


PATHS = {

    "root": PROJECT_ROOT,

    "core": PROJECT_ROOT / "core",

    "config": PROJECT_ROOT / "config",

    "data": PROJECT_ROOT / "data",

    "logs": PROJECT_ROOT / "logs",

    "database": PROJECT_ROOT / "database",

    "portfolio": PROJECT_ROOT / "portfolio",

    "strategy": PROJECT_ROOT / "strategy",

    "risk": PROJECT_ROOT / "risk",

    "execution": PROJECT_ROOT / "execution",

    "analytics": PROJECT_ROOT / "analytics",

    "learning": PROJECT_ROOT / "learning",

    "events": PROJECT_ROOT / "events",

    "dashboard": PROJECT_ROOT / "dashboard",

}


for path in PATHS.values():

    path.mkdir(
        parents=True,
        exist_ok=True
    )



# ==========================================================
# TRADING CONFIG
# ==========================================================


@dataclass
class TradingConfig:


    MODE: str = "SIMULATION"


    PAPER_BALANCE: float = 10000.0


    INITIAL_CAPITAL: float = 10000.0


    BASE_CURRENCY: str = "USDT"



    EXCHANGE: str = "BINANCE"


    MARKET_TYPE: str = "futures"



    TIMEFRAME: str = "5m"


    CANDLE_LIMIT: int = 500



    WATCHLIST: List[str] = field(
        default_factory=lambda:
        [

            "BTCUSDT",

            "ETHUSDT",

            "SOLUSDT",

            "ADAUSDT",

            "DOTUSDT",

            "LINKUSDT",

            "AVAXUSDT",

            "MATICUSDT",

            "UNIUSDT",

            "LTCUSDT"

        ]
    )



# ==========================================================
# RISK CONFIG
# ==========================================================


@dataclass
class RiskConfig:


    MAX_POSITIONS: int = 10


    MAX_DAILY_LOSS_PCT: float = 0.05


    MAX_TOTAL_LOSS_PCT: float = 0.20


    STOP_LOSS_PCT: float = 0.005


    TAKE_PROFIT_PCT: float = 0.10



    RISK_PER_TRADE_PCT: float = 0.01



    KILL_SWITCH_ENABLED: bool = True


    KILL_SWITCH_THRESHOLD: float = 0.15




# ==========================================================
# SIGNAL CONFIG
# ==========================================================


@dataclass
class SignalConfig:


    MIN_CONFIDENCE: float = 0.60


    TECHNICAL_WEIGHT: float = 0.35


    FUNDAMENTAL_WEIGHT: float = 0.15


    SENTIMENT_WEIGHT: float = 0.20


    ML_WEIGHT: float = 0.30



# ==========================================================
# API CONFIG
# ==========================================================


@dataclass
class APIConfig:


    API_KEY: str = field(
        default_factory=lambda:
        os.getenv(
            "BINANCE_API_KEY",
            ""
        )
    )


    API_SECRET: str = field(
        default_factory=lambda:
        os.getenv(
            "BINANCE_API_SECRET",
            ""
        )
    )


    USE_TESTNET: bool = True


    TIMEOUT_SECONDS: int = 30



# ==========================================================
# LEARNING CONFIG
# ==========================================================


@dataclass
class LearningConfig:


    AUTO_LEARNING_ENABLED: bool = True


    FEEDBACK_ENABLED: bool = True


    MIN_TRADES_FOR_RETRAIN: int = 50




# ==========================================================
# SYSTEM CONFIG
# ==========================================================


@dataclass
class SystemConfig:


    VERSION: str = "7.1"


    DEBUG_MODE: bool = False


    LOG_LEVEL: str = "INFO"



# ==========================================================
# CONFIG INSTANCES
# ==========================================================


TRADING = TradingConfig()


RISK = RiskConfig()


SIGNAL = SignalConfig()


API = APIConfig()


LEARNING = LearningConfig()


SYSTEM = SystemConfig()



# ==========================================================
# ATLAS CAPITAL RISK ENGINE
# ==========================================================


PAPER_BALANCE = TRADING.PAPER_BALANCE



RISK_PROFILES = {


    "low": {


        # Sermaye
        "capital_percent": 0.30,


        # Risk
        "risk_per_trade": 0.005,


        "max_positions": 5,


        "max_position_percent": 0.10,


        "leverage": 1,


        # hedef
        "take_profit": 0.06,


        "min_confidence": 60,


        "coins":

        [

            "BTCUSDT",

            "ETHUSDT"

        ]

    },




    "medium": {


        "capital_percent": 0.50,


        "risk_per_trade": 0.01,


        "max_positions": 10,


        "max_position_percent": 0.15,


        "leverage": 2,


        "take_profit": 0.10,


        "min_confidence": 70,


        "coins":

        [

            "SOLUSDT",

            "LINKUSDT",

            "AVAXUSDT",

            "DOTUSDT"

        ]

    },





    "high": {


        "capital_percent": 0.20,


        "risk_per_trade": 0.02,


        "max_positions": 5,


        "max_position_percent": 0.20,


        "leverage": 3,


        "take_profit": 0.15,


        "min_confidence": 80,


        "coins":

        [

            "ADAUSDT",

            "MATICUSDT",

            "UNIUSDT",

            "LTCUSDT"

        ]

    }


}




# ==========================================================
# LEGACY VARIABLES
# ==========================================================


MAX_POSITIONS = RISK.MAX_POSITIONS


MAX_DAILY_LOSS = RISK.MAX_DAILY_LOSS_PCT


MODE = TRADING.MODE


KILL_SWITCH_ENABLED = RISK.KILL_SWITCH_ENABLED




# ==========================================================
# HELPERS
# ==========================================================


def get_config_summary():


    return {


        "version":
        SYSTEM.VERSION,


        "mode":
        TRADING.MODE,


        "exchange":
        TRADING.EXCHANGE,


        "capital":
        TRADING.PAPER_BALANCE,


        "max_positions":
        MAX_POSITIONS,


        "risk_profiles":
        list(
            RISK_PROFILES.keys()
        )


    }




def update_setting(
        key,
        value
):


    for config in [

        TRADING,

        RISK,

        SIGNAL,

        API,

        LEARNING,

        SYSTEM

    ]:


        if hasattr(
            config,
            key
        ):

            setattr(
                config,
                key,
                value
            )

            return True



    return False




# ==========================================================
# TEST
# ==========================================================


if __name__ == "__main__":


    print(
        "Atlas Settings Test"
    )


    print(
        get_config_summary()
    )