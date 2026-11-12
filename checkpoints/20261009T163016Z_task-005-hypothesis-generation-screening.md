# ATLAS CHECKPOINT — Task 005: Hypothesis Generation & Screening Pipeline (2026-10-09)

**Status: IMPLEMENTED AND VERIFIED.**
- Third independent review: PASS.
- Full suite green.

This file grants no authority. Authority stays:
- `production_authority=NONE`
- `live_authority=DENIED`
- `phase_5_10_authority=NONE`

Predecessor: `20261009T153130Z_p4-closure-004-remediation-verified.md`.

## Objective
Implement Task 005 under the owner's brief and the canonical Phase 4 sealing and evidence rules.

## Governance (registry v5.88, committed separately before the implementation)
- **CONFLICT recorded and resolved.** The brief stated "Phase 4 CLOSED under v5.88", but no v5.88 existed in the repository. The owner then decided in session that the agent drafts v5.88.
- **v5.88** (`governance/current/ATLAS_MILESTONE_REGISTRY_v5.88.json`, sha256 `f0f5fffc…`) is a successor of v5.87 (supersedes_sha256 `1814d0f0…`). It records:
  - **PHASE_4_RESEARCH: CLOSED (P4-8).**
    - P4-7 is satisfied by owner acceptance of the round-7 subagent review.
    - Accepted residuals and the open R7-1..R7-4 items are listed.
    - N-4 and the new on-disk formats are UNKNOWN.
  - **Task 005 redefinition.** The previous Task 005 was MEM-005 Persistent Memory. It is now Hypothesis Generation & Screening. MEM-005 is deferred and persistent memory stays NOT_AUTHORIZED. Roadmap placement: Phase 4 research department (§11).
  - **GRANT-TASK-005-HYPOTHESIS-GENERATION-SCREENING-RESEARCH-ONLY**, with the owner's design decisions:
    - screening runs before registration, on historical data only;
    - sealed variant arguments;
    - dedup against the canonical registry only.
  - Scope, residuals, and the `known_limits_and_residuals` list.
- **Tasks 006–015:** their Phase 4 prerequisite is satisfied, but each still needs its own grant.

## Files (implementation commit)
- `research/screening.py`
  - `validate_candle`, shared with `strategy_compare`.
  - `ScreeningSpec`: data must end before registration.
  - Fast-fail stages: integrity → completeness → zero-volume → minimum trades (`NOT_RUN` does not pass).
- `research/hypothesis_generation.py`
  - `Template`, `generate`, `normalize_args`. Knobs are exactly the owner's list plus the fill knobs; defaults and `-0` are dropped; every variant must fill like the reference.
  - `study_spec` / `sealed_variant_args` (with digest).
  - `idea_fingerprint` covers what an idea trades, not its names or evaluation settings.
  - `run_pipeline` does a read-only dedup snapshot, then screens, then registers under the lock: re-read, dedup re-check, real-clock window check, id allocation, family plan/lineage, resume from the sealed plan, `BH`/`BONFERRONI` sealing.
  - `family_completeness`.
- `research/registry_lock.py`
  - Exclusive sidecar lock (`O_CREAT|O_EXCL`) on the resolved path.
  - A stale lock is never broken; `RegistryLockError(OSError)` is treated as transient.
- `tools/hypothesis_pipeline.py`: command-line entry point.
  - Canonical registry only.
  - Realistic reference and fills are forced.
  - Historical download ends at registration.
  - Quick exploratory replay; dry run.
- `tools/strategy_compare.py`
  - `study_parameters(..., variant_args=)`, `sealed_variants`.
  - `_check_reference`: the realistic reference and realistic fills for every variant, checked at bind and at verify.
  - A registered generated study runs exactly its sealed arguments; `--only` is refused.
  - `start_study_run` re-reads and advances under the lock.
  - `_candle_open` delegates to `validate_candle`.
  - R5-2 docstring narrowed.
- `tests/research/__init__.py`, `tests/research/test_task005_hypothesis_pipeline.py`: 88 tests. They cover:
  - generation, the sealed-window rules and dedup;
  - all screening stages and the never-screen-sealed-data rule;
  - registration;
  - the crash, write-failure, lock and resume paths;
  - multiple testing: BH/Bonferroni sealing and Monte Carlo error control;
  - one end-to-end generated → registered → single sealed run → verified cycle;
  - every review finding.

## Architecture decisions
1. **Screening placement.** Screening happens before registration, on historical data only. The sealed future window stays out of sample. Screening output is never evidence.
2. **Sealed arguments.** Generated studies seal their exact replay arguments plus a digest. The runner executes exactly those, with the realistic reference and fills enforced. This closes R5-2 for generated studies.
3. **Idea identity.** It covers universe, timeframe, the EXP-001 floor, reference arguments and the set of variant arguments. Evaluation settings and names are excluded, so re-evaluating an idea counts as EXISTING ("zaten hafızada").
4. **Registry writes from tools take an exclusive lock and re-read inside it.** The registry module itself is unchanged.
5. **One family per template.** It resumes only from its sealed plan; a different plan is refused.

## Independent reviews (fresh-context subagents, read-only)
- **Review 1: FAIL.**
  - F-1 HIGH: lost update.
  - F-2 MEDIUM: dedup bypass.
  - F-3 MEDIUM: weaker reference.
  - F-4 and F-5 LOW, F-6 INFO.
  - All fixed.
- **Review 2: FAIL.**
  - N-1 MEDIUM: cheaper variant fills.
  - Residuals of F-2, F-4 and F-5; N-2 and N-3 INFO.
  - All fixed or documented.
- **Review 3: PASS.**
  - LOW items applied after the PASS, as the reviewer remediated them:
    - NEW-1: `exp001` must be a bool, and `-0` normalizes to the default.
    - NEW-2/NEW-3: the ineffective `regime_bar_check` guard, which was also outside the declared scope, was reverted. Replaced by `family_completeness` plus a caveat in the report and v5.88.
    - NEW-4: knobs restricted to the owner's list.
  - These post-PASS changes are covered by tests and the full suite, not by a fourth review.

## Tests (Python 3.13, `-p no:cacheprovider`)
- **Full suite: 10300 passed, 0 failed, 12 skipped** (Windows-only), exit 0. Baseline was 10209.
- Focused, architecture and governance tests: 405 passed.

## Residuals / known limits (recorded in v5.88)
- The daily agent does not run generated studies; they are run manually.
- Names-only studies are not matched against generated ideas.
- A partly registered family must be resumed before adjudication. `family_completeness` reports this, but nothing enforces it.
- Direct registry API writes that bypass the lock are unguarded.
- Unchanged Phase 4 residuals:
  - unkeyed hashes;
  - price authenticity;
  - cross-family selection.

## Next exact action
Owner review of Task 005. Tasks 006–015 each need their own grant before implementation.
