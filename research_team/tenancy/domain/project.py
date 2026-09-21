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
class ProjectSessionJoined(DomainEvent):
    """The project admitted a session, which inherits the filesystem at `inherited_at`."""

    aggregate_type: str = "Project"
    session_id: UUID
    inherited_at: int


@register_event
class ProjectTipAdvanced(DomainEvent):
    """A session finished; the project's filesystem is now its stream at `at_event`."""

    aggregate_type: str = "Project"
    session_id: UUID
    at_event: int


@register_event
class ProjectDeleted(DomainEvent):
    """The project is retired: it accepts no more joins and is not listed.

    A fact appended to the stream, not a row removed from one. The log is
    append-only, and the project id is redstring's `tenant_id` and the anchor
    of a filesystem lineage -- sessions that recorded it keep their own
    streams, their own files, and their own readable history. Erasing the
    project would leave those pointing at nothing, and would rewrite a past
    that other aggregates already referenced.
    """

    aggregate_type: str = "Project"


@register_event
class ProjectArchived(DomainEvent):
    """The project is archived: read-only, accepts no joins or tip advances."""

    aggregate_type: str = "Project"


@register_event
class ProjectUnarchived(DomainEvent):
    """The project is restored from archive to active standing."""

    aggregate_type: str = "Project"


@register_event
class ProjectRenamed(DomainEvent):
    """The project was given a new name."""

    aggregate_type: str = "Project"
    name: str


@register_event
class ProjectMetadataUpdated(DomainEvent):
    """Project metadata (description, tags, arbitrary key-values) was updated."""

    aggregate_type: str = "Project"
    description: str
    tags: tuple[str, ...] = Field(default_factory=tuple)
    metadata: dict[str, str] = Field(default_factory=dict)


@dataclass(frozen=True)
class CreateProject:
    #: Which project to create. The one command whose target cannot be read
    #: back off the state, there being no state yet; every later command takes
    #: its id from the fold of `ProjectCreated`.
    project_id: UUID
    name: str


@dataclass(frozen=True)
class JoinProject:
    session_id: UUID


@dataclass(frozen=True)
class AdvanceTip:
    """Point the project's filesystem at `session_id`'s stream, `at_event` in.

    Issued from two places, and the second is why the holder check below is
    not the only accepted case. Releasing a project issues it from the holder.
    *Catching the tip up* issues it from a session that has already released
    and then kept working -- a real and ordinary thing, because releasing does
    not close a session or stop it accepting turns.
    """

    session_id: UUID
    at_event: int


@dataclass(frozen=True)
class DeleteProject:
    pass


@dataclass(frozen=True)
class ArchiveProject:
    pass


@dataclass(frozen=True)
class UnarchiveProject:
    pass


@dataclass(frozen=True)
class RenameProject:
    name: str


@dataclass(frozen=True)
class UpdateProjectMetadata:
    description: str | None = None
    tags: tuple[str, ...] | list[str] | None = None
    metadata: dict[str, str] | None = None


ProjectCommand = (
    CreateProject
    | JoinProject
    | AdvanceTip
    | DeleteProject
    | ArchiveProject
    | UnarchiveProject
    | RenameProject
    | UpdateProjectMetadata
)


class ProjectState(BaseModel):
    """Everything derivable from the project's event stream."""

    project_id: UUID | None = None
    """None before the project exists. Set by the fold of `ProjectCreated`.

    Optional because `initial_state()` takes no arguments (eventsource 0.12):
    the value before any event is one value for the aggregate *type*, and an
    id is not part of it.
    """

    status: Literal["new", "created", "archived", "deleted"] = "new"
    name: str = ""
    description: str = ""
    tags: tuple[str, ...] = Field(default_factory=tuple)
    metadata: dict[str, str] = Field(default_factory=dict)
    member_session_ids: list[UUID] = Field(default_factory=list)
    active_session_id: UUID | None = None
    """The session currently holding the project, if any."""
    tip_session_id: UUID | None = None
    """Whose stream the filesystem folds from. None means the project is empty."""
    tip_at_event: int = 0
    """How far into that stream to fold."""


def initial_state() -> ProjectState:
    return ProjectState()


def decide(command: ProjectCommand, state: ProjectState) -> list[DomainEvent]:
    """Which requests are legal, and what facts they produce.

    Reads as a transition table, the way `session.decide` does.
    """
    project_id = state.project_id
    match command, state:
        case CreateProject(project_id=new_id, name=name), ProjectState(status="new"):
            # From the command, not the state: this is the creation command,
            # so on a fresh project `state.project_id` is None.
            return [ProjectCreated(aggregate_id=new_id, name=name)]
        case CreateProject(), _:
            raise CommandRejectedError("project already created")

        case _, ProjectState(status="new"):
            raise CommandRejectedError("project not created")

        # Ordered before the rest: a deleted project answers nothing but
        # "deleted". Joining it would hand out a filesystem lineage that is
        # no longer maintained, and advancing its tip would keep writing to
        # a project that has been retired.
        case DeleteProject(), ProjectState(status="deleted"):
            raise CommandRejectedError("project already deleted")
        case _, ProjectState(status="deleted"):
            raise CommandRejectedError("project has been deleted")

        # Archiving and unarchiving
        case ArchiveProject(), ProjectState(status="archived"):
            raise CommandRejectedError("project already archived")
        case ArchiveProject(), ProjectState(active_session_id=holder) if holder is not None:
            raise CommandRejectedError(f"project is held by session {holder}")
        case ArchiveProject(), _:
            return [ProjectArchived(aggregate_id=project_id)]

        case UnarchiveProject(), ProjectState(status="archived"):
            return [ProjectUnarchived(aggregate_id=project_id)]
        case UnarchiveProject(), _:
            raise CommandRejectedError("project is not archived")

        # Commands on archived projects that are rejected
        case JoinProject(), ProjectState(status="archived"):
            raise CommandRejectedError("project is archived")
        case AdvanceTip(), ProjectState(status="archived"):
            raise CommandRejectedError("project is archived")
        case RenameProject(), ProjectState(status="archived"):
            raise CommandRejectedError("project is archived")
        case UpdateProjectMetadata(), ProjectState(status="archived"):
            raise CommandRejectedError("project is archived")

        # Renaming
        case RenameProject(name=new_name), _:
            cleaned = new_name.strip()
            if not cleaned:
                raise CommandRejectedError("project name cannot be empty")
            if cleaned == state.name:
                return []
            return [ProjectRenamed(aggregate_id=project_id, name=cleaned)]

        # Metadata and tagging
        case UpdateProjectMetadata(description=desc, tags=tags, metadata=meta), _:
            new_desc = state.description if desc is None else desc.strip()
            if tags is None:
                new_tags = state.tags
            else:
                seen: set[str] = set()
                cleaned_tags: list[str] = []
                for t in tags:
                    cleaned_t = t.strip().lower()
                    if cleaned_t and cleaned_t not in seen:
                        seen.add(cleaned_t)
                        cleaned_tags.append(cleaned_t)
                new_tags = tuple(cleaned_tags)

            if meta is None:
                new_meta = state.metadata
            else:
                new_meta = {k.strip(): v.strip() for k, v in meta.items() if k.strip()}
            return [
                ProjectMetadataUpdated(
                    aggregate_id=project_id,
                    description=new_desc,
                    tags=new_tags,
                    metadata=new_meta,
                )
            ]

        # Held means a session is still driving it. Releasing first is the
        # caller's job, and it is a separate decision -- releasing advances
        # the tip, which is a write to that session's project state, not
        # something deletion should do behind the caller's back.
        case DeleteProject(), ProjectState(active_session_id=holder) if holder is not None:
            raise CommandRejectedError(f"project is held by session {holder}")
        case DeleteProject(), _:
            return [ProjectDeleted(aggregate_id=project_id)]

        case JoinProject(session_id=session_id), ProjectState(active_session_id=None):
            return [
                ProjectSessionJoined(
                    aggregate_id=project_id,
                    session_id=session_id,
                    inherited_at=state.tip_at_event,
                )
            ]
        case JoinProject(), ProjectState(active_session_id=holder):
            # Named, not just refused: the next thing anyone asks is "which one".
            raise CommandRejectedError(f"project is held by session {holder}")

        case AdvanceTip(session_id=session_id, at_event=at), _:
            # Two ways to be allowed to move the tip, and the second one is
            # what stops work from detaching. The holder may move it: that is
            # a release. And the session the tip *already names* may move it
            # further along its own stream while nobody else holds the
            # project: that is a catch-up, and it is the only route by which
            # work done after a release rejoins the project it was done in.
            #
            # Both arms are the same fact -- "this session's stream is the
            # project's filesystem, this far in" -- so they produce the same
            # event. What is refused is a session claiming a stream that is
            # not the project's, and a tip that moves backwards: backwards is
            # not a catch-up, it is a rewrite of which work counts, and there
            # is no caller that means it.
            holds = state.active_session_id == session_id
            catching_up = (
                state.active_session_id is None
                and state.tip_session_id == session_id
                and at > state.tip_at_event
            )
            if not (holds or catching_up):
                raise CommandRejectedError(f"session {session_id} does not hold this project")
            return [
                ProjectTipAdvanced(aggregate_id=project_id, session_id=session_id, at_event=at)
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
            # The event is where the id enters the state: `decide` reads it
            # back off `state` for every command but the first.
            return ProjectState(project_id=event.aggregate_id, status="created", name=name)

        case ProjectSessionJoined(session_id=session_id):
            return state.model_copy(
                update={
                    "member_session_ids": [*state.member_session_ids, session_id],
                    "active_session_id": session_id,
                }
            )

        case ProjectArchived():
            return state.model_copy(update={"status": "archived"})

        case ProjectUnarchived():
            return state.model_copy(update={"status": "created"})

        case ProjectRenamed(name=name):
            return state.model_copy(update={"name": name})

        case ProjectMetadataUpdated(description=description, tags=tags, metadata=metadata):
            return state.model_copy(
                update={"description": description, "tags": tags, "metadata": metadata}
            )

        case ProjectDeleted():
            # Everything else is kept: what the project was, who was in it,
            # and where its tip stood are still the truth about a project
            # that existed. Only its status changes.
            return state.model_copy(update={"status": "deleted"})

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

    Architecturally, while `Session` is the aggregate of turns and file
    mutations, `Project` is the aggregate of cross-session lineage pointers
    (`tip_session_id`, `tip_at_event`), exclusive holding leases
    (`active_session_id`), and lifecycle states (`created`, `archived`,
    `deleted`).

    Everything the library needs from an aggregate (replay, snapshots, version
    checks, repository integration) is inherited; everything this project
    decides lives in the functions above. Mirrors `Session`'s shape
    exactly: the class attributes are bound directly to the module-level
    functions rather than wrapped in new method bodies, so there is exactly
    one implementation of each rule to keep in sync.
    """

    aggregate_type = "Project"

    initial_state = staticmethod(initial_state)
    decide = staticmethod(decide)
    evolve = staticmethod(evolve)
