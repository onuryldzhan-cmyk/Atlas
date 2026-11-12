# ATLAS CHECKPOINT — agents page (2D org chart), macro-neutral replay backtest

**Branch:** `claude/exp001-on-owner-lineage` · **Registry head:** v5.30 · **Mandate:** recommended options (decision log #14–15).

## Objective
- Build a separate agents page with a 2D view.
- Make the agents follow the owner's vision rules.
- Make the dashboard more professional, after GitHub research.
- Continue the roadmap steps.

## Completed

**`/agents` page:**
- KPI strip;
- dependency-free SVG 2D organization chart of all 35 units with click-for-detail;
- live monitor of the 5 worker agents: per-coin vote, exclusion reason, agreement with the final decision;
- the vision's operating rules;
- Panel ↔ Ajanlar navigation.

**Research follow-up**, in `docs/research`:
- the TradingAgents UIs' live-monitor pattern is adopted;
- Tabler and ECharts were considered and not vendored.

**`tools/backtest_replay.py`:** replays the real MarketLoop → AtlasBrain → RiskEngine chain over Binance history.
- Macro and sentiment are excluded, and the report says so.
- Fee 0.1% per side; fills at candle close.
- Optional `--exp001`.

## Files changed
- `web_app.py` (the `/agents` route)
- `templates/agents.html` (new), `templates/dashboard.html` (navigation)
- `tools/backtest_replay.py` (new)
- `tests/test_agents_page.py`, `tests/test_backtest_replay.py`
- `tests/test_loopback_host_header_guard.py` (+`/agents`)
- registries v5.29–v5.30, docs

## Tests
- Full suite: **5583 passed, 12 skipped**; only B2 and D5 fail (checker PASS).

## Current state
- The backtest has not been run on real data, because Binance is blocked by this environment's proxy (403).
- The owner runs it (task 5).
- The owner's machine is still on an older build.

## Known issues / risks
- The backtest excludes macro and sentiment, uses close fills and no slippage, over a small 7-day sample. It is research evidence only.
- The "karara uyum" count is descriptive, not a trust score. A per-agent track record against trade outcomes is Phase 6.

## Remaining work
- Owner:
  - pull and restart;
  - telemetry extraction (PERF-001);
  - backtest runs (task 5);
  - EXP-001 decision on 2026-10-12.
- Phase 6 AI agents (AI-001): specification PART_1 is missing.

## Next exact action
The owner runs terminal tasks 1–5 and pastes the telemetry and backtest outputs. The session then records the PERF-001 baseline and the backtest evidence in a successor registry.
