"""The two ontology routes, over an application the composition root built.

Composed rather than faked, for `test_ontology_wiring.py`'s reason: a build
that never constructs an `OntologyRunner` answers `GET .../ontology` with an
empty list and no error, and a fixture that hands the route a hand-built runner
cannot tell that build from a working one. Every assertion here is on the
payload's contents.
"""

import asyncio
from uuid import UUID, uuid4

import pytest
from httpx import ASGITransport, AsyncClient
from langchain_core.language_models.fake_chat_models import FakeMessagesListChatModel
from langchain_core.messages import AIMessage

from research_team.composition import build_application
from research_team.interfaces.web import create_app

SONGS = (
    "There are six difficulties available in the game: EASY, NORMAL, HARD, "
    "EXPERT, MASTER, and APPEND."
)

#: The sentence the model is made to quote as evidence. Named rather than
#: written twice, so the payload assertion below is against the range this
#: quote really occupies rather than a number copied by hand.
QUOTE = "There are six difficulties available in the game"

FOUND = AIMessage(
    content=(
        '{"classes": [{"name": "Difficulty", "kind": "ordered_scale", '
        '"declared_count": 6, "evidence": "' + QUOTE + '", '
        '"members": [{"name": "EASY", "ordinal": 0}, {"name": "MASTER", "ordinal": 4}, '
        '{"name": "LEGEND", "ordinal": 6}]}]}'
    )
)


def _api(application):
    return create_app(
        application.service,
        application.feed,
        application.turns,
        corpus=application.corpus,
        # Required alongside `corpus`: `_reader` refuses with 503 unless both
        # are present, because `ProjectCorpusReader` needs a blob store for
        # `read_media`. Omitting it turns the 404 path below into a 503.
        blob_store=application.blob_store,
        graphs=application.graphs,
        editor=application.editor,
        # The composition root's own, which is the point: hand-built ones here
        # would test this file's wiring rather than the one `web.py` uses.
        ontology=application.ontology,
        ontology_discoverers=application.ontology_discoverers,
    )


@pytest.fixture
async def composed(db_path):
    application = build_application(
        model=FakeMessagesListChatModel(responses=[FOUND] * 4), db_path=db_path
    )
    await application.start()
    # `try`/`finally` around everything after `start`, not just around the
    # yield: a failure during setup would otherwise skip `close()` and leave
    # this application's projections and background tasks running, which does
    # not fail the test -- it hangs the whole session at exit, with no output
    # naming the fixture that did it. Learned the hard way on this file.
    try:
        transport = ASGITransport(app=_api(application))
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            created = await client.post("/api/projects", json={"name": f"ont-{uuid4()}"})
            assert created.status_code == 200
            # `UUID`, not the raw string the JSON carries: `editor.store` builds
            # a `StreamId` from it and raises on a `str`, and that raise lands
            # in fixture setup where it is at its least legible.
            project_id = UUID(created.json()["id"])
            await application.editor.store(project_id, "songs", SONGS)
            for _ in range(500):
                if await application.corpus.get(project_id, "songs") is not None:
                    break
                await asyncio.sleep(0.01)
            else:
                raise AssertionError("the songs document never reached the corpus table")
            yield application, client, project_id
    finally:
        await application.close()


async def test_a_pass_reports_what_it_found(composed):
    _application, client, project_id = composed

    response = await client.post(f"/api/projects/{project_id}/sources/songs/ontology")

    assert response.status_code == 200
    assert response.json() == {"sourceId": "songs", "found": 1}


async def test_the_read_carries_everything_needed_to_judge_a_class(composed):
    """The payload's contents, not its status. A build with the runner unwired
    answers this route 200 with an empty list, so a status assertion passes
    against exactly the bug this feature is most likely to ship with.

    Each field is here because the class is unjudgeable without it: evidence to
    open the source at, the two counts that form the checksum, and the
    rejection that explains why they disagree.
    """
    application, client, project_id = composed
    await client.post(f"/api/projects/{project_id}/sources/songs/ontology")
    await application.ontology.caught_up()

    body = (await client.get(f"/api/projects/{project_id}/ontology")).json()

    (klass,) = body["classes"]
    assert klass["name"] == "Difficulty"
    assert klass["kind"] == "ordered_scale"
    # Two found against six stated: the checksum disagreeing, on purpose.
    assert (klass["declaredCount"], klass["memberCount"]) == (6, 2)
    # The offsets are the range the quoted sentence occupies, located by
    # `_span` rather than estimated by the model.
    assert klass["evidence"] == {"sourceId": "songs", "start": 0, "end": len(QUOTE)}
    assert [member["name"] for member in klass["members"]] == ["EASY", "MASTER"]
    # And the reason the two numbers disagree, which is what makes the gap
    # legible rather than merely visible.
    assert klass["rejectedMembers"] == [
        {"name": "LEGEND", "reason": "not found in the document, verbatim"}
    ]


async def test_a_project_nobody_has_passed_over_has_no_classes(composed):
    """Passes with the feature reverted -- it asserts an absence. Kept because
    it is what makes the empty state a real answer rather than an error, and
    because it is the answer a misconfigured build would also give, which is
    why the 503 test below exists beside it."""
    _application, client, project_id = composed

    body = (await client.get(f"/api/projects/{project_id}/ontology")).json()

    assert body == {"classes": []}


async def test_an_unknown_source_is_404(composed):
    _application, client, project_id = composed

    response = await client.post(f"/api/projects/{project_id}/sources/nope/ontology")

    assert response.status_code == 404


async def test_an_unwired_build_is_503_rather_than_an_empty_200(composed):
    """The distinction the empty-project test above cannot make. An empty list
    is the right answer for a project nobody has run a pass on; a build with no
    ontology service answering the same thing would be indistinguishable from
    a working one with nothing to show."""
    application, _, project_id = composed
    unwired = create_app(
        application.service,
        application.feed,
        application.turns,
        corpus=application.corpus,
        graphs=application.graphs,
    )
    transport = ASGITransport(app=unwired)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        assert (await client.get(f"/api/projects/{project_id}/ontology")).status_code == 503
        posted = await client.post(f"/api/projects/{project_id}/sources/songs/ontology")
        assert posted.status_code == 503


# --- the lenient lever --------------------------------------------------------

WRAPPED = (
    "The agent answering that page may write an mcq, cloze, or flashcard component\n"
    "into its reply instead of just prose."
)
"""Hard-wrapped, which is the whole fixture: measured 2026-08-24 on the owner's
corpus, this exact sentence cost the only real class the pass had ever found,
because the model quotes it the way a reader reads it."""

WRAPPED_QUOTE = (
    "The agent answering that page may write an mcq, cloze, or flashcard component "
    "into its reply instead of just prose"
)
"""The same sentence with the newline flattened to a space -- not in the
document, and not a fabrication either."""

WRAPPED_FOUND = AIMessage(
    content=(
        '{"classes": [{"name": "interactive components", "kind": "unordered_set", '
        '"evidence": "' + WRAPPED_QUOTE + '", '
        '"members": [{"name": "mcq"}, {"name": "cloze"}, {"name": "flashcard"}]}]}'
    )
)


@pytest.fixture
async def wrapped(db_path):
    """`composed`, over a hard-wrapped document and a model that quotes it flat.

    A second fixture rather than a parameter on the first, because the model's
    reply has to quote *this* document and `FakeMessagesListChatModel` is
    handed its replies at construction.
    """
    application = build_application(
        model=FakeMessagesListChatModel(responses=[WRAPPED_FOUND] * 4), db_path=db_path
    )
    await application.start()
    try:
        transport = ASGITransport(app=_api(application))
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            created = await client.post("/api/projects", json={"name": f"ont-{uuid4()}"})
            assert created.status_code == 200
            project_id = UUID(created.json()["id"])
            await application.editor.store(project_id, "readme", WRAPPED)
            for _ in range(500):
                if await application.corpus.get(project_id, "readme") is not None:
                    break
                await asyncio.sleep(0.01)
            else:
                raise AssertionError("the readme document never reached the corpus table")
            yield application, client, project_id
    finally:
        await application.close()


async def test_the_default_pass_refuses_a_class_whose_quote_the_document_wraps(wrapped):
    """The route's default is strict, and this is what that costs.

    Asserted at this layer and not only in `test_ontology_discovery.py` because
    the default lives in the route signature, where a `strict: bool = False`
    typo would be invisible to every application-layer test.
    """
    _application, client, project_id = wrapped

    response = await client.post(f"/api/projects/{project_id}/sources/readme/ontology")

    assert response.json() == {"sourceId": "readme", "found": 0}


async def test_strict_false_keeps_it_and_says_the_span_is_a_member(wrapped):
    """The lever, end to end: query parameter, service, verifier, event,
    projection, payload. Every one of those has to carry `evidence_quoted` for
    this to pass, and the projection is the half most likely to drop it --
    a column that is never written defaults to `True` and looks like a class
    whose sentence was located.

    Proved red against the column: with `evidence_quoted` removed from the
    `OntologyClassRow(...)` construction, `found` is still 1 and only the last
    assertion fails.
    """
    application, client, project_id = wrapped

    response = await client.post(
        f"/api/projects/{project_id}/sources/readme/ontology?strict=false"
    )
    assert response.json() == {"sourceId": "readme", "found": 1}
    await application.ontology.caught_up()

    (klass,) = (await client.get(f"/api/projects/{project_id}/ontology")).json()["classes"]
    assert klass["name"] == "interactive components"
    # The first member's own occurrence, which is text the document contains.
    start, end = klass["evidence"]["start"], klass["evidence"]["end"]
    assert WRAPPED[start:end] == "mcq"
    assert klass["evidenceQuoted"] is False


async def test_a_located_quote_is_reported_as_quoted(composed):
    """The other value of the flag, on the ordinary document. Without this the
    payload could be hard-coded `False` and the test above would still pass."""
    application, client, project_id = composed
    await client.post(f"/api/projects/{project_id}/sources/songs/ontology")
    await application.ontology.caught_up()

    (klass,) = (await client.get(f"/api/projects/{project_id}/ontology")).json()["classes"]

    assert klass["evidenceQuoted"] is True
