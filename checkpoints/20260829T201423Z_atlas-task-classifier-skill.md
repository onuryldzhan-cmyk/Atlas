# ATLAS CHECKPOINT — 20260829T201423Z

## Objective
Create a Claude Code skill (`atlas-task-classifier`) that classifies a described task into CLAUDE.md's five tiers (TRIVIAL/ROUTINE/STANDARD/COMPLEX/CRITICAL) per an owner-specified rubric CLAUDE.md itself leaves undefined, matching the `atlas-checkpoint` skill's existing layout convention, and demonstrate it against three real examples from this session's history.

## Completed
- Inspected `.claude/skills/atlas-checkpoint/SKILL.md` (the only prior skill in the repo) to establish the layout convention: frontmatter with `name` + `description` only, an H1 title, a rubric/required-fields section, an "Operational rules" section, and an exact-order/exact-names output section.
- Checked CLAUDE.md's actual text for conflicts with the owner's rubric — none found. CLAUDE.md names the five tiers and states two operational rules (reclassify upward if scope grows mid-task; CRITICAL gets the full final gate), but never defines tier boundaries or a model/effort mapping, so the rubric fills a gap rather than overriding stated text.
- Wrote `.claude/skills/atlas-task-classifier/SKILL.md` (37 lines) encoding: the five-tier rubric verbatim in meaning with its model/effort mapping; five operational rules (most-severe-wins tie-break, CRITICAL-is-a-floor, mid-task-growth-forces-reclassification with enforcement language, context-`/clear` judgment, conflict-check-and-stop); a five-field output format (Tier, Reason, Model/effort, Final gate, Context `/clear`).
- Demonstrated the skill against three real session examples, grounded in `git show --stat`, `git log --all`, and `git branch --contains` evidence rather than assumed:
  - CLAUDE.md authoring (`4d6f8b5`, `45496d8`) → classified ROUTINE.
  - Observability panel (`5d033a7`, `1a49178`) → classified STANDARD.
  - v4.27/v4.28 governance ratification (`46df920`, `59225d1`) → classified CRITICAL.
- While grounding the third example, discovered `46df920` and `59225d1` exist only on branch `feat/block3-execution-safety`, not in `research/edge-validation`'s ancestry. This resolves the open "Known issues" item in the prior checkpoint (`checkpoints/20260829T115545Z_checkpoint-storage-wiring.md`), which had been unable to find any v4.27/v4.28/GOV-DRIFT-003 evidence anywhere in the repository from `research/edge-validation`. No branch action was taken — reported to the task owner, not acted on.
- Saved a pinned memory (`atlas-task-classification-rubric.md`, in the user's Claude Code memory store outside this repository) capturing the rubric itself as a standing cross-session fact, independent of the skill file, per this session's memory-write rules.
- Reported the diff and withheld committing, per the task's explicit instruction to let the task owner review first.
- Task owner reviewed and committed the skill file independently (commit `93c5083`, `feat(skills): add atlas-task-classifier skill with model/effort rubric`) between turns. Verified at this checkpoint step, via `git diff 128916b 93c5083 -- .claude/skills/atlas-task-classifier/SKILL.md` and blob-hash comparison (`a4d9325` both before and after), that the committed content is byte-identical to what this session wrote — not re-authored or altered.

## Files changed
From `git status --porcelain=v1` and `git show --stat` run at checkpoint time (HEAD = `93c5083`, branch `research/edge-validation`):
- Committed in `93c5083`: `.claude/skills/atlas-task-classifier/SKILL.md` — new file, 37 insertions. Committed by the task owner, not by this session.
- `git status --porcelain=v1` at checkpoint time shows the working tree otherwise clean relative to HEAD except three untracked paths this session did not create and did not modify: `.agents/`, `.claude/skills/claude-automation-recommender/`, `skills-lock.json` — all three were already untracked at the start of this session per the session-start git status snapshot.
- No tracked file other than the new skill file was touched: `CLAUDE.md`, all governance files under `governance/current/`, and every other skill file are unmodified — confirmed via `git status --porcelain=v1` showing no `M` or staged entries.
- `checkpoints/20260829T115545Z_checkpoint-storage-wiring.md` (written earlier this session, for a prior task) is untouched by this task; this checkpoint file is the second file written to `checkpoints/`.

## Architecture decisions
- No new architecture introduced. The only content decision was rubric encoding, which was owner-specified in the task prompt, not derived — tier boundaries and the model/effort mapping were transcribed as given, without loosening, tightening, or reinterpreting them.
- Two of the skill's five operational rules go beyond the literal rubric text (most-severe-wins tie-break; "CRITICAL is a floor, not a ceiling suggestion"). Both are presented in the skill as direct corollaries of rules CLAUDE.md already states elsewhere — never settle at a lighter tier when a heavier one applies; SAFETY → SECURITY → GOVERNANCE → RISK → CAPITAL priority — not as newly invented policy.
- Decision to persist the rubric as a pinned memory in addition to the skill file: reasoning was that memory is consulted even when the skill is not explicitly invoked by name at CLAUDE.md's mandatory CLASSIFY step, while the skill file remains the authoritative, version-controlled copy of record.

## Tests
No automated test suite applies — this is a skill-instruction markdown file, not executable code (consistent with the prior checkpoint's identical finding for the `atlas-checkpoint` skill). Verification performed instead:
- Textual conflict-check of CLAUDE.md's actual classification wording against the given rubric — no conflict found (see Completed).
- Demonstrated the skill's defined output format against three real commits/commit-pairs from this session's git history, with tier and reasoning grounded in `git show --stat` file lists and diff sizes rather than assumed.

Two of the three tier calls were explicitly flagged, in this session's chat output, as judgment calls rather than mechanical certainties: CLAUDE.md-authoring (ROUTINE vs. STANDARD — is project doctrine a "feature addition"?) and the observability panel (STANDARD vs. COMPLEX — 5 top-level directories touched, but self-described read-only and reusing the existing entry-point pattern).

Whether the three examples' *actual* historical handling (which model/effort was deliberately used; whether an INDEPENDENT AUDIT step ran for the v4.27/v4.28 governance commits) matched the rubric's prescription is UNKNOWN — requires verification. No repository-recorded artifact exists confirming either, for any of the three examples.

## Current state
- `.claude/skills/atlas-task-classifier/SKILL.md` exists, is committed at HEAD (`93c5083`), and appears in this session's live skills listing.
- The rubric is also captured in a pinned memory file (`atlas-task-classification-rubric.md`) outside this repository, for applicability in sessions that don't explicitly invoke the skill by name.
- Working tree is clean relative to HEAD except the three pre-existing untracked paths noted above, none created or modified by this session.
- Current branch: `research/edge-validation`.

## Known issues
- **Inherited, now resolved by evidence (not by action):** the prior checkpoint's open question about `v4.27`/`v4.28`/`GOV-DRIFT-003` not being found anywhere in the repository is explained — that work exists on branch `feat/block3-execution-safety`, which has not been merged into `research/edge-validation`. Whether and how to merge it remains a task-owner decision; nothing was done about it in this session beyond reporting it (in this session's chat output, and now in this checkpoint).
- The skill's two borderline tier calls (see Tests) are inherent ambiguity in applying a diff-shape-based rubric to a documentation change and to a multi-directory read-only feature, not defects in the skill itself — worth the task owner's awareness, since a future invocation on a similarly-shaped task will hit the same ambiguity and require the same kind of judgment call.
- CLAUDE.md has no pointer to the new skill's existence — left alone per this task's explicit out-of-scope instruction ("rewriting CLAUDE.md itself... note that as a Deferred Improvement instead"). Still outstanding if the task owner wants discoverability improved.

## Risks
- Low. The skill is a markdown instruction file with no executable behavior and no effect on runtime, financial, or execution code; the worst case of a misapplied tier is over- or under-scoping a future task's effort/gate, not a correctness or safety defect in Atlas itself.
- The unmerged `feat/block3-execution-safety` branch — carrying `v4.27`/`v4.28` governance ratifications, including CRITICAL-tier execution-safety and governance-drift-reconciliation content — sitting outside `research/edge-validation`'s history is a standing risk, now flagged twice (this session's chat output and this checkpoint). Any future session working only from `research/edge-validation` will not see that governance state and could act on stale assumptions about what's ratified. Unchanged by this session; remains the task owner's call.

## Remaining work
- None for this task — it is complete and committed.
- Carried over, not part of this task: task-owner decision on the `feat/block3-execution-safety` merge question; optional CLAUDE.md pointer to the new skill (explicitly deferred, not requested).

## Next exact action
None pending from this session for this task. If the task owner wants the classifier applied going forward, the next natural action is invoking it (or applying its rubric directly) at the CLASSIFY step of whatever task comes next, per CLAUDE.md's mandatory workflow.
