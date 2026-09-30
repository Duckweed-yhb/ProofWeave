"""Command-line interface.

Every query goes through ``proofweave.graph``, the same module the HTTP API
uses, so the CLI and the API can never disagree about what a filter means.

Examples:
    proofweave summary
    proofweave list --type supplier --min-score 80
    proofweave show nvda-tsmc-foundry
    proofweave graph --out graph.json
    proofweave neighbors tsmc --hops 2
    proofweave path tsmc microsoft
    proofweave audit
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import typer

from . import __version__
from .audit import audit_snapshot, stale_relationships
from .data.loader import load_snapshot
from .graph import MAX_HOPS, build_graph, filter_relationships, neighbours, shortest_path
from .models import Direction, RelationType, Status

app = typer.Typer(
    help="ProofWeave -- NVIDIA supply-chain & partnership graph.",
    no_args_is_help=True,
)

_EXIT_BAD_INPUT = 2
_EXIT_NOT_FOUND = 3


def _dump(payload) -> str:
    """One JSON convention for every command, so output stays diffable."""
    return json.dumps(payload, indent=2, default=str, ensure_ascii=False)


@app.command()
def version():
    """Print the installed ProofWeave version."""
    typer.echo(__version__)


@app.command()
def summary():
    """Print a one-line-per-relationship digest."""
    snap = load_snapshot()
    typer.echo(f"ProofWeave {__version__}")
    typer.echo(f"Snapshot: {snap.snapshot_date}  subject: {snap.subject.name} "
               f"({snap.subject.ticker})")
    typer.echo(f"Companies: {len(snap.companies)}   "
               f"Relationships: {len(snap.relationships)}\n")
    for r in snap.relationships:
        score = r.score.total if r.score else "-"
        age = r.score.evidence_age_days if r.score else None
        age_txt = f"{age:>4}d" if age is not None else "   ? "
        typer.echo(f"  [{score:>3}] {age_txt}  {r.relation_type.value:<22} "
                   f"{r.object_company:<12} ({r.status.value:<9})  "
                   f"{r.rationale[:60]}")


@app.command("list")
def list_(
    relation_type: RelationType | None = typer.Option(
        None, "--type", "-t", help="Filter by relation type."),
    status: Status | None = typer.Option(None, help="Filter by status."),
    direction: Direction | None = typer.Option(None, help="Filter by direction."),
    min_score: int = typer.Option(0, min=0, max=100,
                                  help="Only relationships scoring at least this."),
    max_age_days: int | None = typer.Option(
        None, min=0, help="Only evidence at most this many days old."),
    published_after: str | None = typer.Option(
        None, help="Only newest evidence published on/after this YYYY-MM-DD."),
):
    """Filter relationships and print them as JSON."""
    try:
        after = date.fromisoformat(published_after) if published_after else None
    except ValueError:
        typer.secho(f"invalid date {published_after!r}; expected YYYY-MM-DD",
                    fg=typer.colors.RED, err=True)
        raise typer.Exit(code=_EXIT_BAD_INPUT) from None

    snap = load_snapshot()
    rels = filter_relationships(
        snap,
        relation_type=relation_type,
        status=status,
        direction=direction,
        min_score=min_score,
        published_after=after,
        max_age_days=max_age_days,
    )
    typer.echo(_dump([r.model_dump() for r in rels]))


@app.command()
def show(rel_id: str = typer.Argument(..., help="Relationship id.")):
    """Print one relationship with its full evidence list."""
    snap = load_snapshot()
    for r in snap.relationships:
        if r.id == rel_id:
            typer.echo(_dump(r.model_dump()))
            return
    typer.secho(f"no relationship with id {rel_id!r}", fg=typer.colors.RED, err=True)
    raise typer.Exit(code=_EXIT_NOT_FOUND)


@app.command()
def graph(out: Path = typer.Option("graph.json", help="Output path.")):
    """Export the node/edge graph as JSON."""
    snap = load_snapshot()
    out.write_text(_dump(build_graph(snap)), encoding="utf-8")
    typer.echo(f"wrote {out}")


@app.command()
def neighbors(
    company_id: str = typer.Argument(..., help="Company id, e.g. 'tsmc'."),
    hops: int = typer.Option(1, min=1, max=MAX_HOPS,
                             help=f"Traversal depth, 1-{MAX_HOPS}."),
):
    """Print the subgraph within N hops of a company (undirected)."""
    snap = load_snapshot()
    try:
        result = neighbours(snap, company_id, hops)
    except KeyError:
        typer.secho(f"unknown company {company_id!r}", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=_EXIT_NOT_FOUND) from None
    typer.echo(_dump(result))


@app.command()
def path(
    source: str = typer.Argument(..., help="Company id to start from."),
    target: str = typer.Argument(..., help="Company id to reach."),
    max_hops: int = typer.Option(MAX_HOPS, min=1, max=MAX_HOPS),
):
    """Print the shortest undirected path between two companies."""
    snap = load_snapshot()
    try:
        result = shortest_path(snap, source, target, max_hops)
    except KeyError as exc:
        typer.secho(f"unknown company {exc.args[0]!r}", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=_EXIT_NOT_FOUND) from None
    if result is None:
        typer.secho(f"no path from {source!r} to {target!r} within "
                    f"{max_hops} hop{'s' if max_hops != 1 else ''}",
                    fg=typer.colors.RED, err=True)
        raise typer.Exit(code=_EXIT_NOT_FOUND)
    typer.echo(_dump({"source": source, "target": target, **result}))


@app.command()
def audit(
    max_age_days: int = typer.Option(365, min=0,
                                     help="Flag evidence older than this."),
):
    """Self-check the snapshot and list stale evidence.

    Exits non-zero when the snapshot is internally inconsistent, so it can be
    wired into CI as a gate.
    """
    snap = load_snapshot()
    report = audit_snapshot(snap)
    typer.echo(report.format())

    stale_rows = stale_relationships(snap, max_age_days)
    typer.echo(f"\nstale evidence (> {max_age_days} days): {len(stale_rows)}")
    for rel_id, newest, age in stale_rows:
        typer.echo(f"  {age:>5}d  {newest}  {rel_id}")

    if not report.ok:
        raise typer.Exit(code=1)


@app.command()
def stale(
    max_age_days: int = typer.Option(365, min=0),
):
    """List relationships whose newest evidence is older than the limit."""
    snap = load_snapshot()
    rows = stale_relationships(snap, max_age_days)
    typer.echo(_dump([
        {"id": i, "newest_evidence_date": str(d), "age_days": a} for i, d, a in rows
    ]))


if __name__ == "__main__":
    app()
