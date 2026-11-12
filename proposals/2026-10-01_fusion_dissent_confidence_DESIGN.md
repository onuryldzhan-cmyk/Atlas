# AgentFusion: a dissenting vote must never raise the winner's confidence. Design, not implemented (2026-10-01)

**Status:** CRITICAL (decision intelligence). **Implemented 2026-10-01 behind `AgentFusion.full_weight_denominator` (default OFF), switched via `AtlasApplication(fusion_full_weight_denominator=...)`; main.py does not pass it. Tests: `tests/test_fusion_dissent_confidence.py`. Still required: replay comparison, independent audit, owner switch-on after EXP-002 ends.** Found by the independent audit of 2026-10-01 (`docs/audits/INDEPENDENT_AUDIT_FUNDING_SENTIMENT_EXP002_2026-10-01.md`, F-1).

## Fact (measured by the audit with the real `fuse()`, typical live votes)
| | Confidence of the BUY |
|---|---|
| Sentiment abstaining | 0.5963 |
| Sentiment HOLD | 0.6358 |
| Sentiment SELL | 0.6154 |

With NB-5, a missing agent keeps its full weight in the denominator, but a HOLD or SELL vote adds partial support to the BUY share. So a disagreeing agent lifts the BUY more than a silent one does.

This already affects today's runtime: the macro agent votes SELL 0.25 on every coin. Removing the macro agent would *lower* BUY confidence. That is the opposite of what a dissent should do.

## Proposed rule
**The winner's confidence counts only agreeing weight.** A dissenting or neutral vote adds 0 to the numerator and its full weight to the denominator, the same as an abstention. A dissent is therefore never better for the winner than an abstention.

## Expected effect
- BUY confidence drops for every coin where macro dissents. Fewer trades: the conservative direction.
- NB-4 and NB-5 are preserved. Removing evidence still never raises confidence, and the denominator stays the expected roster.

## Required before switch-on
- Tests:
  - dissent ≤ abstain;
  - agreement ≥ abstain;
  - NB-4 removal;
  - NB-5 missing agents;
  - the audit's probe table as a regression.
- Replay comparison (`strategy_compare`) before and after.
- Independent audit.
- Owner approval. This changes live PAPER decisions.
