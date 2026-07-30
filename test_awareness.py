from assistant.awareness.self_awareness_engine import SelfAwarenessEngine


engine = SelfAwarenessEngine(".")


report = engine.inspect_project()


print("="*50)
print("ATLAS SELF AWARENESS ENGINE")
print("="*50)

print(
    "Python Files:",
    report["python_files"]
)

print(
    "Total Lines:",
    report["lines"]
)

print(
    "Large Modules:",
    len(report["large_modules"])
)


for item in report["warnings"]:
    print("WARNING:", item)



engine.save_report()