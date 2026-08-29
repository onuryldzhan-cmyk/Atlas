---
name: atlas-audit-governance
description: Gate AUDIT MODE findings (severity/location/evidence/impact/reasoning/remediation, BLOCKING/HIGH/MEDIUM/LOW/INFORMATIONAL) and governance reconciliation (the CONFLICT format, successor-record-only drift reconciliation, UNKNOWN-not-inferred authorization) per CLAUDE.md's "Operating modes" and "Governance" sections. Use when running an audit, when a document conflicts with the actual repository, or when governance drift needs a new versioned record — an audit finding often triggers a governance action, so both sections can apply to the same situation.
---

# ATLAS AUDIT GOVERNANCE

Covers two CLAUDE.md sections that share the same evidentiary discipline: AUDIT MODE (Section A) and Governance (Section B). A single situation can trigger one, the other, or both — an audit finding is a common trigger for a governance reconciliation record.

## Applicability — which section(s) apply

- **Section A** applies when the task is producing audit findings — looking for problems rather than implementing.
- **Section B** applies when: a document (including CLAUDE.md itself, a checkpoint, or any other doc) is found to conflict with the actual repository/tests/runtime; governance drift needs reconciling with a new registry version; or an authorization status needs recording.
- Both can apply to the same output — e.g., an audit finding surfaces drift, which is then reconciled as a new versioned governance record. Evaluate each trigger independently; do not assume one implies the other.

## Section A — Audit findings (CLAUDE.md "Operating modes", AUDIT MODE)

Every finding requires exactly these 6 fields, in this order:

1. **Severity** — one of BLOCKING / HIGH / MEDIUM / LOW / INFORMATIONAL.
2. **Location** — the exact file/path/line or component the finding is about.
3. **Evidence** — what was actually observed, not assumed.
4. **Impact** — what breaks, or what the consequence is.
5. **Reasoning** — why the evidence leads to that impact.
6. **Remediation** — what would fix it.

Severity gating, exactly as CLAUDE.md states it — no gate is invented for the three levels it leaves ungated:

- **BLOCKING** — stops moving to the next feature.
- **HIGH** — must be fixed and re-reviewed before a milestone is closed.
- **MEDIUM / LOW / INFORMATIONAL** — classified as such; CLAUDE.md states no additional gate for these three, and this skill does not invent one.

Two anti-patterns this skill refuses, stated verbatim in CLAUDE.md:

- **Never downgrade a finding for convenience** — not to avoid a BLOCKING/HIGH gate, not to let a milestone close.
- **Never invent a finding** — every finding must trace to actually observed evidence, not a hypothesized or assumed problem.

## Section B — Governance reconciliation (CLAUDE.md "Governance")

- **Source of truth.** Repository + tests + runtime behavior are the source of truth; no document overrides the actual repository. When a document conflicts with the repository, report it as a **CONFLICT** with exactly these 5 fields, in this order: **Expected / Actual / Evidence / Impact / Decision Required**.
- **Successor-record only.** Governance drift is reconciled only by adding a new versioned successor record — never by editing a historical registry file in place. A reconciliation record states which prior version it supersedes; it does not alter that prior version.
- **UNKNOWN, never inferred.** Any authorization status that is not confirmed is written as `UNKNOWN`, never inferred from context, silence, or the absence of an explicit denial.

## Operational rules

- **Conflict check performed against CLAUDE.md's source wording:** no ambiguity was found in either source section severe enough to let this skill diverge from CLAUDE.md over time. Both sections state closed rule sets (6 finding fields + 5 severities + 2 anti-patterns; 3 governance rules with a 5-field CONFLICT format) rather than open-ended prose requiring invention to operate.
- **Section A blocking is exactly as stated, not extended.** Only BLOCKING and HIGH carry an explicit gate. Do not treat MEDIUM/LOW/INFORMATIONAL as blocking, and do not treat them as ignorable either — they still require all 6 fields; CLAUDE.md just states no gate for them.
- **Section B additive-only applies to the reconciliation record itself.** Producing a new versioned successor record never means editing the file(s) it supersedes — including under this skill's own governance reconciliation output.
- **Both sections run independently when both apply**, per Applicability above; a Section A finding that triggers a Section B action must have that linkage stated explicitly in the output (see Output format), not left implicit.

## Output format (fixed order)

1. **Section(s) applicable** — A / B / both / neither, with the one-line trigger reason.
2. If Section A applies: each finding's 6 fields in the fixed order above, plus its blocking consequence per severity.
3. If Section B applies: each governance item, using whichever applies — a full 5-field CONFLICT record, a successor-record note (new version + what it supersedes), and/or an authorization field explicitly marked `UNKNOWN` where unconfirmed. No field is skipped.
4. **Linkage** — state explicitly whether a Section A finding triggered a listed Section B action, or whether the sections in this output are independent of each other.
