from intelligence.trading.paper_bridge import PaperBridge



bridge = PaperBridge()



result = bridge.open_trade(

    "BTCUSDT",

    500,

    "MOMENTUM"

)



print("="*50)
print("ATLAS PAPER BRIDGE")
print("="*50)

print(result)
print(bridge.get_positions())