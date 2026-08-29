---
name: atlas-prompt-builder
description: Take a plain-language task description and assemble it into CLAUDE.md's exact "Preferred prompt structure" (ROLE → CONTEXT → CURRENT STATE → OBJECTIVE → SCOPE → OUT OF SCOPE → ARCHITECTURE RULES → IMPLEMENTATION → EDGE CASES → TESTS → SECURITY → DO NOT → DEFINITION OF DONE → FINAL REPORT), prefaced by a classification from atlas-task-classifier and cross-skill notes for atlas-migration-safety/atlas-audit-governance where they apply. Use whenever a task needs to be written up as a properly structured Claude Code prompt.
---

# ATLAS PROMPT BUILDER

Turn a plain-language task description into a prompt in CLAUDE.md's "Preferred prompt structure" — the structure every prompt that built this repository's skills has used. This skill depends on `atlas-task-classifier` for classification and does not duplicate its rubric; it also depends on `atlas-migration-safety` and `atlas-audit-governance` for their own applicability triggers.

## Step 1 — Classify (depends on `atlas-task-classifier`)

Before assembling any section, apply `atlas-task-classifier`'s rubric to the plain-language description exactly as that skill defines it — do not re-derive, restate, or loosen the rubric here. Carry forward its five output fields (Tier, Reason, Model/effort, Final gate, Context `/clear`); they become this skill's mandatory prefix line (Step 3).

## Step 2 — Check cross-skill applicability (depends on `atlas-migration-safety`, `atlas-audit-governance`)

Using each skill's own stated triggers, not a new set invented here:

- If the task touches a migration/schema/state-transition path, or confidence/consensus/evidence-weighting logic (`atlas-migration-safety`'s Applicability), note that it applies and should be invoked alongside implementation.
- If the task involves producing audit findings, a document-vs-repository conflict, governance drift reconciliation, or recording an authorization status (`atlas-audit-governance`'s Applicability), note that it applies.
- A task can trigger neither, one, or both. State the result even when neither applies (`no cross-skill applicability`) — don't omit the check silently.
- If applicability genuinely cannot be determined yet (e.g., it depends on what a not-yet-done investigation finds), say so explicitly rather than guessing either way.

## Step 3 — Mandatory prefix line

Before the structured prompt itself, emit one line stating Tier, Model/effort, Final-gate status, and whether a context `/clear` is warranted — taken directly from Step 1. This is one line per prompt produced, not one line per section (see Operational rules for why).

## Step 4 — Assemble the 14 sections, in this exact order and naming

1. **ROLE**
2. **CONTEXT**
3. **CURRENT STATE**
4. **OBJECTIVE**
5. **SCOPE**
6. **OUT OF SCOPE**
7. **ARCHITECTURE RULES**
8. **IMPLEMENTATION**
9. **EDGE CASES**
10. **TESTS**
11. **SECURITY**
12. **DO NOT**
13. **DEFINITION OF DONE**
14. **FINAL REPORT** — sub-structured exactly as CLAUDE.md states: Changed / Tests / Risks / Remaining / Deferred.

## Operational rules

- **Keep concise, not a long narrative** — CLAUDE.md's own instruction for this template. A section with nothing to say states that briefly; it is not padded to look complete.
- **Don't re-ask for already-established evidence.** CONTEXT and CURRENT STATE must reference facts already confirmed as evidence in the current session directly, never phrase them as something a later step should re-verify.
- **Step 1 and Step 2 always run first, in order, and are never skipped.** SCOPE, ARCHITECTURE RULES, and TESTS below depend on their outcome.
- **One prefix line per prompt, not per section.** CLAUDE.md's "for every step, state (a) model tier, (b) whether `/clear` is needed" is broad enough to read as one line per template section. Resolved here as one line per assembled prompt — matching how this skill (and every prompt that built the other three skills) is actually used: one classification governs one self-contained prompt. A task large enough to need genuinely different tiers for different phases is COMPLEX/CRITICAL territory and should be split into separate `atlas-prompt-builder` invocations, each classified on its own, rather than one prompt carrying multiple prefix lines.
- **Conflict check performed against CLAUDE.md's source wording:** the 14-section list, order, and names are unambiguous, and FINAL REPORT's own sub-structure is stated explicitly. The one genuine judgment call is the "for every step" line above — flagged and resolved rather than left silent, not a case where CLAUDE.md's wording itself is self-contradictory.

## Output format (fixed order)

1. **Classification summary** — the five `atlas-task-classifier` fields, quoted from Step 1.
2. **Cross-skill applicability** — the result of Step 2, for both `atlas-migration-safety` and `atlas-audit-governance`, stated even when neither applies or when not yet determinable.
3. **Prefix line** — the one-line Tier / Model-effort / Final-gate / `/clear` statement from Step 3.
4. **The structured prompt** — all 14 sections from Step 4, in order, exact names, populated from the plain-language description.
