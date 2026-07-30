"""
============================================================
ATLAS OS SECRETS MANAGER TEST SUITE v1.0
============================================================

Tests
-----
- Secret registration
- Secret storage and retrieval
- Secret masking
- Required secret validation
- Minimum length validation
- Caller authorization
- Secret rotation
- Secret revocation
- Secret removal
- Secret generation
- Environment loading
- Access history
- Change history
- Snapshot safety
- Statistics
- Service lifecycle

============================================================
"""

from __future__ import annotations

import os
import unittest

from unittest.mock import patch

from atlas_os.secrets import (
    DuplicateSecretError,
    SecretAccessDeniedError,
    SecretExpiredError,
    SecretNotFoundError,
    SecretRevokedError,
    SecretsManager,
    SecretSource,
    SecretStatus,
    SecretValidationError,
    SecretValueMissingError,
)


class SecretsManagerTestCase(unittest.TestCase):
    """
    AtlasOS SecretsManager unit tests.
    """

    def setUp(self) -> None:
        """
        Create a fresh SecretsManager for every test.
        """

        self.manager = SecretsManager(
            history_limit=100,
            access_history_limit=100,
            publish_events=False,
        )

    def tearDown(self) -> None:
        """
        Stop the manager when necessary.
        """

        if self.manager.is_running:
            self.manager.stop()

    # =====================================================
    # REGISTRATION
    # =====================================================

    def test_register_secret_definition(self) -> None:

        definition = self.manager.register(
            "BINANCE_API_KEY",
            description="Binance API key",
            required=True,
            minimum_length=8,
        )

        self.assertEqual(
            definition.key,
            "BINANCE_API_KEY",
        )

        self.assertTrue(
            definition.required
        )

        self.assertEqual(
            definition.minimum_length,
            8,
        )

        self.assertEqual(
            definition.environment_variable,
            "BINANCE_API_KEY",
        )

    def test_register_normalizes_key(self) -> None:

        definition = self.manager.register(
            "  binance_secret  "
        )

        self.assertEqual(
            definition.key,
            "BINANCE_SECRET",
        )

    def test_duplicate_registration_raises(self) -> None:

        self.manager.register(
            "API_KEY"
        )

        with self.assertRaises(
            DuplicateSecretError
        ):
            self.manager.register(
                "API_KEY"
            )

    def test_registration_can_be_replaced(self) -> None:

        self.manager.register(
            "API_KEY",
            description="Version one",
        )

        definition = self.manager.register(
            "API_KEY",
            description="Version two",
            replace=True,
        )

        self.assertEqual(
            definition.description,
            "Version two",
        )

    # =====================================================
    # STORAGE AND RETRIEVAL
    # =====================================================

    def test_set_and_get_secret(self) -> None:

        self.manager.register(
            "API_KEY",
            minimum_length=8,
        )

        metadata = self.manager.set_secret(
            "API_KEY",
            "atlas-api-key",
        )

        value = self.manager.get_secret(
            "API_KEY"
        )

        self.assertEqual(
            value,
            "atlas-api-key",
        )

        self.assertTrue(
            metadata.configured
        )

        self.assertEqual(
            metadata.status,
            SecretStatus.ACTIVE,
        )

        self.assertEqual(
            metadata.source,
            SecretSource.RUNTIME,
        )

    def test_unknown_secret_raises(self) -> None:

        with self.assertRaises(
            SecretNotFoundError
        ):
            self.manager.get_secret(
                "UNKNOWN_SECRET"
            )

    def test_registered_secret_without_value_raises(
        self,
    ) -> None:

        self.manager.register(
            "EMPTY_SECRET"
        )

        with self.assertRaises(
            SecretValueMissingError
        ):
            self.manager.get_secret(
                "EMPTY_SECRET"
            )

    def test_non_string_value_is_rejected(self) -> None:

        self.manager.register(
            "API_KEY"
        )

        with self.assertRaises(
            SecretValidationError
        ):
            self.manager.set_secret(
                "API_KEY",
                12345,  # type: ignore[arg-type]
            )

    def test_minimum_length_is_enforced(self) -> None:

        self.manager.register(
            "API_KEY",
            minimum_length=10,
        )

        with self.assertRaises(
            SecretValidationError
        ):
            self.manager.set_secret(
                "API_KEY",
                "short",
            )

    # =====================================================
    # MASKING AND SNAPSHOTS
    # =====================================================

    def test_metadata_masks_secret(self) -> None:

        self.manager.register(
            "API_SECRET"
        )

        self.manager.set_secret(
            "API_SECRET",
            "never-display-this",
        )

        metadata = self.manager.metadata(
            "API_SECRET"
        )

        self.assertEqual(
            metadata.masked_value,
            "********",
        )

        self.assertNotIn(
            "never-display-this",
            str(metadata),
        )

    def test_snapshot_does_not_expose_plain_secret(
        self,
    ) -> None:

        plain_value = "super-secret-atlas-value"

        self.manager.register(
            "PRIVATE_SECRET"
        )

        self.manager.set_secret(
            "PRIVATE_SECRET",
            plain_value,
        )

        snapshot = self.manager.secrets_snapshot()

        self.assertNotIn(
            plain_value,
            str(snapshot),
        )

        self.assertEqual(
            snapshot.secrets[0].masked_value,
            "********",
        )

    def test_masked_mapping_contains_no_plain_values(
        self,
    ) -> None:

        self.manager.register(
            "TOKEN"
        )

        self.manager.set_secret(
            "TOKEN",
            "plain-token-value",
        )

        mapping = self.manager.masked_mapping()

        self.assertEqual(
            mapping["TOKEN"],
            "********",
        )

        self.assertNotIn(
            "plain-token-value",
            str(mapping),
        )

    # =====================================================
    # REQUIRED SECRET VALIDATION
    # =====================================================

    def test_missing_required_secret_invalidates_manager(
        self,
    ) -> None:

        self.manager.register(
            "REQUIRED_SECRET",
            required=True,
        )

        self.assertFalse(
            self.manager.validate(
                raise_on_error=False
            )
        )

        self.assertEqual(
            self.manager.missing_required_secrets(),
            ("REQUIRED_SECRET",),
        )

    def test_missing_required_secret_raises(
        self,
    ) -> None:

        self.manager.register(
            "REQUIRED_SECRET",
            required=True,
        )

        with self.assertRaises(
            SecretValidationError
        ):
            self.manager.validate()

    def test_configured_required_secret_is_valid(
        self,
    ) -> None:

        self.manager.register(
            "REQUIRED_SECRET",
            required=True,
        )

        self.manager.set_secret(
            "REQUIRED_SECRET",
            "configured-value",
        )

        self.assertTrue(
            self.manager.validate()
        )

        self.assertEqual(
            self.manager.missing_required_secrets(),
            (),
        )

    # =====================================================
    # ACCESS CONTROL
    # =====================================================

    def test_authorized_caller_can_access_secret(
        self,
    ) -> None:

        self.manager.register(
            "EXECUTION_KEY",
            allowed_callers=(
                "ExecutionService",
            ),
        )

        self.manager.set_secret(
            "EXECUTION_KEY",
            "execution-secret",
            caller="ExecutionService",
        )

        value = self.manager.get_secret(
            "EXECUTION_KEY",
            caller="ExecutionService",
        )

        self.assertEqual(
            value,
            "execution-secret",
        )

    def test_unauthorized_caller_is_denied(
        self,
    ) -> None:

        self.manager.register(
            "EXECUTION_KEY",
            allowed_callers=(
                "ExecutionService",
            ),
        )

        self.manager.set_secret(
            "EXECUTION_KEY",
            "execution-secret",
            caller="ExecutionService",
        )

        with self.assertRaises(
            SecretAccessDeniedError
        ):
            self.manager.get_secret(
                "EXECUTION_KEY",
                caller="UnknownService",
            )

        statistics = self.manager.statistics()

        self.assertEqual(
            statistics.denied_accesses,
            1,
        )

    # =====================================================
    # ROTATION
    # =====================================================

    def test_rotate_secret(self) -> None:

        self.manager.register(
            "ROTATING_TOKEN",
            minimum_length=8,
        )

        self.manager.set_secret(
            "ROTATING_TOKEN",
            "first-token",
        )

        metadata = self.manager.rotate_secret(
            "ROTATING_TOKEN",
            "second-token",
        )

        self.assertEqual(
            metadata.version,
            2,
        )

        self.assertEqual(
            metadata.rotation_count,
            1,
        )

        self.assertEqual(
            self.manager.get_secret(
                "ROTATING_TOKEN"
            ),
            "second-token",
        )

    def test_rotation_rejects_same_value(self) -> None:

        self.manager.register(
            "ROTATING_TOKEN"
        )

        self.manager.set_secret(
            "ROTATING_TOKEN",
            "same-token",
        )

        with self.assertRaises(
            SecretValidationError
        ):
            self.manager.rotate_secret(
                "ROTATING_TOKEN",
                "same-token",
            )

    # =====================================================
    # REVOCATION AND REMOVAL
    # =====================================================

    def test_revoke_secret(self) -> None:

        self.manager.register(
            "REVOKE_KEY"
        )

        self.manager.set_secret(
            "REVOKE_KEY",
            "revoke-secret",
        )

        result = self.manager.revoke_secret(
            "REVOKE_KEY"
        )

        self.assertTrue(result)

        self.assertEqual(
            self.manager.metadata(
                "REVOKE_KEY"
            ).status,
            SecretStatus.REVOKED,
        )

        with self.assertRaises(
            SecretRevokedError
        ):
            self.manager.get_secret(
                "REVOKE_KEY"
            )

    def test_remove_secret_preserves_definition(
        self,
    ) -> None:

        self.manager.register(
            "REMOVE_KEY"
        )

        self.manager.set_secret(
            "REMOVE_KEY",
            "remove-secret",
        )

        result = self.manager.remove_secret(
            "REMOVE_KEY"
        )

        self.assertTrue(result)

        metadata = self.manager.metadata(
            "REMOVE_KEY"
        )

        self.assertFalse(
            metadata.configured
        )

        self.assertEqual(
            metadata.status,
            SecretStatus.MISSING,
        )

    # =====================================================
    # GENERATION
    # =====================================================

    def test_generate_secret(self) -> None:

        self.manager.register(
            "GENERATED_KEY",
            minimum_length=16,
        )

        metadata = self.manager.generate_secret(
            "GENERATED_KEY",
            length=32,
        )

        value = self.manager.get_secret(
            "GENERATED_KEY"
        )

        self.assertTrue(
            len(value) >= 32
        )

        self.assertEqual(
            metadata.source,
            SecretSource.GENERATED,
        )

        self.assertEqual(
            self.manager.statistics().generated_secrets,
            1,
        )

    def test_generate_secret_rejects_short_length(
        self,
    ) -> None:

        self.manager.register(
            "GENERATED_KEY"
        )

        with self.assertRaises(
            ValueError
        ):
            self.manager.generate_secret(
                "GENERATED_KEY",
                length=8,
            )

    # =====================================================
    # ENVIRONMENT
    # =====================================================

    def test_load_environment_secret(self) -> None:

        self.manager.register(
            "BINANCE_SECRET",
            environment_variable=(
                "ATLAS_TEST_BINANCE_SECRET"
            ),
            required=True,
        )

        with patch.dict(
            os.environ,
            {
                "ATLAS_TEST_BINANCE_SECRET": (
                    "environment-secret"
                )
            },
            clear=False,
        ):

            loaded = (
                self.manager.load_environment()
            )

        self.assertEqual(
            loaded,
            1,
        )

        self.assertEqual(
            self.manager.get_secret(
                "BINANCE_SECRET"
            ),
            "environment-secret",
        )

        self.assertEqual(
            self.manager.metadata(
                "BINANCE_SECRET"
            ).source,
            SecretSource.ENVIRONMENT,
        )

    def test_missing_required_environment_raises(
        self,
    ) -> None:

        self.manager.register(
            "MISSING_ENV_SECRET",
            environment_variable=(
                "ATLAS_NON_EXISTENT_SECRET"
            ),
            required=True,
        )

        with patch.dict(
            os.environ,
            {},
            clear=True,
        ):

            with self.assertRaises(
                SecretValueMissingError
            ):
                self.manager.load_environment(
                    ignore_missing=False
                )

    # =====================================================
    # HISTORY
    # =====================================================

    def test_access_history_records_reads_and_writes(
        self,
    ) -> None:

        self.manager.register(
            "HISTORY_KEY"
        )

        self.manager.set_secret(
            "HISTORY_KEY",
            "history-secret",
            caller="TestWriter",
        )

        self.manager.get_secret(
            "HISTORY_KEY",
            caller="TestReader",
        )

        records = self.manager.access_history(
            key="HISTORY_KEY"
        )

        operations = {
            record.operation
            for record in records
        }

        self.assertIn(
            "WRITE",
            operations,
        )

        self.assertIn(
            "READ",
            operations,
        )

    def test_change_history_records_lifecycle(
        self,
    ) -> None:

        self.manager.register(
            "CHANGE_KEY"
        )

        self.manager.set_secret(
            "CHANGE_KEY",
            "first-secret",
        )

        self.manager.rotate_secret(
            "CHANGE_KEY",
            "second-secret",
        )

        records = self.manager.change_history(
            key="CHANGE_KEY"
        )

        operations = {
            record.operation
            for record in records
        }

        self.assertIn(
            "STORE",
            operations,
        )

        self.assertIn(
            "ROTATE",
            operations,
        )

    # =====================================================
    # STATISTICS
    # =====================================================

    def test_statistics(self) -> None:

        self.manager.register(
            "ACTIVE_KEY",
            required=True,
        )

        self.manager.register(
            "MISSING_KEY",
            required=True,
        )

        self.manager.set_secret(
            "ACTIVE_KEY",
            "active-secret",
        )

        statistics = self.manager.statistics()

        self.assertEqual(
            statistics.registered_secrets,
            2,
        )

        self.assertEqual(
            statistics.configured_secrets,
            1,
        )

        self.assertEqual(
            statistics.required_secrets,
            2,
        )

        self.assertEqual(
            statistics.missing_required_secrets,
            1,
        )

        self.assertEqual(
            statistics.active_secrets,
            1,
        )

    # =====================================================
    # SERVICE LIFECYCLE
    # =====================================================

    def test_service_start_and_stop(self) -> None:

        self.manager.register(
            "OPTIONAL_SECRET"
        )

        self.manager.start()

        self.assertTrue(
            self.manager.is_running
        )

        self.manager.stop()

        self.assertFalse(
            self.manager.is_running
        )

    def test_service_snapshot(self) -> None:

        self.manager.register(
            "SNAPSHOT_KEY"
        )

        self.manager.set_secret(
            "SNAPSHOT_KEY",
            "snapshot-secret",
        )

        snapshot = self.manager.snapshot()

        self.assertEqual(
            snapshot.identity.name,
            "AtlasOSSecretsManager",
        )


if __name__ == "__main__":
    unittest.main(
        verbosity=2
    )