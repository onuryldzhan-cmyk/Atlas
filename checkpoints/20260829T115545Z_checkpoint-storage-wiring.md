# ATLAS CHECKPOINT — 20260829T115545Z

## Objective
Define and wire the canonical storage location for ATLAS CHECKPOINT files. CLAUDE.md's Checkpoint Protocol specified required checkpoint *content* but never a persistence *location*; the atlas-checkpoint skill had been explicitly written to refuse to invent one. This task resolves that gap by owner decision, wires the skill to it, and demonstrates the result against real repo state.

## Completed
- Added a new paragraph to CLAUDE.md's "Checkpoint Protocol" section (no other text in that section changed) specifying: canonical location `checkpoints/` at repo root; one file per checkpoint; filename convention `<UTC ISO8601 compact>_<short-kebab-slug>.md`; "most recent" = lexicographically last filename in that directory.
- Updated `.claude/skills/atlas-checkpoint/SKILL.md`'s "Output" section to: compute a UTC-compact timestamp + kebab-slug, create `checkpoints/` if missing, write the checkpoint there, and always still print the full checkpoint in chat (write is additive, never silent/write-only).
- Left `.claude/skills/atlas-checkpoint/SKILL.md`'s "Required fields" and "Operational rules" sections untouched — only "Output" was in scope.
- Left CLAUDE.md's "Session start protocol" and "Where current work state actually lives" sections untouched: both already say "read the last checkpoint" / "read the latest ATLAS CHECKPOINT entry" without asserting a location, so neither was made inaccurate by this addition.
- Verified via `git show --stat` that commits `5d033a7` (feat(observability): add read-only test-results and GOV-DRIFT panels — adds `observability/__init__.py`, `observability/panel_router.py`, `observability/panel_sources.py`, `tests/test_observability_panel.py`, `tools/generate_test_results_artifact.py`; edits `.gitignore`, `web_app.py`) and `1a49178` (feat(observability): render test-results and GOV-DRIFT panels on dashboard — edits `templates/dashboard.html`) are real, already-committed history at HEAD, dated 2026-08-29.
- Checked this task's own narrative framing ("the v4.27 discovery, v4.28/GOV-DRIFT-003") against actual repository content — it does not match. See **Known issues**.

## Files changed
From `git status --porcelain=v1` and `git diff` run at checkpoint time (HEAD = `1a49178`):
- Modified: `CLAUDE.md` — one paragraph (2 sentences) inserted after the existing Checkpoint Protocol paragraph, before the `## Context-pressure handling` heading. Confirmed via `git diff -- CLAUDE.md`.
- Untracked → now modified-in-place: `.claude/skills/atlas-checkpoint/SKILL.md` — this is the only file under `.claude/skills/` (confirmed via `Glob .claude/skills/**`); its "Output" section was rewritten as described above.
- New (created by this checkpoint step itself, after the snapshot above was taken): `checkpoints/20260829T115545Z_checkpoint-storage-wiring.md` — this file.
- `git status --porcelain=v1` showed no other paths — working tree is otherwise clean relative to HEAD.

## Architecture decisions
- Canonical checkpoint storage = a flat `checkpoints/` directory at repo root, one file per checkpoint. Decision made by the task owner, not inferred, because CLAUDE.md defined required content but no location, and the skill was explicitly forbidden from inventing one.
- Filename convention `<UTC ISO8601 compact>_<short-kebab-slug>.md` was chosen so recency is resolvable by a plain lexicographic filename sort — no file-content parsing or reliance on filesystem mtime is needed to find the "most recent" checkpoint.
- `checkpoints/` is deliberately kept distinct from `governance/current/`'s milestone registry (`ATLAS_MILESTONE_REGISTRY_v4.19.json` … `v4.26.json`): checkpoints are session-continuity artifacts; the registry is the governance-of-record artifact. This task does not merge them.

## Tests
UNKNOWN — requires verification. No test suite was executed in this session. `tests/test_observability_panel.py` exists at HEAD (518 lines, added in commit `5d033a7`; asserts on identifier `GOV-DRIFT-001` at lines 79, 264, 405 per this session's `git show --stat` and `Grep`), but it was not run in this session, so its current pass/fail status is unverified. The changes made in this task (CLAUDE.md prose, a skill instruction file) are not executable code — there is no automated test to run for them; the only verification performed was the live demonstration in this session.

## Current state
- CLAUDE.md's Checkpoint Protocol section now specifies both required content and storage location; no other CLAUDE.md section was rewritten.
- `.claude/skills/atlas-checkpoint/SKILL.md` now writes every checkpoint to `checkpoints/` in addition to printing it in chat.
- `checkpoints/` did not exist prior to this run (absent from `git status --porcelain` and from the repository generally); this file is the first artifact written there.
- None of the three changed/created paths (`CLAUDE.md`, the skill file, this checkpoint file) have been committed. All remain in the working tree pending task-owner review, per this task's explicit instruction to report the diff before committing.

## Known issues
- **Narrative/repository conflict.** This task's own framing referred to "the v4.27 discovery" and "v4.28/GOV-DRIFT-003" as established facts. Verification performed in this session found no match in the repository:
  - Expected (per task narrative): a "v4.28" governance state and a "GOV-DRIFT-003" finding exist from this session's prior work.
  - Actual (per repository at HEAD `1a49178`): `Glob governance/current/*.json` lists 8 registry files, `v4.19` through `v4.26` only — no `v4.27` or `v4.28` file exists anywhere in the repository (`Grep` for `v4\.27|v4\.28` returned zero files, repo-wide). The only governance-drift identifier occurring anywhere in the repository is `GOV-DRIFT-001` (13 matches across registries v4.19–v4.26, `governance/ATLAS_CURRENT_STATE_ALIGNMENT_v1.0.md`, and `tests/test_observability_panel.py`); `GOV-DRIFT-003` occurs nowhere.
  - Evidence: see the two `Grep` calls and the `Glob governance/current/*.json` call made in this session (outputs available in session transcript).
  - Impact: if v4.27/v4.28 and GOV-DRIFT-003 were expected to exist from earlier work, that work is either uncommitted, external to this repository, or the narrative is mistaken. This session cannot determine which.
  - Decision required (task owner): confirm whether v4.27/v4.28/GOV-DRIFT-003 refer to state this session cannot see, or whether the narrative should be corrected. Per CLAUDE.md's Governance rule, this checkpoint records only the verified repository identifiers (`v4.26`, `GOV-DRIFT-001`) rather than the unverified ones.
- Commit/ignore policy for `checkpoints/` is UNKNOWN — requires verification (task-owner decision). This task specified location and naming only, not whether checkpoint files should be committed, gitignored, or otherwise excluded.

## Risks
- If checkpoint files are committed going forward with no pruning rule, `checkpoints/` grows unboundedly. Low severity; worth an owner decision before many checkpoints accumulate.
- The unresolved v4.27/v4.28/GOV-DRIFT-003 discrepancy above is itself an instance of the kind of drift CLAUDE.md's Governance section and the `GOV-DRIFT-001` mechanism exist to catch — anyone acting on the task narrative without reading this checkpoint could rely on governance state that does not exist in the repository.
- None of this task's three file changes are committed yet; if the working tree were reset or discarded before task-owner review, this work would be lost. Mitigated by this checkpoint file and by the diffs shown in this task's final report.

## Remaining work
- Task owner reviews `git status`/`git diff` for `CLAUDE.md` and `.claude/skills/atlas-checkpoint/SKILL.md` (shown in this task's final report) and decides whether to commit, together with this checkpoint file.
- Task owner resolves the v4.27/v4.28/GOV-DRIFT-003 discrepancy noted above.
- Task owner decides commit/ignore policy for `checkpoints/` (out of this task's scope).

## Next exact action
Task owner reviews the diff already produced for `CLAUDE.md` and `.claude/skills/atlas-checkpoint/SKILL.md`, and — if approved — stages and commits `CLAUDE.md`, `.claude/skills/atlas-checkpoint/SKILL.md`, and `checkpoints/20260829T115545Z_checkpoint-storage-wiring.md`. No further implementation action is pending from this session.
