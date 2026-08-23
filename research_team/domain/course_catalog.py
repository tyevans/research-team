"""What a cluster looks like when it is offered as something to study.

**Nothing here is an aggregate and nothing here is on the event log**, for
`learning_area.py`'s reason, which this module inherits rather than restates: a
candidate is a pure function of a projection that is itself a pure function of
a graph folded from the log. Storing one would store a derivation beside its
own inputs.

The one thing in this feature that *does* earn the log is the featured
override, and it lives in `domain/catalog_curation.py` rather than here --
because it is a person's decision rather than a derivation, and keeping the two
in separate modules is what stops the distinction eroding.
"""

from dataclasses import dataclass
from datetime import datetime
from hashlib import sha256

from research_team.domain.learning_area import AreaMember, LearningArea

CategoryKey = str
"""A grouper's answer for one area. A `str` rather than an enum: the grouper is
a port with more than one intended implementation, and an enum here would make
the domain the place every future grouper's vocabulary has to be registered."""


@dataclass(frozen=True)
class ArtRef:
    """Where a card's illustration is, and what it shows.

    A URL and an alt text and nothing else, so increment 3 changes the value
    this carries and not its shape. `alt` is required rather than optional
    because a decorative-only image on a browsing surface is a card a screen
    reader cannot tell from any other card.
    """

    url: str
    alt: str


@dataclass(frozen=True)
class Blurb:
    """Generated copy, and what it was generated from.

    `membership_hash` is the whole reason this is a record rather than a
    string. A blurb written from forty entities that now describes ninety is
    not wrong in any way a reader can see, and this repository has shipped
    silent staleness more than once. Carrying the hash makes "this description
    is N entities behind" a number a card can render.
    """

    text: str
    membership_hash: str
    generated_at: datetime


@dataclass(frozen=True)
class CourseCandidate:
    """One cluster, dressed for browsing.

    `blurb` is `None` for a candidate nothing has written copy for yet, which
    is every candidate on a cold project. That is an ordinary state and not a
    degraded one: the card renders its title, its anchors and its art, and asks
    for copy when someone looks at it.
    """

    slug: str
    title: str
    category: CategoryKey
    prominence: float
    size: int
    membership_hash: str
    """The area's *current* hash, not the blurb's.

    A candidate whose only hash was the one stamped into `blurb` could never
    tell a reader the copy is stale -- both numbers would always match,
    because there would be only one. This field is what the blurb's hash gets
    compared against, so "this copy is N entities behind" is a number the card
    can compute rather than a claim it takes on faith.
    """
    anchors: tuple[AreaMember, ...]
    art: ArtRef
    blurb: Blurb | None = None
    featured_rank: int | None = None


@dataclass(frozen=True)
class Category:
    """A group of candidates, with the label a reader sees.

    `key` and `label` are separate because only one of them is checkable. The
    key is what the grouper decided and what a page can justify -- "these are
    grouped because their anchors are `person`" -- where the label is cosmetic
    and may be model-written. Collapsing them would make the justification
    unavailable the moment a label is generated.
    """

    key: CategoryKey
    label: str
    candidates: tuple[CourseCandidate, ...]


@dataclass(frozen=True)
class CatalogSections:
    """The catalog, cut into the three bands a reader's attention has."""

    hero: tuple[CourseCandidate, ...]
    highlights: tuple[CourseCandidate, ...]
    filed: tuple[Category, ...]


def prominence_of(area: LearningArea) -> float:
    """How prominently this area should be offered.

    Size times mean anchor centrality. Centrality is already weighted degree
    *within* the area, which is the correct reading: an entity wired to half
    the project but to nothing in its own area is a bridge, not an anchor, and
    ranking on global degree would promote an area on the strength of a member
    that barely belongs to it.

    **What this measures, stated because it does not go away:** how
    well-connected a cluster is. That is a proxy for "well covered by the
    corpus", not for "worth a learner's time". A hero row driven by this alone
    leads with whatever was ingested most, which is why the featured override
    exists in the same increment rather than a later one.

    Zero for an empty area rather than a `ZeroDivisionError`: a degenerate
    projection can produce one, and it must sort last rather than fail the
    whole catalog.
    """
    if not area.members:
        return 0.0
    mean_centrality = sum(m.centrality for m in area.members) / len(area.members)
    return len(area.members) * mean_centrality


def membership_hash(area: LearningArea) -> str:
    """A stable digest of *which entities* are in this area.

    Sorted before hashing, so two reads of one cluster that ordered members
    differently agree. They otherwise would not, and every request would
    invalidate every blurb -- turning a cache into a per-request model call.

    Deliberately over entity ids only, not over names or centralities. A
    consolidation that renames an entity or shifts a weight has not changed
    what the area is *about*, and regenerating copy for it would churn the
    text under a reader for no gain.
    """
    joined = "\n".join(sorted(m.entity_id for m in area.members))
    return sha256(joined.encode("utf-8")).hexdigest()[:16]
