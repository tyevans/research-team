"""Owning a run in flight: one per project, stopped by asking rather than killing.

The supervisor is driven here with a fake "run" that is just a future somebody
else resolves, so every test is about the lifecycle -- started, refused,
cancelled, reported -- and none of them needs a driver, a queue or a model.
"""

import asyncio
from uuid import uuid4

import pytest

from research_team.application.auto_research import RunReport
from research_team.application.research_supervisor import (
    ResearchSupervisor,
    RunAlreadyActive,
)
from research_team.domain.auto_research import AutoRunState, Budget


class FakeRuns:
    """Folds a run by id, the way the real repository does."""

    def __init__(self, **states):
        self.states = states

    async def load(self, run_id):
        state = self.states.get(str(run_id))
        if state is None:
            raise KeyError(run_id)
        return _Loaded(state)


class _Loaded:
    def __init__(self, state):
        self.state = state


def report(reason="queue_empty", **kwargs):
    return RunReport(
        run_id=kwargs.get("run_id", uuid4()),
        reason=reason,
        rounds=kwargs.get("rounds", 1),
        findings=kwargs.get("findings", 1),
        unexamined_topics=kwargs.get("unexamined_topics", 0),
    )


def controllable():
    """A run that finishes when the test says so, and records how it was asked to stop."""
    gate = asyncio.Event()
    seen = {}

    async def start(
        run_id, project_id, session_id, budget, fetch_hosts, fetch_budget, cancelled
    ):
        seen["run_id"] = run_id
        seen["budget"] = budget
        seen["fetch_hosts"] = fetch_hosts
        seen["fetch_budget"] = fetch_budget
        await gate.wait()
        seen["cancelled"] = cancelled()
        return report(reason="cancelled" if cancelled() else "queue_empty", run_id=run_id)

    return start, gate, seen


async def test_a_started_run_is_named_before_it_has_done_anything():
    """The whole reason `start` is synchronous: HTTP has to answer now."""
    start, gate, seen = controllable()
    supervisor = ResearchSupervisor(start, FakeRuns())
    project_id, session_id = uuid4(), uuid4()

    run = supervisor.start(project_id, session_id)

    assert run.project_id == project_id
    assert run.session_id == session_id
    assert supervisor.active(project_id) == run
    gate.set()
    await supervisor.wait(project_id)
    # The id the caller was given is the id the run was started under, or
    # every status call it makes with it is about a run that never existed.
    assert seen["run_id"] == run.run_id


async def test_a_second_run_on_one_project_is_refused_rather_than_queued():
    """Two runs over one queue would hand each other the same topic."""
    start, gate, _ = controllable()
    supervisor = ResearchSupervisor(start, FakeRuns())
    project_id = uuid4()
    first = supervisor.start(project_id, uuid4())

    with pytest.raises(RunAlreadyActive) as raised:
        supervisor.start(project_id, uuid4())

    # Names the run in the way -- the next thing anyone asks is which one.
    assert str(first.run_id) in str(raised.value)
    gate.set()
    await supervisor.wait(project_id)


async def test_two_projects_run_at_once():
    start, gate, _ = controllable()
    supervisor = ResearchSupervisor(start, FakeRuns())
    first, second = uuid4(), uuid4()

    supervisor.start(first, uuid4())
    supervisor.start(second, uuid4())

    assert supervisor.active(first) is not None
    assert supervisor.active(second) is not None
    gate.set()
    await supervisor.wait(first)
    await supervisor.wait(second)


async def test_a_finished_run_frees_the_project():
    start, gate, _ = controllable()
    supervisor = ResearchSupervisor(start, FakeRuns())
    project_id = uuid4()
    supervisor.start(project_id, uuid4())
    gate.set()
    await supervisor.wait(project_id)

    assert supervisor.active(project_id) is None
    supervisor.start(project_id, uuid4())  # and another may start
    await supervisor.wait(project_id)


async def test_cancelling_asks_the_run_rather_than_killing_the_task():
    """A killed task leaves the stream with no stop event, which is the failure."""
    start, gate, seen = controllable()
    supervisor = ResearchSupervisor(start, FakeRuns())
    project_id = uuid4()
    run = supervisor.start(project_id, uuid4())

    cancelled = supervisor.cancel(project_id)

    assert cancelled == run
    gate.set()
    finished = await supervisor.wait(project_id)
    assert seen["cancelled"] is True
    assert finished.reason == "cancelled"


async def test_cancelling_nothing_is_not_an_error():
    supervisor = ResearchSupervisor(controllable()[0], FakeRuns())
    assert supervisor.cancel(uuid4()) is None


async def test_status_is_folded_from_the_log_not_from_the_task():
    """So a run that ended last week answers the same way as one in flight."""
    run_id = uuid4()
    state = AutoRunState(run_id=run_id, status="stopped", rounds=4, findings=2)
    supervisor = ResearchSupervisor(controllable()[0], FakeRuns(**{str(run_id): state}))

    assert (await supervisor.state(run_id)).rounds == 4
    assert await supervisor.state(uuid4()) is None


async def test_the_budget_reaches_the_run():
    start, gate, seen = controllable()
    supervisor = ResearchSupervisor(start, FakeRuns())
    project_id = uuid4()

    supervisor.start(project_id, uuid4(), budget=Budget(max_rounds=3))
    gate.set()
    await supervisor.wait(project_id)

    assert seen["budget"].max_rounds == 3


async def test_the_fetch_grant_reaches_the_run():
    """The other half of what `start` widened to carry -- see `StartRun`."""
    start, gate, seen = controllable()
    supervisor = ResearchSupervisor(start, FakeRuns())
    project_id = uuid4()

    supervisor.start(
        project_id, uuid4(), fetch_hosts=["a.example", "b.example"], fetch_budget=5
    )
    gate.set()
    await supervisor.wait(project_id)

    assert seen["fetch_hosts"] == ["a.example", "b.example"]
    assert seen["fetch_budget"] == 5


async def test_an_ungranted_run_carries_no_hosts_and_no_budget():
    """The REPL's call site, and every other caller that predates grants:
    nothing asked for, nothing carried."""
    start, gate, seen = controllable()
    supervisor = ResearchSupervisor(start, FakeRuns())
    project_id = uuid4()

    supervisor.start(project_id, uuid4())
    gate.set()
    await supervisor.wait(project_id)

    assert seen["fetch_hosts"] == []
    assert seen["fetch_budget"] == 0


async def test_shutdown_asks_every_run_to_stop_and_waits_for_it():
    """Otherwise the store closes underneath a round still trying to append."""
    start, gate, seen = controllable()
    supervisor = ResearchSupervisor(start, FakeRuns())
    first, second = uuid4(), uuid4()
    supervisor.start(first, uuid4())
    supervisor.start(second, uuid4())

    stopping = asyncio.ensure_future(supervisor.stop_all())
    await asyncio.sleep(0)
    gate.set()
    await stopping

    assert seen["cancelled"] is True
    assert supervisor.active(first) is None
    assert supervisor.active(second) is None


async def test_a_run_that_raises_does_not_take_the_process_with_it():
    """Nobody awaits the task, so a failure has to be logged rather than lost."""

    async def explode(
        run_id, project_id, session_id, budget, fetch_hosts, fetch_budget, cancelled
    ):
        raise RuntimeError("the queue projection is down")

    supervisor = ResearchSupervisor(explode, FakeRuns())
    project_id = uuid4()
    supervisor.start(project_id, uuid4())

    with pytest.raises(RuntimeError):
        await supervisor.wait(project_id)
    assert supervisor.active(project_id) is None
