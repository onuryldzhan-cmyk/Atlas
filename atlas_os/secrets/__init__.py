"""
AtlasOS Secrets Manager package.
"""

from atlas_os.secrets.secrets_manager import (
    DuplicateSecretError,
    SecretAccessDeniedError,
    SecretAccessRecord,
    SecretChangeRecord,
    SecretDefinition,
    SecretEventType,
    SecretExpiredError,
    SecretMetadata,
    SecretNotFoundError,
    SecretRevokedError,
    SecretsManager,
    SecretsManagerError,
    SecretsManagerSnapshot,
    SecretsManagerStatistics,
    SecretSource,
    SecretStatus,
    SecretValidationError,
    SecretValueMissingError,
)

__all__ = [
    "DuplicateSecretError",
    "SecretAccessDeniedError",
    "SecretAccessRecord",
    "SecretChangeRecord",
    "SecretDefinition",
    "SecretEventType",
    "SecretExpiredError",
    "SecretMetadata",
    "SecretNotFoundError",
    "SecretRevokedError",
    "SecretsManager",
    "SecretsManagerError",
    "SecretsManagerSnapshot",
    "SecretsManagerStatistics",
    "SecretSource",
    "SecretStatus",
    "SecretValidationError",
    "SecretValueMissingError",
]
