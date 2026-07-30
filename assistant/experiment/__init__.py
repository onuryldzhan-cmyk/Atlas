from __future__ import annotations

from datetime import datetime, UTC
from pathlib import Path
import json



class ExperimentEngine:


    VERSION = "1.0"



    def __init__(self, root="."):

        self.file = (
            Path(root) /
            "atlas_experiments.json"
        )



    def load(self):

        if not self.file.exists():

            return []


        with open(
            self.file,
            "r",
            encoding="utf-8"
        ) as f:

            return json.load(f)



    def save(self, data):

        with open(
            self.file,
            "w",
            encoding="utf-8"
        ) as f:

            json.dump(
                data,
                f,
                indent=4,
                ensure_ascii=False
            )



    def create_experiment(
        self,
        goal
    ):

        experiments = self.load()


        experiment = {

            "id":
                len(experiments)+1,

            "created":
                datetime.now(UTC).isoformat(),

            "goal":
                goal,

            "status":
                "running",

            "before_score":
                None,

            "after_score":
                None

        }


        experiments.append(
            experiment
        )


        self.save(
            experiments
        )


        return experiment




    def complete(
        self,
        experiment_id,
        before,
        after
    ):


        experiments = self.load()


        for exp in experiments:

            if exp["id"] == experiment_id:

                exp["before_score"] = before

                exp["after_score"] = after

                exp["status"] = "completed"



        self.save(
            experiments
        )