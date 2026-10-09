# proposals/

Written output of Atlas's research-scout subagents. Each file is a
**proposal for owner review**, not a decision and not an implementation.

- One file per proposal, named `<YYYYMMDDTHHMMSSZ>_<kebab-slug>.md` (UTC,
  same convention as `checkpoints/`). The slug starts with the scout's domain,
  e.g. `dashboard-`.
- Each proposal carries `Status: PROPOSED — awaiting owner review` until the
  owner records ACCEPT / DEFER / REJECT.
- An accepted proposal is implemented through the normal Atlas workflow
  (CLASSIFY → IMPLEMENT → TEST → REVIEW, and the full critical-task gate where
  it applies) in a regular session. The scout never implements.
- Scouts write nothing (audit P4-CLOSURE-004 F-3). A scout has no Write or
  Edit tool; it returns the proposal text and the calling session saves it
  here after review. The tool list is enforced by the harness. The guard hook
  `.claude/hooks/atlas_proposal_write_guard.py` is still wired in the scout's
  frontmatter as defense in depth, but it was shown not to run in at least
  one environment, so nothing relies on it.
- A saved proposal is immutable: a revision is a new, separately named file.

Current scouts: `atlas-dashboard-scout` (dashboard/UI). It is the only one;
other domains are deferred until this one has been measured.
