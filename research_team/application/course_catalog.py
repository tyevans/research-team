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

from research_team.application.curriculum import Curriculum
from research_team.domain.course_catalog import (
    ArtRef,
    Blurb,
    CatalogSections,
    Category,
    CategoryKey,
    CourseCandidate,
    membership_hash,
    prominence_of,
)
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

    def label_for(self, key: CategoryKey) -> str:
        """The display label for one category key.

        Lives on the port rather than in the catalog assembler: the label
        table is a fact about *this* grouper's vocabulary, and an application
        layer that imported `type_plurality_grouper.CATEGORY_LABELS` directly
        to build one would be reaching into `infrastructure`, which
        `tests/test_architecture.py` forbids. Falling back to the key itself
        for one it does not recognise is a requirement on every
        implementation of this port, not just the default one -- an unlisted
        key is ugly and correct, and a made-up label would be neither.
        """
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


@dataclass(frozen=True)
class DraftBlurb:
    """What a model produced for one candidate's copy, before it is cached.

    `title` and `text` come from one model call -- see
    `BlurbTextPort.write`'s docstring for why a second call for the title
    alone was rejected. Both fields are present or the whole reply is
    `None`; there is no state where a card has a generated title and no
    copy, or copy and no title, because `write` never returns one without
    the other.
    """

    title: str
    text: str


class BlurbTextPort(Protocol):
    """Turns a candidate's anchors into a title and catalog copy, or refuses.

    `None` is a legitimate answer, not an error: an empty reply, one with no
    separate title line, or a title identical to the cluster's top anchor is
    refused rather than returned. That last case is a model handed one
    dominant entity returning its name verbatim as the title -- a plausible-
    looking answer this port exists to stop.

    One call, not two: the writer already prompts with the anchors to write
    the blurb, and a second call for the title would double the cost of a
    sweep that already makes one model call per candidate -- and would let
    the title and the blurb disagree about what the course is about, with
    nothing able to notice. `write` returns both or neither.
    """

    async def write(self, title: str, anchors: Sequence[AreaMember]) -> DraftBlurb | None: ...

    @property
    def model_name(self) -> str:
        """Which model this port writes with, for `CourseBlurbRow.model`.

        On the port rather than returned beside the text, because a refusal
        returns `None` and would take the name with it -- and the name is a
        property of the writer, not of one reply. Without this the column
        exists and nothing in the system can fill it: the caller lives here,
        and `tests/test_architecture.py` keeps this layer free of the chat
        model's vocabulary.
        """
        ...


@dataclass(frozen=True)
class CachedBlurb:
    """A previously generated blurb, in this layer's own vocabulary.

    Not `CourseBlurbRow`: that type carries `project_id` and `slug` a caller
    already supplied to fetch it, and importing it here would put
    `infrastructure.persistence` in a module `tests/test_architecture.py`
    keeps free of it -- the same reasoning `entity_definitions.Definition`
    gives for not being `EntityDefinitionRow`.

    `title` may be `""` -- a row written before titles existed, per
    `CourseBlurbRow.title`'s own default. `CatalogService.build` is where
    that empty string becomes `area.display_name()` again; this type carries
    it through unchanged rather than deciding the fallback itself, so a
    caller with a reason to want the raw cached value still can.
    """

    text: str
    title: str
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
        title: str,
        text: str,
        membership_hash: str,
        model: str,
        generated_at: datetime,
    ) -> None: ...


@dataclass(frozen=True)
class DraftOutline:
    """What a model produced for one candidate, before it is cached.

    `sections` is `(heading, summary)` pairs in reading order -- a tuple of
    pairs rather than a list of dataclasses because nothing reads a section
    except in order and by position, and a third type for two strings is a
    file a reader has to visit to learn nothing.

    Not `CourseOutlineRow`, for `CachedBlurb`'s reason: that type carries
    `project_id`, `slug` and a `membership_hash` the caller already holds,
    and importing it here would put `infrastructure.persistence` in a module
    `tests/test_architecture.py` keeps free of it.
    """

    promise: str
    sections: tuple[tuple[str, str], ...]


class OutlineTextPort(Protocol):
    """Turns a candidate's title and anchors into an outline, or refuses.

    `None` is a legitimate answer, not an error: an outline is refused when the
    reply does not parse as the asked-for shape, and when it carries fewer
    sections than make it an outline at all. A caller falls back to no
    outline; it does not retry on the assumption something went wrong.

    Per CLAUDE.md this port has exactly one production adapter
    (`outline_writer.ModelOutlineWriter`), which means a stub on this side and
    a unit test on the adapter's side prove the two halves work and cannot
    prove they meet. The test that matters drives both ends over real data,
    and it is Task 13's.
    """

    async def write(
        self, title: str, anchors: Sequence[AreaMember]
    ) -> DraftOutline | None: ...

    @property
    def model_name(self) -> str:
        """Which model this port writes with, for `CourseOutlineRow.model`.
        See `BlurbTextPort.model_name` for why it is a property here."""
        ...


@dataclass(frozen=True)
class CachedOutline:
    """A previously generated outline, in this layer's own vocabulary.

    `CachedBlurb` with a structured payload, and separate from it for the
    reason `CourseOutlineRow` is a separate table: one shared type would need
    a field that is meaningful for half its instances.
    """

    promise: str
    sections: tuple[tuple[str, str], ...]
    membership_hash: str
    model: str
    generated_at: datetime


class OutlineCachePort(Protocol):
    """The stored outline for one candidate, if one has been generated.

    Backed by `CourseOutlineStore` at composition time. `slug` alone
    identifies the candidate within a project, matching `BlurbCachePort`.
    """

    async def get(self, project_id: UUID, slug: str) -> CachedOutline | None: ...

    async def put(
        self,
        project_id: UUID,
        slug: str,
        promise: str,
        sections: tuple[tuple[str, str], ...],
        membership_hash: str,
        model: str,
        generated_at: datetime,
    ) -> None: ...


@dataclass(frozen=True)
class Catalog:
    """The assembled catalog for one project, ready to render.

    `unplaceable_featured` is reported rather than silently dropped -- a slug
    is derived from an area's top anchor, so re-clustering can move it, and
    curation work that vanishes without a trace is worse than curation work
    that is visibly stranded. `derived_from` is the projection's own counts,
    carried through so a stale catalog is as detectable as a stale
    curriculum: see `AreaProjection`'s own reasoning for why the counts travel
    with anything derived from it.

    `sections.filed` holds only leftover candidates -- a category whose every
    area was promoted to hero or highlights is not represented there at all,
    per `CatalogService.build`'s reasoning. A future category *page*, browsing
    by key rather than by the three home-page bands, must not be built by
    filtering `sections.filed`: doing so would silently drop that category's
    most prominent courses, the ones good enough to have been promoted out of
    it. `all_candidates` is the total population for exactly that caller.
    """

    sections: CatalogSections
    categories: Mapping[CategoryKey, str]
    unplaceable_featured: tuple[str, ...]
    derived_from: tuple[int, int]

    @property
    def all_candidates(self) -> tuple[CourseCandidate, ...]:
        """Every candidate in the catalog, wherever it landed.

        For a category route: grouping `sections.filed` alone would omit any
        area good enough to have been promoted to hero or highlights, which
        is exactly the area a category page should lead with.
        """
        return (
            *self.sections.hero,
            *self.sections.highlights,
            *(c for cat in self.sections.filed for c in cat.candidates),
        )


HERO_SIZE = 5
"""How many candidates lead the catalog. A layout choice, not a finding --
picked to fill one row of hero cards at the console's current width, and
revisited if the hero component's own sizing changes."""

HIGHLIGHTS_SIZE = 8
"""How many candidates follow the hero before the rest fall into their
categories. Also a layout choice: enough for a second band a reader scans
before descending into `filed`, no more considered than that."""


class CatalogService:
    """Turns a curriculum into three ranked, categorised sections.

    Takes an already-built `Curriculum` rather than the ports that build one
    -- `CurriculumService` already caches per-graph counts, and rebuilding a
    projection inside this call would run a clustering pass per catalog view
    rather than per graph.
    """

    def __init__(
        self, *, grouper: CategoryGrouper, art: ArtPort, blurbs: BlurbCachePort
    ) -> None:
        self._grouper = grouper
        self._art = art
        self._blurbs = blurbs

    async def build(
        self,
        project_id: UUID,
        curriculum: Curriculum,
        featured: Mapping[str, int],
    ) -> Catalog:
        areas = curriculum.projection.areas
        by_slug = {a.slug: a for a in areas}
        category_of = self._grouper.group(areas)

        unplaceable = tuple(sorted(slug for slug in featured if slug not in by_slug))

        candidates: dict[str, CourseCandidate] = {}
        for area in areas:
            slug = area.slug
            category = category_of.get(slug, "unclassified")
            cached = await self._blurbs.get(project_id, slug)
            blurb = None
            title = area.display_name()
            if cached is not None:
                blurb = Blurb(
                    text=cached.text,
                    membership_hash=cached.membership_hash,
                    generated_at=cached.generated_at,
                )
                # `cached.title` is `""` for a row written before titles
                # existed (`CourseBlurbRow.title`'s default) -- `or` covers
                # that fallback without a separate branch, and the empty
                # string is otherwise indistinguishable from "not generated
                # yet" to a reader.
                title = cached.title or area.display_name()
            candidates[slug] = CourseCandidate(
                slug=slug,
                title=title,
                category=category,
                prominence=prominence_of(area),
                size=area.size,
                membership_hash=membership_hash(area),
                anchors=area.anchors,
                art=self._art.for_candidate(slug, category),
                blurb=blurb,
                featured_rank=featured.get(slug),
            )

        # Featured candidates are pinned ahead of everything else, ordered by
        # curator-assigned rank; the remainder falls through to the derived
        # prominence order. Slug is the tiebreak in both sorts -- two
        # candidates of equal prominence, or two featured entries of equal
        # rank, must order identically on every run over an unchanged graph,
        # or cards move between sections for no reason and it reads as
        # flakiness.
        featured_slugs = [
            slug for slug in candidates if candidates[slug].featured_rank is not None
        ]
        featured_slugs.sort(key=lambda slug: (candidates[slug].featured_rank, slug))

        remaining_slugs = [
            slug for slug in candidates if candidates[slug].featured_rank is None
        ]
        remaining_slugs.sort(key=lambda slug: (-candidates[slug].prominence, slug))

        ordered_slugs = featured_slugs + remaining_slugs
        ordered = [candidates[slug] for slug in ordered_slugs]

        hero = tuple(ordered[:HERO_SIZE])
        highlights = tuple(ordered[HERO_SIZE : HERO_SIZE + HIGHLIGHTS_SIZE])
        filed_slugs = ordered_slugs[HERO_SIZE + HIGHLIGHTS_SIZE :]

        # Every area not in hero or highlights lands in exactly one category's
        # `candidates`, so a candidate is never listed twice. `filed` holds
        # only categories with at least one leftover candidate -- a category
        # whose every area got promoted to hero is not seeded here with an
        # empty `candidates` tuple. An empty `Category` would be a tile the
        # browser has nothing to draw in, shipped only to make a category
        # visible that has, by construction, nothing to show in this
        # section. `Catalog.all_candidates` is where a caller that wants
        # "every area of this category, wherever it landed" should look
        # instead -- see the category route note on `Catalog`.
        by_category: dict[CategoryKey, list[CourseCandidate]] = {}
        for slug in filed_slugs:
            by_category.setdefault(candidates[slug].category, []).append(candidates[slug])

        filed = tuple(
            Category(
                key=key,
                label=self._grouper.label_for(key),
                candidates=tuple(members),
            )
            for key, members in sorted(by_category.items())
        )
        categories = {category.key: category.label for category in filed}

        sections = CatalogSections(hero=hero, highlights=highlights, filed=filed)
        return Catalog(
            sections=sections,
            categories=categories,
            unplaceable_featured=unplaceable,
            derived_from=(
                curriculum.projection.entity_count,
                curriculum.projection.relationship_count,
            ),
        )
