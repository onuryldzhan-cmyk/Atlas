"""
Atlas Performance Feedback Engine v1.0

Performance evaluation layer.
Collects results and creates feedback.
"""


import logging


logger = logging.getLogger("AtlasAI")



class PerformanceFeedback:


    def __init__(self):

        self.results = []



    def add_result(
        self,
        result
    ):

        if not result:

            return


        self.results.append(
            result
        )


        logger.info(
            "Performance feedback updated."
        )



    def analyze(
        self
    ):


        total = len(
            self.results
        )


        if total == 0:

            return {

                "total": 0,

                "wins": 0,

                "losses": 0,

                "win_rate": 0

            }



        wins = 0

        losses = 0



        for item in self.results:


            if item.get(
                "result"
            ) == "WIN":

                wins += 1

            else:

                losses += 1



        return {

            "total": total,

            "wins": wins,

            "losses": losses,

            "win_rate":
                round(
                    wins / total * 100,
                    2
                )

        }