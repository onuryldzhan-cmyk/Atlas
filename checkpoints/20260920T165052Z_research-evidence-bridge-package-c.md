# ATLAS CHECKPOINT — Research Evidence Bridge (Package C)

- **UTC:** 2026-09-20T16:50:52Z
- **Branch:** `research/edge-validation`
- **HEAD at start:** `894455d`
- **HEAD at end:** `e2b2c93`
- **Mode:** BUILD
- **Classification:** CRITICAL (governance record committed; evidence/confidence
  boundary), full critical-task final gate applied.

## Objective

Commit the uncommitted governance registry v4.35, verify under it that Package C
is authorized, and then implement `core/research_evidence_bridge.py` per ADR-0009
with its direct unit and integration tests.

## Completed

1. **Step 0 — governance commit.** `governance/current/ATLAS_MILESTONE_REGISTRY_v4.35.json`
   staged by explicit path (no `git add -A`), JSON-validated, committed alone as
   `dfa1251`. Nothing else was staged; every other untracked/modified path was
   left exactly as found.
2. **Step 1 — governance check.** Read v4.35 directly. `RESEARCH-EDGE-VALIDATION`
   carries `continuation_authorized: true`,
   `continuation_authorization_state: GRANTED_SCOPED_TO_PACKAGE_C_ONLY`, and
   `authorized_deliverable: core/research_evidence_bridge.py` under
   `research_edge_validation_package_c_continuation_authorization`. No ambiguity
   or contradiction with the task prompt. Gate cleared.
3. **Step 2 — implementation.** `core/research_evidence_bridge.py` plus
   `tests/test_research_evidence_bridge.py`, committed as `e2b2c93`.

## Files changed

| File | Commit | Change |
| --- | --- | --- |
| `governance/current/ATLAS_MILESTONE_REGISTRY_v4.35.json` | `dfa1251` | added (4670 lines) |
| `core/research_evidence_bridge.py` | `e2b2c93` | added |
| `tests/test_research_evidence_bridge.py` | `e2b2c93` | added |

Nothing else was touched. `research/`, `data_layer/evidence_store.py`,
`ai/core/atlas_brain.py`, `core/application.py`, ADR-0009, the architecture map
and all risk/capital/execution code are byte-identical to `894455d`.

## Architecture decisions

- **Verdict object is `CheckAdjudication`, not `FamilyVerdict`/`HypothesisVerdict`.**
  ADR-0009 (2026-09-19) named prospective types; Package B (`a9dea0d`) actually
  shipped `CheckAdjudication`, produced by `HypothesisRecord.adjudicate_checks()`.
  Repository wins over document (see CONFLICT below). ADR-0009 was not edited.
- **Store injected as a constructor parameter typed `Any`, never imported.**
  Mirrors `ai/core/atlas_brain.py`, which holds the injected `EvidenceStore` as
  `Any | None` and imports only `ClaimSource` from `data_layer/contracts.py`.
  Verified with `classify_module`: the bridge is L3, `research/` L4,
  `data_layer/contracts.py` L1, `data_layer/evidence_store.py` L2; L3's allowed
  dependencies are `stdlib, L0, L1, L2, L4`. No reverse dependency exists —
  `research/` never learns the store exists.
- **Two deliberate, conservative divergences from AtlasBrain**, both because the
  bridge sits on no decision path: the store is *required* at construction (a
  bridge with no store is misconstructed, not degraded), and store failures
  *propagate* instead of being absorbed fail-open.
- **Confidence = `passed_check_count / required_check_count`**, exact `Decimal`,
  denominator taken from the sealed plan. The full adjudication (counts, missing
  checks, failed checks, status, seal hash, universe) is written into the claim
  payload and reason codes, so the ratio is never the only surviving record.
- **Assertion time is derived from the record** (latest recorded check, falling
  back to `preregistered_at`), never `datetime.now()`. The store derives
  `claim_id` from the assertion time, so a wall-clock read would defeat its
  idempotency and file the same verdict twice.
- **Subject scope** is `SYMBOL` for a single-symbol universe and `MARKET` for a
  wider one; picking the first symbol of a multi-symbol universe would file the
  claim against a subject it was never tested on. `claim_kind` is `OTHER`: a
  protocol outcome is not a market opinion.
- **W1 preserved.** Nothing in the runtime closure imports the bridge, so
  `research/` stays out of the closure. Wiring into `core/application.py` (W2)
  remains deferred and was not done.

## NB-4 / NB-5 at this boundary

- **NB-4** — a required check with no recorded result adjudicates as *missing*,
  so the denominator holds while the numerator falls: confidence is monotone
  non-increasing under removal of evidence. Tested over **all 32 subsets** of the
  five checks, not a chosen few.
- **NB-5** — the denominator is the sealed plan's `required_check_count`, never
  `recorded_check_count`. Pinned by a test asserting that two-of-five recorded,
  both passing, records 0.4 and not 1.0.
- **Additional guard** — an adjudication whose counts do not account for every
  required check (`passed + missing + failed != required`) is refused outright,
  because such a verdict would be written at a confidence its evidence does not
  support.

## Tests

- `tests/test_research_evidence_bridge.py` — **78 passed** (unit with a
  recording stand-in store; integration against a real `EvidenceStore` on
  `tmp_path`, covering real verdict → real `ClaimSource` → real `record_claim`,
  read-back, idempotent re-submission, two bridges agreeing on one claim id, and
  a changed verdict landing as a new claim rather than an overwrite).
- `tests/test_research_isolation.py` (C2 guard) — **10 passed**, unchanged.
- `python tools/build_architecture_inventory.py check` —
  `OK: runtime closure matches (105 modules)`,
  `OK: architecture map assigns every live module a layer (105 modules)`,
  `OK: no forbidden dependency edges`.
- **Full regression suite: `python -m pytest tests` → 3142 passed in 345.50s.**
  Zero failures, zero skips, zero xfails reported. No test was modified,
  weakened or skipped.

All runs used an ASCII `--basetemp` under the session scratch directory. No test
touched a configured durable root or real runtime state.

## Current state

Branch `research/edge-validation` at `e2b2c93`, working tree carrying only the
pre-existing untracked artifacts and the pre-existing modification to
`.claude/agents/atlas-db-reader.md`, none of which this session touched.

## Known issues

- **CONFLICT (document vs repository), severity INFORMATIONAL.**
  - *Expected:* ADR-0009's integration diagram says `research/hypothesis_registry.py`
    "returns FamilyVerdict / HypothesisVerdict value objects".
  - *Actual:* no such types exist. The five-check output is `CheckAdjudication`,
    returned by `HypothesisRecord.adjudicate_checks()` and exported in
    `research/hypothesis_registry.__all__`.
  - *Evidence:* `research/hypothesis_registry.py:919` (`CheckAdjudication`),
    `:1003` (`adjudicate_checks`), `:1464-1493` (`__all__`); no match for
    `FamilyVerdict`/`HypothesisVerdict` anywhere in the repository.
  - *Impact:* naming only. ADR-0009 predates Package B and described a
    prospective shape; the L3/L1/L2 edges, the injection pattern and the
    one-way direction it settles are all unchanged and were implemented as
    written.
  - *Decision required:* whether to record this in a successor ADR. **Not done
    here** — v4.35 explicitly lists `ANY_EDIT_TO_ADR_0009_OR_ANY_OTHER_ADR` as
    not authorized.
- Everything ADR-0009 already records as open is unchanged: the ancestor-edge
  gap in `find_forbidden_edges`, the dynamic-import blind spot in the C2 guard,
  and the seal-versioning question.

## Risks

- The bridge is **unreachable from any entry point** by design. It is therefore
  covered only by its own tests, and the architecture gate still cannot see
  `research/`. The first wiring attempt (W2) must re-run the closure artifacts
  and take the W1/W2 decision explicitly.
- `agent_version` is the registry's `REGISTRY_FORMAT_VERSION` (currently `2`). A
  future format bump changes the claim identity for the same verdict, which is
  intended but worth stating.
- No live, production or authority effect. `production_authority=NONE`,
  `live_authority=DENIED`, paper-only.

## Remaining work

- Package D and every other future commit on this branch remain **unauthorized**;
  v4.35 requires a new versioned successor record for each.
- The 16 non-research commits in `a8cffa3..a9dea0d` remain flagged as having had
  no independent correctness review. Untouched here.
- W2 (wiring the bridge into `core/application.py`) still deferred.

## Next exact action

Report to the owner and stop. Do not begin Package D, do not wire the bridge into
`core/application.py`, and do not audit the 16-commit blast radius without a new
governance record authorizing it.
