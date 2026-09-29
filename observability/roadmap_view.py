"""Read-only roadmap view: the canonical Phase 0-10 table plus recorded evidence.

The phases, names and scopes are parsed from the canonical record
governance/ATLAS_ROADMAP_PHASE_0_10_ENUMERATION_v1.0.md (never copied here).
EVIDENCE lists what the governance registries record as delivered, by
registry version; it is evidence, NOT a completion claim - no phase is
marked complete by this view (CLAUDE.md: never claim done without the full
gate). Live stays DENIED whatever the table says.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
ROADMAP_RELPATH = "governance/ATLAS_ROADMAP_PHASE_0_10_ENUMERATION_v1.0.md"
_ROW = re.compile(r"^\|\s*\*\*(\d+)\*\*\s*\|\s*([^|]+?)\s*\|\s*(.+?)\s*\|\s*$")

EVIDENCE: dict[int, list[str]] = {
    2: ["v5.40 live PAPER portfolio valued at real prices (/api/portfolio)",
        "v5.41/v5.51 trade universe = coins with real Binance rules, 8/8/4 selection from Binance data",
        "v5.47/v5.53/v5.54 replay realism (slippage, next-candle fill) and strategy research flags, walk-forward comparison",
        "v5.45 data health check of the durable book (read from a copy)"],
    3: ["v5.37 Command Center brief and status", "v5.44 System health page (unknown is never healthy)"],
    4: ["v5.42 self-review files improvement tasks from real evidence",
        "v5.47 performance report: what Atlas learns from its real trades", "v5.52 strategy research document"],
    5: ["v5.34 capability permission model (financial_execute/deploy never grantable to AI)",
        "v5.36 Security Guardian bound to proposal reviews", "v5.39 independent audit fixes, owner HMAC signatures",
        "v5.55 Security page over the running code"],
    6: ["v5.34 proposal lifecycle, only the owner approves", "v5.35 deterministic Atlas Manager and task routing",
        "v5.50 agent scorecards"],
    7: ["v5.34 Atlas Memory with provenance and authority levels", "v5.43 Decisions & Memory page"],
    8: ["v5.38 Atlas HQ (dependency-free 3D core)", "v5.40 simple start page and Trading page",
        "v5.48 Atlas Chat over the live portfolio", "v5.49 professional operator theme"],
    9: ["v5.42 observe-and-propose self-review only (autonomous deployment DENIED)"],
    10: [],
}


def read_roadmap(repository_root: Path | None = None) -> dict[str, Any]:
    root = REPOSITORY_ROOT if repository_root is None else Path(repository_root)
    try:
        text = (root / ROADMAP_RELPATH).read_text(encoding="utf-8")
    except OSError as exc:
        return {"available": False, "reason": f"{ROADMAP_RELPATH}: {type(exc).__name__}"}
    phases = []
    for line in text.splitlines():
        m = _ROW.match(line)
        if m:
            number = int(m.group(1))
            evidence = EVIDENCE.get(number, [])
            phases.append({"phase": number, "name": m.group(2).strip(), "scope": m.group(3).strip(),
                           "evidence": evidence,
                           "status": "LOCKED (live DENIED)" if number == 10 else
                                     ("EVIDENCE RECORDED - not a completion claim" if evidence else "NO EVIDENCE RECORDED HERE")})
    if len(phases) != 11:
        return {"available": False, "reason": f"expected 11 phases in {ROADMAP_RELPATH}, found {len(phases)}"}
    focus = re.search(r"\*\*Current focus, in the owner's words \(§96\):\*\* \"([^\"]+)\"", text)
    return {"available": True, "source": ROADMAP_RELPATH, "current_focus": focus.group(1) if focus else None,
            "ladder": "Paper → Shadow → Small Live → Controlled Autonomous → Advanced Autonomous",
            "phases": phases}
