"""The four write routes over a project's corpus.

Built through the real `CorpusEditor` and a real `Corpus` aggregate, over a
started application, rather than through doubles like
`test_extraction_routes.py`: the interesting behaviour here is `CorpusEditor`'s
own -- the existence check, the aggregate's refusals, the fold that turns a
restore into a fresh record -- and stubbing it out would leave these tests
asserting that the routes forward calls correctly, which is a smaller and less
useful claim.
"""

from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient

from research_team.composition import build_application as _build_application
from research_team.interfaces.web.app import create_app


async def _started(**kwargs):
    application = _build_application(**kwargs)
    await application.start()
    return application


@pytest.fixture
async def app_and_client(db_path, fake_model):
    application = await _started(model=fake_model, db_path=db_path)
    api = create_app(
        application.service,
        application.feed,
        application.turns,
        corpus=application.corpus,
        editor=application.editor,
    )
    transport = ASGITransport(app=api)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield application, client
    await application.close()


@pytest.fixture
async def app_without_corpus(app_and_client):
    """Neither `corpus` nor `editor` wired -- see the RULING in the brief.

    `_editor()` only checks `editor`, and the two are separately injected, so
    a fixture that supplied one and not the other would exercise a route that
    fails further in (reading back through `_reader`, which would then be the
    thing 503ing) rather than the write-side check this test means to cover.
    """
    application, _ = app_and_client
    api = create_app(
        application.service,
        application.feed,
        application.turns,
        corpus=None,
        editor=None,
    )
    transport = ASGITransport(app=api)
    async with AsyncClient(transport=transport, base_url="http://test") as unwired:
        project = await _new_project(unwired)
        yield unwired, project


async def _new_project(client: AsyncClient) -> str:
    created = await client.post("/api/projects", json={"name": f"corpus-{uuid4()}"})
    assert created.status_code == 200
    return created.json()["id"]


async def test_upload_stores_a_document(app_and_client):
    _app, client = app_and_client
    project = await _new_project(client)

    response = await client.post(
        f"/api/projects/{project}/sources",
        json={"source_id": "s1", "text": "hello", "title": "Hello"},
    )

    assert response.status_code == 201
    assert response.json()["source_id"] == "s1"
    listed = (await client.get(f"/api/projects/{project}/sources")).json()
    assert [row["source_id"] for row in listed] == ["s1"]


async def test_upload_refuses_an_id_the_corpus_holds(app_and_client):
    _app, client = app_and_client
    project = await _new_project(client)
    await client.post(
        f"/api/projects/{project}/sources", json={"source_id": "s1", "text": "hello"}
    )

    response = await client.post(
        f"/api/projects/{project}/sources", json={"source_id": "s1", "text": "other"}
    )

    assert response.status_code == 409


async def test_a_patch_changes_the_title_and_leaves_the_text(app_and_client):
    _app, client = app_and_client
    project = await _new_project(client)
    await client.post(
        f"/api/projects/{project}/sources",
        json={"source_id": "s1", "text": "hello", "title": "Typo"},
    )

    response = await client.patch(
        f"/api/projects/{project}/sources/s1", json={"title": "Fixed"}
    )

    assert response.status_code == 200
    assert response.json()["title"] == "Fixed"
    read_back = (await client.get(f"/api/projects/{project}/sources/s1")).json()
    assert read_back["text"] == "hello"


async def test_a_patch_on_an_unknown_source_is_404(app_and_client):
    _app, client = app_and_client
    project = await _new_project(client)
    await client.post(
        f"/api/projects/{project}/sources", json={"source_id": "s1", "text": "hello"}
    )

    response = await client.patch(
        f"/api/projects/{project}/sources/missing", json={"title": "x"}
    )

    assert response.status_code == 404


async def test_drop_excludes_the_document_and_restore_puts_it_back(app_and_client):
    _app, client = app_and_client
    project = await _new_project(client)
    await client.post(
        f"/api/projects/{project}/sources", json={"source_id": "s1", "text": "hello"}
    )

    dropped = await client.post(
        f"/api/projects/{project}/sources/s1/drop", json={"reason": "off topic"}
    )
    assert dropped.status_code == 200
    assert (await client.get(f"/api/projects/{project}/sources")).json() == []

    restored = await client.post(f"/api/projects/{project}/sources/s1/restore", json={})
    assert restored.status_code == 200
    assert restored.json()["dropped_reason"] is None
    assert len((await client.get(f"/api/projects/{project}/sources")).json()) == 1


async def test_drop_refuses_a_blank_reason(app_and_client):
    _app, client = app_and_client
    project = await _new_project(client)
    await client.post(
        f"/api/projects/{project}/sources", json={"source_id": "s1", "text": "hello"}
    )

    response = await client.post(
        f"/api/projects/{project}/sources/s1/drop", json={"reason": "  "}
    )

    assert response.status_code == 409


async def test_restore_refuses_a_document_that_is_not_dropped(app_and_client):
    _app, client = app_and_client
    project = await _new_project(client)
    await client.post(
        f"/api/projects/{project}/sources", json={"source_id": "s1", "text": "hello"}
    )

    response = await client.post(f"/api/projects/{project}/sources/s1/restore", json={})

    assert response.status_code == 409


async def test_the_routes_answer_503_with_no_corpus_configured(app_without_corpus):
    """`_reader` already answers this for the read routes; the write routes
    have to make the same check rather than failing further in."""
    client, project = app_without_corpus

    response = await client.post(
        f"/api/projects/{project}/sources", json={"source_id": "s1", "text": "hello"}
    )

    assert response.status_code == 503


async def test_upload_works_on_a_project_no_earlier_call_has_touched(app_and_client):
    """A second project, seeded by nothing.

    `CLAUDE.md` records the failure this guards: a request path that stopped
    opening the project answered 503 on the first call for a newly-touched
    project and succeeded on every one after, because some earlier test in the
    same process had already opened it. Every other test in this file arranges
    through the route under test and cannot see that.
    """
    _app, client = app_and_client
    await _new_project(client)  # the project every other assertion would run against
    untouched = await _new_project(client)

    response = await client.post(
        f"/api/projects/{untouched}/sources",
        json={"source_id": "s1", "text": "hello"},
    )

    assert response.status_code == 201
