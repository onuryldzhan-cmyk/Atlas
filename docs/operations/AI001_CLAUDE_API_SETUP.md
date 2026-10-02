# AI-001: advisory agents on the owner's Claude Pro subscription (owner choice 2026-10-02)

## What runs
| Agent | How | Output |
|---|---|---|
| `ceo_ai` | Claude Code (`claude -p`), Sonnet, effort high | Up to 5 priorities grounded in cited memory record ids, as a `CEO-*` record. An answer citing a non-existent record is rejected. |
| `model_council` | Same, two independent perspectives (risk-focused and evidence-focused) | SUPPORT / OPPOSE / UNSURE / DISAGREEMENT on the newest open proposal, as an `MC-*` record. |

Both give **advice only**. They cannot trade, deploy, approve or change a threshold. The trading runtime never imports the gateway (ADR-0011).

## How `tools/ai_gateway.py` calls Claude Code
- **Command:** `claude -p --output-format json --json-schema … --model sonnet --effort high --tools "" --max-turns 3 --setting-sources user --strict-mcp-config`.
- **Prompt:** sent via stdin, after the SensitiveDataGuard.
- **Working directory:** a temporary empty folder. Claude Code sees no repository file and no project `CLAUDE.md`. It has no tools at all.
- **Credentials:** `ANTHROPIC_API_KEY` and `ANTHROPIC_AUTH_TOKEN` are removed from the child process, so your logged-in Pro subscription is used.
- **Failures:** CLI missing, not logged in, usage limit reached, timeout or malformed answer → ABSTAIN.

## Quota (owner rule)
Atlas cannot see your Pro usage percentage, so the quota counts **calls per rolling 5-hour window**:
- `ATLAS_AI_WINDOW_CALLS`, default **10**.
- All agents together may use at most **60 %** of it (6 calls).
- That share is split by task size: CEO **2** calls, council **4** calls (two perspectives per proposal).
- An agent stops at its share. An agent not in the list cannot call at all.

Every call uses part of **your own** Pro 5-hour allowance.

## Owner steps (Windows PowerShell)
1. Remove the placeholder key set earlier, so it can never shadow the subscription:
   `[Environment]::SetEnvironmentVariable("ANTHROPIC_API_KEY", $null, "User")`
2. Close and reopen PowerShell.
3. Check that Claude Code is installed and logged in: `claude --version`, then `claude` (type `/login` if asked; exit with `/exit`).
4. Optional, change the call quota: `setx ATLAS_AI_WINDOW_CALLS "10"`
5. Start Atlas: `python -m tools.start_atlas`

`ATLAS_AI_BACKEND=api` switches back to the paid API-key path.
