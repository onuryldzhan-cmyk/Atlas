"""
Atlas Codebase Indexer v8.0

Scans the entire Atlas project and generates
a structural JSON index for architecture analysis.
"""

from __future__ import annotations

import ast
import json
import logging
from dataclasses import dataclass, asdict, field
from pathlib import Path
from typing import Dict, List

logger = logging.getLogger("AtlasAI")


# ==========================================================
# DATA MODELS
# ==========================================================

@dataclass
class ClassInfo:
    name: str
    methods: List[str] = field(default_factory=list)


@dataclass
class FileIndex:

    path: str

    imports: List[str] = field(default_factory=list)

    classes: List[ClassInfo] = field(default_factory=list)

    functions: List[str] = field(default_factory=list)

    globals: List[str] = field(default_factory=list)

    line_count: int = 0

    complexity: int = 0


# ==========================================================
# INDEXER
# ==========================================================

class CodebaseIndexer:

    def __init__(
        self,
        root="."
    ):

        self.root = Path(root)

        self.index: Dict = {}

    # ======================================================

    def scan(self):

        logger.info("Scanning project...")

        for file in self.root.rglob("*.py"):

            if "__pycache__" in str(file):
                continue

            self.index_file(file)

        logger.info(
            "Indexed %d files.",
            len(self.index)
        )

    # ======================================================

    def index_file(
        self,
        file: Path
    ):

        try:

            source = file.read_text(
                encoding="utf-8"
            )

            tree = ast.parse(source)

        except Exception as e:

            logger.warning(
                "%s skipped (%s)",
                file,
                e
            )

            return

        info = FileIndex(

            path=str(file),

            line_count=len(
                source.splitlines()
            )

        )

        for node in tree.body:

            if isinstance(node, ast.Import):

                for alias in node.names:

                    info.imports.append(
                        alias.name
                    )

            elif isinstance(
                node,
                ast.ImportFrom
            ):

                if node.module:

                    info.imports.append(
                        node.module
                    )

            elif isinstance(
                node,
                ast.FunctionDef
            ):

                info.functions.append(
                    node.name
                )

            elif isinstance(
                node,
                ast.AsyncFunctionDef
            ):

                info.functions.append(
                    node.name
                )

            elif isinstance(
                node,
                ast.Assign
            ):

                for target in node.targets:

                    if isinstance(
                        target,
                        ast.Name
                    ):

                        info.globals.append(
                            target.id
                        )

            elif isinstance(
                node,
                ast.ClassDef
            ):

                cls = ClassInfo(
                    name=node.name
                )

                for item in node.body:

                    if isinstance(
                        item,
                        (
                            ast.FunctionDef,
                            ast.AsyncFunctionDef
                        )
                    ):

                        cls.methods.append(
                            item.name
                        )

                info.classes.append(
                    cls
                )
        method_count = sum(
            len(cls.methods)
            for cls in info.classes
        )

        info.complexity = (
            info.line_count // 10
            + len(info.classes) * 10
            + method_count * 3
            + len(info.functions) * 2
        )

        self.index[str(file)] = {

            "path": info.path,

            "imports": info.imports,

            "classes": [
                {
                    "name": cls.name,
                    "methods": cls.methods
                }
                for cls in info.classes
            ],

            "functions": info.functions,

            "globals": info.globals,

            "line_count": info.line_count,

            "complexity": info.complexity

        }

    # ======================================================
    # SAVE INDEX
    # ======================================================

    def save(
        self,
        output_file="codebase_index.json"
    ):

        with open(
            output_file,
            "w",
            encoding="utf-8"
        ) as file:

            json.dump(

                self.index,

                file,

                indent=4,

                ensure_ascii=False

            )

        logger.info(
            "Codebase index saved -> %s",
            output_file
        )

    # ======================================================
    # SUMMARY
    # ======================================================

    def summary(self):

        files = len(self.index)

        total_classes = 0
        total_functions = 0
        total_imports = 0

        for info in self.index.values():

            total_classes += len(
                info["classes"]
            )

            total_functions += len(
                info["functions"]
            )

            total_imports += len(
                info["imports"]
            )

        return {

            "files": files,

            "classes": total_classes,

            "functions": total_functions,

            "imports": total_imports

        }

    # ======================================================
    # PRINT SUMMARY
    # ======================================================

    def print_summary(self):

        data = self.summary()

        print("=" * 70)
        print("ATLAS CODEBASE INDEX")
        print("=" * 70)

        print(f"Files      : {data['files']}")
        print(f"Classes    : {data['classes']}")
        print(f"Functions  : {data['functions']}")
        print(f"Imports    : {data['imports']}")

        print("=" * 70)


# ==========================================================
# MAIN
# ==========================================================

if __name__ == "__main__":

    logging.basicConfig(
        level=logging.INFO
    )

    indexer = CodebaseIndexer(".")

    indexer.scan()

    indexer.print_summary()

    indexer.save()

    print()

    print("codebase_index.json oluşturuldu.")