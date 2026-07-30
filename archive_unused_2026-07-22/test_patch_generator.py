from core.architecture_analyzer import ArchitectureAnalyzer
from core.refactor_advisor import RefactorAdvisor
from core.patch_generator import PatchGenerator

architecture = ArchitectureAnalyzer().analyze()

advisor = RefactorAdvisor()

patcher = PatchGenerator()

print("=" * 40)
print(" ATLAS PATCH GENERATOR ")
print("=" * 40)

for proposal in advisor.advise(architecture):

    path = patcher.generate(proposal)

    print(path)