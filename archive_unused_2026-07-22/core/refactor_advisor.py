class RefactorAdvisor:

    def advise(self, architecture_report):

        suggestions = []

        for file in architecture_report["large_files"]:

            name = file["file"].lower()

            if "atlas_brain" in name:

                suggestions.append({
                    "file": file["file"],
                    "priority": "CRITICAL",
                    "split_into": [
                        "analysis_core.py",
                        "learning_core.py",
                        "execution_core.py",
                        "research_core.py",
                        "evolution_core.py"
                    ],
                    "reason": "Atlas Brain çok fazla sorumluluk taşıyor."
                })

            elif "outcome_memory" in name:

                suggestions.append({
                    "file": file["file"],
                    "priority": "HIGH",
                    "split_into": [
                        "trade_memory.py",
                        "performance_memory.py"
                    ],
                    "reason": "Outcome Memory iki farklı görevi yönetiyor."
                })

            elif "strategy_competition" in name:

                suggestions.append({
                    "file": file["file"],
                    "priority": "MEDIUM",
                    "split_into": [
                        "strategy_selector.py",
                        "strategy_ranker.py"
                    ],
                    "reason": "Strateji seçimi ve puanlama ayrılmalı."
                })

        return suggestions