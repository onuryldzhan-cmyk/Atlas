---
name: atlas-migration-safety
description: Walk a task that touches migration/schema/state-transition code and/or decision-intelligence/confidence-calculation code through CLAUDE.md's Financial/migration safety checklist and/or its NB-4/NB-5 regression checklist, and refuse to let the task be marked done until every applicable item is explicitly addressed or explicitly N/A with a stated reason. Use whenever a task touches either of those two areas.
---

# ATLAS MIGRATION SAFETY

Gate a task against CLAUDE.md's "Financial / migration safety" section and/or its "Known regressions to guard against" section (NB-4/NB-5). This skill does not advise — it blocks. A task in scope for either checklist is not done while any applicable item on that checklist has no explicit disposition.

## Applicability — which checklist(s) apply

- **Checklist 1 (Migration safety)** applies when the task touches a migration/schema/state-transition path — e.g., a database migration, a schema change, a persisted-state format change, a journal/ledger write path, or recovery/replay logic.
- **Checklist 2 (Decision-intelligence regressions)** applies when the task touches confidence/consensus/evidence-weighting logic — e.g., evidence aggregation, confidence scoring, or roster/consensus calculation.
- A task can trigger neither, one, or both. Evaluate each trigger independently against the task's actual content, not its title. If neither trigger is met, this skill has nothing to check for that task.

## Checklist 1 — Migration safety (CLAUDE.md "Financial / migration safety")

Every migration-touching change must be checked for each of the following 9 items:

1. **Idempotency** — can this change be applied more than once without corrupting state?
2. **Resume** — if interrupted partway, does it resume correctly rather than restart destructively or get stuck?
3. **Retry** — is retrying after failure safe, with no duplicate side effects?
4. **Sequence** — does correctness depend on a specific step sequence, and is that sequence enforced?
5. **Ordering** — are ordering guarantees preserved under concurrent or out-of-order operations?
6. **Duplicates** — can duplicate records/events/operations occur, and are they detected or prevented?
7. **Partial state** — is a partially-applied state detected and handled, rather than treated as complete or silently ignored?
8. **Conflicts** — are conflicting concurrent changes detected and resolved, rather than silently overwritten?
9. **Rollback/recovery** — is there a defined rollback or recovery path if the change fails partway?

Governing rule for all 9 items, quoted from the same CLAUDE.md section: **corrupted state must be detected and halted, never silently continued through.** No item above may be marked Addressed by a disposition that continues silently through detected corruption instead of halting.

## Checklist 2 — Decision-intelligence regressions (CLAUDE.md "Known regressions to guard against")

Decision-intelligence/confidence-calculation work must explicitly guard against both named regressions and carry test coverage for all 6 named scenarios:

1. **NB-4 (guard)** — removing evidence must not make the system less conservative; confidence must not rise when evidence is removed.
2. **NB-5 (guard)** — confidence calculation must use expected roster size as the denominator, not just current/surviving agent count, to avoid false full consensus when agents are missing.
3. **Test: missing evidence**
4. **Test: missing agents**
5. **Test: conflicting evidence**
6. **Test: low confidence**
7. **Test: unexpected roster**
8. **Test: malformed inputs**

## Operational rules

- **Two-form disposition only.** Every item's disposition is either **Addressed** — stating how (which test, which code path, which check) — or **N/A** — stating why it does not apply to this specific task. No other disposition is valid. A vague disposition ("looks fine," "probably OK") is not a disposition. Per CLAUDE.md's No Hallucination Policy, an unverified claim must be written as `UNKNOWN — requires verification`, not asserted as Addressed.
- **Blocks completion, not just advises.** A task in scope for a checklist is not done while any item on that checklist lacks an explicit disposition. This is the skill's purpose, per the task that created it — silent skipping is exactly what it exists to prevent.
- **Corrupted-state rule governs Checklist 1 throughout**, not just item 9 — see the governing rule stated under Checklist 1.
- **Both checklists run independently when both apply.** A change that is both migration-touching and confidence-calculation-touching (e.g., a migration to a confidence-calculation store) must clear both checklists in full; overlap between them is not grounds to shorten either one.
- **Conflict check performed against CLAUDE.md's source wording:** no ambiguity was found in either source section severe enough to let this skill diverge from CLAUDE.md over time. Both checklists are closed, countable lists (9 items; 8 items) rather than open-ended prose, and — unlike the checkpoint-storage-location gap resolved earlier, where CLAUDE.md specified required content but no persistence mechanism at all — CLAUDE.md's own two source sections here do not leave the disposition mechanism itself undefined; nothing in this skill fills a silent gap in CLAUDE.md by invention.

## Output format (all fields, fixed order)

1. **Applicable checklist(s)** — Checklist 1 / Checklist 2 / both / neither, with the one-line trigger reason from Applicability above.
2. For each applicable checklist, every one of its items **in the order listed above**, each with its disposition (`Addressed — <how>` or `N/A — <why>`).
3. **Verdict** — `done` only if every item on every applicable checklist is Addressed or N/A; otherwise `blocked`, listing the unresolved items by name.
