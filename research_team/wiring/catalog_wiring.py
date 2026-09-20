"""Catalog, art, and course realization service construction for the composition root.

Extracts CatalogService, LibraryArtProvider, ModelBlurbWriter, ModelOutlineWriter,
BlurbSweep, ModelSvgArtist, ArtSweep, ArtReroll, course repository,
and CourseService construction out of _build_application.
"""

from dataclasses import dataclass
from typing import Any

from eventsource import EventPublisher
from eventsource.adapters.sqlite import SQLiteEventStore
from eventsource.application.aggregates.repository import AggregateRepository
from langchain_core.language_models import BaseChatModel

from research_team.application.course_catalog import CatalogService
from research_team.application.course_realization import CourseService
from research_team.infrastructure.knowledge.blurb_writer import ModelBlurbWriter
from research_team.infrastructure.knowledge.library_art import LibraryArtProvider
from research_team.infrastructure.knowledge.outline_writer import ModelOutlineWriter
from research_team.infrastructure.knowledge.seeded_art import SeededArtProvider
from research_team.infrastructure.knowledge.svg_artist import ModelSvgArtist
from research_team.infrastructure.knowledge.type_plurality_grouper import TypePluralityGrouper
from research_team.infrastructure.persistence.event_store import build_course_repository
from research_team.interfaces.web.art_sweep import ArtReroll, ArtSweep
from research_team.interfaces.web.blurb_sweep import BlurbSweep
from research_team.wiring.runners import _RealizedCourses

__all__ = [
    "CatalogServices",
    "build_catalog_services",
]


@dataclass(frozen=True)
class CatalogServices:
    """The bundle of catalog, art, and course realization services."""

    catalog_service: CatalogService
    art_matcher: LibraryArtProvider
    blurb_writer: ModelBlurbWriter
    outline_writer: ModelOutlineWriter
    blurb_sweep: BlurbSweep
    art_generator: ModelSvgArtist
    art_sweep: ArtSweep
    art_reroll: ArtReroll
    course_repository: AggregateRepository
    course_service: CourseService


def build_catalog_services(
    *,
    art_store: Any,
    candidate_art_store: Any,
    blurb_cache: Any,
    outline_cache: Any,
    extraction_model: BaseChatModel,
    course_runner: Any,
    authoring: Any,
    store: SQLiteEventStore | None = None,
    publisher: EventPublisher | None = None,
    course_repository: AggregateRepository | None = None,
    fallback_art: Any | None = None,
    grouper: Any | None = None,
) -> CatalogServices:
    """Construct catalog, art, and course realization services.

    Builds the art matcher, catalog service, blurb writer, outline writer,
    blurb sweep, art generator, art sweep, art reroll, course repository,
    and course service.
    """
    resolved_fallback_art = fallback_art if fallback_art is not None else SeededArtProvider()
    resolved_grouper = grouper if grouper is not None else TypePluralityGrouper()

    art_matcher = LibraryArtProvider(
        art_store=art_store,
        candidate_art_store=candidate_art_store,
        fallback=resolved_fallback_art,
    )
    catalog_service = CatalogService(
        grouper=resolved_grouper,
        art=art_matcher,
        blurbs=blurb_cache,
    )
    # R5: constructed even though nothing calls `.write()` yet this
    # increment -- see `Application.blurbs`'s own docstring for the reasoning
    # (a caller-less port is the exact shape CLAUDE.md's co-mention section
    # warns about, and building the object graph now turns the later
    # increment into adding one call rather than a whole graph).
    blurb_writer = ModelBlurbWriter(extraction_model)
    outline_writer = ModelOutlineWriter(extraction_model)
    # The same `extraction_model` `blurb_writer` above takes -- the brief's
    # own instruction, and `ModelOutlineWriter`'s docstring gives the reason:
    # a second model configuration would be a second thing to keep in sync
    # with `config.model_name()` for no benefit, since both jobs want the
    # same "reason less, answer in a fixed shape" trade-off extraction
    # already makes.
    # The sweep nothing called yet in increment 1 -- see `Application
    # .blurb_sweep`'s docstring. Built over the same `blurb_cache` and
    # `outline_cache` every other reader of either uses, so a sweep and an
    # on-demand `catalog`/course-detail read of the same slug see one cache
    # each, not two.
    blurb_sweep = BlurbSweep(blurb_cache, outline_cache)
    # Same `extraction_model` `blurb_writer` above takes -- no second model
    # configuration, matching `outline_writer`'s own comment above on why.
    art_generator = ModelSvgArtist(extraction_model)
    art_sweep = ArtSweep(art_store, candidate_art_store)
    art_reroll = ArtReroll(art_store, candidate_art_store)

    # Unsnapshotted, over this application's own store and publisher, mirroring
    # `media_proposal_repository` -- see `build_course_repository`'s own
    # docstring for why no snapshot policy is warranted here.
    if course_repository is not None:
        resolved_course_repository = course_repository
    elif store is not None:
        resolved_course_repository = build_course_repository(store, publisher)
    else:
        raise ValueError("Either store or course_repository must be provided")

    # `outline_writer` is not passed here: `CourseService` no longer calls a
    # model at all -- see `course_realization.py`'s module docstring. It
    # stays a local above only because `blurb_sweep` needs it.
    course_service = CourseService(
        realized=_RealizedCourses(course_runner, authoring),
        outline_cache=outline_cache,
    )

    return CatalogServices(
        catalog_service=catalog_service,
        art_matcher=art_matcher,
        blurb_writer=blurb_writer,
        outline_writer=outline_writer,
        blurb_sweep=blurb_sweep,
        art_generator=art_generator,
        art_sweep=art_sweep,
        art_reroll=art_reroll,
        course_repository=resolved_course_repository,
        course_service=course_service,
    )
