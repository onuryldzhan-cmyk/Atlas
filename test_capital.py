from core.capital_manager import CapitalManager


capital = CapitalManager(
    10000
)


allocation = capital.allocate(

    "BTCUSDT",

    80,

    60000,

    "high"

)


print(allocation)


capital.open_position(
    allocation
)


print(
    capital.status()
)