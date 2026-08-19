"""The routes the resolved widgets call, against a project nothing has opened.

CLAUDE.md's "Read models" section names the trap this file exists for: a
fixture that seeds through the same call the code under test depends on cannot
see that dependency go missing. `test_definition_wiring.py`'s `_seed` calls
`application.graphs.open(project_id)` to plant its entity, so from every test
in that file the project is always already open -- and a route that stopped
opening it would answer 503 exactly once per project, on the first request,
and be invisible.

So every test here creates a project and then *does not touch it*. The claim
is narrow and worth stating plainly: these routes answer, rather than 503,
for a project no fixture has opened. An empty graph is the right corpus for
that claim -- what is under test is the open, not the answer.

These would pass with the resolved components reverted entirely: they cover
the routes the widgets call, which predate this feature. They are here
because the widgets are the first callers to hit those routes on a project
the console has never displayed, which is exactly the path the once-per-
project 503 lives on.
"""

from uuid import UUID, uuid4

import pytest
from httpx import ASGITransport, AsyncClient

from research_team.composition import build_application
from research_team.interfaces.web import create_app


@pytest.fixture
async def client(db_path):
    application = build_application(db_path=db_path)
    await application.start()
    api = create_app(
        application.service,
        application.feed,
        application.turns,
        corpus=application.corpus,
        blob_store=application.blob_store,
        graphs=application.graphs,
        definitions=application.definition_readers,
    )
    transport = ASGITransport(app=api)
    async with AsyncClient(transport=transport, base_url="http://test") as http:
        yield http
    await application.close()


async def _untouched_project(client: AsyncClient) -> UUID:
    """A project created through the API and opened by nothing.

    Deliberately does not call `graphs.open`, `graphs.chunks`, or any route
    that would. That omission is the entire test.
    """
    created = await client.post("/api/projects", json={"name": f"widget-{uuid4()}"})
    assert created.status_code == 200
    return UUID(created.json()["id"])


async def test_a_name_search_answers_for_a_project_nothing_has_opened(client):
    """The first request a `definition` widget makes.

    Red against a build whose `/graph/entities` route fetches a reader without
    opening the project first -- 503 on the first call for every project, 200
    on every call after it, which reads as flakiness rather than as a bug.
    """
    project_id = await _untouched_project(client)

    response = await client.get(f"/api/projects/{project_id}/graph/entities?name=Constantine")

    assert response.status_code == 200
    assert response.json()["entities"] == []


async def test_a_definition_answers_for_a_project_nothing_has_opened(client):
    """The widget's *second* request, on the same never-opened project.

    The entity id names nothing, so the answer is a 404 -- and the assertion
    is deliberately "not 503" rather than "== 404". What is under test is
    whether the route opened the project before reaching for a reader; which
    of the honest answers it then gives about an entity that does not exist
    is a different claim, and pinning it here would make this test fail for
    reasons that have nothing to do with the trap.
    """
    project_id = await _untouched_project(client)

    response = await client.get(
        f"/api/projects/{project_id}/graph/entities/{uuid4()}/definition"
    )

    assert response.status_code != 503, response.text


async def test_a_neighbourhood_answers_404_not_503_on_an_unopened_project(client):
    """The second request a `graph` widget makes.

    404 is the *right* answer here -- no such entity in an empty graph -- and
    503 is the fixture trap: it means the route reached for a reader without
    opening the project. The two are a character apart in a log and say
    opposite things about whether the build is wired.

    Pinned to 404 rather than the sibling test's `!= 503`, because this route
    has only one honest answer for an id nothing stored: `neighborhood`
    returns `None` and the route turns that into a 404. There is no second
    plausible status for the assertion to be brittle against.
    """
    project_id = await _untouched_project(client)
    unknown = uuid4()

    response = await client.get(
        f"/api/projects/{project_id}/graph/entities/{unknown}/neighborhood?depth=1"
    )

    assert response.status_code == 404, response.text


async def test_a_timeline_answers_for_a_project_nothing_has_opened(client):
    """The only request a `timeline` widget makes.

    `_timeline_reader` opens through `graphs` so the timeline and the graph
    read the *same* store rather than two folds of one log -- which is exactly
    the call a refactor drops, and dropping it is a 503 on the first request
    for every project and a 200 on every one after.
    """
    project_id = await _untouched_project(client)

    response = await client.get(
        f"/api/projects/{project_id}/timeline?entity_type=Person&from=0300-01-01"
    )

    assert response.status_code == 200, response.text
    assert response.json()["bands"] == []


async def test_a_timeline_refuses_an_unparseable_bound_rather_than_widening_it(client):
    """The one place in this feature's routes that 422s instead of clamping.

    Almost everything else the resolved widgets call clamps a bad argument --
    `/documents/{id}/text` clamps its offsets, `/timeline` clamps its `limit`.
    `from`/`to` do not, deliberately (`app.py`'s `read_timeline` docstring): a
    client that mistyped a date and got the whole timeline back has been
    answered a different question with no way to tell. The widget renders this
    as prose, so this test is what says there *is* a 422 to render.

    Red against a route that fell back to "no window" on an unparseable bound
    -- which would answer 200 here.
    """
    project_id = await _untouched_project(client)

    response = await client.get(f"/api/projects/{project_id}/timeline?from=the+fourth+century")

    assert response.status_code == 422, response.text


async def test_an_unfiltered_timeline_answers_for_a_project_nothing_has_opened(client):
    """The `explorer` widget's *vocabulary* read, which is a request no other
    widget makes: `/timeline` with no `entity_type` at all, so the response
    carries every type the picker can offer.

    Deliberately separate from `test_a_timeline_answers_for_a_project_nothing_
    has_opened` above rather than parametrised onto it. That test sends
    `entity_type=Person`, and CLAUDE.md's fixture trap is exactly the class of
    bug where the shape of a request decides whether a dependency is exercised
    -- collapsing the two would leave the unfiltered path with no test of its
    own starting from an untouched project.

    Red against a route that reached for a reader without opening the project:
    503 on the first request for every project and 200 on every one after,
    which reads as flakiness rather than as a bug.
    """
    project_id = await _untouched_project(client)

    response = await client.get(f"/api/projects/{project_id}/timeline")

    assert response.status_code == 200, response.text
    assert response.json()["bands"] == []
