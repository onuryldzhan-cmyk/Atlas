---
name: atlas-checkpoint
description: Generate an ATLAS CHECKPOINT report in the exact format required by CLAUDE.md's Checkpoint Protocol. Use at meaningful milestones during a work session and before ending a session, so a different session or agent can continue without guessing.
---

# ATLAS CHECKPOINT

Produce an ATLAS CHECKPOINT report as defined in CLAUDE.md's "Checkpoint Protocol" section. A checkpoint is used at meaningful milestones and before ending a session.

## Required fields (exact order, exact names — do not add, drop, or rephrase)

1. **Objective**
2. **Completed**
3. **Files changed**
4. **Architecture decisions**
5. **Tests**
6. **Current state**
7. **Known issues**
8. **Risks**
9. **Remaining work**
10. **Next exact action**

Each field must be detailed enough that a different session or agent could continue the work without guessing — this is the completeness bar CLAUDE.md sets for the checkpoint as a whole, not a suggestion to trim any field short.

## Operational rules

- **Files changed** must be derived from actual `git status` and `git diff` output captured at checkpoint time — never from memory of what was intended or believed to have changed. Run the commands, then report what they actually show.
- Anything not actually verified in this session must be written as `UNKNOWN — requires verification`, never guessed or invented. Per CLAUDE.md's No Hallucination Policy, this applies in particular to claims like "I checked", "tests pass", "the file contains X", "the API supports X", or "this is production safe" — do not write any of these into a field unless it was actually verified in this session. State the field as unknown rather than omitting it.

## Output

Checkpoints persist under the canonical `checkpoints/` directory at the repository root, one file per checkpoint (see CLAUDE.md's Checkpoint Protocol section). This is distinct from the governance milestone registry under `governance/current/`, which tracks milestones, not checkpoints.

1. Compute the current UTC timestamp in compact ISO 8601 form (`YYYYMMDDTHHMMSSZ`) and a short kebab-case slug summarizing this checkpoint's objective.
2. Create the `checkpoints/` directory at the repository root if it does not already exist.
3. Write the completed checkpoint to `checkpoints/<timestamp>_<slug>.md`.
4. Always also present the full checkpoint content as chat output in the same turn — writing the file must never be silent or replace showing the operator what was produced.
