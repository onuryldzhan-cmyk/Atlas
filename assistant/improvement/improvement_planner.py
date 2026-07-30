from __future__ import annotations

from datetime import datetime, UTC


class ImprovementPlanner:


    VERSION = "1.0"



    def __init__(self):

        self.rules = [

            {
                "keyword": "large",
                "priority": "HIGH",
                "message":
                    "Büyük modüller parçalanmalı."
            },

            {
                "keyword": "memory",
                "priority": "MEDIUM",
                "message":
                    "Bellek sistemi güçlendirilmeli."
            },

            {
                "keyword": "test",
                "priority": "HIGH",
                "message":
                    "Test kapsamı artırılmalı."
            }

        ]



    def create_plan(self, awareness_report):


        plan = {

            "engine":
                "Atlas Improvement Planner",

            "version":
                self.VERSION,

            "created":
                datetime.now(UTC).isoformat(),

            "issues": [],

            "recommendations": []

        }



        large_files = awareness_report.get(
            "large_modules",
            []
        )



        for file in large_files:


            plan["issues"].append(

                {

                    "type":
                        "architecture",

                    "file":
                        file["file"],

                    "severity":
                        "HIGH",

                    "reason":
                        "Dosya karmaşıklığı yüksek"

                }

            )


            plan["recommendations"].append(

                {

                    "action":
                        "refactor",

                    "target":
                        file["file"],

                    "suggestion":
                        "Modülü daha küçük servisler halinde böl"

                }

            )



        warnings = awareness_report.get(
            "warnings",
            []
        )



        for warning in warnings:


            plan["issues"].append(

                {

                    "type":
                        "system",

                    "severity":
                        "MEDIUM",

                    "reason":
                        warning

                }

            )



        return plan