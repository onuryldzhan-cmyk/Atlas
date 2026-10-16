# ATLAS CHECKPOINT — Task 011: Strategic Scout & External Research Intelligence

## Objective
Complete Task 011 under GRANT-TASK-011-STRATEGIC-SCOUT-OFFLINE-RESEARCH (registry v5.95). The owner's
directive "Task 011 Resolution & Sealing Protocol" set the requirements:
- fix the 28 failing tests in the inherited work in progress;
- keep the six modes deterministic;
- the 7-step gate never auto-accepts;
- unverified trader claims are INSUFFICIENT_EVIDENCE;
- every output is EXPLORATORY;
- the full suite passes;
- an independent review finds 0 BLOCKING / 0 HIGH / 0 MEDIUM;
- two commits: v5.95 alone, then Task 011.

The work is offline and research-only.

## Completed
- **Taking over the work in progress.** The Task 011 work found uncommitted in the tree (author UNKNOWN,
  recorded in v5.95) was taken over on the owner's instruction.
- **The 28 failures** had two causes:
  - The registry clock moved on: the test module now freezes `research.hypothesis_registry`'s clock at
    2026-09-15 with a fixture. `research/hypothesis_registry.py` is unchanged.
  - Two stale tests now assert the current, stricter behaviour. No assertion was weakened.
- **Hardening, in research/scout/ only:**
  - Step 6 re-reads the hypothesis registry from disk, digests the file before and after the read, and
    requires all of the following:
    - binding to the candidate;
    - a state of CANDIDATE or higher;
    - COMPLETE_PASS checks;
    - pre-registration and adjudication times no later than as_of.
  - Malformed, deeply nested or unreadable inputs and registry files become per-record refusals instead
    of aborting the run.
  - Log reasons are escaped plain text.
  - The findings order is deterministic.
  - Reports and ledger entries re-check PENDING findings and step-6 timing when they are built and when
    they are read.
- **Registry v5.95** (successor of v5.94, built by a scratch builder that asserts every v5.94 key is
  preserved):
  - Task 010 CLOSED; Task 011 defined, granted and ACTIVE.
  - Conflicts C-1..C-3, the unknowns and independent reviews 22–29 are recorded.
- **Packaging maps:** the REM-001 maps were regenerated.

## Files changed
- **Commit 1:** governance/current/ATLAS_MILESTONE_REGISTRY_v5.95.json.
- **Commit 2:**
  - research/scout/__init__.py, acceptance_gate.py, provenance.py, strategic_scout.py,
    trader_reputation.py (new)
  - tests/research/test_task011_strategic_scout.py (new, 236 test cases)
  - packaging/REM-001_IMPORT_GRAPH.json, packaging/REM-001_RUNTIME_CONSTRUCTION_PATHS.md,
    packaging/REM-001_STATE_AUTHORITY_MAP.md (regenerated)
  - this checkpoint
- **Unchanged:** research/hypothesis_registry.py, and every runtime module. The scout is not in the
  runtime closure, and only research/scout and its test file import it.

## Architecture decisions
- **There is no ACCEPTED state.** The best outcome is PENDING_OWNER_REVIEW for a candidate and
  RESEARCH_CANDIDATE for a trader claim. Neither carries authority; the next step is Task 005
  preregistration plus Task 006 adjudication.
- **Measurable value (step 6)** comes only from an adjudicated hypothesis in the on-disk registry that is
  bound to the candidate. In-memory or borrowed hypotheses are refused.
- **The ScoutLedger is append-only:**
  - `.jsonl` files only;
  - symlinks, hard links and runtime roots are refused;
  - appends hold the registry write lock;
  - the whole chain is re-verified on every append.

## Tests
- **Full suite:** 10866 passed, 12 skipped, 0 failed, from the final run before commit on 2026-10-16.
  That is 241 more than the Task 010 baseline of 10625: 236 are the Task 011 test cases. No other test
  file changed; the remaining 5 cases come from existing tests and are not individually attributed.
- **Targeted suites** (Task 011, tests/architecture, tests/test_research_isolation.py): green.
- **Mutation testing:** every fix was mutation-checked. The remaining survivors are recorded in v5.95,
  either as equivalent or as defensive or unreachable branches.

## Reviews (fresh context, red team, threshold 0 BLOCKING / 0 HIGH / 0 MEDIUM)
- **Reviews 22–28 — FAIL.**
  - Each found a MEDIUM:
    - untested no-lookahead rules;
    - an unreachable-claim error;
    - registry-load exceptions;
    - untested RESEARCH_CANDIDATE conditions;
    - equivalent-mutant mislabels;
    - an untested naive pre-registration time;
    - an untested red-team mode wrongly called outcome-neutral.
  - Each was fixed, mutation-checked, corrected in the record, and re-reviewed.
- **Review 29 — PASS (0/0/0; 4 LOW, 2 INFORMATIONAL).**
  - L-1, L-2 and L-4 were fixed after the review with 11 test cases; no source changed.
  - L-3 is recorded: untested branches that can only make a result stricter.
  - Details are in v5.95 under task_011_reviews_v5_95.

## Current state
Task 011 is implemented and verified, and its milestone is ACTIVE; closing it is the owner's decision.
There is no effect on the paper runtime.

## Known issues / limitations (all recorded in v5.95)
- Seals are tamper-evidence, not authentication.
- Evaluation contents and check verdicts in the hypothesis registry are not sealed.
- Reports do not record the policy that produced them.
- The adequacy of the policy inputs (the verified-problem register, the licence allow-list and the
  reputation thresholds) is UNKNOWN until they are used.
- L-3 conservative-direction gaps remain untested.

## Risks
None to runtime trading. The scout is offline and grants no authority.

## Remaining work
- The owner closes Task 011.
- Task 012 (lean multi-agent hardening) was signed off for after this commit:
  - a DecisionEnvelope contract;
  - the slippage auditor, as flag + proposal only;
  - the macro observer, observe only with veto OFF;
  - registry v5.96.

## Next exact action
Start Task 012: inspect the Brain→MarketLoop decision path and draft v5.96 (close 011, grant 012). Show
the diffs to the owner before committing.
