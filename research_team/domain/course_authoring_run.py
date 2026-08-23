"""One course-authoring run: which areas it wrote, and into which sessions.

This aggregate exists because a comment said it should not. `authoring.py`'s
`AUTHORING` constant carried:

    Not a domain event and must never become one. What the log records is the
    `write_file` calls each turn makes; "an authoring run started" is not a
    fact the log holds, which is exactly why this module exists.

Every clause was true and the conclusion was backwards, in exactly the shape
CLAUDE.md names: a comment that explains an absence by pointing at another
absence. "The log does not hold it" is the defect, not the premise, and the
question it foreclosed is whether the log *should*.

It should, and the deciding fact is `CourseAuthored.session_id`. Each target is
authored in its own session, and the course markdown lives in that session's
workspace at `/course/areas/<slug>/unit.md`. Nothing else records which session
holds which area: `SessionStarted` carries the project and
`SessionPurpose.COURSE_AUTHORING`, never the slug. So the pairing was reachable
only through a dict in one process, and a restart lost it permanently -- the
files stayed on the log, unfindable, and recovery was archaeology through the
fork tree.

**The path-of-inference that was rejected.** The slug is *technically*
recoverable: the run writes `/course/areas/<slug>/unit.md`, so a projection
could parse the slug back out of a `FileWritten` path on a session whose purpose
is `COURSE_AUTHORING`. That was considered and refused. It makes a directory
naming convention load-bearing across a layer boundary; it cannot distinguish a
target that was authored from one a person hand-edited into place; and it says
nothing about which *run* wrote it, whether that run failed, or whether somebody
stopped it. An inference that is right today and silent when it stops being
right is the failure mode this repository keeps meeting.

**What is here and what is deliberately not.** The events carry facts that
outlive the process: the run began, a target was authored into a session, a
target failed, the run settled. They do not carry `current` -- which area is in
hand right now. That is genuinely process state: nothing is driving a run whose
process is gone, so "current" after a restart would be a claim about work in
progress that is not in progress. `AuthoringActivity` keeps it in memory and the
frame reports `null` for a run it did not start itself.

**Off the live feed**, listed in `UNROUTED_AGGREGATE_TYPES`, for `ResearchRun`'s
reason: `AuthoringActivity` already publishes an `Authoring` frame per target to
the browser, and a second signal for the same repaint is two accounts of one
thing that can disagree with nothing to catch it.
"""

from dataclasses import dataclass
from datetime import datetime
from typing import Literal
from uuid import UUID

from eventsource import CommandRejectedError, DeciderAggregate, DomainEvent, register_event
from pydantic import BaseModel, Field

COURSE_AUTHORING_RUN_AGGREGATE_TYPE = "CourseAuthoringRun"

RunStatus = Literal["running", "done", "failed", "cancelled", "interrupted"]
"""How a run ended, plus the two states that are not an ending.

`interrupted` is never stored and never appended -- it is what a reader derives
for a run whose row says `running` and whose driving task this process does not
hold. See `AuthoringActivity.last`. It is in this alias because it is a value
the wire carries, and leaving it out here would put the wire's vocabulary in a
different place from the aggregate's.
"""

SettledStatus = Literal["done", "failed", "cancelled"]
"""The three a run can actually settle as, and the whole point of the third.

A cancelled run is distinguishable from a failed one because they are different
facts: one is a person pressing stop, the other is the work breaking. Both leave
the same partial set of courses behind, which is exactly why a reader that
cannot tell them apart will misread every one of them.
"""


# ---------------- events ----------------


@register_event
class CourseAuthoringRunStarted(DomainEvent):
    """A run began, over these targets, in this order.

    Must be the first event on the stream -- `decide` refuses every other
    command against a run that has not started.

    `targets` is stored rather than derived from the `CourseAuthored` events
    that follow, because the difference between them is the answer: a run that
    settled with four of nine targets authored is only legible if the nine were
    written down before the four happened.
    """

    aggregate_type: str = COURSE_AUTHORING_RUN_AGGREGATE_TYPE
    project_id: UUID
    kind: str
    """`"area"` for a single area, `"path"` for the whole path. A plain string
    rather than an enum for the reason the wire DTO gives: a build meeting a
    third value should render it rather than refuse the run."""
    targets: list[str]
    started_at: datetime


@register_event
class CourseAuthored(DomainEvent):
    """One target's course was written, and this is the session holding it.

    The event this whole aggregate exists for. `session_id` is not derivable
    from anything else on the log -- see the module docstring.
    """

    aggregate_type: str = COURSE_AUTHORING_RUN_AGGREGATE_TYPE
    project_id: UUID
    target: str
    session_id: UUID


@register_event
class CourseAuthoringFailed(DomainEvent):
    """One target did not get written, and why.

    Per target, not per run: a run over eight areas that lost one to a model
    timeout wrote seven courses that exist, and a single run-level failure
    would hide them. The loop that appends this carries on to the next target
    for the same reason.
    """

    aggregate_type: str = COURSE_AUTHORING_RUN_AGGREGATE_TYPE
    project_id: UUID
    target: str
    detail: str


@register_event
class CourseAuthoringRunSettled(DomainEvent):
    """The run stopped, one way or another. The last event on the stream."""

    aggregate_type: str = COURSE_AUTHORING_RUN_AGGREGATE_TYPE
    project_id: UUID
    status: SettledStatus
    settled_at: datetime


# ---------------- commands ----------------


@dataclass(frozen=True)
class StartCourseAuthoringRun:
    run_id: UUID
    project_id: UUID
    kind: str
    targets: tuple[str, ...]
    started_at: datetime


@dataclass(frozen=True)
class RecordAuthoredCourse:
    run_id: UUID
    target: str
    session_id: UUID


@dataclass(frozen=True)
class RecordAuthoringFailure:
    run_id: UUID
    target: str
    detail: str


@dataclass(frozen=True)
class SettleCourseAuthoringRun:
    run_id: UUID
    status: SettledStatus
    settled_at: datetime


CourseAuthoringRunCommand = (
    StartCourseAuthoringRun
    | RecordAuthoredCourse
    | RecordAuthoringFailure
    | SettleCourseAuthoringRun
)


# ---------------- state ----------------


class CourseAuthoringRunState(BaseModel):
    """Everything derivable from a run's stream.

    `authored` holds pairs rather than two lists, unlike the wire frame, and
    that is deliberate: parallel arrays are the shape `courseLinks` in the
    browser already has to defend against, and a fold that cannot produce a
    length mismatch is better than one that documents what to do about it.
    """

    run_id: UUID | None = None
    project_id: UUID | None = None
    kind: str = ""
    status: Literal["new", "running", "done", "failed", "cancelled"] = "new"
    targets: list[str] = Field(default_factory=list)
    authored: list[tuple[str, UUID]] = Field(default_factory=list)
    failures: list[tuple[str, str]] = Field(default_factory=list)

    @property
    def is_running(self) -> bool:
        return self.status == "running"


def initial_state() -> CourseAuthoringRunState:
    return CourseAuthoringRunState()


# ---------------- decide ----------------


def decide(
    command: CourseAuthoringRunCommand, state: CourseAuthoringRunState
) -> list[DomainEvent]:
    """Which requests are legal, and what facts they produce.

    Every recording command is refused outside `running`. A settled run is a
    closed account: a `CourseAuthored` arriving after `CourseAuthoringRunSettled`
    would mean a course exists that the run's own totals do not include, and the
    projection would write a row whose `status` contradicts its `authored`.
    Refusing here makes that a rejected command at the seam rather than a
    disagreement discovered by a reader much later.
    """
    match command, state:
        case StartCourseAuthoringRun(), CourseAuthoringRunState(status="new"):
            return [
                CourseAuthoringRunStarted(
                    aggregate_id=command.run_id,
                    project_id=command.project_id,
                    kind=command.kind,
                    targets=list(command.targets),
                    started_at=command.started_at,
                )
            ]
        case StartCourseAuthoringRun(), _:
            raise CommandRejectedError("authoring run already started")

        case RecordAuthoredCourse(), CourseAuthoringRunState(status="new"):
            raise CommandRejectedError("authoring run not started")
        case RecordAuthoredCourse(target=target, session_id=session_id), _ if state.is_running:
            return [
                CourseAuthored(
                    aggregate_id=state.run_id,
                    project_id=state.project_id,
                    target=target,
                    session_id=session_id,
                )
            ]
        case RecordAuthoredCourse(), _:
            raise CommandRejectedError(f"authoring run already {state.status}")

        case RecordAuthoringFailure(), CourseAuthoringRunState(status="new"):
            raise CommandRejectedError("authoring run not started")
        case RecordAuthoringFailure(target=target, detail=detail), _ if state.is_running:
            return [
                CourseAuthoringFailed(
                    aggregate_id=state.run_id,
                    project_id=state.project_id,
                    target=target,
                    detail=detail,
                )
            ]
        case RecordAuthoringFailure(), _:
            raise CommandRejectedError(f"authoring run already {state.status}")

        case SettleCourseAuthoringRun(), CourseAuthoringRunState(status="new"):
            raise CommandRejectedError("authoring run not started")
        case SettleCourseAuthoringRun(status=status, settled_at=at), _ if state.is_running:
            return [
                CourseAuthoringRunSettled(
                    aggregate_id=state.run_id,
                    project_id=state.project_id,
                    status=status,
                    settled_at=at,
                )
            ]
        case SettleCourseAuthoringRun(), _:
            raise CommandRejectedError(f"authoring run already {state.status}")

    raise CommandRejectedError(f"unhandled command {type(command).__name__}")


# ---------------- evolve ----------------


def evolve(state: CourseAuthoringRunState, event: DomainEvent) -> CourseAuthoringRunState:
    """What each fact does to the state. Total, like every other fold here."""
    match event:
        case CourseAuthoringRunStarted(project_id=project_id, kind=kind, targets=targets):
            return CourseAuthoringRunState(
                run_id=event.aggregate_id,
                project_id=project_id,
                kind=kind,
                status="running",
                targets=list(targets),
            )

        case CourseAuthored(target=target, session_id=session_id):
            return state.model_copy(
                update={"authored": [*state.authored, (target, session_id)]}
            )

        case CourseAuthoringFailed(target=target, detail=detail):
            return state.model_copy(update={"failures": [*state.failures, (target, detail)]})

        case CourseAuthoringRunSettled(status=status):
            return state.model_copy(update={"status": status})

    return state


class CourseAuthoringRun(DeciderAggregate[CourseAuthoringRunState, CourseAuthoringRunCommand]):
    """The imperative shell. Holds no rules -- it delegates all three."""

    aggregate_type = COURSE_AUTHORING_RUN_AGGREGATE_TYPE

    initial_state = staticmethod(initial_state)
    decide = staticmethod(decide)
    evolve = staticmethod(evolve)
