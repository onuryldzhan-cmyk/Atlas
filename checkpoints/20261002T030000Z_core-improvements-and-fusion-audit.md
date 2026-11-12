# ATLAS CHECKPOINT — 2026-10-02: core improvements, fusion fix audited

## Completed (pushed)
**Fusion dissent fix** (`AgentFusion.full_weight_denominator`, OFF):
- Independent audit: APPROVE switch-on (`docs/audits/INDEPENDENT_AUDIT_FUSION_DISSENT_FIX_2026-10-02.md`).
- Effect: typical BUY confidence 0.636 → 0.48, so with it ON Atlas would open almost no trades in today's market.
- Kept OFF until EXP-002 ends (owner choice).

**Core improvements from high-star repos** (`proposals/20261002T020000Z_core-improvements-from-high-star-repos.md`):
- Brier score and calibration gap (`tools/reality_check.py`).
- Verdicts only with realistic fills; multiple-testing count (`tools/strategy_compare.py`).
- Look-ahead check (`tools/lookahead_check.py`).
- Loss-streak and cooldown evidence on `/postmortem`.
- Item #2 checked and rejected; #8 already present.

## Switches (main.py)
| Switch | State |
|---|---|
| F-3, S1, F-4 5 bp, order observe | ON |
| EXP-002 | ON |
| Funding sentiment | OFF |
| Fusion fix | OFF |
| Live authority | DENIED |

## Tests
Last full suite: 6313 passed, 12 skipped, 0 failed. After it: 49 targeted tests for the last change.

## Next (data- or owner-bound)
1. EXP-002 ends (30 admissions or 2026-10-16): `python -m tools.exp001_report --experiment EXP-002`, then the owner decides.
2. Owner: run the fusion-fix replay variant; decide on the fusion fix; then funding sentiment.
3. Protections #4 and #5: once the `/postmortem` evidence is MEASURED (≥ 10 trades), design, audit and owner.
4. Regime filter: `tools/regime_bar_check.py` on the owner's SC result.
5. Shadow step 1 (read-only order book): owner approval.
