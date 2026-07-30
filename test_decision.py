from intelligence.decision.decision_engine import DecisionEngine


engine = DecisionEngine()


result = engine.decide(

    opportunity_score=90,

    strategy_confidence=85,

    regime="BULLISH"

)


print("="*50)
print("ATLAS DECISION ENGINE")
print("="*50)

print(result)