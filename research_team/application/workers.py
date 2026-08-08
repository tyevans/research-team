"""Everything in flight on one project, in one answer.

A course page that shows counters and nothing else cannot answer "what is
happening right now", and the pieces that *could* answer it are scattered:
which sessions belong to the project is a fold, which of them are mid-turn is
the turn supervisor's dict, whether a run is going is the research
supervisor's, and whether extraction is working is the web layer's buffer.
This gathers those four into one read.

**Protocols rather than the concrete supervisors.** `application` may not
import `interfaces`, and `test_imports_point_inward` enforces it -- the
extraction buffer lives in the web layer, so it arrives here as a structural
type. The same reasoning `TopicQueuePort` gives applies to all three: a
protocol means this can be tested with a stub and names no adapter.

**Nothing here is state the log does not have, and nothing here is durable.**
Every source is process-local by necessity -- a task cannot be persisted --
so a restart shows an empty roster, which is the truth: nothing is running.
"""

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime
from typing import Literal, Protocol
from uuid import UUID

WorkerKind = Literal["run", "turn", "extraction"]


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


class RunsInFlight(Protocol):
    """Satisfied by `ResearchSupervisor`."""

    def active(self, project_id: UUID): ...


class ExtractionsInFlight(Protocol):
    """Satisfied by `ExtractionActivity` in the web layer."""

    def in_flight(self, project_id: UUID) -> ExtractionSnapshot | None: ...


class WorkerRoster:
    """Assembles one project's roster from whoever knows a piece of it."""

    def __init__(
        self,
        projects: ProjectStates,
        *,
        turns: TurnsInFlight,
        runs: RunsInFlight | None = None,
        extractions: ExtractionsInFlight | None = None,
    ) -> None:
        self._projects = projects
        self._turns = turns
        self._runs = runs
        self._extractions = extractions

    async def on(self, project_id: UUID) -> Roster:
        """Everything working on `project_id`, in a fixed order.

        Ordered run, then turns, then extraction -- fixed rather than
        incidental, so the panel does not reshuffle between polls and a test
        can assert on a sequence.
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
