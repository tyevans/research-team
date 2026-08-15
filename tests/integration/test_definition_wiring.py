"""The definition endpoint, over an application the composition root built.

Every other test of this feature builds its collaborators by hand: the
application-layer suite fakes all four ports, and `test_web.py` fakes three
and wires the fourth into `create_app` itself. Both were green while the
endpoint answered 503 in the only build that ships, because nothing in
`composition.py` constructed a `DefinitionService` at all. That is the
failure this file exists to catch, and it can only be caught by asking a
composed application.

Two claims, and they are the two ways the wiring can be wrong:

1. A composed app answers a definition. Reverting the `definition_readers`
   wiring turns `test_a_composed_app_defines_an_entity` into a 503.
2. The service reads the table the invalidation projection writes. A second
   `EntityDefinitionStore` built for the route would pass claim 1 perfectly
   and fail `test_the_route_sees_what_the_invalidation_projection_marked`,
   which stales a row through the projection and asks the route what it sees.

**What is still faked, stated rather than implied.** The model is a
`FakeMessagesListChatModel` -- no live call anywhere here -- so what is
proven about `ChatModelDefinitionText` is that composition hands it the
model and that its reply reaches `_parse`, not anything about a real
endpoint's output. And claim 2 drives `EntityDefinitionProjection` directly
with a handmade `DocumentExtracted` rather than waiting for one to arrive
through the subscription: the event-to-`mark_stale` mapping is already
covered by `tests/infrastructure/test_entity_definition_invalidation.py`,
and what is under test here is which *table* the mark lands in.
"""

import json
from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest
from httpx import ASGITransport, AsyncClient
from langchain_core.language_models.fake_chat_models import FakeMessagesListChatModel
from langchain_core.messages import AIMessage
from redstring import DocumentExtracted, Entity, ExtractionMethod, Provenance
from redstring.domain.chunk import StoredChunk

from research_team.composition import build_application
from research_team.infrastructure.persistence.read_models import (
    EntityDefinitionProjection,
    EntityDefinitionStore,
)
from research_team.interfaces.web import create_app

PASSAGE = "Acme Corp builds rockets in Texas."

REPLY = json.dumps(
    {
        "text": "Acme Corp builds rockets.",
        "citations": [{"source_id": "doc-1", "start": 0, "end": len(PASSAGE)}],
    }
)


def _model() -> FakeMessagesListChatModel:
    """A chat model that always answers with `REPLY`.

    `FakeMessagesListChatModel` cycles its list, so one entry answers every
    call -- including the regeneration in the staleness test. Passed as
    `build_application(model=...)`, which is also what becomes the extraction
    model (`_extraction_model`); that shared instance is exactly the wiring
    under test, not an accident of the fixture.
    """
    return FakeMessagesListChatModel(responses=[AIMessage(content=REPLY)])


def _entity(entity_id: UUID, tenant_id: UUID) -> Entity:
    return Entity(
        id=entity_id,
        tenant_id=tenant_id,
        name="Acme Corp",
        normalized_name="acme corp",
        entity_type="organization",
        provenance=Provenance(
            observed_at=datetime(2026, 1, 1, tzinfo=UTC),
            extraction_method=ExtractionMethod.LLM,
            confidence=0.9,
            source_id="doc-1",
        ),
    )


@pytest.fixture
async def composed(db_path):
    """A started application, its app, a project, and an entity to define.

    The graph and chunk stores are seeded directly, the shortcut
    `_project_with_a_usage` in `test_web.py` takes: extraction is not what is
    under test, and driving it would put a second set of model replies
    between this test and the definition.
    """
    application = build_application(model=_model(), db_path=db_path)
    await application.start()
    api = create_app(
        application.service,
        application.feed,
        application.turns,
        corpus=application.corpus,
        graphs=application.graphs,
        # The composition root's factory, which is the whole point: passing a
        # hand-built service here would test this file's wiring, not the one
        # `web.py` uses.
        definitions=application.definition_readers,
    )
    transport = ASGITransport(app=api)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        created = await client.post("/api/projects", json={"name": f"defs-{uuid4()}"})
        assert created.status_code == 200
        project_id = UUID(created.json()["id"])

        store = await application.graphs.open(project_id)
        entity_id = uuid4()
        await store.upsert_entities([_entity(entity_id, project_id)])
        await application.graphs.chunks(project_id).upsert_many(
            [
                StoredChunk(
                    id="chunk-1",
                    tenant_id=project_id,
                    source_id="doc-1",
                    text=PASSAGE,
                    chunk_index=0,
                    start_char=0,
                    end_char=len(PASSAGE),
                )
            ]
        )
        yield application, client, project_id, entity_id
    await application.close()


async def test_a_composed_app_defines_an_entity(composed):
    """The endpoint answers rather than 503ing -- the whole of Task 10b.

    Fails with a 503 if `web.py`'s `definitions=` or `Application.
    definition_readers` is removed, which is the state this repository was in
    while `test_web.py` passed.
    """
    _application, client, project_id, entity_id = composed

    response = await client.get(
        f"/api/projects/{project_id}/graph/entities/{entity_id}/definition"
    )

    assert response.status_code == 200
    body = response.json()
    assert body["text"] == "Acme Corp builds rockets."
    assert body["citations"] == [{"source_id": "doc-1", "start": 0, "end": len(PASSAGE)}]
    assert body["stale"] is False


async def test_the_definition_lands_in_the_runners_own_table(composed):
    """What the route cached is readable through `EntityDefinitionRunner`.

    The read half of the shared-table claim, and the cheap half: a route
    wired to a second `EntityDefinitionStore` over the same file would still
    pass this, because SQLite would show it the same row. The next test is
    the one that distinguishes them.
    """
    application, client, project_id, entity_id = composed
    await client.get(f"/api/projects/{project_id}/graph/entities/{entity_id}/definition")

    row = await application.definitions.get(project_id, entity_id)

    assert row is not None
    assert row.text == "Acme Corp builds rockets."
    assert row.stale is False


async def test_the_route_sees_what_the_invalidation_projection_marked(composed, db_path):
    """A row the projection stales is a row the route regenerates.

    `stale` is the one field written by neither the service nor the route --
    only the invalidation projection sets it -- so it is the only field that
    can prove the two halves meet in one table rather than in two that agree
    by accident. The projection here runs over its own connection to the same
    database, which is how `EntityDefinitionRunner` would see it arrive.

    The assertion is `stale is False` *after* a stale mark, not `True`:
    `DefinitionService.define` regenerates a stale row and answers the fresh
    one. A route reading a table nothing had marked would answer the cached
    row without regenerating -- indistinguishable in the body, which is why
    `generated_at` is compared too.
    """
    application, client, project_id, entity_id = composed
    first = await client.get(
        f"/api/projects/{project_id}/graph/entities/{entity_id}/definition"
    )
    assert first.status_code == 200

    store = await EntityDefinitionStore.open(db_path)
    try:
        await EntityDefinitionProjection(store)._on_extracted(
            DocumentExtracted(
                aggregate_id=uuid4(),
                tenant_id=project_id,
                source_id="doc-1",
                entities=[_entity(entity_id, project_id)],
                relationships=[],
                model_version="test",
            )
        )
        assert (await application.definitions.get(project_id, entity_id)).stale is True
    finally:
        await store.close()

    second = await client.get(
        f"/api/projects/{project_id}/graph/entities/{entity_id}/definition"
    )

    assert second.status_code == 200
    assert second.json()["stale"] is False
    assert second.json()["generated_at"] != first.json()["generated_at"]
