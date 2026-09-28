# ATLAS CHECKPOINT — organization on the panel, foundation baselines (v5.24–v5.28)

**Branch:** `claude/exp001-on-owner-lineage` · **Registry head:** v5.28 · **Mandate:** the owner delegated every choice to the recommended option (`docs/operations/AUTONOMOUS_DECISION_LOG.md`, entries 7–13).

## Objective
- Research the agent team, organization structure and dashboard on GitHub and the web.
- Show every corporate unit and agent on the website.
- Continue along the roadmap using the recommended options.

## Completed

**Research:** `docs/research/AGENT_TEAM_ORG_AND_DASHBOARD_RESEARCH_2026-09-28.md`.
- Sources: TradingAgents (Apache-2.0), ai-hedge-fund (MIT), MetaGPT, CrewAI, FreqUI (GPL: ideas only), Hummingbot, Lightweight Charts.
- Agent team and organization are placed in Phase 6/9; the dashboard in Phase 8.

**Panel:**
- *Portföy Performansı*: KPIs, cumulative P&L chart, closed-trades table, and account net P&L and fees.
- *Atlas Organizasyonu*: 35 units from docs/vision, each with an honest status (12 active, 10 partial, 13 planned), its phase, and its can/cannot limits.

**Registry:**

| Version | What |
|---|---|
| v5.24 | Owner-delegated Q1–Q4; ARCH-001 baseline = the existing, test-enforced architecture |
| v5.25 | Organization roster; read-only `/api/organization`, covered by the host-header guard |
| v5.26 | CODE-001 baseline and quality ratchet (`tools/code_health_report`) |
| v5.27 | OBS / TEST / REL baselines with gaps; PERF pending the owner's measurement; test-suite ratchet |
| v5.28 | SEC-001.1 / DATA-001 / GOV-001 / SEC-002 baselines; secret-literal scan test |

## Files changed

| Area | Files |
|---|---|
| New modules | `observability/organization.py`, `tools/code_health_report.py` |
| Edited | `web_app.py`, `templates/dashboard.html` |
| New tests | `tests/test_organization_roster.py`, `test_dashboard_performance_js.py`, `test_code001_quality_ratchet.py`, `test_test001_suite_ratchet.py`, `test_sec001_no_secret_literals.py` |
| Test edits | `+1 route` in `test_loopback_host_header_guard.py` (more coverage); `+1 test` in `test_web_app_signals_and_trades.py` |
| Generated | `packaging/*` regenerated |
| Docs | registries v5.24–v5.28, docs |

## Architecture decisions
- **Organization roster placement.** It lives in `observability/` (L5, stdlib only) because the web layer may not import `core`. No layer rule changed: one was briefly added, then reverted.
- **`/api/trades`.** It gains account-level aggregates only. Per-trade cost, fees and prices stay withheld, and the leak test is unchanged.

## Tests
- Last full suite before v5.26: **5551 passed**; only B2 and D5 fail after the guard-list update.
- Later additions, run narrowly:
  - code ratchet: 4 passed;
  - suite ratchet: 1 passed;
  - secret scan: 2 passed;
  - organization tests: 7 passed.
- Mutation checks on the ratchets were caught.

## Current state
- Every Phase 0–5 foundation item is BASELINE_ADOPTED (not certified), except PERF-001, which is pending the owner's telemetry run.
- The owner's machine still runs an older build; pull and restart to get v5.21+.

## Known issues / risks
- "BASELINE_ADOPTED" means known and ratcheted, not certified.
- The gap lists in v5.27 and v5.28 are real work:
  - no automated dependency-vulnerability scan;
  - no data catalog or lineage;
  - manual backups;
  - no restore drill;
  - coverage unknown.

## Remaining work

Owner queue:
- **Q2:** EXP-001 decision on 2026-10-12.
- **Q5:** Phase 4 backtest design.

Owner terminal tasks:
- pull and restart;
- telemetry extraction, for the PERF baseline and the panel card.

Phase 6 agent team / AI-001: its specification PART_1 is missing, so it needs owner scoping.

## Next exact action
Owner:
1. Pull the new build.
2. Run `show_config` and `check_execution_authority_agreement`.
3. Restart the supervisor.
4. Run the telemetry extraction and paste its output.
5. Answer Q5.
