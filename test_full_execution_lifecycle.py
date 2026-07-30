"""
============================================================
ATLAS AI FULL EXECUTION LIFECYCLE TEST v1.0
============================================================

Tests:

BUY
 |
Risk
 |
Capital
 |
Router
 |
Paper Execution
 |
Position
 |
State
 |
Audit
 |
SELL
 |
Recovery

============================================================
"""


from core.execution_manager import ExecutionManager
from core.execution_router import ExecutionRouter
from core.execution_state import ExecutionState
from core.execution_audit import ExecutionAudit
from core.position_controller import PositionController



# Dummy Risk Engine

class TestRisk:


    def validate(self, decision):

        return {

            "approved": True

        }


    def position_opened(self):

        pass


    def position_closed(self):

        pass





# Dummy Capital Manager

class TestCapital:


    def allocate(

        self,

        symbol,

        confidence,

        price,

        risk

    ):


        return {

            "success": True,

            "amount":1500

        }





# Dummy Paper Engine

class TestPaper:



    def execute(

        self,

        action,

        symbol,

        price,

        amount,

        metadata

    ):


        return {


            "status":"FILLED",


            "symbol":symbol,


            "amount":amount


        }





    def buy(

        self,

        symbol,

        price,

        amount,

        strategy,

        confidence

    ):


        return {


            "status":"FILLED"

        }





    def sell(

        self,

        symbol,

        price

    ):


        return {


            "status":"CLOSED"

        }






print("="*70)

print(
"ATLAS FULL EXECUTION LIFECYCLE TEST"
)

print("="*70)





state = ExecutionState()

audit = ExecutionAudit()

position = PositionController()



paper = TestPaper()

risk = TestRisk()

capital = TestCapital()



router = ExecutionRouter(

    paper_engine=paper,

    mode="PAPER"

)




manager = ExecutionManager(

    router=router,

    capital_manager=capital,

    risk_engine=risk,

    position_controller=position,

    execution_state=state,

    audit=audit

)




print("\nSYSTEM")

print(

manager.health()

)





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

"Atlas_Test",


"risk_level":

"MEDIUM"

}




print("\nBUY TEST")



buy = manager.execute(

    decision,

    {

    "price":65000

    }

)



print(buy)





print("\nSTATE")

print(

state.status()

)





print("\nPOSITION")

print(

position.status()

)





print("\nSELL TEST")



sell = manager.execute(

{

"action":"SELL",

"symbol":"BTCUSDT",

"price":66000

},

{

"price":66000

}

)



print(sell)




print("\nAUDIT")

print(

audit.status()

)




print("\nFINAL HEALTH")

print(

manager.health()

)


print("="*70)

print(

"TEST COMPLETED"

)

print("="*70)