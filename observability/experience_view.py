"""Read-only summary of the experience agent for /research (owner 2026-10-02).

Reads only <state>/research/experience/state.json, which tools/experience_agent.py
writes after every replayed day (days, decisions, walk-forward candidate lessons).
Candidates are research evidence, never rules: they change behaviour only
through an owner-approved proposal. Missing or unreadable state is reported as
unavailable, never filled in.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


def state_path_for(state_directory: Any) -> Path | None:
    """<state>/research/experience/state.json for the running runtime's state directory, else None."""
    return Path(state_directory) / "research" / "experience" / "state.json" if state_directory else None


def _day(ms: Any) -> str | None:
    return datetime.fromtimestamp(ms / 1000, UTC).date().isoformat() if isinstance(ms, int) else None


def read_experience(state_path: Path | None) -> dict[str, Any]:
    if state_path is None:
        return {"available": False, "reason": "çalışma zamanı bağlı değil"}
    path = Path(state_path)
    try:
        state = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {"available": False, "reason": "deneyim ajanı henüz çalışmadı"}
    except (OSError, ValueError) as exc:
        return {"available": False, "reason": f"state.json okunamadı ({type(exc).__name__})"}
    if not isinstance(state, dict):
        return {"available": False, "reason": "state.json biçimi geçersiz"}
    lessons = state.get("candidate_lessons")
    return {
        "available": True,
        "days": state.get("days"),
        "decisions": state.get("decisions"),
        "oldest_day": _day(state.get("oldest_day_ms")),
        "newest_day": _day(state.get("newest_day_ms")),
        "updated_at": state.get("updated_at"),
        "candidate_lessons": lessons if isinstance(lessons, list) else None,
    }
