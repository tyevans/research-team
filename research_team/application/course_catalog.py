"""Ports the course catalog depends on and the domain does not decide.

A port lives here rather than in `domain/course_catalog.py` when the decision
it wraps has more than one defensible implementation and the domain should not
have to be edited every time a better one arrives. `CategoryGrouper` is the
first of these.
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol
from uuid import UUID

from research_team.domain.course_catalog import ArtRef, CategoryKey
from research_team.domain.learning_area import AreaMember, LearningArea


class CategoryGrouper(Protocol):
    """Decides which category each area belongs to.

    A port with one implementation today and a known better one waiting. The
    ontology is the better source, and it is not ready to carry the category
    system yet -- measured 2026-08-23 against the real database, a discovery
    sweep has now run over all three projects (37 of 37 extracted documents
    examined) and produced 15 classes and 97 memberships in total. But look at
    one project rather than the total: the Star Trek project alone holds 5,462
    entities, and the sweep found it only 3 classes -- "television series"
    (13 members, no declared count), "television series" *again* from a
    different source (7 of 7), and "Xindi" (6 of 6, a taxonomy). Two of the
    three classes share a name because they came from different sources, which
    means the ontology would need cross-source class merging before it could
    group anything, on top of simply having more classes than three per
    project.

    Even setting the ontology aside, this corpus's own graph-level grouping
    edges are weak -- 470 `is_a`/`member_of` edges over 234 targets whose
    commonest values are `Star Trek`, `The Original Series`, `Rotten Tomatoes`
    and `Variety`. Grouping on those today produces a "Rotten Tomatoes"
    category.

    So this exists so the ontology can replace the implementation without the
    browser changing. Per CLAUDE.md, a port with exactly one production adapter
    needs a test driving *both ends over real data* -- see
    `test_a_catalog_over_a_real_ingest_has_cards_in_more_than_one_category`.
    """

    def group(self, areas: Sequence[LearningArea]) -> Mapping[str, CategoryKey]:
        """Every area's slug mapped to its category. Total: an area that comes
        in must come out, or the catalog silently loses courses."""
        ...


class ArtPort(Protocol):
    """Produces a card's illustration.

    A port with one throwaway implementation today (`SeededArtProvider`) and a
    known replacement waiting -- a searchable art library plus a generator, per
    the increment-3 note on `ArtRef`. The signature is the contract that swap
    has to preserve: given a slug and its category, return something to look
    at and something to say about it. Nothing here promises the art is
    *generated* rather than *selected*, on purpose, so the throwaway
    implementation and its replacement can differ completely underneath it.
    """

    def for_candidate(self, slug: str, category: CategoryKey) -> ArtRef:
        """The art for one candidate. Deterministic in every implementation
        this port is expected to have -- a catalog whose illustrations
        reshuffle between requests is not one a reader can recognise a card
        in, and that constraint belongs on the port, not just on today's
        adapter."""
        ...


class BlurbTextPort(Protocol):
    """Turns a candidate's title and anchors into catalog copy, or refuses.

    `None` is a legitimate answer, not an error: a reply that names an entity
    the cluster does not hold is refused rather than returned, per
    `blurb_writer.ModelBlurbWriter`'s own docstring for why that refusal is
    deliberately the conservative side to fail on.
    """

    async def write(self, title: str, anchors: Sequence[AreaMember]) -> str | None: ...


@dataclass(frozen=True)
class CachedBlurb:
    """A previously generated blurb, in this layer's own vocabulary.

    Not `CourseBlurbRow`: that type carries `project_id` and `slug` a caller
    already supplied to fetch it, and importing it here would put
    `infrastructure.persistence` in a module `tests/test_architecture.py`
    keeps free of it -- the same reasoning `entity_definitions.Definition`
    gives for not being `EntityDefinitionRow`.
    """

    text: str
    membership_hash: str
    model: str
    generated_at: datetime


class BlurbCachePort(Protocol):
    """The stored blurb for one candidate, if one has been generated.

    Backed by `CourseBlurbStore` at composition time -- there is exactly one
    blurb cache in this system and this port is a view onto it. `slug` alone
    identifies the candidate; the project is implicit for the reason
    `DefinitionCachePort` gives for its own: an instance belongs to one
    project, so a caller cannot reach another project's row by passing a
    different slug.
    """

    async def get(self, project_id: UUID, slug: str) -> CachedBlurb | None: ...

    async def put(
        self,
        project_id: UUID,
        slug: str,
        text: str,
        membership_hash: str,
        model: str,
        generated_at: datetime,
    ) -> None: ...
