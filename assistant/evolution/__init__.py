from __future__ import annotations

from pathlib import Path
from datetime import datetime, UTC
import json


class EvolutionEngine:


    VERSION = "1.0"



    def __init__(self, root="."):

        self.root = Path(root)

        self.memory_file = (
            self.root /
            "atlas_evolution_memory.json"
        )



    def load_memory(self):

        if not self.memory_file.exists():

            return []


        try:

            with open(
                self.memory_file,
                "r",
                encoding="utf-8"
            ) as f:

                return json.load(f)


        except Exception:

            return []




    def save_memory(self, data):

        with open(
            self.memory_file,
            "w",
            encoding="utf-8"
        ) as f:

            json.dump(
                data,
                f,
                indent=4,
                ensure_ascii=False
            )




    def register_improvement(
        self,
        recommendation
    ):


        memory = self.load_memory()


        item = {

            "id":
                len(memory)+1,

            "time":
                datetime.now(UTC).isoformat(),

            "status":
                "planned",

            "recommendation":
                recommendation

        }


        memory.append(item)


        self.save_memory(memory)


        return item




    def get_progress(self):


        memory = self.load_memory()


        return {

            "total":
                len(memory),

            "completed":
                len(

                    [
                        x for x in memory
                        if x.get("status")
                        ==
                        "completed"
                    ]

                ),

            "planned":
                len(

                    [
                        x for x in memory
                        if x.get("status")
                        ==
                        "planned"
                    ]

                )

        }