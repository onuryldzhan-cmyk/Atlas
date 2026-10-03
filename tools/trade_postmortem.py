"""Trade post-mortems (owner 2026-10-03): every closed PAPER trade, win or loss, is written to memory with why it
won or lost and what to watch next time, so later work builds on it instead of starting over.

Explainable AI Center (org unit ``explainable_ai``). Evidence only: nothing here changes a decision, a gate or a
threshold, and every suggestion is advice for the owner.

* Facts: observability.learning_view.experiences (net after the 0.1 %/side fee estimate, the coin's regime when
  the trade opened - from market_regime records, never one written later - fee impact, direction) joined with
  the entry approval's confidence and risk (tools.paper_position_report.entry_approval).
* One TP record per trade (TRADING / RESEARCH): outcome, why, what to watch next time, and how the same
  regime + confidence band did before this trade (no look-ahead). At most MAX_PER_RUN per run, so a first
  run back-fills the history over a few runs.
* When enough new post-mortems have gathered, the AI-001 advisor (Claude Sonnet via tools/ai_gateway.py)
  reviews them with the performance totals, the latest change notes and its own previous review, and writes
  patterns, follow-ups on its earlier suggestions and at most three realistic, testable suggestions (TR record).
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any, Callable

from tools import atlas_org_cli as cli

UNIT = "explainable_ai"
MAX_PER_RUN = 50
REVIEW_EVERY = 5          # new post-mortems before an AI review ...
REVIEW_MIN_GAP_H = 3.0    # ... at least this long after the previous review (5 trades is already a small sample)
REVIEW_MAX_GAP_H = 24.0   # or a day after it, with at least one new post-mortem
REVIEW_WINDOW = 30        # post-mortems shown to the reviewer
_OUTCOME_TR = {"WIN": "KAZANÇ", "LOSS_FEES": "KAYIP (ücret)", "LOSS_PRICE": "KAYIP (fiyat)"}

_REVIEW_SCHEMA = {
    "type": "object", "additionalProperties": False,
    "required": ["patterns", "followups", "suggestions", "cited_records"],
    "properties": {
        "patterns": {"type": "array", "items": {"type": "string"}},
        "followups": {"type": "array", "items": {"type": "string"}},
        "suggestions": {"type": "array", "items": {
            "type": "object", "additionalProperties": False, "required": ["change", "why", "test", "risk"],
            "properties": {"change": {"type": "string"}, "why": {"type": "string"},
                           "test": {"type": "string"}, "risk": {"type": "string"}}}},
        "cited_records": {"type": "array", "items": {"type": "string"}}}}
_REVIEW_SYSTEM = ("You review Atlas's PAPER trades. You have no authority: you cannot trade, deploy, approve or change "
                  "any threshold. Use only the records given and cite their ids. If the evidence is insufficient, say "
                  "so. Never invent numbers.")
_REVIEW_TASK = (
    "Task - build on your previous review, do not repeat it:\n"
    "1) patterns: up to 3 patterns across these trades (why we lose, why we win), each citing post-mortem ids.\n"
    "2) followups: for each suggestion of your previous review, one line saying whether the new trades supported "
    "it, refuted it, or have not tested it yet.\n"
    "3) suggestions: at most 3 realistic improvements for the owner. For each: change (what exactly), why (the "
    "evidence), test (how to test it first in PAPER or replay, with a measurable pass criterion, before any gate "
    "changes) and risk (what could go wrong). Prefer a sharper or new step over an earlier suggestion repeated.\n"
    "Turkish. Cite every record you rely on in cited_records. If the trades show nothing new, return empty lists.")


def band(confidence: Any) -> str:
    from tools.reality_check import BANDS

    if not isinstance(confidence, (int, float)):
        return "bilinmiyor"
    for lo, hi in BANDS:
        if lo <= confidence < hi:
            return f"{lo}-{min(hi, 100)}"
    return "bilinmiyor"


def facts(closed: list[dict[str, Any]], memory: list[dict[str, Any]], approvals: dict[str, list[dict]]) -> list[dict[str, Any]]:
    """Every closed trade as an experience, oldest first, with its entry confidence, risk and band."""
    from observability.learning_view import experiences
    from tools.paper_position_report import entry_approval

    out = []
    for exp in experiences(closed, memory):
        appr = entry_approval(approvals.get(str(exp.get("symbol")), []), exp.get("opened_at")) or {}
        conf = appr.get("confidence")
        out.append({**exp, "confidence": conf if isinstance(conf, (int, float)) else None, "band": band(conf),
                    "risk": appr.get("risk"), "experiment_id": appr.get("experiment_id")})
    return out


def explain(exp: dict[str, Any], earlier: list[dict[str, Any]]) -> dict[str, Any]:
    """Why this trade won or lost, what to watch next time, and how its regime + band did before it."""
    a = exp.get("analysis") or {}
    gross, net = Decimal(str(exp["gross_pnl"])), Decimal(str(exp["net_pnl"]))
    ret, regime, conf_band = a.get("gross_return_pct"), exp.get("regime") or "UNKNOWN", exp.get("band") or "bilinmiyor"
    if net > 0:
        kind = "WIN"
        reason = f"yön doğruydu: brüt {gross} (%{ret}), ücretlerden sonra net +{net}"
        nxt = f"{regime} rejimi + {conf_band} güven bandındaki benzer girişleri izle; tek işlem kanıt değildir"
    elif a.get("fees_turned_win_into_loss"):
        kind = "LOSS_FEES"
        reason = f"yön doğruydu (brüt +{gross}, %{ret}) ama gidiş-dönüş ücret (~%0,2) kârı sildi: net {net}"
        nxt = "beklenen hareket gidiş-dönüş ücretin (~%0,2) açıkça üzerinde değilse bu girişi yapmamayı değerlendir"
    else:
        kind = "LOSS_PRICE"
        reason = f"fiyat girişten sonra ters yöne gitti: brüt {gross} (%{ret}), net {net}"
        nxt = f"{regime} rejimi + {conf_band} güven bandında yön tutmadı; bu kombinasyonun geçmişine bak"
    held = a.get("holding_minutes")
    if isinstance(held, (int, float)) and held < 15:
        reason += f"; pozisyon yalnız {held} dk tutuldu"
    same = [e for e in earlier if (e.get("regime") or "UNKNOWN") == regime and (e.get("band") or "bilinmiyor") == conf_band]
    wins = sum(1 for e in same if Decimal(str(e["net_pnl"])) > 0)
    total = sum((Decimal(str(e["net_pnl"])) for e in same), Decimal("0"))
    pattern = ("bu kombinasyonda ilk işlem" if not same else
               f"aynı rejim + bantta önceki {len(same)} işlemin {wins}'i kazandı (net toplam {total})")
    return {"kind": kind, "reason": reason, "next_time": nxt, "pattern_so_far": pattern,
            "earlier_same": {"trades": len(same), "wins": wins, "net_total": str(total)}}


def _memory(records_dir: Path) -> list[dict[str, Any]]:
    from atlas_org import memory_records

    log = records_dir / cli.MEMORY_LOG
    return sorted(memory_records.replay(cli.read_log(log)).values(), key=lambda r: r["seq"]) if log.exists() else []


def _body(record: dict[str, Any] | None) -> dict[str, Any]:
    try:
        body = json.loads((record or {}).get("body") or "{}")
    except ValueError:
        return {}
    return body if isinstance(body, dict) else {}


def _record_id(records_dir: Path, prefix: str) -> str:
    log = records_dir / cli.MEMORY_LOG
    existing = {r["record_id"] for r in cli.read_log(log)} if log.exists() else set()
    return f"{prefix}-{len(existing) + 1:04d}"


def write_postmortems(records_dir: Path, exps: list[dict[str, Any]], memory: list[dict[str, Any]],
                      limit: int | None = None) -> tuple[list[str], int]:
    """TP records for the trades that have none yet (by archive fingerprint). Returns (ids written, left over)."""
    limit = MAX_PER_RUN if limit is None else limit
    done = {_body(r).get("fingerprint") for r in memory if str(r.get("id", "")).startswith("TP-")}
    todo = [(i, e) for i, e in enumerate(exps) if e.get("fingerprint") not in done]
    written = []
    for i, exp in todo[:limit]:
        why = explain(exp, exps[:i])
        net = exp["net_pnl"]
        body = {"fingerprint": exp.get("fingerprint"), "position_id": exp.get("position_id"), "symbol": exp.get("symbol"),
                "opened_at": exp.get("opened_at"), "closed_at": exp.get("closed_at"), "regime_at_entry": exp.get("regime"),
                "confidence": exp.get("confidence"), "band": exp.get("band"), "risk": exp.get("risk"),
                "experiment_id": exp.get("experiment_id"), "notional": exp.get("notional"),
                "gross_pnl": exp.get("gross_pnl"), "net_pnl": net, **why, "analysis": exp.get("analysis")}
        rid = _record_id(records_dir, "TP")
        cli.add_memory_record(records_dir, {
            "record_id": rid, "type": "TRADING", "authority": "RESEARCH",
            "title": f"İşlem sonrası: {exp.get('symbol')} {_OUTCOME_TR[why['kind']]} net {net} — {why['reason'][:120]}",
            "body": json.dumps(body, ensure_ascii=False, default=str),
            "author": UNIT, "source": "tools/trade_postmortem.py (learning_view.experiences + entry approval)"})
        written.append(rid)
    return written, max(0, len(todo) - limit)


def _age_h(stamp: Any, now: datetime) -> float | None:
    try:
        t = datetime.strptime(str(stamp), "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    except ValueError:
        return None
    return (now - t).total_seconds() / 3600


def review_due(memory: list[dict[str, Any]], now: datetime) -> tuple[bool, list[dict[str, Any]], dict[str, Any] | None]:
    """(due, post-mortems since the last review, the last review)."""
    reviews = [r for r in memory if str(r.get("id", "")).startswith("TR-")]
    last = reviews[-1] if reviews else None
    since = int(last.get("seq") or 0) if last else 0  # the log order, exact even within one second
    new = [r for r in memory if str(r.get("id", "")).startswith("TP-") and int(r.get("seq") or 0) > since]
    if not new:
        return False, new, last
    if last is None:  # the first review also waits for a sample worth a model call
        return len(new) >= REVIEW_EVERY, new, last
    age = _age_h(last.get("created_at"), now)
    if age is None:
        return False, new, last  # unreadable time of the last review: fail closed, spend nothing
    return (len(new) >= REVIEW_EVERY and age >= REVIEW_MIN_GAP_H) or age >= REVIEW_MAX_GAP_H, new, last


def review(records_dir: Path, memory: list[dict[str, Any]], *, ask: Callable[..., Any] | None = None, ledger: Any = None,
           now: datetime | None = None) -> dict[str, Any]:
    """The AI-001 review of the latest post-mortems. Returns {"summary", "pending"}."""
    now = now or datetime.now(timezone.utc)
    due, new, last = review_due(memory, now)
    if not due:
        return {"summary": f"AI incelemesi beklemede ({len(new)} yeni işlem)" if new else "", "pending": False}
    tps = [r for r in memory if str(r.get("id", "")).startswith("TP-")][-REVIEW_WINDOW:]
    ids = {str(r.get("id")) for r in tps}
    lines = []
    for r in tps:
        b = _body(r)
        lines.append(f"[{r.get('id')}] {b.get('symbol')} | {b.get('kind')} | net {b.get('net_pnl')} | {b.get('regime_at_entry')} | "
                     f"band {b.get('band')} | {b.get('reason')} | before: {b.get('pattern_so_far')}")
    perf = next((r for r in reversed(memory) if r.get("author") == "quant_research"), None)
    notes = [r for r in memory if r.get("author") == "deployment_manager"][-3:]
    earlier = [s for s in _body(last).get("suggestions", []) if isinstance(s, dict)]
    head = "This is your first review: no earlier suggestions."
    if last is not None and earlier:
        head = (f"Your previous review {last.get('id')} ({last.get('created_at')}) suggested:\n" +
                "\n".join(f"- {s.get('change')} (test: {s.get('test')})" for s in earlier))
    perf_text = "no performance report yet"
    if perf is not None:
        perf_text = f"[{perf.get('id')}] {perf.get('title')}\n{json.dumps(_body(perf).get('total'), ensure_ascii=False)}"
    notes_text = "\n".join(f"[{n.get('id')}] {n.get('title')}" for n in notes) or "no change notes yet"
    prompt = (f"{head}\n\nTrade post-mortems, oldest first (id | symbol | outcome | net | regime at entry | confidence band "
              f"| why | how the same regime + band did before):\n" + "\n".join(lines) +
              f"\n\nPerformance now:\n{perf_text}\n\nLatest change notes (what changed in Atlas):\n{notes_text}\n\n{_REVIEW_TASK}")
    if ask is None:
        from tools.ai_gateway import ask as gateway_ask

        ask = gateway_ask
    res = ask(_REVIEW_SYSTEM, prompt, _REVIEW_SCHEMA, ledger=ledger, agent=UNIT)
    if res.status != "OK":
        return {"summary": f"AI incelemesi çekimser: {res.reason}", "pending": True}
    data = res.data or {}
    known = ids | ({str(perf.get("id"))} if perf else set()) | {str(n.get("id")) for n in notes} | (
        {str(last.get("id"))} if last else set())
    cited = [c for c in data.get("cited_records", []) if isinstance(c, str)]
    patterns = [str(p)[:500] for p in data.get("patterns", []) if str(p).strip()][:3]
    followups = [str(f)[:400] for f in data.get("followups", []) if str(f).strip()][:5]
    suggestions = [{k: str(s.get(k, ""))[:600] for k in ("change", "why", "test", "risk")}
                   for s in data.get("suggestions", []) if isinstance(s, dict) and str(s.get("change", "")).strip()][:3]
    if not (patterns or followups or suggestions):
        return {"summary": "AI incelemesi: yeni bir örüntü ya da öneri yok; kayıt yazılmadı", "pending": False}
    if not cited or any(c not in known for c in cited):
        return {"summary": "AI incelemesi reddedildi: var olmayan ya da hiç kayıt gösterilmedi (kanıt doğrulaması)",
                "pending": False}
    rid = _record_id(records_dir, "TR")
    cli.add_memory_record(records_dir, {
        "record_id": rid, "type": "REVIEWS", "authority": "TEMPORARY",
        "title": f"İşlem incelemesi (AI-001): {len(patterns)} örüntü, {len(suggestions)} öneri (tavsiye, karar değil)",
        "body": json.dumps({"patterns": patterns, "followups": followups, "suggestions": suggestions, "cited_records": cited,
                            "reviewed": sorted(ids), "builds_on": last.get("id") if last else None,
                            "model": res.model, "cost_usd": str(res.cost_usd)}, ensure_ascii=False),
        "author": UNIT, "source": "tools/trade_postmortem.py (review, tools/ai_gateway.py)"})
    return {"summary": f"AI incelemesi {rid}: {len(patterns)} örüntü, {len(suggestions)} öneri", "pending": False}


def run(records_dir: Path, closed: list[dict[str, Any]], approvals: dict[str, list[dict]], *,
        ask: Callable[..., Any] | None = None, ledger: Any = None, now: datetime | None = None) -> dict[str, Any]:
    memory = _memory(records_dir)
    exps = facts(closed, memory, approvals)
    written, left = write_postmortems(records_dir, exps, memory)
    memory = _memory(records_dir) if written else memory
    outcome = review(records_dir, memory, ask=ask, ledger=ledger, now=now)
    kinds = [(_body(r).get("kind")) for r in memory if r.get("id") in set(written)]
    parts = [f"{len(written)} işlem hafızaya yazıldı ({kinds.count('WIN')} kazanç, "
             f"{len(written) - kinds.count('WIN')} kayıp)" if written else f"{len(exps)} işlem; yeni kapanan işlem yok"]
    if left:
        parts.append(f"{left} işlem sonraki çalışmaya kaldı")
    if outcome["summary"]:
        parts.append(outcome["summary"])
    return {"verdict": "OK", "summary": "; ".join(parts), "pending": bool(left) or outcome["pending"]}
