# ATLAS CHECKPOINT — research/ boundary settled as L4 (Package A)

- **UTC:** 2026-09-19T15:24:25Z
- **Branch:** `research/edge-validation`
- **Commit produced:** `b9c96eb`
- **Parent at session start:** `1ac3a64`
- **Task classification:** CRITICAL (governance artifact — the architecture
  map). Full critical-task final gate applied in sequence: IMPLEMENT → TEST →
  SELF-REVIEW → REGRESSION → INDEPENDENT AUDIT → FIX → RE-TEST → FINAL GATE.

## Objective

Before extending `research/hypothesis_registry.py` to the owner's five-check
specification, resolve explicitly whether `research/` may read from or write to
the Evidence Store (`data_layer/evidence_store.py`, ADR-0008) at all without
violating `research/__init__.py`'s "no connection to the Atlas runtime"
invariant — and record the answer — given that the same class of layer
violation was found and fixed twice earlier the same day (`4af72ee`,
`1ac3a64`).

Two phases were in scope: a read-only survey for any real v1 registry file
(Phase 0, an input to a later decision), and implementation of the approved
Package A boundary decision (Phase A).

## Completed

### Phase 0 — registry-file survey: NOT FOUND (definitive)

The on-disk signature was read from the code, not guessed:
`HypothesisRegistry._save` writes a JSON object with top-level `version`
(== `REGISTRY_FORMAT_VERSION`, currently `1`) and `records`; each record from
`HypothesisRecord.as_dict` carries `preregistration`, `preregistration_hash`,
`state`, `evaluations`. `preregistration_hash` is the distinctive marker.

- Content grep for `preregistration_hash` across the repository (tracked and
  untracked, `.git/` excluded): three real hits only —
  `research/hypothesis_registry.py`,
  `tests/test_research_hypothesis_registry.py`,
  `docs/research/0001-hypothesis-registry-design.md`. Restricted to `*.json`:
  zero files.
- Same grep over `C:\AtlasState` (root, `memory_data/`,
  `memory_data_backup_20260915/`, `evidence_store/`, `market_archive/`): zero
  files. `evidence_store/` and `market_archive/` hold no JSON at all.
- Filename sweep of the project tree for `*hypoth*` and `*registry*.json`: only
  unrelated `ATLAS_MILESTONE_REGISTRY_v4.*.json` governance records,
  `ARCH-001.2.3_REGISTRY_PATCH_PROPOSAL.json`, and vendored pydantic plugins.
- `grep "registry_path\|HypothesisRegistry("` over `checkpoints/` and `docs/`:
  zero hits. No record anywhere of a real path ever having been used.

The existing tests route every construction through `tmp_path`, so they leave
nothing behind. **Scope limit, stated so the negative can be trusted:** content
grep covered the repository tree and `C:\AtlasState`; beyond those, only a
filename sweep of the project tree and a bounded sweep of the user home
directory were done — not a full-disk content scan.

**Consequence:** M0 (a clean `REGISTRY_FORMAT_VERSION` 1→2 break) is available
for the later five-check package. That decision is still the owner's and was
deliberately not taken here.

### Phase A — Package A implemented, audited, committed

The boundary question was answered from measured repository evidence:

- `research/**` had no entry in `module_layers` and no matching `layer_rules`
  pattern. `module_layers` is computed over the runtime closure
  (`compute_module_layers(computed_closure, ...)`), the closure holds 105
  modules reachable from `main.py`, `web_app.py`, `atlas_service.py`,
  `atlas_supervisor.py`, and none is under `research/`.
- `find_forbidden_edges` skips any module whose layer is `None`. **`research/`
  was therefore invisible to the architecture gate** — a green `check` run was
  silence about it, not approval of it. This is a third instance of the day's
  failure mode, and the most dangerous: the gate could not see it at all.
- `data_layer/evidence_store.py` = L2, `data_layer/contracts.py` = L1,
  `data_layer/__init__.py` = L2. L4 → L2 and L4 → L3 are hard forbidden edges.
  L3's `allowed_dependencies` span both L2 and L4, making L3 the unique legal
  meeting point.

## Files changed

Committed in `b9c96eb` (3 files, +587 lines, no deletions):

- `packaging/atlas_architecture_map.json` — **+5 lines, purely additive.** One
  `layer_rules` entry: `research/* → L4`, inserted immediately after
  `analysis/*`. No change to `forbidden_edges`, `permitted_exceptions`,
  `layers`, or `module_layers`.
- `tests/test_research_isolation.py` — **new**, 341 lines, 10 tests.
- `docs/adr/0009-hypothesis-registry-boundary.md` — **new**, 241 lines.

`research/`'s four modules are unchanged. Verified by `git status` over
`research/`: empty.

## Architecture decisions (recorded in ADR-0009)

1. **`research/**` is L4 (RESEARCH_INTELLIGENCE).** L4's description restates
   `research/__init__.py`'s own invariant, and siblings `ai/**` and
   `analysis/**` are already L4. No other assignment is defensible.
2. **`research/` imports nothing first-party outside `research/` — not even
   `data_layer/contracts.py`.** That L1 import is technically legal under the
   layer rules and `ai/core/atlas_brain.py` legitimately uses it for
   `ClaimSource`. `research/` is held to the stricter line because its own
   invariant is stronger than L4's, because the strict form is statically
   decidable in one grep, and because taking the L1 import would enlist
   `research/` in the still-open ancestor-edge gap recorded in `1ac3a64` (18
   violations, 15 needing an `__init__.py` classification decision) for no gain.
3. **A `permitted_exceptions` entry was rejected outright** — weakening a hard
   forbidden edge to accommodate code is the anti-pattern both of the day's
   earlier fixes refused.
4. **Reusing `HypothesisRegistry.registry_path` as an Evidence Store path was
   rejected** — it would couple two independent durability contracts and hand
   `research/` a write handle into runtime state.
5. **The sanctioned integration shape is a future L3 bridge.** `research/`
   returns a pure verdict value object; `core/research_evidence_bridge.py`
   (confirmed L3 by `classify_module`; **not built in this package**) reads it,
   builds `ClaimSource` from L1 contracts, and calls `record_claim` on an
   injected store. This mirrors the existing precedent: `core/application.py`
   constructs the `EvidenceStore` and injects it into `AtlasBrain`, which holds
   it as `Any | None` and never imports the store.
6. **W1 over W2** — `research/` stays out of the runtime closure until Step 2
   data acquisition exists. W2 (wiring the bridge into `core/application.py`)
   is deferred as its own package.
7. **Two compensating controls, mandatory because W1 leaves `research/`
   ungoverned by the gate:**
   - **C1** — the `research/* → L4` rule, recorded in advance so the
     classification is a decision on the record rather than one taken under
     pressure the day `research/` is first wired in.
   - **C2** — `tests/test_research_isolation.py`, the only thing enforcing the
     invariant today. Deliberately stricter than `find_forbidden_edges` in three
     ways: `TYPE_CHECKING`-guarded imports are not exempt (the invariant is
     about declared coupling, not only what executes); package-escaping relative
     imports are reported; constant-string dynamic imports
     (`importlib.import_module("x")`, `__import__("x")`) are resolved. It pins
     C1 through `classify_module` (resolved classification, not rule presence)
     and pins W1.

## Tests

All runs used an ASCII `--basetemp`, since this host's default tmp root is
broken.

- **Full suite (the CRITICAL gate RE-TEST step):**
  `python -m pytest tests -q --basetemp=<ascii>` → **2921 passed, 0 failed, 0
  skipped**, 109.13s. The previous full-suite baseline recorded in `1ac3a64`
  was 2910 passed with 1 pre-existing environmental skip (2911 collected). 2911
  + 10 new isolation tests = 2921, and the previously environment-skipped test
  now passes. No regression; the delta is fully accounted for.
- Research regression + new guard (5 files): **131 passed** (121 pre-existing +
  10 new).
- Every consumer of the architecture map — `tests/architecture/`,
  `test_block3_capability_architecture.py`,
  `test_block4_market_data_architecture.py`,
  `test_block4_market_data_live_correctness.py`,
  `test_block5c_upstream_sizing_authority.py`: **195 passed**.
- Architecture gate, run before and after the map edit, identical both times:
  `OK: runtime closure matches (105 modules)` / `OK: architecture map assigns
  every live module a layer (105 modules)` / `OK: no forbidden dependency
  edges`.

**C1's inertness was measured, not asserted:** `module_layers` stays at 105
entries with no `research/` key, the `unassigned` list is unchanged, and the
gate result is byte-identical before and after.

## Independent audit

Performed on the uncommitted change before commit. **Verdict: PASS.** No
BLOCKING, HIGH, or MEDIUM findings. It independently re-derived the inertness
claim (including rule ordering in both directions and the fact that `fnmatch`'s
`*` spans `/`), traced all eight absolute and relative import forms through the
detector, and checked every factual claim in the ADR against the repository —
**no CONFLICT found**.

**Four LOW findings, all closed in this package before commit:**

- **LOW-1** — first-party detection required a `.py` file, so `config/`,
  `database/` and `learning/` (in CLAUDE.md's directory map, importable under
  PEP 420 despite holding only data) would not have been flagged. Detection now
  counts every top-level directory.
- **LOW-2** — the guard derives "first-party" from the working tree while
  `tools/build_architecture_inventory.py` uses `git ls-files`. Kept, and
  documented as deliberate: the divergence only ever *adds* forbidden names, so
  it can make the guard stricter and never weaker.
- **LOW-3** — dynamic imports were invisible. Constant-string
  `importlib.import_module` / `__import__` are now resolved. Computed-string
  imports remain invisible — recorded in ADR-0009 rather than papered over, and
  the ADR's unqualified claim was narrowed to "statically visible shortcut".
- **LOW-4** — the C1 pin asserted the rule's presence rather than its resolved
  classification, so a rule inserted ahead of it could have changed the
  effective layer while the test stayed green. It now calls `classify_module`
  on three paths including a nested one, matching the stronger precedent in
  `test_block4_market_data_architecture.py`.

**Five INFORMATIONAL findings**, all corrected in the ADR text: an
under-enumerated `C:\AtlasState` survey scope; "zero external consumers" not
qualified as excluding its own tests; two truncated or merged quotes from the
architecture map; a present-tense claim that the edit itself had made ambiguous
("no layer assignment at all" → "no entry in `module_layers`"); and the fact
that C1 *moves* a fail-closed tripwire one branch later (from "modules with no
layer assignment" to "module_layers is stale") rather than removing it.

## Current state

- Branch `research/edge-validation` at `b9c96eb`, working tree carrying only the
  nine pre-existing unrelated uncommitted paths that were present at session
  start (`.claude/agents/atlas-db-reader.md`,
  `REM-001_CANONICAL_COMPONENT_MATRIX.json`, three earlier checkpoints,
  `docs/adr/0007-*.md`, two `governance/ATLAS_REM001_*` records,
  `governance/current/ATLAS_MILESTONE_REGISTRY_v4.33.json`). None was touched.
- `research/` remains a standalone, runtime-disconnected prototype with no
  production consumers and no reachability from any entry point.
- Authority state unchanged: `production_authority=NONE`,
  `live_authority=DENIED`, `autonomous_deployment_authority=DENIED`.

## Known issues

- **Pre-existing, not caused here:** `tools/build_provenance_record.py` hashes
  `packaging/atlas_architecture_map.json` into `architecture_map_hash`, and the
  checked-in `reports/block2_freeze_provenance.json` value was **already stale
  at HEAD before this change**. No test breaks (the test recomputes from the
  live file and asserts only a 64-character length). This commit changes the
  live hash further. Out of scope here; worth its own look.
- **Pre-existing, unchanged:** the ancestor-edge gap in `find_forbidden_edges`
  (18 violations in the ad hoc simulation recorded in `1ac3a64`, 15 needing a
  real `__init__.py` classification decision). This decision deliberately does
  not grow it.
- Committing emitted `failed to delete '.git/worktrees/...': Permission denied`
  for two stale worktree entries. Git's stale-worktree pruning on a
  OneDrive-synced path; the commit itself succeeded and is intact.

## Risks

- None introduced by this change. It adds no capability, touches no execution,
  capital, risk, migration, or runtime state, and writes no runtime state.
- Residual, accepted and documented: a dynamic import assembled from a computed
  string inside `research/` would evade C2, as it evades every static checker in
  this repository.
- Behavioural nuance worth knowing: if `research/` is ever wired into the
  runtime, the operator-visible failure message changes from "modules with no
  layer assignment" to "module_layers is stale", plus C2's W1 test firing. Both
  remain fail-closed.

## Remaining work

1. **Owner decision — M0 vs M1** for the five-check package's seal versioning.
   Phase 0 establishes that no real v1 registry file exists, so M0 (clean
   `REGISTRY_FORMAT_VERSION` 1→2 break) is available. M1 (versioned sealed
   payload preserving v1 hashes) remains the alternative. M2 (re-sealing
   existing records) was rejected in the plan — it would destroy the
   tamper-evidence guarantee.
2. **Package B — the five-check contract** (CRITICAL, migration-touching;
   `atlas-migration-safety` checklist applies). Per the approved plan Part 2:
   `CheckName` / `CheckVerdict` / `CheckResult`; `EvaluationRecord.checks`; a
   sealed `check_plan` in `PreRegistration`; conjunctive adjudication
   (`FDR ∧ alpha ∧ effect ∧ all required checks PASS`, never a weighted score);
   the NB-4 analogue (a missing check is FAIL, never "skip"); the NB-5 analogue
   (the denominator is the sealed plan size, not the number of results present);
   and BH continuing to run over **all** tested p-values so that check failures
   cannot shrink *m* and inflate the realised FDR.
   The single irreversible TEST read is the load-bearing constraint that forces
   `COST_ADJUSTED` and `MONTE_CARLO` to ride inside the one TEST
   `EvaluationRecord` rather than as separate evaluations.
3. **Package C — the L3 bridge** (`core/research_evidence_bridge.py`). Blocked
   on Package B.
4. **Package D — the compute engines** (backtest, walk-forward, Monte Carlo,
   cost model). Blocked on Step 2 data acquisition, which
   `docs/research/0001-hypothesis-registry-design.md` names as a prerequisite.
5. **Package E — the ancestor-edge checker fix.** Pre-existing, already owner-
   deferred, unaffected by this work.

## Next exact action

Answer the M0/M1 question (owner decision; Phase 0's negative result is the
input), then dispatch Package B against `research/hypothesis_registry.py` and
`research/lifecycle.py` on branch `research/edge-validation` from `b9c96eb`.
Package B is CRITICAL: the full critical-task final gate and the
`atlas-migration-safety` checklist both apply, and its tests must discriminate
the NB-4 and NB-5 analogues explicitly rather than only exercising the happy
path.

No re-verification is needed for anything already established here: the layer
assignments, the closure size of 105, the gate's blindness to unassigned
modules, the L3 allowed-dependency span, the absence of a real v1 registry file,
and the 2921-test green baseline are all settled evidence as of `b9c96eb`.
