"""The HTTP adapter, exercised over ASGI with no network and no real model."""

import asyncio
import json

import pytest
from httpx import ASGITransport, AsyncClient
from langchain_core.messages import AIMessage

from research_team.composition import build_application
from research_team.interfaces.web import create_app


@pytest.fixture
async def app_and_client(db_path, fake_model):
    application = build_application(model=fake_model, db_path=db_path)
    api = create_app(application.service, application.feed, application.turns)
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
    response = await client.post(
        f"/api/sessions/{session_id}/turns", json={"input": "hello"}
    )
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
    application = build_application(model=writing_model, db_path=db_path)
    api = create_app(application.service, application.feed, application.turns)
    async with AsyncClient(
        transport=ASGITransport(app=api), base_url="http://test"
    ) as client:
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

    forked = (
        await client.post(f"/api/sessions/{session_id}/forks", json={"at": 1})
    ).json()["id"]

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
    child = (await client.post(f"/api/sessions/{parent}/forks", json={"at": 1})).json()[
        "id"
    ]

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
    aggregate.start("prompt", "test-model")
    await repository.save(aggregate)

    frames: list[str] = []
    generator = _sse(StubRequest(), feed)
    task = asyncio.create_task(_drain(generator, frames, wanted=1))
    await asyncio.sleep(0.05)
    aggregate.send_user_message({"type": "human", "data": {"content": "hi"}})
    await repository.save(aggregate)
    await asyncio.wait_for(task, timeout=5)

    assert frames[0].startswith("data: ")
    assert frames[0].endswith("\n\n")
    payload = json.loads(frames[0][len("data: ") :])
    assert payload["session_id"] == str(session_id)
    assert payload["type"] == "UserMessageSent"


async def _drain(generator, frames: list[str], *, wanted: int) -> None:
    """Collect `wanted` data frames, then shut the generator down.

    Leaving it suspended would leave its poll loop holding the store open past
    the end of the test, which surfaces much later as a stray database error.
    """
    try:
        async for frame in generator:
            if frame.startswith("data: "):
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

    application = build_application(model=fake_model, db_path=db_path)
    api = create_app(application.service, application.feed, application.turns)
    config = uvicorn.Config(api, host="127.0.0.1", port=8749, log_level="error")
    server = uvicorn.Server(config)
    serving = asyncio.create_task(server.serve())
    while not server.started:
        await asyncio.sleep(0.02)

    received: list[dict] = []

    async def listen() -> None:
        async with AsyncClient(timeout=20) as browser:
            async with browser.stream(
                "GET", "http://127.0.0.1:8749/api/stream"
            ) as response:
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
        await client.get(
            f"/api/sessions/{session_id}/files", params={"path": "/hello.py"}
        )
    ).json()

    assert past["at"] == write_index
    assert "hi" in past["content"]
    assert "hello" not in past["content"]
    assert "hello" in head["content"]


async def test_a_file_deleted_later_is_still_readable_in_the_past(db_path, fake_model):
    """The headline case: seeing a deleted file again is the point."""
    application = build_application(model=fake_model, db_path=db_path)
    api = create_app(application.service, application.feed, application.turns)
    session_id = await application.service.create_session()
    session = await application.service.load(session_id)
    session.write_file("/doomed.py", {"content": "still here\n"})
    session.delete_file("/doomed.py")
    await application.service._repository.save(session)

    async with AsyncClient(
        transport=ASGITransport(app=api), base_url="http://test"
    ) as client:
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
    application = build_application(model=model, db_path=db_path)
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

    second = await client.post(
        f"/api/sessions/{session_id}/turns", json={"input": "me too"}
    )
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
    response = await client.post(
        f"/api/sessions/{session_id}/turns", json={"input": "quick"}
    )

    assert response.status_code == 200
    assert response.json()["turn_index"] == 1  # the cancelled attempt never counted
