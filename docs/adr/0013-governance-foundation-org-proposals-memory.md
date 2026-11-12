# ADR-0013: Governance Foundation — Organization, Tasks, Proposals, Memory

## Status

**Accepted** on 2026-09-28 (UTC). The owner answered the master build command with "Önce yönetişim temeli (Önerilen)", and the choice is recorded in registry v5.34. Registries v5.35–v5.45 record the implementation and its independent audit. This ADR records the design as built.

- Consistent with ADR-0011: the deterministic core runs without AI, and AI output is always a proposal.
- Consistent with ADR-0012: the owner uses a pull surface, and there are no push notifications.
- Authority state unchanged: `production_authority=NONE`, `live_authority=DENIED`, `autonomous_deployment_authority=DENIED`.

## Context

The owner's principle is that Atlas is an organization that coordinates expert agents under a constitution, with the owner as final authority. Before v5.34 the repository had:
- a static roster of 35 organization units (`observability/organization.py`, v5.25);
- no enforced model of who may do what;
- no proposal lifecycle;
- no provenance-carrying memory.

## Decision

1. **Package `atlas_org/` at layer L1.** It is pure, uses only the standard library and does no I/O. Governance rules are code, re-checked on every read:
   - `permissions.py`: explicit capabilities per unit, deny by default. `financial_execute` and `deploy` can never be granted to an AI unit. No capability exists to change governance or permissions.
   - `proposals.py`: the lifecycle runs DRAFT → UNDER_REVIEW → READY_FOR_OWNER → APPROVED/REJECTED → APPLIED → ROLLED_BACK, with SUPERSEDED possible.
     - Only `owner` decides.
     - READY_FOR_OWNER needs all of the following for the current revision, from reviewers who are not the author: tests with 0 failures, a PASS code review, and a PASS security review.
     - A rollback plan is mandatory.
     - Changes to protected files must be marked CRITICAL. Paths are normalised first: case, `..`, absolute paths, NTFS streams and zero-width characters.
   - `tasks.py` and `manager.py`: the Atlas Manager is **deterministic rules, not an LLM**.
     - It classifies a request, plans it, and routes each step only to a unit that holds the capability.
     - Requests that need owner authority never become tasks: live trading, deploy, risk or capital changes, bypassing approval, governance or permission changes.
   - `memory_records.py`: records are immutable and carry provenance.
     - Only the owner writes or supersedes AUTHORITATIVE records.
     - RESEARCH records need a license, maintenance and security evaluation, and are never authoritative.
   - `security_review.py`: the Security Guardian, based on the Python AST.
     - It covers 8 categories.
     - A review is bound to its evidence: the reviewed files, a content digest and the base. It is re-run before the owner signs.
   - `owner_auth.py`: owner events carry HMAC-SHA256 signatures bound to `seq`/`prev_hash`.
     - The key lives only on the owner's machine, outside the repository.
     - The web layer never reads the key.
2. **Storage.** Append-only, SHA-256 hash-chained JSONL in `governance/records/`.
   - `tools/atlas_org_cli.py` is the only writer. Before every append it replays the whole log, refuses a corrupted log, and uses a single-writer lock and fsync.
3. **Surfaces are read-only and loopback-only.**
   - APIs: `/api/proposals`, `/api/tasks`, `/api/memory`, `/api/permissions`, `/api/command-center`, `/api/chat` (deterministic, cannot act), `/api/portfolio`.
   - Pages: `/home`, `/trading`, `/governance`, `/system`, `/hq`.
4. **Self-improvement is observe-and-propose only** (CLAUDE.md rule 6). `tools/atlas_self_review.py` turns real evidence into tasks through the manager and never edits code.

## Consequences

- A proposal can reach APPLIED only through a signed owner approval, verified with the owner's key on the owner's machine.
- Known limits, recorded in registry v5.39:
  - Any process running as the owner's OS user can read the owner key.
  - Records cut from the end of a log are detectable only against a noted head.
  - The web cannot verify signatures. Ed25519 would need the `cryptography` dependency, which is DEFERRED to an owner decision.
  - Static security analysis cannot follow variable aliasing.
- LLM agents (Phase 6, AI-001) can later plug in as producers of task results and proposals. They cannot change routing, approval or permissions, because those are policy code in `atlas_org/`, and changing it is itself a CRITICAL, owner-signed proposal.
