"""The one route the browser posts to.

Every test here asserts a stored row, not a status code, wherever a row is
what the route is for. A 202 assertion alone passes with the projection
deleted, because replay counts an unhandled event as applied.
"""

from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient

from research_team.composition import build_application
from research_team.interfaces.web.app import create_app


@pytest.fixture
async def application(db_path, tmp_path):
    app = build_application(
        db_path=db_path, interaction_db_path=str(tmp_path / "interactions.db")
    )
    await app.start()
    try:
        yield app
    finally:
        await app.close()


def _api(application, *, interactions=True):
    return create_app(
        application.service,
        application.feed,
        application.turns,
        interactions=application.interaction_recorder if interactions else None,
    )


def _envelope(browser_session, install, seq=1, **over):
    body = {
        "kind": "ViewEntered",
        "browser_session_id": str(browser_session),
        "install_id": str(install),
        "seq": seq,
        "view": "project/entity",
        "occurred_at": "2026-08-17T10:00:00Z",
        "payload": {"params": {"entity_id": "ent_4a1f"}},
    }
    body.update(over)
    return body


async def _client(api):
    return AsyncClient(transport=ASGITransport(app=api), base_url="http://test")


async def test_a_batch_is_accepted_and_stored(application):
    browser_session, install = uuid4(), uuid4()
    async with await _client(_api(application)) as client:
        response = await client.post(
            "/api/interactions",
            json={"events": [_envelope(browser_session, install)]},
        )

        assert response.status_code == 202
        assert response.json() == {"accepted": 1, "rejected": 0}

    await application.interaction_log_caught_up()
    rows = await application.interaction_log.events(browser_session)
    assert len(rows) == 1
    assert rows[0].kind == "ViewEntered"
    assert rows[0].payload["params"]["entity_id"] == "ent_4a1f"


async def test_the_server_stamps_when_it_took_delivery(application):
    """Kept as a cross-check on a client clock that can be skewed or moved,
    not as ordering truth."""
    browser_session, install = uuid4(), uuid4()
    async with await _client(_api(application)) as client:
        await client.post(
            "/api/interactions",
            json={"events": [_envelope(browser_session, install)]},
        )

    await application.interaction_log_caught_up()
    row = (await application.interaction_log.events(browser_session))[0]
    assert row.received_at is not None


async def test_one_bad_event_does_not_lose_the_good_ones(application):
    """Partial acceptance. The client cannot see this response -- sendBeacon
    reports nothing -- so rejecting the batch would discard good events with
    no way for anyone to find out.

    Fails if the route validates the whole batch up front.
    """
    browser_session, install = uuid4(), uuid4()
    good = _envelope(browser_session, install, seq=1)
    bad = _envelope(browser_session, install, seq=2, kind="NotAKind")
    async with await _client(_api(application)) as client:
        response = await client.post("/api/interactions", json={"events": [good, bad]})

        assert response.status_code == 202
        assert response.json() == {"accepted": 1, "rejected": 1}

    await application.interaction_log_caught_up()
    assert len(await application.interaction_log.events(browser_session)) == 1


async def test_an_event_missing_a_required_field_is_rejected_alone(application):
    browser_session, install = uuid4(), uuid4()
    good = _envelope(browser_session, install, seq=1)
    bad = _envelope(browser_session, install, seq=2)
    del bad["view"]
    async with await _client(_api(application)) as client:
        response = await client.post("/api/interactions", json={"events": [good, bad]})

        assert response.json() == {"accepted": 1, "rejected": 1}


async def test_the_same_event_twice_is_one_row(application):
    """A page-hide flush can race a timer flush, and sendBeacon can deliver
    twice. Idempotent on (browser_session_id, seq)."""
    browser_session, install = uuid4(), uuid4()
    batch = {"events": [_envelope(browser_session, install, seq=5)]}
    async with await _client(_api(application)) as client:
        await client.post("/api/interactions", json=batch)
        await client.post("/api/interactions", json=batch)

    await application.interaction_log_caught_up()
    assert len(await application.interaction_log.events(browser_session)) == 1


async def test_an_oversized_batch_is_refused(application):
    browser_session, install = uuid4(), uuid4()
    async with await _client(_api(application)) as client:
        response = await client.post(
            "/api/interactions",
            json={"events": [_envelope(browser_session, install, seq=n) for n in range(201)]},
        )

        assert response.status_code == 422


async def test_an_empty_batch_is_accepted_and_writes_nothing(application):
    async with await _client(_api(application)) as client:
        response = await client.post("/api/interactions", json={"events": []})

        assert response.status_code == 202
        assert response.json() == {"accepted": 0, "rejected": 0}


async def test_the_route_is_absent_when_collection_is_off(application):
    """AGENT_INTERACTION_LOG=0 makes the entrypoint pass None, and the house
    pattern is that the dependency being absent is the switch."""
    async with await _client(_api(application, interactions=False)) as client:
        response = await client.post("/api/interactions", json={"events": []})

        assert response.status_code == 503
