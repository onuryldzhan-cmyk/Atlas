from assistant.awareness.self_awareness_engine import SelfAwarenessEngine
from assistant.improvement.improvement_planner import ImprovementPlanner


awareness = SelfAwarenessEngine(".")

report = awareness.inspect_project()


planner = ImprovementPlanner()


plan = planner.create_plan(report)


print("="*50)
print("ATLAS IMPROVEMENT PLANNER")
print("="*50)


print(
    "Issues:",
    len(plan["issues"])
)


print(
    "Recommendations:",
    len(plan["recommendations"])
)


for item in plan["recommendations"][:5]:

    print(
        item
    )