"""
============================================================
ATLAS OS EVENT BUS v1.0
============================================================

Enterprise event distribution infrastructure for AtlasOS.

Responsibilities
----------------
- Publish immutable Atlas events
- Register event subscribers
- Support event-specific subscriptions
- Support wildcard subscriptions
- Isolate subscriber failures
- Maintain bounded event history
- Maintain delivery statistics
- Support correlation identifiers
- Support event severity levels
- Produce diagnostics and snapshots
- Operate as an AtlasOS managed service

Architecture
------------
Publisher
    |
    v
AtlasEventBus
    |
    +-- Event-specific subscribers
    +-- Wildcard subscribers
    +-- Event history
    +-- Delivery statistics
    +-- Failure isolation

Design principles
-----------------
- Thread safe
- Synchronous and deterministic delivery
- Immutable events
- Failure isolated
- Bounded memory usage
- No trading-specific dependencies
- No direct kernel dependency
- Compatible with BaseAtlasService

============================================================
"""

from __future__ import annotations

import logging
import threading
import uuid

from collections import defaultdict, deque
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from types import MappingProxyType
from typing import Any, Callable, Mapping

from atlas_security import sanitize_sensitive_mapping

from atlas_os.contracts import (
    ServiceIdentity,
)
from atlas_os.services import (
    BaseAtlasService,
)


logger = logging.getLogger(
    "AtlasAI.AtlasOS.EventBus"
)


EventHandler = Callable[
    ["AtlasEvent"],
    None,
]


class EventSeverity(StrEnum):
    """
    Standard AtlasOS event severity levels.
    """

    DEBUG = "DEBUG"
    INFO = "INFO"
    WARNING = "WARNING"
    ERROR = "ERROR"
    CRITICAL = "CRITICAL"


class EventBusError(RuntimeError):
    """
    Base exception for Event Bus operations.
    """


class EventBusNotRunningError(EventBusError):
    """
    Raised when publishing is attempted while the bus is stopped.
    """


class SubscriptionNotFoundError(EventBusError):
    """
    Raised when a requested subscription does not exist.
    """


@dataclass(frozen=True, slots=True)
class AtlasEvent:
    """
    Immutable event distributed through AtlasOS Event Bus.
    """

    event_type: str
    source: str
    payload: Mapping[str, Any] = field(
        default_factory=dict
    )
    severity: EventSeverity = EventSeverity.INFO
    correlation_id: str | None = None
    event_id: str = field(
        default_factory=lambda: str(
            uuid.uuid4()
        )
    )
    created_at: datetime = field(
        default_factory=lambda: datetime.now(UTC)
    )

    def __post_init__(self) -> None:

        normalized_type = (
            self.event_type.strip().upper()
        )

        normalized_source = (
            self.source.strip()
        )

        if not normalized_type:
            raise ValueError(
                "Event type cannot be empty."
            )

        if not normalized_source:
            raise ValueError(
                "Event source cannot be empty."
            )

        object.__setattr__(
            self,
            "event_type",
            normalized_type,
        )

        object.__setattr__(
            self,
            "source",
            normalized_source,
        )

        object.__setattr__(
            self,
            "payload",
            MappingProxyType(
                sanitize_sensitive_mapping(
                    self.payload
                )
            ),
        )


@dataclass(frozen=True, slots=True)
class Subscription:
    """
    Immutable Event Bus subscription.
    """

    subscription_id: str
    event_type: str
    subscriber_name: str
    created_at: datetime = field(
        default_factory=lambda: datetime.now(UTC)
    )


@dataclass(frozen=True, slots=True)
class DeliveryFailure:
    """
    Captured subscriber delivery failure.
    """

    event_id: str
    event_type: str
    subscription_id: str
    subscriber_name: str
    error: str
    failed_at: datetime = field(
        default_factory=lambda: datetime.now(UTC)
    )


@dataclass(frozen=True, slots=True)
class PublishResult:
    """
    Result of one Event Bus publish operation.
    """

    event: AtlasEvent
    matched_subscribers: int
    successful_deliveries: int
    failed_deliveries: int
    failures: tuple[DeliveryFailure, ...]
    completed_at: datetime = field(
        default_factory=lambda: datetime.now(UTC)
    )

    @property
    def success(self) -> bool:
        """
        Return True when every matched delivery succeeded.
        """

        return self.failed_deliveries == 0


@dataclass(frozen=True, slots=True)
class EventBusSnapshot:
    """
    Immutable diagnostic snapshot of Event Bus.
    """

    running: bool
    subscription_count: int
    event_type_count: int
    published_events: int
    successful_deliveries: int
    failed_deliveries: int
    history_size: int
    failure_history_size: int
    subscriptions: tuple[Subscription, ...]
    recent_events: tuple[AtlasEvent, ...]
    recent_failures: tuple[DeliveryFailure, ...]
    generated_at: datetime = field(
        default_factory=lambda: datetime.now(UTC)
    )


@dataclass(slots=True)
class _SubscriberRecord:
    """
    Internal mutable subscriber record.
    """

    subscription: Subscription
    handler: EventHandler


class EventBusService(BaseAtlasService):
    """
    AtlasOS central synchronous Event Bus.

    Wildcard subscriptions use the event type "*".

    Example
    -------
    event_bus.subscribe(
        "SERVICE_STARTED",
        on_service_started,
        subscriber_name="HealthMonitor",
    )

    event_bus.publish_event(
        event_type="SERVICE_STARTED",
        source="Kernel",
        payload={"service": "MarketFeed"},
    )
    """

    VERSION = "1.0.0"

    NAME = "AtlasOSEventBus"

    WILDCARD_EVENT_TYPE = "*"

    def __init__(
        self,
        *,
        history_limit: int = 1000,
        failure_history_limit: int = 500,
        require_running: bool = True,
    ) -> None:

        if history_limit <= 0:
            raise ValueError(
                "history_limit must be greater than zero."
            )

        if failure_history_limit <= 0:
            raise ValueError(
                "failure_history_limit must be greater than zero."
            )

        super().__init__(
            ServiceIdentity(
                name=self.NAME,
                version=self.VERSION,
                service_type="EVENT_INFRASTRUCTURE",
                description=(
                    "Central enterprise event distribution "
                    "service for AtlasOS."
                ),
            )
        )

        self._history_limit = int(
            history_limit
        )

        self._failure_history_limit = int(
            failure_history_limit
        )

        self._require_running = bool(
            require_running
        )

        self._subscribers: dict[
            str,
            dict[str, _SubscriberRecord],
        ] = defaultdict(dict)

        self._subscriptions_by_id: dict[
            str,
            _SubscriberRecord,
        ] = {}

        self._event_history: deque[
            AtlasEvent
        ] = deque(
            maxlen=self._history_limit
        )

        self._failure_history: deque[
            DeliveryFailure
        ] = deque(
            maxlen=self._failure_history_limit
        )

        self._published_events = 0
        self._successful_deliveries = 0
        self._failed_deliveries = 0

        self._event_lock = threading.RLock()

    # =====================================================
    # SERVICE LIFECYCLE
    # =====================================================

    def _on_start(self) -> None:
        """
        Initialize Event Bus runtime.
        """

        logger.info(
            "AtlasOS Event Bus started."
        )

    def _on_stop(self) -> None:
        """
        Stop Event Bus runtime.

        Subscriber declarations and event history are preserved so
        that the service may be restarted without reconfiguration.
        """

        logger.info(
            "AtlasOS Event Bus stopped."
        )

    # =====================================================
    # PROPERTIES
    # =====================================================

    @property
    def history_limit(self) -> int:
        """
        Return maximum retained event count.
        """

        return self._history_limit

    @property
    def failure_history_limit(self) -> int:
        """
        Return maximum retained delivery failure count.
        """

        return self._failure_history_limit

    @property
    def subscription_count(self) -> int:
        """
        Return active subscription count.
        """

        with self._event_lock:
            return len(
                self._subscriptions_by_id
            )

    @property
    def published_events(self) -> int:
        """
        Return total published event count.
        """

        with self._event_lock:
            return self._published_events

    @property
    def successful_deliveries(self) -> int:
        """
        Return total successful subscriber deliveries.
        """

        with self._event_lock:
            return self._successful_deliveries

    @property
    def failed_deliveries(self) -> int:
        """
        Return total failed subscriber deliveries.
        """

        with self._event_lock:
            return self._failed_deliveries

    # =====================================================
    # SUBSCRIPTIONS
    # =====================================================

    def subscribe(
        self,
        event_type: str,
        handler: EventHandler,
        *,
        subscriber_name: str | None = None,
    ) -> Subscription:
        """
        Subscribe a handler to an event type.

        Use "*" to subscribe to every published event.
        """

        if not callable(handler):
            raise TypeError(
                "Event handler must be callable."
            )

        normalized_event_type = (
            self._normalize_event_type(
                event_type
            )
        )

        resolved_subscriber_name = (
            subscriber_name.strip()
            if subscriber_name is not None
            else self._resolve_handler_name(
                handler
            )
        )

        if not resolved_subscriber_name:
            raise ValueError(
                "Subscriber name cannot be empty."
            )

        subscription = Subscription(
            subscription_id=str(
                uuid.uuid4()
            ),
            event_type=normalized_event_type,
            subscriber_name=(
                resolved_subscriber_name
            ),
        )

        record = _SubscriberRecord(
            subscription=subscription,
            handler=handler,
        )

        with self._event_lock:

            self._subscribers[
                normalized_event_type
            ][
                subscription.subscription_id
            ] = record

            self._subscriptions_by_id[
                subscription.subscription_id
            ] = record

        logger.info(
            "AtlasOS event subscriber registered: "
            "%s -> %s",
            resolved_subscriber_name,
            normalized_event_type,
        )

        return subscription

    def unsubscribe(
        self,
        subscription_id: str,
    ) -> Subscription:
        """
        Remove an existing subscription.
        """

        normalized_id = (
            subscription_id.strip()
        )

        if not normalized_id:
            raise ValueError(
                "Subscription ID cannot be empty."
            )

        with self._event_lock:

            record = (
                self._subscriptions_by_id.get(
                    normalized_id
                )
            )

            if record is None:
                raise SubscriptionNotFoundError(
                    f"Subscription '{normalized_id}' "
                    "was not found."
                )

            event_type = (
                record.subscription.event_type
            )

            del self._subscriptions_by_id[
                normalized_id
            ]

            del self._subscribers[
                event_type
            ][
                normalized_id
            ]

            if not self._subscribers[
                event_type
            ]:
                del self._subscribers[
                    event_type
                ]

        logger.info(
            "AtlasOS event subscription removed: "
            "%s",
            normalized_id,
        )

        return record.subscription

    def subscriptions(
        self,
        event_type: str | None = None,
    ) -> tuple[Subscription, ...]:
        """
        Return active subscriptions.

        When event_type is provided, only matching subscriptions
        are returned.
        """

        with self._event_lock:

            if event_type is None:

                records = tuple(
                    self._subscriptions_by_id.values()
                )

            else:

                normalized_type = (
                    self._normalize_event_type(
                        event_type
                    )
                )

                records = tuple(
                    self._subscribers.get(
                        normalized_type,
                        {},
                    ).values()
                )

            return tuple(
                record.subscription
                for record in records
            )

    # =====================================================
    # PUBLISHING
    # =====================================================

    def publish(
        self,
        event: AtlasEvent,
    ) -> PublishResult:
        """
        Publish an immutable Atlas event.

        Subscriber failures are captured and isolated. One failing
        subscriber does not prevent other subscribers from receiving
        the event.
        """

        if not isinstance(event, AtlasEvent):
            raise TypeError(
                "event must be an AtlasEvent instance."
            )

        if (
            self._require_running
            and not self.is_running
        ):
            raise EventBusNotRunningError(
                "AtlasOS Event Bus must be running "
                "before events can be published."
            )

        with self._event_lock:

            event_specific_records = tuple(
                self._subscribers.get(
                    event.event_type,
                    {},
                ).values()
            )

            wildcard_records = tuple(
                self._subscribers.get(
                    self.WILDCARD_EVENT_TYPE,
                    {},
                ).values()
            )

            delivery_records = (
                event_specific_records
                + wildcard_records
            )

            self._event_history.append(
                event
            )

            self._published_events += 1

        failures: list[
            DeliveryFailure
        ] = []

        successful = 0

        for record in delivery_records:

            try:

                record.handler(
                    event
                )

                successful += 1

            except Exception as exc:

                failure = DeliveryFailure(
                    event_id=event.event_id,
                    event_type=event.event_type,
                    subscription_id=(
                        record
                        .subscription
                        .subscription_id
                    ),
                    subscriber_name=(
                        record
                        .subscription
                        .subscriber_name
                    ),
                    error=(
                        f"{type(exc).__name__}: {exc}"
                    ),
                )

                failures.append(
                    failure
                )

                logger.exception(
                    "AtlasOS Event Bus subscriber failed | "
                    "event=%s | subscriber=%s",
                    event.event_type,
                    record.subscription.subscriber_name,
                )

        with self._event_lock:

            self._successful_deliveries += (
                successful
            )

            self._failed_deliveries += len(
                failures
            )

            self._failure_history.extend(
                failures
            )

        return PublishResult(
            event=event,
            matched_subscribers=len(
                delivery_records
            ),
            successful_deliveries=successful,
            failed_deliveries=len(
                failures
            ),
            failures=tuple(
                failures
            ),
        )

    def publish_event(
        self,
        *,
        event_type: str,
        source: str,
        payload: Mapping[str, Any] | None = None,
        severity: EventSeverity = EventSeverity.INFO,
        correlation_id: str | None = None,
    ) -> PublishResult:
        """
        Construct and publish an Atlas event.
        """

        event = AtlasEvent(
            event_type=event_type,
            source=source,
            payload=payload or {},
            severity=severity,
            correlation_id=correlation_id,
        )

        return self.publish(
            event
        )

    # =====================================================
    # HISTORY
    # =====================================================

    def event_history(
        self,
        *,
        event_type: str | None = None,
    ) -> tuple[AtlasEvent, ...]:
        """
        Return retained events.

        Optionally filter by event type.
        """

        with self._event_lock:

            events = tuple(
                self._event_history
            )

        if event_type is None:
            return events

        normalized_type = (
            self._normalize_event_type(
                event_type
            )
        )

        return tuple(
            event
            for event in events
            if event.event_type
            == normalized_type
        )

    def failure_history(
        self,
    ) -> tuple[DeliveryFailure, ...]:
        """
        Return retained subscriber delivery failures.
        """

        with self._event_lock:

            return tuple(
                self._failure_history
            )

    def clear_history(self) -> None:
        """
        Clear event and delivery failure history.

        Lifetime delivery counters are not reset.
        """

        with self._event_lock:

            self._event_history.clear()
            self._failure_history.clear()

    def reset_statistics(self) -> None:
        """
        Reset lifetime Event Bus statistics.
        """

        with self._event_lock:

            self._published_events = 0
            self._successful_deliveries = 0
            self._failed_deliveries = 0

    # =====================================================
    # SNAPSHOT
    # =====================================================

    def event_bus_snapshot(
        self,
    ) -> EventBusSnapshot:
        """
        Return complete Event Bus diagnostics.
        """

        with self._event_lock:

            subscriptions = tuple(
                record.subscription
                for record
                in self._subscriptions_by_id.values()
            )

            return EventBusSnapshot(
                running=self.is_running,
                subscription_count=len(
                    subscriptions
                ),
                event_type_count=len(
                    self._subscribers
                ),
                published_events=(
                    self._published_events
                ),
                successful_deliveries=(
                    self._successful_deliveries
                ),
                failed_deliveries=(
                    self._failed_deliveries
                ),
                history_size=len(
                    self._event_history
                ),
                failure_history_size=len(
                    self._failure_history
                ),
                subscriptions=subscriptions,
                recent_events=tuple(
                    self._event_history
                ),
                recent_failures=tuple(
                    self._failure_history
                ),
            )

    # =====================================================
    # BASE SERVICE DIAGNOSTICS
    # =====================================================

    def _health_details(
        self,
    ) -> Mapping[str, Any]:
        """
        Return Event Bus health details.
        """

        with self._event_lock:

            return {
                "subscription_count": len(
                    self._subscriptions_by_id
                ),
                "event_type_count": len(
                    self._subscribers
                ),
                "published_events": (
                    self._published_events
                ),
                "successful_deliveries": (
                    self._successful_deliveries
                ),
                "failed_deliveries": (
                    self._failed_deliveries
                ),
                "history_size": len(
                    self._event_history
                ),
                "failure_history_size": len(
                    self._failure_history
                ),
            }

    def _snapshot_metadata(
        self,
    ) -> Mapping[str, Any]:
        """
        Return Event Bus configuration metadata.
        """

        return {
            "history_limit": (
                self._history_limit
            ),
            "failure_history_limit": (
                self._failure_history_limit
            ),
            "require_running": (
                self._require_running
            ),
            "delivery_mode": "SYNCHRONOUS",
        }

    # =====================================================
    # INTERNAL HELPERS
    # =====================================================

    @classmethod
    def _normalize_event_type(
        cls,
        event_type: str,
    ) -> str:
        """
        Normalize an event type.
        """

        if not isinstance(event_type, str):
            raise TypeError(
                "Event type must be a string."
            )

        normalized = (
            event_type.strip().upper()
        )

        if not normalized:
            raise ValueError(
                "Event type cannot be empty."
            )

        if normalized == cls.WILDCARD_EVENT_TYPE:
            return normalized

        return normalized

    @staticmethod
    def _resolve_handler_name(
        handler: EventHandler,
    ) -> str:
        """
        Resolve a readable subscriber name from a callable.
        """

        name = getattr(
            handler,
            "__qualname__",
            None,
        )

        if name:
            return str(name)

        return handler.__class__.__name__
