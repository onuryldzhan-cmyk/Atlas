class StrategyCompetition:

    def choose(

        self,

        strategies

    ):

        if not strategies:

            return {

                "winner": None,

                "score": 0

            }

        winner = max(

            strategies,

            key=lambda x: x["score"]

        )

        return {

            "winner": winner,

            "score": winner["score"]

        }