# Autonomous work log (owner-delegated)

**Mandate (owner, 2026-09-28):** "Sen devam et … gerçek trader gibi hareket et, ayrıca önerilen seçenekleri seç, daha sonra bakarız neler yaptığına, ne kararlar verdiğine."

Under this mandate:
- Where a choice exists, I take the option I would have marked **(Önerilen)**, and record every decision here for later owner review.
- The mandate does **not** extend authority:
  - `live_authority=DENIED`, `production_authority=NONE` and `autonomous_deployment_authority=DENIED` are unchanged.
  - No force-push. No edits to historical registries or to CLAUDE.md.
  - CRITICAL changes still go through tests and an independent audit.
  - Anything that would materially widen risk (bigger positions, lower thresholds, new capital exposure) is **not** decided under this mandate. It is queued below for the owner.

## Decisions

| # | Date (UTC) | Decision | Chosen (recommended) | Why | Commit / registry |
|---|---|---|---|---|---|
| 1 | 2026-09-28 | Memory module reports `trades=0` | **Leave unchanged** | It is decision metadata only (it never reaches confidence or action). Feeding it 5 trades would push its historical "effect" toward raising confidence without evidence (rule 3). | this commit |
| 2 | 2026-09-28 | v5.16 LOW "panel down only in logs" | **Close as not applicable** | A panel cannot display its own outage. The supervisor console log is the correct surface, and the runbook documents it. | this commit |
| 3 | 2026-09-28 | v5.23 LOW: partial-sell fee test | **Added the test** | It closes an audit gap with no production change. | this commit |
| 5 | 2026-09-28 | v5.22 audit gap: no real-candle end-to-end test | **Added 2 tests** | Real candles → provider → WorldAnalysisEngine → rule: a calm market gives LOW; a market that is relatively calm but absolutely volatile gives MEDIUM, proving the p30 ceiling works. Test-only. | next commit |
| 6 | 2026-09-28 | v5.22 audit UNKNOWN: can the decision's `risk` key override the regime level? | **Verified with a test, no code change** | The brain decision normalized by MarketLoop carries the regime bucket (LOW / MEDIUM-capped / HIGH). The mutation that switches the brain back to the advisory scorer fails the test. UNKNOWN resolved to FACT. | next commit |
| 7 | 2026-09-28 | Owner request: research on agent team, organization and dashboard | **Agent team and organization: DEFER to Phase 6/9 (recorded). Dashboard step 1: ACCEPT (read-only)** | Rules 1 and 10: Phases 3–5 are still open. The dashboard only reads existing data. GPL FreqUI code is rejected (ideas only). | `docs/research/AGENT_TEAM_ORG_AND_DASHBOARD_RESEARCH_2026-09-28.md` |
| 8 | 2026-09-28 | Dashboard step 1 (net P&L) and step 2 (open-position prices) | **Not done: queued (Q4)** | `/api/trades` deliberately withholds cost, fees and prices (`test_trades_endpoint_does_not_leak_internal_position_fields`). Widening data exposure is a security-posture change, not a recommended-option pick. Steps 3–4 (EXP-001 progress, per-coin risk bucket) already exist on the panel. | — |
| 9 | 2026-09-28 | Continue with the remaining roadmap steps | **Stopped at the dependency wall** | Registry prerequisites chain every next item through ARCH-001 (OBS→TEST→PERF→REL→SEC→DATA→GOV). ARCH-001 needs the owner's scope decision (Q1). | — |
| 10 | 2026-09-28 | Owner: all delegated items take the recommended option | **Q1:** ARCH-001 baseline = existing, test-enforced architecture. **Q3:** keep 0.1%. **Q4:** account-level net P&L and fees on the panel, per-trade details still withheld. **Q2:** decide at the window end. | Recommended options as offered. | registry v5.24 |
| 11 | 2026-09-28 | Owner: "all corporate agents, visible on the website" | **Full 35-unit roster on the panel with honest status**; no new AI agent implemented (Phase 6) | Showing planned agents as running would break the No-Hallucination rule. Building them now breaks rules 1 and 10. The panel shows the whole company and exactly what exists. | registry v5.25 |
| 12 | 2026-09-28 | CODE-001, OBS-001, TEST-001, REL-001, SEC-001.1, DATA-001, GOV-001, SEC-002 | **Baseline adopted with evidence and listed gaps; PERF-001 pending the owner's telemetry run** | Same recommended approach as ARCH-001: adopt what the repo enforces and add ratchets (code-health, test count, secret-literal scan). Not certification. | registry v5.26–v5.28 |
| 13 | 2026-09-28 | Phase 4 (strategy research / backtest) | **Stopped; needs owner scoping** | A faithful backtest must replay the real decision chain, and the macro agent's historical inputs are not available offline. A simplified backtest would misrepresent Atlas. The research design is a material choice. | queued Q5 |
| 14 | 2026-09-28 | Owner: separate agents page with a 2D view; agents work as described | **`/agents` page: 2D SVG organization chart, live worker-agent monitor, vision operating rules. No new UI dependency.** | Dependency-free SVG avoids vetting new third-party code. The rules already hold in code and tests (no AI unit can execute). The planned AI tiers stay Phase 6. | registry v5.29 |
| 15 | 2026-09-28 | Q5: Phase 4 backtest method | **Macro-neutral replay of the real chain, labelled** (`tools/backtest_replay.py`) | It uses the real components (MarketLoop / AtlasBrain / RiskEngine), not a re-implementation. The one missing input (macro) is handled the way the runtime handles a provider outage, and that is conservative. Stated in every report. | registry v5.30 |
| 16 | 2026-09-28 | Self-review of the v5.30 backtest tool | **Fixed 3 defects: every BUY refused (BLOCKING), symbols not on one clock, empty risk state** | The tool would have reported zero trades. Found before any real run. Tests now cover it, and restoring the bug fails 2 tests. | registry v5.31 |
| 17 | 2026-09-28 | Owner: staged entries/exits, stop, bucket allocation | **Design proposal written with recommended numbers; implementation waits for owner approval** | It changes trading behaviour (CRITICAL execution/risk), which the mandate excludes from autonomous decisions. The bucket part already matches (LOW 40 > MEDIUM 25 > HIGH 10). | `governance/ATLAS_STAGED_ENTRY_EXIT_PROPOSAL_v1.0.md` |
| 4 | 2026-09-28 | Next roadmap item | **Do not start ARCH-001 autonomously** | Its specification is lost (GOV-DRIFT-005). Starting it would mean inventing an architecture spec, a CLAUDE.md STOP condition. | queued below |

## Queued for the owner

Status as of registry v5.31. Resolved items are kept for the record.

| # | Topic | Status |
|---|---|---|
| Q1 | ARCH-001 scope | **RESOLVED** (v5.24): the existing, test-enforced architecture was adopted as the baseline |
| Q2 | EXP-001 keep or stop | **OPEN**, due 2026-10-12 or at 50 admissions; decide from `tools/exp001_report` |
| Q3 | Paper fee rate versus the real account tier | **RESOLVED for now** (v5.24): 0.1% per side until the owner's tier is known |
| Q4 | Net P&L and fees on the panel | **RESOLVED** (v5.24): account-level totals only; per-trade details stay withheld |
| Q5 | Phase 4 backtest method | **RESOLVED** (v5.30/v5.31): macro-neutral replay of the real chain, labelled |
| Q7 | Staged entry/exit parameters | **APPROVED** (v5.32): recommended numbers, with the owner's 50/35/15 capital sleeves. Implemented in the backtest; the runtime package waits for the owner's backtest results |
| Q6 | Phase 6 AI agents (AI-001) | **OPEN**: specification PART_1 is missing; the owner decides the scope before any LLM agent is built |
