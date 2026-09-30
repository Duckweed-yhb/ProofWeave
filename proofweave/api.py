"""HTTP JSON API for the frozen NVIDIA relationship snapshot.

Run with:  uvicorn proofweave.api:app --reload
Everything is served from the on-disk JSON snapshot; no network calls are
made at request time.

Query logic lives in ``proofweave.graph`` and the snapshot audit in
``proofweave.audit`` so that the CLI and this API answer identically.
"""

from __future__ import annotations

from datetime import date
from functools import lru_cache

from fastapi import Depends, FastAPI, HTTPException, Query
from pydantic import BaseModel, Field

from . import __version__
from .audit import AuditReport, audit_snapshot, stale_relationships
from .data.loader import load_snapshot
from .graph import MAX_HOPS, build_graph, filter_relationships, neighbours, shortest_path
from .models import Company, Direction, RelationType, Relationship, Snapshot, Status

app = FastAPI(
    title="ProofWeave",
    description=(
        "Reproducible supply-chain & partnership graph for NVIDIA. "
        "Every relationship is scored, sourced and traceable. "
        "Research snapshot only -- not investment advice."
    ),
    version=__version__,
)


@lru_cache(maxsize=1)
def get_snapshot() -> Snapshot:
    """Load the shipped snapshot once per process."""
    return load_snapshot()


# --- response models ---------------------------------------------------------
# Declared explicitly (rather than returning bare dicts) so that the OpenAPI
# schema at /docs documents the real shape for a reviewer.


class Index(BaseModel):
    name: str
    version: str
    documentation: str
    snapshot_date: date
    endpoints: list[str]


class Health(BaseModel):
    status: str
    version: str
    snapshot_date: date
    n_relationships: int
    n_companies: int


class Stats(BaseModel):
    snapshot_date: date
    n_relationships: int
    n_companies: int
    by_relation_type: dict[str, int]
    by_status: dict[str, int]
    score_buckets: dict[str, int]
    newest_evidence_date: date
    oldest_evidence_date: date


class Page(BaseModel):
    total: int = Field(description="Total matches before limit/offset.")
    limit: int
    offset: int
    items: list[Relationship]


class Edge(BaseModel):
    id: str
    source: str
    target: str
    type: str
    direction: str
    status: str
    score: int | None = None


class GraphOut(BaseModel):
    subject: Company
    snapshot_date: date
    nodes: list[Company]
    edges: list[Edge]


class NeighborNode(Company):
    hop_distance: int = 0


class NeighborsOut(BaseModel):
    company: Company
    hops: int
    snapshot_date: date
    nodes: list[NeighborNode]
    edges: list[Edge]
    hop_distances: dict[str, int]


class PathOut(BaseModel):
    source: str
    target: str
    hops: int
    nodes: list[str]
    edges: list[Edge]


class StaleRow(BaseModel):
    id: str
    newest_evidence_date: date
    age_days: int


class StaleOut(BaseModel):
    max_age_days: int
    snapshot_date: date
    n_stale: int
    items: list[StaleRow]


# --- routes ------------------------------------------------------------------


@app.get("/", response_model=Index)
def index(snap: Snapshot = Depends(get_snapshot)):
    """Entry point listing the available endpoints."""
    return Index(
        name="ProofWeave",
        version=__version__,
        documentation="/docs",
        snapshot_date=snap.snapshot_date,
        endpoints=[
            "/health", "/stats", "/audit", "/companies", "/relationships",
            "/relationships/{id}", "/graph", "/graph/neighbors/{company_id}",
            "/graph/path", "/stale",
        ],
    )


@app.get("/health", response_model=Health)
def health(snap: Snapshot = Depends(get_snapshot)):
    return Health(
        status="ok",
        version=__version__,
        snapshot_date=snap.snapshot_date,
        n_relationships=len(snap.relationships),
        n_companies=len(snap.companies),
    )


@app.get("/stats", response_model=Stats)
def stats(snap: Snapshot = Depends(get_snapshot)):
    """One-shot aggregation: counts by relation_type, status, and score bucket."""
    by_type: dict[str, int] = {}
    by_status: dict[str, int] = {}
    score_buckets = {"0-39": 0, "40-69": 0, "70-89": 0, "90-100": 0}
    ages: list[date] = []
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
        if r.score and r.score.newest_evidence_date:
            ages.append(r.score.newest_evidence_date)
    return Stats(
        snapshot_date=snap.snapshot_date,
        n_relationships=len(snap.relationships),
        n_companies=len(snap.companies),
        by_relation_type=by_type,
        by_status=by_status,
        score_buckets=score_buckets,
        newest_evidence_date=max(ages) if ages else snap.snapshot_date,
        oldest_evidence_date=min(ages) if ages else snap.snapshot_date,
    )


@app.get("/audit", response_model=AuditReport)
def audit(snap: Snapshot = Depends(get_snapshot)):
    """Self-check the snapshot: structure, evidence, and score reproducibility."""
    return audit_snapshot(snap)


@app.get("/stale", response_model=StaleOut)
def stale(
    max_age_days: int = Query(default=365, ge=0, le=3650),
    snap: Snapshot = Depends(get_snapshot),
):
    """Relationships whose newest evidence is older than ``max_age_days``."""
    rows = stale_relationships(snap, max_age_days)
    return StaleOut(
        max_age_days=max_age_days,
        snapshot_date=snap.snapshot_date,
        n_stale=len(rows),
        items=[StaleRow(id=i, newest_evidence_date=d, age_days=a) for i, d, a in rows],
    )


@app.get("/companies")
def list_companies(snap: Snapshot = Depends(get_snapshot)) -> dict[str, Company]:
    return snap.companies


@app.get("/relationships", response_model=Page)
def list_relationships(
    relation_type: RelationType | None = Query(default=None),
    status: Status | None = Query(default=None),
    direction: Direction | None = Query(default=None),
    min_score: int = Query(default=0, ge=0, le=100),
    object_company: str | None = Query(
        default=None, description="Filter by counterparty company id."),
    published_after: date | None = Query(
        default=None,
        description="Keep only relationships whose newest evidence was published "
                    "on or after this date."),
    max_age_days: int | None = Query(
        default=None, ge=0,
        description="Keep only relationships whose newest evidence is at most "
                    "this many days older than the snapshot date."),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    snap: Snapshot = Depends(get_snapshot),
):
    rels = filter_relationships(
        snap,
        relation_type=relation_type,
        status=status,
        direction=direction,
        object_company=object_company,
        min_score=min_score,
        published_after=published_after,
        max_age_days=max_age_days,
    )
    total = len(rels)
    return Page(total=total, limit=limit, offset=offset,
                items=rels[offset:offset + limit])


@app.get("/relationships/{rel_id}", response_model=Relationship)
def get_relationship(rel_id: str, snap: Snapshot = Depends(get_snapshot)):
    for r in snap.relationships:
        if r.id == rel_id:
            return r
    raise HTTPException(status_code=404, detail=f"relationship '{rel_id}' not found")


@app.get("/graph", response_model=GraphOut)
def graph(snap: Snapshot = Depends(get_snapshot)):
    """Export a node/edge graph for visualisation."""
    return build_graph(snap)


@app.get("/graph/path", response_model=PathOut)
def graph_path(
    source: str = Query(description="Company id to start from."),
    target: str = Query(description="Company id to reach."),
    max_hops: int = Query(default=MAX_HOPS, ge=1, le=MAX_HOPS),
    snap: Snapshot = Depends(get_snapshot),
):
    """Shortest undirected path between two companies."""
    try:
        result = shortest_path(snap, source, target, max_hops)
    except KeyError as exc:
        raise HTTPException(
            status_code=404, detail=f"company '{exc.args[0]}' not found") from None
    if result is None:
        raise HTTPException(
            status_code=404,
            detail=f"no path from '{source}' to '{target}' within "
                   f"{max_hops} hop{'s' if max_hops != 1 else ''}")
    return PathOut(source=source, target=target, **result)


@app.get("/graph/neighbors/{company_id}", response_model=NeighborsOut)
def graph_neighbors(
    company_id: str,
    hops: int = Query(default=1, ge=1, le=MAX_HOPS,
                      description=f"Traversal depth, 1-{MAX_HOPS}."),
    snap: Snapshot = Depends(get_snapshot),
):
    """The subgraph within ``hops`` of a company (undirected traversal)."""
    try:
        return neighbours(snap, company_id, hops)
    except KeyError:
        raise HTTPException(
            status_code=404, detail=f"company '{company_id}' not found") from None
