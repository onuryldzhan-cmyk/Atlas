from __future__ import annotations

from pathlib import Path
from datetime import datetime, UTC
import json


class SelfAwarenessEngine:

    VERSION = "1.0"


    def __init__(self, project_root="."):

        self.root = Path(project_root)



    def inspect_project(self):

        result = {

            "engine":
                "Atlas Self Awareness",

            "version":
                self.VERSION,

            "time":
                datetime.now(UTC).isoformat(),

            "project":
                str(self.root),

            "modules": 0,

            "python_files": 0,

            "lines": 0,

            "large_modules": [],

            "warnings": []

        }



        for path in self.root.rglob("*.py"):


            if "__pycache__" in path.parts:
                continue



            result["python_files"] += 1



            try:

                content = path.read_text(
                    encoding="utf-8",
                    errors="ignore"
                )


                lines = len(
                    content.splitlines()
                )


            except Exception:

                continue



            result["lines"] += lines



            if path.name != "__init__.py":

                result["modules"] += 1



            if lines > 500:

                result["large_modules"].append(

                    {

                        "file":
                            str(path),

                        "lines":
                            lines,

                        "recommendation":
                            "Bu modül parçalanmalı"

                    }

                )



        if result["python_files"] > 300:

            result["warnings"].append(

                "Büyük kod tabanı. Modüler AI mimarisi gerekli."

            )



        if len(result["large_modules"]) > 10:

            result["warnings"].append(

                "Çok fazla büyük dosya bulundu."

            )



        return result





    def save_report(
        self,
        filename="atlas_self_awareness.json"
    ):


        report = self.inspect_project()


        output = self.root / filename



        with open(
            output,
            "w",
            encoding="utf-8"
        ) as f:

            json.dump(
                report,
                f,
                indent=4,
                ensure_ascii=False
            )



        return output