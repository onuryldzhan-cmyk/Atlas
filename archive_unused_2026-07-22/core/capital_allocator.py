"""
core/capital_allocator.py
Sermaye büyüklüğü hesaplar.
"""
class CapitalAllocator:
    def allocate(self, decision: dict, confidence: float) -> float:
        if decision.get("action") == "BEKLE":
            return 0.0
        return round((confidence / 100) * 0.1, 4)
