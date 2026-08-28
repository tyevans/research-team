"""Everything in flight on one project, in one answer.

A course page that shows counters and nothing else cannot answer "what is
happening right now", and the pieces that *could* answer it are scattered:
which sessions belong to the project is a fold, which of them are mid-turn is
the turn supervisor's dict, whether a run is going is the research
supervisor's, and whether extraction is working is the web layer's buffer.
This gathers those into one read.

**Protocols rather than the concrete supervisors.** `application` may not
import `interfaces`, and `test_imports_point_inward` enforces it -- the
extraction buffer lives in the web layer, so it arrives here as a structural
type. The same reasoning `TopicQueuePort` gives applies to all three: a
protocol means this can be tested with a stub and names no adapter.

**Nothing here is state the log does not have, and nothing here is durable.**
Every source is process-local by necessity -- a task cannot be persisted --
so a restart shows an empty roster, which is the truth: nothing is running.
"""

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Literal, Protocol
from uuid import UUID

WorkerKind = Literal["run", "turn", "extraction", "dispatch"]
"""What kind of thing is working.

**A new member must be mapped deliberately in the browser.** `toRoster` in
`mappers.ts` lists the kinds it recognises and falls back to `turn`, which is
not a neutral label but a different specific kind -- #72's dispatches were
displayed as turns for a while, which is a confident wrong answer rather than a
vague one. Adding a member here without adding it there reproduces that.
"""


@dataclass(frozen=True)
class ExtractionSnapshot:
    """One extraction in flight, as the roster needs to describe it.

    Carries no session id, deliberately. The adapter that produces these is
    scoped to a project and knows nothing about sessions; giving it a second
    identity to get wrong would be worse than resolving the containment here.
    See `_parent_for`.
    """

    source_id: str
    stage: str
    detail: str = ""
    index: int | None = None
    total: int | None = None
    started_at: datetime | None = None


@dataclass(frozen=True)
class DispatchSnapshot:
    """One dispatch in flight, as the roster needs to describe it.

    Declared here rather than in the web layer for `ExtractionSnapshot`'s
    reason: `application` may not import `interfaces`, and `DispatchQueue` --
    which produces these -- lives there.

    Carries no session id, matching `ExtractionSnapshot`. A dispatch *does*
    open a session, unlike an extraction, and it is deliberately not reported
    here: that session is already in the roster as a `turn` worker in its own
    right, the same way a run's session is. Naming it twice would have the
    panel offer two rows that open the same transcript.
    """

    topic_id: str
    action: str
    question: str
    queued: int
    started_at: datetime | None = None


@dataclass(frozen=True)
class Worker:
    """One thing working on this project."""

    kind: WorkerKind
    ref: str
    """Identifies this worker within the roster: a run id, a session id, or a
    source id. Text rather than a UUID because the three are different kinds
    of identifier and `parent` has to be comparable across them."""
    detail: str
    """What it is doing, already composed. The reader wants "round 4 ·
    spaced repetition", and composing it here keeps two front ends from
    disagreeing about how to say the same thing."""
    session_id: UUID | None
    """The session whose transcript is this worker's detail view. None for
    extraction, whose detail view is the extraction pane."""
    parent: str | None
    """The `ref` of the worker this one runs inside, when that is known."""
    started_at: datetime | None


@dataclass(frozen=True)
class Roster:
    """What is working on a project, and who is attached but quiet.

    Two fields rather than one list with a flag, because a worker is a thing
    that is working: an idle session is context about who is here, and folding
    it into `workers` would make "is anything running" a filter rather than a
    length.
    """

    project_id: UUID
    workers: tuple[Worker, ...] = ()
    idle_session_ids: tuple[UUID, ...] = ()


class ProjectStates(Protocol):
    """The slice of the session service the roster reads."""

    async def project_state(self, project_id: UUID): ...


class TurnsInFlight(Protocol):
    """Satisfied by `TurnSupervisor`."""

    def running(self, session_id: UUID): ...

    def running_sessions(self) -> Mapping[UUID, object]:
        """Every session mid-turn, keyed by session id.

        Reading the supervisor's own dict rather than asking it once per
        session: `everywhere` has no project to start from, so the alternative
        is listing projects and folding each one to learn its members --
        exactly the cost that method exists to avoid.
        """
        ...


class RunsInFlight(Protocol):
    """Satisfied by `ResearchSupervisor`."""

    def active(self, project_id: UUID): ...

    def active_projects(self) -> Iterable[UUID]:
        """Every project with a run going. Already keyed by project, so this
        is the supervisor's own keys and costs nothing."""
        ...


class ExtractionsInFlight(Protocol):
    """Satisfied by `ExtractionActivity` in the web layer."""

    def in_flight(self, project_id: UUID) -> ExtractionSnapshot | None: ...

    def active_projects(self) -> Iterable[UUID]:
        """Every project with an extraction going, from the buffer's keys."""
        ...


class SessionProjects(Protocol):
    """Which project each session belongs to.

    A turn is keyed by session and a roster is keyed by project, so something
    has to bridge the two. This is a read-model lookup -- `SessionSummaryRow`
    carries `project_id` and it is required -- rather than a fold, which is the
    only reason `everywhere` can be cheap. Satisfied by an adapter over
    `SessionSummaries`.
    """

    async def project_ids(self) -> Mapping[UUID, UUID]: ...


class DispatchesInFlight(Protocol):
    """Satisfied by `DispatchQueue` in the web layer."""

    def in_flight(self, project_id: UUID) -> DispatchSnapshot | None: ...

    def active_projects(self) -> Iterable[UUID]:
        """Every project with a dispatch running, from the queue's own keys.

        Keyed by project already, so this costs nothing -- the same reason
        `RunsInFlight` and `ExtractionsInFlight` can answer it.
        """
        ...


class ExtractionChannel(ExtractionsInFlight, Protocol):
    """Both halves of the extraction channel: what is running, and how to say so.

    One collaborator rather than two parameters, because they are two views of
    one buffer: the roster reads `in_flight`, and the `remember` tool reports
    through `reporter`. A composition root handed mismatched halves would show
    a roster that disagreed with its own pane, and nothing in either signature
    would have caught it.

    Declared here rather than in the web layer for the reason
    `ExtractionsInFlight` is: `application` may not import `interfaces`, and
    `ExtractionActivity` -- which satisfies both halves -- lives there.
    """

    def reporter(self, project_id: UUID): ...


class SummaryProjects:
    """`SessionProjects` over the stored session list.

    An adapter rather than a method on `SessionSummaries`, because "which
    project is this session in" is the roster's question and the summary list
    already answers it -- `project_id` is a required column on the row. Reading
    the projection means this stays a query against a maintained view rather
    than a fold, which is the whole basis of `everywhere`'s cost claim.

    The list is read whole and reduced here. That is one indexed table scan
    against a read model the landing page already reads on every load, and it
    happens only when a turn is actually running -- see `everywhere`.
    """

    def __init__(self, summaries) -> None:
        self._summaries = summaries

    async def project_ids(self) -> dict[UUID, UUID]:
        return {row.session_id: row.project_id for row in await self._summaries.list()}


class WorkerRoster:
    """Assembles one project's roster from whoever knows a piece of it."""

    def __init__(
        self,
        projects: ProjectStates,
        *,
        turns: TurnsInFlight,
        runs: RunsInFlight | None = None,
        extractions: ExtractionsInFlight | None = None,
        dispatches: DispatchesInFlight | None = None,
        summaries: SessionProjects | None = None,
    ) -> None:
        self._projects = projects
        self._turns = turns
        self._runs = runs
        self._extractions = extractions
        self._dispatches = dispatches
        self._summaries = summaries

    async def on(self, project_id: UUID) -> Roster:
        """Everything working on `project_id`, in a fixed order.

        Ordered run, then dispatch, then turns, then extraction -- fixed rather
        than incidental, so the panel does not reshuffle between polls and a
        test can assert on a sequence.

        A dispatch sits with the run rather than with the turns because it is
        the same kind of thing: something a person asked for that holds the
        project and runs turns inside itself. Its own turn still appears in
        `turns` below, exactly as a run's does -- see `DispatchSnapshot` for
        why that duplication is preferred to hiding it.
        """
        state = await self._projects.project_state(project_id)
        members = list(state.member_session_ids)

        run = self._runs.active(project_id) if self._runs is not None else None
        running = [
            turn for turn in (self._turns.running(session) for session in members) if turn
        ]

        workers: list[Worker] = []
        if run is not None:
            workers.append(
                Worker(
                    kind="run",
                    ref=str(run.run_id),
                    detail="autonomous run",
                    session_id=run.session_id,
                    parent=None,
                    started_at=None,
                )
            )
        dispatch = (
            self._dispatches.in_flight(project_id) if self._dispatches is not None else None
        )
        if dispatch is not None:
            workers.append(
                Worker(
                    kind="dispatch",
                    ref=dispatch.topic_id,
                    detail=_dispatch_detail(dispatch),
                    session_id=None,
                    parent=None,
                    started_at=dispatch.started_at,
                )
            )

        workers.extend(
            Worker(
                kind="turn",
                ref=str(turn.session_id),
                detail=f"turn {turn.turn_index}",
                session_id=turn.session_id,
                parent=None,
                started_at=turn.started_at,
            )
            for turn in running
        )

        snapshot = (
            self._extractions.in_flight(project_id) if self._extractions is not None else None
        )
        if snapshot is not None:
            workers.append(
                Worker(
                    kind="extraction",
                    ref=snapshot.source_id,
                    detail=_extraction_detail(snapshot),
                    session_id=None,
                    parent=_parent_for(run, running),
                    started_at=snapshot.started_at,
                )
            )

        busy = {turn.session_id for turn in running}
        return Roster(
            project_id=project_id,
            workers=tuple(workers),
            idle_session_ids=tuple(session for session in members if session not in busy),
        )

    async def everywhere(self) -> tuple[Roster, ...]:
        """Every project that has something running, and what it is running.

        One answer for a reader who is not looking at a project -- a widget on
        every page cannot ask per project, and `/api/projects` folds one
        aggregate per row, so a naive "list projects, roster each" would be
        O(projects) folds on every page load of a console whose most common
        state is that nothing is running at all.

        Instead the candidates come from the three supervisors, which already
        hold exactly what is in flight in process-local dicts: runs and
        extractions are keyed by project, and turns are keyed by session and
        bridged through the summaries read model -- one indexed lookup, not a
        fold. Only the projects that survive that are folded, so **cost is
        proportional to activity rather than to how many projects exist**, and
        the idle case costs zero folds. `test_everywhere_folds_nothing_when_
        nothing_is_running` is what fails if that stops being true.

        Ordered by project id rather than by activity, so a widget listing them
        does not reshuffle between reads for no reason a reader can see.
        """
        active: set[UUID] = set()

        if self._runs is not None:
            active.update(self._runs.active_projects())
        if self._dispatches is not None:
            active.update(self._dispatches.active_projects())
        if self._extractions is not None:
            active.update(self._extractions.active_projects())

        sessions = list(self._turns.running_sessions())
        if sessions:
            # Only paid for when a turn is actually running: a build with just
            # a run going never touches the read model.
            projects = await self._summaries.project_ids() if self._summaries else {}
            # A session the projection has not caught up to is skipped rather
            # than failing the read. It costs one hidden worker for as long as
            # the projection lags; failing would hide every other one too.
            active.update(
                project
                for session in sessions
                if (project := projects.get(session)) is not None
            )

        return tuple([await self.on(project_id) for project_id in sorted(active, key=str)])


def _dispatch_detail(snapshot: DispatchSnapshot) -> str:
    """What it is doing, and how much is behind it.

    Composed here rather than in the browser for the reason `Worker.detail`
    states: the roster on the landing page and the chip on the topic row must
    say the same words about the same work, and two front ends composing it
    separately is two phrasings that will drift.

    The queue count is included because a reader who scrolled away from the
    running row still needs to know something is waiting -- and omitting it
    when the queue is empty keeps the ordinary case short.
    """
    parts = [snapshot.action]
    if snapshot.question:
        parts.append(snapshot.question)
    if snapshot.queued:
        parts.append(f"{snapshot.queued} queued")
    return " · ".join(parts)


def _extraction_detail(snapshot: ExtractionSnapshot) -> str:
    """The stage, with its progress and subject when there are any."""
    parts = [snapshot.stage]
    if snapshot.index is not None and snapshot.total:
        parts[0] = f"{snapshot.stage} {snapshot.index}/{snapshot.total}"
    if snapshot.detail:
        parts.append(snapshot.detail)
    return " · ".join(parts)


def _parent_for(run, running: Iterable) -> str | None:
    """Which worker an extraction is running inside, when that is knowable.

    A run owns whatever extraction is happening: it is the only thing working
    the queue. With no run, one running turn is unambiguous. Two are not, and
    an extraction is shown at top level rather than attached to a guess -- a
    wrong parent claims a containment that is not there, which reads worse
    than no claim at all.
    """
    if run is not None:
        return str(run.run_id)
    turns = list(running)
    if len(turns) == 1:
        return str(turns[0].session_id)
    return None
