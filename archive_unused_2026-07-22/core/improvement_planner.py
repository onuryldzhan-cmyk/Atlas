"""
Atlas Improvement Planner v6.5

Performance analysis and improvement suggestion system.
"""


import logging


logger = logging.getLogger("AtlasAI")



class ImprovementPlanner:


    def __init__(
        self,
        brain
    ):

        self.brain = brain

        logger.info(
            "Atlas Improvement Planner initialized."
        )



    def analyze(
        self
    ):

        suggestions = []


        learning = (
            self.brain
            .learning_engine
            .get_insight()
        )


        feedback = (
            self.brain
            .performance_feedback
            .analyze()
        )


        performance = (
            self.brain
            .performance_analyzer
            .analyze()
        )


        win_rate = learning.get(
            "win_rate",
            0
        )


        if win_rate < 40:

            suggestions.append(

                {
                    "type": "PERFORMANCE",

                    "priority": "HIGH",

                    "message":
                    "Başarı oranı düşük. Strateji ağırlıkları yeniden optimize edilmeli.",

                    "win_rate":
                    win_rate
                }

            )



        best_strategy = learning.get(
            "best_strategy",
            "UNKNOWN"
        )


        if best_strategy != "UNKNOWN":

            suggestions.append(

                {
                    "type": "STRATEGY",

                    "priority": "MEDIUM",

                    "message":
                    f"En başarılı strateji: {best_strategy}",

                    "strategy":
                    best_strategy
                }

            )



        return {

            "learning":
            learning,

            "performance":
            performance,

            "feedback":
            feedback,

            "suggestions":
            suggestions

        }



    def create_upgrade_plan(
        self
    ):


        report = self.analyze()


        plan = []


        for item in report.get(
            "suggestions",
            []
        ):


            plan.append(

                {

                    "module":
                    item.get("type"),


                    "reason":
                    item.get("message"),


                    "status":
                    "WAITING_APPROVAL"

                }

            )


        return plan