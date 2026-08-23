"""An authoring run's area-to-session mapping, over a real restart.

The bug this file exists for: an authoring run's `completed` list and its
parallel `sessions` list lived in a dict on one `AuthoringActivity` instance,
and that pairing is the only route back to the files the run wrote -- each
target is authored in its own session, and the course markdown lives in that
session's workspace. Restart the server and the mapping was gone permanently.
The markdown stayed on the log, unfindable, and recovery was archaeology
through the session fork tree.

Everything else about authoring is green in a build where `composition.py`
never constructs an `AuthoringRunRunner`, for the reason `eventsource.replay`
states and `test_a_dialogue_survives_a_restart.py` opens with: the events are
appended, nothing is subscribed to them, and an event no projection handles
counts as APPLIED rather than rejected. Nothing raises and nothing logs. So
**every assertion below is on a session id**, never on a request succeeding, a
status being reported, or `start()` returning.

Two applications over one database file, the second standing in for the
restart, exactly as `test_ask_survives_a_restart.py` does. The second one has
never seen this run in memory -- its `AuthoringActivity` is a fresh object --
so the only way a session id can reach it is through the table the first
application's events built.

**The author is a stub, stated rather than implied.** A real one is three model
turns per area against a joined project, which is `test_course_authoring.py`'s
subject. What is composed here is everything between the route and the log: the
aggregate, its repository, the projection, the runner, and the frame
`AuthoringActivity` builds out of a stored row.
"""

import asyncio
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest
from httpx import ASGITransport, AsyncClient
from langchain_core.language_models.fake_chat_models import FakeMessagesListChatModel

from research_team.composition import build_application
from research_team.interfaces.web import create_app
from research_team.interfaces.web.authoring import AuthoringActivity

pytestmark = pytest.mark.asyncio


class StubAuthor:
    """Answers with a session id per target and runs no turns.

    `sessions` records what it handed out, so the test can compare the mapping
    read back after the restart against the one that was actually produced --
    rather than against a list the test also invented, which would pass if the
    projection stored the wrong ids consistently.
    """

    def __init__(self) -> None:
        self.sessions: dict[str, UUID] = {}
        #: Set to a target's slug to make that one target raise.
        self.fail_on: str | None = None
        #: Awaited before each target, so a test can hold a run open.
        self.gate: asyncio.Event | None = None
        #: One permit per target allowed to finish. See the note in
        #: `tests/interfaces/test_curriculum_routes.py`'s `StubAuthor`: an
        #: event cannot express "let exactly one through", and the cancel
        #: test that tried failed on CI where the window is wider.
        self.permits: asyncio.Semaphore | None = None

    async def _one(self, target: str):
        if self.permits is not None:
            await self.permits.acquire()
        if self.gate is not None:
            await self.gate.wait()
        if target == self.fail_on:
            raise RuntimeError("the model refused")
        session_id = uuid4()
        self.sessions[target] = session_id
        return SimpleNamespace(session_id=session_id)

    async def author_area(self, project_id, area, subject, *, lesson_count=3, run_id=None):
        return await self._one(area.slug)

    async def author_path(self, project_id, path, areas, *, run_id=None):
        return await self._one(path.slug)


@pytest.fixture
def db_file(tmp_path) -> str:
    return str(tmp_path / "authoring-restart.db")


async def _application(db_file):
    application = build_application(
        model=FakeMessagesListChatModel(responses=[]), db_path=db_file
    )
    await application.start()
    return application


def _activity(application) -> AuthoringActivity:
    """A fresh activity over the composed repository and runner.

    Fresh on purpose in the second application: an activity that had carried
    its dict across would answer from memory and prove nothing.
    """
    return AuthoringActivity(application.authoring_runs, application.authoring)


async def _project(application) -> UUID:
    api = create_app(application.service, application.feed, application.turns)
    transport = ASGITransport(app=api)
    async with AsyncClient(transport=transport, base_url="http://test") as http:
        created = await http.post("/api/projects", json={"name": f"authoring-{uuid4()}"})
        assert created.status_code == 200
        return UUID(created.json()["id"])


async def _run(activity, project_id, author, targets, *, kind="path"):
    await activity.start(
        project_id, targets, lambda _run_id, target: author._one(target), kind=kind
    )
    await activity.wait(project_id)


async def test_every_authored_area_resolves_to_its_session_after_a_restart(db_file):
    """The acceptance test, and the whole reason for the change.

    Red against the build this replaced: `last()` read a dict that the second
    application does not have, so it answered `None` and the `assert` on
    `completed` failed with nothing raising anywhere.

    Red *also* against a build that appends but wires no runner -- the row is
    never written, `recent_for_project` comes back empty, and this fails on
    the same line. That is the case a test asserting "the request succeeded"
    could not tell apart from success.
    """
    first = await _application(db_file)
    author = StubAuthor()
    try:
        project_id = await _project(first)
        await _run(_activity(first), project_id, author, ["rome", "carthage", "complete"])
        await first.authoring.caught_up()
    finally:
        await first.close()

    second = await _application(db_file)
    try:
        run = await _activity(second).last(project_id)
        assert run is not None, "no run: nothing is following the authoring log"
        assert run["status"] == "done"
        assert run["completed"] == ["rome", "carthage", "complete"]
        # The assertion that matters: the ids read back are the ids the author
        # actually handed out, not merely three well-formed UUIDs.
        assert dict(zip(run["completed"], run["sessions"], strict=True)) == {
            target: str(session_id) for target, session_id in author.sessions.items()
        }
    finally:
        await second.close()


async def test_a_run_interrupted_by_a_restart_reports_interrupted_and_keeps_its_courses(
    db_file,
):
    """A run still in flight when the process died is not `running` afterwards.

    Nothing is driving it any more, so reporting `running` would be a claim
    about work in progress that no process is doing -- a panel would poll it
    forever. It is not `failed` either: the targets it did author exist, and
    this asserts their session ids come back.

    The run is left mid-flight by letting exactly two targets finish and then
    closing the application without waiting, which is what a `kill -9` looks
    like from the log's point of view: a start event, two authored events, and
    no settle.
    """
    first = await _application(db_file)
    author = StubAuthor()
    # Two permits rather than a gate, and this is a fix rather than a style
    # choice. The gate version set the event, waited for `sessions` to reach 2
    # and then cleared it -- which leaves a window between the second target
    # recording its session and the clear taking effect, and the third target
    # only has to pass `gate.wait()` inside that window to finish. Then the run
    # settles, and `status` reads `done` where this asserts `interrupted`.
    #
    # Observed on CI at 5b08f66 and 0ecfb16 as `assert 'done' == 'interrupted'`,
    # and *not* reproducible locally: eight runs of the unmodified test on this
    # machine all passed. That direction is the tell and is why this is a race
    # rather than a wrong expectation -- the failure needs a wider window than a
    # quiet machine gives it, which is exactly what `StubAuthor.permits`
    # documents about the cancel test that tried an event first and "failed on
    # CI where the window is wider".
    #
    # A semaphore has no window. The third target blocks in `acquire()` before
    # it can do anything, however the scheduler interleaves, so the precondition
    # is established by construction instead of by observation.
    #
    # Still measuring what it says it measures: released to `Semaphore(3)` the
    # run finishes and this fails at the `interrupted` assertion. So the two is
    # load-bearing and the test is not green because interruption is the
    # default answer.
    author.permits = asyncio.Semaphore(2)
    try:
        project_id = await _project(first)
        activity = _activity(first)
        await activity.start(
            project_id,
            ["rome", "carthage", "complete"],
            lambda _run_id, target: author._one(target),
            kind="path",
        )
        # Waiting for the two that were permitted, not racing to stop a third.
        # The third cannot proceed regardless of how long this takes.
        while len(author.sessions) < 2:
            await asyncio.sleep(0.01)
        await first.authoring.caught_up()
    finally:
        await first.close()

    second = await _application(db_file)
    try:
        run = await _activity(second).last(project_id)
        assert run is not None
        assert run["status"] == "interrupted"
        # Not `running`, which would keep a panel polling, and not `failed`,
        # which would say the two courses below do not exist.
        assert run["current"] is None
        assert run["completed"] == ["rome", "carthage"]
        assert run["sessions"] == [
            str(author.sessions["rome"]),
            str(author.sessions["carthage"]),
        ]
        # The targets it never reached are still listed, so a reader can see
        # what is missing rather than a run that only ever had two.
        assert run["targets"] == ["rome", "carthage", "complete"]
    finally:
        await second.close()


async def test_a_cancelled_run_persists_as_cancelled_with_its_courses_intact(db_file):
    """Cancelled is a third thing, distinguishable from done and from failed.

    Both leave a partial set of courses behind, which is exactly why a reader
    that cannot tell them apart misreads every one of them: one says a person
    pressed stop, the other says the work broke.

    Red against a `cancel` that cancelled the driving task rather than the
    turn in hand -- the settle would never be appended, and this run would
    read back as `interrupted`.
    """
    first = await _application(db_file)
    author = StubAuthor()
    author.permits = asyncio.Semaphore(0)
    try:
        project_id = await _project(first)
        activity = _activity(first)
        await activity.start(
            project_id,
            ["rome", "carthage", "complete"],
            lambda _run_id, target: author._one(target),
            kind="path",
        )
        # Exactly one permit, so exactly one target finishes however the
        # scheduler interleaves; the rest block on `acquire`.
        author.permits.release()
        while len(author.sessions) < 1:
            await asyncio.sleep(0.01)
        # Two targets abandoned: the one now blocked and the one after it.
        assert activity.cancel(project_id) == 2
        await activity.wait(project_id)
        await first.authoring.caught_up()
    finally:
        await first.close()

    second = await _application(db_file)
    try:
        run = await _activity(second).last(project_id)
        assert run is not None
        assert run["status"] == "cancelled"
        # The course that was written before the stop is still reachable. A
        # cancel that reported an empty run would be lying about a file a
        # reader can open.
        assert run["completed"] == ["rome"]
        assert run["sessions"] == [str(author.sessions["rome"])]
    finally:
        await second.close()


async def test_a_run_that_lost_one_target_is_done_with_the_failure_listed(db_file):
    """Seven of eight is `done`, and the eighth is named.

    Calling it `failed` would hide the courses that exist; saying nothing would
    hide the one that does not. This asserts both halves survive the restart,
    because the failure detail is on the log too.
    """
    first = await _application(db_file)
    author = StubAuthor()
    author.fail_on = "carthage"
    try:
        project_id = await _project(first)
        await _run(_activity(first), project_id, author, ["rome", "carthage", "complete"])
        await first.authoring.caught_up()
    finally:
        await first.close()

    second = await _application(db_file)
    try:
        run = await _activity(second).last(project_id)
        assert run is not None
        assert run["status"] == "done"
        assert run["completed"] == ["rome", "complete"]
        assert run["failures"] == [{"target": "carthage", "detail": "the model refused"}]
    finally:
        await second.close()


async def test_a_run_that_authored_nothing_is_failed(db_file):
    """The one case where a run really is `failed`: no target survived."""
    application = await _application(db_file)
    author = StubAuthor()
    author.fail_on = "rome"
    try:
        project_id = await _project(application)
        await _run(_activity(application), project_id, author, ["rome"], kind="area")
        await application.authoring.caught_up()

        run = await _activity(application).last(project_id)
        assert run is not None
        assert run["status"] == "failed"
        assert run["completed"] == []
    finally:
        await application.close()


async def test_the_live_run_is_reported_by_current_and_not_by_last(db_file):
    """`last` skips the run this process is driving, and `current` carries it.

    Without the skip, a panel would print "last run wrote 0 of 3" underneath
    its own progress bar for the whole of a twenty-minute run -- the row exists
    from the moment the run starts, which is the price of appending the start
    before answering the 202.
    """
    application = await _application(db_file)
    author = StubAuthor()
    author.gate = asyncio.Event()
    try:
        project_id = await _project(application)
        activity = _activity(application)
        await activity.start(
            project_id,
            ["rome", "carthage"],
            lambda _run_id, target: author._one(target),
            kind="path",
        )
        await application.authoring.caught_up()

        live = activity.current(project_id)
        assert live is not None and live["status"] == "running"
        assert await activity.last(project_id) is None

        author.gate.set()
        await activity.wait(project_id)
        await application.authoring.caught_up()

        # And once it settles it is `last`, with `current` empty.
        assert activity.current(project_id) is None
        settled = await activity.last(project_id)
        assert settled is not None and settled["status"] == "done"
    finally:
        await application.close()
