"""The dispatch queue: one at a time per project, and the rest wait their turn.

`SeedingActivity` and `ResearchSupervisor` both refuse a second start with
`RunAlreadyActive`, which is right for a control that appears once on a page.
A dispatch control appears on every topic row, so refusal is the answer to
nearly every second press and a UI whose primary control usually refuses is a
UI people stop pressing. These tests are the specification for the queue that
replaces the refusal.

Driven with plain futures rather than a real dispatcher: what is under test is
the ordering, the frames and the release, none of which involve a model.
"""

import asyncio
from uuid import uuid4

import pytest

from research_team.application.topic_dispatch import DispatchRun
from research_team.interfaces.web.dispatch import DISPATCH, DispatchQueue


@pytest.fixture
def queue():
    return DispatchQueue()


@pytest.fixture
def project_id():
    return uuid4()


def _run(topic_id, *, gate: asyncio.Event | None = None, fail: str | None = None):
    """A dispatch that finishes when told to, so ordering can be observed."""

    async def run(dispatch_id):
        if gate is not None:
            await gate.wait()
        if fail is not None:
            raise RuntimeError(fail)
        return DispatchRun(
            dispatch_id=dispatch_id,
            project_id=uuid4(),
            topic_id=topic_id,
            session_id=uuid4(),
            action="understanding",
            question="a question",
            path="/topics/00-a-question/understanding.md",
            reply="written",
        )

    return run


async def test_the_first_dispatch_runs_and_reports_itself_running(queue, project_id):
    topic_id = uuid4()
    gate = asyncio.Event()
    queue.start(project_id, topic_id, "understanding", _run(topic_id, gate=gate))

    # One turn of the loop is enough for the drain task to claim the item.
    await asyncio.sleep(0)
    await asyncio.sleep(0)

    current = queue.current(project_id)
    assert current is not None
    assert current["status"] == "running"
    assert current["topic_id"] == str(topic_id)

    gate.set()
    await queue.wait(project_id)


async def test_a_second_dispatch_is_queued_rather_than_refused(queue, project_id):
    """The whole reason this class exists rather than a `RunAlreadyActive`.

    Would pass against a queue that ran both at once, which is what the next
    test rules out.

    The second press answers position 2, not 1, and that is the honest number:
    at the moment the route replies, the drain task has been scheduled and has
    not run, so *both* items are still waiting. Once the first is claimed the
    second renumbers to 1, which is what the reader actually sees."""
    first, second = uuid4(), uuid4()
    gate = asyncio.Event()
    queue.start(project_id, first, "understanding", _run(first, gate=gate))
    frame = queue.start(project_id, second, "understanding", _run(second, gate=gate))

    assert frame["status"] == "queued"
    assert frame["position"] == 2

    await asyncio.sleep(0)
    await asyncio.sleep(0)
    assert [item["topic_id"] for item in queue.queued(project_id)] == [str(second)]
    assert [item["position"] for item in queue.queued(project_id)] == [1]

    gate.set()
    await queue.wait(project_id)


async def test_only_one_dispatch_holds_the_project_at_a_time(queue, project_id):
    """The constraint the queue exists to respect: `Project.decide` refuses a
    second `JoinProject`, so two dispatches running at once would have one of
    them fail on a refusal the user never asked for."""
    live: list[str] = []
    peak = 0

    def _tracked(topic_id, gate):
        async def run(dispatch_id):
            nonlocal peak
            live.append(str(topic_id))
            peak = max(peak, len(live))
            await gate.wait()
            live.remove(str(topic_id))
            return DispatchRun(
                dispatch_id=dispatch_id,
                project_id=project_id,
                topic_id=topic_id,
                session_id=uuid4(),
                action="understanding",
                question="q",
                path="/topics/00-q/understanding.md",
                reply="",
            )

        return run

    gate = asyncio.Event()
    topics = [uuid4() for _ in range(3)]
    for topic_id in topics:
        queue.start(project_id, topic_id, "understanding", _tracked(topic_id, gate))

    await asyncio.sleep(0)
    gate.set()
    await queue.wait(project_id)

    assert peak == 1


async def test_dispatches_run_in_the_order_they_were_pressed(queue, project_id):
    order: list[str] = []

    def _recording(topic_id):
        async def run(dispatch_id):
            order.append(str(topic_id))
            return DispatchRun(
                dispatch_id=dispatch_id,
                project_id=project_id,
                topic_id=topic_id,
                session_id=uuid4(),
                action="understanding",
                question="q",
                path="/p/understanding.md",
                reply="",
            )

        return run

    topics = [uuid4() for _ in range(4)]
    for topic_id in topics:
        queue.start(project_id, topic_id, "understanding", _recording(topic_id))

    await queue.wait(project_id)

    assert order == [str(topic_id) for topic_id in topics]


async def test_a_failed_dispatch_does_not_stall_the_ones_behind_it(queue, project_id):
    """A queue that stopped draining on the first failure would turn one model
    timeout into a project that ignores every later press -- and the log would
    say nothing about why, because a dispatch records no event of its own."""
    first, second = uuid4(), uuid4()
    queue.start(project_id, first, "understanding", _run(first, fail="model timed out"))
    queue.start(project_id, second, "understanding", _run(second))

    await queue.wait(project_id)

    assert queue.last(project_id, first)["status"] == "failed"
    assert queue.last(project_id, first)["detail"] == "model timed out"
    assert queue.last(project_id, second)["status"] == "done"


async def test_the_last_outcome_is_kept_per_topic_not_per_project(queue, project_id):
    """Each topic row shows its own last result, so one project's two topics
    must not overwrite each other's. Would pass with a per-project dict if
    only one topic were ever dispatched, which is why two are."""
    first, second = uuid4(), uuid4()
    queue.start(project_id, first, "understanding", _run(first, fail="boom"))
    queue.start(project_id, second, "understanding", _run(second))
    await queue.wait(project_id)

    assert queue.last(project_id, first)["status"] == "failed"
    assert queue.last(project_id, second)["status"] == "done"


async def test_a_finished_dispatch_reports_the_file_it_wrote(queue, project_id):
    """Without the path, the "open what it wrote" affordance has nothing to
    open -- the file is on a session the browser has no other handle on."""
    topic_id = uuid4()
    queue.start(project_id, topic_id, "understanding", _run(topic_id))
    await queue.wait(project_id)

    finished = queue.last(project_id, topic_id)
    assert finished["path"] == "/topics/00-a-question/understanding.md"
    assert finished["session_id"]


async def test_cancelling_clears_the_queue_and_stops_what_is_running(queue, project_id):
    topics = [uuid4() for _ in range(3)]
    gate = asyncio.Event()
    for topic_id in topics:
        queue.start(project_id, topic_id, "understanding", _run(topic_id, gate=gate))
    await asyncio.sleep(0)
    await asyncio.sleep(0)

    queue.cancel(project_id)
    await queue.wait(project_id)

    assert queue.current(project_id) is None
    assert queue.queued(project_id) == []


async def test_cancelling_lets_a_later_dispatch_start(queue, project_id):
    """Cancel must leave the project dispatchable. A drain loop that exited
    without clearing its own bookkeeping would leave every later press
    enqueued behind a task that had already gone."""
    first, second = uuid4(), uuid4()
    gate = asyncio.Event()
    queue.start(project_id, first, "understanding", _run(first, gate=gate))
    await asyncio.sleep(0)
    await asyncio.sleep(0)
    queue.cancel(project_id)
    await queue.wait(project_id)

    queue.start(project_id, second, "understanding", _run(second))
    await queue.wait(project_id)

    assert queue.last(project_id, second)["status"] == "done"


async def test_two_projects_dispatch_in_parallel(queue):
    """The constraint is per project and this must not quietly become global.
    Would pass against a global queue if the two never overlapped, so both
    are held open at once and the second is asserted to have started."""
    one, two = uuid4(), uuid4()
    gate = asyncio.Event()
    queue.start(one, uuid4(), "understanding", _run(uuid4(), gate=gate))
    queue.start(two, uuid4(), "understanding", _run(uuid4(), gate=gate))
    await asyncio.sleep(0)
    await asyncio.sleep(0)

    assert queue.current(one) is not None
    assert queue.current(two) is not None

    gate.set()
    await queue.wait(one)
    await queue.wait(two)


async def test_every_transition_is_announced_to_listeners(queue, project_id):
    """The SSE side of the channel. A frame that is recorded but not announced
    leaves a connected browser showing "queued" until it reloads."""
    listening = queue.listen()
    topic_id = uuid4()
    queue.start(project_id, topic_id, "understanding", _run(topic_id))
    await queue.wait(project_id)

    seen = []
    while not listening.empty():
        seen.append(listening.get_nowait())

    assert [frame["status"] for frame in seen] == ["queued", "running", "done"]
    assert {frame["type"] for frame in seen} == {DISPATCH}
    queue.stop_listening(listening)


async def test_queue_positions_are_renumbered_as_the_queue_drains(queue, project_id):
    """A position that never moved would tell the third presser they are still
    third after the first two finished."""
    gate = asyncio.Event()
    topics = [uuid4() for _ in range(3)]
    for topic_id in topics:
        queue.start(project_id, topic_id, "understanding", _run(topic_id, gate=gate))

    assert [item["position"] for item in queue.queued(project_id)] == [1, 2, 3]

    await asyncio.sleep(0)
    await asyncio.sleep(0)
    assert [item["position"] for item in queue.queued(project_id)] == [1, 2]

    gate.set()
    await queue.wait(project_id)


async def test_the_roster_sees_a_running_dispatch(queue, project_id):
    """`WorkerRoster` reads this project-scoped view, so the landing page and
    the topic row say the same words about the same work."""
    topic_id = uuid4()
    gate = asyncio.Event()
    queue.start(
        project_id,
        topic_id,
        "understanding",
        _run(topic_id, gate=gate),
        question="spaced repetition",
    )
    await asyncio.sleep(0)
    await asyncio.sleep(0)

    snapshot = queue.in_flight(project_id)
    assert snapshot is not None
    assert snapshot.action == "understanding"
    assert snapshot.question == "spaced repetition"
    assert snapshot.queued == 0

    gate.set()
    await queue.wait(project_id)
    assert queue.in_flight(project_id) is None
