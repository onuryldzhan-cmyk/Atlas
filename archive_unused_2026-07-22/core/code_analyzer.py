"""
Atlas Code Analyzer v7.0

Analyzes external projects
and finds useful upgrades.
"""


import logging


logger = logging.getLogger("AtlasAI")



class CodeAnalyzer:


    def __init__(
        self,
        brain=None
    ):

        self.brain = brain


        logger.info(
            "Atlas Code Analyzer initialized."
        )



    # =====================================
    # ANALYZE PROJECT
    # =====================================

    def analyze(
        self,
        project
    ):


        suggestions = []


        features = project.get(
            "features",
            []
        )


        name = project.get(
            "name",
            "UNKNOWN"
        )



        # BACKTEST


        if "Backtesting" in features:


            suggestions.append(

                {

                    "module":
                    "Backtest Engine",

                    "priority":
                    "HIGH",

                    "reason":
                    f"{name} güçlü backtesting sistemi kullanıyor."

                }

            )



        # STRATEGY


        if "Strategy Engine" in features:


            suggestions.append(

                {

                    "module":
                    "Strategy Optimization",

                    "priority":
                    "HIGH",

                    "reason":
                    f"{name} gelişmiş strateji yönetimi içeriyor."

                }

            )



        # INDICATORS


        if "Indicators" in features:


            suggestions.append(

                {

                    "module":
                    "Indicator Library",

                    "priority":
                    "MEDIUM",

                    "reason":
                    f"{name} geniş indikatör desteğine sahip."

                }

            )



        return {


            "project":

            name,


            "score":

            project.get(
                "score",
                0
            ),


            "suggestions":

            suggestions

        }