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


async def test_a_payload_carrying_an_envelope_key_is_rejected_alone(application):
    """A payload that names an envelope-owned key (`seq`, here) collides with
    the explicit keyword the route passes to the same constructor -- a
    `TypeError`, not a `ValidationError`, if nothing guards against it. Before
    the fix this escaped the route's try/except entirely and 500'd the whole
    batch, losing the good event beside it. Fails if the collision check is
    removed and the whole batch is lost with it.
    """
    browser_session, install = uuid4(), uuid4()
    good = _envelope(browser_session, install, seq=1)
    bad = _envelope(browser_session, install, seq=2)
    bad["payload"] = {**bad["payload"], "seq": 999}
    async with await _client(_api(application)) as client:
        response = await client.post("/api/interactions", json={"events": [good, bad]})

        assert response.status_code == 202
        assert response.json() == {"accepted": 1, "rejected": 1}

    await application.interaction_log_caught_up()
    assert len(await application.interaction_log.events(browser_session)) == 1


async def test_the_stored_row_reflects_the_envelope_never_the_payload(application):
    """Even when a payload names an envelope key with a value that would be
    harmless to accept, the envelope is the authority: the event is rejected
    rather than the payload's value being allowed to override it."""
    browser_session, install = uuid4(), uuid4()
    other_install = uuid4()
    event = _envelope(browser_session, install, seq=7)
    event["payload"] = {**event["payload"], "install_id": str(other_install)}
    async with await _client(_api(application)) as client:
        response = await client.post("/api/interactions", json={"events": [event]})

        assert response.json() == {"accepted": 0, "rejected": 1}

    await application.interaction_log_caught_up()
    assert await application.interaction_log.events(browser_session) == []


async def test_the_route_is_absent_when_collection_is_off(application):
    """AGENT_INTERACTION_LOG=0 makes the entrypoint pass None, and the house
    pattern is that the dependency being absent is the switch."""
    async with await _client(_api(application, interactions=False)) as client:
        response = await client.post("/api/interactions", json={"events": []})

        assert response.status_code == 503


async def test_an_oversized_body_is_refused_before_it_is_parsed(application):
    """The design promised a body-size cap alongside the batch limit and only
    the batch limit shipped. One event is enough to exceed it, so this also
    shows the cap is not merely the batch limit restated.

    Proved red without the middleware: 202, the whole body buffered and
    parsed. Asserts 413 rather than a stored row because refusing before
    parsing is the entire point.

    `tests/interfaces/test_extraction_routes.py` is the other half of this
    test: the first version of the cap used `@app.middleware("http")` and
    turned four of those red without touching an interaction route. See
    `_InteractionBodyCap`.
    """
    browser_session, install = uuid4(), uuid4()
    event = _envelope(browser_session, install)
    event["payload"] = {"params": {"entity_id": "x" * 3_000_000}}
    async with await _client(_api(application)) as client:
        response = await client.post("/api/interactions", json={"events": [event]})

        assert response.status_code == 413


async def test_a_payload_carrying_an_unnamed_envelope_key_is_rejected_alone(application):
    """`actor_id` is an envelope field the route's original hand-picked
    exclusion set did not name -- nor `tenant_id`, `metadata`,
    `aggregate_type` or five others. Unlike `seq` above it collides with no
    explicit keyword, so nothing raised: the value was *accepted* and written
    into the event blob -- arbitrary user text outside `TEXT_BEARING_FIELDS`,
    which `row_for` then stripped out of `interaction_events`, leaving it
    invisible to anyone reading the table.

    Proved red against the hand-picked set: `{'accepted': 2, 'rejected': 0}`
    -- nothing rejected, the text stored. (`actor_id` is `str | None` on
    `DomainEvent`, so pydantic had no objection either.)
    """
    browser_session, install = uuid4(), uuid4()
    good = _envelope(browser_session, install, seq=1)
    bad = _envelope(browser_session, install, seq=2)
    bad["payload"] = {
        **bad["payload"],
        "actor_id": "a research prompt about something private",
    }
    async with await _client(_api(application)) as client:
        response = await client.post("/api/interactions", json={"events": [good, bad]})

        assert response.status_code == 202
        assert response.json() == {"accepted": 1, "rejected": 1}

    await application.interaction_log_caught_up()
    assert len(await application.interaction_log.events(browser_session)) == 1


async def test_a_forged_aggregate_type_is_rejected(application):
    """The recorder always appends under the `browser_session` category, so an
    event whose own JSON says otherwise is two fields that must agree and
    don't -- the exact pairing `domain/interaction.py` argues against.

    Proved red against the hand-picked set: `{'accepted': 1, 'rejected': 0}`,
    with `"aggregate_type":"forged"` in the stored event blob while the stream
    it lived in was `browser_session`.
    """
    browser_session, install = uuid4(), uuid4()
    event = _envelope(browser_session, install, seq=3)
    event["payload"] = {**event["payload"], "aggregate_type": "forged"}
    async with await _client(_api(application)) as client:
        response = await client.post("/api/interactions", json={"events": [event]})

        assert response.json() == {"accepted": 0, "rejected": 1}


async def test_an_essay_in_query_text_is_rejected_alone(application):
    """`main` raised the document cap to 500,000 characters and the ask box
    records what was typed verbatim, so pasting a document into it wrote that
    document into the most sensitive field in the system -- and 200 of them in
    one batch is a ~100 MB body the route buffered and stored.

    Bounded at the domain so an over-long one is a per-event reject rather
    than a 500 that loses the batch. Proved red without the bound:
    `{'accepted': 2, 'rejected': 0}`, all 20,000 characters in the row.
    """
    browser_session, install = uuid4(), uuid4()
    good = _envelope(
        browser_session,
        install,
        seq=1,
        kind="AskSubmitted",
        payload={"query_text": "what did we find?"},
    )
    bad = _envelope(
        browser_session,
        install,
        seq=2,
        kind="AskSubmitted",
        payload={"query_text": "x" * 20_000},
    )
    async with await _client(_api(application)) as client:
        response = await client.post("/api/interactions", json={"events": [good, bad]})

        assert response.json() == {"accepted": 1, "rejected": 1}

    await application.interaction_log_caught_up()
    rows = await application.interaction_log.events(browser_session)
    assert [row.payload["query_text"] for row in rows] == ["what did we find?"]
