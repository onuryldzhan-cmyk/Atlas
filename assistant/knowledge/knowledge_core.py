from __future__ import annotations

from pathlib import Path
from datetime import datetime, UTC
import json


class KnowledgeCore:

    VERSION = "1.0"


    def __init__(self, root="."):

        self.root = Path(root)

        self.file = (
            self.root /
            "atlas_knowledge.json"
        )



    def load(self):

        if not self.file.exists():

            return {

                "facts": [],

                "history": []

            }


        with open(
            self.file,
            "r",
            encoding="utf-8"
        ) as f:

            return json.load(f)



    def save(self, data):

        with open(
            self.file,
            "w",
            encoding="utf-8"
        ) as f:

            json.dump(
                data,
                f,
                indent=4,
                ensure_ascii=False
            )



    def remember(
        self,
        category,
        information
    ):

        data = self.load()


        item = {

            "time":
                datetime.now(UTC).isoformat(),

            "category":
                category,

            "information":
                information

        }


        data["facts"].append(
            item
        )


        self.save(
            data
        )


        return item



    def history(
        self,
        event
    ):

        data = self.load()


        item = {

            "time":
                datetime.now(UTC).isoformat(),

            "event":
                event

        }


        data["history"].append(
            item
        )


        self.save(
            data
        )


        return item