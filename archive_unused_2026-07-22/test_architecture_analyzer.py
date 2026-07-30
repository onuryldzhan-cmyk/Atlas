from core.architecture_analyzer import ArchitectureAnalyzer

print("=" * 40)
print(" ATLAS ARCHITECTURE ANALYZER ")
print("=" * 40)

analyzer = ArchitectureAnalyzer()

report = analyzer.analyze()

print()

print("===== LARGE FILES =====")
for item in report["large_files"]:
    print(item)

print()

print("===== LARGE CLASSES =====")
for item in report["large_classes"]:
    print(item)

print()

print("===== RECOMMENDATIONS =====")
for item in report["recommendations"]:
    print("-", item)