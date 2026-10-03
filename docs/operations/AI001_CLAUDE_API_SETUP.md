# AI-001: advisory agents on the owner's Claude Pro subscription (owner choice 2026-10-02)

## What runs
| Agent | How | Output |
|---|---|---|
| `ceo_ai` | Claude Code (`claude -p`), Sonnet, effort high | Up to 5 priorities grounded in cited memory record ids, as a `CEO-*` record. An answer citing a non-existent record is rejected. |
| `model_council` | Same, two independent perspectives (risk-focused and evidence-focused) | SUPPORT / OPPOSE / UNSURE / DISAGREEMENT on each open proposal not yet reviewed (up to 3 per run), as an `MC-*` record. A verdict is recorded only when both perspectives answered; otherwise it is retried later (audit 2026-10-03). |

| `explainable_ai` (trade review, 2026-10-03) | Same | After 5 new trade post-mortems (TP-*, one per closed trade, written rule-based), a review: patterns, follow-ups on its previous suggestions, at most 3 testable suggestions, as a `TR-*` record. |

All of them give **advice only**. They cannot trade, deploy, approve or change a threshold. The trading runtime never imports the gateway (ADR-0011).

**Apprentice (`ai_model_research`, 2026-10-03):** every new, validated answer is also kept in `<state>/research/apprentice/teacher.jsonl` (question and answer as sent and received, after the SensitiveDataGuard). `tools/apprentice.py` learns from the recorded answers: how the council votes and which evidence the CEO picks. Before each new answer it makes its own prediction, so its scores are honest. It never calls a model. When a score is high enough on enough cases its `AP-*` record says so; any takeover needs your approval.

## How `tools/ai_gateway.py` calls Claude Code
- **Command:** `claude -p --output-format json --json-schema … --model sonnet --effort high --tools "" --max-turns 3 --setting-sources user --strict-mcp-config`.
- **Prompt:** sent via stdin, after the SensitiveDataGuard.
- **Working directory:** a temporary empty folder. Claude Code sees no repository file and no project `CLAUDE.md`. It has no tools at all.
- **Credentials:** `ANTHROPIC_API_KEY` and `ANTHROPIC_AUTH_TOKEN` are removed from the child process, so your logged-in Pro subscription is used.
- **Failures:** CLI missing, not logged in, usage limit reached, timeout or malformed answer → ABSTAIN.

## Quota (owner rule)
~~Atlas cannot see your Pro usage percentage, so the quota counts **calls per rolling 5-hour window**: `ATLAS_AI_WINDOW_CALLS`, default **10**; all agents together may use at most **60 %** of it (6 calls); that share is split by task size: CEO **2** calls, council **4** calls; an agent stops at its share; an agent not in the list cannot call at all.~~ **[SUPERSEDED 2026-10-03 by the owner. Reason: tie the budget to the whole 5-hour window and let each agent use what its work needs. Text kept, not erased.]**

**Owner rule 2026-10-03:** the agents may use the **whole** rolling 5-hour window of your plan, each as much as its work needs. There is no 60 % share and no fixed split between agents.
- **Budget:** Atlas cannot see your Pro usage, so the plan's own 5-hour limit is the budget. When Claude Code says the limit is reached, the agents abstain until the window rolls.
- **Your own ceiling (optional):** `ATLAS_AI_WINDOW_CALLS` = calls per rolling 5 hours, used in full. Unset means no Atlas ceiling. An unreadable value means no calls.
- **No repeated questions:** an agent never pays twice for the same question within 24 hours. If it was answered, the same answer is served again for free; if it was not (timeout, error), it is not resent. Only new evidence makes a new question.
- **Counted before it is sent:** every call is written to the usage ledger before it goes out, so a call that times out, crashes or is stopped still counts against every limit below (audit 2026-10-03).
- **Runaway stop:** at most **12** calls per agent per 5 hours. Normal need is far below that (CEO ≤ 2, council 2 per new proposal), so reaching it means a loop.
- **Allowlist:** only `ceo_ai`, `model_council` and `explainable_ai` may call a model.

Every call uses part of **your own** plan allowance. Anthropic: "Both Pro and Max plans offer usage limits that are shared across Claude and Claude Code, meaning all activity in both tools counts against the same usage limits" (support.claude.com, article 11145838, read 2026-10-03). So if the agents use the whole window, your own Claude use waits for the reset too. If you want to keep part of the window for yourself, set a ceiling, for example `setx ATLAS_AI_WINDOW_CALLS "8"`.

## Owner steps (Windows PowerShell)
1. Remove the placeholder key set earlier, so it can never shadow the subscription:
   `[Environment]::SetEnvironmentVariable("ANTHROPIC_API_KEY", $null, "User")`
2. Close and reopen PowerShell.
3. Check that Claude Code is installed and logged in: `claude --version`, then `claude` (type `/login` if asked; exit with `/exit`).
4. Optional, set your own ceiling of calls per 5 hours: `setx ATLAS_AI_WINDOW_CALLS "8"` (unset = the whole plan window)
5. Start Atlas: `python -m tools.start_atlas`

`ATLAS_AI_BACKEND=api` switches back to the paid API-key path.
