"""
============================================================
ATLAS OS SECRETS MANAGER v1.0
============================================================

Secure runtime secret management infrastructure for AtlasOS.

Responsibilities
----------------
- Register secret definitions
- Store secrets in process memory
- Load secrets from environment variables
- Mask sensitive values
- Track secret versions
- Rotate secret values
- Detect expired secrets
- Record secret access history
- Produce safe diagnostic snapshots
- Publish secret lifecycle events
- Operate as an AtlasOS managed service

Security Model
--------------
- Plain secret values are never exposed in snapshots
- Plain values are never written to logs
- Secret history stores masked metadata only
- Public models contain no secret values
- Runtime storage exists only in process memory
- Environment variables may be used as external sources
- Persistent encrypted providers will be added separately

Important
---------
This service does not claim that Python process memory is encrypted.
It prevents accidental disclosure through AtlasOS APIs, logs,
snapshots and history records.

============================================================
"""

from __future__ import annotations

import hashlib
import hmac
import logging
import os
import secrets as secure_random
import threading
import uuid

from collections import deque
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from types import MappingProxyType
from typing import Any, Mapping

from atlas_os.contracts import ServiceIdentity
from atlas_os.events import (
    EventBusService,
    EventSeverity,
)
from atlas_os.services import BaseAtlasService


logger = logging.getLogger(
    "AtlasAI.AtlasOS.Secrets"
)


# =========================================================
# ENUMERATIONS
# =========================================================

class SecretSource(StrEnum):
    """
    Supported secret sources.
    """

    RUNTIME = "RUNTIME"
    ENVIRONMENT = "ENVIRONMENT"
    GENERATED = "GENERATED"


class SecretStatus(StrEnum):
    """
    Secret lifecycle status.
    """

    ACTIVE = "ACTIVE"
    EXPIRED = "EXPIRED"
    REVOKED = "REVOKED"
    MISSING = "MISSING"


class SecretEventType(StrEnum):
    """
    Events published by SecretsManager.
    """

    SECRETS_MANAGER_STARTED = (
        "SECRETS_MANAGER_STARTED"
    )

    SECRETS_MANAGER_STOPPED = (
        "SECRETS_MANAGER_STOPPED"
    )

    SECRET_REGISTERED = "SECRET_REGISTERED"
    SECRET_STORED = "SECRET_STORED"
    SECRET_ACCESSED = "SECRET_ACCESSED"
    SECRET_ROTATED = "SECRET_ROTATED"
    SECRET_REVOKED = "SECRET_REVOKED"
    SECRET_REMOVED = "SECRET_REMOVED"
    SECRET_EXPIRED = "SECRET_EXPIRED"
    SECRET_LOAD_FAILED = "SECRET_LOAD_FAILED"


# =========================================================
# EXCEPTIONS
# =========================================================

class SecretsManagerError(RuntimeError):
    """
    Base Secrets Manager exception.
    """


class SecretNotFoundError(SecretsManagerError):
    """
    Raised when a secret definition does not exist.
    """


class SecretValueMissingError(SecretsManagerError):
    """
    Raised when a registered secret has no value.
    """


class DuplicateSecretError(SecretsManagerError):
    """
    Raised when a secret is registered twice.
    """


class SecretExpiredError(SecretsManagerError):
    """
    Raised when an expired secret is requested.
    """


class SecretRevokedError(SecretsManagerError):
    """
    Raised when a revoked secret is requested.
    """


class SecretValidationError(SecretsManagerError):
    """
    Raised when a secret value is invalid.
    """


class SecretAccessDeniedError(SecretsManagerError):
    """
    Raised when a caller is not permitted to access a secret.
    """


# =========================================================
# PUBLIC DATA MODELS
# =========================================================

@dataclass(frozen=True, slots=True)
class SecretDefinition:
    """
    Immutable secret schema.

    No plain secret value is stored in this model.
    """

    key: str
    description: str = ""
    environment_variable: str | None = None
    required: bool = False
    minimum_length: int = 1
    rotation_interval_days: int | None = None
    allowed_callers: tuple[str, ...] = ()

    def __post_init__(self) -> None:

        normalized_key = self.key.strip().upper()

        if not normalized_key:
            raise ValueError(
                "Secret key cannot be empty."
            )

        if self.minimum_length <= 0:
            raise ValueError(
                "minimum_length must be greater than zero."
            )

        if (
            self.rotation_interval_days is not None
            and self.rotation_interval_days <= 0
        ):
            raise ValueError(
                "rotation_interval_days must be greater than zero."
            )

        environment_variable = (
            self.environment_variable.strip().upper()
            if self.environment_variable
            else normalized_key
        )

        normalized_callers = tuple(
            sorted(
                {
                    caller.strip()
                    for caller in self.allowed_callers
                    if caller.strip()
                }
            )
        )

        object.__setattr__(
            self,
            "key",
            normalized_key,
        )

        object.__setattr__(
            self,
            "description",
            self.description.strip(),
        )

        object.__setattr__(
            self,
            "environment_variable",
            environment_variable,
        )

        object.__setattr__(
            self,
            "allowed_callers",
            normalized_callers,
        )


@dataclass(frozen=True, slots=True)
class SecretMetadata:
    """
    Safe secret metadata without the plain value.
    """

    key: str
    description: str
    source: SecretSource | None
    status: SecretStatus
    required: bool
    version: int
    configured: bool
    masked_value: str | None
    fingerprint: str | None
    environment_variable: str
    created_at: datetime
    updated_at: datetime | None
    expires_at: datetime | None
    last_accessed_at: datetime | None
    access_count: int
    rotation_count: int


@dataclass(frozen=True, slots=True)
class SecretAccessRecord:
    """
    Safe audit record for one secret access operation.
    """

    access_id: str
    key: str
    caller: str
    operation: str
    permitted: bool
    reason: str | None
    accessed_at: datetime


@dataclass(frozen=True, slots=True)
class SecretChangeRecord:
    """
    Safe secret lifecycle change record.
    """

    change_id: str
    key: str
    operation: str
    source: SecretSource | None
    version: int
    previous_fingerprint: str | None
    current_fingerprint: str | None
    changed_at: datetime


@dataclass(frozen=True, slots=True)
class SecretsManagerStatistics:
    """
    Immutable Secrets Manager statistics.
    """

    registered_secrets: int
    configured_secrets: int
    required_secrets: int
    missing_required_secrets: int
    active_secrets: int
    expired_secrets: int
    revoked_secrets: int
    total_accesses: int
    denied_accesses: int
    total_rotations: int
    environment_loads: int
    generated_secrets: int
    event_publication_failures: int
    history_size: int
    access_history_size: int
    last_error: str | None
    generated_at: datetime = field(
        default_factory=lambda: datetime.now(UTC)
    )


@dataclass(frozen=True, slots=True)
class SecretsManagerSnapshot:
    """
    Safe complete Secrets Manager snapshot.
    """

    running: bool
    valid: bool
    secrets: tuple[SecretMetadata, ...]
    missing_required_secrets: tuple[str, ...]
    statistics: SecretsManagerStatistics
    generated_at: datetime = field(
        default_factory=lambda: datetime.now(UTC)
    )


# =========================================================
# INTERNAL DATA MODEL
# =========================================================

@dataclass(slots=True)
class _StoredSecret:
    """
    Internal secret storage model.

    This object must never be returned from a public API.
    """

    value: str
    source: SecretSource
    version: int
    fingerprint: str
    created_at: datetime
    updated_at: datetime
    expires_at: datetime | None
    last_accessed_at: datetime | None = None
    access_count: int = 0
    rotation_count: int = 0
    revoked: bool = False


# =========================================================
# SECRETS MANAGER
# =========================================================

class SecretsManager(BaseAtlasService):
    """
    Central secure runtime secret manager for AtlasOS.
    """

    VERSION = "1.0.0"

    NAME = "AtlasOSSecretsManager"

    def __init__(
        self,
        *,
        history_limit: int = 1000,
        access_history_limit: int = 5000,
        secret_mask: str = "********",
        fingerprint_length: int = 12,
        event_bus: EventBusService | None = None,
        publish_events: bool = False,
    ) -> None:

        if history_limit <= 0:
            raise ValueError(
                "history_limit must be greater than zero."
            )

        if access_history_limit <= 0:
            raise ValueError(
                "access_history_limit must be greater than zero."
            )

        if not secret_mask:
            raise ValueError(
                "secret_mask cannot be empty."
            )

        if fingerprint_length < 8:
            raise ValueError(
                "fingerprint_length must be at least 8."
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

        if publish_events and event_bus is None:
            raise ValueError(
                "event_bus is required when publish_events=True."
            )

        super().__init__(
            ServiceIdentity(
                name=self.NAME,
                version=self.VERSION,
                service_type="SECURITY",
                description=(
                    "Secure runtime secret management "
                    "service for AtlasOS."
                ),
            )
        )

        self._history_limit = int(history_limit)
        self._access_history_limit = int(
            access_history_limit
        )

        self._secret_mask = str(secret_mask)
        self._fingerprint_length = int(
            fingerprint_length
        )

        self._event_bus = event_bus
        self._publish_events = bool(
            publish_events
        )

        self._definitions: dict[
            str,
            SecretDefinition,
        ] = {}

        self._secrets: dict[
            str,
            _StoredSecret,
        ] = {}

        self._change_history: deque[
            SecretChangeRecord
        ] = deque(
            maxlen=self._history_limit
        )

        self._access_history: deque[
            SecretAccessRecord
        ] = deque(
            maxlen=self._access_history_limit
        )

        self._environment_loads = 0
        self._generated_secrets = 0
        self._denied_accesses = 0
        self._event_publication_failures = 0

        self._last_error: str | None = None

        self._secret_lock = threading.RLock()

    # =====================================================
    # SERVICE LIFECYCLE
    # =====================================================

    def _on_start(self) -> None:
        """
        Load registered environment-backed secrets.
        """

        self.load_environment(
            ignore_missing=True
        )

        missing = self.missing_required_secrets()

        self._publish_secret_event(
            SecretEventType.SECRETS_MANAGER_STARTED,
            payload={
                "registered_secrets": len(
                    self._definitions
                ),
                "configured_secrets": len(
                    self._secrets
                ),
                "missing_required_secrets": list(
                    missing
                ),
            },
        )

        logger.info(
            "AtlasOS Secrets Manager started | "
            "registered=%s | configured=%s",
            len(self._definitions),
            len(self._secrets),
        )

    def _on_stop(self) -> None:
        """
        Stop the service without logging secret data.
        """

        self._publish_secret_event(
            SecretEventType.SECRETS_MANAGER_STOPPED,
            payload={
                "registered_secrets": len(
                    self._definitions
                ),
                "configured_secrets": len(
                    self._secrets
                ),
            },
        )

        logger.info(
            "AtlasOS Secrets Manager stopped."
        )

    # =====================================================
    # REGISTRATION
    # =====================================================

    def register_definition(
        self,
        definition: SecretDefinition,
        *,
        replace: bool = False,
    ) -> SecretDefinition:
        """
        Register one secret definition.
        """

        if not isinstance(
            definition,
            SecretDefinition,
        ):
            raise TypeError(
                "definition must be a SecretDefinition instance."
            )

        with self._secret_lock:

            if (
                definition.key in self._definitions
                and not replace
            ):
                raise DuplicateSecretError(
                    f"Secret already registered: "
                    f"{definition.key}"
                )

            self._definitions[
                definition.key
            ] = definition

        self._publish_secret_event(
            SecretEventType.SECRET_REGISTERED,
            payload={
                "key": definition.key,
                "required": definition.required,
                "environment_variable": (
                    definition.environment_variable
                ),
                "rotation_interval_days": (
                    definition.rotation_interval_days
                ),
                "restricted": bool(
                    definition.allowed_callers
                ),
            },
        )

        return definition

    def register(
        self,
        key: str,
        *,
        description: str = "",
        environment_variable: str | None = None,
        required: bool = False,
        minimum_length: int = 1,
        rotation_interval_days: int | None = None,
        allowed_callers: tuple[str, ...] = (),
        replace: bool = False,
    ) -> SecretDefinition:
        """
        Build and register one secret definition.
        """

        definition = SecretDefinition(
            key=key,
            description=description,
            environment_variable=environment_variable,
            required=required,
            minimum_length=minimum_length,
            rotation_interval_days=(
                rotation_interval_days
            ),
            allowed_callers=allowed_callers,
        )

        return self.register_definition(
            definition,
            replace=replace,
        )

    # =====================================================
    # SECRET STORAGE
    # =====================================================

    def set_secret(
        self,
        key: str,
        value: str,
        *,
        source: SecretSource = SecretSource.RUNTIME,
        caller: str = "SYSTEM",
    ) -> SecretMetadata:
        """
        Store or replace one secret value.
        """

        normalized_key = self._normalize_key(
            key
        )

        normalized_caller = self._normalize_caller(
            caller
        )

        with self._secret_lock:

            definition = self._definitions.get(
                normalized_key
            )

        if definition is None:
            raise SecretNotFoundError(
                f"Secret not registered: "
                f"{normalized_key}"
            )

        self._authorize(
            definition,
            normalized_caller,
            operation="WRITE",
        )

        normalized_value = self._validate_value(
            definition,
            value,
        )

        now = datetime.now(UTC)

        with self._secret_lock:

            current = self._secrets.get(
                normalized_key
            )

            previous_fingerprint = (
                current.fingerprint
                if current is not None
                else None
            )

            version = (
                current.version + 1
                if current is not None
                else 1
            )

            rotation_count = (
                current.rotation_count
                if current is not None
                else 0
            )

            created_at = (
                current.created_at
                if current is not None
                else now
            )

            fingerprint = self._fingerprint(
                normalized_value
            )

            expires_at = (
                now
                + timedelta(
                    days=definition
                    .rotation_interval_days
                )
                if definition.rotation_interval_days
                is not None
                else None
            )

            self._secrets[
                normalized_key
            ] = _StoredSecret(
                value=normalized_value,
                source=SecretSource(source),
                version=version,
                fingerprint=fingerprint,
                created_at=created_at,
                updated_at=now,
                expires_at=expires_at,
                last_accessed_at=(
                    current.last_accessed_at
                    if current is not None
                    else None
                ),
                access_count=(
                    current.access_count
                    if current is not None
                    else 0
                ),
                rotation_count=rotation_count,
                revoked=False,
            )

            operation = (
                "STORE"
                if current is None
                else "REPLACE"
            )

            self._record_change(
                key=normalized_key,
                operation=operation,
                source=SecretSource(source),
                version=version,
                previous_fingerprint=(
                    previous_fingerprint
                ),
                current_fingerprint=fingerprint,
            )

            self._last_error = None

        self._record_access(
            key=normalized_key,
            caller=normalized_caller,
            operation="WRITE",
            permitted=True,
        )

        self._publish_secret_event(
            SecretEventType.SECRET_STORED,
            payload={
                "key": normalized_key,
                "source": SecretSource(source).value,
                "version": version,
                "fingerprint": fingerprint,
            },
        )

        return self.metadata(
            normalized_key
        )

    def get_secret(
        self,
        key: str,
        *,
        caller: str = "SYSTEM",
        allow_expired: bool = False,
    ) -> str:
        """
        Return one plain secret value.

        This is the only public method that returns the plain value.
        """

        normalized_key = self._normalize_key(
            key
        )

        normalized_caller = self._normalize_caller(
            caller
        )

        with self._secret_lock:

            definition = self._definitions.get(
                normalized_key
            )

        if definition is None:

            self._record_access(
                key=normalized_key,
                caller=normalized_caller,
                operation="READ",
                permitted=False,
                reason="SECRET_NOT_REGISTERED",
            )

            raise SecretNotFoundError(
                f"Secret not registered: "
                f"{normalized_key}"
            )

        self._authorize(
            definition,
            normalized_caller,
            operation="READ",
        )

        with self._secret_lock:

            stored = self._secrets.get(
                normalized_key
            )

            if stored is None:

                self._record_access(
                    key=normalized_key,
                    caller=normalized_caller,
                    operation="READ",
                    permitted=False,
                    reason="SECRET_VALUE_MISSING",
                )

                raise SecretValueMissingError(
                    f"Secret value is missing: "
                    f"{normalized_key}"
                )

            if stored.revoked:

                self._record_access(
                    key=normalized_key,
                    caller=normalized_caller,
                    operation="READ",
                    permitted=False,
                    reason="SECRET_REVOKED",
                )

                raise SecretRevokedError(
                    f"Secret is revoked: "
                    f"{normalized_key}"
                )

            if (
                self._is_expired(stored)
                and not allow_expired
            ):

                self._record_access(
                    key=normalized_key,
                    caller=normalized_caller,
                    operation="READ",
                    permitted=False,
                    reason="SECRET_EXPIRED",
                )

                self._publish_secret_event(
                    SecretEventType.SECRET_EXPIRED,
                    severity=EventSeverity.WARNING,
                    payload={
                        "key": normalized_key,
                        "version": stored.version,
                    },
                )

                raise SecretExpiredError(
                    f"Secret is expired: "
                    f"{normalized_key}"
                )

            stored.last_accessed_at = (
                datetime.now(UTC)
            )

            stored.access_count += 1

            value = stored.value
            version = stored.version

        self._record_access(
            key=normalized_key,
            caller=normalized_caller,
            operation="READ",
            permitted=True,
        )

        self._publish_secret_event(
            SecretEventType.SECRET_ACCESSED,
            payload={
                "key": normalized_key,
                "caller": normalized_caller,
                "version": version,
            },
        )

        return value

    def rotate_secret(
        self,
        key: str,
        new_value: str,
        *,
        caller: str = "SYSTEM",
        source: SecretSource = SecretSource.RUNTIME,
    ) -> SecretMetadata:
        """
        Rotate an existing secret value.
        """

        normalized_key = self._normalize_key(
            key
        )

        normalized_caller = self._normalize_caller(
            caller
        )

        with self._secret_lock:

            definition = self._definitions.get(
                normalized_key
            )

            current = self._secrets.get(
                normalized_key
            )

        if definition is None:
            raise SecretNotFoundError(
                f"Secret not registered: "
                f"{normalized_key}"
            )

        if current is None:
            raise SecretValueMissingError(
                f"Secret value is missing: "
                f"{normalized_key}"
            )

        self._authorize(
            definition,
            normalized_caller,
            operation="ROTATE",
        )

        normalized_value = self._validate_value(
            definition,
            new_value,
        )

        if hmac.compare_digest(
            current.value,
            normalized_value,
        ):
            raise SecretValidationError(
                "Rotated secret value must differ "
                "from the current value."
            )

        previous_fingerprint = (
            current.fingerprint
        )

        metadata = self.set_secret(
            normalized_key,
            normalized_value,
            source=source,
            caller=normalized_caller,
        )

        with self._secret_lock:

            stored = self._secrets[
                normalized_key
            ]

            stored.rotation_count = (
                current.rotation_count + 1
            )

            self._record_change(
                key=normalized_key,
                operation="ROTATE",
                source=SecretSource(source),
                version=stored.version,
                previous_fingerprint=(
                    previous_fingerprint
                ),
                current_fingerprint=(
                    stored.fingerprint
                ),
            )

            rotation_count = (
                stored.rotation_count
            )

        self._publish_secret_event(
            SecretEventType.SECRET_ROTATED,
            payload={
                "key": normalized_key,
                "version": metadata.version,
                "rotation_count": rotation_count,
                "fingerprint": metadata.fingerprint,
            },
        )

        return self.metadata(
            normalized_key
        )

    def revoke_secret(
        self,
        key: str,
        *,
        caller: str = "SYSTEM",
    ) -> bool:
        """
        Revoke one configured secret.
        """

        normalized_key = self._normalize_key(
            key
        )

        normalized_caller = self._normalize_caller(
            caller
        )

        with self._secret_lock:

            definition = self._definitions.get(
                normalized_key
            )

        if definition is None:
            raise SecretNotFoundError(
                f"Secret not registered: "
                f"{normalized_key}"
            )

        self._authorize(
            definition,
            normalized_caller,
            operation="REVOKE",
        )

        with self._secret_lock:

            stored = self._secrets.get(
                normalized_key
            )

            if stored is None:
                return False

            if stored.revoked:
                return False

            stored.revoked = True
            stored.updated_at = datetime.now(UTC)

            self._record_change(
                key=normalized_key,
                operation="REVOKE",
                source=stored.source,
                version=stored.version,
                previous_fingerprint=(
                    stored.fingerprint
                ),
                current_fingerprint=(
                    stored.fingerprint
                ),
            )

        self._record_access(
            key=normalized_key,
            caller=normalized_caller,
            operation="REVOKE",
            permitted=True,
        )

        self._publish_secret_event(
            SecretEventType.SECRET_REVOKED,
            severity=EventSeverity.WARNING,
            payload={
                "key": normalized_key,
                "version": stored.version,
            },
        )

        return True

    def remove_secret(
        self,
        key: str,
        *,
        caller: str = "SYSTEM",
    ) -> bool:
        """
        Remove one secret value while preserving its definition.
        """

        normalized_key = self._normalize_key(
            key
        )

        normalized_caller = self._normalize_caller(
            caller
        )

        with self._secret_lock:

            definition = self._definitions.get(
                normalized_key
            )

        if definition is None:
            raise SecretNotFoundError(
                f"Secret not registered: "
                f"{normalized_key}"
            )

        self._authorize(
            definition,
            normalized_caller,
            operation="REMOVE",
        )

        with self._secret_lock:

            stored = self._secrets.pop(
                normalized_key,
                None,
            )

            if stored is None:
                return False

            self._record_change(
                key=normalized_key,
                operation="REMOVE",
                source=stored.source,
                version=stored.version,
                previous_fingerprint=(
                    stored.fingerprint
                ),
                current_fingerprint=None,
            )

        self._record_access(
            key=normalized_key,
            caller=normalized_caller,
            operation="REMOVE",
            permitted=True,
        )

        self._publish_secret_event(
            SecretEventType.SECRET_REMOVED,
            severity=EventSeverity.WARNING,
            payload={
                "key": normalized_key,
                "version": stored.version,
            },
        )

        return True

    # =====================================================
    # ENVIRONMENT LOADING
    # =====================================================

    def load_environment(
        self,
        *,
        prefix: str = "",
        ignore_missing: bool = True,
        caller: str = "SYSTEM",
    ) -> int:
        """
        Load registered secrets from environment variables.
        """

        normalized_prefix = prefix.strip().upper()
        loaded = 0

        with self._secret_lock:
            definitions = tuple(
                self._definitions.values()
            )

        for definition in definitions:

            variable_name = (
                normalized_prefix
                + str(
                    definition.environment_variable
                )
            )

            value = os.environ.get(
                variable_name
            )

            if value is None:

                if (
                    definition.required
                    and not ignore_missing
                ):
                    message = (
                        "Required environment secret "
                        f"is missing: {variable_name}"
                    )

                    with self._secret_lock:
                        self._last_error = message

                    self._publish_secret_event(
                        SecretEventType.SECRET_LOAD_FAILED,
                        severity=EventSeverity.ERROR,
                        payload={
                            "key": definition.key,
                            "environment_variable": (
                                variable_name
                            ),
                        },
                    )

                    raise SecretValueMissingError(
                        message
                    )

                continue

            self.set_secret(
                definition.key,
                value,
                source=SecretSource.ENVIRONMENT,
                caller=caller,
            )

            loaded += 1

        with self._secret_lock:
            self._environment_loads += 1

        return loaded

    # =====================================================
    # SECRET GENERATION
    # =====================================================

    def generate_secret(
        self,
        key: str,
        *,
        length: int = 48,
        caller: str = "SYSTEM",
    ) -> SecretMetadata:
        """
        Generate and store a cryptographically secure URL-safe secret.
        """

        if length < 16:
            raise ValueError(
                "Generated secret length must be at least 16."
            )

        random_value = secure_random.token_urlsafe(
            length
        )

        metadata = self.set_secret(
            key,
            random_value,
            source=SecretSource.GENERATED,
            caller=caller,
        )

        with self._secret_lock:
            self._generated_secrets += 1

        return metadata

    # =====================================================
    # VALIDATION
    # =====================================================

    def missing_required_secrets(
        self,
    ) -> tuple[str, ...]:
        """
        Return required secrets without active values.
        """

        with self._secret_lock:

            missing = []

            for definition in self._definitions.values():

                if not definition.required:
                    continue

                stored = self._secrets.get(
                    definition.key
                )

                if (
                    stored is None
                    or stored.revoked
                    or self._is_expired(stored)
                ):
                    missing.append(
                        definition.key
                    )

            return tuple(
                sorted(missing)
            )

    def validate(
        self,
        *,
        raise_on_error: bool = True,
    ) -> bool:
        """
        Validate all required secrets.
        """

        missing = self.missing_required_secrets()

        if not missing:
            return True

        message = (
            "Required secrets are missing, "
            "expired or revoked: "
            + ", ".join(missing)
        )

        with self._secret_lock:
            self._last_error = message

        if raise_on_error:
            raise SecretValidationError(
                message
            )

        return False

    # =====================================================
    # METADATA AND SNAPSHOTS
    # =====================================================

    def metadata(
        self,
        key: str,
    ) -> SecretMetadata:
        """
        Return safe metadata for one secret.
        """

        normalized_key = self._normalize_key(
            key
        )

        with self._secret_lock:

            definition = self._definitions.get(
                normalized_key
            )

            if definition is None:
                raise SecretNotFoundError(
                    f"Secret not registered: "
                    f"{normalized_key}"
                )

            stored = self._secrets.get(
                normalized_key
            )

            if stored is None:

                return SecretMetadata(
                    key=definition.key,
                    description=definition.description,
                    source=None,
                    status=SecretStatus.MISSING,
                    required=definition.required,
                    version=0,
                    configured=False,
                    masked_value=None,
                    fingerprint=None,
                    environment_variable=str(
                        definition.environment_variable
                    ),
                    created_at=datetime.now(UTC),
                    updated_at=None,
                    expires_at=None,
                    last_accessed_at=None,
                    access_count=0,
                    rotation_count=0,
                )

            status = self._status_of(
                stored
            )

            return SecretMetadata(
                key=definition.key,
                description=definition.description,
                source=stored.source,
                status=status,
                required=definition.required,
                version=stored.version,
                configured=True,
                masked_value=self._secret_mask,
                fingerprint=stored.fingerprint,
                environment_variable=str(
                    definition.environment_variable
                ),
                created_at=stored.created_at,
                updated_at=stored.updated_at,
                expires_at=stored.expires_at,
                last_accessed_at=(
                    stored.last_accessed_at
                ),
                access_count=stored.access_count,
                rotation_count=(
                    stored.rotation_count
                ),
            )

    def all_metadata(
        self,
    ) -> tuple[SecretMetadata, ...]:
        """
        Return safe metadata for all registered secrets.
        """

        with self._secret_lock:
            keys = tuple(
                sorted(self._definitions)
            )

        return tuple(
            self.metadata(key)
            for key in keys
        )

    def masked_mapping(
        self,
    ) -> Mapping[str, str | None]:
        """
        Return an immutable mapping containing only masked values.
        """

        values = {
            metadata.key: metadata.masked_value
            for metadata in self.all_metadata()
        }

        return MappingProxyType(
            values
        )

    def statistics(
        self,
    ) -> SecretsManagerStatistics:
        """
        Return immutable service statistics.
        """

        metadata = self.all_metadata()
        missing = self.missing_required_secrets()

        with self._secret_lock:

            return SecretsManagerStatistics(
                registered_secrets=len(
                    self._definitions
                ),
                configured_secrets=sum(
                    item.configured
                    for item in metadata
                ),
                required_secrets=sum(
                    item.required
                    for item in metadata
                ),
                missing_required_secrets=len(
                    missing
                ),
                active_secrets=sum(
                    item.status == SecretStatus.ACTIVE
                    for item in metadata
                ),
                expired_secrets=sum(
                    item.status == SecretStatus.EXPIRED
                    for item in metadata
                ),
                revoked_secrets=sum(
                    item.status == SecretStatus.REVOKED
                    for item in metadata
                ),
                total_accesses=sum(
                    item.access_count
                    for item in metadata
                ),
                denied_accesses=(
                    self._denied_accesses
                ),
                total_rotations=sum(
                    item.rotation_count
                    for item in metadata
                ),
                environment_loads=(
                    self._environment_loads
                ),
                generated_secrets=(
                    self._generated_secrets
                ),
                event_publication_failures=(
                    self._event_publication_failures
                ),
                history_size=len(
                    self._change_history
                ),
                access_history_size=len(
                    self._access_history
                ),
                last_error=self._last_error,
            )

    def secrets_snapshot(
        self,
    ) -> SecretsManagerSnapshot:
        """
        Return complete safe Secrets Manager diagnostics.
        """

        missing = self.missing_required_secrets()

        return SecretsManagerSnapshot(
            running=self.is_running,
            valid=not missing,
            secrets=self.all_metadata(),
            missing_required_secrets=missing,
            statistics=self.statistics(),
        )

    # =====================================================
    # HISTORY
    # =====================================================

    def change_history(
        self,
        *,
        key: str | None = None,
        limit: int | None = None,
        newest_first: bool = False,
    ) -> tuple[SecretChangeRecord, ...]:
        """
        Return safe secret change history.
        """

        if limit is not None and limit < 0:
            raise ValueError(
                "limit cannot be negative."
            )

        with self._secret_lock:
            records = list(
                self._change_history
            )

        if key is not None:

            normalized_key = self._normalize_key(
                key
            )

            records = [
                record
                for record in records
                if record.key == normalized_key
            ]

        if newest_first:
            records.reverse()

        if limit is not None:
            records = records[:limit]

        return tuple(records)

    def access_history(
        self,
        *,
        key: str | None = None,
        caller: str | None = None,
        permitted: bool | None = None,
        limit: int | None = None,
        newest_first: bool = False,
    ) -> tuple[SecretAccessRecord, ...]:
        """
        Return safe secret access history.
        """

        if limit is not None and limit < 0:
            raise ValueError(
                "limit cannot be negative."
            )

        with self._secret_lock:
            records = list(
                self._access_history
            )

        if key is not None:

            normalized_key = self._normalize_key(
                key
            )

            records = [
                record
                for record in records
                if record.key == normalized_key
            ]

        if caller is not None:

            normalized_caller = (
                self._normalize_caller(
                    caller
                )
            )

            records = [
                record
                for record in records
                if (
                    record.caller
                    == normalized_caller
                )
            ]

        if permitted is not None:

            records = [
                record
                for record in records
                if record.permitted is permitted
            ]

        if newest_first:
            records.reverse()

        if limit is not None:
            records = records[:limit]

        return tuple(records)

    def clear_history(self) -> None:
        """
        Clear change and access history.
        """

        with self._secret_lock:
            self._change_history.clear()
            self._access_history.clear()

    # =====================================================
    # INTERNAL SECURITY
    # =====================================================

    def _authorize(
        self,
        definition: SecretDefinition,
        caller: str,
        *,
        operation: str,
    ) -> None:
        """
        Validate caller access against the definition.
        """

        if (
            definition.allowed_callers
            and caller
            not in definition.allowed_callers
        ):

            with self._secret_lock:
                self._denied_accesses += 1

            self._record_access(
                key=definition.key,
                caller=caller,
                operation=operation,
                permitted=False,
                reason="CALLER_NOT_ALLOWED",
            )

            raise SecretAccessDeniedError(
                f"Caller '{caller}' is not allowed "
                f"to access secret '{definition.key}'."
            )

    @staticmethod
    def _validate_value(
        definition: SecretDefinition,
        value: str,
    ) -> str:
        """
        Validate a plain secret value.
        """

        if not isinstance(value, str):
            raise SecretValidationError(
                "Secret value must be a string."
            )

        if len(value) < definition.minimum_length:
            raise SecretValidationError(
                f"Secret '{definition.key}' must contain "
                f"at least {definition.minimum_length} characters."
            )

        if not value:
            raise SecretValidationError(
                "Secret value cannot be empty."
            )

        return value

    def _fingerprint(
        self,
        value: str,
    ) -> str:
        """
        Create a non-reversible short secret fingerprint.
        """

        digest = hashlib.sha256(
            value.encode("utf-8")
        ).hexdigest()

        return digest[
            :self._fingerprint_length
        ]

    @staticmethod
    def _is_expired(
        stored: _StoredSecret,
    ) -> bool:
        """
        Return True when the secret has expired.
        """

        return (
            stored.expires_at is not None
            and datetime.now(UTC)
            >= stored.expires_at
        )

    def _status_of(
        self,
        stored: _StoredSecret,
    ) -> SecretStatus:
        """
        Resolve current secret status.
        """

        if stored.revoked:
            return SecretStatus.REVOKED

        if self._is_expired(stored):
            return SecretStatus.EXPIRED

        return SecretStatus.ACTIVE

    # =====================================================
    # INTERNAL HISTORY
    # =====================================================

    def _record_access(
        self,
        *,
        key: str,
        caller: str,
        operation: str,
        permitted: bool,
        reason: str | None = None,
    ) -> None:
        """
        Record one safe secret access operation.
        """

        record = SecretAccessRecord(
            access_id=str(uuid.uuid4()),
            key=key,
            caller=caller,
            operation=operation,
            permitted=permitted,
            reason=reason,
            accessed_at=datetime.now(UTC),
        )

        with self._secret_lock:
            self._access_history.append(
                record
            )

    def _record_change(
        self,
        *,
        key: str,
        operation: str,
        source: SecretSource | None,
        version: int,
        previous_fingerprint: str | None,
        current_fingerprint: str | None,
    ) -> None:
        """
        Record one safe secret lifecycle change.
        """

        record = SecretChangeRecord(
            change_id=str(uuid.uuid4()),
            key=key,
            operation=operation,
            source=source,
            version=version,
            previous_fingerprint=(
                previous_fingerprint
            ),
            current_fingerprint=(
                current_fingerprint
            ),
            changed_at=datetime.now(UTC),
        )

        self._change_history.append(
            record
        )

    # =====================================================
    # EVENT PUBLICATION
    # =====================================================

    def _publish_secret_event(
        self,
        event_type: SecretEventType,
        *,
        severity: EventSeverity = EventSeverity.INFO,
        payload: Mapping[str, Any] | None = None,
    ) -> None:
        """
        Publish a safe Secrets Manager event.
        """

        if (
            not self._publish_events
            or self._event_bus is None
        ):
            return

        try:

            self._event_bus.publish_event(
                event_type=event_type.value,
                source=self.identity.name,
                severity=severity,
                payload=dict(payload or {}),
            )

        except Exception as exc:

            error = (
                f"{type(exc).__name__}: {exc}"
            )

            with self._secret_lock:

                self._event_publication_failures += 1
                self._last_error = error

            logger.exception(
                "Secrets Manager event publication "
                "failed | event=%s",
                event_type.value,
            )

    # =====================================================
    # HELPERS
    # =====================================================

    @staticmethod
    def _normalize_key(
        key: str,
    ) -> str:
        """
        Normalize one secret key.
        """

        if not isinstance(key, str):
            raise TypeError(
                "Secret key must be a string."
            )

        normalized = key.strip().upper()

        if not normalized:
            raise ValueError(
                "Secret key cannot be empty."
            )

        return normalized

    @staticmethod
    def _normalize_caller(
        caller: str,
    ) -> str:
        """
        Normalize one caller identifier.
        """

        if not isinstance(caller, str):
            raise TypeError(
                "caller must be a string."
            )

        normalized = caller.strip()

        if not normalized:
            raise ValueError(
                "caller cannot be empty."
            )

        return normalized

    # =====================================================
    # BASE SERVICE DIAGNOSTICS
    # =====================================================

    def _health_details(
        self,
    ) -> Mapping[str, Any]:
        """
        Return safe Secrets Manager health details.
        """

        statistics = self.statistics()

        return {
            "registered_secrets": (
                statistics.registered_secrets
            ),
            "configured_secrets": (
                statistics.configured_secrets
            ),
            "required_secrets": (
                statistics.required_secrets
            ),
            "missing_required_secrets": (
                statistics.missing_required_secrets
            ),
            "active_secrets": (
                statistics.active_secrets
            ),
            "expired_secrets": (
                statistics.expired_secrets
            ),
            "revoked_secrets": (
                statistics.revoked_secrets
            ),
            "total_accesses": (
                statistics.total_accesses
            ),
            "denied_accesses": (
                statistics.denied_accesses
            ),
            "total_rotations": (
                statistics.total_rotations
            ),
            "environment_loads": (
                statistics.environment_loads
            ),
            "generated_secrets": (
                statistics.generated_secrets
            ),
            "event_publication_failures": (
                statistics
                .event_publication_failures
            ),
            "last_error": (
                statistics.last_error
            ),
        }

    def _snapshot_metadata(
        self,
    ) -> Mapping[str, Any]:
        """
        Return safe service metadata.
        """

        return {
            "history_limit": self._history_limit,
            "access_history_limit": (
                self._access_history_limit
            ),
            "secret_mask_length": len(
                self._secret_mask
            ),
            "fingerprint_length": (
                self._fingerprint_length
            ),
            "publish_events": (
                self._publish_events
            ),
            "event_bus_configured": (
                self._event_bus is not None
            ),
            "persistent_storage": False,
            "plain_values_in_snapshots": False,
        }