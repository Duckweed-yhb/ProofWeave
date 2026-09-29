"""HTTP JSON API for the frozen NVIDIA relationship snapshot.

Run with:  uvicorn proofweave.api:app --reload
Everything is served from the on-disk JSON snapshot; no network calls are
made at request time.
"""

from __future__ import annotations

from typing import Optional

from fastapi import Depends, FastAPI, HTTPException, Query
from pydantic import BaseModel

from .data.loader import load_snapshot
from .models import Direction, RelationType, Snapshot, Status

app = FastAPI(
    title="ProofWeave",
    description="Reproducible supply-chain & partnership graph for NVIDIA. Not investment advice.",
    version="0.1.0",
)

_snapshot: Snapshot | None = None


def get_snapshot() -> Snapshot:
    global _snapshot
    if _snapshot is None:
        _snapshot = load_snapshot()
    return _snapshot


class Page(BaseModel):
    total: int
    limit: int
    offset: int
    items: list


@app.get("/health")
def health():
    snap = get_snapshot()
    return {"status": "ok", "snapshot_date": str(snap.snapshot_date),
            "n_relationships": len(snap.relationships),
            "n_companies": len(snap.companies)}


@app.get("/stats")
def stats(snap: Snapshot = Depends(get_snapshot)):
    """One-shot aggregation: counts by relation_type, status, and score bucket."""
    by_type: dict[str, int] = {}
    by_status: dict[str, int] = {}
    score_buckets = {"0-39": 0, "40-69": 0, "70-89": 0, "90-100": 0}
    for r in snap.relationships:
        by_type[r.relation_type.value] = by_type.get(r.relation_type.value, 0) + 1
        by_status[r.status.value] = by_status.get(r.status.value, 0) + 1
        s = r.score.total if r.score else 0
        if s < 40:
            score_buckets["0-39"] += 1
        elif s < 70:
            score_buckets["40-69"] += 1
        elif s < 90:
            score_buckets["70-89"] += 1
        else:
            score_buckets["90-100"] += 1
    return {
        "snapshot_date": str(snap.snapshot_date),
        "n_relationships": len(snap.relationships),
        "n_companies": len(snap.companies),
        "by_relation_type": by_type,
        "by_status": by_status,
        "score_buckets": score_buckets,
    }


@app.get("/companies")
def list_companies(snap: Snapshot = Depends(get_snapshot)):
    return snap.companies


@app.get("/relationships", response_model=Page)
def list_relationships(
    relation_type: Optional[RelationType] = Query(default=None),
    status: Optional[Status] = Query(default=None),
    direction: Optional[Direction] = Query(default=None),
    min_score: int = Query(default=0, ge=0, le=100),
    object_company: Optional[str] = Query(default=None, description="Filter by counterparty company id."),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    snap: Snapshot = Depends(get_snapshot),
):
    rels = snap.relationships
    if relation_type is not None:
        rels = [r for r in rels if r.relation_type == relation_type]
    if status is not None:
        rels = [r for r in rels if r.status == status]
    if direction is not None:
        rels = [r for r in rels if r.direction == direction]
    if object_company is not None:
        rels = [r for r in rels if r.object_company == object_company]
    rels = [r for r in rels if (r.score.total if r.score else 0) >= min_score]

    total = len(rels)
    window = rels[offset:offset + limit]
    return Page(total=total, limit=limit, offset=offset,
                items=[r.model_dump() for r in window])


@app.get("/relationships/{rel_id}")
def get_relationship(rel_id: str, snap: Snapshot = Depends(get_snapshot)):
    for r in snap.relationships:
        if r.id == rel_id:
            return r.model_dump()
    raise HTTPException(status_code=404, detail=f"relationship '{rel_id}' not found")


@app.get("/graph")
def graph(snap: Snapshot = Depends(get_snapshot)):
    """Export a node/edge graph for visualisation."""
    nodes = [c.model_dump() for c in snap.companies.values()]
    edges = [
        {
            "id": r.id,
            "source": r.subject,
            "target": r.object_company,
            "type": r.relation_type.value,
            "direction": r.direction.value,
            "status": r.status.value,
            "score": r.score.total if r.score else None,
        }
        for r in snap.relationships
    ]
    return {"subject": snap.subject.model_dump(),
            "snapshot_date": str(snap.snapshot_date),
            "nodes": nodes, "edges": edges}
