"""Discovered classes reaching the graph route, over a composed application.

`ProjectGraphReader`'s `ontology` collaborator is optional, so every
construction site that predates the ontology layer keeps working. That default
has a real cost and this file is the whole of the mitigation: a site that
forgets to pass one draws no classes and reports no error -- a graph with no
class nodes is exactly what a project nobody has run a pass on correctly looks
like, so nothing downstream can tell the two apart.

Only asking a composed application for a class node closes that. The unit tests
in `tests/application/test_graph_read.py` construct the reader themselves and
therefore cannot: they prove the join is right, not that anything calls it.
"""

import asyncio
from datetime import UTC, datetime
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

#: Discovery replies only. These tests seed the graph directly rather than
#: driving extraction (see `_entities`), so the *only* model call made here is
#: the discovery one -- a list that also held an extraction reply would hand
#: that reply to `parse_ontology`, which cannot read it, and the pass would
#: silently record nothing. Cost half an hour; the symptom is a graph with no
#: class node, which is also what a broken join looks like.
#:
#: The member names are spelled exactly as the document spells them, because
#: resolution is by normalised name and a paraphrase would make every
#: membership unresolvable for the wrong reason.
DISCOVERED = AIMessage(
    content=(
        '{"classes": [{"name": "Difficulty", "kind": "ordered_scale", '
        '"declared_count": 6, "evidence": {"start": 0, "end": 66}, '
        '"members": [{"name": "EASY", "ordinal": 0}, {"name": "MASTER", "ordinal": 4}]}]}'
    )
)


@pytest.fixture
async def composed(db_path):
    application = build_application(
        model=FakeMessagesListChatModel(responses=[DISCOVERED] * 4),
        db_path=db_path,
    )
    await application.start()
    try:
        api = create_app(
            application.service,
            application.feed,
            application.turns,
            corpus=application.corpus,
            blob_store=application.blob_store,
            graphs=application.graphs,
            editor=application.editor,
            ontology=application.ontology,
            ontology_discoverers=application.ontology_discoverers,
        )
        transport = ASGITransport(app=api)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            created = await client.post("/api/projects", json={"name": f"og-{uuid4()}"})
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


async def _entities(application, project_id, *names):
    """Put entities in the graph directly, the shortcut the definition wiring
    test takes: extraction is not what is under test here, and driving it would
    put a second set of model replies between this test and the class node."""
    from redstring import Entity, ExtractionMethod, Provenance

    store = await application.graphs.open(project_id)
    await store.upsert_entities(
        [
            Entity(
                id=uuid4(),
                tenant_id=project_id,
                name=name,
                normalized_name=name.lower(),
                entity_type="category",
                provenance=Provenance(
                    observed_at=datetime(2026, 1, 1, tzinfo=UTC),
                    extraction_method=ExtractionMethod.LLM,
                    confidence=0.9,
                    source_id="songs",
                ),
            )
            for name in names
        ]
    )


async def test_a_composed_graph_route_draws_a_discovered_class(composed):
    """The claim the whole ontology layer can ship without.

    Reverting `ontology=ontology` at either `ProjectGraphReader` construction
    site leaves every unit test in `test_graph_read.py` green and turns this
    into a graph with no class node -- which is indistinguishable, from
    outside, from a project nobody has run a pass on.
    """
    application, client, project_id = composed
    await _entities(application, project_id, "EASY", "MASTER")
    await client.post(f"/api/projects/{project_id}/sources/songs/ontology")
    await application.ontology.caught_up()

    body = (await client.get(f"/api/projects/{project_id}/graph")).json()

    classes = [entity for entity in body["entities"] if entity["entity_type"] == "class"]
    assert len(classes) == 1
    assert classes[0]["name"] == "Difficulty"
    assert classes[0]["inferred"] is True


async def test_the_members_are_wired_to_the_class_and_marked_derived(composed):
    application, client, project_id = composed
    await _entities(application, project_id, "EASY", "MASTER")
    await client.post(f"/api/projects/{project_id}/sources/songs/ontology")
    await application.ontology.caught_up()

    body = (await client.get(f"/api/projects/{project_id}/graph")).json()

    edges = [
        edge for edge in body["relationships"] if edge["relationship_type"] == "instance_of"
    ]
    assert len(edges) == 2
    assert all(edge["inferred"] for edge in edges)
    # The derivation names the document and the offsets, so a reader can open
    # the sentence rather than take the edge on trust.
    assert all("songs" in edge["derivation"] for edge in edges)


async def test_a_project_with_no_pass_has_no_class_nodes(composed):
    """The other half of the pair above: this is what an unwired build also
    returns, which is precisely why the first test cannot be a status
    assertion."""
    application, client, project_id = composed
    await _entities(application, project_id, "EASY", "MASTER")

    body = (await client.get(f"/api/projects/{project_id}/graph")).json()

    assert [e for e in body["entities"] if e["entity_type"] == "class"] == []
