from core.atlas_brain import AtlasBrain


brain = AtlasBrain()


print("\n===== ATLAS IMPROVEMENT PLANNER =====\n")


report = brain.improvement_planner.analyze()


print(report)


print("\n===== UPGRADE PLAN =====\n")


plan = brain.improvement_planner.create_upgrade_plan()


for item in plan:

    print(item)