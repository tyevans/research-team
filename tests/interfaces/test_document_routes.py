"""The four write routes over a project's corpus.

Built through the real `CorpusEditor` and a real `Corpus` aggregate, over a
started application, rather than through doubles like
`test_extraction_routes.py`: the interesting behaviour here is `CorpusEditor`'s
own -- the existence check, the aggregate's refusals, the fold that turns a
restore into a fresh record -- and stubbing it out would leave these tests
asserting that the routes forward calls correctly, which is a smaller and less
useful claim.
"""

from urllib.parse import quote
from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient

from research_team.application.knowledge import MAX_DOCUMENT_CHARS, source_id_for_url
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
        blob_store=application.blob_store,
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


async def test_a_patch_over_the_length_cap_is_400_not_500(app_and_client):
    """`_store`'s length cap is the only guard `revise` has -- `decide` has
    no opinion on document size -- and `revise_source` used to catch only
    `UnknownDocument`, so this was an unhandled `KnowledgeError` and a 500
    rather than the 400 `upload_source` already answers for the same error.
    """
    _app, client = app_and_client
    project = await _new_project(client)
    await client.post(
        f"/api/projects/{project}/sources", json={"source_id": "s1", "text": "hello"}
    )

    response = await client.patch(
        f"/api/projects/{project}/sources/s1",
        json={"text": "x" * (MAX_DOCUMENT_CHARS + 1)},
    )

    assert response.status_code == 400


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


async def test_a_refusal_from_decide_answers_409_not_500_on_revise(
    app_and_client, monkeypatch
):
    """The second route with this shape of gap: `revise_source` mapped only
    `UnknownDocument` and `KnowledgeError`, not `CommandRejectedError`. Same
    provocation as the restore case above -- `Corpus.decide` patched to
    refuse unconditionally, since no live caller currently reaches a
    `CommandRejectedError` here. Red without the `except` arm: 500.
    """
    _app, client = app_and_client
    project = await _new_project(client)
    await client.post(
        f"/api/projects/{project}/sources", json={"source_id": "s1", "text": "hello"}
    )

    from research_team.domain.research.corpus import CommandRejectedError, Corpus

    def _refuse(command, state):
        raise CommandRejectedError("decide refused for this test")

    monkeypatch.setattr(Corpus, "decide", staticmethod(_refuse))

    response = await client.patch(f"/api/projects/{project}/sources/s1", json={"title": "x"})

    assert response.status_code == 409
    assert "decide refused for this test" in response.json()["detail"]


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


async def test_a_refusal_from_decide_answers_409_not_500_on_restore(
    app_and_client, monkeypatch
):
    """`restore_source` mapped only `UnknownDocument` and `NotDropped`,
    not `CommandRejectedError` -- which is what `Corpus.decide` raises for
    every refusal it makes. No reachable case survives today -- the
    derivedness guards that could have triggered this were already fixed --
    so this provokes one that isn't reachable through the HTTP surface:
    `Corpus.decide` is patched to refuse unconditionally, standing in for
    whatever future guard on `StoreSourceDocument`/`StoreDerivedText` would
    otherwise become a silent 500 here. Red without the `except` arm: 500.
    """
    _app, client = app_and_client
    project = await _new_project(client)
    await client.post(
        f"/api/projects/{project}/sources", json={"source_id": "s1", "text": "hello"}
    )
    dropped = await client.post(
        f"/api/projects/{project}/sources/s1/drop", json={"reason": "off topic"}
    )
    assert dropped.status_code == 200

    from research_team.domain.research.corpus import CommandRejectedError, Corpus

    def _refuse(command, state):
        raise CommandRejectedError("decide refused for this test")

    monkeypatch.setattr(Corpus, "decide", staticmethod(_refuse))

    response = await client.post(f"/api/projects/{project}/sources/s1/restore", json={})

    assert response.status_code == 409
    assert "decide refused for this test" in response.json()["detail"]


async def test_a_dropped_document_can_still_be_read(app_and_client):
    """The console lists dropped rows and lets you open one.

    Red before `read_source` passed `include_dropped=True`: the GET answered
    404 and the drawer someone had just dropped from rendered an error box,
    with the Restore button above text it could no longer show.
    """
    _app, client = app_and_client
    project = await _new_project(client)
    await client.post(
        f"/api/projects/{project}/sources", json={"source_id": "s1", "text": "hello"}
    )
    await client.post(f"/api/projects/{project}/sources/s1/drop", json={"reason": "off topic"})

    response = await client.get(f"/api/projects/{project}/sources/s1")

    assert response.status_code == 200
    assert response.json()["text"] == "hello"
    assert response.json()["dropped_reason"] == "off topic"


@pytest.mark.parametrize(
    "method,path,body",
    [
        ("post", "/sources", {"source_id": "s1", "text": "hello"}),
        ("patch", "/sources/s1", {"title": "x"}),
        ("post", "/sources/s1/drop", {"reason": "off topic"}),
        ("post", "/sources/s1/restore", {}),
    ],
)
async def test_the_routes_answer_503_with_no_corpus_configured(
    app_without_corpus, method, path, body
):
    """`_reader` already answers this for the read routes; the write routes
    have to make the same check rather than failing further in.

    All four rather than the create alone: they share one `_editor()`, so the
    risk of a divergence is low, but a route added later that forgets the call
    is exactly what a test named for "the routes" should catch.
    """
    client, project = app_without_corpus

    response = await getattr(client, method)(f"/api/projects/{project}{path}", json=body)

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


async def test_a_url_shaped_id_never_reaches_the_handler(app_and_client):
    """Why `source_id` is derived from a url rather than being one.

    This is the defect that started it: `{source_id}` is a single path segment,
    and the ASGI server percent-decodes the path before Starlette routes it, so
    a `%2F` the client correctly encoded arrives at the router as a real
    separator and no route matches. The document is present and readable by
    every other means; only the URL cannot name it.

    Asserts the *shape* of the 404 rather than just its number, because the two
    404s mean opposite things and only one of them is this bug: Starlette's
    unmatched-route body is a bare `{"detail": "Not Found"}`, while the
    handler's own says `no source ... in project ...`. A test that checked only
    the status code would still pass if the route matched and the lookup missed,
    which is a different failure with a different fix. The contrast is asserted
    in both directions below for exactly that reason.

    **Stores nothing, and that is not laziness.** An earlier version of this
    test uploaded the document first, to show the row was fine and the fault was
    routing. `decide` now refuses a `/` in a source_id, so that upload is a 400
    and the defect can no longer be reproduced through any writer -- which is
    the guard working. What survives is the router behaviour that motivated the
    guard, and it needs no stored document: the request never reaches the
    handler, so whether one exists cannot change the answer.
    """
    _app, client = app_and_client
    project = await _new_project(client)
    url_id = "https://en.wikipedia.org/wiki/Roman_monarchy"

    # The writer refuses it now -- the other half of the fix, pinned here
    # rather than only in the domain tests because this is the route a person
    # would actually reach it through.
    refused = await client.post(
        f"/api/projects/{project}/sources",
        json={"source_id": url_id, "text": "hello"},
    )
    assert refused.status_code == 400

    response = await client.get(f"/api/projects/{project}/sources/{quote(url_id, safe='')}")

    assert response.status_code == 404
    assert response.json() == {"detail": "Not Found"}

    # The contrast: an id with no separator reaches the handler, which answers
    # with its own 404 naming the source. Without this half, the assertion
    # above would pass against a build where *every* read 404'd.
    missing = await client.get(f"/api/projects/{project}/sources/no-such-source")
    assert missing.status_code == 404
    assert "no source" in missing.json()["detail"]


async def test_a_derived_id_survives_the_round_trip(app_and_client):
    """The other half, and the one that would have caught this.

    `source_id_for_url` is what `keep` and `remember_page` now store under, so
    the claim worth pinning is not that the helper avoids slashes (that is
    `tests/application/test_source_ids.py`) but that what it produces is
    actually fetchable through the route a browser uses. Fails if the helper
    ever admits a character the router treats as a separator.
    """
    _app, client = app_and_client
    project = await _new_project(client)
    source_id = source_id_for_url("https://en.wikipedia.org/wiki/Roman_monarchy")
    await client.post(
        f"/api/projects/{project}/sources",
        json={"source_id": source_id, "text": "hello"},
    )

    response = await client.get(f"/api/projects/{project}/sources/{quote(source_id, safe='')}")

    assert response.status_code == 200
    assert response.json()["source_id"] == source_id
