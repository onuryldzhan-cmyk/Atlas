# ATLAS CHECKPOINT — Phase 4 P4-5: Knowledge Manager v1 milestone closure (2026-10-08)

**Milestone:** P4-5 Knowledge Manager v1 (`GRANT-KNOWLEDGE-MANAGER-V1-RESEARCH-ONLY`), registry **v5.87** (`governance/current/ATLAS_MILESTONE_REGISTRY_v5.87.json`, SHA256 `1814d0f07f85fb3c1d1d15cb7cbdf7081ac723e83a4d4d91fcb1239321b7cb64`), governance commit **`7f6afc1`**. v5.87 is not edited by this milestone.

**Status: OWNER-APPROVED (2026-10-08).** The owner approved committing the four files below and, as a separate permission, pushing them to `origin/claude/exp001-on-owner-lineage`, accepting KM-A2 and KM-A3 as v1 limitations. The resulting commit hash is recorded by git history, not in this file.

**Objective:** implement Knowledge Manager v1 under v5.87, have it independently audited, remediate the audit's fixable findings, and record the result for the owner's commit decision.

**Completed**
- Implementation of `research/knowledge_manager.py`: research-layer, in-memory state machine for the lineage SOURCE → CLAIM → EVIDENCE → VALIDATION → VALIDATED → OWNER SIGNATURE → AUTHORITATIVE. Statuses UNKNOWN / CONTESTED / UNVALIDATED / VALIDATED / AUTHORITATIVE are derived from the log on every read.
- Independent audit (ATLAS-KM-V1-INDEPENDENT-REVIEW, read-only, 2026-10-08, this session). **Verdict: CONDITIONAL PASS** — no P0, no P1; v5.87 invariants satisfied as written; findings below. Evidence location: the audit report delivered in the 2026-10-08 session; its findings are reproduced in this checkpoint so they survive the session.
- Remediation (ATLAS-KM-V1-CLOSURE-002): KM-A1 fixed (below). No other code change.

**Audit findings and resolution**

| ID | Sev | Finding | Resolution |
|---|---|---|---|
| KM-A1 | P2 | `register_claim(source_ids=<non-sequence>)` (e.g. `123`) raised `TypeError`, which `_guarded` treats as unexpected and **halted the manager** — one malformed call disabled it, contrary to the module contract "malformed input raises without halting". | **FIXED.** `source_ids` must be a non-empty tuple or list (`research/knowledge_manager.py`, `_register_claim`). Regression test `test_malformed_source_ids_are_refused_without_halting` fails on the original code (3 of 6 cases halted) and passes now. |
| KM-A2 | P2 | Non-owner identities (author, validator, submitter, withdrawing actor) are caller-asserted strings. Reproduced: one caller can validate its own claim under an alias (`author_a.2`), use an owner alias as validator (`owner@atlas`), and withdraw another submitter's counter-evidence by asserting that submitter's name, taking CONTESTED → VALIDATED with a misattributed withdrawal record. `validator_differs_from_author`, `owner_is_never_validator` and submitter-only withdrawal are therefore enforced on asserted names only. The owner's identity **is** authenticated (pinned-key HMAC), so AUTHORITATIVE still needs an explicit, keyed owner action. Not recorded as a limitation in v5.87. | **ACCEPTED by the owner (2026-10-08) as a v1 limitation.** Fixing it requires an identity mechanism for non-owner actors (e.g. per-actor pinned keys), which v5.87 neither authorizes nor defines; it needs its own future grant before any consumer relies on VALIDATED. |
| KM-A3 | P2 | "Verifiable" evidence (D5) is implemented as "carries a well-formed 64-hex `content_digest`". The digest is never checked against an artefact; `"0"*64` qualifies. Guarantee level: metadata present and well-formed (enables later verification, does not perform it). v5.87 does not define "verifiable". | **ACCEPTED by the owner (2026-10-08)** as the v1 definition of "verifiable". Artefact resolution is out of scope (no I/O); a future persistent store must not treat a digest as proof. |
| KM-A4 | P3 | `test_forbidden_name_detector_can_fail` adds `importlib` by hand instead of exercising the scanner; the AST scan sees `Name`/import nodes only (attribute reflection such as `object.__subclasses__` is not caught). | Deferred (test hardening). |
| KM-A5 | P3 | Source `retrieved_at` in the future (e.g. 2099) is accepted. | Deferred. |
| KM-A6 | P3 | Hash chain is unkeyed: an in-process rewrite with a recomputed hash is undetected for non-signature entries. Only the owner HMAC is keyed. Tamper-evident against accidental/naive edits only, not tamper-proof. | Accepted v1 boundary (same as Experiment Manager R-1). |
| KM-A7 | P3 | Signing bytes are intentionally identical to `atlas_org.owner_auth`; domain separation relies on the `kind` field, and verification accepts extra payload fields. Exploiting it needs private log injection plus an owner-signed crafted record. | Deferred (strict field-set check / explicit domain tag). |
| KM-A8 | P3 | Not thread-safe; single-threaded in-memory use assumed. Unauthenticated contradiction spam can hold a claim CONTESTED (conservative direction). | Accepted v1 boundary. |
| KM-I1 | Info | `research/` cannot be imported under Python 3.11 here because `research/multiple_testing.py` needs numpy (environment), not a Knowledge Manager incompatibility. | Informational. |

**v5.87 invariants (15):** all traced to code and tests in the audit; satisfied as written. Invariants 4, 5 and 8 (`validator_differs_from_author`, `owner_is_never_validator`, submitter-or-owner withdrawal) hold on asserted names only — see KM-A2.

**Files (release candidate, all new, untracked):**
- `research/knowledge_manager.py` — SHA256 `4f1a54c91443cb5ab6184788858f713b3fed268f4fc81984d1fc2cfb5baf42cc`
- `tests/test_research_knowledge_manager.py` — SHA256 `2b315cb6a825211e9d31fbc8003c1ebd4b63cb6562d922d975cf2b4b6facd94f`
- `tests/architecture/test_knowledge_manager_isolation.py` — SHA256 `4b2614a3d31dbd0cb9e8844bb2e37aa021861e7c3897cc74821f8280132c169d`
- this checkpoint
No other file changed. v5.86 and v5.87 unchanged. `knowledge_manager` org agent, `memory_records.py`, `learning_view.py`, `agent_cycle.py`, `web_app.py`, `core/policy_manifest.py` untouched.

**Tests (Python 3.13.12)**
- After the KM-A1 fix: `python3.13 -m pytest -q -p no:cacheprovider tests/test_research_knowledge_manager.py tests/architecture/test_knowledge_manager_isolation.py tests/test_research_isolation.py` → **84 passed** (65 + 7 + 12), 0 failed, 0 skipped.
- New KM-A1 test against the original module: 3 failed / 3 passed (the defect reproduced), against the fixed module: passes.
- Before the KM-A1 fix (2026-10-08, same session): architecture suite 102 passed; full suite 6881 passed, 0 failed, 12 skipped; 11 guard mutations each detected by at least one test. **Not re-run after the fix**: the fix changes one input guard in `_register_claim`, adds no import and touches no other module, so the full suite and architecture suite were not repeated.

**Architecture decisions:** research layer, in-memory, stdlib only; no `atlas_org` / `data_layer` / runtime import (architecture test); not imported outside `research/`, absent from the runtime closure; not wired into web_app, observability, tools, runtime or W2 (v5.87 C-2). Signature bytes compatible with `atlas_org.owner_auth`, re-implemented not imported (D1). Owner key fingerprint = SHA-256 of the key bytes; the key is never stored.

**Authority statement:** grants NO trading authority, NO Phase 5–10 authority, NO live or autonomous deployment authority, NO W2, NO persistence. Production NONE, live DENIED, autonomous deployment DENIED.

**Known issues / Risks:** KM-A2 and KM-A3 (accepted v1 limitations), KM-A4..A8 (deferred / accepted). None creates trading authority; nothing reads this module's output.

**Remaining work:** P4-1, P4-2, P4-3, P4-6, P4-8. Task ATLAS-MEM-FOUNDATION-005 (persistent memory) is BLOCKED: v5.87 marks persistent memory NOT_AUTHORIZED and Phase 7 memory out of Phase 4 scope; it needs a successor registry grant. Deferred findings each need their own authorized change. UI/endpoint verification stays deferred (C-2).

**Next exact action:** commit and push the four files as approved; then the next Phase 4 criterion chosen by the owner (persistent memory stays blocked until granted).
