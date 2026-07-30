from assistant.awareness.self_awareness_engine import SelfAwarenessEngine
from assistant.improvement.improvement_planner import ImprovementPlanner
from assistant.evolution.evolution_engine import EvolutionEngine
from assistant.advisor.advisor_engine import AdvisorEngine



awareness_engine = SelfAwarenessEngine(".")

awareness = awareness_engine.inspect_project()



planner = ImprovementPlanner()

improvement = planner.create_plan(
    awareness
)



evolution = EvolutionEngine(".")

progress = evolution.get_progress()



advisor = AdvisorEngine()


report = advisor.analyze(

    awareness,

    improvement,

    progress

)



print("="*50)
print("ATLAS ADVISOR ENGINE")
print("="*50)


print(
    "Health:",
    report["system_health"]
)


print(
    "Score:",
    report["score"]
)



for r in report["recommendations"]:

    print(
        "-",
        r
    )