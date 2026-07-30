"""
Atlas AI Intelligence Brain v2.0

Core intelligence layer.

Responsibilities:

- Multi Agent Analysis
- World Model Context
- Reasoning Engine
- Memory Feedback
- Decision Synthesis


Architecture:

Market Data
      |
      v
World Model
      |
      v
Multi Agent
      |
      v
Reasoning
      |
      v
Memory
      |
      v
Decision


This module does NOT:
- Execute trades
- Manage portfolio
- Control risk execution

Execution belongs to core.execution_manager
"""


from datetime import datetime
from typing import Dict, List, Any
import logging



logger = logging.getLogger(
    "AtlasAI.Intelligence"
)



MODULES_AVAILABLE = False



try:

    from .atlas_memory_core import (
        AtlasMemoryCore
    )

    from .atlas_reasoning_engine import (
        AtlasReasoningEngine
    )

    from .atlas_world_model import (
        AtlasWorldModel
    )

    from .atlas_multi_agent import (
        AtlasMultiAgent
    )


    MODULES_AVAILABLE = True


except Exception as e:

    logger.error(
        f"Intelligence modules unavailable: {e}"
    )




class AtlasBrain:


    def __init__(
        self,
        config: Dict = None
    ):


        self.config = config or {}


        self.status = "INITIALIZING"


        self.session_id = (
            f"atlas_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        )


        self.memory = None

        self.reasoning = None

        self.world = None

        self.multi_agent = None



        self._initialize_modules()



        self.status = "ACTIVE"



        logger.info(
            "Atlas Intelligence Brain v2.0 initialized."
        )



    # ==================================================
    # MODULE INITIALIZATION
    # ==================================================


    def _initialize_modules(self):


        if not MODULES_AVAILABLE:


            logger.error(
                "Required intelligence modules missing."
            )

            return



        self.memory = AtlasMemoryCore(
            data_dir="memory_data"
        )



        self.reasoning = AtlasReasoningEngine(
            data_dir="memory_data"
        )



        self.world = AtlasWorldModel(
            data_dir="memory_data"
        )



        self.multi_agent = AtlasMultiAgent(
            data_dir="memory_data"
        )



        print(
            "[INTELLIGENCE] Atlas Intelligence modules loaded"
        )



    # ==================================================
    # MAIN DECISION PIPELINE
    # ==================================================


    def analyze_and_decide(
        self,
        symbol: str,
        market_data: Dict
    ) -> Dict:


        if self.status != "ACTIVE":

            return {

                "symbol": symbol,

                "action": "hold",

                "confidence": 0,

                "risk_level": "high"

            }



        print("\n" + "=" * 60)

        print(
            f"ATLAS INTELLIGENCE ANALYSIS : {symbol}"
        )

        print("=" * 60)



        context = self._world_analysis(
            symbol
        )



        signals = self._agent_analysis(
            symbol,
            market_data
        )



        collective = (
            self.multi_agent
            .collective_decision(
                symbol
            )
            if self.multi_agent
            else
            {
                "decision":"hold",
                "confidence":0
            }
        )



        reasoning = self._reasoning_analysis(
            symbol,
            market_data
        )



        memory = self._memory_feedback(
            symbol
        )



        decision = self._combine(

            symbol,

            collective,

            reasoning,

            memory

        )



        self._store_decision(
            symbol,
            decision
        )



        print(
            f"FINAL INTELLIGENCE: {decision['action'].upper()} "
            f"| Confidence {decision['confidence']}"
        )



        return decision