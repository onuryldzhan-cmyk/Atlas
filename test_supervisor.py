from assistant.supervisor.intelligence_supervisor import IntelligenceSupervisor


atlas = IntelligenceSupervisor(".")


report = atlas.run_analysis()


print("="*50)
print("ATLAS INTELLIGENCE SUPERVISOR")
print("="*50)


print(
    "Health:",
    report["advisor"]["system_health"]
)


print(
    "Score:",
    report["advisor"]["score"]
)


print(
    "Issues:",
    len(
        report["improvement"]["issues"]
    )
)


for item in report["advisor"]["recommendations"]:

    print(
        "-",
        item
    )