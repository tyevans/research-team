"""The five GETs the interaction explorer reads through.

Every store here is seeded through `POST /api/interactions` -- the real ingest
path -- and never through `store.record`. That is the whole point of the file:
a fixture that writes rows directly proves the reader can read rows it wrote
itself, and cannot see a decoder or a projection that stopped matching the
route the browser actually posts to.

For the same reason, no test here asserts only a status code. `CLAUDE.md`
records why: replay counts an event no projection handles as applied, so a
200 assertion passes with the projection deleted.
"""

from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient

from research_team.composition import build_application
from research_team.domain.interaction import INTERACTION_EVENTS
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


def _api(application, *, interactions=True, reader=True, failures=True):
    """The app, with each of the three interaction seams separately switchable.

    Three flags rather than one because the routes gate on three different
    things and conflating them is the defect the spec is most explicit about:
    `collecting` is the recorder, the 503 is the reader, and `failures` is the
    runner's DLQ.
    """
    return create_app(
        application.service,
        application.feed,
        application.turns,
        interactions=application.interaction_recorder if interactions else None,
        interaction_reader=((lambda: application.interaction_log.reader) if reader else None),
        interaction_failures=application.interaction_log.failures if failures else None,
    )


def _envelope(browser_session, install, seq, kind="ViewEntered", view="home", **over):
    body = {
        "kind": kind,
        "browser_session_id": str(browser_session),
        "install_id": str(install),
        "seq": seq,
        "view": view,
        "occurred_at": f"2026-08-17T10:00:{seq:02d}Z",
        "payload": {},
    }
    body.update(over)
    return body


def _client(api):
    return AsyncClient(transport=ASGITransport(app=api), base_url="http://test")


async def _seed(application, api, envelopes):
    """Write through the ingest route and wait for the projection.

    Asserts nothing was rejected: a typo in a payload here would otherwise
    show up as an empty read and be read as a broken reader.
    """
    async with _client(api) as client:
        response = await client.post("/api/interactions", json={"events": envelopes})
    assert response.status_code == 202
    assert response.json()["rejected"] == 0, response.json()
    await application.interaction_log_caught_up()


async def test_health_counts_what_the_ingest_route_stored(application):
    api = _api(application)
    browser_session, install = uuid4(), uuid4()
    await _seed(
        application,
        api,
        [
            _envelope(browser_session, install, 1),
            _envelope(
                browser_session,
                install,
                2,
                kind="ViewExited",
                payload={"dwell_ms": 2300, "hidden_ms": 400},
            ),
        ],
    )

    async with _client(api) as client:
        body = (await client.get("/api/interactions/health")).json()

    assert body["total"] == 2
    assert body["kinds"]["ViewEntered"] == 1
    assert body["kinds"]["ViewExited"] == 1
    assert body["install_count"] == 1
    assert body["session_count"] == 1
    assert body["first_at"] is not None and body["last_at"] is not None
    assert body["failures"] == []


async def test_healths_kinds_covers_the_whole_vocabulary(application):
    """Derived from `INTERACTION_EVENTS` by introspection, never listed.

    A hand-written list is the failure `CLAUDE.md` records under the
    checkpoint markers: it agrees with the code on the day it is written and
    stops noticing the moment a kind is added.
    """
    api = _api(application)
    async with _client(api) as client:
        body = (await client.get("/api/interactions/health")).json()

    expected = {event_type.__name__ for event_type in INTERACTION_EVENTS}
    assert expected <= set(body["kinds"])
    assert all(body["kinds"][name] == 0 for name in expected), (
        "a kind never emitted must report zero, not be absent -- otherwise "
        "'never happened' and 'does not exist' are the same response"
    )


async def test_health_says_collection_is_off_and_still_answers(application):
    """`AGENT_INTERACTION_LOG=0` is not a broken instrument.

    The recorder is absent and the reader is present, which is exactly what
    that variable produces. 503ing here would make "switched off" and
    "broken" the same response.
    """
    api = _api(application, interactions=False)
    async with _client(api) as client:
        response = await client.get("/api/interactions/health")

    assert response.status_code == 200
    body = response.json()
    assert body["collecting"] is False
    assert body["total"] == 0


async def test_health_says_collection_is_on_when_the_recorder_is_wired(application):
    api = _api(application)
    async with _client(api) as client:
        assert (await client.get("/api/interactions/health")).json()["collecting"] is True


async def test_sessions_reports_what_arrived_beside_the_browsers_own_counter(application):
    """`event_count` and `max_seq` disagree exactly when delivery lost
    something. Seeded with a gap in `seq` to prove the two are read from
    different places rather than from one number twice."""
    api = _api(application)
    browser_session, install = uuid4(), uuid4()
    project = uuid4()
    await _seed(
        application,
        api,
        [
            _envelope(browser_session, install, 1, project_id=str(project)),
            _envelope(browser_session, install, 7, view="project/catalog"),
        ],
    )

    async with _client(api) as client:
        body = (await client.get("/api/interactions/sessions")).json()

    assert body["total"] == 1
    (row,) = body["sessions"]
    assert row["browser_session_id"] == str(browser_session)
    assert row["install_id"] == str(install)
    assert row["event_count"] == 2
    assert row["max_seq"] == 7
    assert sorted(row["views"]) == ["home", "project/catalog"]
    assert row["project_ids"] == [str(project)]
    assert row["kinds"] == {"ViewEntered": 2}


async def test_sessions_over_the_cap_is_refused(application):
    api = _api(application)
    async with _client(api) as client:
        assert (await client.get("/api/interactions/sessions?limit=501")).status_code == 422


async def test_one_session_reads_in_seq_order(application):
    api = _api(application)
    browser_session, install = uuid4(), uuid4()
    await _seed(
        application,
        api,
        [
            _envelope(
                browser_session,
                install,
                2,
                kind="ViewExited",
                payload={"dwell_ms": 900, "hidden_ms": 0},
            ),
            _envelope(browser_session, install, 1),
        ],
    )

    async with _client(api) as client:
        body = (await client.get(f"/api/interactions/sessions/{browser_session}")).json()

    rows = body["events"]
    assert [row["seq"] for row in rows] == [1, 2]
    assert [row["kind"] for row in rows] == ["ViewEntered", "ViewExited"]
    assert rows[1]["payload"]["dwell_ms"] == 900, (
        "the payload decodes on the way out -- SQLite hands it back as JSON text"
    )


async def test_an_unknown_session_is_not_found(application):
    api = _api(application)
    async with _client(api) as client:
        response = await client.get(f"/api/interactions/sessions/{uuid4()}")

    assert response.status_code == 404


async def test_events_totals_the_filter_not_the_page(application):
    """A reader who cannot tell 3-of-3 from 3-of-9 cannot tell a filter that
    found everything from one that hit the cap."""
    api = _api(application)
    browser_session, install = uuid4(), uuid4()
    await _seed(
        application,
        api,
        [_envelope(browser_session, install, seq) for seq in range(1, 10)],
    )

    async with _client(api) as client:
        body = (await client.get("/api/interactions/events?limit=3")).json()

    assert len(body["events"]) == 3
    assert body["total"] == 9
    assert body["limit"] == 3
    assert body["offset"] == 0


async def test_events_filters_by_kind_and_view(application):
    api = _api(application)
    browser_session, install = uuid4(), uuid4()
    await _seed(
        application,
        api,
        [
            _envelope(browser_session, install, 1, view="home"),
            _envelope(browser_session, install, 2, view="project/catalog"),
            _envelope(
                browser_session,
                install,
                3,
                kind="ViewExited",
                view="home",
                payload={"dwell_ms": 100, "hidden_ms": 0},
            ),
        ],
    )

    async with _client(api) as client:
        by_kind = (await client.get("/api/interactions/events?kind=ViewExited")).json()
        by_view = (await client.get("/api/interactions/events?view=home")).json()
        both = (
            await client.get(
                "/api/interactions/events?kind=ViewEntered&kind=ViewExited&view=home"
            )
        ).json()

    assert by_kind["total"] == 1
    assert [row["kind"] for row in by_kind["events"]] == ["ViewExited"]
    assert by_view["total"] == 2
    assert both["total"] == 2, "repeated `kind` is a set, not the last one wins"


async def test_events_orders_newest_first_by_default(application):
    api = _api(application)
    browser_session, install = uuid4(), uuid4()
    await _seed(
        application,
        api,
        [_envelope(browser_session, install, seq) for seq in (1, 2, 3)],
    )

    async with _client(api) as client:
        newest = (await client.get("/api/interactions/events")).json()
        oldest = (await client.get("/api/interactions/events?order=oldest")).json()

    assert [row["seq"] for row in newest["events"]] == [3, 2, 1]
    assert [row["seq"] for row in oldest["events"]] == [1, 2, 3]


async def test_an_unknown_kind_is_refused_rather_than_answered_empty(application):
    """On the server an unrecognised kind is a caller error, and an empty page
    is what a correct filter over a quiet log looks like. Answering `[]` makes
    a typo indistinguishable from an instrument that stopped."""
    api = _api(application)
    async with _client(api) as client:
        response = await client.get("/api/interactions/events?kind=NotAKind")

    assert response.status_code == 422
    assert "NotAKind" in response.json()["detail"]


async def test_events_over_the_cap_is_refused(application):
    api = _api(application)
    async with _client(api) as client:
        assert (await client.get("/api/interactions/events?limit=1001")).status_code == 422


async def test_summary_aggregates_dwell_friction_and_approvals(application):
    api = _api(application)
    browser_session, install = uuid4(), uuid4()
    await _seed(
        application,
        api,
        [
            _envelope(browser_session, install, 1, view="project/catalog"),
            _envelope(
                browser_session,
                install,
                2,
                kind="ViewExited",
                view="project/catalog",
                payload={"dwell_ms": 2000, "hidden_ms": 500},
            ),
            _envelope(
                browser_session,
                install,
                3,
                kind="EmptyResultEncountered",
                payload={"where": "search", "query_length": 4},
            ),
            _envelope(
                browser_session,
                install,
                4,
                kind="ApprovalDecided",
                payload={
                    "decision": "approved",
                    "latency_ms": 900,
                    "hidden_ms": 0,
                    "expanded_details": False,
                },
            ),
            _envelope(
                browser_session,
                install,
                5,
                kind="ApprovalDecided",
                payload={
                    "decision": "rejected",
                    "latency_ms": 14200,
                    "hidden_ms": 0,
                    "expanded_details": True,
                },
            ),
        ],
    )

    async with _client(api) as client:
        body = (await client.get("/api/interactions/summary")).json()

    assert body["by_kind"]["ViewEntered"] == 1
    (view,) = [row for row in body["by_view"] if row["view"] == "project/catalog"]
    assert view["entries"] == 1
    assert view["exits"] == 1
    assert view["dwell_ms_median"] == 2000
    assert view["hidden_ms_median"] == 500, (
        "hidden time is reported beside dwell and never subtracted from it"
    )
    assert body["friction"]["empty_results"] == 1
    assert body["friction"]["empty_by_where"] == [{"where": "search", "count": 1}]
    assert body["approvals"]["total"] == 2
    assert body["approvals"]["expanded"] == 1
    assert body["approvals"]["by_decision"] == {"approved": 1, "rejected": 1}
    assert body["approvals"]["median_latency_ms_plain"] == 900
    assert body["approvals"]["median_latency_ms_expanded"] == 14200


async def test_summary_narrows_with_the_same_filters_events_takes(application):
    api = _api(application)
    browser_session, install = uuid4(), uuid4()
    await _seed(
        application,
        api,
        [
            _envelope(browser_session, install, 1, view="home"),
            _envelope(browser_session, install, 2, view="project/catalog"),
        ],
    )

    async with _client(api) as client:
        body = (await client.get("/api/interactions/summary?view=home")).json()

    assert body["by_kind"]["ViewEntered"] == 1
    assert [row["view"] for row in body["by_view"]] == ["home"]


@pytest.mark.parametrize(
    "path",
    [
        "/api/interactions/health",
        "/api/interactions/sessions",
        f"/api/interactions/sessions/{uuid4()}",
        "/api/interactions/events",
        "/api/interactions/summary",
    ],
)
async def test_every_read_is_unavailable_without_a_reader(application, path):
    api = _api(application, reader=False)
    async with _client(api) as client:
        response = await client.get(path)

    assert response.status_code == 503
    assert "reader" in response.json()["detail"]
