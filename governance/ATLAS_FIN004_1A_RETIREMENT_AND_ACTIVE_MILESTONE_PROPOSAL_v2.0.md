# Proposal v2.0 — FIN-004.1a identifiers and the active milestone (owner lineage)

| Field | Value |
| --- | --- |
| Status | `PROPOSED` — no registry value changed |
| Lineage | Canonical owner lineage (registry v5.03 and later) |
| Competing record | Parallel branch `claude/vigilant-maxwell-5vwebp`, registry v4.91 `c2_undefined_milestone_retirement_result` (kept there, unedited) |
| Owner instruction (2026-09-28) | Do not touch the current value; write a new version as separate work; the owner will later compare both, keep the better one and delete the other |

## Facts (unchanged from the earlier evidence, re-checked on this lineage)

- Owner v5.00: `active_milestone = "FIN-004.1a-C1"`; `queued_foundation_sequence` starts with
  `FIN-004.1a-C2`, `FIN-004.1a-C3`, then CFG-001 … SEC-002.
- The three identifiers have no definition, status object or acceptance criteria at any revision; they
  first appear in v4.18 via `71855a0`, already undefined (evidence recorded on the parallel branch's v4.90;
  the pre-`0923805` history is shared by both lineages).
- Owner v4.97 closed REM-001 Gate 1's **original certification path** and adopted session engineering and
  audit work as superseding safety evidence.

## Why the parallel v4.91 answer no longer fits

It retired the identifiers and made **REM-001 Gate 1** the active milestone, re-pointing nine
`FIN-004.1a-C3` prerequisites to Gate 1. After v4.97 closed that Gate 1 path, pointing the active milestone
and nine prerequisites at it would gate work on a path the owner has closed.

## Options for the owner (choose later)

| Option | Active milestone | Prerequisites of ARCH-001, CODE-001, OBS-001, TEST-001, PERF-001, REL-001, SEC-001.1, DATA-001, SEC-002 | Trade-off |
| --- | --- | --- | --- |
| A | `PHASE_2_3_INVESTMENT_ENGINE_AND_RELIABILITY` (the owner's stated current focus, roadmap enumeration §96) | Replace `FIN-004.1a-C3` with that milestone | Matches what is actually being worked on; needs a status object written for it. |
| B | The v4.97 successor evidence framework (as named in v4.97) | Re-point to it | Keeps REM-001 lineage; depends on v4.97's framework being concrete enough to gate on. |
| C | Keep `FIN-004.1a-C1` | Unchanged | No change; the active milestone stays undefined (C2 stays open). |

All options retire nothing implicitly: retiring the identifiers (A, B) must also remove `FIN-004.1a-C2/C3`
from `queued_foundation_sequence` without reordering the rest, and must not loosen any gate (each re-pointed
prerequisite still blocks until its new target is done).

## Not done here

No registry field is changed. Implementation of the chosen option is a separate successor record.
