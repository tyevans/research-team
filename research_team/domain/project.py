"""A project: sessions that share a filesystem lineage and a knowledge graph.

Sequential by construction. One session holds the project at a time, inherits
the filesystem as the last one left it, and hands the tip back when it ends.
That is the same shape as a fork -- inherit at a point, diverge from there --
which is why this aggregate stores a lineage pointer rather than files of its
own. The filesystem still folds out of a single session stream, so scrubbing a
session's timeline still refolds its filesystem.

The project id is also redstring's `tenant_id`, which is why it is a UUID.
"""

from dataclasses import dataclass
from typing import Literal
from uuid import UUID

from eventsource import CommandRejectedError, DeciderAggregate, DomainEvent, register_event
from pydantic import BaseModel, Field


@register_event
class ProjectCreated(DomainEvent):
    """Creation event. Must be the first event on the stream."""

    aggregate_type: str = "Project"
    name: str


@register_event
class SessionJoinedProject(DomainEvent):
    """A session took the project, inheriting the filesystem at `inherited_at`."""

    aggregate_type: str = "Project"
    session_id: UUID
    inherited_at: int


@register_event
class ProjectTipAdvanced(DomainEvent):
    """A session finished; the project's filesystem is now its stream at `at_event`."""

    aggregate_type: str = "Project"
    session_id: UUID
    at_event: int


@dataclass(frozen=True)
class CreateProject:
    name: str


@dataclass(frozen=True)
class JoinProject:
    session_id: UUID


@dataclass(frozen=True)
class AdvanceTip:
    session_id: UUID
    at_event: int


ProjectCommand = CreateProject | JoinProject | AdvanceTip


class ProjectState(BaseModel):
    """Everything derivable from the project's event stream."""

    project_id: UUID
    status: Literal["new", "created"] = "new"
    name: str = ""
    member_session_ids: list[UUID] = Field(default_factory=list)
    active_session_id: UUID | None = None
    """The session currently holding the project, if any."""
    tip_session_id: UUID | None = None
    """Whose stream the filesystem folds from. None means the project is empty."""
    tip_at_event: int = 0
    """How far into that stream to fold."""


def initial_state(aggregate_id: UUID) -> ProjectState:
    return ProjectState(project_id=aggregate_id)


def decide(command: ProjectCommand, state: ProjectState) -> list[DomainEvent]:
    """Which requests are legal, and what facts they produce.

    Reads as a transition table, the way `session.decide` does.
    """
    project_id = state.project_id
    match command, state:
        case CreateProject(name=name), ProjectState(status="new"):
            return [ProjectCreated(aggregate_id=project_id, name=name)]
        case CreateProject(), _:
            raise CommandRejectedError("project already created")

        case _, ProjectState(status="new"):
            raise CommandRejectedError("project not created")

        case JoinProject(session_id=session_id), ProjectState(active_session_id=None):
            return [
                SessionJoinedProject(
                    aggregate_id=project_id,
                    session_id=session_id,
                    inherited_at=state.tip_at_event,
                )
            ]
        case JoinProject(), ProjectState(active_session_id=holder):
            # Named, not just refused: the next thing anyone asks is "which one".
            raise CommandRejectedError(f"project is held by session {holder}")

        case AdvanceTip(session_id=session_id, at_event=at), _:
            if state.active_session_id != session_id:
                raise CommandRejectedError(
                    f"session {session_id} does not hold this project"
                )
            return [
                ProjectTipAdvanced(
                    aggregate_id=project_id, session_id=session_id, at_event=at
                )
            ]

    raise CommandRejectedError(f"unhandled command {type(command).__name__}")


def evolve(state: ProjectState, event: DomainEvent) -> ProjectState:
    """What each fact does to the state.

    Total on purpose: an unknown event leaves the state alone rather than
    raising, so a stream carrying an event this build does not know about still
    replays instead of failing halfway through.
    """
    match event:
        case ProjectCreated(name=name):
            return ProjectState(
                project_id=state.project_id, status="created", name=name
            )

        case SessionJoinedProject(session_id=session_id):
            return state.model_copy(
                update={
                    "member_session_ids": [*state.member_session_ids, session_id],
                    "active_session_id": session_id,
                }
            )

        case ProjectTipAdvanced(session_id=session_id, at_event=at):
            return state.model_copy(
                update={
                    "active_session_id": None,
                    "tip_session_id": session_id,
                    "tip_at_event": at,
                }
            )

        case _:
            return state


class Project(DeciderAggregate[ProjectState, ProjectCommand]):
    """The imperative shell. Holds no rules -- it delegates all three.

    Everything the library needs from an aggregate (replay, snapshots, version
    checks, repository integration) is inherited; everything this project
    decides lives in the functions above. Mirrors `CodingSession`'s shape
    exactly: the class attributes are bound directly to the module-level
    functions rather than wrapped in new method bodies, so there is exactly
    one implementation of each rule to keep in sync.
    """

    aggregate_type = "Project"

    initial_state = staticmethod(initial_state)
    decide = staticmethod(decide)
    evolve = staticmethod(evolve)
