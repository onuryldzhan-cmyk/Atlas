"""
Atlas Self Improvement Core v1.0

Self Analysis
Performance Evaluation
Strategy Improvement Suggestions
"""

import logging


logger = logging.getLogger("AtlasAI")



class SelfImprovement:



    def __init__(
        self,
        brain=None
    ):

        self.brain = brain


        self.history = []


        logger.info(
            "Atlas Self Improvement Core initialized."
        )



    # =====================================
    # SYSTEM ANALYSIS
    # =====================================

    def analyze_system(
        self
    ):


        report = {}


        try:


            learning = (
                self.brain
                .learning_engine
                .get_insight()
            )


            performance = (
                self.brain
                .performance_analyzer
                .analyze()
            )


            feedback = (
                self.brain
                .performance_feedback
                .analyze()
            )


            report = {


                "learning":

                    learning,


                "performance":

                    performance,


                "feedback":

                    feedback


            }



            self.history.append(
                report
            )


            logger.info(
                "Self analysis completed."
            )



        except Exception as e:


            logger.exception(
                e
            )


            report = {

                "error": str(e)

            }



        return report



    # =====================================
    # IMPROVEMENT SUGGESTIONS
    # =====================================

    def generate_suggestions(
        self,
        report
    ):


        suggestions = []



        try:


            feedback = report.get(
                "feedback",
                {}
            )


            win_rate = feedback.get(
                "win_rate",
                0
            )



            if win_rate < 50:


                suggestions.append(

                    {
                        "type":
                        "PERFORMANCE",

                        "message":
                        "Başarı oranı düşük. Strateji ağırlıkları yeniden değerlendirilmeli."

                    }

                )



            else:


                suggestions.append(

                    {
                        "type":
                        "PERFORMANCE",

                        "message":
                        "Performans kabul edilebilir seviyede."

                    }

                )



            learning = report.get(
                "learning",
                {}
            )


            best = learning.get(
                "best_strategy",
                "NONE"
            )



            suggestions.append(

                {

                    "type":
                    "STRATEGY",


                    "message":
                    f"En başarılı strateji: {best}"

                }

            )



        except Exception as e:


            logger.exception(
                e
            )



        return suggestions



    # =====================================
    # FULL REPORT
    # =====================================

    def report(
        self
    ):


        analysis = self.analyze_system()


        suggestions = self.generate_suggestions(
            analysis
        )


        return {


            "analysis":

                analysis,


            "suggestions":

                suggestions


        }