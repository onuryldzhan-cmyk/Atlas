"""
============================================================
ATLAS AI BUY EXECUTION TEST v3.0
============================================================

Professional BUY lifecycle integration test.


Architecture:

Decision Engine
        |
        v
Risk Engine
        |
        v
Capital Manager
        |
        v
Execution Manager
        |
        v
Paper Execution Engine
        |
        v
Position Controller


Test:

- Create BUY decision
- Validate risk
- Allocate capital
- Execute paper trade
- Register position
- Check balances


============================================================
"""


import json
import traceback



# ============================================================
# IMPORTS
# ============================================================


from core.decision_engine import (
    DecisionEngine
)


from core.capital_manager import (
    CapitalManager
)


from core.risk_engine import (
    RiskEngine
)


from core.paper_execution_engine import (
    PaperExecutionEngine
)


from core.execution_manager import (
    ExecutionManager
)


from core.position_controller import (
    PositionManager
)


from core.decision import (
    Decision
)





# ============================================================
# BUILD SYSTEM
# ============================================================


def build_system():


    print(
        "[INIT] Building Atlas BUY system"
    )



    decision_engine = DecisionEngine(

        min_confidence=60

    )



    capital_manager = CapitalManager(

        balance=10000

    )



    risk_engine = RiskEngine(

        max_positions=5,

        max_daily_loss_percent=5,

        min_confidence=60

    )



    paper_engine = PaperExecutionEngine(

        initial_balance=10000

    )



    position_manager = PositionManager()





    execution_manager = ExecutionManager(

        paper_engine=paper_engine,

        capital_manager=capital_manager,

        risk_engine=risk_engine,

        position_manager=position_manager,

        mode="PAPER"

    )



    return {


        "decision":

            decision_engine,


        "capital":

            capital_manager,


        "risk":

            risk_engine,


        "paper":

            paper_engine,


        "position":

            position_manager,


        "execution":

            execution_manager

    }







# ============================================================
# BUY DECISION
# ============================================================


def create_buy_decision():


    return Decision(


        action="BUY",


        symbol="BTCUSDT",


        confidence=72,


        reasoning=

        "Momentum opportunity detected",


        risk_level="MEDIUM",


        strategy="MOMENTUM"


    )






# ============================================================
# TEST
# ============================================================


def run_test():


    print("\n")

    print("="*60)

    print(
        "ATLAS AI BUY EXECUTION TEST v3.0"
    )

    print("="*60)



    try:



        system = build_system()



        decision_engine = system["decision"]

        capital = system["capital"]

        risk = system["risk"]

        paper = system["paper"]

        position = system["position"]

        execution = system["execution"]






        # ==============================================
        # HEALTH CHECK
        # ==============================================


        print("\n")

        print("="*60)

        print(
            "SYSTEM HEALTH CHECK"
        )

        print("="*60)



        print(

            json.dumps(

                {

                "decision_engine":

                    decision_engine is not None,


                "risk_engine":

                    risk is not None,


                "capital_manager":

                    capital is not None,


                "paper_engine":

                    paper is not None,


                "execution_manager":

                    execution is not None,


                "position_manager":

                    position is not None

                },


                indent=4

            )

        )





        # ==============================================
        # DECISION
        # ==============================================


        decision = create_buy_decision()



        print("\n")

        print("="*60)

        print(
            "1. DECISION"
        )

        print("="*60)



        print(

            decision.summary()

        )







        # ==============================================
        # EXECUTION
        # ==============================================


        result = execution.execute(

            decision,

            market_state={

                "price":

                65000

            }

        )





        print("\n")

        print("="*60)

        print(
            "2. EXECUTION RESULT"
        )

        print("="*60)



        print(

            json.dumps(

                result,

                indent=4,

                default=str,

                ensure_ascii=False

            )

        )







        # ==============================================
        # RISK
        # ==============================================


        print("\n")

        print("="*60)

        print(
            "3. RISK STATUS"
        )

        print("="*60)



        print(

            json.dumps(

                risk.status(),

                indent=4

            )

        )








        # ==============================================
        # CAPITAL
        # ==============================================


        print("\n")

        print("="*60)

        print(
            "4. CAPITAL STATUS"
        )

        print("="*60)



        print(

            json.dumps(

                capital.status(),

                indent=4

            )

        )






        # ==============================================
        # PAPER ACCOUNT
        # ==============================================


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







        # ==============================================
        # POSITION
        # ==============================================


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








        # ==============================================
        # EXECUTION STATUS
        # ==============================================


        print("\n")

        print("="*60)

        print(
            "7. EXECUTION STATUS"
        )

        print("="*60)



        print(

            json.dumps(

                execution.status(),

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

            "BUY EXECUTION TEST SUCCESS"

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