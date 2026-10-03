"""Apprentice (owner 2026-10-03): learns the AI-001 advisors' (Claude Sonnet) work so that one day - and only with the
owner's approval - Atlas can do it without them. AI Model Research Team (org unit ``ai_model_research``).

What it can learn honestly, without a language model of its own:
* HOW the council votes on a proposal: a naive-Bayes verdict from the proposal's features (risk level, the red
  team's view, kind, number of claims);
* WHICH evidence the CEO brief rests on: a ranking of the records the CEO saw, from the author, type, title words
  and whether the record was new since the previous brief.
It cannot write Sonnet's prose. For every new Sonnet answer it first predicts from what it has learned so far,
then compares, records the agreement and only then learns from the answer, so its scores are out-of-sample.
Every Sonnet exchange is also kept in research/apprentice/teacher.jsonl (written by tools/ai_gateway.py): the
dataset a future local model would be judged on. The apprentice never calls a model itself.

A takeover is never automatic: when a score is high enough on enough cases the record says so, and the owner
decides through a proposal (capability is never authority).
"""

from __future__ import annotations

import json
import math
import re
from pathlib import Path
from typing import Any

from tools import atlas_org_cli as cli

UNIT = "ai_model_research"
TEACHER_FILE = "teacher.jsonl"
STATE_FILE = "state.json"
CEO_WINDOW = 25            # the CEO brief's own evidence window (tools/agent_cycle.ceo_brief)
READY_COUNCIL_N, READY_COUNCIL_LOW = 30, 0.80   # >= 30 verdicts and the 95 % Wilson lower bound >= 80 %
READY_CEO_BRIEFS, READY_CEO_OVERLAP = 20, 0.80  # >= 20 briefs and >= 80 % of the CEO's picks in its own top-k
_WORD = re.compile(r"[^\W\d_]{4,}", re.UNICODE)


def _body(record: dict[str, Any] | None) -> dict[str, Any]:
    try:
        body = json.loads((record or {}).get("body") or "{}")
    except ValueError:
        return {}
    return body if isinstance(body, dict) else {}


def _load_state(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        data = None
    if not isinstance(data, dict):
        data = {}
    raw_council, raw_ceo = data.get("council"), data.get("ceo")
    council: dict[str, Any] = raw_council if isinstance(raw_council, dict) else {}
    ceo: dict[str, Any] = raw_ceo if isinstance(raw_ceo, dict) else {}
    return {"council": {"prior": council.get("prior") or {}, "counts": council.get("counts") or {},
                        "values": council.get("values") or {}, "learned": council.get("learned") or [],
                        "history": council.get("history") or []},
            "ceo": {"cited": ceo.get("cited") or {}, "seen": ceo.get("seen") or {}, "learned": ceo.get("learned") or [],
                    "history": ceo.get("history") or []}}


def _save_state(path: Path, state: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(state, ensure_ascii=False), encoding="utf-8")
    tmp.replace(path)


# ---------------------------------------------------------------- council verdicts
def council_features(pid: str, prop: Any, earlier: list[dict[str, Any]]) -> dict[str, str]:
    fields = getattr(prop, "fields", None) or {}
    red = [r for r in earlier if r.get("author") == "red_team" and r.get("related_proposal") == pid]
    view = ("yok" if not red else "yetersiz" if "YETERSİZ" in str(red[-1].get("title", "")).upper() else "kabul")
    claims = fields.get("claims") or []
    return {"risk": str(fields.get("risk_level") or fields.get("risk") or "?").upper(), "red_team": view,
            "kind": pid.split("-")[0] if "-" in pid else "?",
            "claims": "0" if not claims else "1" if len(claims) == 1 else "2+"}


def council_predict(model: dict[str, Any], feats: dict[str, str]) -> str | None:
    prior = model["prior"]
    if not prior:
        return None
    total = sum(prior.values())
    best, best_score = None, -math.inf
    for outcome in sorted(prior):
        n = prior[outcome]
        score = math.log((n + 1) / (total + len(prior)))
        for f, v in feats.items():
            seen_values = max(1, len(model["values"].get(f, [])))
            score += math.log((model["counts"].get(outcome, {}).get(f"{f}={v}", 0) + 1) / (n + seen_values + 1))
        if score > best_score:
            best, best_score = outcome, score
    return best


def council_learn(model: dict[str, Any], feats: dict[str, str], outcome: str) -> None:
    model["prior"][outcome] = model["prior"].get(outcome, 0) + 1
    bucket = model["counts"].setdefault(outcome, {})
    for f, v in feats.items():
        bucket[f"{f}={v}"] = bucket.get(f"{f}={v}", 0) + 1
        values = model["values"].setdefault(f, [])
        if v not in values:
            values.append(v)


# ---------------------------------------------------------------- CEO evidence selection
def record_features(record: dict[str, Any], previous_brief_at: str) -> list[str]:
    feats = [f"author={record.get('author')}", f"type={record.get('type')}"]
    if previous_brief_at and str(record.get("created_at") or "") > previous_brief_at:
        feats.append("new")
    words = sorted({w.lower() for w in _WORD.findall(str(record.get("title") or ""))})[:12]
    return feats + [f"word={w}" for w in words]


def ceo_rank(model: dict[str, Any], candidates: list[dict[str, Any]], previous_brief_at: str) -> list[str]:
    def score(r: dict[str, Any]) -> float:
        total = 0.0
        for f in record_features(r, previous_brief_at):
            cited, seen = model["cited"].get(f, 0), model["seen"].get(f, 0)
            total += math.log((cited + 1) / (seen - cited + 1))
        return total
    # ties: newer first (what an untrained apprentice would guess)
    ranked = sorted(enumerate(candidates), key=lambda ir: (score(ir[1]), ir[0]), reverse=True)
    return [str(r.get("id")) for _, r in ranked]


def ceo_learn(model: dict[str, Any], candidates: list[dict[str, Any]], cited: set[str], previous_brief_at: str) -> None:
    for r in candidates:
        hit = str(r.get("id")) in cited
        for f in record_features(r, previous_brief_at):
            model["seen"][f] = model["seen"].get(f, 0) + 1
            if hit:
                model["cited"][f] = model["cited"].get(f, 0) + 1


def _evidence(record: dict[str, Any]) -> bool:
    from tools.agent_cycle import CEO_IGNORED_AUTHORS, CEO_IGNORED_PREFIXES

    return record.get("author") not in CEO_IGNORED_AUTHORS and not str(record.get("id", "")).startswith(CEO_IGNORED_PREFIXES)


# ---------------------------------------------------------------- the run
def _wilson_low(hits: int, n: int) -> float | None:
    from tools.reality_check import wilson

    return wilson(hits, n)[0] if n else None


def scorecard(state: dict[str, Any], teacher_examples: int) -> dict[str, Any]:
    ch = state["council"]["history"]
    hits = sum(1 for h in ch if h.get("hit"))
    low = _wilson_low(hits, len(ch))
    eh = state["ceo"]["history"]
    overlaps = [float(h.get("overlap") or 0) for h in eh]
    recent = overlaps[-READY_CEO_BRIEFS:]
    council_ready = len(ch) >= READY_COUNCIL_N and low is not None and low >= READY_COUNCIL_LOW
    ceo_ready = len(eh) >= READY_CEO_BRIEFS and recent and sum(recent) / len(recent) >= READY_CEO_OVERLAP
    signals = sorted(((f, state["ceo"]["cited"].get(f, 0) / s, s) for f, s in state["ceo"]["seen"].items() if s >= 3),
                     key=lambda x: (-x[1], -x[2]))[:5]
    return {"council": {"verdicts_seen": len(ch), "agreed": hits, "agreement_95ci_low": None if low is None else round(low, 3),
                        "last_20": [h.get("hit") for h in ch[-20:]].count(True) if ch else 0,
                        "ready": bool(council_ready)},
            "ceo": {"briefs_seen": len(eh), "mean_overlap": round(sum(overlaps) / len(overlaps), 3) if overlaps else None,
                    "mean_overlap_last_20": round(sum(recent) / len(recent), 3) if recent else None,
                    "ready": bool(ceo_ready)},
            "teacher_examples": teacher_examples,
            "what_the_ceo_values": [{"feature": f, "cited_rate": round(rate, 2), "seen": s} for f, rate, s in signals],
            "rule": (f"takeover only with the owner's approval; council: >= {READY_COUNCIL_N} verdicts and 95 % lower "
                     f"bound >= {READY_COUNCIL_LOW:.0%}; CEO selection: >= {READY_CEO_BRIEFS} briefs with mean overlap "
                     f">= {READY_CEO_OVERLAP:.0%}")}


def _teacher_examples(research_dir: Path) -> int:
    path = research_dir / "apprentice" / TEACHER_FILE
    try:
        with path.open("rb") as f:
            return sum(1 for _ in f)
    except OSError:
        return 0


def run(records_dir: Path, research_dir: Path, *, proposals: dict[str, Any] | None = None) -> dict[str, Any]:
    from atlas_org import memory_records

    log = records_dir / cli.MEMORY_LOG
    memory = sorted(memory_records.replay(cli.read_log(log)).values(), key=lambda r: r["seq"]) if log.exists() else []
    if proposals is None:
        from atlas_org import proposals as P

        plog = records_dir / cli.PROPOSALS_LOG
        proposals = P.replay(cli.read_log(plog)) if plog.exists() else {}
    state_path = research_dir / "apprentice" / STATE_FILE
    state = _load_state(state_path)
    council, ceo = state["council"], state["ceo"]
    learned_council, learned_ceo = set(council["learned"]), set(ceo["learned"])
    new_council = new_ceo = 0
    for i, rec in enumerate(memory):
        rid = str(rec.get("id"))
        if rec.get("author") == "model_council" and rid not in learned_council:
            outcome = str(_body(rec).get("outcome") or "")
            pid = str(rec.get("related_proposal") or "")
            if outcome and pid:
                feats = council_features(pid, proposals.get(pid), memory[:i])
                guess = council_predict(council, feats)       # first predict ...
                council["history"].append({"id": rid, "proposal": pid, "guess": guess, "actual": outcome,
                                           "hit": guess == outcome})
                council_learn(council, feats, outcome)         # ... then learn
                new_council += 1
            council["learned"].append(rid)
            learned_council.add(rid)
        elif rec.get("author") == "ceo_ai" and rid not in learned_ceo:
            cited = {c for c in _body(rec).get("cited_records", []) if isinstance(c, str)}
            before = memory[:i]
            previous = next((r for r in reversed(before) if r.get("author") == "ceo_ai"), None)
            previous_at = str(previous.get("created_at") or "") if previous else ""
            candidates = [r for r in before if _evidence(r)][-CEO_WINDOW:]
            k = len(cited & {str(r.get("id")) for r in candidates})
            if k:
                picked = set(ceo_rank(ceo, candidates, previous_at)[:k])    # first predict ...
                ceo["history"].append({"id": rid, "k": k, "overlap": round(len(picked & cited) / k, 3)})
                ceo_learn(ceo, candidates, cited, previous_at)              # ... then learn
                new_ceo += 1
            ceo["learned"].append(rid)
            learned_ceo.add(rid)
    if not (new_council or new_ceo):
        _save_state(state_path, state)
        return {"verdict": "OK", "summary": "Sonnet'ten öğrenilecek yeni cevap yok"}
    card = scorecard(state, _teacher_examples(research_dir))
    _save_state(state_path, state)
    c, e = card["council"], card["ceo"]
    readiness = ("DEVRALMAYA ADAY (sahibin onayı gerekir)" if c["ready"] or e["ready"] else "HAZIR DEĞİL")
    overlap = "—" if e["mean_overlap"] is None else f"%{e['mean_overlap'] * 100:.0f}"
    title = (f"Çırak: konsey uyumu {c['agreed']}/{c['verdicts_seen']}, CEO kanıt seçimi ortalama {overlap} "
             f"({e['briefs_seen']} özet) — {readiness}")
    existing = {r["record_id"] for r in cli.read_log(log)} if log.exists() else set()
    cli.add_memory_record(records_dir, {
        "record_id": f"AP-{len(existing) + 1:04d}", "type": "AGENTS", "authority": "RESEARCH", "title": title,
        "body": json.dumps({**card, "learned_now": {"council": new_council, "ceo": new_ceo}}, ensure_ascii=False),
        "author": UNIT, "source": "tools/apprentice.py (learns from AI-001 answers; never calls a model)"})
    return {"verdict": "OK", "summary": title}
