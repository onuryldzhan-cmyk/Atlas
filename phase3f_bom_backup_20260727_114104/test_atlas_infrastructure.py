from __future__ import annotations

import time

from atlas_os import (
    EventSeverity,
    SecretBindingMode,
)

from atlas_runtime import (
    build_infrastructure,
)


infrastructure = build_infrastructure(
    install_signal_handlers=False,
    health_monitor_options={
        "interval_seconds": 0.2,
        "history_limit": 50,
    },
    scheduler_options={
        "polling_interval_seconds": 0.02,
        "history_limit": 50,
    },
)

infrastructure.configuration_secrets_service.register_secret(
    "ATLAS_TEST_SECRET",
    mode=SecretBindingMode.ENVIRONMENT,
    environment_variable=(
        "ATLAS_INFRASTRUCTURE_TEST_SECRET"
    ),
    required=True,
    minimum_length=8,
)

runtime = infrastructure.runtime

print("=" * 60)
print("REGISTRATION")
print("=" * 60)

print(
    "SERVICE COUNT:",
    runtime.service_count,
)

for registration in runtime.registrations():
    print(
        registration.service_name,
        "->",
        registration.dependencies,
    )

runtime.validate()

print()
print("=" * 60)
print("STARTUP")
print("=" * 60)

runtime.start()

print(
    "RUNTIME STATE:",
    runtime.state.value,
)

print(
    "KERNEL STATE:",
    runtime.kernel.state.value,
)

services = (
    infrastructure.configuration_service,
    infrastructure.secrets_manager,
    infrastructure.configuration_secrets_service,
    infrastructure.event_bus,
    infrastructure.metrics_service,
    infrastructure.audit_service,
    infrastructure.scheduler_service,
    infrastructure.health_monitor_service,
)

for service in services:
    print(
        service.identity.name,
        ":",
        service.state.value,
    )

print()
print("=" * 60)
print("EVENT TEST")
print("=" * 60)

publish_result = (
    infrastructure.event_bus.publish_event(
        event_type="ATLAS.RUNTIME.TEST",
        source="test_atlas_infrastructure",
        payload={
            "status": "OK",
            "secret": "NOT_INCLUDED",
        },
        severity=EventSeverity.INFO,
    )
)

print(
    "EVENT PUBLISHED:",
    publish_result.success,
)

time.sleep(
    0.1
)

print(
    "EVENT HISTORY:",
    len(
        infrastructure.event_bus.event_history()
    ),
)

print(
    "AUDIT RECORDS:",
    infrastructure.audit_service.record_count,
)

print(
    "METRIC SERIES:",
    infrastructure.metrics_service.metric_series_count,
)

print()
print("=" * 60)
print("SCHEDULER TEST")
print("=" * 60)

execution_counter = {
    "value": 0,
}


def scheduled_test() -> None:
    execution_counter["value"] += 1


task_id = (
    infrastructure.scheduler_service.register_once(
        "atlas-infrastructure-test",
        scheduled_test,
        delay_seconds=0.05,
    )
)

print(
    "TASK ID CREATED:",
    bool(task_id),
)

time.sleep(
    0.2
)

print(
    "TASK EXECUTIONS:",
    execution_counter["value"],
)

print(
    "SCHEDULER HISTORY:",
    len(
        infrastructure.scheduler_service.history()
    ),
)

print()
print("=" * 60)
print("HEALTH TEST")
print("=" * 60)

observation = (
    infrastructure.health_monitor_service.poll_once()
)

print(
    "OBSERVATION CREATED:",
    observation is not None,
)

print(
    "OBSERVATION COUNT:",
    infrastructure
    .health_monitor_service
    .observation_count,
)

print(
    "HEALTH THREAD:",
    infrastructure
    .health_monitor_service
    .thread_alive,
)

print()
print("=" * 60)
print("SECURITY TEST")
print("=" * 60)

bridge_snapshot = (
    infrastructure
    .configuration_secrets_service
    .secure_snapshot()
)

runtime_snapshot = runtime.snapshot()

print(
    "SECRET LOADED:",
    bridge_snapshot.loaded_bindings,
)

print(
    "SECRET MASKED:",
    bridge_snapshot.masked_secrets[
        "ATLAS_TEST_SECRET"
    ],
)

print(
    "BRIDGE EXPOSED:",
    bridge_snapshot.plaintext_values_exposed,
)

print(
    "RUNTIME EXPOSED:",
    runtime_snapshot.plaintext_values_exposed,
)

print(
    "INFRASTRUCTURE EXPOSED:",
    infrastructure.plaintext_values_exposed,
)

print()
print("=" * 60)
print("SHUTDOWN")
print("=" * 60)

runtime.stop()

print(
    "FINAL RUNTIME STATE:",
    runtime.state.value,
)

print(
    "FINAL KERNEL STATE:",
    runtime.kernel.state.value,
)

for service in reversed(
    services
):
    print(
        service.identity.name,
        ":",
        service.state.value,
    )
