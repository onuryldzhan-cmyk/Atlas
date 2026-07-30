import json
import os
import logging

logger = logging.getLogger("AtlasAI")


class KnowledgeGraph:

    def __init__(self):

        self.file = "knowledge_memory.json"

        self.graph = {
            "nodes": [],
            "edges": []
        }

        self.load()

    # -----------------------------

    def load(self):

        if os.path.exists(self.file):

            with open(
                self.file,
                "r",
                encoding="utf-8"
            ) as f:

                self.graph = json.load(f)

    # -----------------------------

    def save(self):

        with open(
            self.file,
            "w",
            encoding="utf-8"
        ) as f:

            json.dump(
                self.graph,
                f,
                indent=4,
                ensure_ascii=False
            )

    # -----------------------------

    def add_node(
        self,
        node_type,
        name,
        attributes=None
    ):

        if attributes is None:
            attributes = {}

        for node in self.graph["nodes"]:

            if (
                node["type"] == node_type and
                node["name"] == name
            ):
                return node

        node = {

            "id": len(self.graph["nodes"]) + 1,

            "type": node_type,

            "name": name,

            "attributes": attributes

        }

        self.graph["nodes"].append(node)

        self.save()

        return node

    # -----------------------------

    def add_edge(
        self,
        source,
        target,
        relation
    ):

        edge = {

            "source": source,

            "target": target,

            "relation": relation

        }

        self.graph["edges"].append(edge)

        self.save()

        return edge

    # -----------------------------

    def find_node(self, name):

        for node in self.graph["nodes"]:

            if node["name"] == name:
                return node

        return None

    # -----------------------------

    def neighbors(self, name):

        result = []

        for edge in self.graph["edges"]:

            if edge["source"] == name:

                result.append(edge)

        return result

    # -----------------------------

    def statistics(self):

        return {

            "nodes": len(self.graph["nodes"]),

            "edges": len(self.graph["edges"])

        }