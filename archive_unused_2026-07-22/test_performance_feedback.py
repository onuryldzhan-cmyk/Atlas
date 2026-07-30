"""
Atlas Performance Feedback Test
"""


from core.performance_feedback import PerformanceFeedback



feedback = PerformanceFeedback()



feedback.add_result(
    {
        "symbol": "BTCUSDT",
        "strategy": "Trend-Follow",
        "result": "WIN"
    }
)



feedback.add_result(
    {
        "symbol": "ETHUSDT",
        "strategy": "RSI-Scalping",
        "result": "LOSS"
    }
)



print(
    feedback.analyze()
)