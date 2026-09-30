"""Explainable 0-100 scoring for a single relationship.

The formula is intentionally linear and transparent so a reviewer can
re-derive every point by hand:

    base                 from evidentiary status (confirmed/inferred/unknown)
    + evidence_count     up to +15 (3 per independent piece of evidence, cap 5)
    + independence       up to +20 (4 per distinct publisher, cap 5)
    + recency            0 / 3 / 6 / 10 based on how recently the evidence was
                         *published*, measured against the snapshot date
    + quantitative       +8 if a public number anchors the claim
    - penalty            -10 if inferred but only one publisher;
                         -20 if unknown (we are signalling low confidence)
    = clamp(0, 100)

We deliberately do NOT feed LLM embeddings or black-box similarity here:
the challenge asks for a score a reviewer can audit.
"""

from __future__ import annotations

from datetime import date

from .models import Evidence, Relationship, ScoreBreakdown, Status

_BASE = {Status.confirmed: 70, Status.inferred: 40, Status.unknown: 15}

_RECENCY_DAYS = [
    (180, 10),
    (365, 6),
    (730, 3),
]


def _evidence_date(ev: Evidence) -> date:
    """Best-known *publication* date for one piece of evidence.

    We prefer ``published_at`` because that is what makes a claim fresh.
    ``accessed_at`` is only a fallback for undated sources (an undated page has
    no publication date to measure); it must never be the primary input,
    because every source in a frozen snapshot is accessed on roughly the same
    day -- scoring on it would hand every relationship the same bonus and the
    recency term would carry zero information.
    """
    return ev.published_at or ev.accessed_at


def newest_evidence_date(rel: Relationship) -> date:
    """The most recently published evidence backing ``rel``.

    Falls back to the snapshot date for a relationship with no evidence at all,
    so callers always get a usable date.
    """
    return max((_evidence_date(e) for e in rel.evidence), default=rel.as_of)


def _recency_bonus(age_days: int) -> int:
    """Map the age of the newest evidence (in days) onto 0 / 3 / 6 / 10 points."""
    for threshold, pts in _RECENCY_DAYS:
        if age_days <= threshold:
            return pts
    return 0


def score_relationship(rel: Relationship) -> ScoreBreakdown:
    base = _BASE[rel.status]

    n_ev = len(rel.evidence)
    evidence_bonus = min(n_ev, 5) * 3

    publishers = {e.publisher for e in rel.evidence}
    independence_bonus = min(len(publishers), 5) * 4

    newest = newest_evidence_date(rel)
    age_days = (rel.as_of - newest).days
    recency_bonus = _recency_bonus(age_days)

    quant_bonus = 8 if rel.quantitative_note else 0

    penalty = 0
    if rel.status is Status.inferred and len(publishers) < 2:
        penalty -= 10
    if rel.status is Status.unknown:
        penalty -= 20

    total = max(0, min(100, base + evidence_bonus + independence_bonus
                       + recency_bonus + quant_bonus + penalty))

    rationale = (
        f"base={base} ({rel.status.value}); "
        f"+{evidence_bonus} evidence ({n_ev} pieces); "
        f"+{independence_bonus} independence ({len(publishers)} publishers); "
        f"+{recency_bonus} recency (newest evidence {newest.isoformat()}, "
        f"{age_days} days old); "
        f"+{quant_bonus} quantitative anchor; "
        f"{penalty} penalty"
    )
    return ScoreBreakdown(
        base=base,
        evidence_count_bonus=evidence_bonus,
        independence_bonus=independence_bonus,
        recency_bonus=recency_bonus,
        quantitative_bonus=quant_bonus,
        penalty=penalty,
        total=total,
        rationale=rationale,
        newest_evidence_date=newest,
        evidence_age_days=age_days,
    )
