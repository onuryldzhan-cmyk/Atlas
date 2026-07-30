from core.ast_parser import ASTParser


def print_report(result):

    print("=" * 60)
    print("ATLAS AI AST REPORT")
    print("=" * 60)

    print(f"File              : {result.file}")
    print(f"Lines             : {result.line_count}")

    print()

    print(f"Import Count      : {result.import_count}")
    print(f"Class Count       : {result.class_count}")
    print(f"Method Count      : {result.method_count}")
    print(f"Function Count    : {result.function_count}")
    print(f"Dependency Count  : {result.dependency_count}")
    print(f"Complexity Score  : {result.complexity_score}")

    print()

    print("IMPORTS")
    print("-" * 60)

    for item in result.imports:
        print(item)

    print()

    print("DEPENDENCIES")
    print("-" * 60)

    for item in result.dependencies:
        print(item)

    print()

    print("CLASSES")
    print("-" * 60)

    for cls in result.classes:

        print(cls.name)

        for method in cls.methods:
            print(f"   └── {method}")

    print()

    print("GLOBALS")
    print("-" * 60)

    for item in result.globals:
        print(item)


def main():

    parser = ASTParser(
        "core/atlas_brain.py"
    )

    result = parser.parse()

    print_report(result)

    parser.export_json(
        "atlas_ast_report.json"
    )

    print()
    print("JSON raporu oluşturuldu.")
    print("atlas_ast_report.json")


if __name__ == "__main__":
    main()