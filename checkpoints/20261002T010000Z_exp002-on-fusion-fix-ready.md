# ATLAS CHECKPOINT — 2026-10-02: EXP-002 ON, fusion fix ready (OFF), funding sentiment ready (OFF)

## Switches in `main.py`
| Switch | State |
|---|---|
| F-3 (gains no longer offset losses) | ON |
| S1 | ON |
| F-4 5 bp | ON |
| Order observe | ON |
| **EXP-002** (PAPER, MEDIUM only, floor 0.62, 30 admissions, 2026-10-02..16) | **ON** |
| Funding sentiment | OFF |
| Fusion full-weight denominator | OFF |
| Live authority | DENIED |

## Ready but OFF
- **Funding sentiment** (`atlas_finance/market_data/funding_rate_provider.py`). It may only add an agreeing BUY (audit F-1). Audit: APPROVE AFTER FIXES; F-2 needs the owner's acceptance.
- **Fusion dissent fix** (`AgentFusion.full_weight_denominator`, `AtlasApplication(fusion_full_weight_denominator=)`):
  - Tested: a dissent is never better than an abstention; NB-4 and NB-5 hold.
  - Research variant `füzyon düzeltmesi` added to `strategy_compare`.
  - Still needs an audit and the owner. Switch it on only after EXP-002 ends, so the results are not confounded.

## Tools
- `python -m tools.exp001_report --experiment EXP-002`
- `python -m tools.regime_bar_check <result.json>`
- `python -m tools.decision_trace <position_id>`

## Tests
Last full suite: 6308 passed, 12 skipped, 0 failed, before the replay-variant commit. That commit was then checked with 81 targeted tests.

## Next exact action
1. While EXP-002 runs: owner-machine replay with the fusion-fix variant:
   `python -m tools.strategy_compare --days 30 --windows 3 --embargo 240 --only füzyon --symbols-file config/universe_selection.json`
2. After EXP-002 ends (30 admissions or 2026-10-16): run the report. The owner decides keep or stop.
3. Then: an independent audit of the fusion fix, then the owner switches it on. Then, separately, the funding sentiment.
