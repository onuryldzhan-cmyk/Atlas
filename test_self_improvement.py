from assistant.loop.self_improvement_loop import SelfImprovementLoop



atlas = SelfImprovementLoop(".")


report = atlas.run()



print("="*50)
print("ATLAS SELF IMPROVEMENT LOOP")
print("="*50)


print(
    "Health:",
    report["health"]
)


print(
    "Score:",
    report["score"]
)


print(
    "Recommendations:",
    len(report["recommendations"])
)


for item in report["recommendations"]:

    print(
        "-",
        item
    )