from __future__ import annotations

from datetime import datetime, UTC


class AdvisorEngine:


    VERSION = "1.0"



    def analyze(
        self,
        awareness,
        improvement,
        evolution
    ):


        report = {


            "engine":
                "Atlas Advisor Engine",


            "version":
                self.VERSION,


            "time":
                datetime.now(UTC).isoformat(),


            "system_health":
                "UNKNOWN",


            "score":
                0,


            "recommendations":
                []

        }



        score = 100



        files = awareness.get(
            "python_files",
            0
        )


        large = len(
            awareness.get(
                "large_modules",
                []
            )
        )



        if files > 300:

            score -= 10

            report["recommendations"].append(

                "Kod tabanı büyük. Mikro servis mimarisine geçiş düşünülmeli."

            )



        if large > 20:

            score -= 20

            report["recommendations"].append(

                "Büyük modüller refactor edilmeli."

            )



        if len(
            improvement.get(
                "issues",
                []
            )
        ) > 30:


            score -= 10


            report["recommendations"].append(

                "Öncelikli teknik borç temizliği yapılmalı."

            )



        if evolution.get(
            "planned",
            0
        ) > 0:


            report["recommendations"].append(

                "Planlanan geliştirmeler uygulanmalı ve ölçülmeli."

            )



        report["score"] = max(
            score,
            0
        )



        if score >= 80:

            report["system_health"] = "GOOD"


        elif score >= 50:

            report["system_health"] = "DEVELOPING"


        else:

            report["system_health"] = "NEEDS_REFACTOR"



        return report