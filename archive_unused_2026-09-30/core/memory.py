"""
Atlas AI Memory Core v5.0

Central memory abstraction.

Stores:
- Decisions
- Experiences
- Outcomes
- Patterns

Does NOT:
- Train models
- Make decisions
"""


from __future__ import annotations

from datetime import datetime, timezone
from typing import Dict, Any, List
import logging
import uuid



logger = logging.getLogger(
    "AtlasAI.Memory"
)



class MemoryItem:

    def __init__(
        self,
        category: str,
        data: Dict[str, Any]
    ):

        self.id = str(
            uuid.uuid4()
        )

        self.category = category

        self.data = data

        self.created_at = (
            datetime.now(
                timezone.utc
            )
        )


    def to_dict(self):

        return {

            "id":
                self.id,

            "category":
                self.category,

            "data":
                self.data,

            "created_at":
                self.created_at.isoformat()

        }



class AtlasMemory:
    """
    Main memory manager.
    """


    def __init__(self):

        self.items: List[
            MemoryItem
        ] = []


        logger.info(
            "Atlas Memory initialized."
        )



    def remember(
        self,
        category: str,
        data: Dict[str, Any]
    ):

        item = MemoryItem(
            category,
            data
        )


        self.items.append(
            item
        )


        logger.info(
            "Memory stored: %s",
            category
        )


        return item.id



    def recall(
        self,
        category=None
    ):

        results = []


        for item in self.items:

            if category is None:

                results.append(
                    item.to_dict()
                )


            elif item.category == category:

                results.append(
                    item.to_dict()
                )


        return results



    def search(
        self,
        keyword: str
    ):

        results = []


        for item in self.items:

            text = str(
                item.data
            )


            if keyword.lower() in text.lower():

                results.append(
                    item.to_dict()
                )


        return results



    def count(self):

        return len(
            self.items
        )



    def clear(self):

        self.items.clear()