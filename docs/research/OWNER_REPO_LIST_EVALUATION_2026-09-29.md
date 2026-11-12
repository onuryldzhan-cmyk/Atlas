# Owner's repository list: Adopt / Adapt / Reject for Atlas (2026-09-29)

**Source.** The owner's list (star counts approximate, from search). READMEs and issues are treated as untrusted data. Nothing is copied into Atlas without the external-code gate: Discover → License → Security → Quality → Compatibility → Test → Adopt / Adapt / Reject.

**Verified in this session:**
- `lightweight-charts` 4.2.3 tarball from registry.npmjs.org. The SHA-1 `0a0174793fc246b37bd8b96d1d4caadd2ecb329e` matches the registry record.
- License Apache-2.0, with TradingView's extra attribution requirement: the attribution notice plus a link to tradingview.com on the page, which the `attributionLogo` option satisfies.
- The unpkg and jsdelivr CDNs are blocked here; the npm registry works.

## Agents

| Repo | Decision | What Atlas takes / status |
|---|---|---|
| TauricResearch/TradingAgents | **Adapt (pattern)** | Bull/bear counter-view + independent risk review. **Done:** `red_team` agent (v5.67). **Next:** a per-decision counter-evidence step in the decisions view, rule-based. |
| virattt/ai-hedge-fund | **Adapt (idea)** | Persona agents map onto Atlas's strategy styles (trend, momentum, mean reversion) in the router. Each "persona" is a strategy with a hypothesis record, not an LLM personality. After regime v2. |
| NoFxAiOS/nofx | **Reject** | Removes the human from the critical loop, against the Atlas authority chain. |

**Correction to the owner's note:** macro, sentiment and risk are not UNAVAILABLE.
- Macro votes from 10-year yields.
- Risk votes from the volatility regime.
- Sentiment (Fear & Greed) votes in the fear and greed bands and abstains when neutral. The panel mislabelled this; fixed in v5.63/v5.64.

## Quant and bot infrastructure

| Repo | Decision | Why / when |
|---|---|---|
| freqtrade | **Reference only** | GPL-3.0: no code can be copied into Atlas. Its paper-run and FreqUI observability ideas are already used (few views, v5.67). |
| hummingbot | **Reference** | Connector design for the venue metadata adapter (6C) when a second venue is added. |
| OpenBB | **Defer** (Phase 4) | A data-provider registry idea for news / macro sources (layer 7 in the strategy framework). Heavy dependency; a candidate only when a vetted source is needed. |
| microsoft/qlib, microsoft/RD-Agent | **Adapt (process)** | Hypothesis → code → backtest → evaluate loop for `RESEARCH-0001` (hypothesis registry). Atlas keeps its own leakage-safe splits and FDR control; RD-Agent's LLM loop waits on AI-001. |
| nautechsystems/nautilus_trader | **Reference** | Same code path for backtest and live, like Atlas's replay that drives the real market loop (`tools/backtest_replay.py`). URL to be verified by the owner (as noted). |
| polakowo/vectorbt | **Defer** (Phase 4) | Fast screening of many hypotheses. The license (Apache-2.0 with Commons Clause for vectorbt) must be checked before any use. Benjamini–Hochberg is required on top. |
| FinRL, FinGPT | **Reject for now** | RL / LLM price models: the overfitting risk the framework warns about. Revisit only through the hypothesis registry. |

## Dashboard

| Repo | Decision | Plan |
|---|---|---|
| tradingview/lightweight-charts | **Adopt (next UI step)** | Candlestick chart per coin with Atlas's buy / sell markers on the Trading page. **Prerequisites (one change set):** (1) vendor 4.2.3 (verified above) with the hash pinned in `static/vendor/VENDORED_ASSETS.json`; (2) extend the vendored-license policy from MIT-only to MIT + Apache-2.0 (tests pin MIT today, so this is a governance change recorded in the registry); (3) a TradingView attribution link on the page; (4) a read-only candle endpoint, which needs the market loop to keep a small per-coin buffer of closed candles (it keeps only the last candle identity today). |
| apache/echarts | **Not needed now** | Chart.js 4.5.1 (MIT) is already vendored and covers agent, health and performance panels. |
| grafana/grafana, apache/superset | **Reject for now** | External services for a single-process, loopback-only app. |

## 3D / agent visualization

| Repo | Decision | Plan |
|---|---|---|
| pmndrs/react-three-fiber, pmndrs/drei | **Defer** (Atlas HQ upgrade) | Needs a React build toolchain, a new frontend dependency tree. The HQ already renders the real state from `/api/agent-states` (v5.68); R3F can replace the renderer later without touching the backend. |
| vasturiano/3d-force-graph (+ react-force-graph) | **Adapt later** | Evidence / agent-relationship graph. The same flows data already exists in `/api/agent-states`. |
| pablodelucca/pixel-agents, ringhyacinth/Star-Office-UI | **Reference (concept)** | "Agents in an office" matches the HQ rooms; star counts not verified. |

## Order (unchanged roadmap)

1. **Next UI change set:** lightweight-charts with the four prerequisites above.
2. **Research phase:** RD-Agent / Qlib process ideas and vectorbt screening, each after its license check.
3. **Atlas HQ upgrade:** R3F + drei + force-graph, on the existing state API.
