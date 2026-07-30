from events import EventBus
from events import MarketUpdateEvent



bus = EventBus()



def market_listener(event):

    print(
        "MARKET EVENT:",
        event.info()
    )



bus.subscribe(
    "MARKET_UPDATE",
    market_listener
)



event = MarketUpdateEvent(

    "BTCUSDT",

    65000

)



bus.publish(event)