class RiskPlanner:

    def create(self, signal, entry):

        risk_percent = 0.005
        reward_percent = 0.01

        if signal == "AL":

            stop_loss = entry * (1 - risk_percent)
            take_profit = entry * (1 + reward_percent)

        else:

            stop_loss = entry * (1 + risk_percent)
            take_profit = entry * (1 - reward_percent)

        return {

            "signal": signal,

            "entry": round(entry, 2),

            "stop_loss": round(stop_loss, 2),

            "take_profit": round(take_profit, 2)

        }