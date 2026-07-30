"""
============================================================
ATLAS AI PROFESSIONAL PIPELINE TEST v7.2
============================================================

Full Integration Test

Architecture:

Market Intelligence
        |
Market Pipeline
        |
Intelligence Core
        |
Decision Engine
        |
Execution Manager
        |
Paper Execution Engine
        |
Position Controller


============================================================
"""


import json
import traceback



# ============================================================
# IMPORTS
# ============================================================


from core.market_pipeline import (
    MarketPipeline
)


from core.market_intelligence import (
    MarketIntelligence
)


from intelligence.core.intelligence_core import (
    IntelligenceCore
)


from core.decision_engine import (
    DecisionEngine
)


from core.paper_execution_engine import (
    PaperExecutionEngine
)


from core.execution_manager import (
    ExecutionManager
)


from core.position_controller import (
    PositionController
)





# ============================================================
# BUILD ATLAS
# ============================================================


def build_atlas():


    print("[INIT] Building Atlas components")



    # -------------------------------
    # Market Layer
    # -------------------------------


    market_intelligence = MarketIntelligence()



    pipeline = MarketPipeline(

        market_intelligence

    )



    # -------------------------------
    # Decision Layer
    # -------------------------------


    decision_engine = DecisionEngine(

        min_confidence=60

    )



    # -------------------------------
    # Execution Layer
    # -------------------------------


    paper_engine = PaperExecutionEngine(

        initial_balance=10000

    )



    position_controller = PositionController()



    execution_manager = ExecutionManager(

        paper_engine=paper_engine,

        position_manager=position_controller

    )





    # -------------------------------
    # Atlas Brain
    # -------------------------------


    atlas = IntelligenceCore(

        pipeline=pipeline,

        decision_engine=decision_engine,

        execution_manager=execution_manager,

        position_controller=position_controller

    )



    return (

        atlas,

        execution_manager,

        paper_engine,

        decision_engine,

        position_controller

    )







# ============================================================
# HEALTH CHECK
# ============================================================


def health_check(

    atlas,

    execution,

    paper

):


    print("\n")

    print("="*60)

    print(
        "SYSTEM HEALTH CHECK"
    )

    print("="*60)



    health = {


        "pipeline":

            atlas.pipeline is not None,


        "decision_engine":

            atlas.decision_engine is not None,


        "execution":

            execution is not None,


        "paper_engine":

            paper is not None


    }



    print(

        json.dumps(

            health,

            indent=4

        )

    )







# ============================================================
# RUN TEST
# ============================================================


def run_test():


    print("\n")

    print("="*60)

    print(
        "ATLAS AI PROFESSIONAL PIPELINE TEST v7.2"
    )

    print("="*60)




    try:



        atlas, execution, paper, decision, position = build_atlas()



        health_check(

            atlas,

            execution,

            paper

        )





        # ====================================================
        # PIPELINE TEST
        # ====================================================


        print("\n")

        print("="*60)

        print(
            "1. RUNNING INTELLIGENCE PIPELINE"
        )

        print("="*60)



        result = atlas.run(

            symbols=[

                "BTCUSDT",

                "ETHUSDT",

                "SOLUSDT"

            ]

        )



        print(

            json.dumps(

                result,

                indent=4,

                default=str,

                ensure_ascii=False

            )

        )







        # ====================================================
        # ATLAS STATUS
        # ====================================================


        print("\n")

        print("="*60)

        print(
            "2. ATLAS STATUS"
        )

        print("="*60)



        print(

            json.dumps(

                atlas.status(),

                indent=4,

                ensure_ascii=False

            )

        )







        # ====================================================
        # DECISION ENGINE
        # ====================================================


        print("\n")

        print("="*60)

        print(
            "3. DECISION ENGINE STATUS"
        )

        print("="*60)



        print(

            json.dumps(

                decision.status(),

                indent=4

            )

        )







        # ====================================================
        # EXECUTION
        # ====================================================


        print("\n")

        print("="*60)

        print(
            "4. EXECUTION STATUS"
        )

        print("="*60)



        print(

            json.dumps(

                execution.status(),

                indent=4

            )

        )







        # ====================================================
        # PAPER ACCOUNT
        # ====================================================


        print("\n")

        print("="*60)

        print(
            "5. PAPER ACCOUNT"
        )

        print("="*60)



        print(

            json.dumps(

                paper.status(),

                indent=4

            )

        )







        # ====================================================
        # POSITION
        # ====================================================


        print("\n")

        print("="*60)

        print(
            "6. POSITION STATUS"
        )

        print("="*60)



        print(

            json.dumps(

                position.status(),

                indent=4

            )

        )






        print("\n")

        print("="*60)

        print(
            "TEST RESULT"
        )

        print("="*60)



        print(

            "ATLAS PIPELINE TEST SUCCESS"

        )





    except Exception as e:


        print("\n")

        print("="*60)

        print(
            "TEST FAILED"
        )

        print("="*60)



        print(

            type(e).__name__,

            ":",

            str(e)

        )



        traceback.print_exc()







# ============================================================
# ENTRY
# ============================================================


if __name__ == "__main__":


    run_test()