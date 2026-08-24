"""A realized course: a person's decision that a cluster is a real course.

`domain/catalog_curation.py` next door is deliberately *not* an aggregate --
featuring enforces no invariant, so appending directly is enough. Realizing is
different: a second `CourseRealized` on the same stream would overwrite the
frozen membership that `fit_of` compares the live cluster against, and nothing
about that overwrite would look wrong from outside. The drift the feature
exists to surface would be erased by the act of observing it -- silently,
which is exactly the failure this repository keeps meeting elsewhere. That is
the whole reason this gets a `decide`/`evolve` pair and catalog_curation does
not: here, getting it wrong destroys the fact the feature is for.

`member_entity_ids` rides on `CourseRealized` itself rather than living only
in `membership_hash`. The hash says *that* the membership moved; the ids say
*how* -- which entities were kept, which were added, which were dropped. That
comparison is the whole feature. A hash-only event would make `fit_of` answer
a boolean ("changed: yes/no") instead of a diff, and a stranded-course view
that can say only "this drifted" and not "by losing X and gaining Y" is not
worth building the freeze for.

`title` is carried on the event too, despite being derivable from the area's
`display_name()` at read time -- because that derivation stops working the
moment the course needs it most. An orphaned course (see `fit_of`) has no
`LearningArea` to call `display_name()` on: re-clustering moved the slug, so
the area that used to answer it no longer exists under that name. A stranded-
course list that falls back to rendering the bare slug hides the exact case
the list exists to surface. Freezing the title alongside the ids means an
orphaned course still reads as "Warp Drive" rather than "warp-drive".
"""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from uuid import UUID, uuid5

from eventsource import (
    CommandRejectedError,
    DeciderAggregate,
    DomainEvent,
    StreamId,
    register_event,
)
from pydantic import BaseModel, Field

from research_team.domain.learning_area import LearningArea

COURSE_AGGREGATE_TYPE = "Course"


def course_stream_id(project_id: UUID, slug: str) -> StreamId:
    """One stream per (project, slug), so a project's courses do not serialise
    against each other -- realizing two courses at once is an ordinary thing to
    do and a shared stream would make one of them retry.

    `StreamId.aggregate_id` must be a `UUID`, and `(project_id, slug)` is not
    one -- there is no aggregate id that predates the decision to realize this
    slug, unlike a corpus or a run that shares its project's or its own id.
    `uuid5` derives one deterministically from the pair, so the same slug in
    the same project always resolves to the same stream without minting or
    storing an id anywhere.
    """
    return StreamId(uuid5(project_id, slug), COURSE_AGGREGATE_TYPE)


# ---------------- events ----------------


@register_event
class CourseRealized(DomainEvent):
    """A person decided this cluster is a course, and this is what it held.

    `member_entity_ids` and `title` are the frozen membership -- see the
    module docstring for why both ride on the event instead of being derived
    at read time.
    """

    aggregate_type: str = COURSE_AGGREGATE_TYPE
    project_id: UUID
    slug: str
    title: str
    member_entity_ids: list[str]
    membership_hash: str
    realized_at: datetime


@register_event
class CourseAbandoned(DomainEvent):
    """A person undid the decision. The stream is not deleted -- it simply
    stops being realized, so a later `CourseRealized` on it is a fresh act
    rather than a correction of this one."""

    aggregate_type: str = COURSE_AGGREGATE_TYPE
    project_id: UUID
    slug: str


# ---------------- commands ----------------


@dataclass(frozen=True)
class RealizeCourse:
    project_id: UUID
    slug: str
    title: str
    member_entity_ids: tuple[str, ...]
    membership_hash: str
    realized_at: datetime


@dataclass(frozen=True)
class AbandonCourse:
    project_id: UUID
    slug: str


CourseCommand = RealizeCourse | AbandonCourse


# ---------------- state ----------------


class CourseState(BaseModel):
    realized: bool = False
    project_id: UUID | None = None
    slug: str = ""
    title: str = ""
    member_entity_ids: list[str] = Field(default_factory=list)
    membership_hash: str = ""


def initial_state() -> CourseState:
    return CourseState()


# ---------------- decide ----------------


def decide(command: CourseCommand, state: CourseState) -> list[DomainEvent]:
    """Which requests are legal.

    `RealizeCourse` against an already-realized course is refused -- see the
    module docstring for why that refusal is the whole point of this being an
    aggregate. `AbandonCourse` against a course that was never realized (or
    was already abandoned) is refused for the ordinary reason: there is no
    decision to undo.
    """
    match command, state:
        case RealizeCourse(), CourseState(realized=False):
            stream = course_stream_id(command.project_id, command.slug)
            return [
                CourseRealized(
                    aggregate_id=stream.aggregate_id,
                    project_id=command.project_id,
                    slug=command.slug,
                    title=command.title,
                    member_entity_ids=list(command.member_entity_ids),
                    membership_hash=command.membership_hash,
                    realized_at=command.realized_at,
                )
            ]
        case RealizeCourse(slug=slug), _:
            raise CommandRejectedError(
                f"course {slug!r} is already realized -- abandon it first"
            )

        case AbandonCourse(), CourseState(realized=True):
            stream = course_stream_id(command.project_id, command.slug)
            return [
                CourseAbandoned(
                    aggregate_id=stream.aggregate_id,
                    project_id=command.project_id,
                    slug=command.slug,
                )
            ]
        case AbandonCourse(), _:
            raise CommandRejectedError("course is not realized")

    raise CommandRejectedError(f"unhandled command {type(command).__name__}")


# ---------------- evolve ----------------


def evolve(state: CourseState, event: DomainEvent) -> CourseState:
    """What each fact does to the state. Total, like every other fold here."""
    match event:
        case CourseRealized(
            project_id=project_id,
            slug=slug,
            title=title,
            member_entity_ids=member_entity_ids,
            membership_hash=membership_hash,
        ):
            return CourseState(
                realized=True,
                project_id=project_id,
                slug=slug,
                title=title,
                member_entity_ids=list(member_entity_ids),
                membership_hash=membership_hash,
            )

        case CourseAbandoned():
            # The ids and title stay on the state rather than being cleared:
            # nothing reads them while unrealized, and clearing would lose the
            # record for a projection replaying to build history.
            return state.model_copy(update={"realized": False})

    return state


# ---------------- fit ----------------


@dataclass(frozen=True)
class CourseFit:
    kept: tuple[str, ...]
    added: tuple[str, ...]
    dropped: tuple[str, ...]
    orphaned: bool


def fit_of(frozen_ids: Sequence[str], area: LearningArea | None) -> CourseFit:
    """How a realized course stands against its cluster now.

    Entity *ids*, not names. A dropped id has no name in the current cluster --
    resolving it would mean inventing a label for something that is gone -- so
    the presenter resolves what it can and reports the rest as ids.

    `area is None` is the orphaned case: the slug names no cluster, because
    slugs derive from an area's top anchor and re-clustering moves them. It is
    reported separately from "every member dropped" even though the two produce
    identical `dropped` tuples, because they call for different actions.
    """
    frozen = set(frozen_ids)
    if area is None:
        return CourseFit(kept=(), added=(), dropped=tuple(sorted(frozen)), orphaned=True)
    current = {m.entity_id for m in area.members}
    return CourseFit(
        kept=tuple(sorted(frozen & current)),
        added=tuple(sorted(current - frozen)),
        dropped=tuple(sorted(frozen - current)),
        orphaned=False,
    )


class Course(DeciderAggregate[CourseState, CourseCommand]):
    """The imperative shell. Holds no rules -- it delegates all three."""

    aggregate_type = COURSE_AGGREGATE_TYPE

    initial_state = staticmethod(initial_state)
    decide = staticmethod(decide)
    evolve = staticmethod(evolve)
