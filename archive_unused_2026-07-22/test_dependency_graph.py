from core.dependency_graph import DependencyGraph


graph = DependencyGraph()

graph.load()

graph.build()

print("=" * 40)
print(" ATLAS DEPENDENCY GRAPH ")
print("=" * 40)

report = graph.report()

count = 0

for module, info in report.items():

    print()

    print(module)

    print(info)

    count += 1

    if count == 10:
        break


print()

print("=" * 40)
print(" UNUSED MODULES ")
print("=" * 40)

print(graph.unused_modules()[:20])

print()

print("=" * 40)
print(" IMPACT ")
print("=" * 40)

print(graph.impact("decision_engine.py"))