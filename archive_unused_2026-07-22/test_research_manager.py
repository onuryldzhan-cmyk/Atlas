from core.github_scanner import GithubScanner
from core.code_analyzer import CodeAnalyzer
from core.upgrade_advisor import UpgradeAdvisor
from core.research_manager import ResearchManager



manager = ResearchManager(

    GithubScanner(),

    CodeAnalyzer(),

    UpgradeAdvisor()

)



result = manager.research()



print("==============================")
print(" ATLAS RESEARCH REPORT ")
print("==============================")


for item in result:

    print(item)