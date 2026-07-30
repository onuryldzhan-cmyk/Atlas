from learning.model_memory import ModelMemory
from learning.learning_engine import LearningEngine


class AtlasBrain:

    def __init__(self):
        self.memory = ModelMemory()
        self.learning = LearningEngine()

    def think(self):
        trades = self.memory.get_memory()
        learning_data = self.learning.status()
        total = len(trades)

        if total == 0:
            return self._empty_result(learning_data)

        al_success = self._calculate_success(learning_data, "AL")
        sat_success = self._calculate_success(learning_data, "SAT")

        message, confidence = self._determine_strategy(
            al_success, sat_success
        )

        return {
            "message": message,
            "confidence": confidence,
            "trades": total,
            "AL_success": round(al_success, 2),
            "SAT_success": round(sat_success, 2),
            "learning": learning_data
        }

    def _empty_result(self, learning_data):
        return {
            "message": "Henuez yeterli veri yok.",
            "confidence": 50,
            "trades": 0,
            "learning": learning_data
        }

    def _calculate_success(self, learning_data, signal_type):
        if signal_type not in learning_data:
            return 0

        data = learning_data[signal_type]
        if data.get("total", 0) == 0:
            return 0

        return (data["wins"] / data["total"]) * 100

    def _determine_strategy(self, al_success, sat_success):
        if sat_success > al_success:
            message = "Ogrenmeye gore SAT stratejisi guclu."
            confidence = int(50 + (sat_success - al_success) / 2)
        elif al_success > sat_success:
            message = "Ogrenmeye gore AL stratejisi guclu."
            confidence = int(50 + (al_success - sat_success) / 2)
        else:
            message = "Piyasa dengeli."
            confidence = 50

        confidence = max(0, min(confidence, 95))
        return message, confidence

