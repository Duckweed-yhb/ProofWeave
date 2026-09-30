"""Unit tests for the explainable scoring engine."""

from datetime import date, timedelta

from proofweave.models import (
    Direction, Evidence, Relationship, RelationType, Status,
)
from proofweave.scoring import _evidence_date, newest_evidence_date, score_relationship

SNAPSHOT = date(2026, 9, 29)


def _mk(status: Status, n_publishers: int = 2, has_quant: bool = False,
        published: date | None = date(2026, 1, 1),
        accessed: date | None = SNAPSHOT,
        as_of: date = SNAPSHOT) -> Relationship:
    evs = []
    for i in range(n_publishers):
        evs.append(Evidence(
            url=f"https://example.com/{i}",
            publisher=f"pub-{i}",
            published_at=published,
            accessed_at=accessed,
            locator="somewhere",
        ))
    return Relationship(
        id="x", subject="nvda", object_company="tsmc",
        relation_type=RelationType.supplier, direction=Direction.inbound,
        status=status, as_of=as_of,
        rationale="t", evidence=evs,
        quantitative_note="19%" if has_quant else None,
    )


def test_confirmed_beats_inferred_beats_unknown():
    s_conf = score_relationship(_mk(Status.confirmed)).total
    s_inf = score_relationship(_mk(Status.inferred)).total
    s_unk = score_relationship(_mk(Status.unknown)).total
    assert s_conf > s_inf > s_unk


def test_more_evidence_raises_score():
    few = score_relationship(_mk(Status.confirmed, n_publishers=1)).total
    many = score_relationship(_mk(Status.confirmed, n_publishers=5)).total
    assert many > few


def test_quantitative_anchor_adds_points():
    s = score_relationship(_mk(Status.confirmed, has_quant=True))
    assert s.quantitative_bonus == 8
    # Clamped at 100, but the additive term must be recorded transparently.
    assert s.total <= 100


def test_unknown_is_penalised():
    s = score_relationship(_mk(Status.unknown, n_publishers=2))
    assert s.penalty == -20
    assert s.total <= 50  # unknown should never look high-confidence


def test_score_clamped_to_100():
    rel = _mk(Status.confirmed, n_publishers=5, has_quant=True)
    s = score_relationship(rel)
    assert s.total <= 100
    assert s.total >= 0


# --- recency: measured on publication date, not on access date ---------------
#
# Regression guard.  The recency term used to be derived from `accessed_at`.
# In a frozen snapshot every source is accessed on (almost) the same day, so
# every relationship collected the identical bonus and the term carried no
# information at all.  These tests pin the term to `published_at`.


def test_recency_uses_published_at_not_accessed_at():
    """A source written two years ago is not 'fresh' just because we read it today."""
    old = score_relationship(_mk(
        Status.confirmed, published=date(2024, 1, 1), accessed=SNAPSHOT))
    new = score_relationship(_mk(
        Status.confirmed, published=date(2026, 9, 1), accessed=SNAPSHOT))
    # Same accessed_at for both, so any difference must come from published_at.
    assert old.recency_bonus < new.recency_bonus
    assert old.total < new.total


def test_recency_bonus_table():
    """Age buckets must be 10 / 6 / 3 / 0 at 180 / 365 / 730 / beyond."""
    def bonus_for(age: int) -> int:
        # SNAPSHOT minus `age` days, expressed via a published date.
        return score_relationship(_mk(
            Status.confirmed, published=SNAPSHOT - timedelta(days=age))
        ).recency_bonus

    assert bonus_for(1) == 10
    assert bonus_for(180) == 10        # boundary is inclusive
    assert bonus_for(181) == 6
    assert bonus_for(365) == 6
    assert bonus_for(366) == 3
    assert bonus_for(730) == 3
    assert bonus_for(731) == 0


def test_recency_falls_back_to_accessed_at_when_undated():
    """An undated source still gets a usable date instead of crashing or scoring 0."""
    rel = _mk(Status.confirmed, n_publishers=1, published=None, accessed=SNAPSHOT)
    s = score_relationship(rel)
    assert s.recency_bonus == 10
    assert s.newest_evidence_date == SNAPSHOT
    assert s.evidence_age_days == 0


def test_newest_evidence_date_picks_the_latest_and_prefers_published():
    rel = _mk(Status.confirmed, n_publishers=1, published=date(2025, 1, 1))
    undated = Evidence(
        url="https://example.com/undated", publisher="pub-undated",
        published_at=None, accessed_at=date(2026, 3, 1), locator="x",
    )
    rel = rel.model_copy(update={"evidence": [*rel.evidence, undated]})
    assert newest_evidence_date(rel) == date(2026, 3, 1)
    # ...but a dated source always beats its own accessed_at fallback.
    assert _evidence_date(rel.evidence[0]) == date(2025, 1, 1)


def test_evidence_age_and_rationale_are_exposed_for_audit():
    """A reviewer must be able to see what the recency term was measured against."""
    s = score_relationship(_mk(Status.confirmed, published=date(2026, 3, 31)))
    assert s.newest_evidence_date == date(2026, 3, 31)
    assert s.evidence_age_days == (SNAPSHOT - date(2026, 3, 31)).days
    assert "2026-03-31" in s.rationale
