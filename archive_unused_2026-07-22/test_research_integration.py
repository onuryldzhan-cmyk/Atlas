from core.github_scanner import GithubScanner
from core.code_analyzer import CodeAnalyzer
from core.upgrade_advisor import UpgradeAdvisor
from core.research_manager import ResearchManager
from core.research_integration import ResearchIntegration



research = ResearchManager(

    GithubScanner(),

    CodeAnalyzer(),

    UpgradeAdvisor()

)



results = research.research()



integration = ResearchIntegration()



queue = integration.add_research_results(
    results
)



print("==============================")
print(" ATLAS UPGRADE QUEUE ")
print("==============================")


for item in queue:

    print(item)