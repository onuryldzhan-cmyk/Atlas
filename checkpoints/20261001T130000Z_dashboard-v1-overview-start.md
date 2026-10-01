# ATLAS CHECKPOINT — 2026-10-01: start of Dashboard v1 (Overview)

## Objective

Build **Dashboard v1** from the owner's final design. The owner approved it ("başla hepsine"):

- **Overview home page** with:
  - top bar: OPERATIONAL, PAPER, DATA / ENGINE / RISK / SECURITY dots;
  - 4 KPIs: Equity, Today, Total return, Risk;
  - equity curve;
  - Market regime list;
  - Atlas View: signal, signal strength, vote distribution, uncertainty;
  - Why / Why-not;
  - open positions with an empty state;
  - Attention center;
  - What changed.
- **10-item left sidebar.** Items map to existing pages. No new data pages.
- **New palette** (see below). Remove the glass effect and the purple AI colour added in v5.77.

**Rules:**
- Real backend data only. Unknown data shows as N/A.
- No fake confidence. Show "Signal strength" (low / medium / high) with a calibration note, not a raw %.
- No funding, OI, order book, correlation, stress or AI cost. Atlas has none of these sources.
- Read-only web layer. Loopback only.
- Tests go with every change.

**Next steps after v1:**
- v2: Decision Trace page and Trade post-mortem view.
- Later: Ctrl+K palette, export, density modes.

## Design decisions (owner, 2026-10-01)

**Palette:**

| Token | Value |
|---|---|
| bg | #0B0D10 |
| surface | #11151A |
| elevated | #171C22 |
| border | #242A31 |
| text | #F1F3F5 |
| secondary text | #8B949E |
| Atlas blue | #5B8CFF |
| success | #35C98B |
| warning | #E5B95C |
| danger | #E56B6F |
| info | #6EA8FE |

**Look:**
- Fonts: Inter for UI, JetBrains Mono for numbers. Use system fallbacks: no CDN, vendored assets only.
- 6–8 px radius, thin borders, minimal shadow.
- No glass, no neon, no 3D on the dashboard. Dark only.

**Sidebar:**

| Group | Items |
|---|---|
| CORE | Overview, Markets, Portfolio, Strategies |
| INTELLIGENCE | Intelligence, Agents, Research |
| CONTROL | Risk, Proposals, System |

**Page mapping:**

| Sidebar item | Existing page |
|---|---|
| Overview | `/home` (new layout) |
| Markets | `/trading` chart |
| Portfolio | `/trading` / `/dashboard` |
| Strategies | `config/strategy_registry.json` plus strategy_compare memory records |
| Intelligence | `/decisions` |
| Agents | `/agents` + `/hq` |
| Risk | limits card |
| Research | `/research` |
| Proposals | `/governance` |
| System | `/system` + `/security` + `/roadmap` |

The HQ stays a separate experience page, linked as "Command Center".

## Data sources available for v1 (all existing, read-only)

| Data | Source |
|---|---|
| Portfolio | `/api/portfolio`: nav, equity, cash, realized / unrealized, exposure_by_asset, largest_concentration_pct, limits (daily loss / drawdown) |
| Equity curve | cumulative realized net from `/api/trades` (`recent_trades`) or the closed archive. No tick history; say so in the UI |
| Regimes | latest market_regime memory record (MR-*): per-coin regime |
| Signals and votes | `/api/signals` (action, confidence, risk_level, agents{status, action, score}, memory) |
| Why-not | `/api/execution-gates`, plus audit reject reasons (CONFIDENCE_BELOW_POLICY, LOW_CONFIDENCE, SELL with no position → HOLD) |
| Health | `/api/readiness`, `/api/command-center`, `/api/security`, market_loop status |
| Attention | READY_FOR_OWNER proposals, OPEN incidents (memory INCIDENTS), BLOCKED tasks, stale data |
| What changed | needs a server-side previous snapshot. Design: a read-only diff of the current vs. the last stored snapshot. The snapshot write must NOT happen in the web layer (the web is read-only by test). Option: the agent_cycle writes an OV-* memory snapshot each cycle; the web diffs the last two |

## Current state (branch claude/exp001-on-owner-lineage, HEAD 1a269be)

**Tests:** last full run 6146 passed + regenerated maps. Architecture tests: 89 / 89 green, so B2 and D5 are closed.

**Owner machine:** runs from `...\SOURCE_REPOSITORY\SOURCE_REPOSITORY`, on PAPER.
- First backup: `C:\AtlasBackups\20261001T123959Z`. Verified SAĞLAM; a restore drill was done.
- The backup tool now refuses to run while Atlas is running.

**Agents:**
- The cycle runs every 10 min.
- task_runner executes rule-based steps and flags LLM-only steps as waiting on AI-001.
- strategy_research runs strategy_compare daily in the background and writes SC-* memory records. The first run started around 15:44 local on 2026-10-01. The regime-filter decision waits on it, against the pre-registered bar in `proposals/2026-09-30_regime_filter_runtime_DRAFT.md`.

**Switches:**
- **F-3** (unrealized loss in daily loss) and **F-4** (5 bp paper slippage): the independent audit approved both after fixes A-1..A-5, which are done. Switching them on in `core/application.py` was blocked by the auto-mode classifier, so both remain OFF. The owner must allow it or edit two lines locally.
- **S1 sleeves:** engine side done (`sleeves_enabled`, default OFF). Next: persist `risk_bucket` on open positions (migration checklist, rule 7), then audit, then switch on.

## Known issues / risks

- Live authority is DENIED. All CRITICAL switches are OFF until the owner allows them.
- Confidence is uncalibrated: the sample is too small.

## Next exact action

1. Implement Dashboard v1 per above in `templates/home.html` (Overview), `templates/_atlas_theme.html` (palette, no glass) and the shared nav include.
2. Add a read-only `/api/overview` helper only if it is needed to aggregate. Keep `create_app` free of file IO. Extend the loopback / read-only test allowlists with a recorded reason.
3. Tests, a full suite run, then commit and push.
