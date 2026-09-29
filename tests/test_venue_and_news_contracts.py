"""Tasks 13/14: the venue registry matches the loaded instrument rules; no news source is active and news has no order authority."""

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_venue_registry_matches_instrument_rules():
    venues = json.loads((ROOT / "config" / "venues.json").read_text(encoding="utf-8"))["venues"]
    rules = json.loads((ROOT / "config" / "instrument_rules.json").read_text(encoding="utf-8"))["rules"]
    ids = {v["venue_id"] for v in venues}
    assert {r["venue"] for r in rules} <= ids
    quotes = {q for v in venues for q in v["quote_assets"]}
    assert {r["quote_asset"] for r in rules} <= quotes
    assert all("NONE" in v["order_submission"] for v in venues)


def test_news_contract_has_no_active_source_and_no_order_authority():
    news = json.loads((ROOT / "config" / "news_sources.json").read_text(encoding="utf-8"))
    assert news["active_sources"] == []
    assert "never create an order" in news["rules"]["authority"]
