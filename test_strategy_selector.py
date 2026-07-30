from intelligence.strategy.strategy_selector import StrategySelector



selector = StrategySelector()



result = selector.select(

    regime="BULLISH",

    opportunity_score=90,

    volatility=50

)



print("="*50)
print("ATLAS STRATEGY SELECTOR")
print("="*50)

print(result)