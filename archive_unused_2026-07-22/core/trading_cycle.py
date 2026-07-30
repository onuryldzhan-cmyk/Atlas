"""
Atlas AI Trading Cycle v4

Full Decision Pipeline
Data -> Analysis -> Fusion -> Confidence -> Decision -> Risk -> Execution
"""


import logging


from core.data_provider import DataProvider
from core.technical_analyzer import TechnicalAnalyzer
from core.market_intelligence import MarketIntelligence
from core.signal_fusion import SignalFusion
from core.strategy_competition import StrategyCompetition
from core.confidence_engine import ConfidenceEngine
from core.decision_engine import DecisionEngine
from core.capital_allocator import CapitalAllocator
from core.executor import Executor
from core.risk_manager import RiskManager
from core.auto_manager import AutoManager


logger = logging.getLogger("AtlasAI")



class TradingCycle:


    def __init__(
        self,
        trader
    ):


        self.data_provider = DataProvider()

        self.tech_analyzer = TechnicalAnalyzer()

        self.market_intel = MarketIntelligence()

        self.signal_fusion = SignalFusion()

        self.strategy_competition = StrategyCompetition()

        self.confidence_engine = ConfidenceEngine()

        self.decision_engine = DecisionEngine()

        self.capital_allocator = CapitalAllocator()

        self.executor = Executor(trader)

        self.risk_manager = RiskManager()

        self.auto_manager = AutoManager()



    def run(
        self,
        symbol: str
    ):


        logger.info(
            f"TradingCycle başladı: {symbol}"
        )



        candles = self.data_provider.get_klines(
            symbol
        )


        if not candles or len(candles) < 50:


            logger.warning(
                f"{symbol} yeterli veri yok"
            )

            return None




        tech = self.tech_analyzer.analyze(
            candles
        )


        market = self.market_intel.analyze(
            symbol,
            candles
        )



        fusion = self.signal_fusion.fuse(
            tech,
            market
        )



        strategy = self.strategy_competition.run(
            fusion
        )



        confidence = self.confidence_engine.calculate(
            fusion,
            strategy
        )



        decision = self.decision_engine.decide(
            fusion,
            confidence
        )



        action = decision.get(
            "action",
            "BEKLE"
        )



        # ==========================
        # CAPITAL
        # ==========================


        size = self.capital_allocator.allocate(
            decision,
            confidence
        )



        # ==========================
        # RISK
        # ==========================


        risk = self.risk_manager.calculate(

            capital=1000,

            entry_price=tech.get(
                "last_close",
                0
            ),

            action=action,

            confidence=confidence

        )



        if not risk.get(
            "approved",
            False
        ):


            decision["action"] = "BEKLE"


            decision["reason"] = risk.get(
                "reason",
                "Risk reddetti"
            )


        else:


            decision["stop_loss"] = risk.get(
                "stop_loss",
                0
            )


            decision["take_profit"] = risk.get(
                "take_profit",
                0
            )



        # ==========================
        # EXECUTION
        # ==========================


        if decision.get(
            "action"
        ) in [
            "BUY",
            "SELL"
        ]:


            result = self.executor.execute(

                symbol,

                decision["action"],

                size,

                decision.get(
                    "stop_loss",
                    0
                ),

                decision.get(
                    "take_profit",
                    0
                )

            )


            logger.info(
                f"Executor sonucu: {result}"
            )


        else:


            logger.info(
                f"{symbol} işlem açılmadı: {decision.get('reason')}"
            )



        # ==========================
        # AUTO MANAGEMENT
        # ==========================


        self.auto_manager.monitor()



        return {


            "symbol": symbol,

            "decision": decision,

            "confidence": confidence,

            "fusion": fusion,

            "risk": risk

        }