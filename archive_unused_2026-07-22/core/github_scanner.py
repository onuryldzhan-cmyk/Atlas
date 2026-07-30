"""
Atlas GitHub Scanner v7.0

Researches useful open source projects.
"""


import logging


logger = logging.getLogger("AtlasAI")



class GithubScanner:


    def __init__(self):

        self.projects = []


        logger.info(
            "Atlas GitHub Scanner initialized."
        )



    def scan(self, category):


        database = {


            "trading": [

                {
                    "name":"Freqtrade",
                    "features":[
                        "Backtesting",
                        "Strategy Engine",
                        "Optimization"
                    ],
                    "score":90
                },


                {
                    "name":"Backtrader",
                    "features":[
                        "Backtesting",
                        "Indicators"
                    ],
                    "score":85
                }

            ],


            "ai":[

                {
                    "name":"Stable Baselines",
                    "features":[
                        "Reinforcement Learning",
                        "Agents"
                    ],
                    "score":88
                }

            ]

        }



        results = database.get(
            category,
            []
        )


        self.projects.extend(
            results
        )


        return results