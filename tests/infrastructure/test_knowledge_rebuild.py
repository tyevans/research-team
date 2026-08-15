import inspect
from uuid import uuid4

import pytest
from eventsource import ReplayFailedError, ReplayFailure, replay
from eventsource.adapters.sqlite import SQLiteEventStore
from redstring import (
    GraphProjection,
    InMemoryChunkStore,
    InMemoryGraphStore,
    SourceDocument,
    index_documents,
    rank_chunks,
    tokenize,
)

from research_team.application.knowledge import KnowledgeError, SourceRef
from research_team.infrastructure.knowledge import rebuild
from research_team.infrastructure.knowledge.rebuild import rebuild_graph

# `build_adapter` is a pytest fixture defined in test_redstring_adapter; importing
# it into this module's namespace is how pytest shares fixtures across files.


@pytest.mark.asyncio
async def test_a_rebuilt_graph_matches_the_one_maintained_by_ingest(
    tmp_path,
    build_adapter,
):
    """The store is a projection. Rebuilding it must not change what it holds."""
    project_id = uuid4()
    adapter, event_store, _ = build_adapter(tmp_path, project_id)
    await adapter.ingest(
        SourceRef(source_id="notes", text="Ada Lovelace worked with Charles Babbage.")
    )

    rebuilt = InMemoryGraphStore()
    applied = await rebuild_graph(rebuilt, feed=event_store, project_id=project_id)

    live_names = sorted(e.name for e in await adapter._store.find_entities(project_id))
    rebuilt_names = sorted(e.name for e in await rebuilt.find_entities(project_id))
    assert rebuilt_names == live_names
    assert rebuilt_names, "the fixture should have produced entities"
    assert applied > 0


@pytest.mark.asyncio
async def test_rebuilding_an_empty_project_yields_an_empty_graph(tmp_path):
    project_id = uuid4()
    event_store = SQLiteEventStore(str(tmp_path / "sessions.db"))
    try:
        store = InMemoryGraphStore()

        applied = await rebuild_graph(store, feed=event_store, project_id=project_id)

        assert await store.find_entities(project_id) == []
        assert applied == 0
    finally:
        await event_store.close()


@pytest.mark.asyncio
async def test_rebuilding_never_calls_the_model(tmp_path, build_adapter):
    """Replay purity: extraction is recorded, never recomputed.

    `rebuild_graph` accepts no provider, and neither `GraphProjection` nor
    `eventsource.replay` -- the only two library calls this module makes --
    accept one either, so there is
    genuinely nowhere in this path a provider could be reached. A
    raising-provider stub can't be "wired in" because there is no seam to wire
    it into; the strongest test available is pinning that absence
    at every point the call could plausibly have taken a provider, not just on
    `rebuild_graph` itself.
    """
    assert "provider" not in inspect.signature(rebuild.rebuild_graph).parameters
    assert "provider" not in inspect.signature(GraphProjection.__init__).parameters
    assert "provider" not in inspect.signature(replay).parameters

    project_id = uuid4()
    adapter, event_store, _ = build_adapter(tmp_path, project_id)
    await adapter.ingest(SourceRef(source_id="notes", text="Ada Lovelace."))

    # Rebuilds fine with nothing resembling a provider anywhere in scope.
    applied = await rebuild_graph(
        InMemoryGraphStore(), feed=event_store, project_id=project_id
    )
    assert applied > 0


@pytest.mark.asyncio
async def test_a_failed_replay_is_refused_rather_than_served_partial(tmp_path, monkeypatch):
    """A strict replay's refusal must reach the caller as `KnowledgeError`.

    The refusal now names the offending event. That is the half of R4 we could
    never implement ourselves: the old count told an operator that three events
    failed and gave them no way to find one. So the assertion is on the event
    type and the underlying error reaching the message, not merely on raising.
    """
    failure = ReplayFailure(
        position=None,
        event_id=uuid4(),
        event_type="DocumentExtracted",
        projection="GraphProjection",
        error=ValueError("poison"),
    )

    async def _fake_replay(feed, projections, **kwargs):
        assert kwargs["strict"] is True, "a partial graph must never be served"
        raise ReplayFailedError(failure=failure)

    monkeypatch.setattr(rebuild, "replay", _fake_replay)

    project_id = uuid4()
    event_store = SQLiteEventStore(str(tmp_path / "sessions.db"))
    try:
        with pytest.raises(KnowledgeError) as caught:
            await rebuild_graph(InMemoryGraphStore(), feed=event_store, project_id=project_id)
    finally:
        await event_store.close()

    assert "DocumentExtracted" in str(caught.value)
    assert "poison" in str(caught.value)
    assert isinstance(caught.value.__cause__, ReplayFailedError)


@pytest.mark.asyncio
async def test_a_project_opened_from_a_log_with_chunkings_comes_up_with_chunks(tmp_path):
    """The assertion is retrieval, not project open.

    An assertion that the project merely opened would pass with
    `ChunkProjection` removed from the sequence -- `eventsource.replay`
    applies an event no projection handles rather than rejecting it -- so it
    would be reassurance rather than a test. Proven red the right way: with
    `projections.append(ChunkProjection(chunks))` commented out in
    `rebuild_graph`, this failed on the `assert [ranked...]` line (empty
    corpus) with `applied > 0` still passing, then restored to green.
    """
    project_id = uuid4()
    event_store = SQLiteEventStore(str(tmp_path / "sessions.db"))
    try:
        # A throwaway store to drive `index_documents`, which appends
        # `DocumentChunked` to the real feed -- the graph's `event_store`, so
        # the chunking lands in the same log a rebuild reads from. What ends
        # up retrievable is the *store rebuild_graph folds into*, not this
        # one.
        await index_documents(
            [SourceDocument(id="doc-1", text="Acme Corp builds rockets in Texas.")],
            store=InMemoryChunkStore(dimension=8),
            tenant_id=project_id,
            event_store=event_store,
        )

        store = InMemoryChunkStore(dimension=8)
        applied = await rebuild_graph(
            InMemoryGraphStore(), feed=event_store, project_id=project_id, chunks=store
        )

        terms = tokenize("Acme")
        candidates = await store.lexical_candidates(terms, project_id, 10)
        ranked = rank_chunks(terms, candidates, 10)

        assert applied > 0
        assert [r.chunk.text for r in ranked], "chunk corpus came up empty after replay"
    finally:
        await event_store.close()
