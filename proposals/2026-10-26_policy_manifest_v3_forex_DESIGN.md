# Policy manifest v3 (forex) — DESIGN for owner approval

**Status:** DRAFT, not in effect. The runtime keeps verifying `governance/policy/ATLAS_POLICY_MANIFEST_v2.json`.
**Owner request:** "Manifesto v3 hazırla" (2026-10-26).
**Owner values (2026-10-26):**
- forex commission: measure it on the MT5 demo account, and keep 0.1 % until then;
- open positions closed 30 minutes before the Friday close;
- the exit guard runs only the Friday-close rule in FOREX.

**Draft file:** `proposals/2026-10-26_policy_manifest_v3_forex_DRAFT.json`.

## What v3 changes

Five switches change or are added. Every other value is identical to v2.

| Switch | v2 | v3 draft | Why |
|---|---|---|---|
| `market` | not pinned | one of CRYPTO, FOREX | The market becomes part of the check. |
| `exit_guard_mode` | OBSERVE | CRYPTO: OBSERVE, FOREX: ENFORCE | So the weekend rule can actually close a position. |
| `exit_guard_rules` | 0 | CRYPTO: 0, FOREX: 1 | Exactly one rule, WEEKEND_CLOSE. |
| `forex_weekend_close_minutes` | — | 30 | Open forex positions are closed 30 minutes before Friday 17:00 New York. |
| `forex_paper_fee_rate` | — | 0.001 | Same as today's 0.1 %. It is replaced by the measured MT5 commission only through a new ratified manifest. |

Nothing in v3 can enable live trading: `verify()` still refuses any manifest that is not PAPER with live execution
disabled.

## What the weekend rule does
Every cycle in FOREX, from 30 minutes before the Friday close until the close, the exit guard turns each open
position into an exit intent. It goes through the guard's existing, audited path:
- a **reduce-only, full-exit SELL** submitted through `ExecutionManager.execute`, so idempotency, the journal,
  audit, recovery and the RiskEngine reduction checks all apply;
- **never on a stale or missing price** (`EXIT_PENDING_PRICE`);
- **idempotent:** a repeated trigger is the same request, so the SELL executes at most once.

Priority is unchanged: SAFETY_EXIT > PROTECTIVE_EXIT > the Brain's SELL > new-risk decisions. New entries already
stop 60 minutes before the close (Task 022). The 30-minute rule therefore only closes what is still open.

## Code an activation task would change (CRITICAL; not done)
1. **`core/policy_manifest.py`:**
   - support manifest_version 3;
   - add a `by_market` matcher, where a value is chosen by the runtime's `market`;
   - add the new switches to `CRITICAL_SWITCHES`;
   - pin the ratifying registry by id and sha256.
2. **`core/exit_guard.py`:**
   - add a `WEEKEND_CLOSE` rule kind, which triggers in the window before the close and uses the session clock;
   - existing rules are unaffected.
3. **`core/market_loop.py`:** run `ExitGuard.run_once` once per cycle in FOREX, before the Brain's decisions, with
   the cycle's fresh marks.
4. **`core/application.py`:**
   - in FOREX: an ExitGuard with the WEEKEND_CLOSE rule, ENFORCE mode, and the `forex_paper_fee_rate`;
   - CRYPTO keeps today's guard (OBSERVE, no rules).
5. **Governance:**
   - the owner ratifies v3 in a new registry;
   - v3 moves to `governance/policy/ATLAS_POLICY_MANIFEST_v3.json` with its integrity digest and the registry pin;
   - `MANIFEST_PATH` points to it;
   - v2 stays sealed and unchanged.
6. **Gate:**
   - tests for the rule window and boundaries (EDT and EST), a stale price, idempotency across a restart, CRYPTO
     unchanged (golden tests), and a mismatch causing BLOCK_NEW_RISK;
   - the full suite;
   - an independent read-only review with 0 BLOCKING / 0 HIGH / 0 MEDIUM before commit.

## Open points (UNKNOWN until verified)
- **The real commission of the owner's MT5 demo account** is UNKNOWN. It is measured from the account's deal
  history once MT5 runs on the owner's Windows machine.
- **MT5 call semantics are still unverified** on a real terminal (registry v5.102).

## What the owner approves
Approval of this design means two things:
- an activation task may implement steps 1–6;
- the owner ratifies the final v3 in a registry entry.

The agent records the decision but does not create or imply an owner signature.
