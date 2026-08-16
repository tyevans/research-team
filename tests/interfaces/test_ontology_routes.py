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

FOUND = AIMessage(
    content=(
        '{"classes": [{"name": "Difficulty", "kind": "ordered_scale", '
        '"declared_count": 6, "evidence": {"start": 0, "end": 66}, '
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
    assert klass["evidence"] == {"sourceId": "songs", "start": 0, "end": 66}
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
