"""Audit F-2: hand-written world-model strengths are labelled hypotheses, never measured evidence."""

from ai.core.atlas_world_model import AtlasWorldModel


def test_every_seed_relationship_is_a_hypothesis():
    world = AtlasWorldModel()
    edges = [e.to_dict() for e in world.graph.edges] if hasattr(world.graph, "edges") else []
    assert edges, "world model has no edges to check"
    assert all(e["provenance"] == "STATIC_SEED_HYPOTHESIS" and e["validated"] is False for e in edges)


def test_temporal_validity_window():
    from ai.core.atlas_world_model import MarketEdge, RelationshipType

    e = MarketEdge("A", "B", RelationshipType.CORRELATION, 0.5, valid_from="2026-01-01", valid_until="2026-07-01")
    assert e.is_valid_at("2026-03-01") and not e.is_valid_at("2025-12-31") and not e.is_valid_at("2026-07-01")
    assert e.to_dict()["valid_until"] == "2026-07-01"
    assert MarketEdge("A", "B", RelationshipType.CORRELATION).is_valid_at("2099-01-01")
