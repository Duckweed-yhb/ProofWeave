"""Shared read-model helpers for the HTTP API and the CLI.

Both surfaces expose the same queries over the same frozen snapshot.  Keeping
the logic here instead of duplicating it in ``api.py`` and ``cli.py`` means the
two cannot drift apart: a filter or traversal added for one is automatically
available to the other, and there is a single place to test it.

Traversal treats the relationship graph as **undirected**.  That is the useful
reading of a supply-chain graph -- "who is connected to TSMC" should reach
NVIDIA whether the stored edge runs inbound or outbound -- while the stored
``direction`` field still carries the directional meaning for display.
"""

from __future__ import annotations

from collections import deque
from datetime import date

from .models import Direction, Relationship, RelationType, Snapshot, Status
from .scoring import newest_evidence_date

MAX_HOPS = 3


def filter_relationships(
    snap: Snapshot,
    *,
    relation_type: RelationType | None = None,
    status: Status | None = None,
    direction: Direction | None = None,
    object_company: str | None = None,
    min_score: int = 0,
    published_after: date | None = None,
    max_age_days: int | None = None,
) -> list[Relationship]:
    """Filter the snapshot's relationships.

    ``published_after`` and ``max_age_days`` are the two time dimensions the
    snapshot can honestly support.  Every relationship carries the same
    ``as_of`` (a single frozen snapshot), so an "as of arbitrary date" query
    would be vacuous here; what *does* vary is how recent each claim's evidence
    is, which is what these two parameters select on.
    """
    rels = snap.relationships
    if relation_type is not None:
        rels = [r for r in rels if r.relation_type is relation_type]
    if status is not None:
        rels = [r for r in rels if r.status is status]
    if direction is not None:
        rels = [r for r in rels if r.direction is direction]
    if object_company is not None:
        rels = [r for r in rels if r.object_company == object_company]
    if min_score > 0:
        rels = [r for r in rels if (r.score.total if r.score else 0) >= min_score]
    if published_after is not None:
        rels = [r for r in rels if newest_evidence_date(r) >= published_after]
    if max_age_days is not None:
        rels = [
            r for r in rels
            if (snap.snapshot_date - newest_evidence_date(r)).days <= max_age_days
        ]
    return list(rels)


def edge_view(rel: Relationship) -> dict:
    """The compact edge projection shared by every graph-shaped response."""
    return {
        "id": rel.id,
        "source": rel.subject,
        "target": rel.object_company,
        "type": rel.relation_type.value,
        "direction": rel.direction.value,
        "status": rel.status.value,
        "score": rel.score.total if rel.score else None,
    }


def build_graph(snap: Snapshot) -> dict:
    """Full node/edge export, for visualisation."""
    return {
        "subject": snap.subject.model_dump(),
        "snapshot_date": str(snap.snapshot_date),
        "nodes": [c.model_dump() for c in snap.companies.values()],
        "edges": [edge_view(r) for r in snap.relationships],
    }


def _adjacency(snap: Snapshot) -> dict[str, set[str]]:
    """Undirected adjacency map over the relationship edges."""
    adj: dict[str, set[str]] = {cid: set() for cid in snap.companies}
    for r in snap.relationships:
        # Self-loops or dangling endpoints would corrupt traversal; the audit
        # command reports those separately, so skip them defensively here.
        if r.subject == r.object_company:
            continue
        if r.subject in adj and r.object_company in adj:
            adj[r.subject].add(r.object_company)
            adj[r.object_company].add(r.subject)
    return adj


def _distances(adj: dict[str, set[str]], start: str, max_hops: int) -> dict[str, int]:
    """Breadth-first hop distances from ``start``, capped at ``max_hops``."""
    seen = {start: 0}
    queue: deque[str] = deque([start])
    while queue:
        node = queue.popleft()
        if seen[node] >= max_hops:
            continue
        for nxt in sorted(adj.get(node, ())):
            if nxt not in seen:
                seen[nxt] = seen[node] + 1
                queue.append(nxt)
    return seen


def neighbours(snap: Snapshot, company_id: str, hops: int = 1) -> dict:
    """The induced subgraph within ``hops`` of ``company_id``.

    Raises ``KeyError`` for an unknown company so callers can map it to a 404 /
    non-zero exit rather than silently returning an empty graph.
    """
    if company_id not in snap.companies:
        raise KeyError(company_id)

    adj = _adjacency(snap)
    dist = _distances(adj, company_id, hops)
    selected = set(dist)

    return {
        "company": snap.companies[company_id].model_dump(),
        "hops": hops,
        "snapshot_date": str(snap.snapshot_date),
        "nodes": [
            {**snap.companies[cid].model_dump(), "hop_distance": dist[cid]}
            for cid in sorted(selected, key=lambda c: (dist[c], c))
        ],
        "edges": [
            edge_view(r) for r in snap.relationships
            if r.subject in selected and r.object_company in selected
        ],
        "hop_distances": dict(sorted(dist.items(), key=lambda kv: (kv[1], kv[0]))),
    }


def shortest_path(
    snap: Snapshot, source: str, target: str, max_hops: int = MAX_HOPS
) -> dict | None:
    """Shortest undirected path between two companies, or ``None`` if none exists.

    Returns ``{"nodes": [...ids...], "edges": [...], "hops": n}``.  A company
    trivially reaches itself with a zero-hop path.
    """
    for cid in (source, target):
        if cid not in snap.companies:
            raise KeyError(cid)

    if source == target:
        return {"nodes": [source], "edges": [], "hops": 0}

    adj = _adjacency(snap)
    parent: dict[str, str] = {source: source}
    depth: dict[str, int] = {source: 0}
    queue: deque[str] = deque([source])
    while queue:
        node = queue.popleft()
        if depth[node] >= max_hops:
            continue
        for nxt in sorted(adj.get(node, ())):
            if nxt in parent:
                continue
            parent[nxt] = node
            depth[nxt] = depth[node] + 1
            if nxt == target:
                return _reconstruct(snap, parent, source, target)
            queue.append(nxt)
    return None


def _reconstruct(snap: Snapshot, parent: dict[str, str], source: str, target: str) -> dict:
    """Turn a BFS parent chain into an explicit node id list plus its edges."""
    chain = [target]
    while chain[-1] != source:
        chain.append(parent[chain[-1]])
    chain.reverse()

    pairs = list(zip(chain, chain[1:]))
    edges = [
        edge_view(r) for r in snap.relationships
        if (r.subject, r.object_company) in pairs or (r.object_company, r.subject) in pairs
    ]
    return {"nodes": chain, "edges": edges, "hops": len(chain) - 1}
