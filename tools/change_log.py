"""Change notes (owner 2026-10-03): what changed in Atlas, what was fixed, and how Atlas looks since.

Deployment Manager (org unit ``deployment_manager``), observation only: autonomous deployment stays DENIED.
Reads the local git history read-only (``git log``) and writes one DM record per batch of new commits with the
areas touched, the fixes, and the state Atlas was in at that moment next to the state of the previous note, so a
later review can tie a change to what followed it. Writes nothing when no commit is new.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any

from tools import atlas_org_cli as cli

UNIT = "deployment_manager"
ROOT = Path(__file__).resolve().parents[1]
FIRST_RUN_COMMITS = 20  # the first note covers the latest commits, not the whole history
MAX_COMMITS = 200
GIT_TIMEOUT_S = 30
AREAS = (("core/", "çekirdek (karar / risk / işlem)"), ("tools/", "ajanlar ve araçlar"), ("observability/", "panel verisi"),
         ("templates/", "panel"), ("web_app.py", "panel"), ("tests/", "testler"), ("docs/", "dokümanlar"),
         ("governance/", "yönetişim"), ("config/", "ayarlar"), ("checkpoints/", "kontrol noktaları"),
         ("packaging/", "mimari haritalar"), ("static/", "panel"))
FIX_PREFIXES = ("fix", "hotfix", "düzelt", "bugfix")  # a commit is a fix when its subject says so first


def _git(root: Path, *args: str) -> str:
    out = subprocess.run(["git", "-C", str(root), *args], capture_output=True, text=True, encoding="utf-8",
                         timeout=GIT_TIMEOUT_S)
    if out.returncode != 0:
        raise RuntimeError((out.stderr or out.stdout or "").strip()[:200] or f"git exit {out.returncode}")
    return out.stdout


def commits_since(root: Path, since: str | None) -> tuple[list[dict[str, Any]], str]:
    """New commits, oldest first, and how they were found: 'since', 'first' or 'history-changed'."""
    how = "first"
    rng = ["-n", str(FIRST_RUN_COMMITS)]
    if since:
        try:
            _git(root, "merge-base", "--is-ancestor", since, "HEAD")
            rng, how = [f"{since}..HEAD", "-n", str(MAX_COMMITS)], "since"
        except RuntimeError:  # the last noted commit is gone (history rewritten): start again from the latest
            how = "history-changed"
    raw = _git(root, "log", "--no-merges", "--date=iso-strict", "--name-only",
               "--pretty=format:%x1e%H%x1f%cI%x1f%s", *rng)
    commits = []
    for chunk in raw.split("\x1e"):
        if not chunk.strip():
            continue
        head, _, files = chunk.partition("\n")
        sha, at, subject = (head.split("\x1f") + ["", ""])[:3]
        commits.append({"sha": sha.strip(), "at": at.strip(), "subject": subject.strip(),
                        "files": [f.strip() for f in files.splitlines() if f.strip()]})
    return list(reversed(commits)), how


def _area(path: str) -> str:
    return next((label for prefix, label in AREAS if path.startswith(prefix)), "diğer")


def state_now(memory: list[dict[str, Any]]) -> dict[str, Any]:
    """How Atlas looks at this moment, from recorded evidence only."""
    def body(r: dict[str, Any] | None) -> dict[str, Any]:
        try:
            return json.loads((r or {}).get("body") or "{}")
        except ValueError:
            return {}
    perf = next((r for r in reversed(memory) if r.get("author") == "quant_research"), None)
    total = body(perf).get("total") if perf else None
    open_incidents = sum(1 for r in memory if r.get("type") == "INCIDENTS" and not r.get("superseded_by")
                         and (r.get("incident") or {}).get("status") != "RESOLVED")
    return {"performance_report": perf.get("id") if perf else None,
            "trades": (total or {}).get("trades"), "net_pnl_estimate": (total or {}).get("est_net_pnl"),
            "win_rate_after_fees": (total or {}).get("win_rate_after_fees"), "verdict": (total or {}).get("verdict"),
            "open_incidents": open_incidents}


def _delta(before: dict[str, Any], now: dict[str, Any]) -> dict[str, Any]:
    from decimal import Decimal, InvalidOperation

    out: dict[str, Any] = {}
    if isinstance(before.get("trades"), int) and isinstance(now.get("trades"), int):
        out["new_trades"] = now["trades"] - before["trades"]
    try:
        out["net_change"] = str(Decimal(str(now["net_pnl_estimate"])) - Decimal(str(before["net_pnl_estimate"])))
    except (InvalidOperation, KeyError, TypeError, ValueError):
        pass
    if before.get("verdict") != now.get("verdict"):
        out["verdict"] = f"{before.get('verdict')} -> {now.get('verdict')}"
    if before.get("open_incidents") != now.get("open_incidents"):
        out["open_incidents"] = f"{before.get('open_incidents')} -> {now.get('open_incidents')}"
    return out


def run(records_dir: Path, root: Path = ROOT) -> dict[str, Any]:
    from atlas_org import memory_records

    log = records_dir / cli.MEMORY_LOG
    memory = sorted(memory_records.replay(cli.read_log(log)).values(), key=lambda r: r["seq"]) if log.exists() else []
    notes = [r for r in memory if r.get("author") == UNIT]
    last = notes[-1] if notes else None
    try:
        last_body = json.loads(last.get("body") or "{}") if last else {}
    except ValueError:
        last_body = {}
    try:
        commits, how = commits_since(root, last_body.get("head"))
    except (OSError, RuntimeError, subprocess.SubprocessError) as exc:
        return {"verdict": "WARN", "summary": f"git geçmişi okunamadı ({type(exc).__name__}: {str(exc)[:120]}); not yazılmadı"}
    if not commits:
        return {"verdict": "OK", "summary": "yeni değişiklik yok"}
    areas: dict[str, int] = {}
    for c in commits:
        for label in {_area(f) for f in c["files"]} or {"diğer"}:
            areas[label] = areas.get(label, 0) + 1
    fixes = [c["subject"][:160] for c in commits if c["subject"].lower().startswith(FIX_PREFIXES)]
    now = state_now(memory)
    body = {"head": commits[-1]["sha"], "found": how, "commits": [{k: c[k] for k in ("sha", "at", "subject")} for c in commits],
            "areas": dict(sorted(areas.items(), key=lambda x: -x[1])), "fixes": fixes, "state_now": now,
            "since_previous_note": _delta(last_body.get("state_now") or {}, now) if last else None,
            "previous_note": last.get("id") if last else None}
    existing = {r["record_id"] for r in cli.read_log(log)} if log.exists() else set()
    rid = f"DM-{len(existing) + 1:04d}"
    top = ", ".join(f"{k} {v}" for k, v in list(body["areas"].items())[:3])
    cli.add_memory_record(records_dir, {
        "record_id": rid, "type": "DEVELOPMENT", "authority": "RESEARCH",
        "title": f"Değişiklik notu: {len(commits)} değişiklik ({top}), {len(fixes)} düzeltme",
        "body": json.dumps(body, ensure_ascii=False), "author": UNIT, "source": "tools/change_log.py (git log, read-only)"})
    return {"verdict": "OK", "summary": f"{rid}: {len(commits)} değişiklik, {len(fixes)} düzeltme"
                                        + (" (geçmiş yeniden yazılmış; son değişikliklerden başlandı)" if how == "history-changed" else "")}
