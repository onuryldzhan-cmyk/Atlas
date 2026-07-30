from atlas_os import (
    ConfigurationService,
    SecretsManager,
    SecretBindingMode,
)

from atlas_os.integration.configuration_secrets_service import (
    ConfigurationSecretsService,
)


configuration = ConfigurationService()
secrets = SecretsManager()

service = ConfigurationSecretsService(
    configuration,
    secrets,
)

service.register_secret(
    "BINANCE_API_KEY",
    mode=SecretBindingMode.ENVIRONMENT,
    environment_variable="ATLAS_TEST_API_KEY",
    required=True,
    minimum_length=8,
)

configuration.start()
secrets.start()
service.start()

secure_snapshot = service.secure_snapshot()
service_snapshot = service.snapshot()
health = service.health()

print("SERVICE STATE:", service.state.value)
print("SERVICE RUNNING:", service.is_running)
print("HEALTH:", health.status.value)
print("BINDINGS:", secure_snapshot.total_bindings)
print("LOADED:", secure_snapshot.loaded_bindings)
print(
    "MASKED:",
    secure_snapshot.masked_secrets[
        "BINANCE_API_KEY"
    ],
)
print(
    "EXPOSED:",
    secure_snapshot.plaintext_values_exposed,
)
print(
    "UNRESOLVED:",
    service.unresolved_required_bindings(),
)

service.stop()
secrets.stop()
configuration.stop()

print("FINAL STATE:", service.state.value)
