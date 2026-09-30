"""Tests for the shared filter / traversal layer used by both API and CLI."""

from datetime import date

import pytest

from proofweave.graph import (
    build_graph, filter_relationships, neighbours, shortest_path,
)
from proofweave.models import Direction, RelationType, Status


# --- filtering ---------------------------------------------------------------


def test_filter_by_type_matches_snapshot(snap):
    suppliers = filter_relationships(snap, relation_type=RelationType.supplier)
    expected = [r for r in snap.relationships if r.relation_type is RelationType.supplier]
    assert [r.id for r in suppliers] == [r.id for r in expected]
    assert suppliers, "snapshot should contain suppliers"


def test_filters_combine_conjunctively(snap):
    rows = filter_relationships(
        snap, relation_type=RelationType.supplier, min_score=95)
    assert rows
    for r in rows:
        assert r.relation_type is RelationType.supplier
        assert r.score.total >= 95


def test_filter_by_counterparty_and_direction(snap):
    rows = filter_relationships(snap, object_company="tsmc")
    assert [r.id for r in rows] == ["nvda-tsmc-foundry"]
    assert rows[0].direction is Direction.inbound


def test_filter_returns_empty_rather_than_raising(snap):
    assert filter_relationships(snap, object_company="no-such-company") == []


def test_min_score_zero_is_a_no_op(snap):
    assert len(filter_relationships(snap, min_score=0)) == len(snap.relationships)


def test_published_after_filters_on_newest_evidence(snap):
    cutoff = date(2026, 6, 1)
    rows = filter_relationships(snap, published_after=cutoff)
    assert rows
    for r in rows:
        newest = max((e.published_at for e in r.evidence if e.published_at), default=None)
        assert newest is not None and newest >= cutoff


def test_max_age_days_selects_recent_claims_only(snap):
    rows = filter_relationships(snap, max_age_days=30)
    assert rows
    for r in rows:
        assert r.score.evidence_age_days <= 30
    # A wider window can only ever admit more rows.
    assert len(filter_relationships(snap, max_age_days=365)) >= len(rows)


# --- neighbourhoods ----------------------------------------------------------


def test_one_hop_from_a_supplier_reaches_nvda(snap):
    result = neighbours(snap, "tsmc", hops=1)
    assert result["hop_distances"]["tsmc"] == 0
    assert result["hop_distances"]["nvda"] == 1
    assert set(result["hop_distances"]) == {"tsmc", "nvda"}


def test_two_hops_from_a_supplier_reaches_the_other_suppliers(snap):
    one = neighbours(snap, "tsmc", hops=1)
    two = neighbours(snap, "tsmc", hops=2)
    assert len(two["hop_distances"]) > len(one["hop_distances"])
    # The graph is a star around NVIDIA, so everything sits two hops out.
    assert two["hop_distances"]["micron"] == 2
    assert all(d <= 2 for d in two["hop_distances"].values())


def test_neighbour_nodes_carry_their_distance(snap):
    result = neighbours(snap, "nvda", hops=1)
    by_id = {n["id"]: n["hop_distance"] for n in result["nodes"]}
    assert by_id["nvda"] == 0
    assert by_id["tsmc"] == 1
    assert set(by_id) == set(result["hop_distances"])


def test_neighbour_edges_stay_inside_the_selection(snap):
    result = neighbours(snap, "tsmc", hops=1)
    selected = set(result["hop_distances"])
    for e in result["edges"]:
        assert e["source"] in selected and e["target"] in selected


def test_traversal_is_undirected(snap):
    """Asking from a supplier must reach NVIDIA, even though edges point at it."""
    from_nvda = neighbours(snap, "nvda", hops=1)["hop_distances"]
    from_tsmc = neighbours(snap, "tsmc", hops=1)["hop_distances"]
    assert "tsmc" in from_nvda
    assert "nvda" in from_tsmc


def test_unknown_company_raises_keyerror(snap):
    with pytest.raises(KeyError):
        neighbours(snap, "no-such-company")


# --- shortest path -----------------------------------------------------------


def test_path_to_self_is_zero_hops(snap):
    result = shortest_path(snap, "nvda", "nvda")
    assert result == {"nodes": ["nvda"], "edges": [], "hops": 0}


def test_one_hop_path_between_supplier_and_subject(snap):
    result = shortest_path(snap, "tsmc", "nvda")
    assert result["nodes"] == ["tsmc", "nvda"]
    assert result["hops"] == 1
    assert len(result["edges"]) == 1


def test_two_hop_path_between_two_suppliers(snap):
    result = shortest_path(snap, "tsmc", "micron")
    assert result["nodes"] == ["tsmc", "nvda", "micron"]
    assert result["hops"] == 2
    # One edge per hop, all of them real relationship ids.
    assert len(result["edges"]) == 2


def test_path_is_none_when_max_hops_is_too_small(snap):
    assert shortest_path(snap, "tsmc", "micron", max_hops=1) is None


def test_path_rejects_unknown_companies(snap):
    with pytest.raises(KeyError):
        shortest_path(snap, "tsmc", "no-such-company")
    with pytest.raises(KeyError):
        shortest_path(snap, "no-such-company", "tsmc")


def test_every_pair_of_nodes_is_connected(snap):
    """The shipped graph is a connected star; an disconnected pair would be a
    data problem worth surfacing rather than a silent empty result."""
    ids = sorted(snap.companies)
    for other in ids:
        if other == "nvda":
            continue
        assert shortest_path(snap, "nvda", other) is not None, other


# --- graph export ------------------------------------------------------------


def test_build_graph_shape(snap):
    g = build_graph(snap)
    assert len(g["nodes"]) == len(snap.companies)
    assert len(g["edges"]) == len(snap.relationships)
    assert g["snapshot_date"] == str(snap.snapshot_date)


def test_build_graph_edges_are_displayable(snap):
    g = build_graph(snap)
    ids = {n["id"] for n in g["nodes"]}
    for e in g["edges"]:
        assert e["source"] in ids and e["target"] in ids
        assert isinstance(e["score"], int)
        assert e["status"] in {s.value for s in Status}
