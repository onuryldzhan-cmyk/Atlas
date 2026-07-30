from intelligence.pipeline.atlas_intelligence_pipeline import AtlasIntelligencePipeline
from intelligence.decision.decision_engine import DecisionEngine
from intelligence.risk.risk_intelligence import RiskIntelligence
from intelligence.execution.execution_engine import ExecutionEngine
from intelligence.memory.trade_memory import TradeMemory



class IntelligenceCore:


    VERSION = "1.0"



    def __init__(self):

        self.pipeline = AtlasIntelligencePipeline()

        self.decision = DecisionEngine()

        self.risk = RiskIntelligence()

        self.execution = ExecutionEngine()

        self.memory = TradeMemory()



    def run(self):


        analysis = self.pipeline.analyze_market()


        first_coin = analysis["opportunities"][0]



        decision = self.decision.decide(

            opportunity_score=first_coin["score"],

            strategy_confidence=analysis["strategy"]["confidence"],

            regime=analysis["market"]["regime"]

        )



        risk = self.risk.analyze(

            decision=decision["decision"],

            confidence=analysis["strategy"]["confidence"],

            balance=10000

        )



        order = self.execution.execute(

            symbol=first_coin["symbol"],

            decision=decision["decision"],

            position_size=risk["position_size"],

            strategy=analysis["strategy"]["strategy"]

        )



        self.memory.remember(order)



        return {


            "analysis": analysis,

            "decision": decision,

            "risk": risk,

            "order": order

        }