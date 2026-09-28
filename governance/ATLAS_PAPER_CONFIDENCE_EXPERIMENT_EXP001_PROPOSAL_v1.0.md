# Proposal — EXP-001: paper-only confidence-floor experiment

| Field | Value |
| --- | --- |
| Status | `AUTHORIZED` by registry v4.94 (`GRANT-EXP001-PAPER-CONFIDENCE-EXPERIMENT`); implemented — see §11 |
| Tier | CRITICAL (changes which PAPER BUY requests the RiskEngine admits) |
| Owner decision recorded | 2026-09-28: "lower thresholds as a paper experiment", not as a permanent rule |
| Related | `governance/ATLAS_RISK_LEVEL_FROM_VOLATILITY_REGIME_PROPOSAL_v1.0.md` (independent; see §8) |
| Live effect | NONE. `live_authority=DENIED`, `live_status=BLOCKED` unchanged |

## 1. Purpose

Today every BUY is rejected `CONFIDENCE_BELOW_POLICY` (diagnosis:
`checkpoints/20260928T070000Z_buy-risk-bucket-confidence-diagnosis.md`). Nobody knows whether a
60–65 confidence BUY is a good or bad trade, because none has ever been executed. The experiment
produces that evidence in PAPER, with no real capital, so that thresholds can later be set from
measured outcomes instead of being fitted to the scores the system happens to emit.

It is explicitly **not** a threshold change. At the end the defaults return unchanged unless a
separate, evidence-backed decision says otherwise.

## 2. Rule during the experiment

| Bucket | Minimum confidence: default → experiment | Max allocation / exposure ceiling |
| --- | --- | --- |
| LOW | 0.60 → 0.60 | unchanged (0.40 / 0.60) |
| MEDIUM | 0.70 → **0.60** | unchanged (0.25 / 0.40) |
| HIGH | 0.80 → **0.60** | unchanged (**0.10** / 0.20) |

Global minimum stays 0.60 (`core/risk_engine.py:161`). All three buckets share one floor, so the
ladder does not invert: buckets then differ only in *size*, and riskier means smaller. Today's
BUYs fall in HIGH, so they would execute at a 10% allocation ceiling — the most restrictive sizing
Atlas has. Every other RiskEngine check is unchanged: daily loss, drawdown levels, exposure,
per-symbol, concentration, CRITICAL/UNKNOWN rejection, SELL reduce-only.

## 3. Containment (the part that makes it safe)

1. **PAPER only, fail-closed.** The experimental policy may only be constructed when
   `execution_mode == "PAPER"` (`core/application.py:454`). Any other mode with the experiment
   enabled refuses to start rather than silently falling back.
2. **Code-pinned, not configurable.** Experiment id, floor and end date are constants in code and
   in the grant record. No config file or environment variable can enable, extend or loosen it.
3. **Self-expiring.** After the end date (or the sample cap, §5) the default policy is used
   automatically. Expiry can only tighten.
4. **One construction site.** `core/application.py:768-778` builds the single `RiskPolicy` shared
   by `RiskEngine` and `PositionSizingService`, so sizing and admission cannot drift apart.
5. **Tagged outcomes.** A BUY that is admitted *only because of* the lowered floor (confidence
   between 0.60 and its default bucket floor) carries a distinct reason code in the audit event,
   e.g. `RISK_APPROVED_UNDER_EXP001`. Its realized P&L can then be separated from normal trades.
6. **Dashboard banner.** While active, the panel shows that EXP-001 is running and until when.

## 4. What does not change

Agent fusion, ConfidenceEngine, advisory risk scorer, decision builder, `risk_level` assignment,
sizing percentages, every other RiskEngine limit, live gating, the capital ladder
(this stays inside the Paper stage), and CLAUDE.md doctrine.

## 5. Duration, sample and stop conditions (owner to choose values)

- Duration (owner-decided): **14 days** or **50 experiment-tagged BUYs**, whichever comes first.
- Stops early (reverts to defaults) on: daily loss limit reached, drawdown level ≥ RESTRICT,
  any reconciliation or integrity halt, or owner instruction.

## 6. What is measured

Per confidence band (60–65, 65–70, 70–80) and per bucket: count, win rate, realized P&L per
trade, average holding time, maximum adverse excursion, and drawdown contribution. Read-only
analysis from the audit log and closed-positions journal after the run.

## 7. Invariants

| Invariant | Assessment |
| --- | --- |
| NB-4 | Not touched: no confidence computation changes; removing evidence behaves as before. |
| NB-5 | Not touched: roster denominator unchanged. |
| Capability ≠ authority | RiskEngine remains the sole admission authority; the change is a bounded, expiring policy input in PAPER only. |
| "Never raise confidence without evidence" | Confidence values are not raised; the bar is lowered temporarily *to obtain* the missing evidence, and the result is recorded, not assumed. |
| Less conservative somewhere? | Yes, deliberately and only in PAPER: HIGH and MEDIUM BUYs at ≥ 0.60 are admitted, at their unchanged (small) sizes. |

## 8. Relationship to the risk_level proposal

Independent and composable. EXP-001 needs no volatility ceiling and can start first. Its outcome
data (P&L by confidence and by volatility regime) is direct evidence for choosing the ceiling and
the final floors in the risk_level proposal.

## 9. Test plan (before implementation is accepted)

1. Experimental policy constructible only in PAPER; LIVE/SHADOW with experiment enabled refuses to start.
2. After the end date or sample cap, the default policy is in force (clock injected in tests).
3. 0.63 HIGH BUY admitted at ≤ 0.10 allocation with the EXP-001 reason code; 0.59 rejected.
4. Every non-confidence rejection path unchanged (parametrized over existing reasons).
5. Default-policy behaviour byte-identical when the experiment is inactive.
6. Full suite: only the accepted B2 failure. CRITICAL final gate incl. independent audit.

## 10. Open questions for the owner

All three RESOLVED by the owner on 2026-09-28:
1. ~~Experiment floor?~~ **0.60 for the included buckets** (equal to the global minimum; nothing
   below the existing absolute floor is opened).
2. ~~Duration / sample cap?~~ **14 days or 50 experiment-tagged BUYs, whichever comes first.**
3. ~~Include MEDIUM?~~ **Yes: HIGH and MEDIUM.** The ladder stays coherent (one 0.60 floor);
   MEDIUM BUYs may open up to its unchanged 0.25 allocation.

Remaining before implementation: the owner's explicit grant (below).

## Authorization

Granted by the owner on 2026-09-28, recorded in
`governance/current/ATLAS_MILESTONE_REGISTRY_v4.94.json` (`grant_exp001_paper_confidence_experiment`).

## 11. Implementation notes (as built — deviations from §3 stated explicitly)

- **Where:** `core/risk_engine.py` (`ConfidenceFloorExperiment`, pinned
  `EXP001_PAPER_CONFIDENCE_EXPERIMENT`, `RiskEngine.attach_experiment`), `core/application.py`
  (`_attach_paper_confidence_experiment`, `count_experiment_admissions`),
  `core/execution_manager.py` (tag in approval `details`), `main.py` (opt-in).
- **Not a RiskPolicy change.** Implemented as a separate RiskEngine input because
  `RiskEngine.evaluate` requires the restored state's `policy_version` to equal the policy's
  (`RISK_POLICY_STATE_MISMATCH`); a new policy object would have blocked all trading.
- **Deviation from §3.1 — activation is opt-in.** Instead of "refuse to start in other modes",
  the experiment is attached only when `AtlasApplication(paper_confidence_experiment=True)` *and*
  `execution_mode == "PAPER"`; otherwise it is simply not attached (default floors = the
  fail-closed state). Only `main.py` opts in (pinned by a test). Reason: attaching it to every
  PAPER application made existing tests time-dependent (they would change behaviour at the
  window start).
- **Deviation from §3.5 — reason code.** The approval keeps `RISK_APPROVED` (recovery and the
  audit stage map depend on it); the tag is the separate `experiment_id` field on `RiskDecision`
  and in the `RISK_APPROVED` audit event's `details`. Verified: the audit sanitizer keeps
  `details.experiment_id` (not a sensitive key; value `EXP-001` matches no redaction pattern).
- **Deviation from §3.6 — dashboard banner DEFERRED.** Not implemented in this change;
  `RiskEngine.status()["experiment"]` exposes the state for a later panel change.
- **Sample cap:** counted in memory at RiskEngine approval (conservative: downstream refusals
  and re-evaluations also count) and restored at startup from `RISK_APPROVED` audit events.
  An unreadable audit log leaves the experiment unattached.
- **Audit-write failure closes the experiment (independent-audit fix, MEDIUM).** If the
  `RISK_APPROVED` event of an experiment admission cannot be written (write error or audit
  disabled), `ExecutionManager._close_experiment_if_unrecorded` closes the experiment for the
  rest of the process. Residual: after a restart that single unrecorded admission is not
  counted, so the cap can be exceeded by at most one per failed-write-then-restart; each such
  event is logged as an audit write failure.
- **Atomic cap (independent-audit fix, LOW).** `risk_check` is not called under the
  ExecutionManager lock, so the cap is re-checked and incremented under a RiskEngine lock at the
  moment of approval; concurrent evaluations cannot overshoot it.

## 12. Verification (2026-09-28, Python 3.13, pytest 9.1.1)

- `tests/test_exp001_paper_confidence_experiment.py`: 58 passed.
- Mutation check: 10/10 mutants killed (end-inclusive window, no cap counting, floor below global
  minimum, bucket restriction removed, mode check removed, opt-in removed, attach despite
  unreadable audit log, close ignored, no close on failed audit write, no atomic cap re-check —
  the last one via a test that forces the race deterministically).
- Independent audit (separate agent, read-only): **PASS WITH FINDINGS** — all seven hard
  boundaries confirmed; MEDIUM (cap durability on audit-write failure) and LOW (counter
  thread-safety) fixed as above; LOW (in-process counter counts downstream refusals, i.e. closes
  early) accepted as conservative and documented; INFORMATIONAL items noted.
- Re-test after fixes, full suite: **5138 passed, 1 failed (accepted B2 signature, confirmed by
  `tools/ci_check_known_accepted_failures.py`), 11 skipped**.
- Not verified: behaviour in a running Atlas instance (UNKNOWN until the owner restarts Atlas).
