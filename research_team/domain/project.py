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

from research_team.domain.targeting import ChecksCommandTarget
from research_team.domain.workflow import Preset, Stage


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
class WorkflowSelected(DomainEvent):
    """This project is running an instructional-design preset.

    Records the preset by id and version rather than by value. A preset is
    hundreds of lines of prompts and checks, and copying it into the log would
    both bloat every snapshot and freeze a typo forever; the id is the stable
    thing, and the version is what lets a later reader tell whether the preset
    they are holding is the one this run was gated by.
    """

    aggregate_type: str = "Project"
    preset_id: str
    preset_version: str


@register_event
class StageAdvanced(DomainEvent):
    """A stage was completed and the project moved to the next one.

    `from_stage` is recorded even though it is derivable, because the point of
    this event is the transition rather than the destination: an audit that has
    to re-fold the whole stream to learn what a decision was made *about* is
    not much of an audit.
    """

    aggregate_type: str = "Project"
    from_stage: str
    to_stage: str
    decided_by: str
    gate_decision: str


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
    session_id: UUID
    at_event: int


@dataclass(frozen=True)
class DeleteProject:
    pass


@dataclass(frozen=True)
class SelectWorkflow:
    preset: Preset


@dataclass(frozen=True)
class AdvanceStage:
    """Move to `to_stage`, with the preset the caller believes is running.

    The preset travels on the command because ordering cannot be checked
    without the stage list, and the domain will not reach for a registry to
    find one -- that would make `decide` depend on module import order and on
    whichever presets happen to be shipped. Carrying it makes the disagreement
    between caller and aggregate visible, which `decide` then rejects.
    """

    preset: Preset
    to_stage: str
    decided_by: str
    gate_decision: str


ProjectCommand = (
    CreateProject | JoinProject | AdvanceTip | DeleteProject | SelectWorkflow | AdvanceStage
)


class ProjectState(BaseModel):
    """Everything derivable from the project's event stream."""

    project_id: UUID | None = None
    """None before the project exists. Set by the fold of `ProjectCreated`.

    Optional because `initial_state()` takes no arguments (eventsource 0.12):
    the value before any event is one value for the aggregate *type*, and an
    id is not part of it.
    """

    status: Literal["new", "created", "deleted"] = "new"
    name: str = ""
    member_session_ids: list[UUID] = Field(default_factory=list)
    active_session_id: UUID | None = None
    """The session currently holding the project, if any."""
    tip_session_id: UUID | None = None
    """Whose stream the filesystem folds from. None means the project is empty."""
    tip_at_event: int = 0
    """How far into that stream to fold."""

    preset_id: str | None = None
    """Which workflow this project runs. `None` means none was ever selected,
    which is what every project written before workflows existed meant."""
    preset_version: str | None = None
    """The preset version in force when it was selected. Kept so a later reader
    can tell whether the preset they hold is the one this run was gated by."""
    current_stage: str | None = None
    """The stage last advanced *into*. `None` with a preset selected means the
    preset's first stage: selecting a workflow puts a project at its start, but
    no event records entering a stage nobody advanced to, and `evolve` cannot
    look a preset up to fill it in. `current_stage_of` resolves the two cases
    into one answer for anyone who has the preset in hand."""
    stage_history: list[str] = Field(default_factory=list)
    """Every stage advanced into, in order. Excludes the first stage for the
    same reason `current_stage` starts `None` -- nothing was decided to get
    there, so there is no decision to record."""


def initial_state() -> ProjectState:
    return ProjectState()


def current_stage_of(state: ProjectState, preset: Preset) -> Stage | None:
    """Where this project stands in that preset, or None if it runs no workflow.

    The seam between a fold that cannot know the preset and callers that do --
    `StageMiddleware`'s constructor argument comes from here. Deliberately does
    not check that `preset` is the one the project selected: this answers "where
    would this project be in this preset", and the caller that fetched the
    preset by `state.preset_id` already knows. `decide` does check, because
    there a mismatch would let one preset's ordering gate another's run.
    """
    if state.preset_id is None:
        return None
    stage_id = state.current_stage or preset.stages[0].id
    return next((stage for stage in preset.stages if stage.id == stage_id), None)


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
                SessionJoinedProject(
                    aggregate_id=project_id,
                    session_id=session_id,
                    inherited_at=state.tip_at_event,
                )
            ]
        case JoinProject(), ProjectState(active_session_id=holder):
            # Named, not just refused: the next thing anyone asks is "which one".
            raise CommandRejectedError(f"project is held by session {holder}")

        case SelectWorkflow(), ProjectState(preset_id=current) if current is not None:
            # Named, like `JoinProject`'s refusal: the caller's next question is
            # "which one, then". There is no re-selection because a run's whole
            # audit trail is gated by one preset's stage list -- swapping it
            # midway would leave decisions recorded against rules that no
            # longer exist. Forking, or a new project, is the way out.
            raise CommandRejectedError(
                f"project is running workflow {current} v{state.preset_version}"
            )
        case SelectWorkflow(preset=preset), _:
            return [
                WorkflowSelected(
                    aggregate_id=project_id,
                    preset_id=preset.id,
                    preset_version=preset.version,
                )
            ]

        case AdvanceStage(), ProjectState(preset_id=None):
            raise CommandRejectedError("project has no workflow selected")
        case AdvanceStage(preset=preset), _ if preset.id != state.preset_id:
            raise CommandRejectedError(
                f"project runs workflow {state.preset_id}, not {preset.id}"
            )
        case AdvanceStage(preset=preset, to_stage=to_stage), _:
            return [_advanced(state, command, preset, to_stage)]

        case AdvanceTip(session_id=session_id, at_event=at), _:
            if state.active_session_id != session_id:
                raise CommandRejectedError(f"session {session_id} does not hold this project")
            return [
                ProjectTipAdvanced(aggregate_id=project_id, session_id=session_id, at_event=at)
            ]

    raise CommandRejectedError(f"unhandled command {type(command).__name__}")


def _advanced(
    state: ProjectState, command: "AdvanceStage", preset: Preset, to_stage: str
) -> StageAdvanced:
    """The one legal move from where this project stands, or a refusal.

    Only the immediately next stage is legal. Skipping ahead is the failure the
    whole workflow engine exists to prevent -- an artifact produced without the
    stage that was supposed to constrain it looks identical to one produced
    with it. Going back is refused too, though for a different reason: revision
    is real and necessary, but it is an amendment emitted *to* an earlier stage
    rather than a return to it, and conflating the two would let a run quietly
    re-run a gate it had already passed.

    Lifted out of `decide`'s match rather than written as more `case` arms
    because these are four refusals over one situation, and as cases they would
    each have to re-derive the current stage from the preset.
    """
    ids = [stage.id for stage in preset.stages]
    current = state.current_stage or ids[0]
    at = ids.index(current)
    if at == len(ids) - 1:
        raise CommandRejectedError(f"project is at the final stage of {preset.id}: {current}")
    if to_stage not in ids:
        raise CommandRejectedError(f"workflow {preset.id} has no stage {to_stage}")
    expected = ids[at + 1]
    if to_stage != expected:
        raise CommandRejectedError(
            f"project is at {current}; the next stage is {expected}, not {to_stage}"
        )
    return StageAdvanced(
        aggregate_id=state.project_id,
        from_stage=current,
        to_stage=to_stage,
        decided_by=command.decided_by,
        gate_decision=command.gate_decision,
    )


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

        case SessionJoinedProject(session_id=session_id):
            return state.model_copy(
                update={
                    "member_session_ids": [*state.member_session_ids, session_id],
                    "active_session_id": session_id,
                }
            )

        case WorkflowSelected(preset_id=preset_id, preset_version=version):
            return state.model_copy(update={"preset_id": preset_id, "preset_version": version})

        case StageAdvanced(to_stage=to_stage):
            return state.model_copy(
                update={
                    "current_stage": to_stage,
                    "stage_history": [*state.stage_history, to_stage],
                }
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


class Project(ChecksCommandTarget, DeciderAggregate[ProjectState, ProjectCommand]):
    """The imperative shell. Holds no rules -- it delegates all three.

    Everything the library needs from an aggregate (replay, snapshots, version
    checks, repository integration) is inherited; everything this project
    decides lives in the functions above. Mirrors `CodingSession`'s shape
    exactly: the class attributes are bound directly to the module-level
    functions rather than wrapped in new method bodies, so there is exactly
    one implementation of each rule to keep in sync.
    """

    aggregate_type = "Project"
    target_field = "project_id"

    initial_state = staticmethod(initial_state)
    decide = staticmethod(decide)
    evolve = staticmethod(evolve)
