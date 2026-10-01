"""Command Center brief and Atlas Chat, composed only from real read-only state.

``compose`` merges payloads the web layer already produces (runtime health,
account totals, proposals, tasks, memory) into one brief. ``answer`` maps a
question to one of a fixed set of intents and answers from that brief.

Atlas Chat is deterministic, not an LLM: it never invents a number, it only
repeats what the brief holds, and when a source is unavailable it says so.
It cannot act: no intent writes anything, starts anything or approves
anything - an approval request is answered with how the owner does it.
"""

from __future__ import annotations

import re
from typing import Any

INTENTS = (
    ("proposal_detail", r"(proposal|[oö]neri)\s*#?\s*(p-\d+|\d+)"),
    ("approve", r"onayla|approve|reddet|reject"),
    ("help", r"yard[ıi]m|help|ne sorabilirim|neler sorabilirim|komutlar"),
    ("positions", r"pozisyon|position|elimde|neler var|ne tutuyor"),
    ("pnl", r"\bk[aâ]r(\b|[ıi]|lar)|zarar|kazan[cç]|getiri|pnl|p/l|sermaye|bakiye|balance|equity|ne kadar para"),
    ("proposals", r"proposal|[oö]neri|karar|onay|decision|bekleyen"),
    ("tasks", r"g[oö]rev|task|i[sş] (var|ne)"),
    ("agents", r"ajan|agent|kim [cç]al[ıi][sş][ıi]yor|who is working"),
    ("health", r"sa[gğ]l[ıi]k|health|sistem|system|problem|sorun|hata|online"),
    ("trading", r"trad|i[sş]lem|portf|pnl|p/l|k[aâ]r|zarar|bakiye|balance|pozisyon|position"),
    ("memory", r"haf[ıi]za|memory|ne biliyor|know|kay[ıi]t"),
    ("summary", r"[oö]zet|summary|bug[uü]n|today|ne oldu|what happened|durum|status|merhaba|hello"),
)


def compose(*, health: dict[str, Any], account: dict[str, Any] | None,
            proposals: dict[str, Any], tasks: dict[str, Any], memory: dict[str, Any],
            portfolio: dict[str, Any] | None = None,
            agent_states: dict[str, Any] | None = None) -> dict[str, Any]:
    def section(payload: dict[str, Any]) -> dict[str, Any]:
        return payload if payload.get("available") else {"available": False,
                                                         "reason": payload.get("reason", "UNKNOWN")}

    # Single source of agent state (Stage A1, 2026-10-01): when the
    # observability.agent_states view is supplied, every surface (HQ, Overview,
    # chat) reports the same states. Without it the task-log view is kept.
    if agent_states and agent_states.get("available"):
        agents = {a["id"]: {"status": a["state"]} for a in agent_states.get("agents", [])}
        working = sorted(a for a, v in agents.items() if v["status"] in ("WORKING", "REVIEWING"))
        source = "agent_states"
    else:
        agents = tasks.get("agents", {}) if tasks.get("available") else {}
        working = sorted(a for a, v in agents.items() if v.get("status") == "WORKING")
        source = "task_log"
    return {
        "available": True,
        "health": {"healthy": health.get("healthy"), "state": health.get("state"),
                   "reason": health.get("reason")},
        "trading": {"available": account is not None, **(account or {"reason": "PORTFOLIO_NOT_ATTACHED"}),
                    "mode": "PAPER", "live_authority": "DENIED"},
        "proposals": {"available": proposals.get("available", False),
                      "awaiting_owner": proposals.get("awaiting_owner", []),
                      "counts": proposals.get("counts", {}),
                      "reason": proposals.get("reason")},
        "tasks": {"available": tasks.get("available", False), "counts": tasks.get("counts", {}),
                  "reason": tasks.get("reason")},
        "agents": {"working": working, "statuses": {a: v.get("status") for a, v in agents.items()},
                   "source": source},
        "memory": {"available": memory.get("available", False),
                   "records": len(memory.get("records", [])) if memory.get("available") else None},
        "_proposals": section(proposals),
        "_portfolio": portfolio if portfolio and portfolio.get("available") else None,
    }


def _coin_in(text: str, portfolio: dict[str, Any] | None) -> str | None:
    """A coin the question names (BTC, btcusdt, ...), matched against the coins Atlas really scans."""

    if not portfolio:
        return None
    for item in portfolio.get("market", []):
        symbol = item["symbol"]
        base = symbol[:-4] if symbol.endswith("USDT") else symbol
        if re.search(rf"\b({base.lower()}|{symbol.lower()})\b", text):
            return symbol
    return None


def _money(value: Any) -> str:
    return "bilinmiyor" if value is None else f"{float(value):,.2f} $".replace(",", "X").replace(".", ",").replace("X", ".")


def classify(question: str) -> tuple[str, re.Match | None]:
    text = (question or "").replace("İ", "i").replace("I", "i").lower().replace("ı", "i")
    for intent, pattern in INTENTS:
        m = re.search(pattern, text)
        if m:
            return intent, m
    return "unknown", None


def _unavailable(name: str, part: dict[str, Any]) -> str:
    return f"{name}: bilgi yok ({part.get('reason') or 'UNKNOWN'})."


def answer(question: str, brief: dict[str, Any]) -> dict[str, Any]:
    intent, match = classify(question)
    portfolio = brief.get("_portfolio")
    normalised = (question or "").replace("İ", "i").replace("I", "i").lower().replace("ı", "i")
    coin = _coin_in(normalised, portfolio)
    if coin and intent not in ("approve", "proposal_detail"):
        intent = "coin"
    h, t, p, k, a, m = (brief["health"], brief["trading"], brief["proposals"], brief["tasks"],
                        brief["agents"], brief["memory"])
    navigate = None

    def health_line() -> str:
        if h.get("healthy") is True:
            return f"Sistem sağlıklı ({h.get('state')})."
        return f"Sistem sağlıklı DEĞİL: durum {h.get('state') or 'UNKNOWN'} ({h.get('reason') or 'neden bilinmiyor'})."

    def proposal_line() -> str:
        if not p["available"]:
            return _unavailable("Öneriler", p)
        waiting = p["awaiting_owner"]
        return (f"{len(waiting)} öneri onayınızı bekliyor: {', '.join(waiting)}." if waiting
                else "Onayınızı bekleyen öneri yok.")

    def task_line() -> str:
        if not k["available"]:
            return _unavailable("Görevler", k)
        c = k["counts"]
        return (f"Görevler: {c.get('IN_PROGRESS', 0)} sürüyor, {c.get('BLOCKED', 0)} engelli, "
                f"{c.get('DONE', 0)} bitti.")

    def agent_line() -> str:
        return (f"Çalışan ajanlar: {', '.join(a['working'])}." if a["working"]
                else "Şu anda çalışan ajan yok (ajanlar yalnızca görev atandığında çalışır).")

    def trading_line() -> str:
        if portfolio:
            stale = " Fiyatlar ESKİ, piyasa döngüsünü kontrol edin." if portfolio.get("prices_stale") else ""
            pct = portfolio.get("total_pnl_pct")
            return (f"PAPER hesap (canlı para KAPALI): toplam sermaye {_money(portfolio.get('equity'))}, "
                    f"toplam kâr/zarar {_money(portfolio.get('total_pnl'))}"
                    f"{'' if pct is None else f' (%{pct})'}, açık pozisyon {len(portfolio.get('positions', []))}.{stale}")
        if not t["available"]:
            return _unavailable("Trading (PAPER)", t)
        return (f"Trading PAPER modunda (canlı para KAPALI). Gerçekleşen net kâr/zarar {t['realized_net_pnl']}, "
                f"ödenen ücret {t['fees']}.")

    if intent == "summary":
        lines = [health_line(), agent_line(), task_line(), proposal_line(), trading_line()]
    elif intent == "health":
        lines = [health_line()]
    elif intent == "proposals":
        lines = [proposal_line()]
        navigate = "#section-proposals-title"
    elif intent == "proposal_detail":
        raw = match.group(2).upper()
        pid = raw if raw.startswith("P-") else f"P-{int(raw):04d}"
        items = brief["_proposals"].get("proposals", []) if brief["_proposals"].get("available") else []
        found = next((x for x in items if x["id"] == pid), None)
        if found:
            decision = found.get("owner_decision") or {}
            note = (" (sahip imzası bu ekranda doğrulanamaz; kendi makinenizde: python -m tools.atlas_org_cli verify)"
                    if decision and decision.get("verified") is not True else "")
            lines = [f"{pid} — {found['title']}: durum {found['status']}{note}, risk {found['risk_level']}, "
                     f"öneren {found['author']}. Ayrıntılar Öneriler bölümünde."]
            navigate = f"proposal:{pid}"
        else:
            lines = [f"{pid} bulunamadı."]
    elif intent == "approve":
        lines = ["Atlas Chat onay veremez, reddedemez ve bir şey değiştiremez. Kararı siz verirsiniz: "
                 "python -m tools.atlas_org_cli proposal-event --id <ID> --event OWNER_APPROVE "
                 "--actor owner --owner-confirm <ID> (reddetmek için OWNER_REJECT)."]
    elif intent == "tasks":
        lines = [task_line()]
    elif intent == "agents":
        lines = [agent_line()]
    elif intent == "trading":
        lines = [trading_line()]
    elif intent == "pnl":
        if portfolio:
            lines = [trading_line(), f"Gerçekleşen net {_money(portfolio.get('realized_net_pnl'))}, gerçekleşmemiş "
                     f"{_money(portfolio.get('unrealized_pnl'))}, ödenen ücret {_money(portfolio.get('fees'))}, "
                     f"başlangıç {_money(portfolio.get('starting_capital'))}."]
            navigate = "/trading"
        else:
            lines = [trading_line()]
    elif intent == "positions":
        if not portfolio:
            lines = [trading_line()]
        elif not portfolio.get("positions"):
            lines = ["Açık pozisyon yok."]
        else:
            lines = ["Açık pozisyonlar: " + "; ".join(
                f"{p['symbol']} {p['quantity']} adet, ortalama {p['average_entry_price']}, şimdi "
                f"{p['price'] or 'fiyat yok'}, K/Z {_money(p['unrealized_pnl'])}"
                f"{'' if p['unrealized_pct'] is None else ' (%' + p['unrealized_pct'] + ')'}"
                for p in portfolio["positions"]) + "."]
            navigate = "/trading"
    elif intent == "coin":
        m = next(x for x in portfolio["market"] if x["symbol"] == coin)
        held = next((p for p in portfolio.get("positions", []) if p["symbol"] == coin), None)
        conf = m.get("confidence")
        lines = [f"{coin}: fiyat {m['price']} (gerçek, Binance mum kapanışı), Atlas'ın son kararı {m.get('action') or '-'}"
                 f"{'' if conf is None else f' (güven {float(conf):.0f})'}, risk {m.get('risk_level') or '-'}."]
        lines.append(f"Pozisyonda: {held['quantity']} adet, ortalama {held['average_entry_price']}, K/Z "
                     f"{_money(held['unrealized_pnl'])}." if held else "Bu coinde açık pozisyon yok.")
        if portfolio.get("prices_stale"):
            lines.append("Uyarı: fiyatlar eski.")
    elif intent == "help":
        lines = ["Sorabilecekleriniz: 'bugün ne oldu', 'toplam kâr ne kadar', 'pozisyonlarım', 'BTC ne durumda', "
                 "'sistemde sorun var mı', 'bekleyen öneriler', 'öneri P-0001', 'görevler', 'kim çalışıyor', 'hafıza'. "
                 "Atlas Chat yalnız gerçek durumu okur; işlem açamaz, onay veremez."]
    elif intent == "memory":
        lines = [f"Atlas Hafızası'nda {m['records']} kayıt var." if m["available"]
                 else "Atlas Hafızası okunamadı."]
    else:
        lines = ["Bunu anlayamadım. Sorabilecekleriniz: özet, sistem sağlığı, öneriler, öneri P-0001, "
                 "görevler, ajanlar, trading, hafıza."]
    return {"available": True, "intent": intent, "answer": " ".join(lines), "navigate": navigate,
            "engine": "deterministic (observability/command_center.py), no LLM"}
