"""
Atlas Code Smell Detector v1.0

Detects common code quality problems from
codebase_index.json.
"""

from __future__ import annotations

import json
import logging

from pathlib import Path

logger = logging.getLogger("AtlasAI")


class CodeSmellDetector:

    def __init__(

        self,

        index_file="codebase_index.json"

    ):

        self.index_file = Path(index_file)

        self.index = {}

        self.report = []

    # ==========================================
    # LOAD
    # ==========================================

    def load(self):

        if not self.index_file.exists():

            raise FileNotFoundError(
                self.index_file
            )

        with open(

            self.index_file,

            "r",

            encoding="utf-8"

        ) as file:

            self.index = json.load(file)

    # ==========================================
    # ANALYZE
    # ==========================================

    def analyze(self):

        self.report.clear()

        for file_name, info in self.index.items():

            issues = []

            line_count = info.get(
                "line_count",
                0
            )

            complexity = info.get(
                "complexity",
                0
            )

            imports = len(
                info.get(
                    "imports",
                    []
                )
            )

            globals_count = len(
                info.get(
                    "globals",
                    []
                )
            )

            functions = len(
                info.get(
                    "functions",
                    []
                )
            )

            classes = info.get(
                "classes",
                []
            )

            methods = sum(

                len(
                    cls.get(
                        "methods",
                        []
                    )
                )

                for cls in classes

            )

            if line_count > 500:

                issues.append({

                    "level": "CRITICAL",

                    "type": "Long File",

                    "value": line_count

                })

            if complexity > 80:

                issues.append({

                    "level": "CRITICAL",

                    "type": "High Complexity",

                    "value": complexity

                })

            if imports > 20:

                issues.append({

                    "level": "WARNING",

                    "type": "Too Many Imports",

                    "value": imports

                })

            if globals_count > 10:

                issues.append({

                    "level": "WARNING",

                    "type": "Too Many Globals",

                    "value": globals_count

                })

            if functions > 15:

                issues.append({

                    "level": "WARNING",

                    "type": "Too Many Functions",

                    "value": functions

                })

            if methods > 25:

                issues.append({

                    "level": "WARNING",

                    "type": "Too Many Methods",

                    "value": methods

                })

            if len(classes) > 8:

                issues.append({

                    "level": "WARNING",

                    "type": "Large Class Set",

                    "value": len(classes)

                })

            if (

                line_count > 500

                and imports > 20

                and complexity > 80

            ):

                issues.append({

                    "level": "CRITICAL",

                    "type": "God Object",

                    "value": True

                })

            if issues:

                self.report.append({

                    "file": file_name,

                    "issues": issues

                })
    # ==========================================
    # SUMMARY
    # ==========================================

    def summary(self):

        critical = 0
        warning = 0

        for item in self.report:

            for issue in item["issues"]:

                if issue["level"] == "CRITICAL":

                    critical += 1

                else:

                    warning += 1

        return {

            "files_scanned": len(self.index),

            "files_with_smells": len(self.report),

            "critical": critical,

            "warning": warning

        }

    # ==========================================
    # SAVE REPORT
    # ==========================================

    def save(

        self,

        output_file="code_smell_report.json"

    ):

        with open(

            output_file,

            "w",

            encoding="utf-8"

        ) as file:

            json.dump(

                self.report,

                file,

                indent=4,

                ensure_ascii=False

            )

        logger.info(

            "Code smell report saved -> %s",

            output_file

        )

    # ==========================================
    # PRINT REPORT
    # ==========================================

    def print_report(self):

        print("=" * 70)
        print("ATLAS AI CODE SMELL REPORT")
        print("=" * 70)
        print()

        if not self.report:

            print("No code smells detected.")
            return

        for item in self.report:

            print(item["file"])

            for issue in item["issues"]:

                print(

                    f"  [{issue['level']}] "

                    f"{issue['type']} "

                    f"({issue['value']})"

                )

            print()

        stats = self.summary()

        print("=" * 70)

        print(

            f"Files Scanned     : {stats['files_scanned']}"

        )

        print(

            f"Files With Smells : {stats['files_with_smells']}"

        )

        print(

            f"Critical Issues   : {stats['critical']}"

        )

        print(

            f"Warnings          : {stats['warning']}"

        )

        print("=" * 70)


# ==============================================
# MAIN
# ==============================================

if __name__ == "__main__":

    logging.basicConfig(

        level=logging.INFO

    )

    detector = CodeSmellDetector()

    detector.load()

    detector.analyze()

    detector.print_report()

    detector.save()

    print()

    print(

        "code_smell_report.json oluşturuldu."

    )