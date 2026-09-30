"""HTTP-level tests: happy path + edge/error cases."""

from fastapi.testclient import TestClient

from proofweave.api import app

client = TestClient(app)


def test_health():
    r = client.get("/health")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    assert body["n_relationships"] > 10


def test_stats():
    r = client.get("/stats")
    assert r.status_code == 200
    body = r.json()
    assert body["n_relationships"] == client.get("/relationships").json()["total"]
    assert set(body["by_relation_type"].keys()) >= {
        "supplier", "customer", "partner", "investor_or_investee", "peer"
    }
    assert sum(body["score_buckets"].values()) == body["n_relationships"]


def test_list_relationships_default():
    r = client.get("/relationships")
    assert r.status_code == 200
    body = r.json()
    assert body["total"] == len(body["items"])
    assert body["limit"] == 50


def test_filter_by_type():
    r = client.get("/relationships", params={"relation_type": "supplier"})
    assert r.status_code == 200
    items = r.json()["items"]
    assert len(items) >= 5
    assert all(i["relation_type"] == "supplier" for i in items)


def test_filter_min_score():
    r = client.get("/relationships", params={"min_score": 90})
    assert r.status_code == 200
    items = r.json()["items"]
    assert all(i["score"]["total"] >= 90 for i in items)


def test_pagination():
    p1 = client.get("/relationships", params={"limit": 5, "offset": 0}).json()
    p2 = client.get("/relationships", params={"limit": 5, "offset": 5}).json()
    assert len(p1["items"]) == 5
    ids1 = {i["id"] for i in p1["items"]}
    ids2 = {i["id"] for i in p2["items"]}
    assert ids1.isdisjoint(ids2)


def test_get_by_id():
    r = client.get("/relationships/nvda-tsmc-foundry")
    assert r.status_code == 200
    assert r.json()["object_company"] == "tsmc"


def test_404_unknown_id():
    r = client.get("/relationships/does-not-exist")
    assert r.status_code == 404
    assert "not found" in r.json()["detail"]


def test_422_bad_enum():
    """Invalid relation_type must be rejected, not silently ignored."""
    r = client.get("/relationships", params={"relation_type": "banana"})
    assert r.status_code == 422


def test_422_bad_pagination():
    r = client.get("/relationships", params={"limit": 0})
    assert r.status_code == 422
    r = client.get("/relationships", params={"min_score": 150})
    assert r.status_code == 422


def test_graph_shape():
    r = client.get("/graph")
    assert r.status_code == 200
    body = r.json()
    assert "nodes" in body and "edges" in body
    assert body["subject"]["ticker"] == "NVDA"
    assert len(body["edges"]) == client.get("/relationships").json()["total"]


def test_unknown_company_filter():
    """Filtering on a non-existent counterparty returns empty, not 500."""
    r = client.get("/relationships", params={"object_company": "no-such-company"})
    assert r.status_code == 200
    assert r.json()["items"] == []


# --- index / audit / staleness -----------------------------------------------


def test_index_points_at_the_docs():
    r = client.get("/")
    assert r.status_code == 200
    body = r.json()
    assert body["documentation"] == "/docs"
    assert "/relationships" in body["endpoints"]


def test_audit_reports_a_clean_snapshot():
    r = client.get("/audit")
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True
    assert body["n_errors"] == 0
    assert body["checks_run"] > 25


def test_stale_endpoint():
    r = client.get("/stale", params={"max_age_days": 0})
    assert r.status_code == 200
    body = r.json()
    assert body["n_stale"] == len(body["items"])
    assert all(i["age_days"] > 0 for i in body["items"])
    assert client.get("/stale", params={"max_age_days": 3650}).json()["n_stale"] == 0


def test_stale_rejects_negative_age():
    assert client.get("/stale", params={"max_age_days": -1}).status_code == 422


# --- time-dimension filters --------------------------------------------------


def test_max_age_days_filter():
    r = client.get("/relationships", params={"max_age_days": 30})
    assert r.status_code == 200
    items = r.json()["items"]
    assert items
    assert all(i["score"]["evidence_age_days"] <= 30 for i in items)


def test_published_after_filter():
    r = client.get("/relationships", params={"published_after": "2026-06-01"})
    assert r.status_code == 200
    items = r.json()["items"]
    assert items
    assert all(i["score"]["newest_evidence_date"] >= "2026-06-01" for i in items)


def test_future_cutoff_returns_nothing():
    r = client.get("/relationships", params={"published_after": "2999-01-01"})
    assert r.status_code == 200
    assert r.json()["total"] == 0


def test_malformed_date_is_rejected():
    r = client.get("/relationships", params={"published_after": "yesterday"})
    assert r.status_code == 422


# --- traversal ---------------------------------------------------------------


def test_neighbours_of_a_supplier():
    r = client.get("/graph/neighbors/tsmc")
    assert r.status_code == 200
    body = r.json()
    assert body["hop_distances"] == {"tsmc": 0, "nvda": 1}
    assert {n["id"] for n in body["nodes"]} == {"tsmc", "nvda"}
    assert all(n["hop_distance"] <= body["hops"] for n in body["nodes"])


def test_neighbours_two_hops_widens_the_subgraph():
    one = client.get("/graph/neighbors/tsmc", params={"hops": 1}).json()
    two = client.get("/graph/neighbors/tsmc", params={"hops": 2}).json()
    assert len(two["nodes"]) > len(one["nodes"])


def test_neighbours_404_for_unknown_company():
    r = client.get("/graph/neighbors/no-such-company")
    assert r.status_code == 404
    assert "not found" in r.json()["detail"]


def test_neighbours_rejects_hops_beyond_the_cap():
    assert client.get("/graph/neighbors/nvda", params={"hops": 99}).status_code == 422
    assert client.get("/graph/neighbors/nvda", params={"hops": 0}).status_code == 422


def test_path_between_two_suppliers():
    r = client.get("/graph/path", params={"source": "tsmc", "target": "micron"})
    assert r.status_code == 200
    body = r.json()
    assert body["nodes"] == ["tsmc", "nvda", "micron"]
    assert body["hops"] == 2
    assert len(body["edges"]) == 2


def test_path_to_self():
    r = client.get("/graph/path", params={"source": "nvda", "target": "nvda"})
    assert r.status_code == 200
    assert r.json()["hops"] == 0


def test_path_404_when_unreachable_within_max_hops():
    r = client.get("/graph/path",
                   params={"source": "tsmc", "target": "micron", "max_hops": 1})
    assert r.status_code == 404


def test_path_404_for_unknown_company():
    assert client.get("/graph/path",
                      params={"source": "nope", "target": "nvda"}).status_code == 404
    assert client.get("/graph/path",
                      params={"source": "nvda", "target": "nope"}).status_code == 404


def test_path_requires_both_parameters():
    assert client.get("/graph/path", params={"source": "nvda"}).status_code == 422


def test_graph_path_is_not_shadowed_by_the_neighbors_route():
    """Both live under /graph; neither may swallow the other."""
    assert client.get("/graph/path", params={"source": "nvda", "target": "tsmc"}).status_code == 200
    assert client.get("/graph/neighbors/nvda").status_code == 200
