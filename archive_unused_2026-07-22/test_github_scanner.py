from core.github_scanner import GithubScanner



scanner = GithubScanner()


print(
    "===== TRADING PROJECTS ====="
)


projects = scanner.scan(
    "trading"
)


for p in projects:

    print(p)