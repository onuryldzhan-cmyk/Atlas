"""
============================================================
ATLAS OS CONFIGURATION-SECRETS SERVICE v1.0.0
============================================================

Project
-------
Project Atlas AI

Package
-------
atlas_os.integration

Purpose
-------
Provide a lifecycle-managed AtlasOS service around the secure
ConfigurationSecretsBridge.

Responsibilities
----------------
- Integrate ConfigurationService with SecretsManager
- Resolve registered secret bindings during service startup
- Validate required secrets before dependent services start
- Prevent unsafe startup when required secrets are unresolved
- Expose safe lifecycle health information
- Produce metadata without plaintext secret values
- Support AtlasOS Kernel dependency orchestration
- Preserve strict separation between configuration and secrets

Architecture
------------
ConfigurationService
        |
        v
ConfigurationSecretsBridge
        |
        v
ConfigurationSecretsService
        |
        v
SecretsManager

Kernel lifecycle
----------------
ConfigurationService
        |
        v
SecretsManager
        |
        v
ConfigurationSecretsService
        |
        v
Exchange / Execution / External API services

Security guarantees
-------------------
- Plaintext secret values are never written to service snapshots
- Plaintext secret values are never included in health details
- Plaintext secret values are never logged by this service
- Required unresolved bindings block service startup
- Configuration references are resolved through the bridge
- SecretsManager remains the authoritative runtime secret store

============================================================
"""

from __future__ import annotations

import inspect
import logging

from datetime import UTC
from datetime import datetime
from threading import RLock
from typing import Any
from typing import Mapping

from atlas_os.configuration import ConfigurationService
from atlas_os.contracts import ServiceIdentity
from atlas_os.integration.configuration_secrets_bridge import (
    ConfigurationSecretsBridge,
    ConfigurationSecretsSnapshot,
    SecretBinding,
    SecretBindingResult,
)
from atlas_os.secrets import SecretsManager
from atlas_os.services import BaseAtlasService


logger = logging.getLogger(
    "AtlasOS.ConfigurationSecretsService"
)


# =========================================================
# EXCEPTIONS
# =========================================================


class ConfigurationSecretsServiceError(
    RuntimeError
):
    """
    Base exception for configuration-secrets lifecycle failures.
    """


class ConfigurationServiceUnavailableError(
    ConfigurationSecretsServiceError
):
    """
    Raised when ConfigurationService is not ready.
    """


class SecretsManagerUnavailableError(
    ConfigurationSecretsServiceError
):
    """
    Raised when SecretsManager is not ready.
    """


class RequiredSecretResolutionError(
    ConfigurationSecretsServiceError
):
    """
    Raised when one or more required secrets cannot be resolved.
    """


class ConfigurationSecretsValidationError(
    ConfigurationSecretsServiceError
):
    """
    Raised when bridge validation fails.
    """


# =========================================================
# SERVICE
# =========================================================


class ConfigurationSecretsService(
    BaseAtlasService
):
    """
    Lifecycle-managed configuration-to-secrets integration service.

    This class does not own ConfigurationService or SecretsManager
    lifecycle. Those services must be registered separately with
    AtlasOS Kernel and declared as dependencies of this service.

    During startup, the service:

    1. Verifies ConfigurationService readiness.
    2. Verifies SecretsManager readiness.
    3. Loads all registered bridge bindings.
    4. Validates required bindings.
    5. Refuses to enter RUNNING state if validation fails.

    No plaintext secret values are exposed through service health,
    snapshots, logs, or metadata.
    """

    VERSION = "1.0.0"

    NAME = "ConfigurationSecretsService"

    SERVICE_NAME = "configuration-secrets-service"

    DESCRIPTION = (
        "Lifecycle-managed secure integration between "
        "ConfigurationService and SecretsManager."
    )

    DEFAULT_CALLER = (
        "AtlasOSConfigurationSecretsService"
    )

    def __init__(
        self,
        configuration_service: ConfigurationService,
        secrets_manager: SecretsManager,
        *,
        bridge: ConfigurationSecretsBridge | None = None,
        continue_on_error: bool = False,
        validate_on_start: bool = True,
        require_running_dependencies: bool = True,
        reject_plaintext_configuration: bool = True,
        caller: str = DEFAULT_CALLER,
        identity: ServiceIdentity | None = None,
    ) -> None:
        """
        Initialize the lifecycle service.

        Parameters
        ----------
        configuration_service:
            AtlasOS ConfigurationService instance.

        secrets_manager:
            AtlasOS SecretsManager instance.

        bridge:
            Optional preconfigured ConfigurationSecretsBridge.
            When omitted, a bridge is created automatically.

        continue_on_error:
            Whether bridge loading should continue after an individual
            binding failure. Required unresolved bindings still prevent
            successful service startup.

        validate_on_start:
            Whether bridge validation is enforced during startup.

        require_running_dependencies:
            Whether ConfigurationService and SecretsManager must already
            be running before this service starts.

        reject_plaintext_configuration:
            Forwarded to an automatically created bridge.

        caller:
            Runtime identity used when loading and accessing secrets.

        identity:
            Optional custom ServiceIdentity.
        """

        if not isinstance(
            configuration_service,
            ConfigurationService,
        ):
            raise TypeError(
                "configuration_service must be an instance "
                "of ConfigurationService."
            )

        if not isinstance(
            secrets_manager,
            SecretsManager,
        ):
            raise TypeError(
                "secrets_manager must be an instance "
                "of SecretsManager."
            )

        normalized_caller = str(
            caller
        ).strip()

        if not normalized_caller:
            raise ValueError(
                "caller cannot be empty."
            )

        if bridge is None:
            resolved_bridge = (
                ConfigurationSecretsBridge(
                    configuration_service,
                    secrets_manager,
                    reject_plaintext_configuration=(
                        reject_plaintext_configuration
                    ),
                )
            )
        else:
            if not isinstance(
                bridge,
                ConfigurationSecretsBridge,
            ):
                raise TypeError(
                    "bridge must be an instance of "
                    "ConfigurationSecretsBridge."
                )

            if (
                bridge.configuration_service
                is not configuration_service
            ):
                raise ValueError(
                    "bridge.configuration_service does not "
                    "match configuration_service."
                )

            if (
                bridge.secrets_manager
                is not secrets_manager
            ):
                raise ValueError(
                    "bridge.secrets_manager does not match "
                    "secrets_manager."
                )

            resolved_bridge = bridge

        service_identity = (
            identity
            if identity is not None
            else self._create_service_identity()
        )

        super().__init__(
            service_identity
        )

        self.configuration_service = (
            configuration_service
        )

        self.secrets_manager = (
            secrets_manager
        )

        self.bridge = resolved_bridge

        self.continue_on_error = bool(
            continue_on_error
        )

        self.validate_on_start = bool(
            validate_on_start
        )

        self.require_running_dependencies = bool(
            require_running_dependencies
        )

        self.caller = normalized_caller

        self._lock = RLock()

        self._last_bridge_snapshot: (
            ConfigurationSecretsSnapshot | None
        ) = None

        self._last_load_results: tuple[
            SecretBindingResult,
            ...,
        ] = ()

        self._last_loaded_at: datetime | None = None

        self._last_validated_at: datetime | None = None

        self._last_validation_result: bool | None = None

        self._load_count = 0

        self._validation_count = 0

        self._startup_failure_count = 0

        logger.info(
            "%s v%s initialized.",
            self.NAME,
            self.VERSION,
        )

    # =====================================================
    # IDENTITY
    # =====================================================

    @classmethod
    def _create_service_identity(
        cls,
    ) -> ServiceIdentity:
        """
        Build ServiceIdentity using the installed AtlasOS contract.

        AtlasOS service identity contracts may evolve by gaining
        optional metadata fields. This factory forwards only fields
        supported by the active ServiceIdentity constructor.
        """

        supported_values: dict[str, Any] = {
            "name": cls.SERVICE_NAME,
            "service_name": cls.SERVICE_NAME,
            "version": cls.VERSION,
            "description": cls.DESCRIPTION,
            "component": cls.NAME,
            "service_type": "INTEGRATION",
            "critical": True,
            "metadata": {
                "component": cls.NAME,
                "category": "SECURITY_INTEGRATION",
                "plaintext_exposure_allowed": False,
            },
        }

        signature = inspect.signature(
            ServiceIdentity
        )

        kwargs: dict[str, Any] = {}

        for parameter_name, parameter in (
            signature.parameters.items()
        ):
            if parameter_name in supported_values:
                kwargs[parameter_name] = (
                    supported_values[
                        parameter_name
                    ]
                )
                continue

            if (
                parameter.default
                is inspect.Parameter.empty
            ):
                raise TypeError(
                    "Unsupported required ServiceIdentity "
                    f"parameter: {parameter_name!r}. "
                    "Update ConfigurationSecretsService "
                    "identity factory."
                )

        return ServiceIdentity(
            **kwargs
        )

    # =====================================================
    # PUBLIC API
    # =====================================================

    def register_binding(
        self,
        binding: SecretBinding,
        *,
        replace: bool = False,
    ) -> SecretBinding:
        """
        Register a complete bridge binding.
        """

        with self._lock:
            return self.bridge.register_binding(
                binding,
                replace=replace,
            )

    def register_secret(
        self,
        secret_key: str,
        **kwargs: Any,
    ) -> SecretBinding:
        """
        Register a bridge secret binding.

        Keyword arguments are forwarded to
        ConfigurationSecretsBridge.register().
        """

        with self._lock:
            return self.bridge.register(
                secret_key,
                **kwargs,
            )

    def reload(
        self,
        *,
        continue_on_error: bool | None = None,
        validate: bool = True,
    ) -> tuple[SecretBindingResult, ...]:
        """
        Reload all registered secret bindings.

        This operation never includes plaintext values in its result.
        """

        effective_continue_on_error = (
            self.continue_on_error
            if continue_on_error is None
            else bool(
                continue_on_error
            )
        )

        with self._lock:
            self._assert_dependencies_ready()

            results = self.bridge.load_all(
                caller=self.caller,
                continue_on_error=(
                    effective_continue_on_error
                ),
            )

            self._last_load_results = tuple(
                results
            )

            self._last_loaded_at = datetime.now(
                UTC
            )

            self._load_count += 1

            self._refresh_bridge_snapshot()

            if validate:
                self.validate_bindings(
                    raise_on_error=True
                )

            return self._last_load_results

    def validate_bindings(
        self,
        *,
        raise_on_error: bool = True,
    ) -> bool:
        """
        Validate bridge bindings and required secret resolution.
        """

        with self._lock:
            self._validation_count += 1

            self._last_validated_at = datetime.now(
                UTC
            )

            try:
                valid = bool(
                    self.bridge.validate(
                        raise_on_error=raise_on_error
                    )
                )
            except Exception:
                self._last_validation_result = False
                self._refresh_bridge_snapshot()
                raise

            self._last_validation_result = valid

            self._refresh_bridge_snapshot()

            unresolved = (
                self.bridge
                .unresolved_required_bindings()
            )

            if unresolved:
                self._last_validation_result = False

                message = (
                    "Required secret bindings are unresolved: "
                    + ", ".join(
                        unresolved
                    )
                )

                if raise_on_error:
                    raise RequiredSecretResolutionError(
                        message
                    )

                return False

            if not valid and raise_on_error:
                raise ConfigurationSecretsValidationError(
                    "Configuration-secrets bridge validation "
                    "failed."
                )

            return valid

    def secure_snapshot(
        self,
    ) -> ConfigurationSecretsSnapshot:
        """
        Return the bridge's safe masked snapshot.
        """

        with self._lock:
            return self._refresh_bridge_snapshot()

    def unresolved_required_bindings(
        self,
    ) -> tuple[str, ...]:
        """
        Return unresolved required binding names.
        """

        with self._lock:
            return (
                self.bridge
                .unresolved_required_bindings()
            )

    # =====================================================
    # LIFECYCLE
    # =====================================================

    def _on_start(
        self,
    ) -> None:
        """
        Load and validate all registered secret bindings.
        """

        logger.info(
            "%s startup initiated.",
            self.NAME,
        )

        try:
            self._assert_dependencies_ready()

            self.reload(
                continue_on_error=(
                    self.continue_on_error
                ),
                validate=self.validate_on_start,
            )

            if not self.validate_on_start:
                self._refresh_bridge_snapshot()

            logger.info(
                "%s started securely. "
                "Loaded bindings: %s.",
                self.NAME,
                len(
                    self._last_load_results
                ),
            )

        except Exception:
            with self._lock:
                self._startup_failure_count += 1

                self._last_validation_result = False

                self._refresh_bridge_snapshot()

            logger.exception(
                "%s startup failed.",
                self.NAME,
            )

            raise

    def _on_stop(
        self,
    ) -> None:
        """
        Stop the integration service.

        Secret values remain owned by SecretsManager. This service
        does not remove or expose them during shutdown.
        """

        with self._lock:
            self._refresh_bridge_snapshot()

        logger.info(
            "%s stopped.",
            self.NAME,
        )

    # =====================================================
    # DEPENDENCY VALIDATION
    # =====================================================

    def _assert_dependencies_ready(
        self,
    ) -> None:
        """
        Ensure required services are available and optionally running.
        """

        if self.configuration_service is None:
            raise ConfigurationServiceUnavailableError(
                "ConfigurationService is unavailable."
            )

        if self.secrets_manager is None:
            raise SecretsManagerUnavailableError(
                "SecretsManager is unavailable."
            )

        if not self.require_running_dependencies:
            return

        if not self.configuration_service.is_running:
            raise ConfigurationServiceUnavailableError(
                "ConfigurationService must be running before "
                "ConfigurationSecretsService starts."
            )

        if not self.secrets_manager.is_running:
            raise SecretsManagerUnavailableError(
                "SecretsManager must be running before "
                "ConfigurationSecretsService starts."
            )

    # =====================================================
    # OBSERVABILITY
    # =====================================================

    def _refresh_bridge_snapshot(
        self,
    ) -> ConfigurationSecretsSnapshot:
        """
        Refresh and retain the current safe bridge snapshot.
        """

        snapshot = self.bridge.snapshot()

        if snapshot.plaintext_values_exposed:
            raise ConfigurationSecretsServiceError(
                "Bridge snapshot reports plaintext exposure."
            )

        self._last_bridge_snapshot = snapshot

        return snapshot

    def _health_details(
        self,
    ) -> Mapping[str, Any]:
        """
        Return plaintext-safe service health details.
        """

        with self._lock:
            snapshot = (
                self._last_bridge_snapshot
                or self._refresh_bridge_snapshot()
            )

            unresolved = (
                self.bridge
                .unresolved_required_bindings()
            )

            return {
                "version": self.VERSION,
                "configuration_service_running": (
                    self.configuration_service.is_running
                ),
                "secrets_manager_running": (
                    self.secrets_manager.is_running
                ),
                "total_bindings": (
                    snapshot.total_bindings
                ),
                "loaded_bindings": (
                    snapshot.loaded_bindings
                ),
                "missing_bindings": (
                    snapshot.missing_bindings
                ),
                "invalid_bindings": (
                    snapshot.invalid_bindings
                ),
                "skipped_bindings": (
                    snapshot.skipped_bindings
                ),
                "required_bindings": (
                    snapshot.required_bindings
                ),
                "unresolved_required_bindings": (
                    unresolved
                ),
                "unresolved_required_count": len(
                    unresolved
                ),
                "last_validation_result": (
                    self._last_validation_result
                ),
                "last_loaded_at": (
                    self._to_isoformat(
                        self._last_loaded_at
                    )
                ),
                "last_validated_at": (
                    self._to_isoformat(
                        self._last_validated_at
                    )
                ),
                "plaintext_values_exposed": False,
            }

    def _snapshot_metadata(
        self,
    ) -> Mapping[str, Any]:
        """
        Return plaintext-safe lifecycle snapshot metadata.
        """

        with self._lock:
            snapshot = (
                self._last_bridge_snapshot
                or self._refresh_bridge_snapshot()
            )

            unresolved = (
                self.bridge
                .unresolved_required_bindings()
            )

            return {
                "service_version": self.VERSION,
                "caller": self.caller,
                "continue_on_error": (
                    self.continue_on_error
                ),
                "validate_on_start": (
                    self.validate_on_start
                ),
                "require_running_dependencies": (
                    self.require_running_dependencies
                ),
                "total_bindings": (
                    snapshot.total_bindings
                ),
                "loaded_bindings": (
                    snapshot.loaded_bindings
                ),
                "missing_bindings": (
                    snapshot.missing_bindings
                ),
                "invalid_bindings": (
                    snapshot.invalid_bindings
                ),
                "skipped_bindings": (
                    snapshot.skipped_bindings
                ),
                "required_bindings": (
                    snapshot.required_bindings
                ),
                "unresolved_required_bindings": (
                    unresolved
                ),
                "load_count": self._load_count,
                "validation_count": (
                    self._validation_count
                ),
                "startup_failure_count": (
                    self._startup_failure_count
                ),
                "last_validation_result": (
                    self._last_validation_result
                ),
                "last_loaded_at": (
                    self._to_isoformat(
                        self._last_loaded_at
                    )
                ),
                "last_validated_at": (
                    self._to_isoformat(
                        self._last_validated_at
                    )
                ),
                "masked_secrets": dict(
                    snapshot.masked_secrets
                ),
                "plaintext_values_exposed": False,
            }

    # =====================================================
    # UTILITIES
    # =====================================================

    @staticmethod
    def _to_isoformat(
        value: datetime | None,
    ) -> str | None:
        """
        Convert an optional datetime to ISO-8601.
        """

        return (
            value.isoformat()
            if value is not None
            else None
        )


__all__ = [
    "ConfigurationSecretsService",
    "ConfigurationSecretsServiceError",
    "ConfigurationServiceUnavailableError",
    "SecretsManagerUnavailableError",
    "RequiredSecretResolutionError",
    "ConfigurationSecretsValidationError",
]