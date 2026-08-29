---
name: atlas-task-classifier
description: Classify a described task into TRIVIAL/ROUTINE/STANDARD/COMPLEX/CRITICAL per CLAUDE.md's "Required workflow before implementation" CLASSIFY step, and state the resulting model/effort recommendation, whether the critical-task final gate applies, and whether a context /clear is warranted before starting. Use before implementing any non-trivial task, and again immediately if a task's actual scope grows past its original tier.
---

# ATLAS TASK CLASSIFIER

Classify a task as defined by CLAUDE.md's "Required workflow before implementation" step 2 (CLASSIFY). CLAUDE.md names five tiers and requires the model/effort tier to scale with them, but does not itself define tier boundaries or the model/effort mapping. This skill applies the project owner's canonical rubric for both.

## Tier rubric (apply as written — do not loosen, tighten, or reinterpret the boundaries)

1. **TRIVIAL** — typo/formatting/comment-only changes, no behavior change.
   → fastest/cheapest available model, LOW effort.
2. **ROUTINE** — single well-scoped file/feature addition, no architecture impact, easily reversible, follows an existing pattern.
   → mid-tier model, LOW–MEDIUM effort.
3. **STANDARD** — multi-file change within one module/subsystem, follows existing patterns, no new architectural decision.
   → mid-tier model, MEDIUM–HIGH effort.
4. **COMPLEX** — cross-module change, introduces a new pattern, or has genuinely ambiguous requirements.
   → strongest model, HIGH effort.
5. **CRITICAL** — touches risk/execution/capital/security/migration/governance, or is hard/impossible to reverse.
   → strongest model, MAXIMUM effort. CLAUDE.md's full critical-task final gate applies: IMPLEMENT → TEST → SELF-REVIEW → REGRESSION → INDEPENDENT AUDIT → FIX → RE-TEST → FINAL GATE — never declare a critical subsystem complete after only a happy-path test.

## Operational rules

- **Most-severe-wins.** If a task matches the criteria of more than one tier at once (e.g., a multi-file subsystem change that also touches security), classify at the higher tier. This follows directly from CLAUDE.md's own rule that classification must never settle at the lighter tier when a heavier one applies.
- **CRITICAL is a floor, not a ceiling suggestion.** Any task touching risk, execution, capital, security, migration, or governance is CRITICAL regardless of how small the diff looks, per CLAUDE.md's decision priority (SAFETY → SECURITY → GOVERNANCE → RISK → CAPITAL → AI DECISION → EXECUTION).
- **Mid-task growth forces reclassification.** CLAUDE.md's workflow step already states that a task which grows more complex mid-task must be reclassified upward, never left at its original tier. This skill enforces that, not just states it: if the task's actual scope turns out to exceed its original tier against the rubric above (a second module gets touched, or risk/execution/capital/security/migration/governance code turns out to be involved), stop, reclassify at the new tier using this same rubric, and restate all five output fields below — do not continue under the original classification.
- **Context /clear.** Recommend `/clear` when the conversation's prior context is unrelated to the task being classified; recommend skipping it when the task is directly continuous with what the session was just doing.
- **Conflict check.** If the task as described conflicts with CLAUDE.md's own wording on classification — not merely a boundary CLAUDE.md leaves undefined and this rubric fills — stop and report the conflict per CLAUDE.md's STOP conditions instead of resolving it silently.

## Output format (all five fields, exact order, exact names)

1. **Tier** — one of TRIVIAL / ROUTINE / STANDARD / COMPLEX / CRITICAL.
2. **Reason** — one line naming the specific rubric criterion that triggered the tier, not a restatement of the task.
3. **Model/effort** — the tier's model tier and effort level from the rubric above.
4. **Final gate** — `applies` (CRITICAL only) or `does not apply`.
5. **Context /clear** — `warranted` or `not warranted`, with the one-line reason from the Context /clear rule above.
