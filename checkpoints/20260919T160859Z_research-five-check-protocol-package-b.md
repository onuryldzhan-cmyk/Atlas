# ATLAS CHECKPOINT — Package B: five-check validation protocol

**UTC:** 2026-09-19T16:08:59Z
**Branch:** `research/edge-validation`
**Commit:** `a9dea0d` (parent `b9c96eb`)

## Objective

Extend `research/hypothesis_registry.py` to the owner's full five-check
validation spec: a `CheckName`/`CheckVerdict`/`CheckResult` data model, a sealed
`check_plan` on every pre-registration, conjunctive verdict adjudication with
NB-4/NB-5 analogue guards, and Benjamini-Hochberg ordering preserved so that
check gating applies strictly *after* the correction — all under a clean
`REGISTRY_FORMAT_VERSION` 1 → 2 break (M0) with no version-1 loading path.

Scope was extended mid-package, on owner instruction, to close two real gaps the
first independent audit found: make sealed check thresholds **binding** on the
verdict rather than documentary (audit finding F-3), and close the `advance()`
promotion bypass. Documentation of the whole protocol was added in the same
package, and everything was committed as one commit.

## Completed

- **Five-check data model.** `CheckName` (BACKTEST, WALK_FORWARD,
  OUT_OF_SAMPLE, COST_ADJUSTED, MONTE_CARLO — closed set), `CheckVerdict`
  (PASS/FAIL, deliberately no third value), `CheckPlanStatus`
  (INCOMPLETE/COMPLETE_PASS/COMPLETE_FAIL), frozen `CheckResult`
  (`check_name, verdict, statistic_value, p_value, effect_size,
  threshold_applied, payload, recorded_at`), `CheckPlan`, and
  `CheckAdjudication`. `EvaluationRecord` gained `checks: tuple[CheckResult, ...]`.
- **Check-to-segment binding.** `CHECK_SEGMENTS` maps BACKTEST→TRAIN,
  WALK_FORWARD→CALIBRATION, and OUT_OF_SAMPLE/COST_ADJUSTED/MONTE_CARLO→TEST.
  All three TEST checks ride on the single irreversible TEST evaluation;
  `EvaluationRecord` refuses a check attached to the wrong segment.
- **Sealed `check_plan`.** Required field on `PreRegistration` (no default),
  included in `sealed_payload()`, with per-check parameter schema validation and
  type coercion so an identical plan cannot seal two ways.
- **M0 version bump.** `REGISTRY_FORMAT_VERSION = 2`, no version-1 loading path,
  `_load`'s fail-closed version check unchanged.
- **Conjunctive adjudication.** `adjudicate_family` promotes only on
  `passes_fdr AND passes_alpha AND passes_effect AND passes_checks` — a hard
  AND, no weighting.
- **NB-4 analogue.** `adjudicate_checks` iterates the sealed plan and looks each
  required check up among results; an absent required check is a FAIL, never a
  skip.
- **NB-5 analogue.** `required_check_count` is read from the sealed plan and is
  the only denominator; `len(recorded)` is never a divisor.
- **F-3 — sealed thresholds made binding.** `_CHECK_THRESHOLD_PARAMETER` maps
  each check to its sealed comparison threshold (BACKTEST→`minimum_effect_size`,
  WALK_FORWARD→`minimum_fraction_passing`, COST_ADJUSTED→`cost_bps`,
  MONTE_CARLO→`percentile_threshold`, OUT_OF_SAMPLE→none).
  `CheckPlan.threshold_for()` exposes it; `_verify_threshold_binding()` raises
  `ThresholdBindingError` on mismatch. Enforced on **both** the write path
  (`record_evaluation`) and the load path (`verify_recorded_checks`). A check
  with no sealed threshold must declare none.
- **`advance()` promotion bypass closed.** `advance()` refuses
  `(TESTED, CANDIDATE)` by comparing against lifecycle's
  `FAMILY_ADJUDICATED_TRANSITION` — previously declared and enforced nowhere —
  raising `FamilyAdjudicationRequiredError` before `validate_transition`.
- **Earlier audit fixes (first audit round), also in this commit.** Load path now
  re-applies the write path's check invariants (`verify_recorded_checks`),
  closing an append-a-duplicate verdict-laundering route; duplicate check results
  fold conservatively toward FAIL; malformed stored payloads raise
  `RegistryError` rather than raw `TypeError`/`ValueError`; identifier
  parameters must be `str`.
- **Documentation.** `docs/research/0001-hypothesis-registry-design.md` gained
  **Decision 5** (+181 lines) in the document's own `Decision N` / `###` style,
  plus an additive amendment note under Status and three new Open items.

## Files changed

Captured from `git show --stat a9dea0d` and `git status --short` at checkpoint
time.

Committed in `a9dea0d` (5 files, +2551 / −7):

| File | Change |
|---|---|
| `research/hypothesis_registry.py` | +819 / −7 |
| `research/__init__.py` | +24 |
| `tests/test_research_hypothesis_checks.py` | new, 1463 lines |
| `tests/test_research_hypothesis_registry.py` | +71 |
| `docs/research/0001-hypothesis-registry-design.md` | +181 |

`research/lifecycle.py` was **not** modified.
`tests/test_research_isolation.py` was **not** modified.

Working tree after the commit contains only pre-existing, unrelated paths that
predate this session and were deliberately left unstaged:
`.claude/agents/atlas-db-reader.md` (modified);
`REM-001_CANONICAL_COMPONENT_MATRIX.json`, four `checkpoints/*.md`,
`docs/adr/0007-durable-state-relocation-off-onedrive.md`, two
`governance/ATLAS_REM001_*.md`, and
`governance/current/ATLAS_MILESTONE_REGISTRY_v4.33.json` (untracked).

## Architecture decisions

1. **`research/lifecycle.py` left unchanged.** Check progress is representable
   as data on existing evaluations; no new state was needed. The segment-access
   rules already give the protocol its ordering: BACKTEST and WALK_FORWARD score
   segments readable only before TESTED, so consuming the test read first makes
   them permanently unrecordable and the hypothesis permanently unpromotable.
   A new state would have diluted a ten-state machine whose discipline (monotone,
   no LIVE/PRODUCTION/DEPLOYED) is load-bearing.
2. **Clean break, no v1 compatibility path.** The seal covers `check_plan`, so no
   v1 payload can produce a valid v2 seal. Verified that no registry data file
   exists anywhere (repository or `C:\AtlasState`) and that nothing outside
   `tests/` constructs `HypothesisRegistry`, so there was no data to migrate.
3. **Duplicate check results are refused, not overwritten.** Follows the existing
   single-use TEST evaluation convention. An idempotent overwrite would let a
   FAIL be replaced by a PASS.
4. **Every write-path invariant is re-checked on load.** Evaluations are outside
   the seal, so an invariant enforced in only one place holds only until the next
   restart. This is now the standing rule for this module.
5. **`advance()` refusal needs no extra mechanism.** `adjudicate_family`
   validates and writes `_records` directly and never calls `advance()`, so a
   plain refusal in `advance()` cannot affect the legitimate path. No guard flag,
   internal entry point, or transition-reason argument was introduced.
6. **Check plans are normalised before sealing.** Required checks are ordered
   into `CHECK_ORDER` and parameters coerced to settled types, so two
   semantically identical plans seal identically.

## Tests

- **Full suite, run synchronously on the final pre-commit disk state:
  `3064 passed`, 0 failed, in 268.77s** (`python -m pytest tests -q` with an
  ASCII `--basetemp` and `-p no:cacheprovider`).
- Baseline before Package B was `2921 passed`. Progression across the package:
  2921 → 3030 (implementation) → 3038 (first-audit fixes) → 3064 (F-3 +
  `advance()` closure, 26 new tests).
- Research modules: 131 pre-existing (121 + 10 isolation) → 274.
  `tests/test_research_hypothesis_checks.py` contributes 141;
  `tests/test_research_hypothesis_registry.py` 57.
- `tests/test_research_isolation.py`: **10 passed with zero modifications to the
  file**, confirmed by `git diff --exit-code`.
- Discriminating tests worth naming for a future session:
  `test_the_bh_family_size_is_unaffected_by_check_verdicts` (compares every BH
  input and output bit-for-bit across two families differing only in check
  verdicts), `test_removing_evidence_can_only_make_the_verdict_less_permissive`
  (all 32 subsets of the evidence), `test_the_audit_reproduction_no_longer_promotes`,
  and `test_a_failing_verdict_cannot_be_re_rolled_by_appending_a_passing_copy`.

## Current state

Package B is complete and committed as `a9dea0d` on `research/edge-validation`.
Nothing is pushed; there is no remote. The working tree is clean of
Package B content.

The CRITICAL-task final gate was completed in full:
IMPLEMENT → TEST → SELF-REVIEW → REGRESSION → INDEPENDENT AUDIT → FIX →
RE-TEST → FINAL GATE, across two audit rounds.

**Session note on process.** The first independent audit ran as a background
subagent and returned findings normally. The second audit round was disrupted:
the session entered a stuck background-task polling loop waiting on a subagent
that never returned, and the owner interrupted and stopped it. The second audit
was then re-run **synchronously, as direct tool calls in a single turn**, with
no background task and no notification polling. That synchronous audit is the
one whose results are recorded below. For future sessions on this repository,
prefer running verification work synchronously in-turn over spawning a
background agent and waiting on a notification.

## Known issues

Recorded, not fixed. None blocks the package.

1. **Non-float numeric types accepted for `threshold_applied`.**
   INFORMATIONAL. `CheckResult` accepts `'0.5'`, `Decimal('0.5')`,
   `Fraction(1, 2)` and stores them in memory as given. The binding comparison is
   numeric, so this **cannot** loosen the gate, and `as_dict()` normalises to
   `float`, so the value self-heals on the next round trip (verified: on-disk
   `0.5`, reloads as `float`). A non-numeric string raises raw `ValueError`
   rather than `RegistryError` on direct construction. Verified to be a
   **pre-existing convention** of this module —
   `EvaluationRecord.statistic_value` behaves identically and predates Package B.
2. **A record's `state` is not sealed.** Pre-existing. `state` is mutable by
   design, so hand-editing the stored `state` to `CANDIDATE` loads as a promoted
   record regardless of p-value or checks. The `advance()` closure addresses the
   in-process route only; the doc's Decision 5 heading is deliberately scoped
   "in process" for this reason. Recorded as Open item 8 in
   `docs/research/0001-hypothesis-registry-design.md`.
3. **Evaluations are not tamper-evident.** Pre-existing and documented. An
   in-place edit of a single stored verdict (`FAIL` → `PASS`) remains
   undetectable; verified to behave exactly as documented, no better and no
   worse. Closing it needs a chained hash over the append-only log.
4. **Family membership is not sealed.** Pre-existing, from the first audit
   (F-4). Deleting a losing hypothesis from the stored file shrinks `m` and
   relaxes every survivor's BH threshold. Recorded as Open item 6.
5. **A registry file with no `records` key loads as an empty registry.**
   Pre-existing, from the first audit (F-5). Recorded as Open item 7.
6. **Non-threshold sealed parameters are sealed but not bound.**
   `cost_model_id`, `null_model_id`, `window_count` and `trial_count` cannot be
   bound through `threshold_applied` alone; binding them needs fields on
   `CheckResult` that do not exist. Documented in Decision 5 as an explicit
   residual.

## Risks

- Items 2–5 above share one root cause: the seal binds the pre-registration, not
  the whole stored file. Anyone with write access to the registry JSON can still
  promote a hypothesis. This is acceptable for a single-operator research tool
  and is the correct scope for the current step, but it must not be mistaken for
  tamper-evidence over the whole file if `research/` ever gains a runtime driver
  or a second writer.
- `HypothesisRegistry` has no file locking. Verified that nothing outside
  `tests/` constructs it and nothing outside `research/` imports the package, so
  no concurrent writer exists today. That N/A expires the moment a runtime driver
  is added.
- `research/` remains L4 with zero first-party imports outside `research/`,
  enforced solely by `tests/test_research_isolation.py`; the architecture
  inventory tool still cannot see `research/` (ADR-0009, W1). A green
  architecture check remains silence about `research/`, not approval.
- No market data change: the Open items 1–4 of the original design note still
  stand, so **no hypothesis can be validly evaluated yet**. This package is
  infrastructure only and asserts no edge.

## Remaining work

- **Package C** — the L3 bridge from `research/` to the Evidence Store. Deferred,
  not started.
- **Package D** — the actual compute engines for walk-forward, Monte Carlo and
  cost modelling. Deferred, not started. `CheckResult` objects are currently
  constructed only in tests as plain data. Package D should read its thresholds
  from `CheckPlan.threshold_for()` rather than choosing them.
- Governance registration for Package B: **UNKNOWN — requires verification.** No
  governance record was created or updated in this session, and whether this
  milestone requires one was not determined.
- Optional follow-ups, owner's call: bind the non-threshold sealed parameters
  (needs new `CheckResult` fields); a chained hash over the append-only
  evaluation log, which would close Known issues 2, 3 and 4 together.

## Next exact action

Decide between Package C and Package D, and confirm whether Package B needs a
governance registry entry before the milestone can close. No code action is
pending on Package B itself; it is complete, committed, and green.

If the next session starts with Package D, the exact entry point is:
`CheckPlan.threshold_for(check_name)` in `research/hypothesis_registry.py` — the
compute engine reads its threshold there and echoes it back as
`CheckResult.threshold_applied`, or `record_evaluation` will refuse the result.
