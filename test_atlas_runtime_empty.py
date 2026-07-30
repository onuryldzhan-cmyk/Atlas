from atlas_runtime import AtlasRuntime


runtime = AtlasRuntime(
    install_signal_handlers=False,
)

print("INITIAL:", runtime.state.value)
print("SERVICES:", runtime.service_count)

runtime.validate()

print("VALIDATED:", runtime.state.value)

result = runtime.start()

print("RUNNING:", runtime.state.value)
print("KERNEL RUNNING:", runtime.kernel.is_running)

snapshot = runtime.snapshot()

print("SNAPSHOT STATE:", snapshot.state.value)
print("SNAPSHOT SERVICES:", snapshot.service_count)
print("EXPOSED:", snapshot.plaintext_values_exposed)

runtime.stop()

print("STOPPED:", runtime.state.value)
print("KERNEL RUNNING:", runtime.kernel.is_running)
