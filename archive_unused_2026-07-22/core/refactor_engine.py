"""
Atlas Refactor Engine v2.0

Code Quality & Refactoring Analyzer

Features
--------
- Project scanning
- AST analysis
- Code metrics
- Issue detection
- Quality score
- Suggestion generation
- JSON memory
"""

from __future__ import annotations

import ast
import json
import logging
import os
from datetime import datetime
from pathlib import Path

logger = logging.getLogger("AtlasAI")


class RefactorEngine:
    """
    Atlas Code Analysis Engine
    """

    def __init__(
        self,
        project_path: str = ".",
        memory_file: str = "refactor_memory.json",
    ):

        self.project_path = Path(project_path)
        self.memory_file = Path(memory_file)

        self.memory = self.load_memory()

        logger.info("Atlas Refactor Engine initialized.")

    # -------------------------------------------------
    # MEMORY
    # -------------------------------------------------

    def load_memory(self):

        if self.memory_file.exists():

            try:

                with open(
                    self.memory_file,
                    "r",
                    encoding="utf-8",
                ) as f:

                    return json.load(f)

            except Exception as e:

                logger.warning(
                    f"Memory load failed: {e}"
                )

        return {

            "last_scan": None,
            "files": [],
            "suggestions": []

        }

    def save_memory(self):

        self.memory["last_scan"] = datetime.now().isoformat()

        with open(
            self.memory_file,
            "w",
            encoding="utf-8",
        ) as f:

            json.dump(
                self.memory,
                f,
                indent=4,
                ensure_ascii=False,
            )

    # -------------------------------------------------
    # PROJECT SCAN
    # -------------------------------------------------

    def scan_project(self):

        logger.info(
            "Atlas project scan started."
        )

        results = []

        for root, _, files in os.walk(
            self.project_path
        ):

            for file in files:

                if not file.endswith(".py"):
                    continue

                path = os.path.join(
                    root,
                    file
                )

                analysis = self.analyze_file(
                    path
                )

                results.append(
                    analysis
                )

        self.memory["files"] = results

        self.save_memory()

        logger.info(
            f"Project scan finished. {len(results)} files analyzed."
        )

        return results
    # -------------------------------------------------
    # FILE ANALYSIS
    # -------------------------------------------------

    def analyze_file(self, path: str):

        logger.debug(f"Analyzing: {path}")

        data = {

            "file": path,
            "lines": 0,
            "functions": 0,
            "classes": 0,
            "imports": 0,
            "issues": [],
            "quality_score": 100

        }

        try:

            with open(
                path,
                "r",
                encoding="utf-8"
            ) as f:

                source = f.read()

            lines = source.splitlines()

            data["lines"] = len(lines)

            tree = ast.parse(source)

            for node in ast.walk(tree):

                if isinstance(node, ast.FunctionDef):

                    data["functions"] += 1

                    function_length = (
                        getattr(node, "end_lineno", node.lineno)
                        - node.lineno
                    )

                    if function_length > 80:

                        data["issues"].append(
                            f"Uzun fonksiyon: {node.name}"
                        )

                        data["quality_score"] -= 5

                elif isinstance(node, ast.ClassDef):

                    data["classes"] += 1

                elif isinstance(
                    node,
                    (
                        ast.Import,
                        ast.ImportFrom
                    )
                ):

                    data["imports"] += 1

            # ----------------------------
            # Basic Metrics
            # ----------------------------

            if data["lines"] > 500:

                data["issues"].append(
                    "Dosya çok büyük (>500 satır)"
                )

                data["quality_score"] -= 10

            if data["functions"] > 30:

                data["issues"].append(
                    "Fonksiyon sayısı yüksek"
                )

                data["quality_score"] -= 8

            if data["classes"] > 10:

                data["issues"].append(
                    "Sınıf sayısı yüksek"
                )

                data["quality_score"] -= 5

            # ----------------------------
            # TODO / FIXME Scan
            # ----------------------------

            for line in lines:

                upper = line.upper()

                if "TODO" in upper:

                    data["issues"].append(
                        "TODO bulundu"
                    )

                    data["quality_score"] -= 1

                if "FIXME" in upper:

                    data["issues"].append(
                        "FIXME bulundu"
                    )

                    data["quality_score"] -= 2

            if data["quality_score"] < 0:

                data["quality_score"] = 0

        except SyntaxError as e:

            data["issues"].append(
                f"SyntaxError: {e}"
            )

            data["quality_score"] = 0

        except Exception as e:

            data["issues"].append(
                str(e)
            )

            data["quality_score"] = 0

        return data
    # -------------------------------------------------
    # SUGGESTION ENGINE
    # -------------------------------------------------

    def generate_suggestions(self):

        logger.info("Generating refactor suggestions...")

        suggestions = []

        files = self.memory.get("files", [])

        for item in files:

            filename = os.path.basename(item["file"])

            # Büyük dosya
            if item["lines"] > 500:

                suggestions.append({

                    "file": filename,
                    "priority": "HIGH",
                    "title": "Dosya çok büyük",
                    "suggestion": (
                        "Dosyayı daha küçük modüllere ayır."
                    )

                })

            # Çok fazla fonksiyon
            if item["functions"] > 30:

                suggestions.append({

                    "file": filename,
                    "priority": "MEDIUM",
                    "title": "Fonksiyon yoğunluğu",
                    "suggestion": (
                        "Bazı fonksiyonları yeni sınıflara taşı."
                    )

                })

            # Kalite skoru düşük
            if item["quality_score"] < 70:

                suggestions.append({

                    "file": filename,
                    "priority": "HIGH",
                    "title": "Kalite skoru düşük",
                    "suggestion": (
                        "Kod gözden geçirilmeli."
                    )

                })

            # Dosyaya özel sorunlar
            for issue in item["issues"]:

                suggestions.append({

                    "file": filename,
                    "priority": "INFO",
                    "title": issue,
                    "suggestion": issue

                })

        self.memory["suggestions"] = suggestions

        self.save_memory()

        logger.info(
            f"{len(suggestions)} suggestions generated."
        )

        return suggestions

    # -------------------------------------------------
    # REPORT
    # -------------------------------------------------

    def report(self):

        files = self.memory.get("files", [])

        if not files:

            return {

                "files_scanned": 0,
                "average_score": 0,
                "best_file": None,
                "worst_file": None,
                "suggestions": 0

            }

        average_score = sum(
            f["quality_score"] for f in files
        ) / len(files)

        best = max(
            files,
            key=lambda x: x["quality_score"]
        )

        worst = min(
            files,
            key=lambda x: x["quality_score"]
        )

        return {

            "files_scanned": len(files),

            "average_score": round(
                average_score,
                2
            ),

            "best_file": best["file"],

            "worst_file": worst["file"],

            "suggestions": len(
                self.memory.get(
                    "suggestions",
                    []
                )
            )

        }
    # -------------------------------------------------
    # PRINT REPORT
    # -------------------------------------------------

    def print_report(self):

        report = self.report()

        print("\n" + "=" * 60)
        print("        ATLAS REFACTOR REPORT")
        print("=" * 60)

        print(f"Files Scanned : {report['files_scanned']}")
        print(f"Average Score : {report['average_score']}")
        print(f"Suggestions   : {report['suggestions']}")

        if report["best_file"]:

            print(f"Best File     : {report['best_file']}")

        if report["worst_file"]:

            print(f"Worst File    : {report['worst_file']}")

        print("=" * 60)

    # -------------------------------------------------
    # EXPORT REPORT
    # -------------------------------------------------

    def export_report(
        self,
        filename="refactor_report.json"
    ):

        report = {

            "summary": self.report(),

            "files": self.memory.get(
                "files",
                []
            ),

            "suggestions": self.memory.get(
                "suggestions",
                []
            )

        }

        with open(
            filename,
            "w",
            encoding="utf-8"
        ) as f:

            json.dump(
                report,
                f,
                indent=4,
                ensure_ascii=False
            )

        logger.info(
            f"Report exported -> {filename}"
        )

        return filename

    # -------------------------------------------------
    # RUN
    # -------------------------------------------------

    def run(self):

        logger.info(
            "Atlas Refactor Engine started."
        )

        self.scan_project()

        self.generate_suggestions()

        self.print_report()

        self.export_report()

        logger.info(
            "Atlas Refactor Engine finished."
        )