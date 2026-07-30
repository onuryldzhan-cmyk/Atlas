from ai.execution.paper_executor import PaperExecutor


from core.decision import (
    Decision,
    DecisionAction
)



executor = PaperExecutor()



buy = Decision(

    action=DecisionAction.BUY,

    symbol="BTCUSDT",

    confidence=80,

    reasoning="test"

)



print(
    executor.execute(
        buy,
        60000
    )
)



print(
    executor.status()
)