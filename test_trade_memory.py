from core.trade_memory import TradeMemory



memory = TradeMemory()



trade = {


    "execution_id":

    "MEMORY_TEST_001",


    "symbol":

    "BTCUSDT",


    "side":

    "BUY",


    "strategy":

    "Atlas_Test",


    "confidence":

    85,


    "risk":

    "MEDIUM",


    "price":

    65000,


    "amount":

    1500

}



print("\nADDING TRADE\n")


saved = memory.remember(
    trade
)


print(saved)



print("\nUPDATING RESULT\n")


result = memory.update_result(

    "MEMORY_TEST_001",

    2.5

)


print(result)



print("\nMEMORY STATUS\n")


print(

    memory.status()

)