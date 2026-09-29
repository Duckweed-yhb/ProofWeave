"""Unit tests for the explainable scoring engine."""

from datetime import date

from proofweave.models import (
    Direction, Evidence, Relationship, RelationType, Status,
)
from proofweave.scoring import score_relationship


def _mk(status: Status, n_publishers: int = 2, has_quant: bool = False,
        age_days: int = 30) -> Relationship:
    evs = []
    for i in range(n_publishers):
        evs.append(Evidence(
            url=f"https://example.com/{i}",
            publisher=f"pub-{i}",
            published_at=date(2026, 1, 1),
            accessed_at=date(2026, 9, 29),
            locator="somewhere",
        ))
    return Relationship(
        id="x", subject="nvda", object_company="tsmc",
        relation_type=RelationType.supplier, direction=Direction.inbound,
        status=status, as_of=date(2026, 9, 29),
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
