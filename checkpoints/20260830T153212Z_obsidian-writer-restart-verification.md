# ATLAS CHECKPOINT — 20260830T153212Z

## Objective
Successor to `checkpoints/20260830T152232Z_obsidian-writer-mcp-diagnosis.md`. Complete the restart-verification it deferred: confirm whether (1) the main-session `mcp__filesystem__*` leak and (2) `atlas-obsidian-writer`'s wrong-directory bug both survive a genuine Claude Code CLI restart, then determine whether a `/feedback` bug report to Anthropic is actually warranted by the evidence.

## Completed
1. User confirmed a full quit-and-relaunch of the `claude` process (explicitly not `/clear`, not `--continue`) between the prior checkpoint and this one.
2. Re-ran `ToolSearch` for `"filesystem"` post-restart: all 14 `mcp__filesystem__*` tools still returned with complete schemas, immediately, no "still connecting" phase. Re-ran `claude mcp list`: still genuinely "No MCP servers configured" — the config itself remains clean.
3. Re-invoked `atlas-obsidian-writer` (a fresh `Agent` call) with its unchanged, already-correct config: `list_allowed_directories` again reported the repo root (`...SOURCE_REPOSITORY\SOURCE_REPOSITORY`), and `read_text_file` on `START_HERE.md` again failed with `ENOENT` at that root — identical signature to both pre-restart runs.
4. **Critical disambiguation, performed before drawing any conclusion**: rather than accepting "a restart happened" as sufficient grounds to call either finding "confirmed across restart," called `mcp__ccd_session_mgmt__get_session("self")` to check this session's own metadata directly. Result: `createdAt: "2026-08-28T14:32:23.386Z"` — two days before the current date (2026-08-30) and before this entire conversation. This proves this specific session is a **resumed/continued session**, not a newly-created blank one, despite the underlying `claude` process genuinely having been fully quit and relaunched. (Exact mechanism by which relaunching reattached to this pre-existing session rather than starting blank is UNKNOWN — requires verification; plausibly automatic session-resume behavior in this environment's client layer.)
5. Consulted `claude-code-guide` a second time, specifically on whether Claude Code documents any tool-list caching for local stdio MCP servers that could explain persistence across both config removal and a restart. Finding: documentation only describes a discovery cache for remote HTTP/SSE servers (`MCP_DISCOVERY_CACHE`, off by default), nothing documented for local stdio servers like `server-filesystem`, and the CLI reference states plain `claude` should start a fresh session. No documented mechanism explains the observed persistence under the assumption of a truly blank session — but step 4's finding shows the session was not in fact blank, which fully accounts for the observation without needing to invoke an undocumented bug.
6. **Disambiguated the two findings' evidentiary status — they are not equally confirmed:**
   - **Subagent wrong-directory bug** (`atlas-obsidian-writer` resolving to the repo cwd instead of the configured "Atlas Memory" path): **CONFIRMED reproducible across a genuine process restart.** This finding is not confounded by the parent session being resumed, because each `Agent`-tool invocation spawns an independent, fresh subagent process that reads the current agent file and establishes its own new MCP connection at spawn time, regardless of the orchestrating session's own history/age. Reproduced in 3 separate fresh subagent invocations across two checkpoints now (real vault path; a space-free scratch path; real vault path again post-restart), all with the identical repo-root-fallback signature.
   - **Main-session `mcp__filesystem__*` leak "surviving a restart"**: **NOT CONFIRMED** as a restart-surviving bug. Fully and adequately explained by this being a resumed session (its `createdAt` predates the restart) that appears to have carried forward previously-established MCP tool-connection state rather than re-deriving it from the now-clean config. A clean test of this requires a genuinely new session (fresh `createdAt`), which has not yet been performed.
7. Drafted — **not submitted**, since no tool exists to submit `/feedback` on the user's behalf; it is an interactive terminal command outside this session's available tools — a precise, reproducible bug report scoped **only** to the confirmed subagent finding, for the user to submit themselves. The unconfirmed main-session-leak finding was deliberately excluded from that draft, to avoid handing Anthropic a claim not actually supported by evidence:

   > **Bug: agent-scoped inline `mcpServers` (subagent frontmatter) does not forward trailing stdio server args on Windows — server falls back to process cwd**
   >
   > Environment: Windows 11, Claude Code CLI (WinGet install, `Anthropic.ClaudeCode` package), Node v24.20.0.
   >
   > Repro:
   > 1. A subagent definition (`.claude/agents/<name>.md`) frontmatter includes:
   > ```yaml
   > mcpServers:
   >   - <server-name>:
   >       type: stdio
   >       command: cmd
   >       args:
   >         - /c
   >         - npx
   >         - -y
   >         - "@modelcontextprotocol/server-filesystem@<version>"
   >         - "<absolute-path>"
   >       env: {}
   > tools: mcp__<server-name>__*
   > ```
   > 2. Invoke the subagent and call `mcp__<server-name>__list_allowed_directories`.
   > 3. Expected: reports `<absolute-path>` as configured.
   > 4. Actual: reports the session's project working directory instead — the trailing directory argument never reaches the spawned `server-filesystem` process, which falls back to its own `process.cwd()`.
   >
   > Isolation performed:
   > - The identical `command`/`args` pair, spawned directly via Node's `child_process.spawn` outside Claude Code, works correctly (server reports the correct configured directory) — rules out a Windows `cmd.exe`/`npx` quoting issue.
   > - The YAML shape (`mcpServers:` as a list of single-key maps) matches Claude Code's documented schema for agent-scoped inline MCP servers — rules out a config-schema mistake.
   > - Replacing `<absolute-path>` with a different, pure-ASCII, space-free path reproduces the identical failure (repo root reported instead) — rules out any dependency on the path's content (spaces, Unicode).
   > - Reproduced across 3 separate subagent invocations, including after a full quit-and-relaunch of the `claude` process — not a stale-connection artifact of a long-running session.
   >
   > Impact: agent-scoped inline `mcpServers` for stdio servers with directory/path arguments is currently non-functional on this platform/build; the server always resolves to the project cwd regardless of configured args.

## Files changed
Verified via `git status --porcelain=v1` and `git diff --stat` run at checkpoint time: both empty of any tracked-file change (only the same three pre-existing untracked entries from session start: `.agents/`, `.claude/skills/claude-automation-recommender/`, `skills-lock.json` — untouched). No files were modified during this checkpoint's investigation. This checkpoint file itself is new: `checkpoints/20260830T153212Z_obsidian-writer-restart-verification.md`.

## Architecture decisions
None made or changed.

## Tests
- `mcp__ccd_session_mgmt__get_session("self")` — direct, verifiable evidence of session resume (`createdAt` 2026-08-28 vs. current date 2026-08-30). This is the pivotal piece of evidence in this checkpoint.
- Repeat `ToolSearch("filesystem")` and `claude mcp list` post-restart — leak persists in the tool list; config independently confirmed still clean.
- Third fresh `atlas-obsidian-writer` invocation post-restart — identical `ENOENT`-at-cwd failure; third reproduction of the same defect.
- Second `claude-code-guide` consultation, focused specifically on documented caching behavior for local stdio MCP servers — found no such documented mechanism, which is why the session-resume explanation (not an undocumented cache bug) is preferred for the main-session-leak observation.

## Current state
The subagent bug is fully diagnosed and confirmed-reproducible across a genuine restart; a precise, scoped bug report is drafted and ready for the user to review and submit via `/feedback`. The main-session-leak question remains genuinely open — not currently believed to be a CLI bug, but not confirmed clean either, pending a test in an actual newly-created (non-resumed) session.

## Known issues
- Same core issue as the prior checkpoint: `atlas-obsidian-writer` cannot reach the real "Atlas Memory" vault on this CLI build.
- This conversation's session is confirmed resumed (created 2026-08-28), not fresh. Any future "does X survive a restart" question asked within this same conversation will not cleanly test that on its own — first check `get_session("self")`'s `createdAt` is current before trusting a "clean" result as proof of a true fresh start.

## Risks
- If a future session or the user submits a `/feedback` report that conflates the two findings (treating the main-session leak as also restart-confirmed), that report would contain a claim not actually supported by evidence. The two findings must stay separated in any external report; only the subagent finding is currently solid enough to report.
- If the user starts a genuinely fresh session to test the main-session leak and it turns out still present there too, that would upgrade it to a real, separate, reportable finding — this checkpoint deliberately does not presume that outcome either way.

## Remaining work
1. User reviews and decides whether to submit the drafted `/feedback` report (scoped to the subagent bug only) via their own interactive terminal.
2. If the main-session-leak question still matters, test it properly: start a genuinely new session, confirm via `get_session("self")` that its `createdAt` is current (not inherited from a prior session), then check `ToolSearch("filesystem")` there.
3. Once (if) a CLI-level fix or workaround for the subagent arg-forwarding bug becomes available, re-run the same `list_allowed_directories` + `read_text_file` verification used throughout this and the prior checkpoint to confirm `atlas-obsidian-writer` actually works before relying on it for any real vault task.

## Next exact action
Present the drafted `/feedback` content to the user for their review/submission, and ask whether they want the main-session-leak question tested in a genuinely fresh (non-resumed) session.
