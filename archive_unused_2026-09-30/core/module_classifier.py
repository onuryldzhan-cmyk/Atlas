"""
Atlas Module Classifier v1.1

Atlas Code Intelligence Component

Features:
- Scan project modules
- Ignore archive folders
- Classify modules
- Count lines
- Detect large files
- Generate report
"""

import os
import json
from datetime import datetime


class ModuleClassifier:

    def __init__(self, root="."):

        self.root = root

        self.categories = {

            "CORE": [],
            "AI": [],
            "TRADING": [],
            "LEARNING": [],
            "DATA": [],
            "DATABASE": [],
            "ANALYSIS": [],
            "TEST": [],
            "CONFIG": [],
            "WEB": [],
            "UNKNOWN": []
        }


        self.modules = []


    def scan(self):

        for root, dirs, files in os.walk(self.root):

            # Gereksiz klasörleri atla
            dirs[:] = [
                d for d in dirs
                if not (
                    d.startswith("archive")
                    or d.startswith("backup")
                    or d.startswith("old")
                    or d.startswith("temp")
                    or d in [
                        "__pycache__",
                        ".git",
                        ".venv",
                        "venv"
                    ]
                )
            ]


            for file in files:

                if not file.endswith(".py"):
                    continue


                path = os.path.join(
                    root,
                    file
                )


                info = self.analyze_file(path)


                self.modules.append(info)


                self.classify(path, info)



        return self.categories



    def analyze_file(self, path):

        try:

            with open(
                path,
                "r",
                encoding="utf-8"
            ) as f:

                lines = f.readlines()


            return {

                "file": path,

                "lines": len(lines),

                "size_kb":
                    round(
                        os.path.getsize(path) / 1024,
                        2
                    )
            }


        except Exception:


            return {

                "file": path,

                "lines": 0,

                "size_kb": 0
            }



    def classify(self, path, info):

        normalized = path.lower()


        if "test" in normalized:

            self.categories["TEST"].append(info)



        elif (
            "config" in normalized
            or "settings" in normalized
        ):

            self.categories["CONFIG"].append(info)



        elif (
            "database" in normalized
            or "\\db" in normalized
            or "/db" in normalized
        ):

            self.categories["DATABASE"].append(info)



        elif (
            "learning" in normalized
            or "memory" in normalized
        ):

            self.categories["LEARNING"].append(info)



        elif (
            "strategy" in normalized
            or "trade" in normalized
            or "order" in normalized
        ):

            self.categories["TRADING"].append(info)



        elif (
            "ai" in normalized
            or "brain" in normalized
        ):

            self.categories["AI"].append(info)



        elif (
            "data" in normalized
            or "provider" in normalized
        ):

            self.categories["DATA"].append(info)



        elif (
            "analysis" in normalized
            or "analyzer" in normalized
        ):

            self.categories["ANALYSIS"].append(info)



        elif (
            "web" in normalized
            or "api" in normalized
        ):

            self.categories["WEB"].append(info)



        elif (
            "\\core\\" in normalized
            or "/core/" in normalized
        ):

            self.categories["CORE"].append(info)



        else:

            self.categories["UNKNOWN"].append(info)



    def generate_report(self):

        large_files = [

            m for m in self.modules
            if m["lines"] > 400

        ]


        report = {


            "generated":

                datetime.now().isoformat(),


            "total_modules":

                len(self.modules),


            "large_files":

                large_files,


            "categories":

                self.categories

        }


        with open(

            "atlas_module_report.json",

            "w",

            encoding="utf-8"

        ) as f:


            json.dump(

                report,

                f,

                indent=4,

                ensure_ascii=False

            )


        return report



if __name__ == "__main__":


    print("=" * 60)

    print(
        " ATLAS MODULE CLASSIFIER v1.1 "
    )

    print("=" * 60)



    classifier = ModuleClassifier(".")


    classifier.scan()


    report = classifier.generate_report()



    for category, files in report["categories"].items():


        print("\n")

        print(category)

        print("-" * 40)


        for item in files:

            print(
                f'{item["file"]} '
                f'({item["lines"]} lines)'
            )



    print("\n")

    print(
        "TOTAL MODULES:",
        report["total_modules"]
    )


    print("\n")

    print(
        "LARGE FILES:"
    )


    for file in report["large_files"]:

        print(
            file["file"],
            "-",
            file["lines"],
            "lines"
        )