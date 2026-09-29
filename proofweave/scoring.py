"""Explainable 0-100 scoring for a single relationship.

The formula is intentionally linear and transparent so a reviewer can
re-derive every point by hand:

    base                 from evidentiary status (confirmed/inferred/unknown)
    + evidence_count     up to +15 (3 per independent piece of evidence, cap 5)
    + independence       up to +20 (4 per distinct publisher, cap 5)
    + recency            0 / 3 / 6 / 10 based on newest evidence vs snapshot
    + quantitative       +8 if a public number anchors the claim
    - penalty            -10 if inferred but only one publisher;
                         -20 if unknown (we are signalling low confidence)
    = clamp(0, 100)

We deliberately do NOT feed LLM embeddings or black-box similarity here:
the challenge asks for a score a reviewer can audit.
"""

from __future__ import annotations

from datetime import date

from .models import Relationship, ScoreBreakdown, Status

_BASE = {Status.confirmed: 70, Status.inferred: 40, Status.unknown: 15}

_RECENCY_DAYS = [
    (180, 10),
    (365, 6),
    (730, 3),
]


def _recency_bonus(newest: date, snapshot: date) -> int:
    age_days = (snapshot - newest).days
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

    newest = max((e.accessed_at for e in rel.evidence), default=rel.as_of)
    recency_bonus = _recency_bonus(newest, rel.as_of)

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
        f"+{recency_bonus} recency; "
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
    )
