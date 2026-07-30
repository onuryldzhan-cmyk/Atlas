"""
Atlas AI Confidence Engine v6.1

Adaptive Institutional Confidence System

Layers:

- Market Regime
- Strategy Quality
- Pattern Memory
- Outcome Memory
- Signal Strength
- Learning Feedback

"""


class ConfidenceEngine:


    def __init__(self):


        self.weights = {


            "regime": 0.25,

            "strategy": 0.25,

            "pattern": 0.15,

            "outcome": 0.15,

            "signal": 0.20


        }



    def normalize(
        self,
        value
    ):


        return max(
            0,
            min(
                100,
                value
            )
        )



    def calculate(
        self,
        fusion,
        strategy,
        learning_info=None,
        pattern=None,
        outcome=None
    ):


        regime_score = 50

        strategy_score = 50

        pattern_score = 50

        outcome_score = 50

        signal_score = 50



        # ==================================
        # MARKET REGIME
        # ==================================


        technical = fusion.get(
            "technical",
            {}
        )


        trend = technical.get(
            "trend",
            ""
        )


        adx = technical.get(
            "adx",
            0
        )



        if trend in [
            "BULLISH",
            "BEARISH"
        ]:

            regime_score += 15



        if adx >= 40:

            regime_score += 25


        elif adx >= 25:

            regime_score += 15


        elif adx < 15:

            regime_score -= 10



        regime_score = self.normalize(
            regime_score
        )



        # ==================================
        # STRATEGY QUALITY
        # ==================================


        strategy_score = strategy.get(
            "score",
            50
        )


        final_vote = strategy.get(
            "final_vote",
            "WAIT"
        )



        if final_vote in [
            "BUY",
            "SELL"
        ]:

            strategy_score += 10



        strategy_score = self.normalize(
            strategy_score
        )



        # ==================================
        # PATTERN MEMORY
        # ==================================


        if pattern:


            trades = pattern.get(
                "count",
                0
            )


            success = pattern.get(
                "SUCCESS_RATE",
                0
            )



            # Veri yoksa ceza verme

            if trades < 10:


                pattern_score = 50



            else:


                pattern_score = success



        pattern_score = self.normalize(
            pattern_score
        )



        # ==================================
        # OUTCOME MEMORY
        # ==================================


        if outcome:


            trades = outcome.get(
                "trades",
                0
            )



            if trades < 20:


                outcome_score = 50



            else:


                outcome_score = outcome.get(
                    "success_rate",
                    50
                )



        outcome_score = self.normalize(
            outcome_score
        )



        # ==================================
        # SIGNAL STRENGTH
        # ==================================


        fusion_score = fusion.get(
            "score",
            50
        )


        signal_strength = abs(
            fusion_score - 50
        )



        signal_score = 50 + (
            signal_strength * 1.5
        )



        strength = fusion.get(
            "strength",
            ""
        )



        if strength == "STRONG":


            signal_score += 15



        elif strength == "WEAK":


            signal_score -= 10



        signal_score = self.normalize(
            signal_score
        )



        # ==================================
        # LEARNING FEEDBACK
        # ==================================


        if learning_info:


            total = learning_info.get(
                "total_trades",
                0
            )


            win_rate = learning_info.get(
                "win_rate",
                50
            )



            # Sadece yeterli veri varsa kullan


            if total >= 20:


                if win_rate >= 60:

                    strategy_score += 5


                elif win_rate <= 40:

                    strategy_score -= 5



        strategy_score = self.normalize(
            strategy_score
        )



        # ==================================
        # FINAL CONFIDENCE
        # ==================================


        confidence = (


            regime_score *
            self.weights["regime"]


            +


            strategy_score *
            self.weights["strategy"]


            +


            pattern_score *
            self.weights["pattern"]


            +


            outcome_score *
            self.weights["outcome"]


            +


            signal_score *
            self.weights["signal"]


        )



        return round(
            self.normalize(
                confidence
            ),
            2
        )