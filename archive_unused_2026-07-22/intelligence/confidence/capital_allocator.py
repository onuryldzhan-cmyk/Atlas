class CapitalAllocator:

    def allocate(
        self,
        confidence
    ):

        if confidence >= 90:
            return {
                "zone": "FULL",
                "capital": 1.00
            }

        elif confidence >= 80:
            return {
                "zone": "CORE",
                "capital": 0.50
            }

        elif confidence >= 70:
            return {
                "zone": "SCALPING",
                "capital": 0.25
            }

        elif confidence >= 60:
            return {
                "zone": "TEST",
                "capital": 0.10
            }

        return {
            "zone": "NONE",
            "capital": 0.00
        }