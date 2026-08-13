"""The ask routes, and the claim that asking writes nothing.

The position assertion is the load-bearing one: it is what makes 'ephemeral'
a property of the system rather than a promise in a document.
"""

import asyncio
import json
from uuid import uuid4

from fastapi.testclient import TestClient

from research_team.application.ask import (
    AskAnswer,
    AskInFlight,
    AskService,
    Citation,
    ConversationRegistry,
)
from research_team.application.ports import ActivityDelta, ActivityMessage
from research_team.interfaces.web.app import AskRequest, create_app

SOME_ANSWER = AskAnswer(text="an answer")
"""A module-level default because `ruff`'s B008 forbids the call in the
signature. Shared safely: `AskAnswer` is frozen."""


class StubExecutor:
    def __init__(self, notes=(), answer=SOME_ANSWER):
        self.notes = list(notes)
        self.answer = answer

    async def run(self, *, project_id, history, question, on_activity):
        for note in self.notes:
            on_activity(note)
        return self.answer


def client(ask: AskService, **kwargs) -> TestClient:
    """`create_app` takes every dependency as a parameter; the ask routes need
    only `ask`, so the rest stay None and their routes stay unexercised."""
    return TestClient(create_app(service=None, feed=None, turns=None, ask=ask, **kwargs))


def ask_service(executor) -> AskService:
    return AskService(
        executor=executor,
        conversations=ConversationRegistry(now=lambda: 0.0),
        now=lambda: 0.0,
    )


def frames(response) -> list[dict]:
    return [
        json.loads(line[len("data: ") :])
        for line in response.text.splitlines()
        if line.startswith("data: ")
    ]


def test_the_answer_arrives_last_with_its_citations():
    """The page renders the reply and its citations together."""
    executor = StubExecutor(
        answer=AskAnswer(text="two papers", citations=(Citation(kind="source", id="s1"),))
    )
    response = client(ask_service(executor)).post(
        f"/api/projects/{uuid4()}/ask", json={"chat_id": "c", "question": "why?"}
    )

    assert response.status_code == 200
    last = frames(response)[-1]
    assert last == {
        "type": "answer",
        "text": "two papers",
        "citations": [{"kind": "source", "id": "s1"}],
    }


def test_activity_is_streamed_before_the_answer():
    """Without this the page has nothing to show while the model works."""
    executor = StubExecutor(
        notes=[
            ActivityDelta(message_id="m1", text="thinking"),
            ActivityMessage(message_id="m2", kind="tool", payload={"name": "read_source"}),
        ]
    )
    response = client(ask_service(executor)).post(
        f"/api/projects/{uuid4()}/ask", json={"chat_id": "c", "question": "why?"}
    )

    kinds = [frame["type"] for frame in frames(response)]
    assert kinds == ["delta", "message", "answer"]


def test_a_failing_executor_reports_an_error_frame_rather_than_a_dead_stream():
    """A stream that just stops is indistinguishable from a slow model."""

    class Broken:
        async def run(self, **_):
            raise RuntimeError("model fell over")

    response = client(ask_service(Broken())).post(
        f"/api/projects/{uuid4()}/ask", json={"chat_id": "c", "question": "why?"}
    )

    assert frames(response)[-1]["type"] == "error"


def test_a_second_question_on_a_busy_chat_answers_409():
    """The service's one-at-a-time rule has to reach the browser as a status."""

    class Busy:
        async def run(self, **_):
            raise AssertionError("should not have been reached")

    ask = ask_service(Busy())

    async def refuse(**_):
        raise AskInFlight("busy")
        # Unreachable, and it is what makes this double honest: `AskService.ask`
        # is an async generator, so the refusal arrives on the first `__anext__`
        # rather than from the call. A plain coroutine here would be a different
        # object shape and the route would fail on it for the wrong reason.
        yield

    ask.ask = refuse  # type: ignore[method-assign]
    response = client(ask).post(
        f"/api/projects/{uuid4()}/ask", json={"chat_id": "c", "question": "why?"}
    )

    assert response.status_code == 409


def test_deleting_a_chat_forgets_its_history():
    """Backs the 'new chat' control."""
    ask = ask_service(StubExecutor())
    project = uuid4()
    http = client(ask)
    http.post(f"/api/projects/{project}/ask", json={"chat_id": "c", "question": "one"})

    response = http.delete(f"/api/projects/{project}/ask/c")

    assert response.status_code == 200
    assert ask._conversations.get("c", project).messages == ()


async def test_closing_the_stream_cancels_the_model_call():
    """A reader who walks away must not leave a model call burning tokens.

    Driven without `TestClient` on purpose: the route's `finally` never runs
    on a disconnect as such -- Starlette leaves the generator suspended at a
    yield -- it runs when the generator is finalised, and `aclose()` is that
    moment made explicit. Calling the endpoint directly is the only way to
    reach it deterministically, and it covers the route's `finally` and
    `AskService.ask`'s cancellation together. Revert either and the executor
    never learns the reader has gone.
    """
    parked = asyncio.Event()

    class Parking:
        cancelled = False

        async def run(self, *, project_id, history, question, on_activity):
            on_activity(ActivityDelta(message_id="m1", text="thinking"))
            try:
                await parked.wait()
            except asyncio.CancelledError:
                Parking.cancelled = True
                raise
            return SOME_ANSWER

    app = create_app(service=None, feed=None, turns=None, ask=ask_service(Parking()))
    endpoint = next(
        route.endpoint
        for route in app.routes
        if getattr(route, "path", "") == "/api/projects/{project_id}/ask"
        and "POST" in getattr(route, "methods", ())
    )

    response = await endpoint(uuid4(), AskRequest(chat_id="c", question="why?"))
    assert await response.body_iterator.__anext__()  # the first note; now parked
    await response.body_iterator.aclose()

    assert Parking.cancelled


def test_an_unknown_project_is_a_404_rather_than_a_stream_that_errors():
    """Told before a graph is opened or a model is called.

    Without this the page has to read "no such project" out of an error frame
    on a 200, and a mistyped id gets as far as the agent. `service` is the
    thing that knows, so the route asks it -- and only when there is one,
    which is what keeps every `service=None` test above about its own subject.
    """

    class Unknown:
        attached_project_id = None

        async def project_state(self, project_id):
            raise LookupError(project_id)

    class Reached:
        async def run(self, **_):
            raise AssertionError("the ask ran despite an unknown project")

    http = TestClient(
        create_app(service=Unknown(), feed=None, turns=None, ask=ask_service(Reached()))
    )

    response = http.post(
        f"/api/projects/{uuid4()}/ask", json={"chat_id": "c", "question": "why?"}
    )

    assert response.status_code == 404


def test_an_unconfigured_build_says_so_rather_than_failing_obscurely():
    """`ask` is optional on `create_app`, so a build without it -- a test app,
    or a front end wired before the service existed -- must answer a status
    naming the gap rather than an AttributeError the browser sees as a 500."""
    http = TestClient(create_app(service=None, feed=None, turns=None))

    assert (
        http.post(
            f"/api/projects/{uuid4()}/ask", json={"chat_id": "c", "question": "why?"}
        ).status_code
        == 503
    )
    assert http.delete(f"/api/projects/{uuid4()}/ask/c").status_code == 503
