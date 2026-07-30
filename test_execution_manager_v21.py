"""
============================================================
ATLAS EXECUTION MANAGER v21 INTEGRATION TEST
============================================================

Full execution lifecycle validation

BUY FLOW:

Decision
 -> Risk
 -> Capital
 -> Paper Execution
 -> Position Controller
 -> State
 -> Memory
 -> Audit

============================================================
"""


from core.execution_manager import ExecutionManager

from core.paper_execution_engine import PaperExecutionEngine

from core.position_controller import PositionController

from core.execution_state import ExecutionState

from core.execution_audit import ExecutionAudit

from core.capital_manager import CapitalManager

from core.trade_memory import TradeMemory



print("=" * 70)
print("ATLAS EXECUTION MANAGER v21 INTEGRATION TEST")
print("=" * 70)



print("\n[1] LOADING COMPONENTS")



paper_engine = PaperExecutionEngine()

position_controller = PositionController()

execution_state = ExecutionState()

audit = ExecutionAudit()

capital_manager = CapitalManager()

trade_memory = TradeMemory()



print("paper_engine        : OK")
print("position_controller : OK")
print("execution_state     : OK")
print("audit               : OK")
print("capital_manager     : OK")
print("trade_memory        : OK")





print("\n[2] BUILD EXECUTOR")



executor = ExecutionManager(

    paper_engine=paper_engine,

    capital_manager=capital_manager,

    position_controller=position_controller,

    execution_state=execution_state,

    trade_memory=trade_memory,

    audit=audit,

    mode="PAPER"

)



print(

    executor.health()

)






print("\n[3] BUY SIGNAL")



decision = {


    "action":
    "BUY",


    "symbol":
    "BTCUSDT",


    "price":
    65000,


    "confidence":
    85,


    "strategy":
    "Atlas_Test_Strategy",


    "risk_level":
    "MEDIUM"

}



market_state = {


    "price":
    65000

}





result = executor.execute(

    decision,

    market_state

)



print("\nRESULT")

print(result)





print("\n[4] FINAL STATUS")

print(

    executor.status()

)



print("\n[5] POSITION STATUS")

print(

    position_controller.status()

)



print("\n[6] STATE STATUS")

print(

    execution_state.status()

)



print("\n[7] AUDIT STATUS")

print(

    audit.status()

)



print("\n[8] MEMORY STATUS")

print(

    trade_memory.status()

)



print("\n" + "="*70)

print("ATLAS EXECUTION MANAGER v21 TEST COMPLETED")

print("="*70)