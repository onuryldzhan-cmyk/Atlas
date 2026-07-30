class PositionSizer:

    def calculate(
        self,
        balance,
        confidence,
        risk_level
    ):

        if risk_level == "HIGH":
            risk_percent = 0.01

        elif risk_level == "MEDIUM":
            risk_percent = 0.02

        else:
            risk_percent = 0.03

        confidence_multiplier = confidence / 100

        position_size = (
            balance
            * risk_percent
            * confidence_multiplier
        )

        return round(position_size, 2)