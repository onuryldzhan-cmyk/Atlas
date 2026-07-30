from core.decision_adapter import DecisionAdapter



adapter = DecisionAdapter()



decision1 = {


    "action":
    "BUY",


    "symbol":
    "BTCUSDT",


    "confidence":
    75

}



decision2 = {


    "decision":
    "BUY",


    "order":
    {

        "symbol":
        "ETHUSDT"

    },


    "strategy_confidence":
    82

}



print(
    adapter.adapt(
        decision1
    )
)



print(
    adapter.adapt(
        decision2
    )
)



print(
    adapter.status()
)