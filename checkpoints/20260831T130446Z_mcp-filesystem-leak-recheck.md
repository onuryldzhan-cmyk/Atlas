# ATLAS CHECKPOINT — 20260831T130446Z

## Objective
Successor to `checkpoints/20260830T153212Z_obsidian-writer-restart-verification.md`. That checkpoint left one question genuinely open: whether the main-session `mcp__filesystem__*` tool leak survives in a verifiably fresh (non-resumed) session, since its own test was confounded by running inside a resumed session. This checkpoint was requested explicitly as that follow-up test: call `get_session("self")` first to confirm session freshness, then re-check `ToolSearch("filesystem")` and `claude mcp list`, and investigate the source of any still-appearing "MCP filesystem: Server disconnected" message.

## Completed
1. Called `mcp__ccd_session_mgmt__get_session("self")`. Result: `createdAt: "2026-08-28T14:32:23.386Z"`, `lastActivityAt: "2026-08-31T13:01:50.323Z"`, `sessionId: "local_937f4b77-83bc-4e1d-a29e-4c682cb4470d"`, title "Atlas research/edge-validation infrastructure". **This `createdAt` is identical, to the millisecond, to the one reported in the 2026-08-30 checkpoint.** This is not a new session — it is the same resumed session continuing into a third calendar day (created 2026-08-28, checkpointed 2026-08-30, still active 2026-08-31). The request's framing — "confirm this is a genuinely new session" — does not hold; this must be reported as a failed precondition, not confirmed.
2. Re-ran the filesystem-tool discoverability check despite the confounded precondition, since a result either way is still evidence. Two independent checks, both clean:
   - Targeted `ToolSearch("select:mcp__filesystem__list_allowed_directories,mcp__filesystem__read_text_file,mcp__filesystem__read_file")` → `"No matching deferred tools found."`
   - The full deferred-tools list delivered in this conversation's opening system-reminder (the standard list of not-yet-loaded tools for this turn) contains zero `mcp__filesystem__*` entries — checked by reading that list directly.
   - An earlier, broader `ToolSearch("filesystem", max_results=15)` in this same session matched only `ExitWorktree` (an unrelated fuzzy match on wording, not a real filesystem-server tool).
   
   This contrasts with the 2026-08-30 checkpoint, where the identical check (in this same session, post a confirmed full process restart) returned all 14 `mcp__filesystem__*` tools with complete schemas.
3. Re-ran `claude mcp list` → `"No MCP servers configured. Use \`claude mcp add\` to add a server."` Identical to both prior checkpoints. Confirms nothing appears at main-session level, including no entry for `atlas-obsidian-writer` — which is the expected, correct result: that agent's MCP server is declared inline in its own agent-scoped frontmatter (`.claude/agents/atlas-obsidian-writer.md`), never registered via `claude mcp add`, so it was never going to appear in this command's output regardless of whether the subagent itself works.
4. Investigated the source of any residual "filesystem" config entry, across every config surface reachable from this session, to answer whether a still-appearing disconnect message (if any) could be traced to a leftover config entry:
   - `find . -maxdepth 3 -iname "*.mcp.json"` at repo root → no results. No project-level `.mcp.json` exists.
   - `grep -ril "filesystem" .claude` → two hits only: `.claude/agents/atlas-obsidian-writer.md` (its own legitimate agent-scoped `@modelcontextprotocol/server-filesystem@2026.7.10` entry, line 12 — expected and correct) and `.claude/hooks/atlas_db_read_guard.py` (+ its compiled `.pyc`), which uses the word "filesystem" in unrelated prose/code, not as an MCP server config.
   - `grep -n -i "filesystem"` against the user-level `~/.claude.json` and `~/.claude/settings.json` → zero matches in both.
   - Conclusion: no leftover "filesystem" MCP config entry exists anywhere in accessible config at main-session scope, project or user level. The only live "filesystem" MCP reference anywhere in this repository's or this user's config is `atlas-obsidian-writer`'s own intended agent-scoped one.
5. Attempted to directly observe whether "MCP filesystem: Server disconnected" is currently visible to the user, via `mcp__terminal__read_terminal` (reads the user's integrated terminal panel, last ~200 lines, ANSI stripped). Result: a bare PowerShell prompt at the repository root, no other visible output — no CLI startup banner, no MCP status lines, no disconnect message of any kind. This result is **inconclusive, not a clean negative**: the total absence of even a Claude Code CLI startup banner in that pane raises doubt about whether this is actually the terminal running the `claude` process the user means, versus a different/idle terminal, or a pane whose earlier output has simply scrolled past the ~200-line window. This tool cannot substitute for asking the user directly where they see (or saw) the message.

## Files changed
Verified via `git status --porcelain=v1` (run at 20260831T130446Z) and `git diff --stat` / `git diff --cached --stat`: both diff commands report no output (no tracked-file changes, staged or unstaged). `git status` shows the same three pre-existing untracked entries as every prior checkpoint in this series (`.agents/`, `.claude/skills/claude-automation-recommender/`, `skills-lock.json`), plus the previous checkpoint file itself (`checkpoints/20260830T153212Z_obsidian-writer-restart-verification.md`, untracked until committed) — none touched by this session. This checkpoint file is new: `checkpoints/20260831T130446Z_mcp-filesystem-leak-recheck.md`.

## Architecture decisions
None made or changed.

## Tests
- `mcp__ccd_session_mgmt__get_session("self")` — direct evidence the session is still the same resumed one from 2026-08-28 (identical `createdAt`), not a fresh session, despite the request asking to confirm freshness.
- Targeted `ToolSearch` for the three previously-leaked `mcp__filesystem__*` tool names — all three now return no match.
- Broad `ToolSearch("filesystem")` — matches nothing but an unrelated tool.
- Deferred-tools list in this conversation's own system-reminder — independently corroborates zero `mcp__filesystem__*` tools present.
- `claude mcp list` — unchanged clean result, third consecutive checkpoint confirming it.
- `grep`/`find` across repo `.mcp.json`, `.claude/settings.json`, `.claude/settings.local.json`, user-level `~/.claude.json`, `~/.claude/settings.json` — no residual "filesystem" config entry found anywhere except `atlas-obsidian-writer`'s own intended one.
- `mcp__terminal__read_terminal` — attempted direct observation of the user's terminal; returned a blank prompt, which is inconclusive for the reasons stated in Completed item 5.

## Current state
The subagent wrong-directory bug (`atlas-obsidian-writer` resolving to repo cwd instead of the configured vault path) is unchanged from the prior checkpoint — **not re-tested this session**, no new evidence gathered on it either way; it still stands as previously recorded (CONFIRMED reproducible across a restart, as of 2026-08-30).

The main-session `mcp__filesystem__*` leak question is now **partially resolved, with a caveat that must not be dropped**: the leak is confirmed ABSENT right now, in the very same resumed session where it was previously confirmed PRESENT (post-restart, on 2026-08-30) — and no config-file source for it exists anywhere reachable. However, because `get_session("self")` proves this is still not a genuinely fresh session, this result does **not** meet the "test in an actual newly-created session" bar that the prior checkpoint's remaining-work item 2 called for. It is new evidence, not a closing one.

The mechanism for why the leak was present on 2026-08-30 and is absent now, within the same session, is **UNKNOWN — requires verification**. Candidate explanations (none confirmed): an unreported subsequent full process restart that this time rebuilt the tool-discovery list cleanly from config; a context-compaction event (this session's transcript has grown across three days and multiple checkpoints, and compaction is documented to occur automatically) that incidentally reset cached tool-discovery state; or some other mechanism not yet identified. None of these should be asserted as the cause without further evidence.

Whether "MCP filesystem: Server disconnected" is still visible to the user right now is **UNKNOWN — requires verification from the user directly**; the one available tool for observing it (`mcp__terminal__read_terminal`) produced an inconclusive blank result rather than a confirmed absence.

## Known issues
- Same core issue as both prior checkpoints: `atlas-obsidian-writer` cannot reach the real "Atlas Memory" vault on this CLI build (unchanged, not re-tested this session).
- This conversation's session is confirmed, for the second time now (2026-08-30 and again 2026-08-31), to be a long-lived resumed session, not a fresh one. Any future test of "does X survive a restart / does X happen in a fresh session" asked within this same conversation will not cleanly test that — `get_session("self")`'s `createdAt` must be checked and shown to match the actual moment of the test, not just be "recent," before trusting a result as proof of a true fresh start.

## Risks
- If a future report (internal or an external `/feedback` submission) treats today's clean `ToolSearch`/`claude mcp list` result as proof the main-session leak is fixed or was never a real bug, that claim would outrun the evidence: the confounding factor (same resumed session) is unchanged from the prior checkpoint, only the observed symptom flipped from present to absent. The correct framing is "absent now, cause unknown, still untested in a genuinely fresh session" — not "resolved."
- If the user is in fact still seeing "MCP filesystem: Server disconnected" in their UI right now, this checkpoint has not identified its source — the message cannot currently be attributed to any config entry or tool-discovery state this session can observe. Treating the message as explained without locating an actual source would be a hallucinated conclusion under CLAUDE.md's No Hallucination Policy.

## Remaining work
1. Ask the user directly whether they restarted the `claude` process again at any point between the 2026-08-30 checkpoint and now — this is the single most useful missing fact for disambiguating why the leak symptom disappeared.
2. Ask the user exactly where they still see, or last saw, "MCP filesystem: Server disconnected" (a persistent status line, `/mcp` panel output, a one-time startup banner, or elsewhere) — this session cannot reliably observe the user's own CLI chrome, and `/mcp` itself is an interactive-only command not available to run from here.
3. If the main-session-leak question still matters to the user, the only fully clean remaining test is a verifiably fresh session: start one, confirm via `get_session("self")` that `createdAt` matches the actual session-start time (not an inherited older value) before trusting any "clean" result from it as proof of a true fresh start.
4. The subagent wrong-directory bug's drafted `/feedback` report (from the 2026-08-30 checkpoint) still awaits the user's own review/submission — unchanged, not actioned this session.

## Next exact action
Report these findings to the user in chat; ask where they currently observe the disconnect message and whether another restart happened since 2026-08-30; do not represent the main-session-leak question as closed until it has been tested inside a session whose `createdAt` is verified current at test time.
