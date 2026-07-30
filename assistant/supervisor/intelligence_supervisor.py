from __future__ import annotations


from assistant.awareness.self_awareness_engine import SelfAwarenessEngine
from assistant.improvement.improvement_planner import ImprovementPlanner
from assistant.evolution.evolution_engine import EvolutionEngine
from assistant.advisor.advisor_engine import AdvisorEngine
from assistant.knowledge.knowledge_core import KnowledgeCore



class IntelligenceSupervisor:


    VERSION = "1.0"



    def __init__(self, root="."):


        self.awareness = SelfAwarenessEngine(root)

        self.improvement = ImprovementPlanner()

        self.evolution = EvolutionEngine(root)

        self.advisor = AdvisorEngine()

        self.knowledge = KnowledgeCore(root)



    def run_analysis(self):


        awareness_report = (
            self.awareness.inspect_project()
        )


        improvement_report = (
            self.improvement.create_plan(
                awareness_report
            )
        )


        evolution_progress = (
            self.evolution.get_progress()
        )


        advisor_report = (
            self.advisor.analyze(
                awareness_report,
                improvement_report,
                evolution_progress
            )
        )


        self.knowledge.remember(

            "system_analysis",

            {

                "health":
                    advisor_report["system_health"],

                "score":
                    advisor_report["score"]

            }

        )


        return {


            "awareness":
                awareness_report,


            "improvement":
                improvement_report,


            "advisor":
                advisor_report

        }