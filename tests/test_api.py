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
