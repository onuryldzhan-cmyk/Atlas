"""
============================================================
ATLAS OS CONFIGURATION SERVICE v1.0
============================================================

Enterprise configuration management infrastructure for AtlasOS.

Responsibilities
----------------
- Define configuration schemas
- Load environment variables
- Load JSON configuration files
- Apply runtime overrides
- Validate required settings
- Convert values into declared types
- Mask sensitive configuration values
- Track configuration changes
- Produce immutable snapshots
- Reload registered configuration sources
- Publish configuration lifecycle events
- Operate as an AtlasOS managed service

Source Precedence
-----------------
Lowest priority
    |
    +-- Schema defaults
    +-- JSON configuration files
    +-- Environment variables
    +-- Runtime overrides
    |
Highest priority

Architecture
------------
Configuration Sources
        |
        +-- Defaults
        +-- JSON
        +-- Environment
        +-- Runtime
        |
        v
ConfigurationService
        |
        +-- Schema Registry
        +-- Type Converter
        +-- Validation Engine
        +-- Secret Masking
        +-- Change History
        +-- Snapshot Engine
        +-- Event Publisher

Design Principles
-----------------
- Explicit schemas
- Deterministic source precedence
- Strong typing
- Immutable public snapshots
- Thread-safe runtime operations
- Sensitive-value protection
- No external dependencies
- No autonomous production changes
- Human-controlled runtime overrides

============================================================
"""

from __future__ import annotations

import json
import logging
import math
import os
import threading
import uuid

from collections import deque
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from types import MappingProxyType
from typing import Any, Mapping

from atlas_os.contracts import ServiceIdentity
from atlas_os.events import (
    EventBusService,
    EventSeverity,
)
from atlas_os.services import BaseAtlasService


logger = logging.getLogger(
    "AtlasAI.AtlasOS.Configuration"
)


# =========================================================
# ENUMERATIONS
# =========================================================

class ConfigurationValueType(StrEnum):
    """
    Supported configuration value types.
    """

    STRING = "STRING"
    INTEGER = "INTEGER"
    FLOAT = "FLOAT"
    BOOLEAN = "BOOLEAN"
    LIST = "LIST"
    DICTIONARY = "DICTIONARY"


class ConfigurationSource(StrEnum):
    """
    Configuration source identifiers.
    """

    DEFAULT = "DEFAULT"
    JSON_FILE = "JSON_FILE"
    ENVIRONMENT = "ENVIRONMENT"
    RUNTIME = "RUNTIME"


class ConfigurationEnvironment(StrEnum):
    """
    Standard AtlasOS runtime environments.
    """

    DEVELOPMENT = "DEVELOPMENT"
    TEST = "TEST"
    STAGING = "STAGING"
    PRODUCTION = "PRODUCTION"


class ConfigurationEventType(StrEnum):
    """
    Events published by ConfigurationService.
    """

    CONFIGURATION_STARTED = "CONFIGURATION_STARTED"
    CONFIGURATION_STOPPED = "CONFIGURATION_STOPPED"

    CONFIGURATION_SCHEMA_REGISTERED = (
        "CONFIGURATION_SCHEMA_REGISTERED"
    )

    CONFIGURATION_VALUE_CHANGED = (
        "CONFIGURATION_VALUE_CHANGED"
    )

    CONFIGURATION_SOURCE_LOADED = (
        "CONFIGURATION_SOURCE_LOADED"
    )

    CONFIGURATION_RELOADED = (
        "CONFIGURATION_RELOADED"
    )

    CONFIGURATION_VALIDATION_FAILED = (
        "CONFIGURATION_VALIDATION_FAILED"
    )


# =========================================================
# EXCEPTIONS
# =========================================================

class ConfigurationError(RuntimeError):
    """
    Base configuration exception.
    """


class ConfigurationKeyNotFoundError(ConfigurationError):
    """
    Raised when a configuration key does not exist.
    """


class DuplicateConfigurationKeyError(ConfigurationError):
    """
    Raised when a schema key is registered twice.
    """


class ConfigurationValidationError(ConfigurationError):
    """
    Raised when configuration validation fails.
    """


class ConfigurationConversionError(ConfigurationError):
    """
    Raised when a value cannot be converted.
    """


class ConfigurationSourceError(ConfigurationError):
    """
    Raised when a configuration source cannot be loaded.
    """


class ProductionSafetyError(ConfigurationError):
    """
    Raised when production safety requirements are violated.
    """


# =========================================================
# DATA MODELS
# =========================================================

@dataclass(frozen=True, slots=True)
class ConfigurationSchema:
    """
    Immutable schema definition for one configuration key.
    """

    key: str
    value_type: ConfigurationValueType
    default: Any = None
    required: bool = False
    secret: bool = False
    description: str = ""
    environment_variable: str | None = None
    allowed_values: tuple[Any, ...] = ()
    minimum: float | None = None
    maximum: float | None = None

    def __post_init__(self) -> None:

        normalized_key = self.key.strip().upper()

        if not normalized_key:
            raise ValueError(
                "Configuration key cannot be empty."
            )

        normalized_description = (
            self.description.strip()
        )

        environment_variable = (
            self.environment_variable.strip().upper()
            if self.environment_variable is not None
            else normalized_key
        )

        if not environment_variable:
            raise ValueError(
                "environment_variable cannot be empty."
            )

        if (
            self.minimum is not None
            and self.maximum is not None
            and self.minimum > self.maximum
        ):
            raise ValueError(
                "minimum cannot be greater than maximum."
            )

        object.__setattr__(
            self,
            "key",
            normalized_key,
        )

        object.__setattr__(
            self,
            "description",
            normalized_description,
        )

        object.__setattr__(
            self,
            "environment_variable",
            environment_variable,
        )

        object.__setattr__(
            self,
            "allowed_values",
            tuple(self.allowed_values),
        )


@dataclass(frozen=True, slots=True)
class ConfigurationEntry:
    """
    Immutable resolved configuration entry.
    """

    key: str
    value: Any
    masked_value: Any
    value_type: ConfigurationValueType
    source: ConfigurationSource
    required: bool
    secret: bool
    description: str
    updated_at: datetime


@dataclass(frozen=True, slots=True)
class ConfigurationChange:
    """
    Immutable configuration change record.
    """

    change_id: str
    key: str
    source: ConfigurationSource
    previous_value: Any
    current_value: Any
    previous_masked_value: Any
    current_masked_value: Any
    changed_at: datetime
    changed: bool


@dataclass(frozen=True, slots=True)
class ConfigurationStatistics:
    """
    Immutable Configuration Service statistics.
    """

    registered_keys: int
    configured_keys: int
    required_keys: int
    missing_required_keys: int
    secret_keys: int
    json_sources: int
    runtime_overrides: int
    total_changes: int
    successful_loads: int
    failed_loads: int
    reload_count: int
    event_publication_failures: int
    last_loaded_source: str | None
    last_error: str | None
    generated_at: datetime = field(
        default_factory=lambda: datetime.now(UTC)
    )


@dataclass(frozen=True, slots=True)
class ConfigurationSnapshot:
    """
    Complete immutable configuration snapshot.
    """

    running: bool
    environment: ConfigurationEnvironment
    strict_mode: bool
    valid: bool
    entries: tuple[ConfigurationEntry, ...]
    missing_required_keys: tuple[str, ...]
    statistics: ConfigurationStatistics
    generated_at: datetime = field(
        default_factory=lambda: datetime.now(UTC)
    )


@dataclass(slots=True)
class _ConfigurationValue:
    """
    Internal mutable configuration value.
    """

    value: Any
    source: ConfigurationSource
    updated_at: datetime


# =========================================================
# CONFIGURATION SERVICE
# =========================================================

class ConfigurationService(BaseAtlasService):
    """
    Central AtlasOS configuration management service.

    Values are resolved according to source priority:

    DEFAULT < JSON_FILE < ENVIRONMENT < RUNTIME
    """

    VERSION = "1.0.0"

    NAME = "AtlasOSConfiguration"

    _SOURCE_PRIORITY = {
        ConfigurationSource.DEFAULT: 10,
        ConfigurationSource.JSON_FILE: 20,
        ConfigurationSource.ENVIRONMENT: 30,
        ConfigurationSource.RUNTIME: 40,
    }

    _TRUE_VALUES = {
        "1",
        "TRUE",
        "YES",
        "ON",
        "ENABLED",
    }

    _FALSE_VALUES = {
        "0",
        "FALSE",
        "NO",
        "OFF",
        "DISABLED",
    }

    def __init__(
        self,
        *,
        environment: ConfigurationEnvironment = (
            ConfigurationEnvironment.DEVELOPMENT
        ),
        strict_mode: bool = True,
        history_limit: int = 1000,
        secret_mask: str = "********",
        event_bus: EventBusService | None = None,
        publish_events: bool = False,
    ) -> None:

        if history_limit <= 0:
            raise ValueError(
                "history_limit must be greater than zero."
            )

        if not secret_mask:
            raise ValueError(
                "secret_mask cannot be empty."
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
                service_type="CONFIGURATION",
                description=(
                    "Central enterprise configuration "
                    "management service for AtlasOS."
                ),
            )
        )

        self._environment = ConfigurationEnvironment(
            environment
        )

        self._strict_mode = bool(strict_mode)
        self._history_limit = int(history_limit)
        self._secret_mask = str(secret_mask)

        self._event_bus = event_bus
        self._publish_events = bool(publish_events)

        self._schemas: dict[
            str,
            ConfigurationSchema,
        ] = {}

        self._values: dict[
            str,
            _ConfigurationValue,
        ] = {}

        self._runtime_overrides: dict[
            str,
            Any,
        ] = {}

        self._json_sources: list[Path] = []

        self._history: deque[
            ConfigurationChange
        ] = deque(
            maxlen=self._history_limit
        )

        self._successful_loads = 0
        self._failed_loads = 0
        self._reload_count = 0
        self._event_publication_failures = 0

        self._last_loaded_source: str | None = None
        self._last_error: str | None = None

        self._configuration_lock = threading.RLock()

    # =====================================================
    # PROPERTIES
    # =====================================================

    @property
    def environment(
        self,
    ) -> ConfigurationEnvironment:
        """
        Return active environment profile.
        """

        return self._environment

    @property
    def strict_mode(self) -> bool:
        """
        Return strict validation setting.
        """

        return self._strict_mode

    @property
    def registered_key_count(self) -> int:
        """
        Return registered schema count.
        """

        with self._configuration_lock:
            return len(self._schemas)

    # =====================================================
    # SERVICE LIFECYCLE
    # =====================================================

    def _on_start(self) -> None:
        """
        Resolve registered configuration sources and validate.
        """

        self.reload()

        missing = self.missing_required_keys()

        if missing and self._strict_mode:

            message = (
                "Required configuration values are missing: "
                + ", ".join(missing)
            )

            self._last_error = message

            self._publish_configuration_event(
                ConfigurationEventType
                .CONFIGURATION_VALIDATION_FAILED,
                severity=EventSeverity.ERROR,
                payload={
                    "missing_required_keys": list(missing),
                },
            )

            raise ConfigurationValidationError(
                message
            )

        self._publish_configuration_event(
            ConfigurationEventType.CONFIGURATION_STARTED,
            payload={
                "environment": self._environment.value,
                "registered_keys": len(self._schemas),
                "missing_required_keys": list(missing),
            },
        )

        logger.info(
            "AtlasOS Configuration Service started | "
            "environment=%s | keys=%s",
            self._environment.value,
            len(self._schemas),
        )

    def _on_stop(self) -> None:
        """
        Stop Configuration Service.
        """

        self._publish_configuration_event(
            ConfigurationEventType.CONFIGURATION_STOPPED,
            payload={
                "registered_keys": len(self._schemas),
                "configured_keys": len(self._values),
            },
        )

        logger.info(
            "AtlasOS Configuration Service stopped."
        )

    # =====================================================
    # SCHEMA REGISTRATION
    # =====================================================

    def register_schema(
        self,
        schema: ConfigurationSchema,
        *,
        replace: bool = False,
    ) -> ConfigurationSchema:
        """
        Register one configuration schema.
        """

        if not isinstance(
            schema,
            ConfigurationSchema,
        ):
            raise TypeError(
                "schema must be a ConfigurationSchema instance."
            )

        with self._configuration_lock:

            if (
                schema.key in self._schemas
                and not replace
            ):
                raise DuplicateConfigurationKeyError(
                    f"Configuration key already registered: "
                    f"{schema.key}"
                )

            self._schemas[schema.key] = schema

            if schema.default is not None:

                converted_default = self._convert_value(
                    schema,
                    schema.default,
                )

                self._apply_value(
                    schema.key,
                    converted_default,
                    ConfigurationSource.DEFAULT,
                )

        self._publish_configuration_event(
            ConfigurationEventType
            .CONFIGURATION_SCHEMA_REGISTERED,
            payload={
                "key": schema.key,
                "value_type": schema.value_type.value,
                "required": schema.required,
                "secret": schema.secret,
            },
        )

        return schema

    def register(
        self,
        key: str,
        value_type: ConfigurationValueType,
        *,
        default: Any = None,
        required: bool = False,
        secret: bool = False,
        description: str = "",
        environment_variable: str | None = None,
        allowed_values: tuple[Any, ...] = (),
        minimum: float | None = None,
        maximum: float | None = None,
        replace: bool = False,
    ) -> ConfigurationSchema:
        """
        Build and register one configuration schema.
        """

        schema = ConfigurationSchema(
            key=key,
            value_type=ConfigurationValueType(
                value_type
            ),
            default=default,
            required=required,
            secret=secret,
            description=description,
            environment_variable=environment_variable,
            allowed_values=allowed_values,
            minimum=minimum,
            maximum=maximum,
        )

        return self.register_schema(
            schema,
            replace=replace,
        )

    def register_many(
        self,
        schemas: tuple[
            ConfigurationSchema,
            ...,
        ],
        *,
        replace: bool = False,
    ) -> tuple[
        ConfigurationSchema,
        ...,
    ]:
        """
        Register multiple configuration schemas.
        """

        return tuple(
            self.register_schema(
                schema,
                replace=replace,
            )
            for schema in schemas
        )

    # =====================================================
    # SOURCE REGISTRATION
    # =====================================================

    def add_json_source(
        self,
        path: str | Path,
    ) -> Path:
        """
        Register a JSON configuration source.
        """

        resolved_path = Path(path).expanduser()

        with self._configuration_lock:

            if resolved_path not in self._json_sources:
                self._json_sources.append(
                    resolved_path
                )

        return resolved_path

    def json_sources(
        self,
    ) -> tuple[Path, ...]:
        """
        Return registered JSON sources.
        """

        with self._configuration_lock:
            return tuple(self._json_sources)

    # =====================================================
    # SOURCE LOADING
    # =====================================================

    def load_json(
        self,
        path: str | Path,
        *,
        register_source: bool = True,
        ignore_missing: bool = False,
    ) -> int:
        """
        Load configuration values from one JSON file.

        Nested dictionaries are flattened using underscore-separated keys.

        Example
        -------
        {
            "database": {
                "host": "localhost"
            }
        }

        becomes:

        DATABASE_HOST
        """

        resolved_path = Path(path).expanduser()

        if register_source:
            self.add_json_source(
                resolved_path
            )

        if not resolved_path.exists():

            if ignore_missing:
                return 0

            self._record_load_failure(
                f"JSON configuration file not found: "
                f"{resolved_path}"
            )

            raise ConfigurationSourceError(
                f"JSON configuration file not found: "
                f"{resolved_path}"
            )

        try:

            with resolved_path.open(
                "r",
                encoding="utf-8",
            ) as file:

                raw_data = json.load(file)

        except (
            OSError,
            json.JSONDecodeError,
        ) as exc:

            message = (
                f"Failed to load JSON configuration "
                f"from {resolved_path}: "
                f"{type(exc).__name__}: {exc}"
            )

            self._record_load_failure(
                message
            )

            raise ConfigurationSourceError(
                message
            ) from exc

        if not isinstance(raw_data, dict):

            message = (
                "JSON configuration root must be "
                "an object."
            )

            self._record_load_failure(
                message
            )

            raise ConfigurationSourceError(
                message
            )

        flattened = self._flatten_mapping(
            raw_data
        )

        applied = self._load_mapping(
            flattened,
            ConfigurationSource.JSON_FILE,
            ignore_unknown=not self._strict_mode,
        )

        with self._configuration_lock:

            self._successful_loads += 1
            self._last_loaded_source = str(
                resolved_path
            )
            self._last_error = None

        self._publish_configuration_event(
            ConfigurationEventType
            .CONFIGURATION_SOURCE_LOADED,
            payload={
                "source": ConfigurationSource.JSON_FILE.value,
                "path": str(resolved_path),
                "applied_values": applied,
            },
        )

        return applied

    def load_environment(
        self,
        *,
        prefix: str = "",
    ) -> int:
        """
        Load registered values from process environment variables.
        """

        normalized_prefix = prefix.strip().upper()

        applied = 0

        with self._configuration_lock:
            schemas = tuple(self._schemas.values())

        for schema in schemas:

            variable_name = (
                normalized_prefix
                + str(schema.environment_variable)
            )

            if variable_name not in os.environ:
                continue

            raw_value = os.environ[
                variable_name
            ]

            converted = self._convert_value(
                schema,
                raw_value,
            )

            self._apply_value(
                schema.key,
                converted,
                ConfigurationSource.ENVIRONMENT,
            )

            applied += 1

        with self._configuration_lock:

            self._successful_loads += 1
            self._last_loaded_source = (
                f"ENVIRONMENT:{normalized_prefix}"
            )
            self._last_error = None

        self._publish_configuration_event(
            ConfigurationEventType
            .CONFIGURATION_SOURCE_LOADED,
            payload={
                "source": (
                    ConfigurationSource
                    .ENVIRONMENT
                    .value
                ),
                "prefix": normalized_prefix,
                "applied_values": applied,
            },
        )

        return applied

    def reload(self) -> int:
        """
        Reload defaults, JSON sources, environment and runtime values.
        """

        with self._configuration_lock:

            schemas = tuple(self._schemas.values())
            json_sources = tuple(self._json_sources)
            runtime_overrides = dict(
                self._runtime_overrides
            )

            self._values.clear()

        applied = 0

        for schema in schemas:

            if schema.default is None:
                continue

            converted = self._convert_value(
                schema,
                schema.default,
            )

            self._apply_value(
                schema.key,
                converted,
                ConfigurationSource.DEFAULT,
            )

            applied += 1

        for source in json_sources:

            applied += self.load_json(
                source,
                register_source=False,
                ignore_missing=not self._strict_mode,
            )

        applied += self.load_environment()

        for key, raw_value in runtime_overrides.items():

            self.set(
                key,
                raw_value,
                source=ConfigurationSource.RUNTIME,
                persist_override=False,
            )

            applied += 1

        with self._configuration_lock:

            self._reload_count += 1
            self._last_error = None

        self._publish_configuration_event(
            ConfigurationEventType.CONFIGURATION_RELOADED,
            payload={
                "applied_values": applied,
                "reload_count": self._reload_count,
            },
        )

        return applied

    # =====================================================
    # VALUE MANAGEMENT
    # =====================================================

    def set(
        self,
        key: str,
        value: Any,
        *,
        source: ConfigurationSource = (
            ConfigurationSource.RUNTIME
        ),
        persist_override: bool = True,
    ) -> ConfigurationChange:
        """
        Set one configuration value.
        """

        normalized_key = self._normalize_key(
            key
        )

        resolved_source = ConfigurationSource(
            source
        )

        with self._configuration_lock:

            schema = self._schemas.get(
                normalized_key
            )

        if schema is None:
            raise ConfigurationKeyNotFoundError(
                f"Configuration key not registered: "
                f"{normalized_key}"
            )

        converted = self._convert_value(
            schema,
            value,
        )

        change = self._apply_value(
            normalized_key,
            converted,
            resolved_source,
        )

        if (
            persist_override
            and resolved_source
            == ConfigurationSource.RUNTIME
        ):
            with self._configuration_lock:
                self._runtime_overrides[
                    normalized_key
                ] = converted

        return change

    def remove_runtime_override(
        self,
        key: str,
        *,
        reload_configuration: bool = True,
    ) -> bool:
        """
        Remove one runtime override.
        """

        normalized_key = self._normalize_key(
            key
        )

        with self._configuration_lock:

            existed = (
                normalized_key
                in self._runtime_overrides
            )

            self._runtime_overrides.pop(
                normalized_key,
                None,
            )

        if existed and reload_configuration:
            self.reload()

        return existed

    def clear_runtime_overrides(
        self,
        *,
        reload_configuration: bool = True,
    ) -> int:
        """
        Remove all runtime overrides.
        """

        with self._configuration_lock:

            count = len(
                self._runtime_overrides
            )

            self._runtime_overrides.clear()

        if count and reload_configuration:
            self.reload()

        return count

    def get(
        self,
        key: str,
        default: Any = None,
    ) -> Any:
        """
        Return one resolved configuration value.
        """

        normalized_key = self._normalize_key(
            key
        )

        with self._configuration_lock:

            stored = self._values.get(
                normalized_key
            )

            if stored is None:
                return default

            return stored.value

    def require(
        self,
        key: str,
    ) -> Any:
        """
        Return a value or raise when it is unavailable.
        """

        normalized_key = self._normalize_key(
            key
        )

        with self._configuration_lock:

            if normalized_key not in self._schemas:
                raise ConfigurationKeyNotFoundError(
                    f"Configuration key not registered: "
                    f"{normalized_key}"
                )

            stored = self._values.get(
                normalized_key
            )

        if stored is None or stored.value is None:
            raise ConfigurationValidationError(
                f"Required configuration value "
                f"is missing: {normalized_key}"
            )

        return stored.value

    def contains(
        self,
        key: str,
    ) -> bool:
        """
        Return True when a resolved value exists.
        """

        normalized_key = self._normalize_key(
            key
        )

        with self._configuration_lock:

            return (
                normalized_key in self._values
                and self._values[
                    normalized_key
                ].value is not None
            )

    def source_of(
        self,
        key: str,
    ) -> ConfigurationSource | None:
        """
        Return the active source of one configuration value.
        """

        normalized_key = self._normalize_key(
            key
        )

        with self._configuration_lock:

            stored = self._values.get(
                normalized_key
            )

            return (
                stored.source
                if stored is not None
                else None
            )

    # =====================================================
    # VALIDATION
    # =====================================================

    def missing_required_keys(
        self,
    ) -> tuple[str, ...]:
        """
        Return required keys without resolved values.
        """

        with self._configuration_lock:

            return tuple(
                schema.key
                for schema in self._schemas.values()
                if (
                    schema.required
                    and (
                        schema.key not in self._values
                        or self._values[
                            schema.key
                        ].value is None
                    )
                )
            )

    def validate(
        self,
        *,
        raise_on_error: bool = True,
    ) -> bool:
        """
        Validate all required configuration values.
        """

        missing = self.missing_required_keys()

        if not missing:
            return True

        message = (
            "Required configuration values are missing: "
            + ", ".join(missing)
        )

        with self._configuration_lock:
            self._last_error = message

        self._publish_configuration_event(
            ConfigurationEventType
            .CONFIGURATION_VALIDATION_FAILED,
            severity=EventSeverity.ERROR,
            payload={
                "missing_required_keys": list(missing),
            },
        )

        if raise_on_error:
            raise ConfigurationValidationError(
                message
            )

        return False

    def validate_production(
        self,
        *,
        required_environment: (
            ConfigurationEnvironment
        ) = ConfigurationEnvironment.PRODUCTION,
    ) -> bool:
        """
        Enforce baseline production safety rules.
        """

        if self._environment != required_environment:
            return True

        missing = self.missing_required_keys()

        if missing:
            raise ProductionSafetyError(
                "Production configuration is incomplete: "
                + ", ".join(missing)
            )

        secret_keys = [
            schema.key
            for schema in self._schemas.values()
            if schema.secret
        ]

        for key in secret_keys:

            if not self.contains(key):
                raise ProductionSafetyError(
                    f"Production secret is missing: {key}"
                )

        return True

    # =====================================================
    # SNAPSHOTS
    # =====================================================

    def entry(
        self,
        key: str,
    ) -> ConfigurationEntry:
        """
        Return one immutable configuration entry.
        """

        normalized_key = self._normalize_key(
            key
        )

        with self._configuration_lock:

            schema = self._schemas.get(
                normalized_key
            )

            if schema is None:
                raise ConfigurationKeyNotFoundError(
                    f"Configuration key not registered: "
                    f"{normalized_key}"
                )

            stored = self._values.get(
                normalized_key
            )

            value = (
                stored.value
                if stored is not None
                else None
            )

            source = (
                stored.source
                if stored is not None
                else ConfigurationSource.DEFAULT
            )

            updated_at = (
                stored.updated_at
                if stored is not None
                else datetime.now(UTC)
            )

            return ConfigurationEntry(
                key=schema.key,
                value=value,
                masked_value=self._mask_value(
                    schema,
                    value,
                ),
                value_type=schema.value_type,
                source=source,
                required=schema.required,
                secret=schema.secret,
                description=schema.description,
                updated_at=updated_at,
            )

    def entries(
        self,
    ) -> tuple[
        ConfigurationEntry,
        ...,
    ]:
        """
        Return all configuration entries.
        """

        with self._configuration_lock:
            keys = tuple(sorted(self._schemas))

        return tuple(
            self.entry(key)
            for key in keys
        )

    def as_dict(
        self,
        *,
        mask_secrets: bool = True,
    ) -> Mapping[str, Any]:
        """
        Export resolved configuration as an immutable mapping.
        """

        values = {}

        for entry in self.entries():

            values[entry.key] = (
                entry.masked_value
                if mask_secrets
                else entry.value
            )

        return MappingProxyType(
            values
        )

    def statistics(
        self,
    ) -> ConfigurationStatistics:
        """
        Return immutable runtime statistics.
        """

        missing = self.missing_required_keys()

        with self._configuration_lock:

            return ConfigurationStatistics(
                registered_keys=len(self._schemas),
                configured_keys=len(self._values),
                required_keys=sum(
                    schema.required
                    for schema in self._schemas.values()
                ),
                missing_required_keys=len(missing),
                secret_keys=sum(
                    schema.secret
                    for schema in self._schemas.values()
                ),
                json_sources=len(self._json_sources),
                runtime_overrides=len(
                    self._runtime_overrides
                ),
                total_changes=len(self._history),
                successful_loads=self._successful_loads,
                failed_loads=self._failed_loads,
                reload_count=self._reload_count,
                event_publication_failures=(
                    self._event_publication_failures
                ),
                last_loaded_source=(
                    self._last_loaded_source
                ),
                last_error=self._last_error,
            )

    def configuration_snapshot(
        self,
    ) -> ConfigurationSnapshot:
        """
        Return complete Configuration Service diagnostics.
        """

        missing = self.missing_required_keys()

        return ConfigurationSnapshot(
            running=self.is_running,
            environment=self._environment,
            strict_mode=self._strict_mode,
            valid=not missing,
            entries=self.entries(),
            missing_required_keys=missing,
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
    ) -> tuple[
        ConfigurationChange,
        ...,
    ]:
        """
        Return bounded configuration change history.
        """

        if limit is not None and limit < 0:
            raise ValueError(
                "limit cannot be negative."
            )

        with self._configuration_lock:
            changes = list(self._history)

        if key is not None:

            normalized_key = self._normalize_key(
                key
            )

            changes = [
                change
                for change in changes
                if change.key == normalized_key
            ]

        if newest_first:
            changes.reverse()

        if limit is not None:
            changes = changes[:limit]

        return tuple(changes)

    def clear_change_history(self) -> None:
        """
        Clear retained configuration change history.
        """

        with self._configuration_lock:
            self._history.clear()

    # =====================================================
    # INTERNAL VALUE APPLICATION
    # =====================================================

    def _apply_value(
        self,
        key: str,
        value: Any,
        source: ConfigurationSource,
    ) -> ConfigurationChange:
        """
        Apply one value according to source priority.
        """

        normalized_key = self._normalize_key(
            key
        )

        with self._configuration_lock:

            schema = self._schemas.get(
                normalized_key
            )

            if schema is None:
                raise ConfigurationKeyNotFoundError(
                    f"Configuration key not registered: "
                    f"{normalized_key}"
                )

            current = self._values.get(
                normalized_key
            )

            if current is not None:

                current_priority = (
                    self._SOURCE_PRIORITY[
                        current.source
                    ]
                )

                incoming_priority = (
                    self._SOURCE_PRIORITY[
                        source
                    ]
                )

                if incoming_priority < current_priority:

                    return ConfigurationChange(
                        change_id=str(uuid.uuid4()),
                        key=normalized_key,
                        source=source,
                        previous_value=current.value,
                        current_value=current.value,
                        previous_masked_value=(
                            self._mask_value(
                                schema,
                                current.value,
                            )
                        ),
                        current_masked_value=(
                            self._mask_value(
                                schema,
                                current.value,
                            )
                        ),
                        changed_at=datetime.now(UTC),
                        changed=False,
                    )

            previous_value = (
                current.value
                if current is not None
                else None
            )

            changed = (
                current is None
                or previous_value != value
                or current.source != source
            )

            timestamp = datetime.now(UTC)

            self._values[
                normalized_key
            ] = _ConfigurationValue(
                value=value,
                source=source,
                updated_at=timestamp,
            )

            change = ConfigurationChange(
                change_id=str(uuid.uuid4()),
                key=normalized_key,
                source=source,
                previous_value=previous_value,
                current_value=value,
                previous_masked_value=(
                    self._mask_value(
                        schema,
                        previous_value,
                    )
                ),
                current_masked_value=(
                    self._mask_value(
                        schema,
                        value,
                    )
                ),
                changed_at=timestamp,
                changed=changed,
            )

            if changed:
                self._history.append(change)

        if changed:

            self._publish_configuration_event(
                ConfigurationEventType
                .CONFIGURATION_VALUE_CHANGED,
                payload={
                    "key": normalized_key,
                    "source": source.value,
                    "previous_value": (
                        change.previous_masked_value
                    ),
                    "current_value": (
                        change.current_masked_value
                    ),
                },
                correlation_id=change.change_id,
            )

        return change

    def _load_mapping(
        self,
        values: Mapping[str, Any],
        source: ConfigurationSource,
        *,
        ignore_unknown: bool,
    ) -> int:
        """
        Load values from a normalized mapping.
        """

        applied = 0

        for key, raw_value in values.items():

            normalized_key = self._normalize_key(
                key
            )

            with self._configuration_lock:
                schema = self._schemas.get(
                    normalized_key
                )

            if schema is None:

                if ignore_unknown:
                    continue

                raise ConfigurationKeyNotFoundError(
                    f"Configuration key not registered: "
                    f"{normalized_key}"
                )

            converted = self._convert_value(
                schema,
                raw_value,
            )

            self._apply_value(
                normalized_key,
                converted,
                source,
            )

            applied += 1

        return applied

    # =====================================================
    # TYPE CONVERSION
    # =====================================================

    def _convert_value(
        self,
        schema: ConfigurationSchema,
        value: Any,
    ) -> Any:
        """
        Convert and validate one value.
        """

        if value is None:
            return None

        try:

            if (
                schema.value_type
                == ConfigurationValueType.STRING
            ):
                converted = str(value)

            elif (
                schema.value_type
                == ConfigurationValueType.INTEGER
            ):

                if isinstance(value, bool):
                    raise ValueError(
                        "Boolean cannot be converted to integer."
                    )

                converted = int(value)

            elif (
                schema.value_type
                == ConfigurationValueType.FLOAT
            ):

                if isinstance(value, bool):
                    raise ValueError(
                        "Boolean cannot be converted to float."
                    )

                converted = float(value)

                if not math.isfinite(converted):
                    raise ValueError(
                        "Float value must be finite."
                    )

            elif (
                schema.value_type
                == ConfigurationValueType.BOOLEAN
            ):
                converted = self._convert_boolean(
                    value
                )

            elif (
                schema.value_type
                == ConfigurationValueType.LIST
            ):
                converted = self._convert_list(
                    value
                )

            elif (
                schema.value_type
                == ConfigurationValueType.DICTIONARY
            ):
                converted = self._convert_dictionary(
                    value
                )

            else:
                raise ValueError(
                    f"Unsupported configuration type: "
                    f"{schema.value_type}"
                )

        except (
            TypeError,
            ValueError,
            json.JSONDecodeError,
        ) as exc:

            raise ConfigurationConversionError(
                f"Cannot convert configuration "
                f"'{schema.key}' to "
                f"{schema.value_type.value}: "
                f"{type(exc).__name__}: {exc}"
            ) from exc

        self._validate_constraints(
            schema,
            converted,
        )

        return converted

    def _validate_constraints(
        self,
        schema: ConfigurationSchema,
        value: Any,
    ) -> None:
        """
        Validate allowed values and numeric boundaries.
        """

        if (
            schema.allowed_values
            and value not in schema.allowed_values
        ):
            raise ConfigurationValidationError(
                f"Configuration '{schema.key}' must be "
                f"one of {schema.allowed_values}."
            )

        if (
            schema.minimum is not None
            and isinstance(value, (int, float))
            and not isinstance(value, bool)
            and value < schema.minimum
        ):
            raise ConfigurationValidationError(
                f"Configuration '{schema.key}' cannot "
                f"be less than {schema.minimum}."
            )

        if (
            schema.maximum is not None
            and isinstance(value, (int, float))
            and not isinstance(value, bool)
            and value > schema.maximum
        ):
            raise ConfigurationValidationError(
                f"Configuration '{schema.key}' cannot "
                f"be greater than {schema.maximum}."
            )

    @classmethod
    def _convert_boolean(
        cls,
        value: Any,
    ) -> bool:
        """
        Convert common boolean representations.
        """

        if isinstance(value, bool):
            return value

        if isinstance(value, int):

            if value == 1:
                return True

            if value == 0:
                return False

        normalized = str(value).strip().upper()

        if normalized in cls._TRUE_VALUES:
            return True

        if normalized in cls._FALSE_VALUES:
            return False

        raise ValueError(
            f"Unsupported boolean value: {value}"
        )

    @staticmethod
    def _convert_list(
        value: Any,
    ) -> list[Any]:
        """
        Convert a value into a list.
        """

        if isinstance(value, list):
            return list(value)

        if isinstance(value, tuple):
            return list(value)

        if isinstance(value, str):

            normalized = value.strip()

            if not normalized:
                return []

            if normalized.startswith("["):

                parsed = json.loads(
                    normalized
                )

                if not isinstance(parsed, list):
                    raise ValueError(
                        "JSON value is not a list."
                    )

                return parsed

            return [
                item.strip()
                for item in normalized.split(",")
                if item.strip()
            ]

        raise ValueError(
            "List configuration requires a list, "
            "tuple, JSON array or comma-separated string."
        )

    @staticmethod
    def _convert_dictionary(
        value: Any,
    ) -> dict[str, Any]:
        """
        Convert a value into a dictionary.
        """

        if isinstance(value, Mapping):
            return dict(value)

        if isinstance(value, str):

            parsed = json.loads(
                value
            )

            if not isinstance(parsed, dict):
                raise ValueError(
                    "JSON value is not an object."
                )

            return parsed

        raise ValueError(
            "Dictionary configuration requires a "
            "mapping or JSON object string."
        )

    # =====================================================
    # MASKING
    # =====================================================

    def _mask_value(
        self,
        schema: ConfigurationSchema,
        value: Any,
    ) -> Any:
        """
        Mask sensitive values.
        """

        if value is None:
            return None

        if schema.secret:
            return self._secret_mask

        return value

    # =====================================================
    # EVENT PUBLICATION
    # =====================================================

    def _publish_configuration_event(
        self,
        event_type: ConfigurationEventType,
        *,
        severity: EventSeverity = EventSeverity.INFO,
        payload: Mapping[str, Any] | None = None,
        correlation_id: str | None = None,
    ) -> None:
        """
        Publish a Configuration Service event safely.
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
                correlation_id=correlation_id,
            )

        except Exception as exc:

            error = (
                f"{type(exc).__name__}: {exc}"
            )

            with self._configuration_lock:

                self._event_publication_failures += 1
                self._last_error = error

            logger.exception(
                "AtlasOS Configuration event "
                "publication failed | event=%s",
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
        Normalize one configuration key.
        """

        if not isinstance(key, str):
            raise TypeError(
                "Configuration key must be a string."
            )

        normalized = key.strip().upper()

        if not normalized:
            raise ValueError(
                "Configuration key cannot be empty."
            )

        return normalized

    @classmethod
    def _flatten_mapping(
        cls,
        mapping: Mapping[str, Any],
        *,
        prefix: str = "",
    ) -> dict[str, Any]:
        """
        Flatten nested mappings using underscore-separated keys.
        """

        flattened: dict[str, Any] = {}

        for key, value in mapping.items():

            normalized_key = cls._normalize_key(
                str(key)
            )

            complete_key = (
                f"{prefix}_{normalized_key}"
                if prefix
                else normalized_key
            )

            if isinstance(value, Mapping):

                flattened.update(
                    cls._flatten_mapping(
                        value,
                        prefix=complete_key,
                    )
                )

            else:

                flattened[
                    complete_key
                ] = value

        return flattened

    def _record_load_failure(
        self,
        message: str,
    ) -> None:
        """
        Record one source-loading failure.
        """

        with self._configuration_lock:

            self._failed_loads += 1
            self._last_error = message

        logger.error(
            message
        )

    # =====================================================
    # BASE SERVICE DIAGNOSTICS
    # =====================================================

    def _health_details(
        self,
    ) -> Mapping[str, Any]:
        """
        Return Configuration Service health details.
        """

        statistics = self.statistics()

        return {
            "environment": self._environment.value,
            "strict_mode": self._strict_mode,
            "registered_keys": (
                statistics.registered_keys
            ),
            "configured_keys": (
                statistics.configured_keys
            ),
            "required_keys": (
                statistics.required_keys
            ),
            "missing_required_keys": (
                statistics.missing_required_keys
            ),
            "secret_keys": (
                statistics.secret_keys
            ),
            "json_sources": (
                statistics.json_sources
            ),
            "runtime_overrides": (
                statistics.runtime_overrides
            ),
            "successful_loads": (
                statistics.successful_loads
            ),
            "failed_loads": (
                statistics.failed_loads
            ),
            "reload_count": (
                statistics.reload_count
            ),
            "event_publication_failures": (
                statistics
                .event_publication_failures
            ),
            "last_loaded_source": (
                statistics.last_loaded_source
            ),
            "last_error": (
                statistics.last_error
            ),
        }

    def _snapshot_metadata(
        self,
    ) -> Mapping[str, Any]:
        """
        Return Configuration Service metadata.
        """

        return {
            "environment": self._environment.value,
            "strict_mode": self._strict_mode,
            "history_limit": self._history_limit,
            "secret_mask_length": len(
                self._secret_mask
            ),
            "publish_events": self._publish_events,
            "event_bus_configured": (
                self._event_bus is not None
            ),
            "source_priority": {
                source.value: priority
                for source, priority
                in self._SOURCE_PRIORITY.items()
            },
        }