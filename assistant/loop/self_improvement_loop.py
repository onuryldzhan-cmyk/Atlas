from __future__ import annotations

from datetime import datetime, UTC
import json
from pathlib import Path


from assistant.supervisor.intelligence_supervisor import IntelligenceSupervisor
from assistant.evolution.evolution_engine import EvolutionEngine



class SelfImprovementLoop:


    VERSION = "1.0"



    def __init__(self, root="."):


        self.root = Path(root)


        self.supervisor = IntelligenceSupervisor(
            root
        )


        self.evolution = EvolutionEngine(
            root
        )


        self.report_file = (
            self.root /
            "atlas_self_improvement_report.json"
        )



    def run(self):


        analysis = (
            self.supervisor.run_analysis()
        )


        advisor = analysis["advisor"]


        recommendations = (
            advisor["recommendations"]
        )



        for item in recommendations:


            self.evolution.register_improvement(

                {

                    "source":
                        "SelfImprovementLoop",

                    "recommendation":
                        item

                }

            )



        result = {


            "engine":
                "Atlas Self Improvement Loop",


            "version":
                self.VERSION,


            "time":
                datetime.now(UTC).isoformat(),


            "health":
                advisor["system_health"],


            "score":
                advisor["score"],


            "recommendations":
                recommendations


        }



        self.save_report(
            result
        )


        return result




    def save_report(
        self,
        data
    ):


        with open(

            self.report_file,

            "w",

            encoding="utf-8"

        ) as f:


            json.dump(

                data,

                f,

                indent=4,

                ensure_ascii=False

            )



        return self.report_file