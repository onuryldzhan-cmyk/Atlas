from __future__ import annotations

from datetime import datetime, UTC



class PerformanceEvaluator:


    VERSION = "1.0"



    def evaluate(
        self,
        before_score,
        after_score
    ):


        difference = (
            after_score -
            before_score
        )



        if difference > 0:

            result = "IMPROVED"


        elif difference < 0:

            result = "WORSE"


        else:

            result = "NO_CHANGE"



        return {


            "time":
                datetime.now(UTC).isoformat(),


            "before":
                before_score,


            "after":
                after_score,


            "difference":
                difference,


            "result":
                result,


            "message":
                self.message(result, difference)

        }



    def message(
        self,
        result,
        difference
    ):


        if result == "IMPROVED":

            return (
                f"Atlas gelişti. "
                f"+{difference} puan artış."
            )


        if result == "WORSE":

            return (
                f"Değişiklik başarısız. "
                f"{difference} puan düşüş."
            )


        return "Değişiklik etkisiz."