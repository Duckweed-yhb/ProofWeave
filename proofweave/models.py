"""Core data models for ProofWeave.

Every model is frozen (immutable) by default so that a snapshot loaded from
disk cannot be mutated in place between requests.  A `Relationship` carries
the four things the challenge asks us to keep linked: the conclusion
(who relates to whom, in which direction, of what type), the evidence
(source URL, publisher, date, locator), the time (as_of + accessed_at),
and an explainable score (see proofweave.scoring).
"""

from __future__ import annotations

from datetime import date
from enum import Enum
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field, HttpUrl


class _Frozen(BaseModel):
    """Base class for every model in this package.

    A loaded snapshot is a deliverable that the API caches process-wide, so
    in-place mutation would silently leak one request's edits into every later
    request.  Freezing makes that a loud error instead.  Rebuild with
    ``model_copy(update={...})`` when a change is genuinely intended.
    """

    model_config = ConfigDict(frozen=True)


class RelationType(str, Enum):
    supplier = "supplier"
    customer = "customer"
    partner = "partner"
    investor_or_investee = "investor_or_investee"
    peer = "peer"


class Direction(str, Enum):
    """Direction of the relationship *from the subject (NVIDIA)* outward.

    inbound  : the other company acts *toward* NVIDIA
               (e.g. TSMC manufactures wafers for NVIDIA; TSMC invests in NVIDIA)
    outbound : NVIDIA acts *toward* the other company
               (e.g. NVIDIA sells GPUs to Microsoft; NVIDIA invests in CoreWeave)
    both     : two-way (e.g. CoreWeave is both a customer and an investee)
    """

    inbound = "inbound"
    outbound = "outbound"
    both = "both"


class Status(str, Enum):
    """Evidentiary status of the claim.

    confirmed : named directly in an official filing, press release, or CEO statement.
    inferred  : consistent across multiple independent secondary sources, but
                not named in an official primary disclosure.
    unknown   : anonymous disclosure (e.g. 10-K "Customer A = 30%") or a
                market rumour.  We deliberately do NOT guess who it is.
    """

    confirmed = "confirmed"
    inferred = "inferred"
    unknown = "unknown"


class Company(_Frozen):
    id: str = Field(description="Stable slug, e.g. 'tsmc' or 'nvda'.")
    name: str
    ticker: Optional[str] = None
    exchange: Optional[str] = Field(
        default=None, description="e.g. 'NASDAQ', 'NYSE', 'TWSE', 'KRX'."
    )
    cik: Optional[str] = Field(
        default=None,
        description="SEC EDGAR CIK (10-digit) for US-listed filers, so a reviewer "
                    "can jump straight to https://www.sec.gov/edgar/browse/?CIK=<cik>.",
    )
    is_listed: bool = True
    note: Optional[str] = None


class Evidence(_Frozen):
    url: HttpUrl
    publisher: str
    published_at: Optional[date] = Field(
        default=None, description="When the source itself was published, if known."
    )
    accessed_at: date = Field(description="When we fetched/verified the source.")
    locator: str = Field(
        description="Pinpoint within the source, e.g. '10-K FY2026 Item 1 Business'."
    )
    access_note: str = Field(
        default="Public page, no auth / paywall / robots restriction.",
        description="How a reviewer may re-access this source legally.",
    )
    quote: Optional[str] = Field(
        default=None, description="Short verbatim excerpt that anchors the claim."
    )


class ScoreBreakdown(_Frozen):
    """Every additive term is exposed so a reviewer can re-derive 0-100."""

    base: int = Field(ge=0, le=100)
    evidence_count_bonus: int = 0
    independence_bonus: int = 0
    recency_bonus: int = 0
    quantitative_bonus: int = 0
    penalty: int = 0
    total: int = Field(ge=0, le=100)
    rationale: str = ""
    newest_evidence_date: Optional[date] = Field(
        default=None,
        description="Publication date of the most recent evidence backing the "
                    "claim; this is the date the recency term is measured against.",
    )
    evidence_age_days: Optional[int] = Field(
        default=None,
        description="snapshot as_of minus newest_evidence_date, in days. Lets a "
                    "reviewer check the recency term without re-deriving dates.",
    )


class Relationship(_Frozen):
    id: str
    subject: str = Field(description="Company id of the focal entity, e.g. 'nvda'.")
    object_company: str = Field(description="Company id of the counterparty.")
    relation_type: RelationType
    direction: Direction
    status: Status
    as_of: date = Field(description="Snapshot date this claim is frozen to.")
    rationale: str
    evidence: list[Evidence]
    quantitative_note: Optional[str] = Field(
        default=None,
        description="e.g. '~19% of TSMC 2025 revenue'; only when a public figure exists.",
    )
    uncertainty_note: Optional[str] = None
    score: Optional[ScoreBreakdown] = None


class Snapshot(_Frozen):
    """The frozen, reviewable deliverable.  Serialised to JSON and shipped
    inside the repo so a reviewer never has to re-crawl anything."""

    subject: Company
    snapshot_date: date
    coverage_statement: str
    companies: dict[str, Company]
    relationships: list[Relationship]
