# ADR-0008: Research Evidence Store

## Status

Accepted. First increment implemented 2026-09-18 (UTC). Supersedes nothing.
Introduces the durable research-claim store and its write path; the
dashboard-facing HTTP surface (`/api/evidence`, `/api/research`) is
deliberately deferred to a later task and is **not** part of this record.

## Context

The owner's specification is that every significant Atlas assertion must
carry a traceable chain:

> CLAIM → SOURCE → EVIDENCE → TIMESTAMP → AGENT → CONFIDENCE →
> COUNTER-EVIDENCE

A claim such as "BTC's volatility regime changed" must be answerable for
which data was examined, over which time range, from which source, by which
model, whether counter-evidence exists, and what happened in similar past
situations.

Atlas's research layer was far simpler than that. The five agents in
`ai/core/` emit only `{action, score}`, and nothing was persisted. A partial
exception exists and matters: `core/decision_intelligence.py` already defines
an `Evidence` dataclass and an `EvidenceStatus` enum, and
`ai/core/atlas_brain.py` already converts each agent into one. That type is
a *per-cycle directional vote* consumed by `SignalFusion` and then discarded
— it has no claim text, no payload, no counter-evidence, no precedent and no
persistence. Reusing the name for the durable unit would have collided with
a live, load-bearing type on the decision path.

This store is the foundation that the Hypothesis Registry, the Manager/Worker
research organisation, the Self-Deception Engine and Strategy Lab are all
planned to consume, so the schema is expensive to unwind later.

## Decisions

- **The persisted unit is a `ClaimRecord`, not an `Evidence`.**
  `core.decision_intelligence.Evidence`, `EvidenceStatus`, and
  `AtlasBrain._build_phase5_agent_evidence()` are untouched by this work.
  A claim is the durable statement; evidence is what stands behind it, which
  also matches the owner's own wording ("her önemli iddianın arkasında").

- **SQLite, not append-only JSONL.** Counter-evidence is a graph, so "find
  everything that contradicts claim X" is an indexed edge lookup rather than
  a linear scan; lifecycle status needs current-state resolution, which on
  JSONL means replaying the whole file on every read; and at the measured
  10-second market interval, naive per-cycle recording of 5 symbols × 5
  agents would be roughly 79M rows a year. The existing checksummed
  forward-only migration framework in `data_layer/migrations.py` is reused
  verbatim rather than forked.

- **Immutability is preserved without JSONL.** `claims`, `claim_sources` and
  `claim_relations` rows are written once and never `UPDATE`d; lifecycle
  transitions are appended to `claim_status_history`. This applies the
  project's standing governance rule — reconcile by adding a successor
  record, never by editing a historical one — to research state.

- **The module lives in `data_layer/`, not `research/`.** The plan said
  `research/evidence_store.py`, but `research/__init__.py` states a hard
  invariant for that package: *"no connection to the Atlas runtime. It never
  writes Atlas runtime state, and it carries no trading authority of any
  kind."* This store is constructed at the composition root and written from
  the brain, so placing it there would have violated that invariant. It is a
  SQLite-backed durable store, which is exactly what `data_layer/` holds.

- **A third operator-relocatable root, `ATLAS_EVIDENCE_DIRECTORY`**, default
  `<installation>/evidence_store`, operator target
  `C:\AtlasState\evidence_store`. It resolves through the *same*
  `_resolve_configured_directory()` validator as the other two roots, so an
  override that is empty, relative, missing, or not a directory raises
  `ConfiguredDirectoryError` instead of silently falling back to a different,
  empty database.

  **No code path creates the directory — not the resolver, and not
  `EvidenceStore.open()`, for either the override or the installation
  default.** Auto-creating it would turn a mistyped or not-yet-provisioned
  root into a new, empty database that looks healthy, which is the exact
  silent failure the resolver exists to prevent. A missing directory raises
  `StorageError`, which startup absorbs fail-open and `health()` reports.
  The practical consequence is deliberate: until the operator creates the
  directory, Atlas runs normally and records no evidence.

  A third root rather than a subdirectory of the state root because evidence
  has a different profile: a continuously-appended, growing database whose
  backup and retention needs are nothing like the small, precious financial
  state in `memory_data`. Keeping them apart lets each be backed up on its
  own terms and lets evidence live on a different disk.

- **WAL is enabled.** `C:\AtlasState` was confirmed a genuinely local,
  non-synced disk during STATE-MOVE-1 (ADR-0007), which is the precondition
  WAL requires.

- **Library first; HTTP is a later, read-only projection.** Every writer is
  in-process, and SQLite with multiple writing processes is a corruption
  risk, so a single in-process writer owned by the composition root is the
  safe architecture. The dashboard already reaches runtime objects through
  `application.state.atlas_runtime`, so the future endpoints are a thin read
  layer over the same object, not a second service.

- **Change-triggered writes.** An agent is recorded when its direction flips,
  when its conviction moves by at least `evidence_conviction_delta`
  (default **0.15** on the 0..1 conviction scale, configurable per run), when
  the fused action changes, or on first observation of that agent/symbol
  pair. Per-cycle recording would bury genuine assertions in telemetry.

- **The decision-path hook is fail-OPEN.** This is the one deliberate
  departure from Atlas's fail-closed default, and it is narrow: evidence
  carries no trading authority, so a research-database failure must never
  alter or block a trading decision. The store itself still raises rather
  than silently discarding a write; the hook absorbs it, logs it, and
  registers it on `EvidenceStore.health()`. Fail-open must not mean
  fail-silent.

- **Provenance is never fabricated.** A claim is recorded only when the
  market data carries a trustworthy, timezone-aware ingestion timestamp,
  mirroring `_parse_ingestion_timestamp()`'s existing contract. Missing
  provenance produces no claim rather than a claim with an invented one.

- **Status is system-only in this increment (OQ-5)**, and **precedent is
  edges only (OQ-6)** — `claim_relations.PRECEDENT_OF`. Outcomes belong to
  the Hypothesis Registry and are not modelled here.

## Consequences

- Atlas now has a fourth durable artifact to think about operationally, but
  it is the only one Atlas will start *without*: if the evidence database
  cannot be opened, startup logs the failure and continues. Refusing to trade
  because a research store would not open would be the worse outcome.

- The `claim_current_status` view exists as the readable definition of
  current status, but library queries deliberately do **not** join it.
  `EXPLAIN QUERY PLAN` showed SQLite materialising the view — a `GROUP BY`
  scan over the whole history table on every call — which turned an
  O(log n + k) counter-evidence lookup into an O(history) one and defeated
  `idx_relations_to`. The library uses an equivalent correlated subquery that
  is a primary-key seek per candidate row. Future queries added to this
  module must keep that property; the index-usage test enforces it.

- **Measured cost on the decision path: a change-triggered cycle goes from
  ~1.3ms to ~72ms median** (5 claims, one transaction each). That is 0.7% of
  the 10-second market interval, so it is accepted rather than optimised.
  The cost is dominated by opening a SQLite connection per operation
  (~6.2ms of each ~13.8ms `record_claim`), which is the convention
  `data_layer/sqlite.py` already uses; an empty transaction on a held
  connection is ~0.05ms. `synchronous = NORMAL` was tried and reverted
  because it produced no measurable gain, so the store keeps SQLite's
  default durability. If the market interval is ever shortened materially,
  connection reuse is the lever to pull — and it should be pulled then, on
  evidence, not pre-emptively now.

- `CONTRADICTS` is stored as two rows written in one transaction because it
  is semantically symmetric, so every counter-evidence read stays a single
  index seek. `SUPERSEDES`, `REFINES` and `PRECEDENT_OF` are directional and
  stored once.

- Schema evolution has two independent axes: `data_layer/migrations.py` for
  table shape, and the `schema_version` column for payload shape. Payload
  evolution is additive only; a breaking change takes a new `claim_kind`
  rather than redefining an existing one. Historical rows are never
  rewritten.

- The operator must create `C:\AtlasState\evidence_store` and set
  `ATLAS_EVIDENCE_DIRECTORY` manually. Until a directory exists, Atlas
  starts normally, logs that the evidence store could not be opened, and
  records nothing — evidence recording is opt-in by provisioning. The
  installation-anchored default is gitignored, so pointing at it instead is
  also safe.

## Evidence

- Implementation: `data_layer/evidence_store.py`; wiring in
  `core/application.py` (`DEFAULT_EVIDENCE_DIRECTORY`,
  `EVIDENCE_DIRECTORY_ENV`, `resolve_evidence_directory()`,
  `self.evidence_directory`, `self.evidence_store`) and `core/brain.py`;
  recording hook in `ai/core/atlas_brain.py`
  (`_record_evidence_claims()` and helpers).

- Tests: `tests/test_evidence_store.py` (50) and
  `tests/test_evidence_store_integration.py` (24), covering constraint
  rejection, idempotency, append-only lifecycle, counter-evidence semantics,
  index usage via `EXPLAIN QUERY PLAN`, migration bootstrap/no-op/tamper,
  concurrency, fail-closed env-var resolution, change-trigger logic, and
  fail-open behaviour against a broken store.

- Untouched by design, verified by diff: `core/decision_intelligence.py` and
  `AtlasBrain._build_phase5_agent_evidence()`.
