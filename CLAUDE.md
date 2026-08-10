# Project Atlas — Claude Code Contract

## Identity
Atlas is an evidence-driven investment research and execution system.
AI is a tool used by Atlas; it is not the definition of the system.

## Source of Truth
- Existing repository contracts and governance override assumptions.
- Never invent requirements, milestones, acceptance criteria, or evidence.
- Mark anything not demonstrated by evidence as UNVERIFIED.

## Safety
- PAPER-only unless the user explicitly authorizes otherwise.
- LIVE / real-money trading authority is DENIED by default.
- Never expose or introduce secrets, credentials, PII, or sensitive financial data.
- Never weaken security, validation, governance, risk controls, or tests.

## Engineering
- Make the smallest production-quality change that satisfies the current work item.
- No unrelated refactors.
- No unnecessary dependencies, frameworks, abstractions, or files.
- Preserve existing interfaces and contracts unless the task explicitly requires a change.
- Do not delete, bypass, weaken, or rewrite tests merely to make them pass.

## Context Discipline
- Do not scan the whole repository by default.
- Inspect only files directly relevant to the current task.
- Prefer targeted search over broad recursive reads.
- Do not read generated, cache, vendor, environment, build, or large-output directories unless required.
- Do not dump large files, diffs, logs, or test output into chat.
- Reuse already verified facts from the current session instead of rediscovering them.

## Workflow
Inspect narrowly -> implement minimally -> run targeted validation -> report evidence.

## Validation
- Run the narrowest relevant tests/checks first.
- Broader validation requires a reason based on change impact.
- Never claim PASS unless the supporting command actually ran successfully.

## Reporting
Keep final responses compact:
1. Changed files
2. Validation executed + result
3. Remaining blocker/risk
4. Next single recommended step
