# AI-001: Claude API setup for the advisory agents (owner choice 2026-10-02)

## What runs
| Agent | Model | What it writes |
|---|---|---|
| `ceo_ai` | `claude-opus-5-5` | Up to 5 priorities for the owner, grounded in cited memory record ids, as a `CEO-*` record. An answer that cites a non-existent record is rejected. |
| `model_council` | `claude-opus-5-5` and `claude-sonnet-5-5`, independently | A review of the newest open proposal: SUPPORT, OPPOSE, UNSURE or DISAGREEMENT, as an `MC-*` record. |

Both are **advice**. They cannot trade, deploy, approve or change a threshold. The trading runtime never imports the gateway (ADR-0011; architecture test).

## Safety in `tools/ai_gateway.py`
- **Credentials** come from the environment only. Nothing is stored in the repository.
- **Prompts** pass the SensitiveDataGuard before they are sent.
- **Answers** must match a JSON schema and are validated twice.
- **Failures abstain:** a refusal, timeout, malformed answer or truncated answer gives ABSTAIN.
- **Daily cost cap:** `ATLAS_AI_DAILY_BUDGET_USD`, default **1.00 USD**.
- **Owner quota rule (2026-10-02):** all AI agents together may use at most **60 %** of the daily budget. That share is split by task size (weight = model calls per run): `ceo_ai` weight 1, `model_council` weight 2. With a 3.00 USD budget, the CEO gets 0.60 USD and the council 1.20 USD. An agent stops at its own share; an agent not in the list cannot spend at all. Adding an agent re-splits the shares automatically.
- **Second lock, outside Atlas:** set a monthly spend limit on the API key in the Anthropic Console. The spend ledger is `<state>/research/ai_usage.json`; if it is unreadable, nothing is spent.

## Owner steps (Windows PowerShell, once)
1. Install the SDK:
   `python -m pip install -r requirements-ai.txt`
2. Set the key **for your user only**. Never put it in a file in the repository:
   `setx ANTHROPIC_API_KEY "<your key>"`
3. Optional, change the daily cap:
   `setx ATLAS_AI_DAILY_BUDGET_USD "1.00"`
4. Close and reopen PowerShell, then start Atlas as usual:
   `python -m tools.start_atlas`

**Without a key:** the two agents show "AI-001 çekimser: NO_CREDENTIALS" and do nothing else.
