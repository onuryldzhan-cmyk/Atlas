"""Audit F-2: hand-written world-model strengths are labelled hypotheses, never measured evidence."""

from ai.core.atlas_world_model import AtlasWorldModel


def test_every_seed_relationship_is_a_hypothesis():
    world = AtlasWorldModel()
    edges = [e.to_dict() for e in world.graph.edges] if hasattr(world.graph, "edges") else []
    assert edges, "world model has no edges to check"
    assert all(e["provenance"] == "STATIC_SEED_HYPOTHESIS" and e["validated"] is False for e in edges)
