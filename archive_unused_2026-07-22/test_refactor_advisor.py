from core.architecture_analyzer import ArchitectureAnalyzer
from core.refactor_advisor import RefactorAdvisor

architecture = ArchitectureAnalyzer().analyze()

advisor = RefactorAdvisor()

report = advisor.advise(architecture)

print("=" * 40)
print(" ATLAS REFACTOR ADVISOR ")
print("=" * 40)

for item in report:
    print(item)