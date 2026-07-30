"""
Atlas Evolution Engine v6.7

Responsible for:
- Running improvement experiments
- Evaluating results
- Deciding upgrade candidates
- Evolution memory
"""

import logging


logger = logging.getLogger("AtlasAI")



class EvolutionEngine:


    def __init__(
        self,
        brain=None
    ):

        self.brain = brain


        logger.info(
            "Atlas Evolution Engine initialized."
        )



    # =====================================
    # START EVOLUTION
    # =====================================

    def evaluate_experiment(
        self,
        experiment_id,
        old_score,
        new_score
    ):


        improvement = (

            new_score -
            old_score

        )



        success = improvement > 0



        result = {


            "experiment_id":
            experiment_id,


            "old_score":
            old_score,


            "new_score":
            new_score,


            "improvement":
            improvement,


            "success":
            success

        }



        if self.brain:


            self.brain.experiment_manager.complete_experiment(

                experiment_id,

                success,

                result

            )



        if success:


            logger.info(
                "[EVOLUTION] Upgrade successful."
            )


        else:


            logger.info(
                "[EVOLUTION] Upgrade rejected."
            )



        return result



    # =====================================
    # AUTO DECISION
    # =====================================

    def should_upgrade(
        self,
        result
    ):


        if result.get(
            "success"
        ):

            return {

                "upgrade":
                True,

                "reason":
                "Yeni sistem daha başarılı."

            }



        return {


            "upgrade":
            False,


            "reason":
            "Performans artışı yok."

        }