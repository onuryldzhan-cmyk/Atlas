# ATLAS CHECKPOINT

## Objective

Owner brief 2026-09-25, Part I: implement, in this order, the three
hardening items recommended in
`checkpoints/20260925T185500Z_batch-i-hypothesis-registry-already-built.md`:

1. Truncated-file refusal (item 5 there).
2. Family manifest sealing (item 4 there).
3. State hash chain (item 6 there).

Power analysis and the p-value procedure were explicitly out of scope and
were not attempted. All three items proved tractable at the complexity the
prior checkpoint estimated, so none was stopped partway.

**Status: COMPLETE.** All three items implemented in `research/hypothesis_registry.py`.

## Completed

**Registry format bumped `2 -> 3`** (clean break, no version-2 loading
path, matching the module's own 1->2 precedent). No hypothesis registry
file has ever been checked into this repository - confirmed by
`git ls-files | grep -i hypothesis` and by `registry_path` having no
default anywhere in `core/` or `config/` - so this bump carries no
data-migration burden: nothing to resume, retry, or roll back.

1. **Truncated-file refusal.** `HypothesisRegistry._load` now refuses when
   the parsed JSON is not an object, when `records` is missing or not a
   list, or when the new `family_manifests` key (below) is missing or not a
   list. Previously a payload with no `records` key loaded silently as zero
   records.

2. **Family manifest sealing.** New `FamilyManifest` dataclass
   (`family_id`, ordered `member_ids`, a `manifest_hash` sealing both,
   verified the same way `PreRegistration`'s own seal is). `register()`
   creates or extends the manifest for a hypothesis's family in
   registration order. The registry persists `family_manifests` as a
   top-level list and, on every load, cross-checks each manifest's member
   set against the hypothesis records actually present in both directions:
   a family with records but no manifest, a manifest with no matching
   records, or any mismatch between the two, all raise
   `FamilyMembershipTamperedError`. This is what stops a hypothesis record
   being deleted from `records` to shrink a family and inflate the
   survivors' BH power - deletion is now visible as tampering rather than
   silent.

3. **State hash chain.** New `StateTransition` dataclass and
   `_fold_state_chain()` helper (Merkle-style running fold: each link hashes
   the previous link's hash together with its own content). Every
   `HypothesisRecord` now carries `state_chain` (the ordered transitions,
   starting from a genesis link `None -> REGISTERED`) and
   `state_chain_hash` (the fold's final hash). `HypothesisRecord.initial()`
   builds the genesis link at `register()`; `HypothesisRecord.
   transitioned_to()` extends and reseals the chain at every subsequent
   state change (`advance()`, the TEST-segment auto-transition inside
   `record_evaluation()`, and `adjudicate_family()`'s promotion/rejection).
   `verify_state_chain()`, run on every load, checks: the chain is
   non-empty; the recomputed fold hash matches the stored one; the first
   link starts at genesis and lands on REGISTERED; each later link
   continues from the previous link's `to_state`; each link beyond genesis
   is a legal `research.lifecycle` transition; and the final link's
   `to_state` equals the record's stored `state`. That last check is the
   one that catches the concrete failure named in the brief: a hand-edited
   `state: "CANDIDATE"` with no matching chain link now fails to load
   instead of loading as promoted.

## Files changed

- `research/hypothesis_registry.py`:
  - `REGISTRY_FORMAT_VERSION` 2 -> 3.
  - New: `FamilyMembershipTamperedError`, `StateChainError`,
    `StateTransition`, `_fold_state_chain()`, `FamilyManifest`.
  - `HypothesisRecord`: new fields `state_chain`, `state_chain_hash`; new
    `initial()` classmethod, `transitioned_to()` instance method,
    `verify_state_chain()`; `as_dict()`/`from_dict()` updated (both new
    fields required on load, no default).
  - `HypothesisRegistry`: new `self._family_manifests`; `_load()` rewritten
    per items 1-2 above; `_save()` persists `family_manifests`; new
    `family_manifest()` accessor; `register()`, `advance()`,
    `record_evaluation()`, `adjudicate_family()` updated to build/extend
    manifests and to route every state change through `transitioned_to()`
    instead of constructing `replace(record, state=...)` directly.
  - `__all__` extended with the five new names.
- `tests/test_research_hypothesis_registry_hardening.py` (new, 26 tests):
  6 for truncated-file refusal (missing/non-list `records`, missing/non-list
  `family_manifests`, non-object payload, and the one legitimate empty-file
  case: a registry that was never written to); 9 for family manifest
  sealing (ordered manifest construction, reload survival, a deleted member
  caught, a tampered manifest hash caught, a *self-consistent forged*
  manifest still caught by the records cross-check, a record spliced in
  outside `register()` caught, an orphaned manifest caught, plus two
  `FamilyManifest` unit-level guards); 11 for the state chain (genesis link
  on registration, full-lifecycle chain growth to CANDIDATE, reload
  survival, the hand-edited-`state`-with-no-link case, a tampered chain
  hash, a self-consistent-but-illegal forged chain, a discontinuous chain,
  an empty chain, a missing `state_chain` key, and a genesis link that lands
  somewhere other than REGISTERED).
- `tests/test_research_hypothesis_registry.py`: one assertion updated
  (`"expected 2"` -> `"expected 3"` in
  `test_a_format_version_1_registry_is_refused`) - the version-1-refusal
  behaviour itself is unchanged, only the current format version the error
  message names.
- `tests/test_research_hypothesis_checks.py`: one test renamed and its
  literal updated (`test_the_registry_writes_the_version_2_format` ->
  `test_the_registry_writes_the_current_format_version`, asserting `== 3`
  instead of `== 2`) - same reasoning.

## Architecture decisions

- **Threat model unchanged from the existing seal.** `FamilyManifest` and
  the state chain are tamper-*evident* via SHA-256 self-consistency, the
  same posture `preregistration_hash` already holds - they catch an
  accidental or careless edit (or a naive delete), not a sophisticated
  attacker who forges an entire new internally-consistent structure with
  full file write access. No HMAC or secret-key infrastructure exists in
  this codebase to do better, and introducing one was out of scope for this
  package. Both new mechanisms therefore layer a second, independent check
  beyond hash self-consistency where one was cheaply available: the family
  manifest is cross-checked against the actual records (catching a
  self-consistent forged manifest, per
  `test_a_self_consistent_forged_manifest_is_still_caught_by_cross_check`),
  and the state chain is re-validated against `research.lifecycle`'s legal
  transitions (catching a self-consistent forged chain, per
  `test_a_forged_but_illegal_chain_is_caught`).
- **`transitioned_to()` only records, it does not gate.** All three call
  sites (`advance`, `record_evaluation`, `adjudicate_family`) still call
  `research.lifecycle.validate_transition()` before invoking it, exactly as
  before this package. This mirrors the pre-existing division between gate
  and bookkeeping already used for `preregistration_hash`.
- **In-memory/disk divergence on a failed `_save()` is unchanged, not
  fixed.** `register()`, `advance()`, `record_evaluation()`, and
  `adjudicate_family()` all mutate `self._records` (and now
  `self._family_manifests`) before calling `_save()`; if `_save()` raises,
  the in-memory state was already diverging from disk before this package
  and still does. This was not introduced by this work and fixing it was
  not requested; flagged here as a pre-existing property, not a new risk.
- **No power analysis / p-value procedure / explicit two-gate record.**
  Confirmed still out of scope per the brief; not touched.

## Tests

`pytest tests/test_research_hypothesis_registry.py
tests/test_research_hypothesis_registry_hardening.py
tests/test_research_hypothesis_checks.py tests/test_research_splitting.py
tests/test_research_multiple_testing.py tests/test_research_lifecycle.py
tests/test_research_isolation.py tests/test_research_evidence_bridge.py
tests/test_research_market_data_bridge.py
tests/test_research_timestamp_split_binding.py`
→ **480 passed**, 0 failed (454 pre-existing + 26 new).

Full-suite regression (`pytest tests/ -q`, run once after both Part G and
Part I were complete, on the final code state):
**3999 passed, 1 failed**, 337.14s. The one failure,
`tests/architecture/test_forbidden_layer_imports.py::test_forbidden_layer_imports`
(a forbidden `atlas_finance/market_data/contracts.py -> atlas_finance/__init__.py`
/ `-> atlas_finance/market_data/__init__.py` dependency edge), was verified
**pre-existing and unrelated to this session**: `git stash` (removing every
change from both Part G and Part I) and re-running that one test in
isolation reproduces the identical failure and identical two-edge message
against the unmodified base commit. It touches `atlas_finance/`, which
neither part of this session's work imports or modifies. Not investigated
further as out of scope for both parts' SCOPE/OUT-OF-SCOPE boundaries.
The brief's stated baseline was "3961 passed / 1 failed (known Group B2)";
this session added 40 new tests (14 in Part G, 26 in Part I). The measured
total (4000 collected) does not arithmetically reconcile exactly against
that stated baseline (3962) plus 40 — UNKNOWN why, not independently
re-verified in this session since the pre-existing-failure check above
already isolates the one actual failure to a cause outside this session's
diff. Flagged rather than silently assumed away.

## Current state

`core/`, `risk/`, and `execution/` were not touched (confirmed by `git diff
--stat` against this branch's prior commit, see below). The three bridges
in `core/` that read `HypothesisRegistry` output
(`research_evidence_bridge.py`, `research_market_data_bridge.py`,
`research_timestamp_split_binding.py`) were checked and do not construct
`HypothesisRecord` directly or otherwise assume the old stored shape; they
read `preregistration_hash` via `getattr` and are unaffected.

## Known issues

None found.

## Risks

None introduced beyond the pre-existing `_save()`-failure divergence noted
above, which this package did not change.

## Remaining work

- Governance registration for this format-version bump and the two new
  hardening mechanisms was not performed in this session (no governance
  registry entry was added). Flagged for the owner alongside Part G's
  deferred governance-authorization item.
- Items still explicitly deferred per the original brief: power analysis,
  the p-value procedure, and an explicit statistical-vs-economic two-gate
  record.
- Leakage-controls-beyond-purge-and-embargo (item 7 in the prior checkpoint)
  was not investigated in this session; still UNKNOWN.

## Next exact action

Owner decides whether this format-version bump and the two new hardening
mechanisms need a governance registry entry before being considered closed,
and whether/when to schedule the deferred power-analysis and p-value-
procedure design decisions.
