from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest

from research_team.application.workers import (
    DispatchSnapshot,
    ExtractionSnapshot,
    WorkerRoster,
)
from research_team.domain.project import ProjectState

AT = datetime(2026, 8, 7, 12, 0, tzinfo=UTC)


@dataclass(frozen=True)
class FakeRunningTurn:
    session_id: UUID
    turn_index: int
    started_at: datetime


@dataclass(frozen=True)
class FakeActiveRun:
    run_id: UUID
    project_id: UUID
    session_id: UUID


class FakeTurns:
    """A `TurnsInFlight` over a dict."""

    def __init__(self, running: dict[UUID, FakeRunningTurn]) -> None:
        self._running = running

    def running(self, session_id: UUID):
        return self._running.get(session_id)


class FakeRuns:
    def __init__(self, run: FakeActiveRun | None) -> None:
        self._run = run

    def active(self, project_id: UUID):
        return self._run


class FakeExtractions:
    def __init__(self, snapshot: ExtractionSnapshot | None) -> None:
        self._snapshot = snapshot

    def in_flight(self, project_id: UUID):
        return self._snapshot


class FakeDispatches:
    def __init__(self, snapshot: DispatchSnapshot | None) -> None:
        self._snapshot = snapshot

    def in_flight(self, project_id: UUID):
        return self._snapshot


class FakeProjects:
    """The slice of the session service the roster uses."""

    def __init__(self, state: ProjectState) -> None:
        self._state = state

    async def project_state(self, project_id: UUID) -> ProjectState:
        return self._state


def state_with(project_id: UUID, members: list[UUID]) -> ProjectState:
    return ProjectState(
        project_id=project_id, status="created", name="course", member_session_ids=members
    )


@pytest.mark.asyncio
async def test_a_running_turn_is_a_worker_and_a_quiet_session_is_idle():
    project_id, busy, quiet = uuid4(), uuid4(), uuid4()
    roster = WorkerRoster(
        FakeProjects(state_with(project_id, [busy, quiet])),
        turns=FakeTurns({busy: FakeRunningTurn(busy, 12, AT)}),
        runs=None,
        extractions=None,
    )

    result = await roster.on(project_id)

    assert [w.kind for w in result.workers] == ["turn"]
    assert result.workers[0].session_id == busy
    assert result.workers[0].detail == "turn 12"
    assert result.workers[0].started_at == AT
    assert result.idle_session_ids == (quiet,)


@pytest.mark.asyncio
async def test_the_run_comes_first_and_extraction_nests_under_it():
    project_id, run_session = uuid4(), uuid4()
    run = FakeActiveRun(uuid4(), project_id, run_session)
    roster = WorkerRoster(
        FakeProjects(state_with(project_id, [run_session])),
        turns=FakeTurns({run_session: FakeRunningTurn(run_session, 4, AT)}),
        runs=FakeRuns(run),
        extractions=FakeExtractions(
            ExtractionSnapshot(
                source_id="roediger-2006",
                stage="consolidating",
                detail="Henry L. Roediger III",
                index=7,
                total=23,
                started_at=AT,
            )
        ),
    )

    result = await roster.on(project_id)

    assert [w.kind for w in result.workers] == ["run", "turn", "extraction"]
    assert result.workers[0].ref == str(run.run_id)
    extraction = result.workers[-1]
    assert extraction.parent == str(run.run_id)
    assert extraction.detail == "consolidating 7/23 · Henry L. Roediger III"
    # Extraction opens no session of its own: the pane is its detail view.
    assert extraction.session_id is None


@pytest.mark.asyncio
async def test_extraction_nests_under_the_only_turn_when_no_run_is_active():
    project_id, session_id = uuid4(), uuid4()
    roster = WorkerRoster(
        FakeProjects(state_with(project_id, [session_id])),
        turns=FakeTurns({session_id: FakeRunningTurn(session_id, 3, AT)}),
        runs=None,
        extractions=FakeExtractions(
            ExtractionSnapshot("notes", "extracting", "", None, None, AT)
        ),
    )

    result = await roster.on(project_id)

    assert result.workers[-1].parent == str(session_id)


@pytest.mark.asyncio
async def test_extraction_is_top_level_when_the_owner_is_ambiguous():
    """Two turns and no run: nothing here knows which one called `remember`.

    Shown at top level rather than attached to a guess. A wrong parent claims
    a containment that is not there, which is worse than none.
    """
    project_id, one, two = uuid4(), uuid4(), uuid4()
    roster = WorkerRoster(
        FakeProjects(state_with(project_id, [one, two])),
        turns=FakeTurns({one: FakeRunningTurn(one, 1, AT), two: FakeRunningTurn(two, 1, AT)}),
        runs=None,
        extractions=FakeExtractions(
            ExtractionSnapshot("notes", "extracting", "", None, None, AT)
        ),
    )

    result = await roster.on(project_id)

    assert result.workers[-1].parent is None


@pytest.mark.asyncio
async def test_a_project_with_nothing_running_has_no_workers():
    project_id, session_id = uuid4(), uuid4()
    roster = WorkerRoster(
        FakeProjects(state_with(project_id, [session_id])),
        turns=FakeTurns({}),
        runs=None,
        extractions=None,
    )

    result = await roster.on(project_id)

    assert result.workers == ()
    assert result.idle_session_ids == (session_id,)


@pytest.mark.asyncio
async def test_a_running_dispatch_is_a_worker_with_its_action_and_topic():
    """`Worker.detail` is composed server-side so the landing-page roster and
    the topic row say the same words. Asserted on the exact string for that
    reason -- two front ends phrasing it themselves is the failure."""
    project_id, session_id = uuid4(), uuid4()
    roster = WorkerRoster(
        FakeProjects(state_with(project_id, [session_id])),
        turns=FakeTurns({}),
        dispatches=FakeDispatches(
            DispatchSnapshot(
                topic_id="t-1",
                action="understanding",
                question="spaced repetition",
                queued=0,
                started_at=AT,
            )
        ),
    )

    result = await roster.on(project_id)

    assert [w.kind for w in result.workers] == ["dispatch"]
    assert result.workers[0].detail == "understanding · spaced repetition"
    assert result.workers[0].ref == "t-1"
    assert result.workers[0].started_at == AT


@pytest.mark.asyncio
async def test_a_dispatch_says_how_many_are_waiting_behind_it():
    """A reader who scrolled away from the running row still needs to know
    something is queued. Would pass with the count omitted if the queue were
    always empty, which is why this one is not."""
    project_id = uuid4()
    roster = WorkerRoster(
        FakeProjects(state_with(project_id, [])),
        turns=FakeTurns({}),
        dispatches=FakeDispatches(
            DispatchSnapshot(
                topic_id="t-1", action="understanding", question="retention", queued=2
            )
        ),
    )

    result = await roster.on(project_id)

    assert result.workers[0].detail == "understanding · retention · 2 queued"


@pytest.mark.asyncio
async def test_a_dispatch_comes_after_the_run_and_before_the_turns():
    """The order is fixed rather than incidental, so the panel does not
    reshuffle between polls."""
    project_id, run_session, busy = uuid4(), uuid4(), uuid4()
    run = FakeActiveRun(uuid4(), project_id, run_session)
    roster = WorkerRoster(
        FakeProjects(state_with(project_id, [busy])),
        turns=FakeTurns({busy: FakeRunningTurn(busy, 3, AT)}),
        runs=FakeRuns(run),
        dispatches=FakeDispatches(
            DispatchSnapshot(topic_id="t-1", action="understanding", question="q", queued=0)
        ),
    )

    result = await roster.on(project_id)

    assert [w.kind for w in result.workers] == ["run", "dispatch", "turn"]


@pytest.mark.asyncio
async def test_the_composition_root_wires_a_roster(db_path):
    """A built application can answer "what is running" without more wiring.

    Asserted here rather than left to the web tests because both front ends
    are entitled to the roster, and a CLI that had to build its own would end
    up with a second one disagreeing with the first.
    """
    from research_team import composition

    app = composition.build_application(db_path=db_path)

    assert app.workers is not None
