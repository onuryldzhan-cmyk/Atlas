"""
Atlas AI Core Events v5.0

Responsibility:
- Define internal Atlas events
- Provide common event structure
- Enable event-driven architecture

Events do not execute actions.
They only describe something that happened.
"""


from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Dict, Any
import uuid

from atlas_security import sanitize_sensitive_mapping



class EventType(Enum):
    """
    All supported Atlas events.
    """


    # Runtime

    RUNTIME_STARTED = (
        "runtime_started"
    )

    RUNTIME_STOPPED = (
        "runtime_stopped"
    )

    RUNTIME_FAILED = (
        "runtime_failed"
    )


    # Market

    MARKET_UPDATED = (
        "market_updated"
    )

    MARKET_SCAN_COMPLETED = (
        "market_scan_completed"
    )


    # Analysis

    ANALYSIS_COMPLETED = (
        "analysis_completed"
    )


    # Decision

    DECISION_CREATED = (
        "decision_created"
    )


    # Trading

    TRADE_OPENED = (
        "trade_opened"
    )

    TRADE_CLOSED = (
        "trade_closed"
    )


    # Learning

    LEARNING_COMPLETED = (
        "learning_completed"
    )



@dataclass
class AtlasEvent:
    """
    Base event object.

    Every event inside Atlas
    inherits this structure.
    """


    event_type: EventType


    source: str


    payload: Dict[str, Any] = field(
        default_factory=dict
    )


    created_at: datetime = field(
        default_factory=lambda:
        datetime.now(timezone.utc)
    )


    event_id: str = field(
        default_factory=lambda:
        str(uuid.uuid4())
    )


    def to_dict(self):

        return {

            "id":
                self.event_id,

            "type":
                self.event_type.value,

            "source":
                self.source,

            "created_at":
                self.created_at.isoformat(),

            "payload":
                sanitize_sensitive_mapping(
                    self.payload
                )
        }



# Specialized events


class RuntimeStartedEvent(
    AtlasEvent
):

    def __init__(
        self,
        source="runtime"
    ):

        super().__init__(
            event_type=
                EventType.RUNTIME_STARTED,

            source=source
        )



class RuntimeStoppedEvent(
    AtlasEvent
):

    def __init__(
        self,
        source="runtime"
    ):

        super().__init__(
            event_type=
                EventType.RUNTIME_STOPPED,

            source=source
        )



class TradeOpenedEvent(
    AtlasEvent
):

    def __init__(
        self,
        symbol: str,
        price: float,
        side: str
    ):

        super().__init__(
            event_type=
                EventType.TRADE_OPENED,

            source="executor",

            payload={

                "symbol":
                    symbol,

                "price":
                    price,

                "side":
                    side

            }
        )
