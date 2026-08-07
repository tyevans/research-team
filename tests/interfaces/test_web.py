"""The HTTP adapter, exercised over ASGI with no network and no real model."""

import asyncio
import hashlib
import json
from uuid import UUID, uuid4

import pytest
from httpx import ASGITransport, AsyncClient
from langchain_core.messages import AIMessage

from research_team.application.ports import ActivityMessage
from research_team.composition import build_application as _build_application
from research_team.domain import (
    DeleteFile,
    DropSourceDocument,
    SendUserMessage,
    StartSession,
    StoreSourceDocument,
    WriteFile,
)
from research_team.infrastructure.persistence import build_corpus_repository
from research_team.interfaces.web import TurnActivity, create_app


async def _started(**kwargs):
    """Build an application and start its projection.

    These tests construct their own applications rather than take the fixture,
    because they need the FastAPI app wired around the same instance. Starting
    is still not optional -- `/sessions` reads a projection that has to be
    following the log before it can answer.
    """
    application = _build_application(**kwargs)
    await application.start()
    return application


@pytest.fixture
async def app_and_client(db_path, fake_model):
    application = await _started(model=fake_model, db_path=db_path)
    api = create_app(
        application.service, application.feed, application.turns, corpus=application.corpus
    )
    transport = ASGITransport(app=api)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield application, client
    await application.close()


@pytest.fixture
def client(app_and_client):
    return app_and_client[1]


@pytest.fixture
def service(app_and_client):
    return app_and_client[0].service


async def _new_session(client) -> str:
    response = await client.post("/api/sessions", json={})
    assert response.status_code == 200
    return response.json()["id"]


# ---------------- sessions ----------------


async def test_create_and_list_sessions(client):
    session_id = await _new_session(client)
    listed = (await client.get("/api/sessions")).json()
    assert [row["id"] for row in listed] == [session_id]


async def test_get_session_reports_its_prompt_and_model(client):
    session_id = await _new_session(client)
    body = (await client.get(f"/api/sessions/{session_id}")).json()
    assert body["id"] == session_id
    assert body["system_prompt"]
    assert body["turn_index"] == 0
    assert body["files"] == []


async def test_create_session_honours_a_custom_prompt(client):
    response = await client.post(
        "/api/sessions", json={"system_prompt": "a distinctive prompt"}
    )
    session_id = response.json()["id"]
    body = (await client.get(f"/api/sessions/{session_id}")).json()
    assert body["system_prompt"] == "a distinctive prompt"


async def test_unknown_session_is_404(client):
    response = await client.get("/api/sessions/8ad0f9de-0000-4000-8000-000000000000")
    assert response.status_code == 404


async def test_malformed_session_id_is_422(client):
    assert (await client.get("/api/sessions/not-a-uuid")).status_code == 422


# ---------------- turns ----------------


async def test_run_turn_records_events_and_returns_the_reply(client):
    session_id = await _new_session(client)
    response = await client.post(f"/api/sessions/{session_id}/turns", json={"input": "hello"})
    assert response.status_code == 200
    assert response.json()["reply"] == "done"

    events = (await client.get(f"/api/sessions/{session_id}/events")).json()
    assert [row["type"] for row in events] == [
        "SessionStarted",
        "UserMessageSent",
        "AssistantMessageAdded",
        "TurnCompleted",
    ]
    assert [row["index"] for row in events] == [1, 2, 3, 4]


async def test_messages_are_rendered_with_roles(client):
    session_id = await _new_session(client)
    await client.post(f"/api/sessions/{session_id}/turns", json={"input": "hello"})
    body = (await client.get(f"/api/sessions/{session_id}")).json()
    assert [message["role"] for message in body["messages"]] == ["user", "assistant"]
    assert body["messages"][0]["content"] == "hello"


# ---------------- files, history, diffs ----------------


@pytest.fixture
def writing_model(fake_model):
    """A model that writes a file, then edits it -- two turns of provenance."""
    fake_model.responses = [
        AIMessage(
            content="",
            id="a1",
            tool_calls=[
                {
                    "name": "write_file",
                    "args": {"file_path": "/hello.py", "content": "print('hi')\n"},
                    "id": "t1",
                }
            ],
        ),
        AIMessage(content="wrote it", id="a2"),
        AIMessage(
            content="",
            id="a3",
            tool_calls=[
                {
                    "name": "edit_file",
                    "args": {
                        "file_path": "/hello.py",
                        "old_string": "hi",
                        "new_string": "hello",
                    },
                    "id": "t2",
                }
            ],
        ),
        AIMessage(content="edited it", id="a4"),
    ]
    return fake_model


@pytest.fixture
async def written(db_path, writing_model):
    application = await _started(model=writing_model, db_path=db_path)
    api = create_app(application.service, application.feed, application.turns)
    async with AsyncClient(transport=ASGITransport(app=api), base_url="http://test") as client:
        session_id = await _new_session(client)
        await client.post(f"/api/sessions/{session_id}/turns", json={"input": "write"})
        await client.post(f"/api/sessions/{session_id}/turns", json={"input": "edit"})
        yield client, session_id
    await application.close()


async def test_file_is_listed_with_size_and_revisions(written):
    client, session_id = written
    body = (await client.get(f"/api/sessions/{session_id}")).json()
    assert [entry["path"] for entry in body["files"]] == ["/hello.py"]
    assert body["files"][0]["revisions"] == 2  # one write, one edit


async def test_file_contents_are_served(written):
    client, session_id = written
    body = (
        await client.get(f"/api/sessions/{session_id}/files", params={"path": "/hello.py"})
    ).json()
    assert "hello" in body["content"]


async def test_missing_file_is_404(written):
    client, session_id = written
    response = await client.get(
        f"/api/sessions/{session_id}/files", params={"path": "/nope.py"}
    )
    assert response.status_code == 404


async def test_file_history_carries_the_edit_intent(written):
    client, session_id = written
    rows = (
        await client.get(
            f"/api/sessions/{session_id}/files/history", params={"path": "/hello.py"}
        )
    ).json()
    assert [row["type"] for row in rows] == ["FileWritten", "FileEdited"]
    assert rows[0]["old_string"] is None
    assert rows[1]["old_string"] == "hi"
    assert rows[1]["new_string"] == "hello"


# ---------------- time travel ----------------


async def test_scrubbing_reproduces_the_earlier_workspace(written):
    """The point of the whole project: fold to a prefix, see the past."""
    client, session_id = written
    events = (await client.get(f"/api/sessions/{session_id}/events")).json()
    write_index = next(row["index"] for row in events if row["type"] == "FileWritten")

    past = (await client.get(f"/api/sessions/{session_id}/at/{write_index}")).json()
    assert past["at"] == write_index
    assert [entry["path"] for entry in past["files"]] == ["/hello.py"]

    head = (await client.get(f"/api/sessions/{session_id}")).json()
    assert head["at"] is None
    # The edit happened after the fold point, so the past is genuinely smaller.
    assert past["files"][0]["size"] < head["files"][0]["size"]


async def test_scrubbing_writes_nothing(written):
    client, session_id = written
    before = (await client.get(f"/api/sessions/{session_id}/events")).json()
    await client.get(f"/api/sessions/{session_id}/at/2")
    after = (await client.get(f"/api/sessions/{session_id}/events")).json()
    assert after == before
    assert len((await client.get("/api/sessions")).json()) == 1


async def test_scrubbing_out_of_range_is_400(written):
    client, session_id = written
    assert (await client.get(f"/api/sessions/{session_id}/at/999")).status_code == 400
    assert (await client.get(f"/api/sessions/{session_id}/at/0")).status_code == 400


# ---------------- forks ----------------


async def test_fork_creates_a_child_and_leaves_the_original(client):
    session_id = await _new_session(client)
    await client.post(f"/api/sessions/{session_id}/turns", json={"input": "hello"})
    before = (await client.get(f"/api/sessions/{session_id}/events")).json()

    forked = (await client.post(f"/api/sessions/{session_id}/forks", json={"at": 1})).json()[
        "id"
    ]

    assert forked != session_id
    assert (await client.get(f"/api/sessions/{session_id}/events")).json() == before
    child = (await client.get(f"/api/sessions/{forked}")).json()
    assert child["forked_from"] == session_id
    assert child["forked_at"] == 1


async def test_fork_out_of_range_is_400(client):
    session_id = await _new_session(client)
    response = await client.post(f"/api/sessions/{session_id}/forks", json={"at": 99})
    assert response.status_code == 400


async def test_tree_nests_forks_under_their_parent(client):
    parent = await _new_session(client)
    await client.post(f"/api/sessions/{parent}/turns", json={"input": "hello"})
    child = (await client.post(f"/api/sessions/{parent}/forks", json={"at": 1})).json()["id"]

    tree = (await client.get("/api/tree")).json()
    assert [node["id"] for node in tree] == [parent]
    assert [node["id"] for node in tree[0]["children"]] == [child]
    assert tree[0]["children"][0]["forked_at"] == 1


async def test_tree_keeps_unforked_sessions_as_roots(client):
    first = await _new_session(client)
    second = await _new_session(client)
    tree = (await client.get("/api/tree")).json()
    assert {node["id"] for node in tree} == {first, second}
    assert all(node["children"] == [] for node in tree)


# ---------------- live feed ----------------

# httpx's ASGI transport buffers a whole response before returning it, so an
# endless SSE stream can never be read through it. The framing is unit-tested
# against the generator, and the wire is proved once against a real server.


class StubRequest:
    """The only thing `_sse` asks a request: have you gone away yet."""

    def __init__(self, disconnect_after: int = 10_000) -> None:
        self._checks = 0
        self._disconnect_after = disconnect_after

    async def is_disconnected(self) -> bool:
        self._checks += 1
        return self._checks > self._disconnect_after


async def test_sse_frames_each_event_as_a_data_line(repository, session_id):
    from research_team.application import LiveFeed
    from research_team.interfaces.web.app import _sse

    feed = LiveFeed(repository, poll_interval=0.01)
    aggregate = repository.create(session_id)
    aggregate.execute(
        StartSession(
            session_id=aggregate.aggregate_id, system_prompt="prompt", model_name="test-model"
        )
    )
    await repository.save(aggregate)

    frames: list[str] = []
    generator = _sse(StubRequest(), feed)
    task = asyncio.create_task(_drain(generator, frames, wanted=1))
    await asyncio.sleep(0.05)
    aggregate.execute(SendUserMessage(message={"type": "human", "data": {"content": "hi"}}))
    await repository.save(aggregate)
    await asyncio.wait_for(task, timeout=5)

    assert frames[0].endswith("\n\n")
    payload = json.loads(frames[0].split("data: ", 1)[1])
    assert payload["session_id"] == str(session_id)
    assert payload["type"] == "UserMessageSent"


async def _drain(generator, frames: list[str], *, wanted: int) -> None:
    """Collect `wanted` data frames, then shut the generator down.

    Leaving it suspended would leave its poll loop holding the store open past
    the end of the test, which surfaces much later as a stray database error.
    """
    try:
        async for frame in generator:
            # Event frames carry an id line ahead of their data; the only other
            # thing on the wire is a `:` keepalive comment.
            if not frame.startswith(":"):
                frames.append(frame)
                if len(frames) >= wanted:
                    return
    finally:
        await generator.aclose()


async def test_sse_emits_a_keepalive_while_the_log_is_idle(repository, monkeypatch):
    """A minute of model thinking must not look like a dead connection."""
    from research_team.application import LiveFeed
    from research_team.interfaces.web import app as web_app
    from research_team.interfaces.web.app import _sse

    monkeypatch.setattr(web_app, "KEEPALIVE_SECONDS", 0.05)
    generator = _sse(StubRequest(), LiveFeed(repository, poll_interval=0.01))
    frame = await asyncio.wait_for(anext(generator), timeout=5)
    assert frame == ": keepalive\n\n"
    await generator.aclose()


async def test_sse_stops_when_the_client_goes_away(repository, monkeypatch):
    from research_team.application import LiveFeed
    from research_team.interfaces.web import app as web_app
    from research_team.interfaces.web.app import _sse

    monkeypatch.setattr(web_app, "KEEPALIVE_SECONDS", 0.01)
    generator = _sse(StubRequest(disconnect_after=2), LiveFeed(repository, poll_interval=0.01))
    frames = [frame async for frame in generator]
    assert all(frame == ": keepalive\n\n" for frame in frames)  # then it ended


async def test_stream_reaches_a_real_browser_over_a_real_socket(db_path, fake_model):
    """One end-to-end proof over the wire, since the ASGI transport cannot."""
    import uvicorn

    application = await _started(model=fake_model, db_path=db_path)
    api = create_app(application.service, application.feed, application.turns)
    config = uvicorn.Config(api, host="127.0.0.1", port=8749, log_level="error")
    server = uvicorn.Server(config)
    serving = asyncio.create_task(server.serve())
    while not server.started:
        await asyncio.sleep(0.02)

    received: list[dict] = []

    async def listen() -> None:
        async with (
            AsyncClient(timeout=20) as browser,
            browser.stream("GET", "http://127.0.0.1:8749/api/stream") as response,
        ):
            assert response.status_code == 200
            assert "text/event-stream" in response.headers["content-type"]
            async for line in response.aiter_lines():
                if line.startswith("data: "):
                    received.append(json.loads(line[len("data: ") :]))
                    return

    listener = asyncio.create_task(listen())
    try:
        await asyncio.sleep(0.4)  # let the subscriber take its position
        session_id = await application.service.create_session()
        await asyncio.wait_for(listener, timeout=10)
    finally:
        # Let the server notice the browser has gone and unwind the streaming
        # response before shutting down: a poll still in flight when the store
        # closes is harmless but noisy.
        await asyncio.sleep(0.3)
        server.should_exit = True
        await serving
        await application.close()

    assert received[0]["session_id"] == str(session_id)
    assert received[0]["type"] == "SessionStarted"


# ---------------- the page itself ----------------


async def test_index_is_served(client):
    response = await client.get("/")
    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]


# ---------------- concurrent clients ----------------


async def test_two_turns_at_once_on_one_session_conflict_rather_than_interleave(
    app_and_client,
):
    """Two tabs, one session. One turn wins; the other is told to retry.

    The loser's events are discarded whole, so the log gains exactly one turn
    -- the all-or-nothing guarantee holding under concurrency, not just under
    failure.
    """
    application, client = app_and_client
    session_id = await application.service.create_session()

    first, second = await asyncio.gather(
        client.post(f"/api/sessions/{session_id}/turns", json={"input": "a"}),
        client.post(f"/api/sessions/{session_id}/turns", json={"input": "b"}),
    )

    assert sorted([first.status_code, second.status_code]) == [200, 409]

    events = (await client.get(f"/api/sessions/{session_id}/events")).json()
    assert [row["type"] for row in events] == [
        "SessionStarted",
        "UserMessageSent",
        "AssistantMessageAdded",
        "TurnCompleted",
    ]


async def test_turns_on_different_sessions_run_concurrently(app_and_client):
    application, client = app_and_client
    first_id = await application.service.create_session()
    second_id = await application.service.create_session()

    responses = await asyncio.gather(
        client.post(f"/api/sessions/{first_id}/turns", json={"input": "a"}),
        client.post(f"/api/sessions/{second_id}/turns", json={"input": "b"}),
    )

    assert [response.status_code for response in responses] == [200, 200]
    for session_id in (first_id, second_id):
        events = (await client.get(f"/api/sessions/{session_id}/events")).json()
        assert len(events) == 4


async def test_reads_are_safe_while_a_turn_is_in_flight(app_and_client):
    application, client = app_and_client
    session_id = await application.service.create_session()
    await client.post(f"/api/sessions/{session_id}/turns", json={"input": "first"})

    turn, events, listing, scrub = await asyncio.gather(
        client.post(f"/api/sessions/{session_id}/turns", json={"input": "second"}),
        client.get(f"/api/sessions/{session_id}/events"),
        client.get("/api/sessions"),
        client.get(f"/api/sessions/{session_id}/at/2"),
    )

    assert turn.status_code == 200
    assert events.status_code == 200
    assert listing.status_code == 200
    assert scrub.status_code == 200


async def test_a_failed_turn_is_recorded_and_reported(app_and_client, monkeypatch):
    """A turn the model could not complete: 500 to the browser, and a marker in
    the log so the audit trail records the attempt."""
    from research_team.infrastructure.agent.deep_agent import DeepAgentTurnExecutor

    application, client = app_and_client
    session_id = await application.service.create_session()

    async def boom(self, session, messages, system_prompt, on_activity):
        raise RuntimeError("model endpoint is down")

    monkeypatch.setattr(DeepAgentTurnExecutor, "_invoke", boom)

    # The default transport re-raises app exceptions instead of turning them
    # into a response; a browser sees the 500, so this test should too.
    api = create_app(application.service, application.feed, application.turns)
    async with AsyncClient(
        transport=ASGITransport(app=api, raise_app_exceptions=False),
        base_url="http://test",
    ) as browser:
        response = await browser.post(
            f"/api/sessions/{session_id}/turns", json={"input": "hello"}
        )
    assert response.status_code == 500

    events = (await client.get(f"/api/sessions/{session_id}/events")).json()
    assert [row["type"] for row in events] == ["SessionStarted", "TurnFailed"]
    assert "model endpoint is down" in events[1]["summary"]
    # The user's message from the failed turn was discarded with the rest of it.
    body = (await client.get(f"/api/sessions/{session_id}")).json()
    assert body["messages"] == []
    assert body["turn_index"] == 0


# ---------------- reading files in the past ----------------


async def test_a_file_can_be_read_as_of_an_earlier_event(written):
    """Scrubbing must reach file *contents*, not just the file list."""
    client, session_id = written
    events = (await client.get(f"/api/sessions/{session_id}/events")).json()
    write_index = next(row["index"] for row in events if row["type"] == "FileWritten")

    past = (
        await client.get(
            f"/api/sessions/{session_id}/files",
            params={"path": "/hello.py", "at": write_index},
        )
    ).json()
    head = (
        await client.get(f"/api/sessions/{session_id}/files", params={"path": "/hello.py"})
    ).json()

    assert past["at"] == write_index
    assert "hi" in past["content"]
    assert "hello" not in past["content"]
    assert "hello" in head["content"]


async def test_a_file_deleted_later_is_still_readable_in_the_past(db_path, fake_model):
    """The headline case: seeing a deleted file again is the point."""
    application = await _started(model=fake_model, db_path=db_path)
    api = create_app(application.service, application.feed, application.turns)
    session_id = await application.service.create_session()
    session = await application.service.load(session_id)
    session.execute(WriteFile(path="/doomed.py", file_data={"content": "still here\n"}))
    session.execute(DeleteFile(path="/doomed.py"))
    await application.service._repository.save(session)

    async with AsyncClient(transport=ASGITransport(app=api), base_url="http://test") as client:
        events = (await client.get(f"/api/sessions/{session_id}/events")).json()
        written_at = next(r["index"] for r in events if r["type"] == "FileWritten")

        gone = await client.get(
            f"/api/sessions/{session_id}/files", params={"path": "/doomed.py"}
        )
        past = await client.get(
            f"/api/sessions/{session_id}/files",
            params={"path": "/doomed.py", "at": written_at},
        )

    assert gone.status_code == 404
    assert past.status_code == 200
    assert past.json()["content"] == "still here\n"
    await application.close()


async def test_reading_a_file_at_an_impossible_point_is_400(written):
    client, session_id = written
    response = await client.get(
        f"/api/sessions/{session_id}/files", params={"path": "/hello.py", "at": 999}
    )
    assert response.status_code == 400


# ---------------- turn outcome and cancellation ----------------


async def test_a_turn_reports_the_events_it_wrote(client):
    """So a client can say "this turn produced events 2-4" and jump to them."""
    session_id = await _new_session(client)
    body = (
        await client.post(f"/api/sessions/{session_id}/turns", json={"input": "hello"})
    ).json()

    assert body["turn_index"] == 1
    assert (body["from_index"], body["to_index"]) == (2, 4)

    events = (await client.get(f"/api/sessions/{session_id}/events")).json()
    span = [r for r in events if body["from_index"] <= r["index"] <= body["to_index"]]
    assert [row["type"] for row in span] == [
        "UserMessageSent",
        "AssistantMessageAdded",
        "TurnCompleted",
    ]


async def test_the_reported_span_continues_across_turns(client):
    session_id = await _new_session(client)
    first = (
        await client.post(f"/api/sessions/{session_id}/turns", json={"input": "one"})
    ).json()
    second = (
        await client.post(f"/api/sessions/{session_id}/turns", json={"input": "two"})
    ).json()

    assert second["from_index"] == first["to_index"] + 1
    assert second["turn_index"] == 2


async def test_nothing_is_running_on_a_quiet_session(client):
    session_id = await _new_session(client)
    body = (await client.get(f"/api/sessions/{session_id}/turns/current")).json()
    assert body["running"] is False


async def test_cancelling_when_nothing_runs_reports_so(client):
    session_id = await _new_session(client)
    body = (await client.post(f"/api/sessions/{session_id}/turns/cancel")).json()
    assert body["cancelled"] is False


@pytest.fixture
async def slow_app(db_path):
    """A server whose turns are slow enough to interrupt on purpose."""
    from tests.application.test_turn_supervisor import SlowModel

    model = SlowModel(responses=[AIMessage(content="eventually", id="s1")])
    application = await _started(model=model, db_path=db_path)
    api = create_app(application.service, application.feed, application.turns)
    async with AsyncClient(
        transport=ASGITransport(app=api, raise_app_exceptions=False),
        base_url="http://test",
    ) as client:
        yield application, client, model
    await application.close()


async def test_an_in_flight_turn_is_visible_and_cancellable(slow_app):
    application, client, _ = slow_app
    session_id = await application.service.create_session()

    turn = asyncio.create_task(
        client.post(f"/api/sessions/{session_id}/turns", json={"input": "slow"})
    )
    await asyncio.sleep(0.4)

    running = (await client.get(f"/api/sessions/{session_id}/turns/current")).json()
    assert running["running"] is True

    cancelled = (await client.post(f"/api/sessions/{session_id}/turns/cancel")).json()
    assert cancelled["cancelled"] is True

    response = await turn
    assert response.status_code == 499  # abandoned on purpose, not a failure

    events = (await client.get(f"/api/sessions/{session_id}/events")).json()
    assert [row["type"] for row in events] == ["SessionStarted", "TurnFailed"]
    assert (await client.get(f"/api/sessions/{session_id}/turns/current")).json()[
        "running"
    ] is False


async def test_a_second_turn_is_refused_while_one_is_running(slow_app):
    """Refused immediately, rather than after spending a minute in the model."""
    application, client, _ = slow_app
    session_id = await application.service.create_session()

    turn = asyncio.create_task(
        client.post(f"/api/sessions/{session_id}/turns", json={"input": "slow"})
    )
    await asyncio.sleep(0.4)

    second = await client.post(f"/api/sessions/{session_id}/turns", json={"input": "me too"})
    assert second.status_code == 409

    await client.post(f"/api/sessions/{session_id}/turns/cancel")
    assert (await turn).status_code == 499


async def test_the_session_still_works_after_a_cancellation(slow_app):
    application, client, model = slow_app
    session_id = await application.service.create_session()

    turn = asyncio.create_task(
        client.post(f"/api/sessions/{session_id}/turns", json={"input": "slow"})
    )
    await asyncio.sleep(0.4)
    await client.post(f"/api/sessions/{session_id}/turns/cancel")
    await turn

    model.delay = 0.0
    response = await client.post(f"/api/sessions/{session_id}/turns", json={"input": "quick"})

    assert response.status_code == 200
    assert response.json()["turn_index"] == 1  # the cancelled attempt never counted


async def test_a_running_turn_is_described_not_just_flagged(slow_app):
    """A tab arriving mid-turn should be able to say which turn, and for how long."""
    application, client, _ = slow_app
    session_id = await application.service.create_session()

    turn = asyncio.create_task(
        client.post(f"/api/sessions/{session_id}/turns", json={"input": "slow"})
    )
    await asyncio.sleep(0.4)

    body = (await client.get(f"/api/sessions/{session_id}/turns/current")).json()
    assert body["running"] is True
    assert body["turn_index"] == 1
    assert body["started_at"] is not None
    assert 0 < body["elapsed_seconds"] < 60

    await client.post(f"/api/sessions/{session_id}/turns/cancel")
    await turn


async def test_a_quiet_session_reports_no_running_turn_details(client):
    session_id = await _new_session(client)
    body = (await client.get(f"/api/sessions/{session_id}/turns/current")).json()
    assert body == {
        "running": False,
        "turn_index": None,
        "started_at": None,
        "elapsed_seconds": None,
    }


async def test_a_cancellation_is_marked_as_such_in_the_log(slow_app):
    """Stopped on purpose must be distinguishable from broke, without prose."""
    application, client, _ = slow_app
    session_id = await application.service.create_session()

    turn = asyncio.create_task(
        client.post(f"/api/sessions/{session_id}/turns", json={"input": "slow"})
    )
    await asyncio.sleep(0.4)
    body = (await client.post(f"/api/sessions/{session_id}/turns/cancel")).json()
    await turn

    assert body == {"cancelled": True, "settled": True}

    events = (await client.get(f"/api/sessions/{session_id}/events")).json()
    failed = next(row for row in events if row["type"] == "TurnFailed")
    assert failed["cancelled"] is True
    assert "cancelled" in failed["summary"]


async def test_a_genuine_failure_is_not_marked_cancelled(app_and_client, monkeypatch):
    from research_team.infrastructure.agent.deep_agent import DeepAgentTurnExecutor

    application, client = app_and_client
    session_id = await application.service.create_session()

    async def boom(self, session, messages, system_prompt, on_activity):
        raise RuntimeError("model endpoint is down")

    monkeypatch.setattr(DeepAgentTurnExecutor, "_invoke", boom)
    with pytest.raises(RuntimeError):
        await application.turns.run(session_id, "hello")

    events = (await client.get(f"/api/sessions/{session_id}/events")).json()
    failed = next(row for row in events if row["type"] == "TurnFailed")
    assert failed["cancelled"] is False
    assert "RuntimeError" in failed["summary"]


async def test_ordinary_events_carry_no_cancellation_flag(client):
    session_id = await _new_session(client)
    await client.post(f"/api/sessions/{session_id}/turns", json={"input": "hello"})
    events = (await client.get(f"/api/sessions/{session_id}/events")).json()
    assert all(row["cancelled"] is None for row in events)


def _cursor_of(frame: str) -> str:
    return frame.split("id: ", 1)[1].split("\n", 1)[0]


async def _watch(feed, resume_from=None, wanted: int = 1):
    """Start an `_sse` stream and collect frames in the background.

    Returns the task and the list it fills. Starting the drain *before* the
    events are appended is what makes the test meaningful: a stream takes its
    position when it is first iterated, not when it is constructed.
    """
    from research_team.interfaces.web.app import _sse

    frames: list[str] = []
    generator = _sse(StubRequest(), feed, resume_from)
    task = asyncio.create_task(_drain(generator, frames, wanted=wanted))
    await asyncio.sleep(0.05)
    return task, frames


async def test_each_frame_carries_the_cursor_that_follows_it(repository, session_id):
    """Without an id, a browser has nothing to reconnect with."""
    from research_team.application import LiveFeed

    feed = LiveFeed(repository, poll_interval=0.01)
    aggregate = repository.create(session_id)
    aggregate.execute(
        StartSession(
            session_id=aggregate.aggregate_id, system_prompt="prompt", model_name="test-model"
        )
    )
    await repository.save(aggregate)

    task, frames = await _watch(feed)
    aggregate.execute(SendUserMessage(message={"type": "human", "data": {"content": "hi"}}))
    await repository.save(aggregate)
    await asyncio.wait_for(task, timeout=5)

    assert frames[0].startswith("id: ")
    assert repository.decode_position(_cursor_of(frames[0])) is not None


async def test_reconnecting_with_a_cursor_delivers_what_was_missed(repository, session_id):
    """The gap a dropped connection leaves is the whole point of the id.

    The second message is appended while no stream is open at all, so a feed
    that started at the live end would never show it -- and the browser would
    have no way to know it had missed anything.
    """
    from research_team.application import LiveFeed

    feed = LiveFeed(repository, poll_interval=0.01)
    aggregate = repository.create(session_id)
    aggregate.execute(
        StartSession(
            session_id=aggregate.aggregate_id, system_prompt="prompt", model_name="test-model"
        )
    )
    await repository.save(aggregate)

    task, frames = await _watch(feed)
    aggregate.execute(SendUserMessage(message={"type": "human", "data": {"content": "seen"}}))
    await repository.save(aggregate)
    await asyncio.wait_for(task, timeout=5)
    cursor = _cursor_of(frames[0])

    # Nobody is listening for this one.
    aggregate.execute(
        SendUserMessage(message={"type": "human", "data": {"content": "missed"}})
    )
    await repository.save(aggregate)

    resumed, recovered = await _watch(feed, resume_from=cursor)
    await asyncio.wait_for(resumed, timeout=5)

    assert json.loads(recovered[0].split("data: ", 1)[1])["type"] == "UserMessageSent"
    assert _cursor_of(recovered[0]) != cursor


async def test_an_unplaceable_cursor_falls_back_to_the_live_end(repository, session_id):
    """A stale or foreign id must not replay the whole log at a browser."""
    from research_team.application import LiveFeed

    feed = LiveFeed(repository, poll_interval=0.01)
    aggregate = repository.create(session_id)
    aggregate.execute(
        StartSession(
            session_id=aggregate.aggregate_id, system_prompt="prompt", model_name="test-model"
        )
    )
    await repository.save(aggregate)  # already in the log, must not be replayed

    task, frames = await _watch(feed, resume_from="junk-from-another-database")
    aggregate.execute(SendUserMessage(message={"type": "human", "data": {"content": "after"}}))
    await repository.save(aggregate)
    await asyncio.wait_for(task, timeout=5)

    payload = json.loads(frames[0].split("data: ", 1)[1])
    assert payload["type"] == "UserMessageSent"


async def test_health_reports_the_projection_is_trustworthy(client):
    body = (await client.get("/api/health")).json()
    assert body["summaries"]["healthy"] is True
    assert body["summaries"]["failed_events"] == 0


async def test_rebuild_endpoint_rederives_the_session_list(client, service):
    """A browser is the primary surface, so the repair has to be reachable there.

    Safe to expose: it discards derived data and recomputes it from the log,
    which is idempotent and cannot lose anything the log still holds.
    """
    session_id = await service.create_session()

    response = await client.post("/api/summaries/rebuild")

    assert response.status_code == 200
    assert response.json()["healthy"] is True
    listed = (await client.get("/api/sessions")).json()
    assert [row["id"] for row in listed] == [str(session_id)]


# ---------------- projects ----------------


async def test_list_projects_starts_empty_then_shows_a_created_one(client):
    assert (await client.get("/api/projects")).json() == []

    response = await client.post("/api/projects", json={"name": "atlas"})
    assert response.status_code == 200
    created = response.json()
    assert created["name"] == "atlas"
    assert created["id"]

    listed = (await client.get("/api/projects")).json()
    # A fresh project is held by nobody and has no tip: exactly the state a
    # row needs to offer "open" rather than a join that would be rejected.
    # No workflow either -- creating and choosing one are separate decisions,
    # and the aggregate refuses a second choice, so nothing may be assumed.
    assert listed == [
        {
            "id": created["id"],
            "name": "atlas",
            "active_session_id": None,
            "tip_at_event": 0,
            "workflow": None,
            "stage": None,
        }
    ]


async def test_creating_a_project_with_a_taken_name_does_not_create_a_second(client):
    first = await client.post("/api/projects", json={"name": "atlas"})
    assert first.status_code == 200

    second = await client.post("/api/projects", json={"name": "atlas"})
    assert second.status_code == 409

    listed = (await client.get("/api/projects")).json()
    # The proof that matters: still exactly one project, not just an error
    # response for the second attempt.
    assert len(listed) == 1
    assert listed[0]["id"] == first.json()["id"]


async def test_joining_a_project_starts_a_session_that_inherits_its_files(client, service):
    project_id = (await client.post("/api/projects", json={"name": "atlas"})).json()["id"]

    first_join = await client.post(f"/api/projects/{project_id}/join")
    assert first_join.status_code == 200
    first_session_id = first_join.json()["id"]
    assert first_join.json()["project_id"] == project_id

    # Put a known file on the first holder's stream directly -- deterministic,
    # unlike relying on the fake model to decide to write one -- then hand the
    # project's tip back so a second join has something to inherit.
    from uuid import UUID as _UUID

    session = await service.load(_UUID(first_session_id))
    session.execute(WriteFile(path="/atlas.py", file_data={"content": "shared content\n"}))
    await service._repository.save(session)
    await service.release_project(_UUID(first_session_id))

    second_join = await client.post(f"/api/projects/{project_id}/join")
    assert second_join.status_code == 200
    second_session_id = second_join.json()["id"]
    assert second_session_id != first_session_id

    second_body = (await client.get(f"/api/sessions/{second_session_id}")).json()
    assert second_body["project_id"] == project_id
    assert any(f["path"] == "/atlas.py" for f in second_body["files"])

    file_body = (
        await client.get(
            f"/api/sessions/{second_session_id}/files", params={"path": "/atlas.py"}
        )
    ).json()
    # The assertion that actually proves inheritance: the byte content of the
    # file on the *second* session matches what was written on the first.
    assert file_body["content"] == "shared content\n"


async def test_joining_a_project_attaches_the_knowledge_tools(app_and_client):
    """The web-route counterpart of Task 14's REPL fix.

    `application.turns_tools()` is the surface the executor actually reads
    from on the next turn -- the same surface
    `test_project_use_attaches_the_knowledge_graph` asserts on for the REPL.
    Before `POST /api/projects/{id}/join`, no project is attached, so the
    knowledge tools must be absent; asserting that first is what lets this
    test fail if the join route stops calling `attach_project`.
    """
    application, client = app_and_client

    names_before = {tool.name for tool in application.turns_tools()}
    assert "remember" not in names_before
    assert "graph_search" not in names_before
    assert "unmerge" not in names_before

    project_id = (await client.post("/api/projects", json={"name": "atlas"})).json()["id"]
    join = await client.post(f"/api/projects/{project_id}/join")
    assert join.status_code == 200

    names_after = {tool.name for tool in application.turns_tools()}
    assert "remember" in names_after
    assert "graph_search" in names_after
    assert "unmerge" in names_after


async def test_joining_an_already_held_project_names_the_holder(client):
    project_id = (await client.post("/api/projects", json={"name": "atlas"})).json()["id"]
    first_join = await client.post(f"/api/projects/{project_id}/join")
    holder_session_id = first_join.json()["id"]

    second_join = await client.post(f"/api/projects/{project_id}/join")

    assert second_join.status_code == 409
    assert holder_session_id in second_join.json()["detail"]


async def test_releasing_a_session_frees_its_project_for_the_next_one(client):
    """The loop the web app could not close: finish here, start fresh there.

    Before `POST /api/sessions/{id}/release` this took a REPL, or a restart:
    the browser had no verb that gave a project back, so the second join in
    this test could only ever be the 409 above.
    """
    project_id = (await client.post("/api/projects", json={"name": "atlas"})).json()["id"]
    first = (await client.post(f"/api/projects/{project_id}/join")).json()["id"]

    release = await client.post(f"/api/sessions/{first}/release")
    assert release.status_code == 200
    assert release.json() == {"released": True, "project_id": project_id}

    listed = (await client.get("/api/projects")).json()
    assert listed[0]["active_session_id"] is None

    second = await client.post(f"/api/projects/{project_id}/join")
    assert second.status_code == 200
    assert second.json()["id"] != first


async def test_releasing_a_session_in_no_project_is_not_an_error(client):
    session_id = (await client.post("/api/sessions")).json()["id"]

    response = await client.post(f"/api/sessions/{session_id}/release")

    assert response.status_code == 200
    assert response.json() == {"released": False, "project_id": None}


async def test_release_advances_the_tip_so_the_next_session_inherits(client, service):
    """Releasing is how work travels between sessions, not just cleanup.

    `release_project` advances the project's tip; a UI that only ever joined
    would fork every new session from a tip that never moved, silently losing
    everything the previous session wrote.
    """
    from uuid import UUID as _UUID

    project_id = (await client.post("/api/projects", json={"name": "atlas"})).json()["id"]
    first = (await client.post(f"/api/projects/{project_id}/join")).json()["id"]

    session = await service.load(_UUID(first))
    session.execute(WriteFile(path="/atlas.py", file_data={"content": "shared content\n"}))
    await service._repository.save(session)

    assert (await client.post(f"/api/sessions/{first}/release")).status_code == 200

    second = (await client.post(f"/api/projects/{project_id}/join")).json()["id"]
    body = (
        await client.get(f"/api/sessions/{second}/files", params={"path": "/atlas.py"})
    ).json()
    assert body["content"] == "shared content\n"


async def test_taking_over_a_held_project_ends_the_holder_and_starts_fresh(client):
    project_id = (await client.post("/api/projects", json={"name": "atlas"})).json()["id"]
    first = (await client.post(f"/api/projects/{project_id}/join")).json()["id"]

    second = await client.post(f"/api/projects/{project_id}/join", json={"take_over": True})

    assert second.status_code == 200
    assert second.json()["id"] != first
    listed = (await client.get("/api/projects")).json()
    assert listed[0]["active_session_id"] == second.json()["id"]


async def test_a_session_reports_whether_it_still_holds_its_project(client):
    project_id = (await client.post("/api/projects", json={"name": "atlas"})).json()["id"]
    first = (await client.post(f"/api/projects/{project_id}/join")).json()["id"]

    assert (await client.get(f"/api/sessions/{first}")).json()["holds_project"] is True

    await client.post(f"/api/projects/{project_id}/join", json={"take_over": True})

    # The fact the UI needs to stop offering this session as the live one.
    assert (await client.get(f"/api/sessions/{first}")).json()["holds_project"] is False


async def test_deleting_a_project_removes_it_from_the_listing(client):
    project_id = (await client.post("/api/projects", json={"name": "atlas"})).json()["id"]

    response = await client.delete(f"/api/projects/{project_id}")

    assert response.status_code == 200
    assert response.json() == {"deleted": True, "project_id": project_id}
    assert (await client.get("/api/projects")).json() == []


async def test_a_deleted_project_cannot_be_joined(client):
    project_id = (await client.post("/api/projects", json={"name": "atlas"})).json()["id"]
    await client.delete(f"/api/projects/{project_id}")

    join = await client.post(f"/api/projects/{project_id}/join")

    assert join.status_code == 409
    assert "deleted" in join.json()["detail"]


async def test_deleting_a_held_project_needs_the_holder_released_first(client):
    """The 409 names the holder, so the UI can offer the thing that fixes it."""
    project_id = (await client.post("/api/projects", json={"name": "atlas"})).json()["id"]
    holder = (await client.post(f"/api/projects/{project_id}/join")).json()["id"]

    refused = await client.delete(f"/api/projects/{project_id}")
    assert refused.status_code == 409
    assert holder in refused.json()["detail"]
    assert len((await client.get("/api/projects")).json()) == 1

    accepted = await client.delete(f"/api/projects/{project_id}?release_holder=true")
    assert accepted.status_code == 200
    assert (await client.get("/api/projects")).json() == []


async def test_deleting_a_project_leaves_its_sessions_readable(client, service):
    """Deletion retires the project, not the work done inside it."""
    from uuid import UUID as _UUID

    project_id = (await client.post("/api/projects", json={"name": "atlas"})).json()["id"]
    session_id = (await client.post(f"/api/projects/{project_id}/join")).json()["id"]
    session = await service.load(_UUID(session_id))
    session.execute(WriteFile(path="/atlas.py", file_data={"content": "kept\n"}))
    await service._repository.save(session)

    await client.delete(f"/api/projects/{project_id}?release_holder=true")

    body = (await client.get(f"/api/sessions/{session_id}")).json()
    assert body["id"] == session_id
    assert any(f["path"] == "/atlas.py" for f in body["files"])
    file_body = (
        await client.get(f"/api/sessions/{session_id}/files", params={"path": "/atlas.py"})
    ).json()
    assert file_body["content"] == "kept\n"


async def test_a_deleted_projects_name_can_be_used_again(client):
    first = (await client.post("/api/projects", json={"name": "atlas"})).json()["id"]
    await client.delete(f"/api/projects/{first}")

    again = await client.post("/api/projects", json={"name": "atlas"})

    assert again.status_code == 200
    assert again.json()["id"] != first


async def test_deleting_an_unknown_project_is_a_404(client):
    response = await client.delete(f"/api/projects/{uuid4()}")

    assert response.status_code == 404


async def test_a_turn_reattaches_the_sessions_own_knowledge_graph(app_and_client):
    """The bug behind "the agent says it has no knowledge graph".

    Attaching only at join meant any later turn ran with whatever graph was
    attached last -- or none, after a restart -- even though the session's
    recorded prompt promises `remember`/`graph_search`/`unmerge`. Detaching
    here stands in for that drift; the turn has to put it back.
    """
    application, client = app_and_client

    project_id = (await client.post("/api/projects", json={"name": "atlas"})).json()["id"]
    session_id = (await client.post(f"/api/projects/{project_id}/join")).json()["id"]

    await application.service.detach_project()
    assert "remember" not in {tool.name for tool in application.turns_tools()}

    response = await client.post(f"/api/sessions/{session_id}/turns", json={"input": "hi"})
    assert response.status_code == 200

    assert "remember" in {tool.name for tool in application.turns_tools()}


# ---------------- turn activity ----------------


@pytest.fixture
async def activity_app(db_path, fake_model):
    application = await _started(model=fake_model, db_path=db_path)
    activity = TurnActivity()
    api = create_app(
        application.service,
        application.feed,
        application.turns,
        activity=activity,
    )
    transport = ASGITransport(app=api)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield application, client, activity
    await application.close()


async def test_activity_catch_up_route_is_empty_before_a_turn(activity_app):
    _, client, _ = activity_app
    session_id = await _new_session(client)
    body = (await client.get(f"/api/sessions/{session_id}/turns/current/activity")).json()
    assert body == {"running": [], "discarded": []}


async def test_a_turn_reports_activity_into_the_buffer(activity_app):
    """The buffer fills during the turn; it is dropped once the turn commits."""
    _, client, _ = activity_app
    session_id = await _new_session(client)
    response = await client.post(f"/api/sessions/{session_id}/turns", json={"input": "hi"})
    assert response.status_code == 200
    # Committed, so the log is authoritative and the buffer is gone.
    body = (await client.get(f"/api/sessions/{session_id}/turns/current/activity")).json()
    assert body["running"] == []


async def test_activity_frames_ride_the_stream_without_an_id(repository, session_id):
    """Exercises `_sse` directly, like the other frame-shape tests above --
    the ASGI transport cannot stream a still-running response (see
    `test_stream_reaches_a_real_browser_over_a_real_socket`), so going
    through the HTTP client here would just hang.
    """
    from research_team.application import LiveFeed
    from research_team.interfaces.web.app import _sse

    activity = TurnActivity()
    feed = LiveFeed(repository, poll_interval=0.01)

    frames: list[str] = []
    generator = _sse(StubRequest(), feed, None, None, activity)
    task = asyncio.create_task(_drain(generator, frames, wanted=1))
    await asyncio.sleep(0.05)
    activity.begin(session_id)
    activity.reporter(session_id)(
        ActivityMessage(message_id="a1", kind="assistant", payload={"content": "hi"})
    )
    await asyncio.wait_for(task, timeout=5)

    assert frames[0].startswith("data: ")
    payload = json.loads(frames[0][len("data: ") :])
    assert payload["type"] == "TurnActivity"
    assert payload["message_id"] == "a1"
    # Not a log entry: no id line precedes the data, unlike a logged event.
    assert "\nid:" not in frames[0]


# ---------------- corpus ----------------


async def _project_with_sources(application, client, *documents) -> str:
    """A project holding `documents`, with the corpus projection caught up.

    Takes document *specs* -- keyword dicts -- rather than built commands,
    because `StoreSourceDocument` names the corpus it targets and this helper
    is what decides which corpus that is. A caller cannot name an id the helper
    has not created yet.

    Stores through the `Corpus` aggregate rather than through `remember`,
    because `remember` runs an extraction and these tests are about the read
    path. The projection follows the log asynchronously, so the wait is what
    makes the assertions deterministic rather than timing-dependent.
    """
    created = await client.post("/api/projects", json={"name": f"corpus-{uuid4()}"})
    assert created.status_code == 200
    project_id = created.json()["id"]

    corpus = build_corpus_repository(
        application.service._repository.store,
        application.service._repository.publisher,
        snapshot_store=application.service._repository.snapshot_store,
    )
    aggregate = await corpus.load_or_create(UUID(project_id))
    for spec in documents:
        # A dict is a store spec this helper addresses; anything else is
        # already a command (a drop), which names no corpus and needs none.
        aggregate.execute(
            StoreSourceDocument(corpus_id=UUID(project_id), **spec)
            if isinstance(spec, dict)
            else spec
        )
    await corpus.save(aggregate)
    await application.corpus_caught_up()
    return project_id


async def test_listing_sources_reports_metadata_and_never_text(app_and_client):
    application, client = app_and_client
    project_id = await _project_with_sources(
        application,
        client,
        {
            "source_id": "s1",
            "text": "Ada Lovelace worked with Charles Babbage.",
            "uri": "https://example.test/ada",
            "title": "Ada Lovelace",
            "published_at": "1843-07-10",
            "note": "for the timeline",
        },
        {"source_id": "s2", "text": "Grace Hopper."},
    )

    response = await client.get(f"/api/projects/{project_id}/sources")

    assert response.status_code == 200
    rows = response.json()
    assert [row["source_id"] for row in rows] == ["s1", "s2"]
    assert rows[0]["char_count"] == 41
    assert rows[0]["uri"] == "https://example.test/ada"
    assert rows[0]["title"] == "Ada Lovelace"
    assert rows[0]["published_at"] == "1843-07-10"
    assert rows[0]["note"] == "for the timeline"
    # The digest describes the bytes, so a quote can be checked against the
    # document it claims to come from even after that source is revised.
    assert (
        rows[0]["sha256"]
        == hashlib.sha256(b"Ada Lovelace worked with Charles Babbage.").hexdigest()
    )
    # The contract that makes a listing affordable for a corpus of hundreds.
    assert all("text" not in row for row in rows)


async def test_listing_sources_of_an_empty_corpus_is_an_empty_list(app_and_client):
    """An existing project with nothing stored is empty, not missing."""
    _, client = app_and_client
    created = await client.post("/api/projects", json={"name": f"bare-{uuid4()}"})
    project_id = created.json()["id"]

    response = await client.get(f"/api/projects/{project_id}/sources")

    assert response.status_code == 200
    assert response.json() == []


async def test_reading_a_source_returns_its_text_and_citation(app_and_client):
    application, client = app_and_client
    project_id = await _project_with_sources(
        application,
        client,
        {
            "source_id": "s1",
            "text": "Ada Lovelace worked with Charles Babbage.",
            "title": "Ada Lovelace",
        },
    )

    response = await client.get(f"/api/projects/{project_id}/sources/s1")

    assert response.status_code == 200
    body = response.json()
    assert body["source_id"] == "s1"
    assert body["text"] == "Ada Lovelace worked with Charles Babbage."
    assert body["title"] == "Ada Lovelace"
    assert body["char_count"] == 41
    assert body["start"] == 0
    assert body["end"] == 41


async def test_reading_a_range_reports_the_offsets_it_actually_returned(app_and_client):
    """The offsets describe the text in the response, not the text requested."""
    application, client = app_and_client
    project_id = await _project_with_sources(
        application,
        client,
        {"source_id": "s1", "text": "Ada Lovelace worked with Charles Babbage."},
    )

    response = await client.get(
        f"/api/projects/{project_id}/sources/s1", params={"start": 4, "end": 12}
    )

    assert response.status_code == 200
    body = response.json()
    assert body["text"] == "Lovelace"
    assert (body["start"], body["end"]) == (4, 12)
    assert body["char_count"] == 41, "the whole document's size, not the range's"


async def test_a_range_past_the_end_is_clamped_rather_than_refused(app_and_client):
    application, client = app_and_client
    project_id = await _project_with_sources(
        application,
        client,
        {"source_id": "s1", "text": "Ada Lovelace."},
    )

    response = await client.get(
        f"/api/projects/{project_id}/sources/s1", params={"start": 4, "end": 9_000}
    )

    assert response.status_code == 200
    assert response.json()["end"] == 13


async def test_an_unknown_source_is_a_404(app_and_client):
    application, client = app_and_client
    project_id = await _project_with_sources(
        application,
        client,
        {"source_id": "s1", "text": "Ada Lovelace."},
    )

    response = await client.get(f"/api/projects/{project_id}/sources/nope")

    assert response.status_code == 404
    assert "nope" in response.json()["detail"]


async def test_an_unknown_project_is_a_404_on_both_routes(client):
    unknown = uuid4()

    listing = await client.get(f"/api/projects/{unknown}/sources")
    reading = await client.get(f"/api/projects/{unknown}/sources/s1")

    assert listing.status_code == 404
    assert reading.status_code == 404


async def test_a_dropped_source_is_gone_from_both_routes(app_and_client):
    """Dropped means unreadable. The row survives for the audit, not for callers."""
    application, client = app_and_client
    project_id = await _project_with_sources(
        application,
        client,
        {"source_id": "s1", "text": "Ada Lovelace."},
        DropSourceDocument(source_id="s1", reason="superseded by the 1843 notes"),
    )

    listing = await client.get(f"/api/projects/{project_id}/sources")
    reading = await client.get(f"/api/projects/{project_id}/sources/s1")

    assert listing.json() == []
    assert reading.status_code == 404


# ---------------- workflows ----------------


async def test_the_workflow_list_says_what_each_preset_produces_and_where_it_stops(client):
    """The list is the whole basis for the choice, so it carries the consequences.

    A preset that stops before the production half yields a design and not
    materials, and someone who expected materials finding out at the end is
    the failure this endpoint exists to prevent.
    """
    body = (await client.get("/api/workflows")).json()

    by_id = {row["id"]: row for row in body}
    assert set(by_id) == {"hybrid.default", "ubd.pure", "addie.pure"}
    assert by_id["ubd.pure"]["produces"] == "design"
    assert by_id["hybrid.default"]["produces"] == "materials"
    assert by_id["ubd.pure"]["terminates_at"]["spine"] < 8
    assert all(row["label"] for row in body)


async def test_the_recommended_preset_is_listed_first(client):
    """Order is the recommendation. Whichever pure methodology a user picks,
    they inherit that tradition's structural defect, and knowing which defect
    to tolerate needs the expertise they came here without."""
    body = (await client.get("/api/workflows")).json()
    assert body[0]["id"] == "hybrid.default"


async def test_selecting_a_workflow_puts_the_project_at_the_presets_first_stage(client):
    project_id = (await client.post("/api/projects", json={"name": "atlas"})).json()["id"]

    response = await client.post(
        f"/api/projects/{project_id}/workflow", json={"preset_id": "ubd.pure"}
    )
    assert response.status_code == 200

    body = (await client.get(f"/api/projects/{project_id}/workflow")).json()
    assert body["workflow"]["id"] == "ubd.pure"
    # No event records entering a stage nobody advanced to, so "the first
    # stage" is resolved from the preset rather than read off the log.
    assert body["stage"]["index"] == 1
    assert body["stage"]["of"] == 6


async def test_a_project_row_carries_its_workflow_and_stage(client):
    project_id = (await client.post("/api/projects", json={"name": "atlas"})).json()["id"]
    await client.post(f"/api/projects/{project_id}/workflow", json={"preset_id": "ubd.pure"})

    [row] = (await client.get("/api/projects")).json()

    assert row["workflow"]["id"] == "ubd.pure"
    assert row["workflow"]["name"] == "Understanding by Design (unit plan)"
    assert row["stage"]["index"] == 1


async def test_a_project_with_no_workflow_reports_neither(client):
    await client.post("/api/projects", json={"name": "atlas"})

    [row] = (await client.get("/api/projects")).json()

    assert row["workflow"] is None
    assert row["stage"] is None


async def test_selecting_a_second_workflow_is_a_409_naming_the_first(client):
    """The domain's refusal names the running preset, and that name is the
    whole value of it -- "already selected" leaves the user with no idea what
    they are already running."""
    project_id = (await client.post("/api/projects", json={"name": "atlas"})).json()["id"]
    await client.post(f"/api/projects/{project_id}/workflow", json={"preset_id": "ubd.pure"})

    response = await client.post(
        f"/api/projects/{project_id}/workflow", json={"preset_id": "addie.pure"}
    )

    assert response.status_code == 409
    assert "ubd.pure" in response.json()["detail"]

    # The refusal changed nothing, which is the half an error code cannot say.
    body = (await client.get(f"/api/projects/{project_id}/workflow")).json()
    assert body["workflow"]["id"] == "ubd.pure"


async def test_an_unknown_preset_is_a_404_naming_the_ones_that_exist(client):
    project_id = (await client.post("/api/projects", json={"name": "atlas"})).json()["id"]

    response = await client.post(
        f"/api/projects/{project_id}/workflow", json={"preset_id": "tyler.pure"}
    )

    assert response.status_code == 404
    assert "hybrid.default" in response.json()["detail"]


async def test_an_unknown_project_is_a_404_on_both_workflow_routes(client):
    missing = uuid4()

    assert (await client.get(f"/api/projects/{missing}/workflow")).status_code == 404
    post = await client.post(
        f"/api/projects/{missing}/workflow", json={"preset_id": "ubd.pure"}
    )
    assert post.status_code == 404


async def test_a_deleted_project_refuses_a_workflow(client):
    """409 rather than 404: a tombstone is not an absence.

    The project is still there and still readable -- that is what retiring
    means here -- so the honest answer is the domain's, which says it was
    deleted. Joining a deleted project relays the same refusal the same way.
    """
    project_id = (await client.post("/api/projects", json={"name": "atlas"})).json()["id"]
    await client.delete(f"/api/projects/{project_id}")

    response = await client.post(
        f"/api/projects/{project_id}/workflow", json={"preset_id": "ubd.pure"}
    )

    assert response.status_code == 409
    assert "deleted" in response.json()["detail"]


# ---------------- the course ----------------


async def _course_project(client, preset_id: str = "ubd.pure") -> str:
    project_id = (await client.post("/api/projects", json={"name": "atlas"})).json()["id"]
    await client.post(f"/api/projects/{project_id}/workflow", json={"preset_id": preset_id})
    return project_id


async def test_the_course_lists_every_stage_whether_or_not_it_has_run(client):
    """The rail shows the plan, so a stage that has produced nothing still appears.

    A view built from the `/course` directory instead would show what happened
    and leave what was supposed to happen underivable -- backwards for a
    surface whose job is to show a run against its plan.
    """
    project_id = await _course_project(client)

    body = (await client.get(f"/api/projects/{project_id}/course")).json()

    assert body["preset"]["id"] == "ubd.pure"
    assert body["position"] == 1
    assert body["stage_count"] == len(body["stages"]) == 6
    assert body["stages"][0]["status"] == "current"
    assert {stage["status"] for stage in body["stages"][1:]} == {"upcoming"}


async def test_declared_artifacts_appear_as_named_gaps_before_anything_is_written(client):
    project_id = await _course_project(client)

    body = (await client.get(f"/api/projects/{project_id}/course")).json()
    slots = [slot for stage in body["stages"] for slot in stage["outputs"]]

    assert slots, "the preset declares outputs; the course must name them"
    assert all(slot["present"] is False for slot in slots)
    assert all(slot["path"].startswith("/course/") for slot in slots)
    assert all(slot["provenance"] is None for slot in slots)


async def test_a_written_artifact_shows_up_with_the_provenance_it_claims(client, service):
    """The course reads the filesystem of whichever session currently holds it.

    Written through the session that joined the project rather than through a
    fixture, because "which stream carries this project's files" is the part
    the endpoint has to get right.
    """
    project_id = await _course_project(client)
    body = (await client.get(f"/api/projects/{project_id}/course")).json()
    path = body["stages"][0]["outputs"][0]["path"]

    session_id = (await client.post(f"/api/projects/{project_id}/join")).json()["id"]
    session = await service.load(UUID(session_id))
    session.execute(
        WriteFile(
            path=path,
            file_data={
                "content": (
                    "---\n"
                    "artifact_type: Intent\n"
                    "stage: s\n"
                    "preset: ubd.pure\n"
                    "preset_version: '1.0'\n"
                    "provenance:\n"
                    "  - source_id: doc-1\n"
                    "    start: 0\n"
                    "    end: 40\n"
                    "---\n\nthe body\n"
                )
            },
        )
    )
    await service._repository.save(session)

    slot = (await client.get(f"/api/projects/{project_id}/course")).json()["stages"][0][
        "outputs"
    ][0]

    assert slot["present"] is True
    assert slot["has_frontmatter"] is True
    assert slot["missing_fields"] == []
    assert slot["provenance"]["sources"] == [{"source_id": "doc-1", "start": 0, "end": 40}]
    assert slot["provenance"]["empty"] is False
    assert slot["provenance"]["inferred"] is False


async def test_a_project_with_no_workflow_has_no_course(client):
    """409, not 404: the project is here; the choice has not been made."""
    project_id = (await client.post("/api/projects", json={"name": "atlas"})).json()["id"]

    response = await client.get(f"/api/projects/{project_id}/course")

    assert response.status_code == 409
    assert "no workflow" in response.json()["detail"]


async def test_an_unknown_project_has_no_course(client):
    response = await client.get(f"/api/projects/{uuid4()}/course")
    assert response.status_code == 404


# ---------------- components ----------------
#
# The parsed route and the attempt route are two halves of one decision: the
# learner projection strips the answer key, so the browser cannot grade and has
# to ask. Both halves are tested here rather than only the parse, because a
# projection that withholds and an endpoint that hands the key back would each
# pass on their own.

LESSON = """\
---
type: lesson
---

# Declaring severity

```component:mcq
id: sev-1
prompt: What severity?
options:
  - text: "SEV-1"
    correct: false
    feedback: "No data loss."
  - text: "SEV-2"
    correct: true
    feedback: "Textbook SEV-2."
rationale: |
  Severity is a communication decision.
```

```component:from-the-future
shape: unknowable
```
"""

LESSON_PATH = "/course/01-lesson.md"


async def _with_lesson(service, content=LESSON, path=LESSON_PATH) -> str:
    session_id = await service.create_session()
    session = await service.load(session_id)
    session.execute(WriteFile(path=path, file_data={"content": content}))
    await service._repository.save(session)
    return str(session_id)


async def test_the_parsed_view_returns_frontmatter_and_blocks_in_order(client, service):
    session_id = await _with_lesson(service)

    body = (
        await client.get(
            f"/api/sessions/{session_id}/files/parsed", params={"path": LESSON_PATH}
        )
    ).json()

    assert body["frontmatter"] == {"type": "lesson"}
    assert [b["kind"] for b in body["blocks"]] == ["markdown", "component", "component"]
    assert body["blocks"][2]["unknown"] is True


async def test_the_author_view_is_the_default_and_carries_the_key(client, service):
    session_id = await _with_lesson(service)

    body = (
        await client.get(
            f"/api/sessions/{session_id}/files/parsed", params={"path": LESSON_PATH}
        )
    ).json()

    assert body["view"] == "author"
    assert body["blocks"][1]["data"]["options"][1]["correct"] is True


async def test_the_learner_view_does_not_ship_the_answer(client, service):
    """Asserted over the response text, because the failure that matters is a
    secret reaching the wire by any route, not one particular field surviving."""
    session_id = await _with_lesson(service)

    response = await client.get(
        f"/api/sessions/{session_id}/files/parsed",
        params={"path": LESSON_PATH, "view": "learner"},
    )

    assert "Textbook SEV-2" not in response.text
    assert "communication decision" not in response.text
    assert "What severity?" in response.text


async def test_an_unrecognised_view_is_refused_rather_than_defaulted(client, service):
    """Defaulting a typo to the author view would leak the key on `view=learnr`."""
    session_id = await _with_lesson(service)

    response = await client.get(
        f"/api/sessions/{session_id}/files/parsed",
        params={"path": LESSON_PATH, "view": "learnr"},
    )

    assert response.status_code == 422


async def test_a_parsed_file_can_be_read_in_the_past(client, service):
    session_id = await service.create_session()
    session = await service.load(session_id)
    session.execute(WriteFile(path="/c.md", file_data={"content": LESSON}))
    session.execute(DeleteFile(path="/c.md"))
    await service._repository.save(session)

    events = (await client.get(f"/api/sessions/{session_id}/events")).json()
    written_at = next(r["index"] for r in events if r["type"] == "FileWritten")

    gone = await client.get(
        f"/api/sessions/{session_id}/files/parsed", params={"path": "/c.md"}
    )
    past = await client.get(
        f"/api/sessions/{session_id}/files/parsed",
        params={"path": "/c.md", "at": written_at},
    )

    assert gone.status_code == 404
    assert len(past.json()["blocks"]) == 3


async def test_a_missing_file_is_a_404_from_the_parsed_route_too(client, service):
    session_id = await _with_lesson(service)
    response = await client.get(
        f"/api/sessions/{session_id}/files/parsed", params={"path": "/nope.md"}
    )
    assert response.status_code == 404


async def test_a_right_answer_is_graded_and_the_rationale_returned(client, service):
    session_id = await _with_lesson(service)

    body = (
        await client.post(
            f"/api/sessions/{session_id}/attempts",
            json={"path": LESSON_PATH, "component_id": "sev-1", "response": 1},
        )
    ).json()

    assert body["correct"] is True
    assert body["feedback"] == ["Textbook SEV-2."]
    assert "communication decision" in body["rationale"]


async def test_a_wrong_answer_is_graded_rather_than_refused(client, service):
    session_id = await _with_lesson(service)

    response = await client.post(
        f"/api/sessions/{session_id}/attempts",
        json={"path": LESSON_PATH, "component_id": "sev-1", "response": 0},
    )

    assert response.status_code == 200
    assert response.json()["correct"] is False
    assert response.json()["correct_options"] == [1]


async def test_an_attempt_at_a_component_that_is_not_there_is_a_404(client, service):
    session_id = await _with_lesson(service)

    response = await client.post(
        f"/api/sessions/{session_id}/attempts",
        json={"path": LESSON_PATH, "component_id": "nope", "response": 1},
    )

    assert response.status_code == 404


async def test_a_response_of_the_wrong_shape_is_a_400_not_a_500(client, service):
    session_id = await _with_lesson(service)

    response = await client.post(
        f"/api/sessions/{session_id}/attempts",
        json={"path": LESSON_PATH, "component_id": "sev-1", "response": {"a": 1}},
    )

    assert response.status_code == 400


async def test_an_attempt_is_graded_against_the_file_as_it_was(client, service):
    """Grading at HEAD would mark yesterday's attempt against today's key."""
    session_id = await service.create_session()
    session = await service.load(session_id)
    session.execute(WriteFile(path="/c.md", file_data={"content": LESSON}))
    await service._repository.save(session)
    events = (await client.get(f"/api/sessions/{session_id}/events")).json()
    original = next(r["index"] for r in events if r["type"] == "FileWritten")

    # The revision moves the answer rather than adding one: a second `correct`
    # option would make the item multiple-response and change what "0" means.
    revised = (
        LESSON.replace("correct: false", "correct: WAS_FALSE")
        .replace("correct: true", "correct: false")
        .replace("correct: WAS_FALSE", "correct: true")
    )
    session = await service.load(session_id)
    session.execute(WriteFile(path="/c.md", file_data={"content": revised}))
    await service._repository.save(session)

    now = await client.post(
        f"/api/sessions/{session_id}/attempts",
        json={"path": "/c.md", "component_id": "sev-1", "response": 0},
    )
    then = await client.post(
        f"/api/sessions/{session_id}/attempts",
        json={"path": "/c.md", "component_id": "sev-1", "response": 0, "at": original},
    )

    assert now.json()["correct"] is True
    assert then.json()["correct"] is False


# ---------------- autonomous research ----------------


@pytest.fixture
async def research_client(db_path, fake_model):
    """A client whose app was wired *with* a research supervisor.

    Separate from `client` because the default app is deliberately built
    without one: `AGENT_AUTO_RESEARCH` gates the wiring in `web.py`, and the
    unwired case is a behaviour these tests check rather than a setup detail.
    """
    application = await _started(model=fake_model, db_path=db_path)
    api = create_app(
        application.service,
        application.feed,
        application.turns,
        corpus=application.corpus,
        research=application.research,
    )
    transport = ASGITransport(app=api)
    async with AsyncClient(transport=transport, base_url="http://test") as http:
        yield application, http
    await application.close()


async def test_the_run_routes_are_absent_unless_the_instance_was_wired_for_them(client):
    """404 rather than 403: a refusal announces the loop to whoever asked."""
    project_id = (await client.post("/api/projects", json={"name": "atlas"})).json()["id"]

    response = await client.post(f"/api/projects/{project_id}/auto-research", json={})

    assert response.status_code == 404
    assert "AGENT_AUTO_RESEARCH" in response.json()["detail"]


async def test_starting_a_run_answers_with_its_ids_before_it_has_finished(research_client):
    application, http = research_client
    project_id = (await http.post("/api/projects", json={"name": "atlas"})).json()["id"]

    response = await http.post(f"/api/projects/{project_id}/auto-research", json={})

    assert response.status_code == 202
    body = response.json()
    assert body["project_id"] == project_id
    # The run works turns on a session, and the caller is told which -- that
    # is where everything the agent actually said is visible.
    assert UUID(body["session_id"])
    await application.research.wait(UUID(project_id))


async def test_a_started_run_reports_its_own_fold(research_client):
    application, http = research_client
    project_id = (await http.post("/api/projects", json={"name": "atlas"})).json()["id"]
    started = await http.post(
        f"/api/projects/{project_id}/auto-research", json={"max_rounds": 2}
    )

    status = await http.get(f"/api/projects/{project_id}/auto-research")

    # Either the run is still in flight and reports its counters, or it has
    # already drained an empty queue -- both are folds of the same stream, and
    # which one this lands on is a race with a run that has nothing to do.
    if status.status_code == 200:
        assert status.json()["run_id"] == started.json()["run_id"]
        assert status.json()["budget"]["max_rounds"] == 2
    else:
        assert status.status_code == 404
    await application.research.wait(UUID(project_id))


async def test_asking_about_a_project_with_no_run_is_a_404(research_client):
    _, http = research_client
    project_id = (await http.post("/api/projects", json={"name": "atlas"})).json()["id"]

    response = await http.get(f"/api/projects/{project_id}/auto-research")

    assert response.status_code == 404


async def test_cancelling_nothing_reports_that_nothing_was_running(research_client):
    _, http = research_client
    project_id = (await http.post("/api/projects", json={"name": "atlas"})).json()["id"]

    response = await http.post(f"/api/projects/{project_id}/auto-research/cancel")

    assert response.status_code == 200
    assert response.json() == {"cancelled": False, "run": None}


async def test_a_finished_run_puts_its_session_away(research_client):
    """Or the second run on a project is refused by a session nobody is driving.

    This route starts the session the run works in, so nothing else will ever
    release it. Releasing is also what advances the project's tip, which is how
    anything a run wrote reaches the session that comes after it.
    """
    application, http = research_client
    project_id = (await http.post("/api/projects", json={"name": "atlas"})).json()["id"]

    first = await http.post(f"/api/projects/{project_id}/auto-research", json={})
    await application.research.wait(UUID(project_id))

    assert first.status_code == 202
    held = (await application.service.project_state(UUID(project_id))).active_session_id
    assert held is None
    second = await http.post(f"/api/projects/{project_id}/auto-research", json={})
    assert second.status_code == 202
    await application.research.wait(UUID(project_id))


async def test_a_run_on_an_unknown_project_is_a_404(research_client):
    _, http = research_client
    response = await http.post(f"/api/projects/{uuid4()}/auto-research", json={})
    assert response.status_code == 404
