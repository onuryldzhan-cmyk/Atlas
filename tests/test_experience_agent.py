"""Experience agent (owner 2026-10-02): one replayed day per cycle, walk-forward lessons, research only."""
from decimal import Decimal
from types import SimpleNamespace

from atlas_org import memory_records
from tools import atlas_org_cli as cli
from tools import experience_agent as xp

D = xp.DAY_MS
NOW = 100 * D + 6 * 3_600_000  # day 100, 06:00 UTC


def test_next_day_first_then_forward_then_backward_then_done():
    # 2026-10-02 option C: the longest outcome is 1 day, so a day is complete only when the
    # whole following day has passed (was 240 minutes; expectations moved one day back).
    assert xp.next_day({}, NOW) == (98 * D, "first")
    assert xp.next_day({"newest_day_ms": 97 * D, "oldest_day_ms": 97 * D}, NOW) == (98 * D, "forward")
    assert xp.next_day({"newest_day_ms": 98 * D, "oldest_day_ms": 98 * D}, NOW) == (97 * D, "backward")
    full = {"newest_day_ms": 98 * D, "oldest_day_ms": 98 * D - xp.MAX_DAYS_BACK * D}
    assert xp.next_day(full, NOW) is None


def _fake_replay(n_per_day=4, net="0.002", spacing_ms=21_600_000):
    # 2026-10-02: decisions 6 h apart by default, so each is an independent 240m outcome
    # (candidate lessons now count non-overlapping outcomes; see test_overlapping_decisions_are_not_independent_evidence)
    def replay(data, **kw):
        assert kw["record_signals"] is True and set(data) <= set(xp.symbols()) and "BTCUSDT" in data
        first = min(int(r[0]) for rows in data.values() for r in rows)
        day = first + xp_window_ms()
        from datetime import UTC, datetime
        sigs = []
        for i in range(n_per_day):
            t = datetime.fromtimestamp((day + i * spacing_ms) / 1000, UTC).isoformat()
            sigs.append({"symbol": "BTCUSDT", "time": t, "action": "BUY", "confidence": Decimal("61"),
                         "bucket": "MEDIUM", "regime": "TREND_UP", "net_60m": Decimal(net), "net_240m": Decimal(net)})
        before = datetime.fromtimestamp((first) / 1000, UTC).isoformat()  # warm-up decision: must be dropped
        sigs.append({**sigs[0], "time": before})
        return SimpleNamespace(signals=sigs)
    return replay


def xp_window_ms():
    from tools import backtest_replay as bt
    return bt.WINDOW * 60_000


def _fetch(symbol, start):
    if start >= NOW:
        return []
    return [[start + i * 60_000, "1", "1", "1", "1", "1", start + i * 60_000 + 59_999] for i in range(1000)]


def test_run_walks_days_records_lessons_once_and_touches_nothing_else(tmp_path):
    rec, res = tmp_path / "records", tmp_path / "research"
    for _ in range(40):  # 40 days x 4 BUY decisions, all +0.2% -> one stable candidate lesson
        out = xp.run(rec, res, fetch=_fetch, now_ms=NOW, replay=_fake_replay())
        assert out["verdict"] == "OK"
    state_path, signals_path = xp._paths(res)
    import json
    state = json.loads(state_path.read_text())
    assert state["days"] == 40 and state["newest_day_ms"] == 98 * D and state["oldest_day_ms"] == 59 * D
    rows = signals_path.read_text().splitlines()
    assert len(rows) == 1 + 40 * 4  # warm-up decisions outside the day were dropped
    xps = [r for r in memory_records.replay(cli.read_log(rec / cli.MEMORY_LOG)).values() if r["author"] == "experiment_manager"]
    assert len(xps) == 1 and "aday ders" in xps[0]["title"]  # written once, when the candidate set appeared
    assert sorted(p.name for p in tmp_path.rglob("*") if p.is_file()) == sorted(
        [cli.MEMORY_LOG, "state.json", "signals_v3.csv"] + [p.name for p in rec.iterdir() if p.name != cli.MEMORY_LOG])


def test_network_failure_records_nothing_and_retries_the_same_day(tmp_path):
    def broken(symbol, start):
        raise OSError("timeout")
    out = xp.run(tmp_path / "r", tmp_path / "x", fetch=broken, now_ms=NOW, replay=_fake_replay())
    assert out["verdict"] == "WARN"
    assert xp._load_state(xp._paths(tmp_path / "x")[0]) == {}


def test_candidate_needs_both_halves_measured_and_agreeing():
    def rows(net, n, start):
        return [{"time": f"{start}{i:05d}", "action": "BUY", "regime": "SIDEWAYS", "confidence": "61",
                 "symbol": "X", "bucket": "M", "net_60m": net, "net_240m": net} for i in range(n)]
    agree = rows("0.01", 40, "a") + rows("0.02", 40, "b")
    assert len(xp.candidate_lessons(agree)) == 1
    flip = rows("0.01", 40, "a") + rows("-0.02", 40, "b")
    assert xp.candidate_lessons(flip) == []           # direction changed between halves: no lesson
    assert xp.candidate_lessons(rows("0.01", 40, "a")) == []  # one half under MIN_SAMPLES


def test_all_watched_coins_and_a_coin_without_history_does_not_erase_the_day(tmp_path):
    assert len(xp.symbols()) == 20 and "BTCUSDT" in xp.symbols()  # config/universe_selection.json
    seen = {}

    def replay(data, **kw):
        seen.update(data)
        return SimpleNamespace(signals=[])

    def fetch(symbol, start):
        if symbol == "0GUSDT":  # not listed yet in this window
            return []
        return _fetch(symbol, start)
    xp.replay_day(98 * D, fetch, replay=replay)
    assert "0GUSDT" not in seen and "BTCUSDT" in seen and len(seen) == 19


def test_stream_groups_match_lesson_book_build(tmp_path):
    import csv as _csv
    import random

    from tools import experience_agent as xa
    from tools import lesson_book as lb

    rng = random.Random(7)
    cols = ["time", "action", "regime", "confidence", "net_240m", "ret_240m"]
    rows = []
    for i in range(400):
        rows.append({"time": f"2026-01-{1 + i % 28:02d}T00:00:00+00:00", "action": rng.choice(["BUY", "SELL"]),
                     "regime": rng.choice(["TREND_UP", "RANGE", ""]), "confidence": str(rng.randint(50, 64)),
                     "net_240m": "" if i % 17 == 0 else f"{rng.uniform(-0.02, 0.02):.6f}",
                     "ret_240m": "" if i % 5 else f"{rng.uniform(-0.02, 0.02):.6f}"})
    path = tmp_path / "s.csv"
    with path.open("w", newline="", encoding="utf-8") as f:
        w = _csv.DictWriter(f, fieldnames=cols)
        w.writeheader()
        w.writerows(rows)
    split = "2026-01-15T00:00:00+00:00"
    older, newer, total = xa.stream_groups(path, split)
    assert total == 400
    for part, got in (([r for r in rows if r["time"] < split], older), ([r for r in rows if r["time"] >= split], newer)):
        want = {(g["action"], g["regime"], g["confidence"]): g for g in lb.build(part)}
        assert set(want) == set(got)
        for k, g in want.items():
            for field in ("n", "verdict", "net_240m_win", "net_240m_avg_pct"):
                assert got[k][field] == g[field], (k, field)
    lessons, n = xa.stream_candidates(path, split)
    assert n == 400 and lessons == xa._compare(older, newer)


def test_experience_view_reads_state_and_reports_missing(tmp_path):
    import json as _json

    from observability import experience_view as ev

    missing = ev.read_experience(tmp_path / "none.json")
    assert missing["available"] is False
    bad = tmp_path / "bad.json"
    bad.write_text("{", encoding="utf-8")
    assert ev.read_experience(bad)["available"] is False
    good = tmp_path / "state.json"
    good.write_text(_json.dumps({"days": 3, "decisions": 120, "oldest_day_ms": 0, "newest_day_ms": 2 * 86_400_000,
                                 "candidate_lessons": [{"action": "BUY"}]}), encoding="utf-8")
    out = ev.read_experience(good)
    assert out["available"] and out["days"] == 3 and out["oldest_day"] == "1970-01-01" and out["newest_day"] == "1970-01-03"
    assert out["updated_at"] is None and out["candidate_lessons"] == [{"action": "BUY"}]


def test_experience_view_without_runtime_is_unavailable():
    from observability import experience_view as ev

    assert ev.state_path_for(None) is None
    assert ev.read_experience(None)["available"] is False
    assert str(ev.state_path_for("/s")).replace("\\", "/") == "/s/research/experience/state.json"


def _lesson(sign=1.0):
    return {"action": "BUY", "regime": "TREND_UP", "confidence": "60-65", "n_older": 40, "n_newer": 35,
            "avg240_older_pct": 0.2 * sign, "avg240_newer_pct": 0.3 * sign, "win240_older": 0.6, "win240_newer": 0.6}


def test_streaks_count_consecutive_days_and_reset():
    from tools import experience_agent as xa

    s = {}
    for _ in range(3):
        s = xa.update_streaks(s, [_lesson()])
    assert list(s.values()) == [3]
    assert xa.update_streaks(s, [_lesson(-1)]) == {"BUY-TREND_UP-60_65-NEG": 1}  # direction flip is a new lesson
    assert xa.update_streaks(s, []) == {}


def test_stable_lesson_is_drafted_once_and_never_applied(tmp_path):
    from atlas_org import proposals as P
    from tools import atlas_org_cli as cli
    from tools import experience_agent as xa

    lessons = [_lesson()]
    key = xa._lesson_key(lessons[0])
    assert xa.draft_proposals(tmp_path, lessons, {key: xa.STABLE_RUNS - 1}) == []
    assert xa.draft_proposals(tmp_path, lessons, {key: xa.STABLE_RUNS}) == [f"XL-{key}.1"]
    assert xa.draft_proposals(tmp_path, lessons, {key: xa.STABLE_RUNS + 5}) == []  # already open: no duplicate
    events = cli.read_log(tmp_path / cli.PROPOSALS_LOG)
    assert [e["event"] for e in events] == ["CREATE"] and events[0]["actor"] == "experiment_manager"
    state = P.replay(events)[f"XL-{key}.1"]
    assert state.status not in P.TERMINAL and state.owner_decision is None


def test_red_team_reviews_experience_drafts(tmp_path):
    import json as _json

    from tools import agent_cycle as ac
    from tools import atlas_org_cli as cli
    from tools import experience_agent as xa

    lesson = _lesson()
    [pid] = xa.draft_proposals(tmp_path, [lesson], {xa._lesson_key(lesson): xa.STABLE_RUNS})
    out = ac.red_team(tmp_path)
    assert pid in out["summary"]
    [rec] = [r for r in cli.read_log(tmp_path / cli.MEMORY_LOG) if r.get("related_proposal") == pid]
    assert "shadow" in _json.loads(rec["body"])["challenge"]
    assert pid not in ac.red_team(tmp_path)["summary"]  # reviewed once


def test_overlapping_decisions_are_not_independent_evidence(tmp_path):
    """40 days x 4 BUY decisions 15 minutes apart = 40 independent 240m outcomes, 20 per half: no lesson."""
    rec, res = tmp_path / "records", tmp_path / "research"
    for _ in range(40):
        xp.run(rec, res, fetch=_fetch, now_ms=NOW, replay=_fake_replay(spacing_ms=900_000))
    import json
    state = json.loads(xp._paths(res)[0].read_text())
    assert state["decisions"] == 160 and state["candidate_lessons"] == []


def test_non_overlapping_count_keeps_outcomes_240_minutes_apart():
    assert xp._non_overlapping(set()) == 0
    assert xp._non_overlapping({5}) == 1
    assert xp._non_overlapping({1, 2, 3, 4}) == 2  # neighbours may be 15 minutes apart: every other one
    assert xp._non_overlapping({1, 3, 5}) == 3


def test_binomial_and_bh_match_scipy_and_statsmodels_reference_values():
    """Reference values from scipy.stats.binomtest and statsmodels multipletests(method="fdr_bh")."""
    import pytest as _pytest

    for k, n, ref in ((7, 10, 0.34375), (20, 30, 0.09873714670538905), (60, 100, 0.05688793364098089), (0, 5, 0.0625)):
        assert xp.binom_two_sided_p(k, n) == _pytest.approx(ref, rel=1e-9)
    assert xp.bh_qvalues([0.01, 0.04, 0.03, 0.2, 0.5]) == _pytest.approx(
        [0.05, 0.06666666666666667, 0.06666666666666667, 0.25, 0.5], rel=1e-12)


def test_lucky_groups_do_not_survive_the_false_discovery_filter():
    """200 coin-flip groups: a few look consistent in both halves by luck; none may become a lesson."""
    import random

    rng = random.Random(11)
    older, newer = {}, {}
    for i in range(200):
        for half in (older, newer):
            n = 60
            wins = sum(rng.random() < 0.5 for _ in range(n))
            half[("BUY", f"R{i}", "60-65")] = {"n": n, "n_eff": n, "verdict": "MEASURED", "net_240m_win": wins / n,
                                               "net_240m_avg_pct": (wins / n - 0.5) or 0.001}
    agreeing = [k for k in older if (older[k]["net_240m_avg_pct"] > 0) == (newer[k]["net_240m_avg_pct"] > 0)]
    assert len(agreeing) > 50  # without the filter, luck alone would hand over this many "lessons"
    assert xp._compare(older, newer) == []


def test_strong_consistent_group_survives_and_reports_q():
    g = {"n": 80, "n_eff": 80, "verdict": "MEASURED", "net_240m_win": 0.75, "net_240m_avg_pct": 0.4}
    noise = {("BUY", f"R{i}", "60-65"): {"n": 80, "n_eff": 80, "verdict": "MEASURED", "net_240m_win": 0.5,
                                          "net_240m_avg_pct": 0.01} for i in range(20)}
    older = {**noise, ("BUY", "TREND_UP", "60-65"): g}
    [lesson] = [c for c in xp._compare(older, dict(older)) if c["regime"] == "TREND_UP"]
    assert lesson["q_newer"] < xp.FDR_Q and lesson["tested_groups"] == 21


def test_daily_history_feeds_the_research_chart(tmp_path):
    rec, res = tmp_path / "records", tmp_path / "research"
    for _ in range(3):
        xp.run(rec, res, fetch=_fetch, now_ms=NOW, replay=_fake_replay())
    from observability import experience_view as ev

    out = ev.read_experience(xp._paths(res)[0])
    assert [d["decisions"] for d in out["daily"]] == [4, 4, 4]
    assert [d["day"] for d in out["daily"]] == sorted(d["day"] for d in out["daily"])


def test_replay_noise_does_not_reach_the_console_and_errors_still_do(caplog):
    # Owner console 2026-10-03: thousands of "execution skipped: manager unavailable" lines from this agent.
    import logging

    loop_log = logging.getLogger("AtlasAI.MarketLoop")
    before = loop_log.level

    def replay(data, **kw):
        loop_log.warning("BTCUSDT execution skipped: manager unavailable")
        loop_log.error("a real error")
        return SimpleNamespace(signals=[])

    with caplog.at_level(logging.DEBUG):
        xp.replay_day(98 * D, _fetch, symbols=["BTCUSDT"], replay=replay)
    messages = [r.getMessage() for r in caplog.records if r.name == "AtlasAI.MarketLoop"]
    assert messages == ["a real error"]
    assert loop_log.level == before                   # restored afterwards
