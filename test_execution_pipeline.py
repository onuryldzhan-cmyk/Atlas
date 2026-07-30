"""
============================================================
ATLAS AI EXECUTION PIPELINE TEST v1.0
============================================================

Purpose:

Validate complete trading execution lifecycle.

Pipeline:

Decision
    |
Risk Engine
    |
Capital Manager
    |
Execution Manager
    |
Paper Execution Engine
    |
Position Controller
    |
Trade Result


Mode:
PAPER TRADING


============================================================
"""


from datetime import datetime, UTC


from core.execution_manager import ExecutionManager
from core.risk_engine import RiskEngine
from core.capital_manager import CapitalManager
from core.paper_execution_engine import PaperExecutionEngine
from core.position_controller import PositionManager





def banner():

    print("=" * 70)

    print(
        "ATLAS AI EXECUTION PIPELINE TEST v1.0"
    )

    print("=" * 70)





def create_components():


    print("\n[INIT] Loading Atlas execution components...\n")


    components = {}


    components["risk_engine"] = RiskEngine()

    components["capital_manager"] = CapitalManager()

    components["paper_engine"] = PaperExecutionEngine()

    components["position_manager"] = PositionManager()



    return components






def health_check(components):


    print("[SYSTEM HEALTH CHECK]\n")


    for name, obj in components.items():

        print(

            f"{name:<25}:",

            "OK" if obj else "FAILED"

        )





def build_execution_manager(components):


    return ExecutionManager(

        paper_engine=
            components["paper_engine"],

        capital_manager=
            components["capital_manager"],

        risk_engine=
            components["risk_engine"],

        position_manager=
            components["position_manager"],

        mode="PAPER"

    )







def create_test_decision():


    return {


        "action":

        "BUY",


        "symbol":

        "BTCUSDT",


        "price":

        65000,


        "confidence":

        80,


        "strategy":

        "Atlas_Test_Strategy",


        "risk_level":

        "MEDIUM"

    }







def validate_result(result):


    print("\n[EXECUTION VALIDATION]\n")


    success = True



    if result.get("status") == "EXECUTED":

        print(
            "Execution Status : PASS"
        )

    else:

        print(
            "Execution Status : FAIL"
        )

        success = False





    trade = result.get(
        "trade"
    )


    if trade:


        print(
            "Trade Created    : PASS"
        )


        print(
            f"Symbol           : {trade['symbol']}"
        )


        print(
            f"Amount           : {trade['amount']}"
        )


        print(
            f"Confidence       : {trade['confidence']}"
        )


    else:

        print(
            "Trade Created    : FAIL"
        )

        success = False





    position = result.get(
        "position"
    )


    if position:


        print(
            "Position Manager  : PASS"
        )


        print(
            f"Position Symbol  : {position.symbol}"
        )


    else:

        print(
            "Position Manager  : WARNING"
        )

        print(
            "Position may exist inside execution engine"
        )




    return success







def main():


    banner()



    try:


        components = create_components()


        health_check(
            components
        )



        execution = build_execution_manager(
            components
        )



        print(
            "\n[EXECUTION MANAGER STATUS]\n"
        )


        print(
            execution.status()
        )




        decision = create_test_decision()



        market = {


            "price":

            65000

        }




        print(
            "\n[EXECUTING TEST BUY]\n"
        )


        result = execution.execute(

            decision,

            market

        )




        print(
            "\n[RAW RESULT]\n"
        )


        print(result)




        passed = validate_result(
            result
        )




        print("\n" + "=" * 70)



        if passed:


            print(
                "ATLAS EXECUTION PIPELINE TEST SUCCESS"
            )


        else:


            print(
                "ATLAS EXECUTION PIPELINE TEST FAILED"
            )



        print("=" * 70)



        print(

            "Completed:",

            datetime.now(
                UTC
            ).isoformat()

        )



    except Exception as e:


        print("\nTEST ERROR")

        print(
            str(e)
        )






if __name__ == "__main__":

    main()