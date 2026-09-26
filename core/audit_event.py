"""
============================================================
ATLAS AUDIT EVENT v1.0
============================================================

Immutable Institutional Audit Event

Purpose
-------
Represent one immutable and cryptographically verifiable
Atlas lifecycle event.

Responsibilities
----------------
- Canonical event identity
- UTC timestamp normalization
- Immutable dataclass structure
- Safe payload serialization
- Deterministic SHA-256 hashing
- Previous-event hash linking
- Dictionary and JSON conversion
- Stored-event verification

Hash Model
----------
event_hash = SHA256(
    canonical_json(
        event_without_event_hash
    )
)

The event_hash field itself is excluded from the hash input.

============================================================
"""

from __future__ import annotations

import hashlib
import json
import uuid

from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from enum import Enum
from types import MappingProxyType
from typing import Any, Mapping

from atlas_security import sanitize_sensitive_data


GENESIS_HASH = "GENESIS"


@dataclass(
    frozen=True,
    slots=True,
)
class AuditEvent:
    """
    Immutable Atlas audit event.
    """

    event_id: str

    event_type: str

    source: str

    aggregate_type: str

    aggregate_id: str

    payload: Mapping[str, Any]

    timestamp: str

    previous_hash: str

    event_hash: str

    version: str = "1.0"

    correlation_id: str | None = None

    causation_id: str | None = None

    metadata: Mapping[str, Any] = field(
        default_factory=dict
    )

    # =========================================================
    # FACTORY
    # =========================================================

    @classmethod
    def create(
        cls,
        *,
        event_type: str,
        source: str,
        aggregate_type: str,
        aggregate_id: str,
        payload: Mapping[str, Any],
        previous_hash: str = GENESIS_HASH,
        event_id: str | None = None,
        timestamp: str | datetime | None = None,
        correlation_id: str | None = None,
        causation_id: str | None = None,
        metadata: Mapping[str, Any] | None = None,
    ) -> "AuditEvent":
        """
        Create a new immutable event and calculate its hash.
        """

        normalized_event_id = (
            str(
                event_id
            ).strip()
            if event_id
            else str(
                uuid.uuid4()
            )
        )

        normalized_timestamp = (
            cls._normalize_timestamp(
                timestamp
            )
        )

        normalized_payload = cls._safe_payload(
            payload
        )

        normalized_metadata = cls._safe_payload(
            metadata or {}
        )

        unsigned_data = {
            "event_id": normalized_event_id,
            "event_type": cls._required_text(
                event_type,
                "event_type",
            ),
            "source": cls._required_text(
                source,
                "source",
            ),
            "aggregate_type": cls._required_text(
                aggregate_type,
                "aggregate_type",
            ),
            "aggregate_id": cls._required_text(
                aggregate_id,
                "aggregate_id",
            ),
            "payload": normalized_payload,
            "timestamp": normalized_timestamp,
            "previous_hash": cls._required_text(
                previous_hash,
                "previous_hash",
            ),
            "version": "1.0",
            "correlation_id": cls._optional_text(
                correlation_id
            ),
            "causation_id": cls._optional_text(
                causation_id
            ),
            "metadata": normalized_metadata,
        }

        event_hash = cls.calculate_hash(
            unsigned_data
        )

        return cls(
            event_id=unsigned_data[
                "event_id"
            ],
            event_type=unsigned_data[
                "event_type"
            ],
            source=unsigned_data[
                "source"
            ],
            aggregate_type=unsigned_data[
                "aggregate_type"
            ],
            aggregate_id=unsigned_data[
                "aggregate_id"
            ],
            payload=MappingProxyType(
                normalized_payload
            ),
            timestamp=unsigned_data[
                "timestamp"
            ],
            previous_hash=unsigned_data[
                "previous_hash"
            ],
            event_hash=event_hash,
            version=unsigned_data[
                "version"
            ],
            correlation_id=unsigned_data[
                "correlation_id"
            ],
            causation_id=unsigned_data[
                "causation_id"
            ],
            metadata=MappingProxyType(
                normalized_metadata
            ),
        )

    @classmethod
    def from_dict(
        cls,
        data: Mapping[str, Any],
    ) -> "AuditEvent":
        """
        Restore an event from persisted data.
        """

        payload = cls._safe_payload(
            data.get(
                "payload",
                {},
            )
        )

        metadata = cls._safe_payload(
            data.get(
                "metadata",
                {},
            )
        )

        return cls(
            event_id=cls._required_text(
                data.get(
                    "event_id"
                ),
                "event_id",
            ),
            event_type=cls._required_text(
                data.get(
                    "event_type"
                ),
                "event_type",
            ),
            source=cls._required_text(
                data.get(
                    "source"
                ),
                "source",
            ),
            aggregate_type=cls._required_text(
                data.get(
                    "aggregate_type"
                ),
                "aggregate_type",
            ),
            aggregate_id=cls._required_text(
                data.get(
                    "aggregate_id"
                ),
                "aggregate_id",
            ),
            payload=MappingProxyType(
                payload
            ),
            timestamp=cls._normalize_timestamp(
                data.get(
                    "timestamp"
                )
            ),
            previous_hash=cls._required_text(
                data.get(
                    "previous_hash"
                ),
                "previous_hash",
            ),
            event_hash=cls._required_text(
                data.get(
                    "event_hash"
                ),
                "event_hash",
            ),
            version=str(
                data.get(
                    "version",
                    "1.0",
                )
            ),
            correlation_id=cls._optional_text(
                data.get(
                    "correlation_id"
                )
            ),
            causation_id=cls._optional_text(
                data.get(
                    "causation_id"
                )
            ),
            metadata=MappingProxyType(
                metadata
            ),
        )

    # =========================================================
    # HASHING
    # =========================================================

    @classmethod
    def calculate_hash(
        cls,
        event_data: Mapping[str, Any],
    ) -> str:
        """
        Calculate deterministic SHA-256 event hash.
        """

        unsigned_data = {
            str(
                key
            ): cls._safe_payload(
                value
            )
            for key, value
            in event_data.items()
            if key != "event_hash"
        }

        canonical_json = json.dumps(
            unsigned_data,
            ensure_ascii=False,
            sort_keys=True,
            separators=(
                ",",
                ":",
            ),
        )

        return hashlib.sha256(
            canonical_json.encode(
                "utf-8"
            )
        ).hexdigest()

    def verify_hash(
        self,
    ) -> bool:
        """
        Verify the stored event hash.
        """

        return self.event_hash == (
            self.calculate_hash(
                self.unsigned_dict()
            )
        )

    # =========================================================
    # CONVERSION
    # =========================================================

    def unsigned_dict(
        self,
    ) -> dict[str, Any]:
        """
        Return event fields excluding event_hash.
        """

        return {
            "event_id": self.event_id,
            "event_type": self.event_type,
            "source": self.source,
            "aggregate_type": (
                self.aggregate_type
            ),
            "aggregate_id": self.aggregate_id,
            "payload": self._safe_payload(
                self.payload
            ),
            "timestamp": self.timestamp,
            "previous_hash": (
                self.previous_hash
            ),
            "version": self.version,
            "correlation_id": (
                self.correlation_id
            ),
            "causation_id": self.causation_id,
            "metadata": self._safe_payload(
                self.metadata
            ),
        }

    def to_dict(
        self,
    ) -> dict[str, Any]:
        """
        Return JSON-safe complete event representation.
        """

        data = self.unsigned_dict()

        data[
            "event_hash"
        ] = self.event_hash

        return data

    def to_json(
        self,
    ) -> str:
        """
        Return canonical persisted JSON representation.
        """

        return json.dumps(
            self.to_dict(),
            ensure_ascii=False,
            sort_keys=True,
            separators=(
                ",",
                ":",
            ),
        )

    # =========================================================
    # VALIDATION
    # =========================================================

    def validate(
        self,
    ) -> dict[str, Any]:
        """
        Validate event structure and cryptographic hash.
        """

        errors: list[str] = []

        for field_name in (
            "event_id",
            "event_type",
            "source",
            "aggregate_type",
            "aggregate_id",
            "timestamp",
            "previous_hash",
            "event_hash",
        ):
            value = getattr(
                self,
                field_name,
            )

            if not str(
                value
            ).strip():
                errors.append(
                    f"{field_name} is required"
                )

        if not self.verify_hash():
            errors.append(
                "event_hash verification failed"
            )

        return {
            "valid": not errors,
            "errors": errors,
            "event_id": self.event_id,
            "event_hash": self.event_hash,
        }

    # =========================================================
    # SERIALIZATION
    # =========================================================

    @classmethod
    def _safe_payload(
        cls,
        value: Any,
    ) -> Any:
        return sanitize_sensitive_data(
            value,
            preserve_identifiers=True,
        )

    # =========================================================
    # NORMALIZATION
    # =========================================================

    @staticmethod
    def _required_text(
        value: Any,
        field_name: str,
    ) -> str:
        normalized = str(
            value or ""
        ).strip()

        if not normalized:
            raise ValueError(
                f"{field_name} is required"
            )

        return normalized

    @staticmethod
    def _optional_text(
        value: Any,
    ) -> str | None:
        if value is None:
            return None

        normalized = str(
            value
        ).strip()

        return normalized or None

    @staticmethod
    def _normalize_timestamp(
        value: str | datetime | None,
    ) -> str:
        if value is None:
            return datetime.now(
                UTC
            ).isoformat()

        if isinstance(
            value,
            datetime,
        ):
            timestamp = value

        else:
            normalized = str(
                value
            ).strip()

            if not normalized:
                raise ValueError(
                    "timestamp is required"
                )

            if normalized.endswith(
                "Z"
            ):
                normalized = (
                    normalized[:-1]
                    + "+00:00"
                )

            timestamp = datetime.fromisoformat(
                normalized
            )

        if timestamp.tzinfo is None:
            timestamp = timestamp.replace(
                tzinfo=UTC
            )

        return timestamp.astimezone(
            UTC
        ).isoformat()
