"""
Atlas AI Experiment Manager v6.6

Manages AI improvement experiments.

Responsibilities:
- Create experiments
- Track changes
- Compare results
- Store experiment history
"""

import json
import os
import logging
from datetime import datetime


logger = logging.getLogger("AtlasAI")



class ExperimentManager:


    def __init__(
        self,
        brain=None
    ):

        self.brain = brain

        self.file = "experiment_memory.json"

        self.experiments = []

        self.load()


        logger.info(
            "Atlas Experiment Manager initialized."
        )



    # =====================================
    # LOAD MEMORY
    # =====================================

    def load(self):

        if os.path.exists(
            self.file
        ):

            try:

                with open(
                    self.file,
                    "r",
                    encoding="utf-8"
                ) as f:

                    self.experiments = json.load(f)


            except Exception as e:

                logger.error(
                    f"Experiment load error: {e}"
                )

                self.experiments = []



    # =====================================
    # SAVE MEMORY
    # =====================================

    def save(self):

        with open(
            self.file,
            "w",
            encoding="utf-8"
        ) as f:


            json.dump(
                self.experiments,
                f,
                indent=4,
                ensure_ascii=False
            )



    # =====================================
    # CREATE EXPERIMENT
    # =====================================

    def create_experiment(
        self,
        module,
        change,
        reason,
        before=None,
        after=None
    ):


        experiment = {


            "id":
            len(self.experiments) + 1,


            "date":
            datetime.now().strftime(
                "%Y-%m-%d %H:%M:%S"
            ),


            "module":
            module,


            "change":
            change,


            "reason":
            reason,


            "before":
            before,


            "after":
            after,


            "status":
            "TESTING",


            "result":
            None

        }



        self.experiments.append(
            experiment
        )


        self.save()


        logger.info(
            f"[EXPERIMENT] Created: {module}"
        )


        return experiment



    # =====================================
    # COMPLETE EXPERIMENT
    # =====================================

    def complete_experiment(
        self,
        experiment_id,
        success,
        result=None
    ):


        for exp in self.experiments:


            if exp["id"] == experiment_id:


                exp["status"] = (

                    "SUCCESS"
                    if success
                    else
                    "FAILED"

                )


                exp["result"] = result


                self.save()


                logger.info(
                    f"[EXPERIMENT] Finished {experiment_id}"
                )


                return exp



        return None



    # =====================================
    # ACTIVE EXPERIMENTS
    # =====================================

    def get_testing(self):


        return [

            x for x in self.experiments

            if x.get(
                "status"
            )
            ==
            "TESTING"

        ]



    # =====================================
    # REPORT
    # =====================================

    def report(self):


        return {


            "total":

            len(
                self.experiments
            ),


            "testing":

            len(
                self.get_testing()
            ),


            "experiments":

            self.experiments

        }