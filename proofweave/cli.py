"""Command-line interface.

Examples:
    proofweave summary
    proofweave list --type supplier --min-score 80
    proofweave show nvda-tsmc-foundry
    proofweave graph --out graph.json
"""

from __future__ import annotations

import json
from pathlib import Path

import typer

from .data.loader import load_snapshot
from .models import Direction, RelationType, Status

app = typer.Typer(help="ProofWeave — NVIDIA supply-chain & partnership graph.")


@app.command()
def summary():
    """Print a one-line-per-relationship digest."""
    snap = load_snapshot()
    typer.echo(f"Snapshot: {snap.snapshot_date}  subject: {snap.subject.name} ({snap.subject.ticker})")
    typer.echo(f"Companies: {len(snap.companies)}   Relationships: {len(snap.relationships)}\n")
    for r in snap.relationships:
        score = r.score.total if r.score else "-"
        typer.echo(f"  [{score:>3}] {r.relation_type.value:<22} {r.object_company:<12} "
                   f"({r.status.value:<9})  {r.rationale[:70]}")


@app.command()
def list(
    type: RelationType = typer.Option(None, help="Filter by relation type."),
    status: Status = typer.Option(None),
    direction: Direction = typer.Option(None),
    min_score: int = typer.Option(0, min=0, max=100),
):
    snap = load_snapshot()
    rels = snap.relationships
    if type:
        rels = [r for r in rels if r.relation_type == type]
    if status:
        rels = [r for r in rels if r.status == status]
    if direction:
        rels = [r for r in rels if r.direction == direction]
    rels = [r for r in rels if (r.score.total if r.score else 0) >= min_score]
    typer.echo(json.dumps([r.model_dump() for r in rels], indent=2, default=str))


@app.command()
def show(rel_id: str):
    snap = load_snapshot()
    for r in snap.relationships:
        if r.id == rel_id:
            typer.echo(json.dumps(r.model_dump(), indent=2, default=str))
            return
    raise typer.Exit(code=3)


@app.command()
def graph(out: Path = typer.Option("graph.json", help="Output path.")):
    snap = load_snapshot()
    payload = {
        "subject": snap.subject.model_dump(),
        "snapshot_date": str(snap.snapshot_date),
        "nodes": [c.model_dump() for c in snap.companies.values()],
        "edges": [
            {"id": r.id, "source": r.subject, "target": r.object_company,
             "type": r.relation_type.value, "status": r.status.value,
             "score": r.score.total if r.score else None}
            for r in snap.relationships
        ],
    }
    out.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
    typer.echo(f"wrote {out}")


if __name__ == "__main__":
    app()
