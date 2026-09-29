"""Sanity checks on the frozen snapshot itself."""

from proofweave.models import RelationType


def test_snapshot_loads(snap):
    assert snap.subject.id == "nvda"
    assert snap.subject.ticker == "NVDA"
    assert snap.snapshot_date.isoformat() == "2026-09-29"


def test_at_least_five_relation_types_covered(snap):
    types = {r.relation_type for r in snap.relationships}
    # Challenge requires supplier, customer, partner, investor_or_investee, peer.
    expected = {RelationType.supplier, RelationType.customer, RelationType.partner,
                RelationType.investor_or_investee, RelationType.peer}
    assert expected.issubset(types), f"missing types: {expected - types}"


def test_every_relationship_has_score_in_range(snap):
    for r in snap.relationships:
        assert r.score is not None, f"{r.id} missing score"
        assert 0 <= r.score.total <= 100


def test_every_relationship_has_at_least_one_evidence(snap):
    for r in snap.relationships:
        assert len(r.evidence) >= 1, f"{r.id} has no evidence"
        for e in r.evidence:
            assert str(e.url).startswith("http"), f"{r.id} bad evidence url"
            assert e.publisher
            assert e.locator


def test_anonymous_customers_stay_unknown(snap):
    """Boundary case: 10-K anonymous customers must NOT be upgraded to confirmed."""
    anon = [r for r in snap.relationships if r.object_company == "unknown"]
    assert len(anon) == 1
    assert anon[0].status.value == "unknown"


def test_all_object_companies_exist(snap):
    ids = set(snap.companies.keys())
    for r in snap.relationships:
        assert r.object_company in ids, f"{r.id} references unknown company {r.object_company}"


def test_graph_has_no_dangling_edges(snap):
    """Every edge target/source must resolve to a node (no dangling refs)."""
    ids = set(snap.companies.keys())
    for r in snap.relationships:
        assert r.subject in ids
        assert r.object_company in ids
