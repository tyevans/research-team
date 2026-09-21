"""Turn supervisor, concurrency, and cancellation tests exercised over ASGI."""

import asyncio
from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient
from langchain_core.messages import AIMessage

from research_team.composition import build_application as _build_application
from research_team.infrastructure.agent.deep_agent import DeepAgentTurnExecutor
from research_team.interfaces.web import create_app
from research_team.interfaces.web.extraction import ExtractionActivity
from research_team.session.application.workers import (
    SummaryProjects,
    WorkerRoster,
)
from tests.application.test_turn_supervisor import SlowModel, once_inside_the_model
from tests.conftest import start_session


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
def extraction():
    """The buffer the app and its roster share -- the reporter's other end.

    Its own fixture so both sides of `app_and_client` and any test that drives
    it get the one instance. Two would let the `/workers` answer and the
    `/extraction` answer disagree about the same ingest, which is the failure
    the single-channel design rules out.
    """
    return ExtractionActivity()


@pytest.fixture
async def app_and_client(db_path, fake_model, extraction):
    application = await _started(model=fake_model, db_path=db_path)
    api = create_app(
        application.service,
        application.feed,
        application.turns,
        corpus=application.corpus,
        blob_store=application.blob_store,
        workers=WorkerRoster(
            application.service,
            turns=application.turns,
            runs=application.research,
            extractions=extraction,
            # Wired as the composition root wires it, so `/api/workers` is
            # exercised in its real shape: without this a running turn has no
            # way back to its project and the cross-project route would answer
            # empty while looking correct.
            summaries=SummaryProjects(application.summaries),
        ),
        extraction=extraction,
        # The application's own policy, not a fresh one: the routes are only
        # able to change anything because they hold the object the executor
        # reads, and a test against a copy would pass while proving nothing.
        policy=application.policy,
        topics=application.topic_readers,
        topic_repository=application.topic_repository,
        graphs=application.graphs,
    )
    transport = ASGITransport(app=api)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield application, client
    await application.close()


@pytest.fixture
def client(app_and_client):
    return app_and_client[1]


@pytest.fixture
async def slow_app(db_path):
    """A server whose turns are slow enough to interrupt on purpose."""
    model = SlowModel(responses=[AIMessage(content="eventually", id="s1")])
    application = await _started(model=model, db_path=db_path)
    api = create_app(application.service, application.feed, application.turns)
    async with AsyncClient(
        transport=ASGITransport(app=api, raise_app_exceptions=False),
        base_url="http://test",
    ) as client:
        yield application, client, model
    await application.close()


async def _new_session(client) -> str:
    """A session over HTTP, by the only route there is: a project, then a join.

    `POST /api/sessions` is gone -- a session belongs to a project, and joining
    one is where the project agrees to it. A project per call, with a unique
    name: a project holds one session at a time and creation rejects a
    duplicate name, so a shared one would fail the second caller in a rejection
    about neither of their subjects.
    """
    project = await client.post("/api/projects", json={"name": f"test project {uuid4()}"})
    assert project.status_code == 200
    response = await client.post(f"/api/projects/{project.json()['id']}/join")
    assert response.status_code == 200
    return response.json()["id"]


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
    session_id = await start_session(application.service)

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
    first_id = await start_session(application.service)
    second_id = await start_session(application.service)

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
    session_id = await start_session(application.service)
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
    application, client = app_and_client
    session_id = await start_session(application.service)

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


async def test_an_in_flight_turn_is_visible_and_cancellable(slow_app):
    application, client, model = slow_app
    session_id = await start_session(application.service)

    turn = asyncio.create_task(
        client.post(f"/api/sessions/{session_id}/turns", json={"input": "slow"})
    )
    await once_inside_the_model(model)

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
    application, client, model = slow_app
    session_id = await start_session(application.service)

    turn = asyncio.create_task(
        client.post(f"/api/sessions/{session_id}/turns", json={"input": "slow"})
    )
    await once_inside_the_model(model)

    second = await client.post(f"/api/sessions/{session_id}/turns", json={"input": "me too"})
    assert second.status_code == 409

    await client.post(f"/api/sessions/{session_id}/turns/cancel")
    assert (await turn).status_code == 499


async def test_the_session_still_works_after_a_cancellation(slow_app):
    application, client, model = slow_app
    session_id = await start_session(application.service)

    turn = asyncio.create_task(
        client.post(f"/api/sessions/{session_id}/turns", json={"input": "slow"})
    )
    await once_inside_the_model(model)
    await client.post(f"/api/sessions/{session_id}/turns/cancel")
    await turn

    model.delay = 0.0
    response = await client.post(f"/api/sessions/{session_id}/turns", json={"input": "quick"})

    assert response.status_code == 200
    assert response.json()["turn_index"] == 1  # the cancelled attempt never counted


async def test_a_running_turn_is_described_not_just_flagged(slow_app):
    """A tab arriving mid-turn should be able to say which turn, and for how long."""
    application, client, model = slow_app
    session_id = await start_session(application.service)

    turn = asyncio.create_task(
        client.post(f"/api/sessions/{session_id}/turns", json={"input": "slow"})
    )
    await once_inside_the_model(model)

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
    application, client, model = slow_app
    session_id = await start_session(application.service)

    turn = asyncio.create_task(
        client.post(f"/api/sessions/{session_id}/turns", json={"input": "slow"})
    )
    await once_inside_the_model(model)
    body = (await client.post(f"/api/sessions/{session_id}/turns/cancel")).json()
    await turn

    assert body == {"cancelled": True, "settled": True}

    events = (await client.get(f"/api/sessions/{session_id}/events")).json()
    failed = next(row for row in events if row["type"] == "TurnFailed")
    assert failed["cancelled"] is True
    assert "cancelled" in failed["summary"]


async def test_a_genuine_failure_is_not_marked_cancelled(app_and_client, monkeypatch):
    application, client = app_and_client
    session_id = await start_session(application.service)

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
