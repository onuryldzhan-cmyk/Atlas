from intelligence.execution.execution_engine import ExecutionEngine



engine = ExecutionEngine()



result = engine.execute(

    symbol="BTCUSDT",

    decision="BUY",

    position_size=500,

    strategy="TREND_FOLLOWING"

)



print("="*50)
print("ATLAS EXECUTION ENGINE")
print("="*50)

print(result)