"""A generic request must not retrieve a whole mechanism store through grammatical words."""

from animedex.light.ideation import retrieve_materials


def test_retrieval_matches_content_and_preserves_domain_breadth():
    materials = {
        "memory": {"domain": "science", "causal_rule": "A recalled memory becomes unstable."},
        "bridge": {"domain": "science", "causal_rule": "A bridge consumes workers from traffic."},
        "contract": {"domain": "law", "causal_rule": "A contract distributes a shared obligation."},
    }
    assert retrieve_materials("a story", materials, len(materials)) == []
    assert retrieve_materials("unstable memory", materials, len(materials)) == ["memory"]
    selected = retrieve_materials("memory bridge obligation", materials, len(materials))
    assert len(selected) == len(materials)
    assert materials[selected[0]]["domain"] != materials[selected[1]]["domain"]
