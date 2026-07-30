class RiskManager:

    def __init__(self, balance=10000, risk_percent=1):
        self.balance = balance
        self.risk_percent = risk_percent

    def calculate_position(self, price):
        risk_amount = self.balance * (self.risk_percent / 100)
        position_size = risk_amount / price
        return round(position_size, 6)

    def check_trade(self, signal):
        signal = signal.upper()

        if signal == "BUY":
            return "ONAYLANDI"

        elif signal == "SELL":
            return "ONAYLANDI"

        elif signal == "HOLD":
            return "BEKLE"

        return "RED"

    def calculate(self, analysis):
        score = 100

        rsi = analysis.get("rsi", 50)

        if rsi > 75:
            score -= 30
        elif rsi > 70:
            score -= 20
        elif rsi < 25:
            score -= 15

        macd = analysis.get("macd_signal", "HOLD")

        if macd == "SELL":
            score -= 20

        ema = analysis.get("ema_signal", "HOLD")

        if ema == "SELL":
            score -= 20

        if score >= 80:
            level = "LOW"

        elif score >= 60:
            level = "MEDIUM"

        else:
            level = "HIGH"

        return {
            "score": score,
            "level": level
        }

    def get_trade_info(self, price):
        return {
            "balance": self.balance,
            "risk_percent": self.risk_percent,
            "position_size": self.calculate_position(price)
        }


if __name__ == "__main__":

    risk = RiskManager()

    print(risk.check_trade("BUY"))
    print(risk.check_trade("SELL"))
    print(risk.check_trade("HOLD"))

    sample = {
        "rsi": 68,
        "macd_signal": "BUY",
        "ema_signal": "BUY"
    }

    print(risk.calculate(sample))
    print(risk.get_trade_info(100000))