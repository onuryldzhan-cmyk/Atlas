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
- Scouts can write here and nowhere else. This is enforced by
  `.claude/hooks/atlas_proposal_write_guard.py`, wired in each scout's agent
  frontmatter. Scouts cannot write this README or into subdirectories.

Current scouts: `atlas-dashboard-scout` (dashboard/UI). It is the only one;
other domains are deferred until this one has been measured.
