"""
============================================================
ATLAS MARKET SOURCE INSPECTOR v1.0
============================================================

Reads selected market-data source files without importing them.

This avoids:
- Network calls
- Test execution
- Thread startup
- Module side effects

============================================================
"""

from __future__ import annotations

import ast

from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent


TARGET_FILES = (
    "data/market_provider.py",
    "data/binance_provider.py",
    "data/candle_manager.py",
    "core/candle_processor.py",
    "exchange/market_feed.py",
    "exchange/exchange_manager.py",
    "exchange/adapters/binance_global.py",
)


def separator(
    title: str,
) -> None:
    print()
    print("=" * 88)
    print(title)
    print("=" * 88)


def inspect_file(
    relative_path: str,
) -> None:
    file_path = (
        PROJECT_ROOT
        / Path(relative_path)
    )

    separator(
        relative_path
    )

    if not file_path.exists():
        print(
            "STATUS: FILE NOT FOUND"
        )
        return

    source = file_path.read_text(
        encoding="utf-8-sig"
    )

    print(
        "STATUS: FOUND"
    )

    print(
        "LINES:",
        len(
            source.splitlines()
        ),
    )

    try:
        tree = ast.parse(
            source,
            filename=str(
                file_path
            ),
        )

    except SyntaxError as error:
        print(
            "SYNTAX ERROR:",
            error,
        )

        print()
        print("SOURCE")
        print(source)

        return

    imports = []
    classes = []
    functions = []
    module_expressions = []
    main_guard_found = False

    for node in tree.body:
        if isinstance(
            node,
            ast.Import,
        ):
            imports.extend(
                alias.name
                for alias in node.names
            )

        elif isinstance(
            node,
            ast.ImportFrom,
        ):
            module_name = (
                node.module or ""
            )

            imports.append(
                module_name
            )

        elif isinstance(
            node,
            ast.ClassDef,
        ):
            classes.append(
                node.name
            )

        elif isinstance(
            node,
            (
                ast.FunctionDef,
                ast.AsyncFunctionDef,
            ),
        ):
            functions.append(
                node.name
            )

        elif isinstance(
            node,
            ast.If,
        ):
            condition = ast.dump(
                node.test,
                include_attributes=False,
            )

            if (
                "__name__"
                in condition
                and "__main__"
                in condition
            ):
                main_guard_found = True

        elif isinstance(
            node,
            ast.Expr,
        ):
            module_expressions.append(
                ast.unparse(
                    node
                )
            )

        elif isinstance(
            node,
            (
                ast.Assign,
                ast.AnnAssign,
            ),
        ):
            continue

        else:
            module_expressions.append(
                ast.unparse(
                    node
                )
            )

    print()
    print("IMPORTS")

    if imports:
        for imported_module in imports:
            print(
                "-",
                imported_module,
            )
    else:
        print(
            "- <none>"
        )

    print()
    print("CLASSES")

    if classes:
        for class_name in classes:
            print(
                "-",
                class_name,
            )
    else:
        print(
            "- <none>"
        )

    print()
    print("FUNCTIONS")

    if functions:
        for function_name in functions:
            print(
                "-",
                function_name,
            )
    else:
        print(
            "- <none>"
        )

    print()
    print(
        "MAIN GUARD:",
        main_guard_found,
    )

    print()
    print("POSSIBLE MODULE-SCOPE SIDE EFFECTS")

    if module_expressions:
        for expression in module_expressions:
            print(
                "-",
                expression,
            )
    else:
        print(
            "- <none>"
        )

    print()
    print("SOURCE")
    print("-" * 88)
    print(source)


def main() -> int:
    separator(
        "ATLAS MARKET SOURCE INSPECTION"
    )

    for relative_path in TARGET_FILES:
        inspect_file(
            relative_path
        )

    separator(
        "INSPECTION COMPLETED"
    )

    return 0


if __name__ == "__main__":
    raise SystemExit(
        main()
    )