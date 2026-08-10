"""The pgvector store this project constructs, against a real Postgres.

Deselected by default. Start the server and run it deliberately:

    docker compose -f docker-compose.test.yml up -d postgres
    uv run pytest -m integration tests/integration/test_pgvector_store.py

What this pins is our wiring, not redstring's adapter -- redstring's own suite
covers the SQL. The wiring is where this project's bugs were, and both of them
were invisible without a server: `build_vector_store` was synchronous while
`PgVectorStore.connect` is a coroutine, so it returned an un-awaited coroutine
in place of a store; and nothing called `ensure_schema`, so even once awaited
the store addressed a table that did not exist. Every assertion here is
therefore about something that only fails on a round trip.

`test_the_configured_store_survives_a_restart` is the one worth reading. It is
the difference between the two vector backends and the reason this one exists:
`AGENT_VECTOR_STORE=memory` loses every vector when the process ends and cannot
get them back, because `EntitiesEmbedded` is never appended to this project's
log and so there is nothing for a replay to fold. pgvector is currently the
only way this project holds an embedding across a restart.
"""

import os
from uuid import uuid4

import pytest
from redstring import SourceDocument, build_graph

from research_team.infrastructure.knowledge.stores import build_vector_store
from tests.conftest import fake_provider

pytestmark = pytest.mark.integration

#: Small on purpose. The width has to match between provider and store or
#: redstring refuses to wire them, and nothing here is measuring similarity --
#: so the cheapest width that is not degenerate is the right one.
DIMENSION = 8

DEFAULT_DSN = "postgresql://redstring:redstring@localhost:55432/redstring"


@pytest.fixture
def pgvector_env(monkeypatch):
    monkeypatch.setenv("AGENT_PGVECTOR_DSN", os.getenv("AGENT_PGVECTOR_DSN", DEFAULT_DSN))


@pytest.fixture
async def store(pgvector_env):
    """A configured `PgVectorStore` with its schema applied, cleaned up after.

    `ensure_schema` is called here for the same reason `ProjectGraphs` calls it
    at project open: without it the table does not exist and the first
    `upsert_many` raises. That it is a fixture rather than an assertion is
    deliberate -- the test that this project *does* call it lives in
    `tests/application/test_project_graphs.py`, where it needs no server.
    """
    built = await build_vector_store("pgvector", dimension=DIMENSION)
    assert built is not None, "'pgvector' must not resolve to the feature being off"
    await built.ensure_schema()
    yield built
    await built.close()


async def test_the_configured_store_round_trips_against_a_real_postgres(store):
    """A vector written through this project's builder can be read back.

    Fails before this PR at `build_vector_store`, not here: `asyncpg` was not
    installed, because `redstring[pgvector]` was assumed to resolve
    transitively and did not. The import in `build_vector_store` is lazy, so
    that was an `ImportError` on the first pgvector ingest rather than at
    startup.
    """
    from redstring import VectorRecord

    tenant_id = uuid4()
    entity_id = uuid4()
    try:
        await store.upsert_many(
            [
                VectorRecord(
                    entity_id=entity_id,
                    tenant_id=tenant_id,
                    vector=[0.1] * DIMENSION,
                )
            ]
        )

        found = await store.get(entity_id, tenant_id)

        assert found is not None
        assert found.entity_id == entity_id
    finally:
        # Leave no rows behind: the next run shares this server.
        await store.delete_by_tenant(tenant_id)


async def test_a_real_ingest_lands_entities_in_the_configured_store(store):
    """The path an ingest actually takes, end to end against the server.

    Not `upsert_many` directly: `build_graph` is what production calls, and it
    reaches the store through `VectorProjection` after extracting. A wiring gap
    between the two is invisible to a test that writes a record by hand.
    """
    from redstring import FakeEmbeddingProvider

    tenant_id = uuid4()
    try:
        report = await build_graph(
            SourceDocument(id="notes", text="Ada Lovelace worked with Charles Babbage."),
            provider=fake_provider(),
            store=_throwaway_graph(),
            tenant_id=tenant_id,
            domain="encyclopedia_wiki",
            embedding_provider=FakeEmbeddingProvider(dimension=DIMENSION),
            vector_store=store,
        )

        assert report.embedded > 0, "the ingest should have written vectors"
        assert report.event is not None
        for entity in report.event.entities:
            assert await store.get(entity.id, tenant_id) is not None
    finally:
        await store.delete_by_tenant(tenant_id)


async def test_the_configured_store_survives_a_restart(pgvector_env):
    """Vectors written by one store are found by a second built from scratch.

    This is the claim the backend is for, and the one `memory` cannot make.
    A second `build_vector_store` stands in for a restarted process: it shares
    no state with the first, so anything it finds came off the disk.
    """
    from redstring import VectorRecord

    tenant_id = uuid4()
    entity_id = uuid4()
    first = await build_vector_store("pgvector", dimension=DIMENSION)
    assert first is not None
    await first.ensure_schema()
    try:
        await first.upsert_many(
            [VectorRecord(entity_id=entity_id, tenant_id=tenant_id, vector=[0.2] * DIMENSION)]
        )
    finally:
        await first.close()

    second = await build_vector_store("pgvector", dimension=DIMENSION)
    assert second is not None
    await second.ensure_schema()
    try:
        assert await second.get(entity_id, tenant_id) is not None
    finally:
        await second.delete_by_tenant(tenant_id)
        await second.close()


async def test_a_dsn_pointing_nowhere_is_refused_at_the_builder(monkeypatch):
    """An unreachable server fails where the store is built, not later.

    `PgVectorStore.connect` awaits `asyncpg.create_pool`, which opens
    connections before it returns -- so unlike `Neo4jGraphStore.connect`, which
    builds a lazy driver, this one does reach the server. Recorded because
    `stores.py` asserted the opposite until this PR, and because it is what
    makes a bad `AGENT_PGVECTOR_DSN` a startup failure rather than a failure
    partway through the first ingest.
    """
    monkeypatch.setenv("AGENT_PGVECTOR_DSN", "postgresql://nobody:nobody@localhost:1/nothing")

    with pytest.raises(Exception):  # noqa: B017 -- asyncpg's type is not the point
        await build_vector_store("pgvector", dimension=DIMENSION)


def _throwaway_graph():
    """An in-memory graph, because this module is about the vector store.

    `build_graph` requires one and writes entities to it; which store that is
    has no bearing on whether the vectors land in Postgres.
    """
    from redstring import InMemoryGraphStore

    return InMemoryGraphStore()
