"""The route, driven by the bytes the browser actually serialises.

B146. `tests/interfaces/test_interaction_routes.py` covers this route well and
cannot cover this: its `_envelope` is hand-written Python, so it supplies the
contract it is checking -- CLAUDE.md's fixture rule, one language over. The
console's own tests have the same problem from the other side, asserting
against an `InteractionEvent` interface declared in TypeScript.

So the fixture is a file neither side writes by hand.
`frontend/src/infrastructure/http/interaction-wire-format.test.ts` produces it
from the real emitter and the real `HttpInteractionSink`, through the same
`JSON.stringify` and the same `Blob` `navigator.sendBeacon` carries. This
posts those bytes, unmodified, and asserts a stored row per event.

What breaks it, which is the point: a field renamed on either side, a kind the
browser can send that the route does not register, a `null` where the server
requires a value, a UUID sent as something the decoder refuses. None of those
are visible to either end alone.

What it does not cover: HTTP itself -- no browser runs here. `sendBeacon`'s
`Content-Type` handling has its own comment in the adapter and no test; a
Playwright job is the only thing that would cover it and is not worth a CI job
for one header.
"""

import json
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from httpx import ASGITransport, AsyncClient

from research_team.composition import build_application
from research_team.domain.interaction import INTERACTION_EVENTS
from research_team.interfaces.web.app import create_app

WIRE_FIXTURE = (
    Path(__file__).resolve().parents[2]
    / "frontend"
    / "src"
    / "infrastructure"
    / "http"
    / "interaction-wire-format.fixture.json"
)


def _batch() -> dict:
    """The committed batch, with fresh identity ids.

    `browser_session_id` and `install_id` are rewritten per test rather than
    taken from the file: the route dedupes on `(browser_session_id, seq)`, and
    two tests sharing the fixture's literal pair would have the second one
    silently accepted and stored nothing. Every other field, including every
    payload, is exactly what the browser sent.
    """
    body = json.loads(WIRE_FIXTURE.read_text())
    browser_session, install = str(uuid4()), str(uuid4())
    for event in body["events"]:
        event["browser_session_id"] = browser_session
        event["install_id"] = install
    return body


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


async def test_the_browsers_own_batch_is_accepted_and_every_event_stored(application):
    """One row per event, not a 202.

    A status assertion passes with the projection deleted -- replay counts an
    event no projection handles as applied (CLAUDE.md, "Events"). The count and
    the kinds are what the route is for.
    """
    api = create_app(
        application.service,
        application.feed,
        application.turns,
        interactions=application.interaction_recorder,
    )
    body = _batch()
    browser_session = UUID(body["events"][0]["browser_session_id"])

    async with AsyncClient(transport=ASGITransport(app=api), base_url="http://test") as client:
        response = await client.post("/api/interactions", json=body)

        assert response.status_code == 202, response.text
        # Named rather than left implicit: the route accepts partially, so a
        # single rejected event is a 202 with a count nobody would notice.
        assert response.json() == {"accepted": len(body["events"]), "rejected": 0}

    await application.interaction_log_caught_up()
    rows = await application.interaction_log.events(browser_session)

    assert {row.kind for row in rows} == {event["kind"] for event in body["events"]}
    assert len(rows) == len(body["events"])


def test_the_fixture_carries_every_kind_the_server_registers():
    """The other half of the console-side completeness check.

    That one pins the fixture against `INTERACTION_KINDS` in TypeScript; this
    pins it against `INTERACTION_EVENTS` in Python. Both are needed: a kind
    added to the server and not to the browser is invisible to the first, and
    the reverse is invisible to the second. Together they make the two
    vocabularies one.
    """
    fixture_kinds = {event["kind"] for event in json.loads(WIRE_FIXTURE.read_text())["events"]}

    assert fixture_kinds == {event.__name__ for event in INTERACTION_EVENTS}
