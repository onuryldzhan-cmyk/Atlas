# ATLAS CHECKPOINT — risk_level design decisions and pending work

## Objective
Carry the 2026-09-28 BUY-blocking investigation from diagnosis to an owner-decided design,
without implementing anything, and hand over a clean list of what is left.

## Completed
- Diagnosis (read-only): `checkpoints/20260928T070000Z_buy-risk-bucket-confidence-diagnosis.md`.
  risk_level comes from vote-count agreement + reasoning with volatility defaulted; LOW is
  unreachable; max reachable BUY confidence 76.05 < HIGH bar 80.
- Design proposal (PROPOSED, not authorized):
  `governance/ATLAS_RISK_LEVEL_FROM_VOLATILITY_REGIME_PROPOSAL_v1.0.md`, including an
  implementation map (touch points, untouched files, test impact).
- Owner decisions recorded in that proposal (all 2026-09-28):
  1. Direction: derive risk_level from the market-risk volatility regime.
  2. Macro cap: LOW only if Macro is available and not SELL; SELL or absent → at most MEDIUM
     (absence included for NB-4).
  3. Dashboard: show only the new level.
  4. "Like a real trader": LOW also needs an absolute volatility ceiling (value to be measured);
     multi-timeframe (24h) confirmation DEFERRED; volatility-scaled sizing = separate Phase B.
- Staleness question resolved (FACT): regime recomputed every cycle, no cache.
- New finding: the regime is relative to the trailing ~3h (percentile), so LOW occurs in roughly
  20% of cycles regardless of absolute volatility — the reason for the ceiling.
- Read-only measurement script delivered to the owner: `atlas_vol_ceiling_measure.py`
  (volatility per regime + bucket distribution from `C:\AtlasState`).
- Commits: `f05e3cd` (diagnosis checkpoint; its trailer names this same session, though the
  commit is outside this agent's visible context), `0745d6c` (proposal). CI green on `0745d6c`.

## Files changed
- `governance/ATLAS_RISK_LEVEL_FROM_VOLATILITY_REGIME_PROPOSAL_v1.0.md` (new; implementation map added after `0745d6c`)
- this checkpoint
No source, test, config or threshold change.

## Architecture decisions
Only the direction above; implementation needs an explicit grant in a registry successor record.

## Tests
None run (documentation only). Shell execution in this cloud session was intermittently blocked
by the harness's approval classifier.

## Current state
- Branch `claude/vigilant-maxwell-5vwebp`, PR onuryldzhan-cmyk/Atlas#1 open; CI green on
  `0745d6c` (runs 36397955289, 36397949530). PR activity is being watched.
- BUYs remain rejected in production-paper behaviour; nothing changed at runtime.

## Known issues
- Commit `0745d6c`'s message says it adds the checkpoint too; it only adds the proposal (the
  checkpoint arrived in `f05e3cd`). Not rewritten, to avoid history rewriting. The owner was
  told `f05e3cd` was not made by this session; its trailer shows it was — corrected here.
- This cloud session cannot read `C:\AtlasState` or run PowerShell on the owner's machine.

## Risks
- The LOW bucket is the most permissive sizing bucket (0.40 allocation); opening it lowers the
  confidence bar and raises size at once. Mitigated by ceiling + Macro cap; still CRITICAL.
- End-to-end brain tests may encode the current risk_level; UNKNOWN until checked at implementation.

## Remaining work (owner-gated, deferred by owner)
1. Run `atlas_vol_ceiling_measure.py` on `C:\AtlasState` (or open a local Claude Code session)
   → choose the absolute ceiling value.
2. Approve implementation of Phase A (registry successor grant) → CRITICAL final gate.
3. Review and merge PR onuryldzhan-cmyk/Atlas#1.
4. REM-001 Gate 1 decisions: D1/D2/D6 review, ARCH-001.2.1 schema custody, D7 definition,
   D9 language (registered `.ps1` vs Python candidate `tools/rem001_gate1_validator.py`).
5. RELSUP remediation proposal: G-S1 hang detection, G-S3 alert channel (needs owner-held credentials).
6. Later phases: A3 multi-timeframe confirmation (data-source question vs registry v4.79);
   Phase B volatility-scaled sizing.

## Next exact action
Owner runs the measurement script and pastes its output; then present ceiling options from the
measured LOW-regime volatility distribution.
