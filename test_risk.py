from core.risk_engine import RiskEngine


risk = RiskEngine()


decision = {

    "action":"BUY",

    "symbol":"BTCUSDT",

    "confidence":75

}


result = risk.approve(
    decision
)


print(result)


print(
    risk.status()
)