"""Minimal secret-provider seam.

Domain and application logic should depend on the SecretProvider protocol,
never on where a secret value actually comes from. This module defines
that contract plus a single environment-backed adapter. Other backends
(OS keychain, Vault, a cloud secret manager) are future work and are
deliberately not implemented here; existing secret consumers are not
migrated to this contract by this change.
"""

from __future__ import annotations

import os
from typing import Protocol


class SecretNotFoundError(LookupError):
    """Raised when a requested secret has no value available."""


class SecretValue:
    """Wraps a secret so it cannot be accidentally logged or printed.

    The raw value is only reachable via reveal(); repr()/str() and
    accidental f-string interpolation always show a fixed redacted
    marker instead of the value.
    """

    __slots__ = ("_value",)

    def __init__(self, value: str) -> None:
        self._value = str(value)

    def reveal(self) -> str:
        return self._value

    def __repr__(self) -> str:
        return "SecretValue('[REDACTED]')"

    __str__ = __repr__

    def __eq__(self, other: object) -> bool:
        return isinstance(other, SecretValue) and self._value == other._value

    def __hash__(self) -> int:
        return hash(self._value)


class SecretProvider(Protocol):
    """Contract implemented by every secret-source adapter."""

    def get_secret(self, name: str) -> SecretValue:
        """Return the named secret, or raise SecretNotFoundError."""
        ...


class EnvironmentSecretProvider:
    """Reads secrets from process environment variables.

    This adapter never reads or writes .env files; loading .env into the
    process environment (if used at all) remains a deployment concern
    outside this module.
    """

    def __init__(self, *, prefix: str = "") -> None:
        self._prefix = prefix

    def get_secret(self, name: str) -> SecretValue:
        env_name = f"{self._prefix}{name}"
        value = os.environ.get(env_name)
        if value is None:
            raise SecretNotFoundError(env_name)
        return SecretValue(value)
