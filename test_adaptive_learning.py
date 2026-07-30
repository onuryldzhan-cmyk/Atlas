from intelligence.learning.adaptive_learning_engine import AdaptiveLearningEngine



engine = AdaptiveLearningEngine()



engine.register_trade(
    "TREND_FOLLOWING",
    100
)


engine.register_trade(
    "TREND_FOLLOWING",
    -20
)


engine.register_trade(
    "TREND_FOLLOWING",
    80
)



result = engine.evaluate_strategy(
    "TREND_FOLLOWING"
)



print("="*50)
print("ATLAS ADAPTIVE LEARNING ENGINE")
print("="*50)

print(result)