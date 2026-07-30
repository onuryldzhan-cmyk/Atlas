"""
============================================================
ATLAS OS METRICS SERVICE v1.0
============================================================

Enterprise in-memory metrics infrastructure for AtlasOS.

Responsibilities
----------------
- Maintain counters
- Maintain gauges
- Maintain histogram observations
- Measure execution durations
- Support metric labels
- Subscribe to AtlasOS Event Bus optionally
- Produce immutable metric snapshots
- Provide aggregation statistics
- Maintain bounded histogram observations
- Operate as an AtlasOS managed service
- Provide health and diagnostic information

Architecture
------------
AtlasOS Components
        |
        +-- increment()
        +-- set_gauge()
        +-- observe()
        +-- timer()
        |
        v
MetricsService
        |
        +-- Counters
        +-- Gauges
        +-- Histograms
        +-- Timers
        +-- Event metrics
        +-- Snapshot

Design principles
-----------------
- Thread safe
- Strongly validated
- Label aware
- Bounded memory usage
- Deterministic metric identity
- No external dependency
- No trading-specific dependency
- Backward compatible with AtlasOS services

============================================================
"""

from __future__ import annotations

import math
import re
import threading
import time

from collections import deque
from contextlib import AbstractContextManager
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any, Mapping

from atlas_os.contracts import (
    ServiceIdentity,
)
from atlas_os.events import (
    AtlasEvent,
    EventBusService,
    Subscription,
)
from atlas_os.services import (
    BaseAtlasService,
)


class MetricType(StrEnum):
    """
    Supported AtlasOS metric types.
    """

    COUNTER = "COUNTER"
    GAUGE = "GAUGE"
    HISTOGRAM = "HISTOGRAM"


class MetricsError(RuntimeError):
    """
    Base exception for metrics operations.
    """


class InvalidMetricNameError(MetricsError):
    """
    Raised when a metric name is invalid.
    """


class MetricTypeConflictError(MetricsError):
    """
    Raised when one metric identity is used with multiple types.
    """


@dataclass(frozen=True, slots=True)
class MetricIdentity:
    """
    Immutable metric identity.

    A metric is uniquely identified by its normalized name and labels.
    """

    name: str
    labels: tuple[tuple[str, str], ...] = ()

    def label_dict(self) -> dict[str, str]:
        """
        Return labels as a dictionary.
        """

        return dict(self.labels)


@dataclass(frozen=True, slots=True)
class CounterMetric:
    """
    Immutable counter snapshot.
    """

    identity: MetricIdentity
    value: float
    updated_at: datetime


@dataclass(frozen=True, slots=True)
class GaugeMetric:
    """
    Immutable gauge snapshot.
    """

    identity: MetricIdentity
    value: float
    updated_at: datetime


@dataclass(frozen=True, slots=True)
class HistogramMetric:
    """
    Immutable histogram snapshot.
    """

    identity: MetricIdentity
    count: int
    total: float
    minimum: float | None
    maximum: float | None
    average: float | None
    latest: float | None
    observations: tuple[float, ...]
    updated_at: datetime


@dataclass(frozen=True, slots=True)
class MetricsStatistics:
    """
    Immutable Metrics Service runtime statistics.
    """

    counter_count: int
    gauge_count: int
    histogram_count: int
    total_metric_series: int
    total_updates: int
    counter_updates: int
    gauge_updates: int
    histogram_updates: int
    timer_observations: int
    event_observations: int
    last_metric_name: str | None
    generated_at: datetime = field(
        default_factory=lambda: datetime.now(UTC)
    )


@dataclass(frozen=True, slots=True)
class MetricsSnapshot:
    """
    Complete immutable Metrics Service snapshot.
    """

    running: bool
    event_subscription_active: bool
    counters: tuple[CounterMetric, ...]
    gauges: tuple[GaugeMetric, ...]
    histograms: tuple[HistogramMetric, ...]
    statistics: MetricsStatistics
    generated_at: datetime = field(
        default_factory=lambda: datetime.now(UTC)
    )


@dataclass(slots=True)
class _CounterState:
    """
    Internal mutable counter state.
    """

    value: float = 0.0
    updated_at: datetime = field(
        default_factory=lambda: datetime.now(UTC)
    )


@dataclass(slots=True)
class _GaugeState:
    """
    Internal mutable gauge state.
    """

    value: float = 0.0
    updated_at: datetime = field(
        default_factory=lambda: datetime.now(UTC)
    )


@dataclass(slots=True)
class _HistogramState:
    """
    Internal mutable histogram state.
    """

    count: int = 0
    total: float = 0.0
    minimum: float | None = None
    maximum: float | None = None
    latest: float | None = None
    observations: deque[float] = field(
        default_factory=deque
    )
    updated_at: datetime = field(
        default_factory=lambda: datetime.now(UTC)
    )


class MetricTimer(AbstractContextManager["MetricTimer"]):
    """
    Context manager for recording execution duration.

    Example
    -------
    with metrics.timer(
        "atlas.kernel.start.duration_seconds"
    ):
        kernel.start()
    """

    def __init__(
        self,
        metrics: "MetricsService",
        metric_name: str,
        *,
        labels: Mapping[str, Any] | None = None,
    ) -> None:

        self._metrics = metrics
        self._metric_name = metric_name
        self._labels = dict(
            labels or {}
        )

        self._started_at: float | None = None
        self._finished_at: float | None = None
        self._elapsed_seconds: float | None = None

    @property
    def elapsed_seconds(self) -> float | None:
        """
        Return measured duration after completion.
        """

        return self._elapsed_seconds

    def __enter__(self) -> "MetricTimer":

        self._started_at = time.perf_counter()

        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: Any,
    ) -> bool:

        self._finished_at = time.perf_counter()

        if self._started_at is None:
            raise RuntimeError(
                "Metric timer was not started."
            )

        self._elapsed_seconds = (
            self._finished_at
            - self._started_at
        )

        timer_labels = dict(
            self._labels
        )

        timer_labels["outcome"] = (
            "error"
            if exc is not None
            else "success"
        )

        self._metrics.observe(
            self._metric_name,
            self._elapsed_seconds,
            labels=timer_labels,
            timer_observation=True,
        )

        return False


class MetricsService(BaseAtlasService):
    """
    AtlasOS central in-memory metrics service.

    Metric names are normalized to lowercase. Labels are normalized
    into sorted string key-value pairs.

    Counters cannot decrease.
    Gauges may increase or decrease.
    Histograms retain bounded recent observations.
    """

    VERSION = "1.0.0"

    NAME = "AtlasOSMetrics"

    _METRIC_NAME_PATTERN = re.compile(
        r"^[A-Za-z][A-Za-z0-9_.:-]*$"
    )

    def __init__(
        self,
        *,
        histogram_history_limit: int = 1000,
        event_bus: EventBusService | None = None,
        collect_event_metrics: bool = False,
    ) -> None:

        if histogram_history_limit <= 0:
            raise ValueError(
                "histogram_history_limit must be greater than zero."
            )

        if (
            event_bus is not None
            and not isinstance(
                event_bus,
                EventBusService,
            )
        ):
            raise TypeError(
                "event_bus must be an EventBusService instance."
            )

        if (
            collect_event_metrics
            and event_bus is None
        ):
            raise ValueError(
                "event_bus is required when "
                "collect_event_metrics is enabled."
            )

        super().__init__(
            ServiceIdentity(
                name=self.NAME,
                version=self.VERSION,
                service_type="OBSERVABILITY",
                description=(
                    "Central in-memory metrics collection "
                    "service for AtlasOS."
                ),
            )
        )

        self._histogram_history_limit = int(
            histogram_history_limit
        )

        self._event_bus = event_bus
        self._collect_event_metrics = bool(
            collect_event_metrics
        )

        self._event_subscription: (
            Subscription | None
        ) = None

        self._counters: dict[
            MetricIdentity,
            _CounterState,
        ] = {}

        self._gauges: dict[
            MetricIdentity,
            _GaugeState,
        ] = {}

        self._histograms: dict[
            MetricIdentity,
            _HistogramState,
        ] = {}

        self._metric_types: dict[
            MetricIdentity,
            MetricType,
        ] = {}

        self._total_updates = 0
        self._counter_updates = 0
        self._gauge_updates = 0
        self._histogram_updates = 0
        self._timer_observations = 0
        self._event_observations = 0

        self._last_metric_name: str | None = None

        self._metrics_lock = threading.RLock()

    # =====================================================
    # SERVICE LIFECYCLE
    # =====================================================

    def _on_start(self) -> None:
        """
        Activate optional Event Bus metric collection.
        """

        if (
            self._collect_event_metrics
            and self._event_bus is not None
            and self._event_subscription is None
        ):

            self._event_subscription = (
                self._event_bus.subscribe(
                    "*",
                    self._observe_event,
                    subscriber_name=self.identity.name,
                )
            )

        self.set_gauge(
            "atlas.metrics.service.running",
            1.0,
        )

    def _on_stop(self) -> None:
        """
        Remove optional Event Bus subscription.
        """

        subscription = self._event_subscription

        if (
            subscription is not None
            and self._event_bus is not None
        ):

            try:

                self._event_bus.unsubscribe(
                    subscription.subscription_id
                )

            except Exception:
                pass

        self._event_subscription = None

        self.set_gauge(
            "atlas.metrics.service.running",
            0.0,
        )

    # =====================================================
    # PROPERTIES
    # =====================================================

    @property
    def histogram_history_limit(self) -> int:
        """
        Return maximum retained observations per histogram.
        """

        return self._histogram_history_limit

    @property
    def event_subscription_active(self) -> bool:
        """
        Return True when Event Bus collection is active.
        """

        with self._metrics_lock:
            return self._event_subscription is not None

    @property
    def metric_series_count(self) -> int:
        """
        Return total unique metric series count.
        """

        with self._metrics_lock:

            return (
                len(self._counters)
                + len(self._gauges)
                + len(self._histograms)
            )

    # =====================================================
    # COUNTERS
    # =====================================================

    def increment(
        self,
        name: str,
        amount: float = 1.0,
        *,
        labels: Mapping[str, Any] | None = None,
    ) -> float:
        """
        Increment a counter.

        Counter increments must be finite and non-negative.
        """

        value = self._normalize_number(
            amount
        )

        if value < 0:
            raise ValueError(
                "Counter increment cannot be negative."
            )

        identity = self._build_identity(
            name,
            labels,
        )

        with self._metrics_lock:

            self._assert_metric_type(
                identity,
                MetricType.COUNTER,
            )

            state = self._counters.setdefault(
                identity,
                _CounterState(),
            )

            state.value += value
            state.updated_at = datetime.now(UTC)

            self._record_update(
                identity.name,
                MetricType.COUNTER,
            )

            return state.value

    def counter_value(
        self,
        name: str,
        *,
        labels: Mapping[str, Any] | None = None,
        default: float | None = None,
    ) -> float | None:
        """
        Return a counter value.
        """

        identity = self._build_identity(
            name,
            labels,
        )

        with self._metrics_lock:

            state = self._counters.get(
                identity
            )

            if state is None:
                return default

            return state.value

    # =====================================================
    # GAUGES
    # =====================================================

    def set_gauge(
        self,
        name: str,
        value: float,
        *,
        labels: Mapping[str, Any] | None = None,
    ) -> float:
        """
        Set a gauge to an absolute value.
        """

        normalized_value = (
            self._normalize_number(
                value
            )
        )

        identity = self._build_identity(
            name,
            labels,
        )

        with self._metrics_lock:

            self._assert_metric_type(
                identity,
                MetricType.GAUGE,
            )

            state = self._gauges.setdefault(
                identity,
                _GaugeState(),
            )

            state.value = normalized_value
            state.updated_at = datetime.now(UTC)

            self._record_update(
                identity.name,
                MetricType.GAUGE,
            )

            return state.value

    def adjust_gauge(
        self,
        name: str,
        amount: float,
        *,
        labels: Mapping[str, Any] | None = None,
    ) -> float:
        """
        Add a positive or negative amount to a gauge.
        """

        normalized_amount = (
            self._normalize_number(
                amount
            )
        )

        identity = self._build_identity(
            name,
            labels,
        )

        with self._metrics_lock:

            self._assert_metric_type(
                identity,
                MetricType.GAUGE,
            )

            state = self._gauges.setdefault(
                identity,
                _GaugeState(),
            )

            state.value += normalized_amount
            state.updated_at = datetime.now(UTC)

            self._record_update(
                identity.name,
                MetricType.GAUGE,
            )

            return state.value

    def gauge_value(
        self,
        name: str,
        *,
        labels: Mapping[str, Any] | None = None,
        default: float | None = None,
    ) -> float | None:
        """
        Return a gauge value.
        """

        identity = self._build_identity(
            name,
            labels,
        )

        with self._metrics_lock:

            state = self._gauges.get(
                identity
            )

            if state is None:
                return default

            return state.value

    # =====================================================
    # HISTOGRAMS
    # =====================================================

    def observe(
        self,
        name: str,
        value: float,
        *,
        labels: Mapping[str, Any] | None = None,
        timer_observation: bool = False,
    ) -> HistogramMetric:
        """
        Record one histogram observation.
        """

        normalized_value = (
            self._normalize_number(
                value
            )
        )

        identity = self._build_identity(
            name,
            labels,
        )

        with self._metrics_lock:

            self._assert_metric_type(
                identity,
                MetricType.HISTOGRAM,
            )

            state = self._histograms.get(
                identity
            )

            if state is None:

                state = _HistogramState(
                    observations=deque(
                        maxlen=(
                            self._histogram_history_limit
                        )
                    )
                )

                self._histograms[
                    identity
                ] = state

            state.count += 1
            state.total += normalized_value
            state.latest = normalized_value

            state.minimum = (
                normalized_value
                if state.minimum is None
                else min(
                    state.minimum,
                    normalized_value,
                )
            )

            state.maximum = (
                normalized_value
                if state.maximum is None
                else max(
                    state.maximum,
                    normalized_value,
                )
            )

            state.observations.append(
                normalized_value
            )

            state.updated_at = datetime.now(UTC)

            self._record_update(
                identity.name,
                MetricType.HISTOGRAM,
            )

            if timer_observation:
                self._timer_observations += 1

            return self._histogram_snapshot(
                identity,
                state,
            )

    def histogram(
        self,
        name: str,
        *,
        labels: Mapping[str, Any] | None = None,
    ) -> HistogramMetric | None:
        """
        Return one histogram snapshot.
        """

        identity = self._build_identity(
            name,
            labels,
        )

        with self._metrics_lock:

            state = self._histograms.get(
                identity
            )

            if state is None:
                return None

            return self._histogram_snapshot(
                identity,
                state,
            )

    # =====================================================
    # TIMERS
    # =====================================================

    def timer(
        self,
        name: str,
        *,
        labels: Mapping[str, Any] | None = None,
    ) -> MetricTimer:
        """
        Create a duration timer context manager.
        """

        self._validate_metric_name(
            name
        )

        return MetricTimer(
            self,
            name,
            labels=labels,
        )

    # =====================================================
    # EVENT BUS METRICS
    # =====================================================

    def _observe_event(
        self,
        event: AtlasEvent,
    ) -> None:
        """
        Convert one Event Bus event into metrics.
        """

        self.increment(
            "atlas.events.total",
        )

        self.increment(
            "atlas.events.by_type.total",
            labels={
                "event_type": event.event_type,
            },
        )

        self.increment(
            "atlas.events.by_severity.total",
            labels={
                "severity": event.severity.value,
            },
        )

        self.increment(
            "atlas.events.by_source.total",
            labels={
                "source": event.source,
            },
        )

        with self._metrics_lock:
            self._event_observations += 1

    # =====================================================
    # RESET
    # =====================================================

    def remove_metric(
        self,
        name: str,
        *,
        labels: Mapping[str, Any] | None = None,
    ) -> bool:
        """
        Remove one metric series.
        """

        identity = self._build_identity(
            name,
            labels,
        )

        with self._metrics_lock:

            removed = False

            if identity in self._counters:
                del self._counters[identity]
                removed = True

            if identity in self._gauges:
                del self._gauges[identity]
                removed = True

            if identity in self._histograms:
                del self._histograms[identity]
                removed = True

            self._metric_types.pop(
                identity,
                None,
            )

            return removed

    def clear_metrics(
        self,
        *,
        reset_statistics: bool = False,
    ) -> None:
        """
        Clear all metric series.

        Runtime statistics may optionally be reset.
        """

        with self._metrics_lock:

            self._counters.clear()
            self._gauges.clear()
            self._histograms.clear()
            self._metric_types.clear()

            if reset_statistics:

                self._total_updates = 0
                self._counter_updates = 0
                self._gauge_updates = 0
                self._histogram_updates = 0
                self._timer_observations = 0
                self._event_observations = 0
                self._last_metric_name = None

    # =====================================================
    # SNAPSHOTS
    # =====================================================

    def counter_metrics(
        self,
    ) -> tuple[CounterMetric, ...]:
        """
        Return all counter snapshots.
        """

        with self._metrics_lock:

            return tuple(
                CounterMetric(
                    identity=identity,
                    value=state.value,
                    updated_at=state.updated_at,
                )
                for identity, state
                in sorted(
                    self._counters.items(),
                    key=lambda item: (
                        item[0].name,
                        item[0].labels,
                    ),
                )
            )

    def gauge_metrics(
        self,
    ) -> tuple[GaugeMetric, ...]:
        """
        Return all gauge snapshots.
        """

        with self._metrics_lock:

            return tuple(
                GaugeMetric(
                    identity=identity,
                    value=state.value,
                    updated_at=state.updated_at,
                )
                for identity, state
                in sorted(
                    self._gauges.items(),
                    key=lambda item: (
                        item[0].name,
                        item[0].labels,
                    ),
                )
            )

    def histogram_metrics(
        self,
    ) -> tuple[HistogramMetric, ...]:
        """
        Return all histogram snapshots.
        """

        with self._metrics_lock:

            return tuple(
                self._histogram_snapshot(
                    identity,
                    state,
                )
                for identity, state
                in sorted(
                    self._histograms.items(),
                    key=lambda item: (
                        item[0].name,
                        item[0].labels,
                    ),
                )
            )

    def statistics(
        self,
    ) -> MetricsStatistics:
        """
        Return immutable Metrics Service statistics.
        """

        with self._metrics_lock:

            return MetricsStatistics(
                counter_count=len(
                    self._counters
                ),
                gauge_count=len(
                    self._gauges
                ),
                histogram_count=len(
                    self._histograms
                ),
                total_metric_series=(
                    len(self._counters)
                    + len(self._gauges)
                    + len(self._histograms)
                ),
                total_updates=self._total_updates,
                counter_updates=(
                    self._counter_updates
                ),
                gauge_updates=(
                    self._gauge_updates
                ),
                histogram_updates=(
                    self._histogram_updates
                ),
                timer_observations=(
                    self._timer_observations
                ),
                event_observations=(
                    self._event_observations
                ),
                last_metric_name=(
                    self._last_metric_name
                ),
            )

    def metrics_snapshot(
        self,
    ) -> MetricsSnapshot:
        """
        Return complete Metrics Service diagnostics.
        """

        return MetricsSnapshot(
            running=self.is_running,
            event_subscription_active=(
                self.event_subscription_active
            ),
            counters=self.counter_metrics(),
            gauges=self.gauge_metrics(),
            histograms=self.histogram_metrics(),
            statistics=self.statistics(),
        )

    # =====================================================
    # BASE SERVICE DIAGNOSTICS
    # =====================================================

    def _health_details(
        self,
    ) -> Mapping[str, Any]:
        """
        Return Metrics Service health details.
        """

        statistics = self.statistics()

        return {
            "event_subscription_active": (
                self.event_subscription_active
            ),
            "counter_count": (
                statistics.counter_count
            ),
            "gauge_count": (
                statistics.gauge_count
            ),
            "histogram_count": (
                statistics.histogram_count
            ),
            "total_metric_series": (
                statistics.total_metric_series
            ),
            "total_updates": (
                statistics.total_updates
            ),
            "timer_observations": (
                statistics.timer_observations
            ),
            "event_observations": (
                statistics.event_observations
            ),
            "last_metric_name": (
                statistics.last_metric_name
            ),
        }

    def _snapshot_metadata(
        self,
    ) -> Mapping[str, Any]:
        """
        Return Metrics Service configuration metadata.
        """

        return {
            "histogram_history_limit": (
                self._histogram_history_limit
            ),
            "collect_event_metrics": (
                self._collect_event_metrics
            ),
            "event_bus_configured": (
                self._event_bus is not None
            ),
            "metric_types": [
                metric_type.value
                for metric_type in MetricType
            ],
        }

    # =====================================================
    # INTERNAL HELPERS
    # =====================================================

    def _record_update(
        self,
        metric_name: str,
        metric_type: MetricType,
    ) -> None:
        """
        Record internal update statistics.
        """

        self._total_updates += 1
        self._last_metric_name = metric_name

        if metric_type == MetricType.COUNTER:
            self._counter_updates += 1

        elif metric_type == MetricType.GAUGE:
            self._gauge_updates += 1

        elif metric_type == MetricType.HISTOGRAM:
            self._histogram_updates += 1

    def _assert_metric_type(
        self,
        identity: MetricIdentity,
        metric_type: MetricType,
    ) -> None:
        """
        Ensure a metric identity is not reused with another type.
        """

        existing_type = self._metric_types.get(
            identity
        )

        if (
            existing_type is not None
            and existing_type != metric_type
        ):
            raise MetricTypeConflictError(
                f"Metric '{identity.name}' with labels "
                f"{identity.label_dict()} is already registered "
                f"as {existing_type.value}."
            )

        self._metric_types[
            identity
        ] = metric_type

    def _build_identity(
        self,
        name: str,
        labels: Mapping[str, Any] | None,
    ) -> MetricIdentity:
        """
        Construct a normalized metric identity.
        """

        normalized_name = (
            self._validate_metric_name(
                name
            )
        )

        normalized_labels = (
            self._normalize_labels(
                labels
            )
        )

        return MetricIdentity(
            name=normalized_name,
            labels=normalized_labels,
        )

    @classmethod
    def _validate_metric_name(
        cls,
        name: str,
    ) -> str:
        """
        Validate and normalize a metric name.
        """

        if not isinstance(name, str):
            raise TypeError(
                "Metric name must be a string."
            )

        normalized = name.strip().lower()

        if not normalized:
            raise InvalidMetricNameError(
                "Metric name cannot be empty."
            )

        if not cls._METRIC_NAME_PATTERN.fullmatch(
            normalized
        ):
            raise InvalidMetricNameError(
                f"Invalid metric name: '{name}'."
            )

        return normalized

    @staticmethod
    def _normalize_labels(
        labels: Mapping[str, Any] | None,
    ) -> tuple[tuple[str, str], ...]:
        """
        Normalize labels into a deterministic tuple.
        """

        if labels is None:
            return ()

        if not isinstance(
            labels,
            Mapping,
        ):
            raise TypeError(
                "Metric labels must be a mapping."
            )

        normalized: list[
            tuple[str, str]
        ] = []

        for key, value in labels.items():

            normalized_key = str(
                key
            ).strip().lower()

            if not normalized_key:
                raise ValueError(
                    "Metric label key cannot be empty."
                )

            normalized_value = str(
                value
            ).strip()

            normalized.append(
                (
                    normalized_key,
                    normalized_value,
                )
            )

        normalized.sort(
            key=lambda item: item[0]
        )

        return tuple(
            normalized
        )

    @staticmethod
    def _normalize_number(
        value: float,
    ) -> float:
        """
        Normalize and validate a numeric metric value.
        """

        if isinstance(value, bool):
            raise TypeError(
                "Boolean values are not valid metric values."
            )

        try:

            normalized = float(
                value
            )

        except (
            TypeError,
            ValueError,
        ) as exc:

            raise TypeError(
                "Metric value must be numeric."
            ) from exc

        if not math.isfinite(
            normalized
        ):
            raise ValueError(
                "Metric value must be finite."
            )

        return normalized

    @staticmethod
    def _histogram_snapshot(
        identity: MetricIdentity,
        state: _HistogramState,
    ) -> HistogramMetric:
        """
        Convert internal histogram state into an immutable snapshot.
        """

        average = (
            state.total / state.count
            if state.count > 0
            else None
        )

        return HistogramMetric(
            identity=identity,
            count=state.count,
            total=state.total,
            minimum=state.minimum,
            maximum=state.maximum,
            average=average,
            latest=state.latest,
            observations=tuple(
                state.observations
            ),
            updated_at=state.updated_at,
        )