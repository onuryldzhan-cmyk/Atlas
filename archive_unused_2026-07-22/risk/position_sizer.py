class PositionSizer:


    def calculate(
        self,
        balance,
        risk_percent,
        entry,
        stop_loss
    ):


        risk_amount = balance * (
            risk_percent / 100
        )


        distance = abs(
            entry - stop_loss
        )


        if distance == 0:

            return 0



        quantity = risk_amount / distance


        return round(
            quantity,
            6
        )