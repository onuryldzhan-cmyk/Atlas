from intelligence.scanner.coin_scanner import CoinScanner



scanner = CoinScanner()


print(
    scanner.get_watchlist()
)



result = scanner.analyze_coin(

    "BTCUSDT",

    65572,

    1200000,

    2.5

)


print(result)