"""
AtlasOS integration package.

Public integration contracts and service bridges.
"""

from atlas_os.integration.configuration_secrets_bridge import (
    ConfigurationReaderProtocol,
    ConfigurationSecretsBridge,
    ConfigurationSecretsBridgeError,
    ConfigurationSecretsSnapshot,
    ConfigurationValueNotFoundError,
    SecretBinding,
    SecretBindingMode,
    SecretBindingNotFoundError,
    SecretBindingRegistrationError,
    SecretBindingResult,
    SecretBindingStatus,
    UnsafeSecretConfigurationError,
)

__all__ = [
    "ConfigurationReaderProtocol",
    "ConfigurationSecretsBridge",
    "ConfigurationSecretsBridgeError",
    "ConfigurationSecretsSnapshot",
    "ConfigurationValueNotFoundError",
    "SecretBinding",
    "SecretBindingMode",
    "SecretBindingNotFoundError",
    "SecretBindingRegistrationError",
    "SecretBindingResult",
    "SecretBindingStatus",
    "UnsafeSecretConfigurationError",
]