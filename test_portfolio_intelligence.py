from intelligence.portfolio.portfolio_intelligence import PortfolioIntelligence



engine = PortfolioIntelligence()



coins = [

    {
        "symbol": "BTCUSDT",
        "score": 90
    },

    {
        "symbol": "ETHUSDT",
        "score": 70
    },

    {
        "symbol": "DOGEUSDT",
        "score": 40
    }

]



result = engine.allocate(coins)



print("="*50)
print("ATLAS PORTFOLIO INTELLIGENCE")
print("="*50)

print(result)