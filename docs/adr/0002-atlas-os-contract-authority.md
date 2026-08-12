# ADR-0002: AtlasOS Contract Authority

## Status

Accepted, with one deferred item (see Consequences). Frozen architecture
decision for Block 2 / Package 2A.

## Decision

The canonical AtlasOS authorities are:

- `atlas_os/contracts.py`
- `atlas_os/kernel/`
- `atlas_os/services/`

(plus the infrastructure implementations that compose with them:
`atlas_os/events/`, `atlas_os/observability/`, `atlas_os/audit/`,
`atlas_os/scheduling/`, `atlas_os/secrets/`, `atlas_os/configuration/`,
`atlas_os/integration/`, `atlas_os/integrations/`, all re-exported from
`atlas_os/__init__.py`.)

`atlas_os/core/*` is a duplicate, **non-canonical** prototype implementation
and is classified `NON_CANONICAL` in `packaging/atlas_architecture_map.json`.

## Evidence

- `atlas_os/__init__.py` states explicitly in its own docstring: *"The
  experimental `atlas_os.core` prototype is intentionally not re-exported
  here. It remains isolated until its useful parts are reviewed and merged
  into the canonical AtlasOS implementation."* This corroborates the
  quarantine classification independent of this review.
- A repository-wide AST/grep sweep found **zero** live-runtime importers of
  `atlas_os.core` or any `atlas_os/core/*` submodule. Neither
  `atlas_os/kernel/*`, `atlas_os/services/*`, nor `atlas_os/contracts.py`
  import anything from `atlas_os/core/*`. The generated runtime closure
  (`packaging/atlas_runtime_closure.json`) contains no `atlas_os/core/*`
  module.
- The **only** importer of `atlas_os.core` anywhere in the repository is
  `tests/atlas_os/test_kernel.py`, a real test under the canonical `tests/`
  tree that exclusively exercises `atlas_os/core/kernel.py::AtlasKernel` and
  its supporting `atlas_os/core/*` types (`AtlasService`, `HealthReport`,
  `HealthState`, `KernelState`, `ServiceMetadata`, `ServiceSnapshot`,
  `ServiceState`). All eleven other files under `tests/atlas_os/` import only
  canonical `atlas_os` symbols.

## Interface comparison (canonical vs. `atlas_os/core`)

A side-by-side reading of both implementations shows they are **materially
different**, not drop-in equivalents:

| Aspect | Canonical (`atlas_os/contracts.py`, `atlas_os/kernel/`, `atlas_os/services/`) | Non-canonical (`atlas_os/core/*`) |
|---|---|---|
| Service contract lifecycle methods | `start()`, `stop()`, `health()`, `snapshot()` | `initialize()`, `start()`, `stop()`, `health_check()`, `snapshot()` (extra lifecycle stage, differently-named health method) |
| Service identity | `identity: ServiceIdentity` (no `dependencies` field) | `metadata: ServiceMetadata` (bakes in `dependencies`/`critical`/`tags`) |
| State enum | `ServiceState` lacks `INITIALIZING`/`READY` | `ServiceState` lacks `DEGRADED` |
| Health type | `HealthStatus` | `HealthState` (same 4 values, different class name) |
| Kernel design | `AtlasOSKernel`: composed with a separate `DependencyServiceManager`, `register_service(service, dependencies=...)`, `start(rollback_on_failure=...)` returns `OrchestrationResult` | `AtlasKernel`: `ServiceRegistry`-based, dependencies declared on the service itself via `ServiceMetadata.dependencies`, `start()`/`stop()` return `None` |
| Registry design | `ServiceRegistry` is case-insensitive, delegates dependency resolution to `DependencyServiceManager`, exposes `start_all`/`stop_all` | `ServiceRegistry` is case-sensitive, resolves startup order itself via Kahn's-algorithm topological sort, no built-in `start_all`/`stop_all` |

## Test retargeting decision

Per the Package 2A instructions, a test that currently pins the
non-canonical implementation may only be retargeted to the canonical
implementation when the semantics are equivalent or the difference is
explicitly reviewed and accepted; if semantics materially differ, the
package must **stop and report** rather than silently migrate the test.

Given the interface comparison above, `tests/atlas_os/test_kernel.py` is
**not** retargeted. Its assertions exercise `AtlasKernel`-specific behavior
(constructor signature, `None`-returning lifecycle methods, service-declared
dependency metadata, Kahn's-algorithm-based `resolve_startup_order`) that has
no equivalent call shape in `AtlasOSKernel`. Migrating it would require
rewriting the test's assertions to a different contract, which is a
behavior-affecting decision requiring its own explicit review, not a
mechanical rename.

## Consequences

- `atlas_os/core/*` remains classified `NON_CANONICAL` and undergoes no
  behavior change, but is **not** physically moved to quarantine in Package
  2A: doing so would delete the only test coverage for it
  (`tests/atlas_os/test_kernel.py`), which the package instructions
  explicitly forbid ("Do not silently weaken or delete those tests").
- This is recorded as a **deferred finding**: reconciling `atlas_os/core/*`
  requires either (a) a reviewed decision to retire `test_kernel.py`'s
  coverage entirely, or (b) porting its assertions onto the canonical
  `AtlasOSKernel`/`ServiceRegistry` contract as a deliberate, reviewed
  behavior change. Both are out of scope for Package 2A's "no feature
  development, no behavior change" mandate and are left for a future
  package.
- `packaging/atlas_architecture_map.json` records the canonical/non-canonical
  split under `canonical_authorities.atlas_os`.
