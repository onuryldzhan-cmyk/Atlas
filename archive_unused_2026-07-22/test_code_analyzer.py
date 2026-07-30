from core.github_scanner import GithubScanner
from core.code_analyzer import CodeAnalyzer



scanner = GithubScanner()

analyzer = CodeAnalyzer()



projects = scanner.scan(
    "trading"
)



print("==============================")
print(" ATLAS CODE ANALYZER TEST ")
print("==============================")



for project in projects:


    result = analyzer.analyze(
        project
    )


    print("\n")
    print(result)