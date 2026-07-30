"""
Atlas AI Code Cleanup Analyzer v1.0

Purpose:
- Detect unused modules
- Detect backup files
- Detect oversized files
- Analyze import relationships
- Generate cleanup report

IMPORTANT:
This tool NEVER deletes files.
It only reports.
"""

from __future__ import annotations

import os
import ast
from pathlib import Path
from collections import defaultdict


class CodeCleanupAnalyzer:


    def __init__(self, root="."):

        self.root = Path(root)

        self.python_files = []

        self.import_graph = defaultdict(list)

        self.imported_modules = set()

        self.report = {}



    # ------------------------------------------------

    def scan_files(self):

        for path in self.root.rglob("*.py"):

            if "__pycache__" in str(path):
                continue

            self.python_files.append(path)



    # ------------------------------------------------

    def analyze_imports(self):

        for file in self.python_files:

            try:

                tree = ast.parse(
                    file.read_text(
                        encoding="utf-8",
                        errors="ignore"
                    )
                )


                current = str(
                    file
                    .relative_to(self.root)
                )


                for node in ast.walk(tree):

                    if isinstance(node, ast.Import):

                        for item in node.names:

                            self.imported_modules.add(
                                item.name
                            )

                            self.import_graph[current].append(
                                item.name
                            )


                    elif isinstance(node, ast.ImportFrom):

                        if node.module:

                            self.imported_modules.add(
                                node.module
                            )

                            self.import_graph[current].append(
                                node.module
                            )


            except Exception as e:

                print(
                    "[PARSE ERROR]",
                    file,
                    e
                )



    # ------------------------------------------------

    def find_backups(self):

        backups=[]

        for file in self.root.rglob("*"):

            name=file.name.lower()

            if (
                name.endswith(".bak")
                or
                "backup" in name
                or
                "old" in name
            ):

                backups.append(
                    str(file)
                )


        return backups



    # ------------------------------------------------

    def find_large_files(self):

        large=[]


        for file in self.python_files:

            try:

                lines=len(
                    file.read_text(
                        encoding="utf-8",
                        errors="ignore"
                    ).splitlines()
                )


                if lines > 400:

                    large.append(
                        {
                            "file":str(file),
                            "lines":lines
                        }
                    )


            except:

                pass


        return large



    # ------------------------------------------------

    def find_unused_candidates(self):

        unused=[]


        for file in self.python_files:


            module=str(
                file
                .with_suffix("")
                .relative_to(self.root)
            )


            module=module.replace(
                "\\",
                "."
            )


            if module.startswith(
                "test"
            ):

                continue


            found=False


            for imported in self.imported_modules:

                if (
                    module in imported
                    or
                    imported in module
                ):

                    found=True
                    break


            if not found:

                unused.append(
                    str(file)
                )


        return unused



    # ------------------------------------------------

    def run(self):

        print(
            "\n=============================="
        )

        print(
            " ATLAS CODE CLEANUP ANALYZER"
        )

        print(
            "==============================\n"
        )


        self.scan_files()

        self.analyze_imports()


        self.report = {

            "total_python_files":
                len(self.python_files),


            "backup_candidates":
                self.find_backups(),


            "large_files":
                self.find_large_files(),


            "unused_candidates":
                self.find_unused_candidates()

        }


        return self.report



    # ------------------------------------------------

    def print_report(self):

        r=self.report


        print(
            "\nTOTAL PYTHON FILES:"
        )

        print(
            r["total_python_files"]
        )


        print(
            "\nBACKUP FILES:"
        )

        for x in r["backup_candidates"]:

            print(
                " -",
                x
            )



        print(
            "\nLARGE FILES:"
        )

        for x in r["large_files"]:

            print(
                " -",
                x["file"],
                "(",
                x["lines"],
                "lines)"
            )



        print(
            "\nUNUSED CANDIDATES:"
        )

        for x in r["unused_candidates"]:

            print(
                " -",
                x
            )



if __name__ == "__main__":


    analyzer = CodeCleanupAnalyzer(
        "."
    )


    analyzer.run()

    analyzer.print_report()