from abc import ABC, abstractmethod


class BaseSignal(ABC):


    def __init__(self, name):

        self.name = name



    @abstractmethod
    def generate(self, data):

        pass



    def result(
        self,
        signal,
        confidence,
        reason
    ):

        return {

            "name": self.name,

            "signal": signal,

            "confidence": round(
                confidence,
                2
            ),

            "reason": reason

        }