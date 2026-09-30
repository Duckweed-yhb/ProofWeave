"""Tests for the snapshot self-audit.

The audit exists to make a claim checkable, so the important tests are the ones
that prove it *fails* when the data is wrong -- an audit that always says "ok"
is worse than none.
"""

from datetime import date, timedelta

from proofweave.audit import audit_snapshot, stale_relationships
from proofweave.models import ScoreBreakdown
from proofweave.scoring import score_relationship


def _finding_checks(report, severity=None):
    return {f.check for f in report.findings
            if severity is None or f.severity == severity}


def test_shipped_snapshot_passes_audit(snap):
    report = audit_snapshot(snap)
    assert report.ok, report.format()
    assert report.n_errors == 0
    assert report.checks_run > 25


def test_shipped_snapshot_has_no_warnings(snap):
    """Warnings are meant to be a signal; a noisy audit gets ignored."""
    report = audit_snapshot(snap)
    assert report.n_warnings == 0, report.format()


def test_shipped_snapshot_is_actually_re_scored_on_load(snap):
    """Scores come from the formula, not from the JSON on disk."""
    for rel in snap.relationships:
        assert rel.score.model_dump() == score_relationship(rel).model_dump()


# --- the audit must actually fail when the data is wrong ---------------------


def test_audit_detects_a_hand_typed_score(fresh_snap, tamper):
    """The whole point: a score that does not match the formula must be caught."""
    corrupted = tamper(
        fresh_snap, 0,
        score=ScoreBreakdown(base=70, total=99, rationale="hand written"),
    )
    report = audit_snapshot(corrupted)

    assert not report.ok
    assert "scores_are_derived_not_typed" in _finding_checks(report, "error")


def test_audit_accepts_a_correctly_derived_score(fresh_snap, tamper):
    """Guard against a false positive: re-deriving must not itself trip the check."""
    rel = fresh_snap.relationships[0]
    report = audit_snapshot(tamper(fresh_snap, 0, score=score_relationship(rel)))
    assert "scores_are_derived_not_typed" not in _finding_checks(report)


def test_audit_detects_a_dangling_edge(fresh_snap, tamper):
    report = audit_snapshot(tamper(fresh_snap, 0, object_company="no-such-company"))
    assert "dangling_edge" in _finding_checks(report, "error")


def test_audit_detects_duplicate_relationship_ids(fresh_snap, tamper):
    corrupted = tamper(fresh_snap, 1, id=fresh_snap.relationships[0].id)
    report = audit_snapshot(corrupted)
    assert "unique_relationship_ids" in _finding_checks(report, "error")


def test_audit_detects_a_relationship_without_evidence(fresh_snap, tamper):
    report = audit_snapshot(tamper(fresh_snap, 0, evidence=[]))
    assert "evidence_present" in _finding_checks(report, "error")


def test_audit_detects_a_missing_score(fresh_snap, tamper):
    report = audit_snapshot(tamper(fresh_snap, 0, score=None))
    assert "score_present" in _finding_checks(report, "error")


def test_audit_detects_evidence_accessed_before_publication(fresh_snap, tamper):
    rel = fresh_snap.relationships[0]
    bad = rel.evidence[0].model_copy(
        update={"published_at": rel.evidence[0].accessed_at + timedelta(days=1)})
    report = audit_snapshot(tamper(fresh_snap, 0, evidence=[bad, *rel.evidence[1:]]))
    assert "published_before_accessed" in _finding_checks(report, "warning")


def test_audit_detects_evidence_without_attribution(fresh_snap, tamper):
    rel = fresh_snap.relationships[0]
    bad = rel.evidence[0].model_copy(update={"locator": ""})
    report = audit_snapshot(tamper(fresh_snap, 0, evidence=[bad, *rel.evidence[1:]]))
    assert "evidence_attribution" in _finding_checks(report, "error")


def test_audit_warns_when_recency_stops_discriminating(fresh_snap, rescore):
    """The regression that started all this: a constant term is a dead term."""
    rels = [
        r.model_copy(update={
            "evidence": [e.model_copy(update={"published_at": date(2026, 9, 1)})
                         for e in r.evidence],
        })
        for r in fresh_snap.relationships
    ]
    # Re-score first: otherwise the audit reports the stale scores instead.
    corrupted = rescore(fresh_snap.model_copy(update={"relationships": rels}))
    report = audit_snapshot(corrupted)
    assert "recency_term_discriminates" in _finding_checks(report, "warning")


def test_audit_detects_as_of_drift(fresh_snap, tamper):
    report = audit_snapshot(
        tamper(fresh_snap, 0, as_of=fresh_snap.snapshot_date - timedelta(days=1)))
    assert "as_of_matches_snapshot" in _finding_checks(report, "warning")


def test_report_format_is_human_readable(snap):
    text = audit_snapshot(snap).format()
    assert "verdict" in text
    assert "OK" in text


# --- staleness ---------------------------------------------------------------


def test_stale_relationships_respects_the_threshold(snap):
    assert stale_relationships(snap, 10_000) == []
    rows = stale_relationships(snap, 0)
    assert rows, "some evidence must be older than the snapshot date"
    # Sorted oldest first, and every age is a real age.
    assert [a for _, _, a in rows] == sorted((a for _, _, a in rows), reverse=True)
    for rel_id, newest, age in rows:
        assert age == (snap.snapshot_date - newest).days
        assert age > 0


def test_stale_relationships_agrees_with_the_filter(snap):
    from proofweave.graph import filter_relationships

    limit = 200
    stale_ids = {rel_id for rel_id, _, _ in stale_relationships(snap, limit)}
    kept = {r.id for r in filter_relationships(snap, max_age_days=limit)}
    assert stale_ids.isdisjoint(kept)
    assert stale_ids | kept == {r.id for r in snap.relationships}
