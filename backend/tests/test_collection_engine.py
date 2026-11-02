import pytest
from app.services.collection_engine import (
    find_weakly_connected_components,
    topological_sort_subgraph,
    generate_collection_identity,
    determine_collection_health,
)


def test_find_weakly_connected_components():
    story_ids = {"S1", "S2", "S3", "S4", "S_SOLO"}
    edges = [("S1", "S2"), ("S2", "S3")]  # S1 -> S2 -> S3 (comp 1)
    # S4 and S_SOLO have no edges

    comps = find_weakly_connected_components(story_ids, edges)
    assert len(comps) == 1
    assert comps[0] == {"S1", "S2", "S3"}


def test_find_multiple_components():
    story_ids = {"A1", "A2", "B1", "B2", "B3", "SOLO"}
    edges = [("A1", "A2"), ("B1", "B2"), ("B2", "B3")]

    comps = find_weakly_connected_components(story_ids, edges)
    assert len(comps) == 2
    comp_sets = [set(c) for c in comps]
    assert {"A1", "A2"} in comp_sets
    assert {"B1", "B2", "B3"} in comp_sets


def test_topological_sort_subgraph():
    comp = {"Auth", "Cart", "Checkout"}
    directed_edges = [("Auth", "Cart"), ("Cart", "Checkout")]
    titles = {"Auth": "Story 1: Auth", "Cart": "Story 2: Cart", "Checkout": "Story 3: Checkout"}

    order = topological_sort_subgraph(comp, directed_edges, titles)
    assert order == ["Auth", "Cart", "Checkout"]


def test_topological_sort_diamond():
    # Diamond: S1 -> S2, S1 -> S3, S2 -> S4, S3 -> S4
    comp = {"S1", "S2", "S3", "S4"}
    edges = [("S1", "S2"), ("S1", "S3"), ("S2", "S4"), ("S3", "S4")]
    titles = {"S1": "S1", "S2": "S2", "S3": "S3", "S4": "S4"}

    order = topological_sort_subgraph(comp, edges, titles)
    assert order[0] == "S1"
    assert order[-1] == "S4"
    assert set(order[1:3]) == {"S2", "S3"}


def test_generate_collection_identity():
    topo_order = ["S1", "S2", "S3"]
    titles = {
        "S1": "Story 1: Auth & User Session",
        "S2": "Story 2: Cart Management",
        "S3": "Story 3: Checkout & Payment",
    }
    name, code = generate_collection_identity(topo_order, titles, set())
    assert "Auth & User Session" in name
    assert "Checkout & Payment" in name
    assert code.startswith("COL-")
