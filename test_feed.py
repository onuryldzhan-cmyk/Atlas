from exchange.market_feed import MarketFeed

feed = MarketFeed()

feed.start()

print(feed.price("BTCUSDT"))

feed.stop()