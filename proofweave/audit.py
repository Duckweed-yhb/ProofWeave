"""Self-audit for the shipped snapshot.

The project's central claim is that a reviewer can re-derive every number in it.
``audit_snapshot`` turns that claim into something runnable: it re-checks the
structural invariants of the data and, most importantly, recomputes every score
from the evidence and compares it against what was loaded.  If someone ever
hand-edits a score into the JSON -- or the scoring formula drifts away from the
numbers in the README -- this reports it instead of shipping it.

Findings are graded ``error`` (the snapshot is internally inconsistent and the
claim it makes is false) or ``warning`` (defensible but worth a human look).
"""

from __future__ import annotations

from datetime import date

from pydantic import BaseModel, Field

from .models import RelationType, Snapshot
from .scoring import newest_evidence_date, score_relationship

_REQUIRED_TYPES = set(RelationType)


class AuditFinding(BaseModel):
    check: str
    severity: str = Field(description="'error' or 'warning'.")
    message: str
    subject: str | None = Field(
        default=None, description="Relationship or company id the finding is about."
    )


class AuditReport(BaseModel):
    ok: bool = Field(description="True when no check produced an error.")
    checks_run: int
    n_errors: int
    n_warnings: int
    findings: list[AuditFinding]

    def format(self) -> str:
        lines = [
            f"checks run : {self.checks_run}",
            f"errors     : {self.n_errors}",
            f"warnings   : {self.n_warnings}",
            f"verdict    : {'OK' if self.ok else 'FAILED'}",
        ]
        for f in self.findings:
            where = f" [{f.subject}]" if f.subject else ""
            lines.append(f"  {f.severity.upper():<7} {f.check}{where}: {f.message}")
        return "\n".join(lines)


class _Collector:
    """Accumulates findings while counting how many checks actually ran."""

    def __init__(self) -> None:
        self.findings: list[AuditFinding] = []
        self.checks = 0

    def check(self, name: str, ok: bool, message: str,
              subject: str | None = None, severity: str = "error") -> bool:
        self.checks += 1
        if not ok:
            self.findings.append(AuditFinding(
                check=name, severity=severity, message=message, subject=subject))
        return ok


def audit_snapshot(snap: Snapshot) -> AuditReport:
    """Run every structural and arithmetic check against a loaded snapshot."""
    c = _Collector()
    companies = snap.companies

    # --- identity / structure -------------------------------------------------
    for rel in snap.relationships:
        if rel.subject not in companies or rel.object_company not in companies:
            c.check(
                "dangling_edge", False,
                f"references unknown company(s): subject={rel.subject!r} "
                f"object={rel.object_company!r}", rel.id,
            )
        else:
            c.checks += 1

    ids = [r.id for r in snap.relationships]
    dupes = sorted({i for i in ids if ids.count(i) > 1})
    c.check("unique_relationship_ids", not dupes,
            f"duplicate relationship ids: {dupes}")

    mismatched = [cid for cid, comp in companies.items() if comp.id != cid]
    c.check("company_keys_match_ids", not mismatched,
            f"company dict keys disagree with Company.id: {mismatched}")

    subjects = {r.subject for r in snap.relationships}
    c.check("subject_is_the_snapshot_subject",
            subjects <= {snap.subject.id},
            f"relationships use subjects outside the focal company: "
            f"{sorted(subjects - {snap.subject.id})}", severity="warning")

    # --- evidence -------------------------------------------------------------
    for rel in snap.relationships:
        if not rel.evidence:
            c.check("evidence_present", False, "relationship has no evidence", rel.id)
            continue
        c.checks += 1
        for ev in rel.evidence:
            url = str(ev.url)
            if not url.startswith(("http://", "https://")):
                c.check("evidence_url_scheme", False,
                        f"non-HTTP evidence url {url!r}", rel.id)
            elif not ev.publisher or not ev.locator:
                c.check("evidence_attribution", False,
                        f"evidence {url!r} lacks publisher or locator", rel.id)
            else:
                c.checks += 1
            if ev.published_at and ev.published_at > ev.accessed_at:
                c.check("published_before_accessed", False,
                        f"evidence {url!r} was accessed before it was published "
                        f"({ev.accessed_at} < {ev.published_at})", rel.id,
                        severity="warning")
            else:
                c.checks += 1
            if ev.published_at and ev.published_at > snap.snapshot_date:
                c.check("no_future_evidence", False,
                        f"evidence {url!r} is published after the snapshot date "
                        f"({ev.published_at})", rel.id, severity="warning")

    # --- scores are derived, never stored ------------------------------------
    stored_vs_derived: list[str] = []
    for rel in snap.relationships:
        if rel.score is None:
            c.check("score_present", False, "relationship has no score", rel.id)
            continue
        c.checks += 1
        expected = score_relationship(rel)
        if rel.score.model_dump() != expected.model_dump():
            stored_vs_derived.append(rel.id)
        if not 0 <= rel.score.total <= 100:
            c.check("score_in_range", False,
                    f"score {rel.score.total} outside 0-100", rel.id)
        else:
            c.checks += 1
    c.check("scores_are_derived_not_typed",
            not stored_vs_derived,
            "these relationships carry a score that does not match the scoring "
            f"formula recomputed from their evidence: {stored_vs_derived}")

    # --- the score must actually discriminate --------------------------------
    bonuses = {r.score.recency_bonus for r in snap.relationships if r.score}
    c.check("recency_term_discriminates", len(bonuses) > 1,
            "the recency bonus is identical for every relationship, so the term "
            "is not measuring evidence freshness", severity="warning")

    # --- time consistency -----------------------------------------------------
    off_as_of = [r.id for r in snap.relationships if r.as_of != snap.snapshot_date]
    c.check("as_of_matches_snapshot", not off_as_of,
            f"relationships dated differently from the snapshot: {off_as_of}",
            severity="warning")

    for rel in snap.relationships:
        newest = newest_evidence_date(rel)
        if newest > rel.as_of:
            c.check("evidence_not_after_as_of", False,
                    f"newest evidence {newest} post-dates as_of {rel.as_of}", rel.id,
                    severity="warning")
        else:
            c.checks += 1

    # --- coverage -------------------------------------------------------------
    covered = {r.relation_type for r in snap.relationships}
    c.check("all_relation_types_covered", _REQUIRED_TYPES <= covered,
            f"snapshot is missing relation types: "
            f"{sorted(t.value for t in _REQUIRED_TYPES - covered)}",
            severity="warning")

    unknowns = [r.id for r in snap.relationships if r.status.value == "unknown"]
    c.check("unknown_rows_are_labelled", bool(unknowns),
            "no relationship carries the deliberately-unknown status; the "
            "anonymous-customer boundary case is expected to be present",
            severity="warning")

    n_errors = sum(1 for f in c.findings if f.severity == "error")
    n_warnings = sum(1 for f in c.findings if f.severity == "warning")
    return AuditReport(
        ok=n_errors == 0,
        checks_run=c.checks,
        n_errors=n_errors,
        n_warnings=n_warnings,
        findings=c.findings,
    )


def stale_relationships(snap: Snapshot, max_age_days: int) -> list[tuple[str, date, int]]:
    """(id, newest evidence date, age in days) for claims older than the limit."""
    out = []
    for rel in snap.relationships:
        newest = newest_evidence_date(rel)
        age = (snap.snapshot_date - newest).days
        if age > max_age_days:
            out.append((rel.id, newest, age))
    return sorted(out, key=lambda row: row[2], reverse=True)
