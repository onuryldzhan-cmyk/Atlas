from atlas_os import SecretBindingMode

from atlas_runtime import build_secure_core


secure_core = build_secure_core(
    install_signal_handlers=False,
)

secure_core.configuration_secrets_service.register_secret(
    "ATLAS_TEST_SECRET",
    mode=SecretBindingMode.ENVIRONMENT,
    environment_variable="ATLAS_SECURE_CORE_TEST",
    required=True,
    minimum_length=8,
)

runtime = secure_core.runtime

print("INITIAL STATE:", runtime.state.value)
print("SERVICE COUNT:", runtime.service_count)

for registration in runtime.registrations():
    print(
        "REGISTERED:",
        registration.service_name,
        "DEPENDENCIES:",
        registration.dependencies,
    )

runtime.validate()

print("VALIDATED:", runtime.state.value)

runtime.start()

print("RUNTIME:", runtime.state.value)
print("KERNEL:", runtime.kernel.state.value)

print(
    "CONFIGURATION RUNNING:",
    secure_core.configuration_service.is_running,
)

print(
    "SECRETS RUNNING:",
    secure_core.secrets_manager.is_running,
)

print(
    "BRIDGE SERVICE RUNNING:",
    secure_core
    .configuration_secrets_service
    .is_running,
)

bridge_snapshot = (
    secure_core
    .configuration_secrets_service
    .secure_snapshot()
)

print(
    "TOTAL BINDINGS:",
    bridge_snapshot.total_bindings,
)

print(
    "LOADED BINDINGS:",
    bridge_snapshot.loaded_bindings,
)

print(
    "MASKED:",
    bridge_snapshot.masked_secrets[
        "ATLAS_TEST_SECRET"
    ],
)

print(
    "UNRESOLVED:",
    secure_core
    .configuration_secrets_service
    .unresolved_required_bindings(),
)

print(
    "BRIDGE EXPOSED:",
    bridge_snapshot.plaintext_values_exposed,
)

runtime_snapshot = runtime.snapshot()

print(
    "RUNTIME EXPOSED:",
    runtime_snapshot.plaintext_values_exposed,
)

runtime.stop()

print("FINAL STATE:", runtime.state.value)

print(
    "CONFIGURATION RUNNING:",
    secure_core.configuration_service.is_running,
)

print(
    "SECRETS RUNNING:",
    secure_core.secrets_manager.is_running,
)

print(
    "BRIDGE SERVICE RUNNING:",
    secure_core
    .configuration_secrets_service
    .is_running,
)
