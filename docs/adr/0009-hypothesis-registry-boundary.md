# ADR-0009: The `research/` Boundary and Its Evidence Store Integration Shape

## Status

Accepted 2026-09-19 (UTC). Supersedes nothing. Amends nothing in ADR-0008,
which remains the authority on the Evidence Store itself.

This record settles a boundary question and installs two compensating
controls. It builds no integration: `core/research_evidence_bridge.py` is
described here as the sanctioned future shape and is deliberately **not**
implemented in this package. The extension of `research/hypothesis_registry.py`
to the owner's five-check specification is likewise a separate, later package.

## Context

`research/` (`hypothesis_registry.py`, `lifecycle.py`, `multiple_testing.py`,
`splitting.py`) is a tested, deliberately scoped "Step 1 infrastructure only"
prototype — see `docs/research/0001-hypothesis-registry-design.md`. Outside its
own four test files it has no consumers, and it is reachable from no entry
point.

`research/__init__.py` states a hard invariant: the package "contains no
strategy, no signal, no data acquisition, and no connection to the Atlas
runtime. It never writes Atlas runtime state, and it carries no trading
authority of any kind."

The Evidence Store (ADR-0008, `data_layer/evidence_store.py`) is the durable
claim/evidence store, and ADR-0008 explicitly names the Hypothesis Registry as
one of its planned consumers. That raises the question this record answers: may
`research/` read from or write to it, and if not, what reads a hypothesis
verdict and turns it into a claim?

The question is being answered **before** any implementation is dispatched
because the same class of boundary was violated twice on 2026-09-19 and fixed
twice on the same day:

1. `ai/core/atlas_brain.py` (L4) imported `ClaimSource` directly from
   `data_layer/evidence_store.py` (L2) — fixed in commit `4af72ee` by
   extracting `ClaimSource` into `data_layer/contracts.py` (L1).
2. `data_layer/__init__.py` eagerly imported its L2 submodules, so any import
   reaching the package — including the now-sanctioned L4 → L1 `ClaimSource`
   path — loaded the SQLite backend into the L4 decision-path process. Fixed in
   commit `1ac3a64` by converting the package to PEP 562 lazy attributes.

Both fixes used the same principle: extract a pure boundary or make it lazy;
never weaken a forbidden edge with a `permitted_exceptions` entry.

### What the gate does and does not see

Verified against the repository on 2026-09-19:

- `research/**` has **no entry in `module_layers`**, before this record and
  after it. `module_layers` is computed over the runtime closure
  (`compute_module_layers(computed_closure, ...)` in
  `tools/build_architecture_inventory.py`), the closure holds 105 modules
  reachable from `main.py`, `web_app.py`, `atlas_service.py` and
  `atlas_supervisor.py`, and none of them is under `research/`.
- `find_forbidden_edges` skips any module whose layer is `None`
  (`importer_layer = module_layers.get(relative_path)` → `continue`).
  **`research/` is therefore invisible to the architecture gate.** A green
  `check` run says nothing about it.
- Before this record, no `layer_rules` pattern matched `research/*`, so the
  moment `research/` entered the closure, `cmd_check` would have failed at the
  unassigned-modules gate — *before* forbidden-edge analysis ever ran. C1 does
  not remove that tripwire, it moves it one branch later: the same event now
  fails on `module_layers is stale` instead, and additionally on C2's W1 test.
  The behaviour stays fail-closed either way; only the message an operator sees
  changes.
- `data_layer/evidence_store.py` is L2; `data_layer/contracts.py` is L1;
  `data_layer/__init__.py` is L2.
- L4's allowed dependencies are stdlib, L0 and L1. L4 → L2 and L4 → L3 are hard
  forbidden edges, reasoned in the map as "research/intelligence must not reach
  execution/infrastructure internals (research cannot trade)" and
  "...execution/application internals (research cannot trade)" respectively.
- L3's allowed dependencies are stdlib, L0, L1, **L2 and L4**. L3 is the only
  layer permitted to hold both an infrastructure store and a research result.
- `find_forbidden_edges` resolves only direct dotted imports and emits no
  ancestor-package edges. Commit `1ac3a64` records that this gap remains open,
  at 18 violations in an ad hoc simulation, 15 of which need a real
  `__init__.py` classification decision. That remediation is deferred as its
  own package and is unchanged by this record.

## Decisions

- **`research/**` is L4 (RESEARCH_INTELLIGENCE).** L4's description —
  "Produces proposals and evidence. Must never own execution authority or reach
  execution internals directly (research cannot trade)." — restates
  `research/__init__.py`'s own
  invariant, and the sibling packages `ai/**` and `analysis/**` are already L4.
  No other assignment is defensible.

- **`research/` imports nothing first-party outside `research/` — not even
  `data_layer/contracts.py`.** The package's own invariant is stronger than the
  layer rule that now covers it. L4 would permit importing any L1 contract, and
  `ai/core/atlas_brain.py` legitimately does exactly that for `ClaimSource`.
  `research/` is held to the stricter line for three reasons:

  1. "No connection to the Atlas runtime" becomes **statically decidable in one
     grep**, permanently, by anyone, without consulting the layer table.
  2. It keeps `research/` out of the open ancestor-edge gap. Under
     ancestor-aware semantics, even `from data_layer.contracts import
     ClaimSource` would emit `research/x.py (L4) → data_layer/__init__.py (L2)`,
     a forbidden edge. Taking the L1 import would grow that deferred
     remediation from 18 files to more, for no gain.
  3. It keeps `research/` importable and testable in a bare interpreter with no
     Atlas runtime present, which its 121 existing tests rely on.

- **A `permitted_exceptions` entry for `research/` → `data_layer/**` is
  rejected outright.** Weakening a hard forbidden edge to accommodate code is
  the anti-pattern both of the same day's fixes refused.

- **Reusing `HypothesisRegistry.registry_path` as an Evidence Store path is
  rejected.** The registry is a JSON document with its own seal and
  format-version contract; the store is SQLite with its own schema and
  fail-open write path. Conflating them would couple two independent durability
  contracts and hand `research/` a write handle into runtime state.

- **The sanctioned integration shape is a future L3 bridge.**

  ```
  research/hypothesis_registry.py   (L4, pure, stdlib-only)
        └─ returns FamilyVerdict / HypothesisVerdict value objects
                            │
                            ▼  read by
  core/research_evidence_bridge.py  (L3 — classify_module confirms L3)
        ├─ imports research.hypothesis_registry       (L3 → L4, allowed)
        ├─ imports data_layer.contracts.ClaimSource   (L3 → L1, allowed)
        └─ calls record_claim() on an injected store  (L3 → L2, allowed)
  ```

  This mirrors the established precedent rather than inventing one:
  `core/application.py` constructs the `EvidenceStore` and injects it into
  `AtlasBrain`, which holds it as `Any | None` and never imports the store. The
  bridge is one-way by construction — `research/` never learns the store
  exists. **Not built in this package.**

- **W1 over W2: `research/` stays out of the runtime closure for now.** Wiring
  the bridge into `core/application.py` (W2) would pull `research/` into the
  closure, require the closure and `module_layers` artifacts to be regenerated,
  and give the live runtime a research write path — before Step 2 data
  acquisition, which `docs/research/0001-hypothesis-registry-design.md` names as
  a prerequisite, exists at all. Deferred as its own package.

- **Because W1 leaves `research/` ungoverned by the gate, two compensating
  controls are mandatory and are delivered here.**

  - **C1 — the classification is recorded in advance.** A
    `{"pattern": "research/*", "layer": "L4"}` rule is added to `layer_rules`.
    It is **verified inert**: `compute_module_layers` iterates only the closure,
    `research/**` is in no closure, so `module_layers` stays at 105 entries and
    `check` stays green. Its purpose is that the classification is a decision on
    the record now, rather than one taken under pressure on the day `research/`
    is first wired in.
  - **C2 — a static guard test.** `tests/test_research_isolation.py` AST-walks
    every `research/**/*.py` and fails on any import resolving to a first-party
    module outside `research/`. It is the only thing enforcing the invariant
    today. It is deliberately **stricter** than `find_forbidden_edges` in three
    ways: `TYPE_CHECKING`-guarded imports are not exempt, because the invariant
    is about declared coupling and not only about what executes; relative
    imports that would climb above `research/` are reported rather than ignored;
    and constant-string dynamic imports (`importlib.import_module("x")`,
    `__import__("x")`) are resolved, since they would otherwise be the obvious
    way around the guard. A dynamic import assembled from a computed string
    remains invisible — as it does to every static checker in this repository —
    and that residual gap is accepted here rather than papered over. The guard
    pins its own classification through `classify_module` rather than by
    checking that the rule is merely present, and it pins W1 — if `research/`
    ever enters the runtime closure, the W1 test fails and forces the W2
    decision to be taken explicitly instead of by drift.

## Consequences

- `research/` gains no capability in this package. Its four modules are
  unchanged; the 121 existing research tests are untouched.
- The architecture gate's output is unchanged (105 modules, no unassigned
  modules, no forbidden edges). This is the intended proof of C1's inertness,
  not an absence of effect.
- Any future author who wants a hypothesis verdict inside Atlas has exactly one
  sanctioned route — the L3 bridge — and will be stopped by C2 on the first
  attempt to take any statically visible shortcut through `data_layer`.
- The cost of the stricter line is one small translation function outside
  `research/`, paid once, in the bridge package.
- The open ancestor-edge gap in `find_forbidden_edges` is neither fixed nor
  worsened here. This record's purpose with respect to it is containment: the
  eventual remediation's blast radius does not grow by `research/`.
- Whether the five-check extension breaks seal compatibility (a clean
  `REGISTRY_FORMAT_VERSION` bump versus a versioned sealed payload) is a
  separate decision, deliberately left open by this record.

## Evidence

- Architecture map: `packaging/atlas_architecture_map.json`, `layer_rules`
  entry `research/*` → L4. Verified with
  `tools.build_architecture_inventory.classify_module`, which returns `L4` for
  all five current `research/` modules and for a hypothetical nested
  `research/sub/deep/mod.py` (`fnmatch` `*` spans `/`, as it already does for
  the `ai/*` rule covering `ai/core/**`).

- Inertness of C1, measured before and after the edit:
  `python tools/build_architecture_inventory.py check` →
  `OK: runtime closure matches (105 modules)`,
  `OK: architecture map assigns every live module a layer (105 modules)`,
  `OK: no forbidden dependency edges`. `module_layers` remains 105 entries with
  no `research/` key.

- Guard test: `tests/test_research_isolation.py`, 10 tests, all passing. It
  includes a negative self-check (`test_detector_flags_a_forbidden_import`)
  asserting the detector flags `from data_layer.contracts import ClaimSource`,
  `import data_layer.evidence_store`, a `TYPE_CHECKING`-guarded
  `core.application` import, a package-escaping relative import,
  `importlib.import_module("data_layer.evidence_store")`,
  `__import__("core.application")` and `import config` (a directory holding no
  Python today but importable under PEP 420) — so the invariant test cannot pass
  merely because the detector is broken. A positive control asserts that stdlib
  and intra-`research/` imports produce no violation.

- Independent audit performed before this record was finalised: PASS, with no
  BLOCKING, HIGH or MEDIUM findings. Four LOW findings were raised against the
  guard test — first-party name detection that required a `.py` file, a
  working-tree versus git-tracked definition of "first-party", invisibility of
  dynamic imports, and a C1 pin that asserted the rule's presence rather than
  its resolved classification. All four were closed in this package; the
  detection heuristics are now documented in the test's own docstrings as
  deliberate and safe-by-direction.

- Registry-file survey (read-only, 2026-09-19): the on-disk signature of a real
  registry is a JSON object with top-level `version` / `records`, each record
  carrying `preregistration`, `preregistration_hash`, `state`, `evaluations`
  (`HypothesisRegistry._save`, `HypothesisRecord.as_dict`). A content search for
  `preregistration_hash` across the repository returns only
  `research/hypothesis_registry.py`, `tests/test_research_hypothesis_registry.py`
  and `docs/research/0001-hypothesis-registry-design.md`; no `.json` file
  anywhere matches. A recursive content search of `C:\AtlasState` — whose
  contents are the root, `memory_data/`, `memory_data_backup_20260915/`,
  `evidence_store/` and `market_archive/` — returns no such file either. A
  filename sweep of the project tree for `*hypoth*` and `*registry*.json`
  returns only unrelated `ATLAS_MILESTONE_REGISTRY_v4.*.json` governance records
  and vendored `pydantic` plugins. No `checkpoints/` or `docs/` record
  mentions `registry_path` or a `HypothesisRegistry(` construction. **No real v1
  registry file exists**, which is recorded here as an input to the later
  seal-versioning decision.
