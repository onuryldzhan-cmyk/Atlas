from intelligence.risk.risk_intelligence import RiskIntelligence



engine = RiskIntelligence()



result = engine.analyze(

    decision="BUY",

    confidence=85,

    balance=10000,

    price=65000,

    risk_level="MEDIUM"

)



print("="*50)
print("ATLAS RISK INTELLIGENCE v2")
print("="*50)

print(result)