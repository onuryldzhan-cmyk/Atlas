# ADR-0004: Operational Boundary Seams (Secrets, Observability, Provenance, Policy)

## Status

Accepted. Block 2 / Package 2C.

## Context

Atlas is expected to later grow PostgreSQL-backed storage, external AI/model
providers, Tool/MCP integrations, governed agents, self-development
workflows, production observability, and reproducible builds. None of that
is built in this package. This ADR records the minimal seams added so those
systems have a safe place to attach later, without pulling in any new
runtime dependency.

## Decisions

- **Secrets** (`core/secret_provider.py`): a `SecretProvider` protocol and a
  `SecretValue` wrapper whose `repr()`/`str()` never expose the underlying
  value, plus one `EnvironmentSecretProvider` adapter. Existing secret
  consumers are not migrated to this contract. No Vault/keychain/cloud
  secret manager backend is added. This does not replace or modify
  `atlas_os/secrets/secrets_manager.py`; it is an independent, minimal
  contract for new code that wants to depend on "a secret" without
  depending on where it comes from.
- **Observability** (`core/operational_contracts.py`): `OperationContext`
  (trace/operation/actor/request identity) and `OperationResult`
  (status/reason/latency, sanitized through the existing
  `atlas_security.sanitize_sensitive_data` authority) give an
  OpenTelemetry-compatible shape without installing OpenTelemetry. No
  production call site is required to adopt these types by this change.
- **Policy/governance hook** (also `core/operational_contracts.py`):
  `PolicyDecision` and a `PolicyGate` protocol give the minimum shape a
  future authorization check (model call, tool call, code modification,
  deployment, live trading) would return. Nothing in the runtime calls
  `PolicyGate.evaluate()` yet; no RBAC store, agent org tree, or scheduler
  is introduced.
- **Provenance** (`tools/build_provenance_record.py`): a read-only,
  network-free generator that records `git_commit`/`branch`/
  `dirty_worktree`, Python version, and SHA-256 hashes of the dependency,
  runtime-distribution, and architecture-map manifests already checked
  into the repository. It refuses to record `build_mode="LIVE"` and always
  reports `live_authority: false`. This is not a cryptographic attestation
  (no SLSA/Sigstore/SBOM tooling).

## Consequences

- All four seams are additive, unimported by any existing production
  module, and therefore outside the statically-computed runtime closure
  (`packaging/atlas_runtime_closure.json` is unchanged by this package).
- No trading decision, confidence, risk bucket, allocation, or execution
  routing behavior changes as a result of this package.
- Wiring any of these seams into an actual call site (e.g. making
  `ExecutionManager` call a `PolicyGate` before a live order, or migrating
  an existing secret consumer) is deliberately left to a future,
  separately reviewed package.
