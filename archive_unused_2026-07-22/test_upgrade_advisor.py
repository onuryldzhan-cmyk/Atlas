from core.github_scanner import GithubScanner
from core.code_analyzer import CodeAnalyzer
from core.upgrade_advisor import UpgradeAdvisor



scanner = GithubScanner()

analyzer = CodeAnalyzer()

advisor = UpgradeAdvisor()



projects = scanner.scan(
    "trading"
)



for project in projects:


    analysis = analyzer.analyze(
        project
    )


    upgrade = advisor.generate(
        analysis
    )


    print("==============================")
    print(upgrade)