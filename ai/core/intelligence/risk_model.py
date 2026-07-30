"""
Atlas Risk Model v1.0

Professional risk classification layer.

Responsibilities:

- Convert confidence into risk level
- Protect weak decisions
- Provide execution risk information

"""


from core.decision import RiskLevel



class RiskModel:


    VERSION = "1.0"



    def calculate(
        self,
        confidence: float
    ):


        confidence = max(
            0,
            min(
                confidence,
                1
            )
        )



        if confidence >= 0.75:


            return RiskLevel.LOW



        elif confidence >= 0.55:


            return RiskLevel.MEDIUM



        elif confidence >= 0.40:


            return RiskLevel.HIGH



        else:


            return RiskLevel.CRITICAL