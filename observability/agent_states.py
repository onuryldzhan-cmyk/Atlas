"""Live state of every Atlas agent, derived only from recorded evidence (Atlas HQ backbone).

The 3D HQ and the 2D panels draw this; they never invent motion. Every
state carries the record it came from. Sources (all read-only):

* task log       - a step's status for the unit it is assigned to
* proposal log   - who authored, who reviewed, what waits for the owner
* memory log     - the last agent-cycle record (what each rule-based agent did)
* signals        - the five voting agents' last votes from the running market loop

States: IDLE, WORKING, WAITING (assigned, no executor yet), BLOCKED, ERROR,
REVIEWING, WAITING_FOR_HUMAN, OFFLINE (no evidence at all). Flows are real
hand-offs: consecutive steps of one task, proposal author -> reviewer ->
owner, and the agent cycle order.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

ROOMS = {
    "command": "Komuta merkezi", "research": "Araştırma laboratuvarı", "quant": "Trading katı",
    "dev": "Geliştirme laboratuvarı", "review": "İnceleme merkezi", "security": "Güvenlik merkezi",
    "memory": "Hafıza merkezi", "governance": "Onay merkezi", "system": "Altyapı",
}

AGENTS: dict[str, tuple[str, str]] = {  # unit id -> (display name, room)
    "owner": ("Onur (sahip)", "governance"),
    "atlas_manager": ("Atlas Manager", "command"),
    "executive_assistant": ("Assistant Manager", "command"),
    "open_source_research": ("Araştırma ajanı", "research"),
    "quant_research": ("Kantitatif araştırma", "quant"),
    "strategy_lab": ("Strateji laboratuvarı", "quant"),
    "strategy_research": ("Strateji karşılaştırma", "research"),
    "task_runner": ("Görev yürütücü", "command"),
    "market_regime": ("Piyasa rejimi", "research"),
    "code_engineering": ("Kod ajanı", "dev"),
    "code_review": ("Kod inceleme", "review"),
    "red_team": ("Karşı görüş", "review"),
    "security": ("Güvenlik muhafızı", "security"),
    "data_quality": ("Veri kalitesi", "system"),
    "knowledge_manager": ("Hafıza yöneticisi", "memory"),
    "model_validation": ("Model doğrulama", "review"),
    "experiment_manager": ("Deneyim ajanı", "research"),
    "digital_twin": ("Shadow maliyet ölçümü", "research"),
    "ceo_ai": ("CEO AI (AI-001)", "command"),
    "model_council": ("Model konseyi (AI-001)", "review"),
    "overview_snapshot": ("Durum özeti", "system"),
    "agent_technical": ("Teknik analiz", "quant"),
    "agent_macro": ("Makro", "quant"),
    "agent_sentiment": ("Duygu (Fear & Greed)", "quant"),
    "agent_risk": ("Risk (volatilite)", "quant"),
    "agent_momentum": ("Momentum", "quant"),
}
VOTERS = {"technical": "agent_technical", "macro": "agent_macro", "sentiment": "agent_sentiment",
          "risk": "agent_risk", "momentum": "agent_momentum"}
RECENT_CYCLE_S = 2 * 3600


def _age_s(iso: str | None, now: datetime) -> float | None:
    try:
        t = datetime.fromisoformat(str(iso).replace("Z", "+00:00"))
    except ValueError:
        return None
    return (now - (t if t.tzinfo else t.replace(tzinfo=timezone.utc))).total_seconds()


def build(tasks: dict, proposals: dict, memory: dict, signals: dict | None,
          now: datetime | None = None) -> dict[str, Any]:
    now = now or datetime.now(timezone.utc)
    agents = {uid: {"id": uid, "name": n, "room": r, "room_name": ROOMS[r], "state": "OFFLINE",
                    "doing": "kayıtta iz yok", "source": None} for uid, (n, r) in AGENTS.items()}
    flows: list[dict[str, Any]] = []

    def set_state(uid: str, state: str, doing: str, source: str, rank: dict[str, int] = {
            "OFFLINE": 0, "IDLE": 1, "WAITING": 2, "REVIEWING": 3, "WORKING": 4, "WAITING_FOR_HUMAN": 4,
            "BLOCKED": 5, "ERROR": 6}) -> None:
        a = agents.get(uid)
        if a is None:
            return
        if rank[state] >= rank[a["state"]]:
            a.update(state=state, doing=doing, source=source)

    # memory: last agent cycle
    records = memory.get("records", []) if memory.get("available") else []
    cycles = sorted((r for r in records if r.get("type") == "OPERATIONS" and str(r.get("id", "")).startswith("AC-")),
                    key=lambda r: r.get("seq", 0))
    if cycles:
        last = cycles[-1]
        age = _age_s(last.get("created_at"), now)
        try:
            results = json.loads(last.get("body", "{}")).get("agent_cycle", [])
        except ValueError:
            results = []
        order = [r.get("unit") for r in results]
        for r in results:
            if r.get("verdict") == "FAIL":
                set_state(r.get("unit"), "ERROR", r.get("summary", ""), last["id"])
            elif age is not None and age <= RECENT_CYCLE_S:
                set_state(r.get("unit"), "IDLE", "son döngüde: " + str(r.get("summary", "")), last["id"])
        flows += [{"from": a, "to": b, "kind": "agent_cycle", "label": last["id"]} for a, b in zip(order, order[1:])]

    # tasks: assigned steps wait for an executor
    for t in tasks.get("tasks", []) if tasks.get("available") else []:
        if t.get("status") == "DONE":
            continue
        units = []
        for s in t.get("steps", []):
            uid, st = s.get("unit"), s.get("status")
            units.append(uid)
            if st == "WORKING":
                set_state(uid, "WORKING", f"{t['id']}: {s.get('goal')}", t["id"])
            elif st in ("BLOCKED", "FAILED"):
                set_state(uid, "BLOCKED", f"{t['id']}: {s.get('goal')} ({st})", t["id"])
            elif st in ("ASSIGNED", "PENDING"):
                set_state(uid, "WAITING", f"{t['id']}: {s.get('goal')} — çalıştırıcı bekliyor", t["id"])
        flows += [{"from": a, "to": b, "kind": "task", "label": t["id"]}
                  for a, b in zip(units, units[1:]) if a and b and a != b]

    # proposals: review and the owner's decision
    awaiting, open_ids = [], []
    for p in proposals.get("proposals", []) if proposals.get("available") else []:
        if p.get("status") in ("APPLIED", "REJECTED", "ROLLED_BACK", "SUPERSEDED"):
            continue
        open_ids.append(p["id"])
        if p.get("status") == "READY_FOR_OWNER":  # only what is really waiting on the owner's signature
            awaiting.append(p["id"])
        flows.append({"from": p.get("author"), "to": "owner", "kind": "proposal", "label": p["id"]})
        for rv in p.get("reviews", []):
            flows.append({"from": p.get("author"), "to": rv.get("reviewer"), "kind": "review", "label": p["id"]})
    for r in records:
        if r.get("author") == "red_team" and r.get("related_proposal") in open_ids:
            set_state("red_team", "REVIEWING", r.get("title", ""), r["id"])
    if awaiting:
        set_state("owner", "WAITING_FOR_HUMAN", f"{len(awaiting)} öneri kararınızı bekliyor: {', '.join(awaiting[:3])}",
                  "proposals")
    elif proposals.get("available"):
        set_state("owner", "IDLE", f"onayınıza sunulmuş öneri yok ({len(open_ids)} öneri hazırlık aşamasında)" if open_ids
                  else "bekleyen öneri yok", "proposals")

    # voting agents: the running market loop
    sig = (signals or {}).get("signals") if (signals or {}).get("status") == "SUCCESS" else None
    if sig:
        for name, uid in VOTERS.items():
            votes = [s.get("agents", {}).get(name, {}) for s in sig.values()]
            evaluated = sum(1 for v in votes if v.get("status") == "EVALUATED")
            set_state(uid, "WORKING" if evaluated else "IDLE",
                      f"{evaluated}/{len(votes)} coin için oy verdi" if evaluated else "bu döngüde oy yok (çekimser/hariç)",
                      "/api/signals")
            flows.append({"from": uid, "to": "atlas_manager", "kind": "vote", "label": f"{evaluated} oy"})
        set_state("atlas_manager", "WORKING", f"{len(sig)} coinde oyları birleştirip risk zincirine gönderiyor", "/api/signals")

    flows = [f for f in flows if f["from"] in agents and f["to"] in agents]
    activity = _activity(records, proposals)
    for a in agents.values():
        a["history"] = [e for e in activity if e["agent"] == a["id"]][:10]
    counts: dict[str, int] = {}
    for a in agents.values():
        counts[a["state"]] = counts.get(a["state"], 0) + 1
    return {"available": True, "generated_at": now.isoformat(), "rooms": ROOMS,
            "agents": list(agents.values()), "flows": flows, "counts": counts, "activity": activity[:40]}


def _category(record: dict[str, Any]) -> str:
    """Runtime, governance and security events are kept apart (owner spec §44)."""
    if record.get("author") == "security" or record.get("type") == "INCIDENTS":
        return "SECURITY"
    if record.get("type") in ("REVIEWS", "DECISIONS") or record.get("related_proposal"):
        return "GOVERNANCE"
    return "RUNTIME"


def _activity(records: list[dict[str, Any]], proposals: dict) -> list[dict[str, Any]]:
    """Real recorded events only, newest first. An empty log gives an empty feed, never filler."""
    events = [{"at": r.get("created_at"), "agent": r.get("author"), "category": _category(r),
               "text": r.get("title", ""), "source": r.get("id")} for r in records]
    for p in proposals.get("proposals", []) if proposals.get("available") else []:
        events.append({"at": p.get("created_at") or p.get("updated_at"), "agent": p.get("author"),
                       "category": "GOVERNANCE", "text": f"{p.get('id')}: {p.get('title', '')} ({p.get('status')})",
                       "source": p.get("id")})
    return sorted((e for e in events if e["at"]), key=lambda e: str(e["at"]), reverse=True)
