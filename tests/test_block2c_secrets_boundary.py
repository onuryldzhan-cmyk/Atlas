"""Block 2C Part B: minimal secrets-provider seam.

Covers H5 / P4 from the Block 2C work order: secrets are never exposed in
repr()/str() or through the existing atlas_security sanitization path.
"""

from __future__ import annotations

import pytest

from atlas_security import sanitize_sensitive_data
from core.secret_provider import (
    EnvironmentSecretProvider,
    SecretNotFoundError,
    SecretValue,
)

RAW_SECRET = "sk-super-secret-value-does-not-belong-in-logs"


def test_secret_value_repr_never_shows_raw_value():
    value = SecretValue(RAW_SECRET)
    assert RAW_SECRET not in repr(value)
    assert repr(value) == "SecretValue('[REDACTED]')"


def test_secret_value_str_never_shows_raw_value():
    value = SecretValue(RAW_SECRET)
    assert RAW_SECRET not in str(value)
    assert RAW_SECRET not in f"{value}"


def test_secret_value_reveal_returns_raw_value():
    value = SecretValue(RAW_SECRET)
    assert value.reveal() == RAW_SECRET


def test_secret_value_sanitized_by_atlas_security_authority():
    value = SecretValue(RAW_SECRET)
    sanitized = sanitize_sensitive_data({"credential": value})
    assert RAW_SECRET not in str(sanitized)


def test_environment_secret_provider_reads_set_variable(monkeypatch):
    monkeypatch.setenv("ATLAS_TEST_SECRET_XYZ", RAW_SECRET)
    provider = EnvironmentSecretProvider()
    secret = provider.get_secret("ATLAS_TEST_SECRET_XYZ")
    assert isinstance(secret, SecretValue)
    assert secret.reveal() == RAW_SECRET


def test_environment_secret_provider_missing_variable_raises_clearly(monkeypatch):
    monkeypatch.delenv("ATLAS_TEST_SECRET_MISSING", raising=False)
    provider = EnvironmentSecretProvider()
    with pytest.raises(SecretNotFoundError, match="ATLAS_TEST_SECRET_MISSING"):
        provider.get_secret("ATLAS_TEST_SECRET_MISSING")


def test_environment_secret_provider_honors_prefix(monkeypatch):
    monkeypatch.setenv("ATLAS_PREFIX_TOKEN", RAW_SECRET)
    provider = EnvironmentSecretProvider(prefix="ATLAS_PREFIX_")
    secret = provider.get_secret("TOKEN")
    assert secret.reveal() == RAW_SECRET
