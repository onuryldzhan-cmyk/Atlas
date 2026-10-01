from intelligence.position.position_manager import PositionManager



manager = PositionManager()



manager.open_position(

    "BTCUSDT",

    2500,

    65000,

    63700,

    68250

)



result = manager.update_price(

    "BTCUSDT",

    69000

)



print("="*50)
print("ATLAS POSITION MANAGER")
print("="*50)

print(result)