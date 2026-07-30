from intelligence.opportunity.opportunity_engine import OpportunityEngine



engine = OpportunityEngine()



coin = {

    "symbol":
        "BTCUSDT",

    "score":
        70,

    "change":
        2.5,

    "volume":
        1200000

}



result = engine.evaluate(
    coin
)



print(result)


print(
    engine.rank()
)