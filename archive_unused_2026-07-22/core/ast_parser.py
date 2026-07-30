"""
Atlas AI AST Parser v1.0
Read-only source code analyzer.
"""

from __future__ import annotations

import ast
import json
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import List


@dataclass
class ClassInfo:
    name: str
    methods: List[str] = field(default_factory=list)


@dataclass
class ParseResult:
    file: str
    line_count: int = 0

    imports: List[str] = field(default_factory=list)
    classes: List[ClassInfo] = field(default_factory=list)
    functions: List[str] = field(default_factory=list)
    globals: List[str] = field(default_factory=list)

    import_count: int = 0
    class_count: int = 0
    method_count: int = 0
    function_count: int = 0
    dependency_count: int = 0
    complexity_score: int = 0

    dependencies: List[str] = field(default_factory=list)


class ASTParser:
    """
    Atlas AI AST Parser

    Reads Python source code and extracts structural information.
    """

    def __init__(self, file_path: str):
        self.file_path = Path(file_path)

    def parse(self) -> ParseResult:

        source = self.file_path.read_text(
            encoding="utf-8"
        )

        tree = ast.parse(source)

        result = ParseResult(
            file=str(self.file_path),
            line_count=len(source.splitlines())
        )

        for node in tree.body:

            if isinstance(node, ast.Import):

                for alias in node.names:
                    result.imports.append(alias.name)

            elif isinstance(node, ast.ImportFrom):

                result.imports.append(node.module or "")

            elif isinstance(node, ast.FunctionDef):

                result.functions.append(node.name)

            elif isinstance(node, ast.AsyncFunctionDef):

                result.functions.append(node.name)

            elif isinstance(node, ast.Assign):

                for target in node.targets:

                    if isinstance(target, ast.Name):
                        result.globals.append(target.id)

            elif isinstance(node, ast.ClassDef):

                cls = ClassInfo(name=node.name)

                for item in node.body:

                    if isinstance(
                        item,
                        (
                            ast.FunctionDef,
                            ast.AsyncFunctionDef
                        )
                    ):
                        cls.methods.append(item.name)

                result.classes.append(cls)

        result.import_count = len(result.imports)
        result.class_count = len(result.classes)
        result.function_count = len(result.functions)

        result.method_count = sum(
            len(cls.methods)
            for cls in result.classes
        )

        result.dependencies = sorted(
            set(result.imports)
        )

        result.dependency_count = len(
            result.dependencies
        )

        result.complexity_score = (
            result.line_count // 10
            + result.class_count * 10
            + result.method_count * 3
            + result.function_count * 2
        )

        return result

    def export_json(
        self,
        output_file: str
    ) -> None:

        result = self.parse()

        Path(output_file).write_text(

            json.dumps(
                asdict(result),
                indent=4,
                ensure_ascii=False
            ),

            encoding="utf-8"
        )


if __name__ == "__main__":

    parser = ASTParser(
        "core/atlas_brain.py"
    )

    report = parser.parse()

    print(report)