from datetime import UTC, datetime
from uuid import uuid4

import pytest
from eventsource import StreamId, collect
from eventsource.adapters.sqlite import SQLiteEventStore
from redstring import (
    FakeEmbeddingProvider,
    FakeLlmProvider,
    InMemoryChunkStore,
    InMemoryVectorStore,
    LlmProviderError,
    SlidingWindowChunker,
    document_stream,
    rank_chunks,
    tokenize,
)

from research_team.application.knowledge import KnowledgeError, SearchMode, SourceRef
from research_team.domain.judgements import EntityKey, HoldSame
from research_team.infrastructure.knowledge import redstring_adapter
from research_team.infrastructure.knowledge.redstring_adapter import RedstringKnowledge
from research_team.infrastructure.persistence.event_store import (
    build_corpus_repository,
    build_judgements_repository,
)
from tests.conftest import TWO_PEOPLE, fake_provider

#: A second document's worth of people, sharing nothing with `TWO_PEOPLE` --
#: not the names, and (since redstring 0.5.0 compares neighbours by name) not
#: the neighbourhood either.
_HOPPER = {
    "entities": [
        {"name": "Grace Hopper", "entity_type": "Person"},
        {"name": "Harvard Mark I", "entity_type": "Machine"},
    ],
    "relationships": [
        {
            "source_name": "Grace Hopper",
            "target_name": "Harvard Mark I",
            "relationship_type": "WORKED_ON",
        }
    ],
}


@pytest.mark.asyncio
async def test_ingest_reports_what_it_extracted(tmp_path, build_adapter):
    project_id = uuid4()
    adapter, _, _ = build_adapter(tmp_path, project_id)

    report = await adapter.ingest(
        SourceRef(source_id="notes", text="Ada Lovelace worked with Charles Babbage.")
    )

    assert report.source_id == "notes"
    assert report.entity_count >= 1
    assert report.domain == "encyclopedia_wiki"


@pytest.mark.asyncio
async def test_indexing_a_document_writes_retrievable_passages(tmp_path, build_adapter):
    """`index` runs with no `provider`/`embeddings` at all -- it must still work
    with the fixture's `fake_provider()` sitting unused, which is the point:
    nothing about indexing touches a model.
    """
    project_id = uuid4()
    chunk_store = InMemoryChunkStore(dimension=8)
    knowledge, _, _ = build_adapter(tmp_path, project_id, chunks=chunk_store)

    await knowledge.index(
        SourceRef(source_id="doc-1", text="Acme Corp builds rockets in Texas.")
    )

    terms = tokenize("Acme")
    candidates = await chunk_store.lexical_candidates(terms, project_id, 10)
    assert list(rank_chunks(terms, candidates, 10))


@pytest.mark.asyncio
async def test_indexing_the_same_document_twice_writes_nothing_the_second_time(
    tmp_path, build_adapter
):
    """`record_chunking` refuses a repeat under the same signature, so a
    re-index over an unchanged corpus is free rather than duplicating every
    passage. Without the shared event store (see `RedstringKnowledge.index`)
    it would not be -- the repeat is recognised from the recorded signature,
    not from the store's contents.

    **Counts the writes rather than the passages**, and the distinction is the
    whole test. An earlier version asserted `get_by_source` returned the same
    number of chunks both times; it passed with `event_store` deleted from the
    `index_documents` call, because `ChunkProjection` writes through
    `replace_source` and replacing a source with an identical re-chunking
    leaves the count untouched. That version could not observe the failure it
    was named for -- every passage rewritten while `documents_skipped` read 0.
    Proved red on 2026-08-14 by removing `event_store=self._event_store`: this
    version fails with 2 writes against the expected 1, the earlier one still
    passed.
    """
    project_id = uuid4()
    writes = []

    class CountingChunkStore(InMemoryChunkStore):
        """`replace_source` is the only method `ChunkProjection` calls (its own
        docstring says so: one of the port's nine), so counting it counts every
        write indexing can make."""

        async def replace_source(self, source_id, tenant_id, chunks):
            writes.append(source_id)
            return await super().replace_source(source_id, tenant_id, chunks)

    chunk_store = CountingChunkStore(dimension=8)
    knowledge, _, _ = build_adapter(tmp_path, project_id, chunks=chunk_store)
    source = SourceRef(source_id="doc-1", text="Acme Corp builds rockets in Texas.")

    await knowledge.index(source)
    await knowledge.index(source)

    assert writes == ["doc-1"]


@pytest.mark.asyncio
async def test_indexing_with_no_chunk_store_configured_is_a_no_op(tmp_path, build_adapter):
    """`chunks=None` is `AGENT_CHUNK_STORE=none`. Indexing must not raise over a
    feature that is off -- the same shape `ProjectGraphs.chunks` uses for
    "chunking is off" (see its docstring).
    """
    project_id = uuid4()
    knowledge, _, _ = build_adapter(tmp_path, project_id)

    await knowledge.index(
        SourceRef(source_id="doc-1", text="Acme Corp builds rockets in Texas.")
    )


@pytest.mark.asyncio
async def test_storing_a_document_indexes_it_without_extracting(tmp_path, build_adapter):
    """Indexing must not be conditional on extraction having run: `store_source`
    never extracts, and a document worth reading is worth finding passages in
    regardless. This is what makes `RedstringKnowledge._store_document` the
    right hook rather than `ingest` alone.
    """
    project_id = uuid4()
    chunk_store = InMemoryChunkStore(dimension=8)
    knowledge, _, _ = build_adapter(tmp_path, project_id, chunks=chunk_store)

    await knowledge.store_source(
        SourceRef(source_id="doc-1", text="Acme Corp builds rockets in Texas.")
    )

    terms = tokenize("Acme")
    candidates = await chunk_store.lexical_candidates(terms, project_id, 10)
    assert list(rank_chunks(terms, candidates, 10))


@pytest.mark.asyncio
async def test_ingest_appends_the_extraction_to_the_document_stream(tmp_path, build_adapter):
    """The event is the record; the graph is derived from it."""
    project_id = uuid4()
    adapter, store, _ = build_adapter(tmp_path, project_id)

    await adapter.ingest(
        SourceRef(source_id="notes", text="Ada Lovelace worked with Charles Babbage.")
    )

    stream = document_stream(tenant_id=project_id, source_id="notes")
    envelopes = await collect(store.read_stream(stream))
    assert len(envelopes) == 1
    assert type(envelopes[0].event).__name__ == "DocumentExtracted"


@pytest.mark.asyncio
async def test_a_blank_source_id_is_rejected(tmp_path, build_adapter):
    project_id = uuid4()
    adapter, _, _ = build_adapter(tmp_path, project_id)

    with pytest.raises(KnowledgeError):
        await adapter.ingest(SourceRef(source_id="   ", text="anything"))


@pytest.mark.asyncio
async def test_an_oversized_document_is_refused_before_extraction(tmp_path, build_adapter):
    from research_team.infrastructure.knowledge.redstring_adapter import (
        MAX_DOCUMENT_CHARS,
    )

    project_id = uuid4()
    adapter, store, _ = build_adapter(tmp_path, project_id)

    with pytest.raises(KnowledgeError, match="limit"):
        await adapter.ingest(SourceRef(source_id="huge", text="x" * (MAX_DOCUMENT_CHARS + 1)))

    stream = document_stream(tenant_id=project_id, source_id="huge")
    assert await collect(store.read_stream(stream)) == []


@pytest.mark.asyncio
async def test_reconsolidate_is_scoped_to_one_documents_entities(tmp_path, build_adapter):
    """`reconsolidate(source_id)` acts on exactly that document's entities.

    Asserted directly, by capturing what `_consolidate` is actually handed:
    `reconsolidate("a")` must pass the entity ids `entities_for("a")` reports
    and none of `entities_for("b")`'s. A `reconsolidate` that ignored
    `source_id` and always re-resolved the same set -- or read the wrong
    stream -- would fail the disjointness check below even though its return
    value (empty merges, zero failures) would look identical either way. That
    return value is otherwise uninformative here: re-resolving after an
    explicit merge is a genuine no-op, because `CandidateFinder._block` runs
    `resolve_entity_ids` over the whole block and drops every entity that is
    already an alias -- an absorbed entity cannot be merged again, so it is
    never proposed. That is redstring's own idempotence rather than anything
    this adapter adds, and it is why the no-op alone cannot prove `source_id`
    did any work.

    This docstring previously attributed the no-op to the merged entity's
    graph-similarity signal dropping to `0.0` and holding its score under
    redstring's threshold. That mechanism is real -- it is the bug
    `test_one_entity_named_the_same_in_two_documents_becomes_one_node` pins --
    but it is not what makes *this* case a no-op, and alias exclusion happens
    first regardless of any score.

    The provider is explicit rather than `fake_provider()` because of
    redstring 0.5.0. `fake_provider()` answers `TWO_PEOPLE` whatever it is
    asked, so both documents used to extract Ada and Babbage, and the test
    read as two documents about different things only in the prose it fed the
    fake. Under 0.4.0 that was harmless -- the cross-document pair scored
    0.7143 and was rejected -- but 0.5.0 compares neighbours by name, so the
    two Adas share the neighbour "charles babbage", score 1.0, and *auto-merge
    during the second ingest*. The fixture's own `merge_entities` then failed
    on an entity that was already an alias. The two documents now genuinely
    extract different people, which is what the assertions below have always
    claimed and what the prose already said.
    """
    project_id = uuid4()
    adapter, _, _ = build_adapter(
        tmp_path,
        project_id,
        provider=FakeLlmProvider(by_substring={"Grace Hopper": _HOPPER}, default=TWO_PEOPLE),
    )
    await adapter.ingest(
        SourceRef(source_id="a", text="Ada Lovelace worked with Charles Babbage.")
    )
    await adapter.ingest(
        SourceRef(source_id="b", text="Grace Hopper worked on the Harvard Mark I.")
    )

    a_entities = await adapter.entities_for("a")
    b_entities = await adapter.entities_for("b")
    assert len(a_entities) >= 2, "fixture needs two entities in document a"
    await adapter.merge_entities(
        canonical=a_entities[0].id, absorbed=[a_entities[1].id], reason="test fixture"
    )

    seen: list[set] = []
    original_consolidate = adapter._consolidate

    async def recording_consolidate(entities):
        seen.append({entity.id for entity in entities})
        return await original_consolidate(entities)

    adapter._consolidate = recording_consolidate

    a_merges, a_failures = await adapter.reconsolidate("a")
    b_merges, b_failures = await adapter.reconsolidate("b")

    assert len(seen) == 2, "one _consolidate call per reconsolidate"
    a_ids_seen, b_ids_seen = seen
    a_ids = {entity.id for entity in a_entities}
    b_ids = {entity.id for entity in b_entities}
    assert a_ids_seen == a_ids, "reconsolidate('a') must act on exactly a's entities"
    assert b_ids_seen == b_ids, "reconsolidate('b') must act on exactly b's entities"
    assert a_ids_seen.isdisjoint(b_ids), "a's and b's entities are never the same ids"
    assert b_ids_seen.isdisjoint(a_ids), "the property must hold in both directions"

    assert a_failures == 0, "nothing further for a to resolve; not a fault"
    assert a_merges == (), "the merge already happened; resolve has nothing to redo"
    assert b_failures == 0, "document b's entities were never touched"
    assert b_merges == (), "b's entities were never candidates for each other"


#: One entity, named identically in two documents, each with a *different*
#: neighbour. That difference is the whole point: entity ids are namespaced per
#: document by `redstring.extraction.mapping.entity_id_for`, so the two
#: neighbours are two ids no matter what they are called, and the neighbour sets
#: of the duplicate pair are disjoint by construction.
_BREED_IN_CANADA = {
    "entities": [
        {"name": "Nova Scotia Duck Tolling Retriever", "entity_type": "concept"},
        {"name": "Canada", "entity_type": "concept"},
    ],
    "relationships": [
        {
            "source_name": "Nova Scotia Duck Tolling Retriever",
            "target_name": "Canada",
            "relationship_type": "ORIGINATES_IN",
        }
    ],
}

_BREED_AND_HUNTING = {
    "entities": [
        {"name": "Nova Scotia Duck Tolling Retriever", "entity_type": "concept"},
        {"name": "Duck hunting", "entity_type": "concept"},
    ],
    "relationships": [
        {
            "source_name": "Nova Scotia Duck Tolling Retriever",
            "target_name": "Duck hunting",
            "relationship_type": "USED_FOR",
        }
    ],
}


#: What the adjudicator says when it is asked. One verdict, because the
#: identical-name pair is the only thing that should ever reach the band --
#: `zip(strict=True)` upstream turns a count mismatch into "no answer", so a
#: second candidate arriving here would show up as a failed merge rather than
#: as a silently mis-paired verdict.
_SAYS_THEY_ARE_THE_SAME = {
    "verdicts": [
        {"same": True, "confidence": 0.99, "reason": "the same dog breed, named identically"}
    ]
}


# `test_one_entity_named_the_same_in_two_documents_becomes_one_node` lived
# here from PR #84 until the floor it depended on was deleted. It is now two
# tests in `test_embedded_consolidation.py` -- one showing the pair merging on
# three-feature evidence, one showing it staying two nodes on two -- because
# the single test could no longer say which of those it was pinning. The
# fixtures it used stay here; both modules read them.


@pytest.mark.asyncio
async def test_a_consolidation_failure_says_which_entity_and_why(tmp_path, build_adapter):
    """A swallowed `RedstringError` used to be indistinguishable from routine.

    `_consolidate` caught every `RedstringError`, incremented a counter and
    continued, on the stated assumption that the cause is "typically the entity
    was absorbed by a merge earlier in this same loop". That is only true of
    `ConsolidationInvariantError`. `RedstringError` is redstring's *base* class,
    so `CircuitOpen`, `RateLimitExceeded`, `LlmProviderError`,
    `MissingEntityError` and `AliasCycleError` all landed in the same arm --
    a rate-limited adjudicator would consolidate nothing across a whole ingest
    and report only a number.

    The count itself was always reported (`format_ingest_report` prints it), so
    what was missing is *which entity and why*. This asserts the note carries
    the entity's name and the error's own text.

    Reverting the change makes this fail: without it the only note for a failed
    entity is the "consolidating" one made before `resolve` was called, which
    names the entity but not the failure.
    """
    project_id = uuid4()
    adapter, _, _ = build_adapter(tmp_path, project_id)

    async def always_fails(entity, **kwargs):
        raise LlmProviderError("the adjudicator is rate limited", model="test-model")

    adapter._consolidator.resolve = always_fails

    notes = []
    report = await adapter.ingest(
        SourceRef(source_id="notes", text="Ada Lovelace worked with Charles Babbage."),
        report=notes.append,
    )

    assert report.consolidation_failures == report.entity_count
    details = [note.detail for note in notes if note.detail]
    assert any(
        "could not be consolidated" in detail and "rate limited" in detail
        for detail in details
    ), details


@pytest.mark.asyncio
async def test_merge_entities_rejects_absorbing_an_already_merged_entity(
    tmp_path, build_adapter
):
    """`merge_entities` is the explicit path -- it still enforces redstring's

    own invariant that an absorbed entity cannot be merged again, and that
    invariant surfaces as `KnowledgeError`, not a raw redstring exception.
    """
    project_id = uuid4()
    adapter, _, _ = build_adapter(tmp_path, project_id)
    await adapter.ingest(
        SourceRef(source_id="a", text="Ada Lovelace worked with Charles Babbage.")
    )

    a_entities = await adapter.entities_for("a")
    await adapter.merge_entities(
        canonical=a_entities[0].id, absorbed=[a_entities[1].id], reason="first merge"
    )

    with pytest.raises(KnowledgeError):
        await adapter.merge_entities(
            canonical=a_entities[1].id,
            absorbed=[a_entities[0].id],
            reason="already absorbed",
        )


@pytest.mark.asyncio
async def test_reconsolidating_an_unknown_source_is_an_error(tmp_path, build_adapter):
    project_id = uuid4()
    adapter, _, _ = build_adapter(tmp_path, project_id)

    with pytest.raises(KnowledgeError, match="never-ingested"):
        await adapter.reconsolidate("never-ingested")


@pytest.mark.asyncio
async def test_a_provider_failure_records_no_extraction(tmp_path, build_adapter):
    """No extraction is appended, and the caller gets an error it can render.

    The corpus write is a separate guarantee and deliberately does survive
    this -- see `test_the_document_survives_a_failed_extraction`.
    """

    class Failing:
        async def complete(self, *args, **kwargs):
            raise RuntimeError("endpoint down")

    project_id = uuid4()
    adapter, store, _ = build_adapter(tmp_path, project_id, provider=Failing())

    with pytest.raises(KnowledgeError):
        await adapter.ingest(SourceRef(source_id="notes", text="Ada Lovelace."))

    stream = document_stream(tenant_id=project_id, source_id="notes")
    assert await collect(store.read_stream(stream)) == []


@pytest.mark.asyncio
async def test_search_finds_an_ingested_entity_by_substring(tmp_path, build_adapter):
    project_id = uuid4()
    adapter, _, _ = build_adapter(tmp_path, project_id)
    await adapter.ingest(
        SourceRef(source_id="notes", text="Ada Lovelace worked with Charles Babbage.")
    )

    matches = (await adapter.search("lovelace")).matches

    assert matches, "an ingested entity should be findable"
    assert any("lovelace" in match.name.lower() for match in matches)


@pytest.mark.asyncio
async def test_search_finds_an_entity_by_an_interior_fragment(tmp_path, build_adapter):
    """`ovelace` finds `Ada Lovelace`.

    Passes today against the substring scan. It is here because it does *not*
    pass against `redstring.Retriever`'s lexical channel, which blocks on a
    five-character prefix of the normalized name and a soundex of the whole
    name -- an interior fragment shares neither. Measured 2026-08-21.

    The existing `test_search_finds_an_ingested_entity_by_substring` cannot
    catch that loss: it searches `lovelace`, which is a prefix of the
    *surname* but the fused channel is blocking on `ada l`, and more to the
    point a full-name query matches under every candidate implementation.
    If this test goes red, the substring channel was dropped.
    """
    project_id = uuid4()
    adapter, _, _ = build_adapter(tmp_path, project_id)
    await adapter.ingest(
        SourceRef(source_id="notes", text="Ada Lovelace worked with Charles Babbage.")
    )

    matches = (await adapter.search("ovelace")).matches

    assert [match.name for match in matches] == ["Ada Lovelace"]


@pytest.mark.asyncio
async def test_search_finds_an_entity_by_a_short_prefix(tmp_path, build_adapter):
    """`Ada` finds `Ada Lovelace`.

    Fails against `Retriever` alone: the query's prefix key is `p:ada` and the
    entity's is `p:ada l` -- five characters, space included -- and their
    soundexes differ (`A300` against `A314`). Measured 2026-08-21.
    """
    project_id = uuid4()
    adapter, _, _ = build_adapter(tmp_path, project_id)
    await adapter.ingest(
        SourceRef(source_id="notes", text="Ada Lovelace worked with Charles Babbage.")
    )

    matches = (await adapter.search("Ada")).matches

    assert [match.name for match in matches] == ["Ada Lovelace"]


@pytest.mark.asyncio
async def test_search_finds_an_entity_despite_a_misspelling(tmp_path, build_adapter):
    """`Adah Lovelace` finds `Ada Lovelace`.

    The capability this stage adds, and the reason for taking on
    `redstring.Retriever` at all. A substring test cannot reach it at any
    threshold -- the query is not contained in the name -- so it returns
    nothing today and fails with the fused channels reverted.

    It works through the soundex blocking key: `Adah Lovelace` and `Ada
    Lovelace` both soundex to `A314`.

    **`embeddings` and `vector_store` are passed because `Retriever.__init__`
    requires them**, not because anything here uses a semantic channel --
    `search` asks for `RetrievalMode.LEXICAL` and the match is a soundex hit.
    See `search`'s docstring for what that constructor requirement costs a
    deployment with embeddings switched off, and `BACKLOG.md`
    B-LEXICAL-NEEDS-EMBEDDINGS-1.

    Exactly one result, not "at least one": the lexical channel is asked for
    names and `Charles Babbage` is not one. An earlier draft of this test ran
    under `RetrievalMode.HYBRID`, where the semantic channel returned
    `Charles Babbage` too -- `FakeEmbeddingProvider` hashes text into a unit
    vector, so those neighbours were the hash rather than a meaning. That is
    the observation that moved `search` off HYBRID; see its docstring.
    """
    project_id = uuid4()
    adapter, _, _ = build_adapter(
        tmp_path,
        project_id,
        embeddings=FakeEmbeddingProvider(dimension=8),
        vector_store=InMemoryVectorStore(dimension=8),
    )
    await adapter.ingest(
        SourceRef(source_id="notes", text="Ada Lovelace worked with Charles Babbage.")
    )

    matches = (await adapter.search("Adah Lovelace")).matches

    assert [match.name for match in matches] == ["Ada Lovelace"]


@pytest.mark.asyncio
async def test_search_reads_relationships_once_regardless_of_match_count(
    tmp_path, build_adapter
):
    """One `get_relationships_for`, not one per match.

    The previous shape issued the call inside the match loop: N round trips to
    answer one question, and invisible to every test because the counts came
    out identical either way. Counted through a wrapper rather than timed,
    because a per-match call is correct-looking and differs only in cost.

    Fails with the batching reverted, at 2 calls for 2 matches.
    """
    project_id = uuid4()
    adapter, _, _ = build_adapter(tmp_path, project_id)
    await adapter.ingest(
        SourceRef(source_id="notes", text="Ada Lovelace worked with Charles Babbage.")
    )

    calls = 0
    original = adapter._store.get_relationships_for

    async def counting(*args, **kwargs):
        nonlocal calls
        calls += 1
        return await original(*args, **kwargs)

    adapter._store.get_relationships_for = counting

    matches = (await adapter.search("a")).matches

    assert len(matches) == 2, "fixture needs both entities to match"
    assert all(match.relationship_count == 1 for match in matches), (
        "the batched read must still count each endpoint's edge"
    )
    assert calls == 1


@pytest.mark.asyncio
async def test_search_reports_substring_mode_when_embeddings_are_unavailable(
    tmp_path, build_adapter
):
    """A dead embedding endpoint degrades entity search, and says so.

    `_embedding_pair` latches `(None, None)` when its probe fails. That is the
    right trade for consolidation -- losing an optional scoring feature beats
    discarding a document that has already been fetched and extracted -- and
    the wrong one for retrieval, where it silently removes the fuzzy channel
    and leaves plausible substring hits behind.

    This asserts the degradation is legible from the **result**. With this
    reverted the only trace was a log line at warning, and a caller could not
    tell a thin answer from a degraded one.

    Note what it does *not* assert: that the search failed. Degrading is the
    intended behaviour and `Ada Lovelace` still comes back.
    """
    project_id = uuid4()
    adapter, _, _ = build_adapter(tmp_path, project_id)
    await adapter.ingest(
        SourceRef(source_id="notes", text="Ada Lovelace worked with Charles Babbage.")
    )

    outcome = await adapter.search("Ada")

    assert outcome.mode is SearchMode.SUBSTRING
    assert [match.name for match in outcome.matches] == ["Ada Lovelace"]


@pytest.mark.asyncio
async def test_search_reports_fused_mode_when_embeddings_work(tmp_path, build_adapter):
    """The healthy case names itself too.

    Without this, `mode` could be hardcoded to SUBSTRING and the test above
    would pass -- which is the whole failure shape the field exists to close,
    reproduced inside its own test.
    """
    project_id = uuid4()
    adapter, _, _ = build_adapter(
        tmp_path,
        project_id,
        embeddings=FakeEmbeddingProvider(dimension=8),
        vector_store=InMemoryVectorStore(dimension=8),
    )
    await adapter.ingest(
        SourceRef(source_id="notes", text="Ada Lovelace worked with Charles Babbage.")
    )

    outcome = await adapter.search("Ada")

    assert outcome.mode is SearchMode.FUSED


@pytest.mark.asyncio
async def test_search_caps_at_the_limit(tmp_path, build_adapter):
    """Distinguish "capped correctly" from "returned nothing": both entities
    match "a" (Ada Lovelace, Charles Babbage), so an uncapped search returns
    two -- only a working cap brings it down to exactly one."""
    project_id = uuid4()
    adapter, _, _ = build_adapter(tmp_path, project_id)
    await adapter.ingest(
        SourceRef(source_id="notes", text="Ada Lovelace worked with Charles Babbage.")
    )

    uncapped = (await adapter.search("a")).matches
    assert len(uncapped) >= 2, "fixture needs at least two entities matching 'a'"

    assert len((await adapter.search("a", limit=1)).matches) == 1


@pytest.mark.asyncio
async def test_search_rejects_a_limit_below_one(tmp_path, build_adapter):
    project_id = uuid4()
    adapter, _, _ = build_adapter(tmp_path, project_id)

    with pytest.raises(KnowledgeError):
        await adapter.search("anything", limit=0)


@pytest.mark.asyncio
async def test_search_of_a_blank_query_returns_nothing(tmp_path, build_adapter):
    project_id = uuid4()
    adapter, _, _ = build_adapter(tmp_path, project_id)
    await adapter.ingest(
        SourceRef(source_id="notes", text="Ada Lovelace worked with Charles Babbage.")
    )

    assert (await adapter.search("   ")).matches == ()


@pytest.mark.asyncio
async def test_undo_merge_rejects_an_unknown_id(tmp_path, build_adapter):
    project_id = uuid4()
    adapter, _, _ = build_adapter(tmp_path, project_id)

    with pytest.raises(KnowledgeError):
        await adapter.undo_merge(uuid4())


@pytest.mark.asyncio
async def test_undo_merge_reverses_an_explicit_merge(tmp_path, build_adapter):
    project_id = uuid4()
    adapter, _, _ = build_adapter(tmp_path, project_id)
    await adapter.ingest(
        SourceRef(source_id="a", text="Ada Lovelace worked with Charles Babbage.")
    )
    a_entities = await adapter.entities_for("a")
    merge = await adapter.merge_entities(
        canonical=a_entities[0].id, absorbed=[a_entities[1].id], reason="test fixture"
    )

    record = await adapter.undo_merge(merge.merge_id)

    assert record.merge_id == merge.merge_id
    # Undoing the same merge again must fail -- it is no longer in effect.
    with pytest.raises(KnowledgeError):
        await adapter.undo_merge(merge.merge_id)


@pytest.mark.asyncio
async def test_merges_are_remembered_across_restarts(tmp_path, build_adapter):
    """Undo is durable only when both stores are passed; assert it, don't assume.

    The boolean alone is a claim about durability, not proof of it, so this
    also performs a merge through one adapter and undoes it through a SECOND
    adapter built with a FRESH `SQLiteEventStore` over the same db_path -- the
    strongest cheap evidence that the merge log actually survived a restart
    rather than living in memory.

    The snapshot store is deliberately reused rather than reopened: it is an
    optimisation over the event log, not the record, and `SQLiteSnapshotStore`
    has no `close()` -- a second instance over the same path would leak its
    worker thread and hang interpreter shutdown. Durability is a property of
    the event log, which is exactly what the fresh `SQLiteEventStore` proves.

    The graph store is also reused rather than reopened, for an unrelated
    reason: `InMemoryGraphStore` is this test's stand-in for what would be a
    persistent backend (e.g. Neo4j) in production, and its persistence is not
    what this test is about -- undoing a merge replays restored relationships
    onto entities the merge touched, and a fresh, empty `InMemoryGraphStore`
    would not have them. What is under test is that the *merge log* survives
    a restart of the event store, not that this stand-in graph backend does.
    """
    project_id = uuid4()
    adapter, _, snapshot_store = build_adapter(tmp_path, project_id)

    assert adapter.remembers_merges_across_restarts

    await adapter.ingest(
        SourceRef(source_id="a", text="Ada Lovelace worked with Charles Babbage.")
    )
    a_entities = await adapter.entities_for("a")
    merge = await adapter.merge_entities(
        canonical=a_entities[0].id, absorbed=[a_entities[1].id], reason="test fixture"
    )

    db_path = str(tmp_path / "sessions.db")
    restarted_event_store = SQLiteEventStore(db_path)
    try:
        restarted = RedstringKnowledge(
            project_id,
            store=adapter._store,
            event_store=restarted_event_store,
            snapshot_store=snapshot_store,
            provider=fake_provider(),
            corpus=build_corpus_repository(
                restarted_event_store, snapshot_store=snapshot_store
            ),
            domain="encyclopedia_wiki",
            adjudicate=False,
        )

        record = await restarted.undo_merge(merge.merge_id)
        assert record.merge_id == merge.merge_id
    finally:
        await restarted_event_store.close()


@pytest.fixture
def captured_documents(monkeypatch):
    """Records every `SourceDocument` the adapter hands to `build_graph`.

    The citation fields are asserted against the document rather than the
    `IngestReport`, which carries none of them and so would pass whether or
    not they were ever set -- the exact bug these tests exist to catch.
    """

    documents = []
    real_build_graph = redstring_adapter.build_graph

    async def recording_build_graph(document, **kwargs):
        documents.append(document)
        return await real_build_graph(document, **kwargs)

    monkeypatch.setattr(redstring_adapter, "build_graph", recording_build_graph)
    return documents


@pytest.mark.asyncio
async def test_citation_fields_reach_the_source_document(
    tmp_path, build_adapter, captured_documents
):
    project_id = uuid4()
    adapter, _, _ = build_adapter(tmp_path, project_id)

    await adapter.ingest(
        SourceRef(
            source_id="notes",
            text="Ada Lovelace worked with Charles Babbage.",
            uri="https://example.test/ada",
            title="Ada Lovelace",
            published_at="1843-07-10",
        )
    )

    document = captured_documents[0]
    assert document.uri == "https://example.test/ada"
    assert document.title == "Ada Lovelace"
    assert document.published_at == datetime(1843, 7, 10, tzinfo=UTC)


@pytest.mark.asyncio
async def test_a_source_without_citation_fields_leaves_them_unset(
    tmp_path, build_adapter, captured_documents
):
    project_id = uuid4()
    adapter, _, _ = build_adapter(tmp_path, project_id)

    await adapter.ingest(
        SourceRef(source_id="notes", text="Ada Lovelace worked with Charles Babbage.")
    )

    document = captured_documents[0]
    assert document.uri is None
    assert document.title is None
    assert document.published_at is None
    assert "published_at" not in document.metadata


@pytest.mark.asyncio
async def test_an_unparseable_date_is_kept_verbatim_rather_than_dropped(
    tmp_path, build_adapter, captured_documents
):
    """An unreadable date must not cost us the document, nor the string itself."""
    project_id = uuid4()
    adapter, _, _ = build_adapter(tmp_path, project_id)

    report = await adapter.ingest(
        SourceRef(
            source_id="notes",
            text="Ada Lovelace worked with Charles Babbage.",
            published_at="sometime last spring",
        )
    )

    assert report.entity_count >= 1
    document = captured_documents[0]
    assert document.published_at is None
    assert document.metadata["published_at"] == "sometime last spring"


@pytest.mark.asyncio
async def test_a_timestamp_with_a_zone_is_accepted(
    tmp_path, build_adapter, captured_documents
):
    project_id = uuid4()
    adapter, _, _ = build_adapter(tmp_path, project_id)

    await adapter.ingest(
        SourceRef(
            source_id="notes",
            text="Ada Lovelace worked with Charles Babbage.",
            published_at="2026-08-05T12:30:00Z",
        )
    )

    assert captured_documents[0].published_at == datetime(2026, 8, 5, 12, 30, tzinfo=UTC)


def _corpus_events(store, project_id):
    """The corpus stream's events, read directly rather than via a projection.

    The read model for the corpus is built in a separate workstream; reading
    the log keeps these assertions independent of it, and the log is the
    thing B12 is actually about -- a projection could be rebuilt, a missing
    event could not.
    """
    return collect(store.read_stream(StreamId(project_id, "Corpus")))


@pytest.mark.asyncio
async def test_ingest_keeps_the_source_text(tmp_path, build_adapter):
    """After `remember` the system holds the document, not just a graph about it.

    The guarantee the corpus layer exists to provide: extraction used to be
    handed the text and drop it, leaving a graph whose every claim named a
    source nothing could produce.
    """
    project_id = uuid4()
    adapter, store, _ = build_adapter(tmp_path, project_id)

    await adapter.ingest(
        SourceRef(
            source_id="notes",
            text="Ada Lovelace worked with Charles Babbage.",
            uri="https://example.test/ada",
            title="Ada Lovelace",
            published_at="sometime last spring",
            note="for the timeline",
        )
    )

    envelopes = await _corpus_events(store, project_id)
    assert len(envelopes) == 1
    stored = envelopes[0].event
    assert type(stored).__name__ == "CorpusDocumentStored"
    assert stored.source_id == "notes"
    assert stored.text == "Ada Lovelace worked with Charles Babbage."
    assert stored.uri == "https://example.test/ada"
    assert stored.title == "Ada Lovelace"
    # Verbatim, unlike redstring's `published_at`: the corpus event is the
    # archival copy, so it keeps what the source said even when it is prose.
    assert stored.published_at == "sometime last spring"
    assert stored.note == "for the timeline"


@pytest.mark.asyncio
async def test_the_document_survives_a_failed_extraction(tmp_path, build_adapter):
    """Store first, extract second -- and a failed extraction keeps the text."""

    class Failing:
        async def complete(self, *args, **kwargs):
            raise RuntimeError("endpoint down")

    project_id = uuid4()
    adapter, store, _ = build_adapter(tmp_path, project_id, provider=Failing())

    with pytest.raises(KnowledgeError):
        await adapter.ingest(SourceRef(source_id="notes", text="Ada Lovelace."))

    envelopes = await _corpus_events(store, project_id)
    assert [e.event.text for e in envelopes] == ["Ada Lovelace."]
    extraction = document_stream(tenant_id=project_id, source_id="notes")
    assert await collect(store.read_stream(extraction)) == []


@pytest.mark.asyncio
async def test_nothing_is_stored_when_the_document_is_refused(tmp_path, build_adapter):
    """The size and id guards run before the corpus write, not after."""
    from research_team.infrastructure.knowledge.redstring_adapter import (
        MAX_DOCUMENT_CHARS,
    )

    project_id = uuid4()
    adapter, store, _ = build_adapter(tmp_path, project_id)

    with pytest.raises(KnowledgeError):
        await adapter.ingest(SourceRef(source_id="huge", text="x" * (MAX_DOCUMENT_CHARS + 1)))
    with pytest.raises(KnowledgeError):
        await adapter.ingest(SourceRef(source_id="  ", text="Ada Lovelace."))

    assert await _corpus_events(store, project_id) == []


@pytest.mark.asyncio
async def test_re_ingesting_identical_bytes_stores_one_document(tmp_path, build_adapter):
    project_id = uuid4()
    adapter, store, _ = build_adapter(tmp_path, project_id)
    source = SourceRef(source_id="notes", text="Ada Lovelace worked with Charles Babbage.")

    await adapter.ingest(source)
    await adapter.ingest(source)

    envelopes = await _corpus_events(store, project_id)
    assert len(envelopes) == 1


@pytest.mark.asyncio
async def test_re_ingesting_changed_bytes_records_the_revision(tmp_path, build_adapter):
    """Same id, new text is a revision -- both versions stay in the log."""
    project_id = uuid4()
    adapter, store, _ = build_adapter(tmp_path, project_id)

    await adapter.ingest(SourceRef(source_id="notes", text="Ada Lovelace."))
    await adapter.ingest(SourceRef(source_id="notes", text="Ada Lovelace and Babbage."))

    envelopes = await _corpus_events(store, project_id)
    assert [e.event.text for e in envelopes] == [
        "Ada Lovelace.",
        "Ada Lovelace and Babbage.",
    ]


@pytest.mark.asyncio
async def test_identical_bytes_under_a_new_id_are_stored_separately(tmp_path, build_adapter):
    """Two URIs can legitimately serve one document, and each needs its own record."""
    project_id = uuid4()
    adapter, store, _ = build_adapter(tmp_path, project_id)
    text = "Ada Lovelace worked with Charles Babbage."

    await adapter.ingest(SourceRef(source_id="mirror-a", text=text))
    await adapter.ingest(SourceRef(source_id="mirror-b", text=text))

    envelopes = await _corpus_events(store, project_id)
    assert [e.event.source_id for e in envelopes] == ["mirror-a", "mirror-b"]


# --- concurrent ingest ------------------------------------------------------
#
# The model puts several tool calls in one assistant message and the executor
# runs them concurrently, so two `remember` calls land in the same moment. Both
# reach `_store_document`, both load the corpus at the same version, and the
# second save loses the compare-and-swap.
#
# What made this worth a fix rather than a shrug is where the error surfaced.
# `remember` catches `KnowledgeError` and nothing else, so an
# `OptimisticLockError` escaped the tool, escaped the executor, and was
# recorded as a `TurnFailed` -- the whole turn discarded because two of its
# tool calls were merely simultaneous. And because a corpus shares its
# project's UUID, the message named the *project*, which is why this reads as
# a project-level fault in the UI when nothing about the project was wrong.


@pytest.mark.asyncio
async def test_two_ingests_at_once_do_not_lose_one_to_a_lock_error(tmp_path, build_adapter):
    """Two `remember` calls in one assistant message must both land."""
    import asyncio

    project_id = uuid4()
    adapter, store, snapshot_store = build_adapter(tmp_path, project_id)

    reports = await asyncio.gather(
        adapter.ingest(SourceRef(source_id="a", text="Ada Lovelace wrote a program.")),
        adapter.ingest(SourceRef(source_id="b", text="Grace Hopper built a compiler.")),
    )

    assert len(reports) == 2
    # Both documents are in the corpus. A lost write here means a source the
    # user paid to fetch is silently absent, which is the failure the corpus
    # layer exists to prevent.
    corpus = build_corpus_repository(store, snapshot_store=snapshot_store)
    state = (await corpus.load(project_id)).state
    assert sorted(state.documents) == ["a", "b"]


@pytest.mark.asyncio
async def test_ingest_reports_its_stages_in_order(tmp_path, build_adapter):
    """The stage sequence, pinned.

    This is what stops a refactor from quietly silencing the pane: the
    sequence is the contract, not the individual calls.
    """
    project_id = uuid4()
    adapter, _, _ = build_adapter(tmp_path, project_id)
    notes = []

    await adapter.ingest(
        SourceRef(source_id="notes", text="Ada Lovelace worked with Charles Babbage."),
        report=notes.append,
    )

    stages = [note.stage for note in notes]
    assert stages[0] == "storing"
    assert stages[1] == "extracting"
    assert "extracted" in stages
    assert stages[-1] == "consolidated"
    # Consolidation is per entity, and the fake extracts two.
    consolidating = [note for note in notes if note.stage == "consolidating"]
    assert [note.index for note in consolidating] == [1, 2]
    assert all(note.total == 2 for note in consolidating)
    assert all(note.source_id == "notes" for note in notes)


@pytest.mark.asyncio
async def test_the_extracted_note_carries_the_counts_and_the_schema(tmp_path, build_adapter):
    project_id = uuid4()
    adapter, _, _ = build_adapter(tmp_path, project_id)
    notes = []

    report = await adapter.ingest(
        SourceRef(source_id="notes", text="Ada Lovelace worked with Charles Babbage."),
        report=notes.append,
    )

    extracted = next(note for note in notes if note.stage == "extracted")
    assert extracted.entities == report.entity_count
    assert extracted.relationships == report.relationship_count
    assert extracted.domain == report.domain


@pytest.mark.asyncio
async def test_model_calls_are_counted_from_inside_extraction(tmp_path, build_adapter):
    """`build_graph` takes no callbacks, so the provider is the way in.

    Without this the pane has nothing to show during the longest part of an
    ingest, and a slow model looks identical to a hung one.
    """
    project_id = uuid4()
    adapter, _, _ = build_adapter(tmp_path, project_id)
    notes = []

    await adapter.ingest(
        SourceRef(source_id="notes", text="Ada Lovelace worked with Charles Babbage."),
        report=notes.append,
    )

    counted = [note.model_calls for note in notes if note.model_calls]
    assert counted, "no note reported a model call"
    assert max(counted) >= 1


@pytest.mark.asyncio
async def test_a_reporter_that_raises_does_not_fail_the_ingest(tmp_path, build_adapter):
    """A listener must not cost a document already fetched and paid for."""
    project_id = uuid4()
    adapter, _, _ = build_adapter(tmp_path, project_id)

    def explode(note):
        raise RuntimeError("the listener is broken")

    report = await adapter.ingest(
        SourceRef(source_id="notes", text="Ada Lovelace worked with Charles Babbage."),
        report=explode,
    )

    assert report.entity_count > 0


@pytest.mark.asyncio
async def test_a_failed_extraction_reports_a_failed_stage(tmp_path, build_adapter):
    """The pane must be able to say "it broke", not just stop updating."""
    project_id = uuid4()
    adapter, _, _ = build_adapter(tmp_path, project_id)
    notes = []

    with pytest.raises(KnowledgeError):
        await adapter.ingest(
            SourceRef(
                source_id="notes", text="x" * (redstring_adapter.MAX_DOCUMENT_CHARS + 1)
            ),
            report=notes.append,
        )

    assert notes[-1].stage == "failed"
    assert notes[-1].detail


@pytest.mark.asyncio
async def test_a_no_op_re_ingest_still_closes_its_pane(tmp_path, build_adapter):
    """Same content, same model version: nothing new to record, but the pane

    still needs its closing note. A watcher cannot tell "already known" from
    "hung" if the second ingest goes quiet after `extracting`.
    """
    project_id = uuid4()
    adapter, _, _ = build_adapter(tmp_path, project_id)
    source = SourceRef(source_id="notes", text="Ada Lovelace worked with Charles Babbage.")

    await adapter.ingest(source)
    notes = []
    await adapter.ingest(source, report=notes.append)

    stages = [note.stage for note in notes]
    assert "extracted" in stages
    assert stages[-1] == "consolidated"


@pytest.mark.asyncio
async def test_a_blank_source_id_announces_nothing(tmp_path, build_adapter):
    """There is no id to attribute a note to, so no note is made."""
    project_id = uuid4()
    adapter, _, _ = build_adapter(tmp_path, project_id)
    notes = []

    with pytest.raises(KnowledgeError):
        await adapter.ingest(SourceRef(source_id="   ", text="anything"), report=notes.append)

    assert notes == []


@pytest.mark.asyncio
async def test_fetched_at_reaches_the_stored_document(tmp_path, build_adapter) -> None:
    """The field has existed on the command and the event since the corpus
    layer landed, and has always been None on this path -- `remember` has no
    argument that could fill it. Fails if the adapter drops it again."""
    project_id = uuid4()
    adapter, store, _ = build_adapter(tmp_path, project_id)

    await adapter.ingest(
        SourceRef(
            source_id="s1",
            text="body",
            uri="https://example.com/a",
            fetched_at="2026-08-10T12:00:00+00:00",
        )
    )

    envelopes = await _corpus_events(store, project_id)
    stored = envelopes[0].event
    assert stored.fetched_at == "2026-08-10T12:00:00+00:00"


@pytest.mark.asyncio
async def test_a_source_without_a_fetch_time_leaves_it_unset(tmp_path, build_adapter) -> None:
    """`remember` cannot know when text it was handed was read, and a guessed
    timestamp would be worse than the absence it replaced."""
    project_id = uuid4()
    adapter, store, _ = build_adapter(tmp_path, project_id)

    await adapter.ingest(SourceRef(source_id="s1", text="body"))

    envelopes = await _corpus_events(store, project_id)
    stored = envelopes[0].event
    assert stored.fetched_at is None


@pytest.fixture
def captured_build_kwargs(monkeypatch):
    """Records the keyword arguments the adapter hands to `build_graph`.

    Deliberately not the `IngestReport`: nothing on the report reflects
    `concurrency` or `chunker`, so an assertion made there would pass whether
    or not either value ever left this adapter. The call is the only place the
    fact is observable without a real model and a stopwatch.
    """
    calls = []
    real_build_graph = redstring_adapter.build_graph

    async def recording_build_graph(document, **kwargs):
        calls.append(kwargs)
        return await real_build_graph(document, **kwargs)

    monkeypatch.setattr(redstring_adapter, "build_graph", recording_build_graph)
    return calls


@pytest.mark.asyncio
async def test_the_extraction_knobs_reach_build_graph(
    tmp_path, build_adapter, captured_build_kwargs
) -> None:
    """Both are plumbing, and plumbing is exactly what silently goes missing.

    This fails with the change reverted -- `concurrency` would be absent from
    the call rather than merely different, since the adapter did not pass it
    at all.
    """
    chunker = SlidingWindowChunker(default_chunk_size=2_000)
    adapter, _, _ = build_adapter(tmp_path, uuid4(), concurrency=8, chunker=chunker)

    await adapter.ingest(SourceRef(source_id="s1", text="body"))

    assert captured_build_kwargs[0]["concurrency"] == 8
    assert captured_build_kwargs[0]["chunker"] is chunker


@pytest.mark.asyncio
async def test_an_adapter_built_without_the_knobs_extracts_serially(
    tmp_path, build_adapter, captured_build_kwargs
) -> None:
    """The default is redstring's serial pipeline, not the configured value.

    `config` is read in the composition root and nowhere else, so a
    `RedstringKnowledge` built directly -- which is every test here, and any
    future caller that is not `build_container` -- gets `concurrency=1`, which
    upstream states is byte-identical to the pre-0.8.0 pipeline. The point is
    that turning concurrency on is a decision made in one visible place rather
    than a default that arrives everywhere at once.
    """
    adapter, _, _ = build_adapter(tmp_path, uuid4())

    await adapter.ingest(SourceRef(source_id="s1", text="body"))

    assert captured_build_kwargs[0]["concurrency"] == 1
    assert captured_build_kwargs[0]["chunker"] is None


@pytest.mark.asyncio
async def test_store_source_keeps_the_text_without_extracting_it(
    tmp_path, build_adapter, captured_build_kwargs
) -> None:
    """The whole point of the method: the document, and no model calls.

    `captured_build_kwargs` staying empty is the load-bearing assertion. Were
    this to call `ingest`, the corpus check would pass identically and the
    only visible difference would be minutes of wall clock and a model call
    per chunk -- which is exactly the mistake the method exists to prevent.
    """
    project_id = uuid4()
    adapter, store, _ = build_adapter(tmp_path, project_id)

    await adapter.store_source(
        SourceRef(
            source_id="example-test-ada",
            text="Ada Lovelace worked with Charles Babbage.",
            uri="https://example.test/ada",
            title="Ada Lovelace",
        )
    )

    envelopes = await _corpus_events(store, project_id)
    assert [envelope.event.source_id for envelope in envelopes] == ["example-test-ada"]
    assert captured_build_kwargs == []


@pytest.mark.asyncio
async def test_store_source_refuses_what_ingest_refuses(tmp_path, build_adapter) -> None:
    """Both refusals are kept, and the length one is the non-obvious half.

    Nothing here chunks the text, so the cap looks like it could be relaxed.
    It is not: a document over it can never be extracted later, so storing one
    would create a corpus entry no `remember_page` could ever complete.
    """
    project_id = uuid4()
    adapter, store, _ = build_adapter(tmp_path, project_id)

    with pytest.raises(KnowledgeError):
        await adapter.store_source(SourceRef(source_id="  ", text="body"))
    with pytest.raises(KnowledgeError):
        await adapter.store_source(
            SourceRef(source_id="huge", text="x" * (redstring_adapter.MAX_DOCUMENT_CHARS + 1))
        )

    assert await _corpus_events(store, project_id) == []


@pytest.mark.asyncio
async def test_storing_the_same_page_twice_records_it_once(tmp_path, build_adapter) -> None:
    """A run re-reading a page must not grow the corpus each time.

    Automatic saving makes this ordinary rather than exceptional: the model
    does not choose when this runs, so the same url arriving twice in one run
    is expected. The digest check in `_store_document` is what absorbs it, and
    this is the caller that depends on it.
    """
    project_id = uuid4()
    adapter, store, _ = build_adapter(tmp_path, project_id)
    source = SourceRef(
        source_id="example-test-a",
        text="Ada Lovelace worked with Charles Babbage.",
        uri="https://example.test/a",
    )

    await adapter.store_source(source)
    await adapter.store_source(source)

    assert len(await _corpus_events(store, project_id)) == 1


#: Two documents naming one person two ways, with no shared neighbour.
#:
#: `JFK` against `John F. Kennedy` scores 0.609 on name similarity and the two
#: share no blocking prefix, so redstring's own finder never builds the pair as
#: a candidate at all -- which is the case entity judgements exist for, and the
#: reason these fixtures are not the `Nova Scotia` pair the rest of this module
#: uses. An identical-name pair would merge on its own evidence and prove
#: nothing about judgements.
_KENNEDY_SHORT = {
    "entities": [
        {"name": "JFK", "entity_type": "concept"},
        {"name": "PT-109", "entity_type": "concept"},
    ],
    "relationships": [
        {
            "source_name": "JFK",
            "target_name": "PT-109",
            "relationship_type": "COMMANDED",
        }
    ],
}

_KENNEDY_LONG = {
    "entities": [
        {"name": "John F. Kennedy", "entity_type": "concept"},
        {"name": "Inauguration", "entity_type": "concept"},
    ],
    "relationships": [
        {
            "source_name": "John F. Kennedy",
            "target_name": "Inauguration",
            "relationship_type": "SPOKE_AT",
        }
    ],
}


@pytest.fixture
def kennedy_provider():
    """One person, two documents, two spellings, two distinct neighbours."""
    return FakeLlmProvider(
        by_substring={"inauguration": _KENNEDY_LONG},
        default=_KENNEDY_SHORT,
    )


async def _record_same(store, snapshot_store, project_id, left, right, reason):
    """Record one held-same judgement over the adapter's own log."""
    repository = build_judgements_repository(store, snapshot_store=snapshot_store)
    judgements = await repository.load_or_create(project_id)
    judgements.execute(
        HoldSame(
            judgements_id=project_id,
            keys=[EntityKey.of(left, "concept"), EntityKey.of(right, "concept")],
            reason=reason,
        )
    )
    await repository.save(judgements)


@pytest.mark.asyncio
async def test_a_held_same_judgement_merges_what_scoring_never_pairs(
    tmp_path, build_adapter, kennedy_provider
):
    """The whole point of the feature, end to end.

    `JFK` and `John F. Kennedy` score 0.609 on name and share no blocking
    prefix, so no threshold or weight change reaches them -- redstring never
    builds the pair as a candidate at all. The judgement is what puts the
    counterpart in front of consolidation, injected at 1.0 so it merges
    without a model call.

    **Proved red before it was trusted green**: with `judgements=False` passed
    to `build_adapter` and everything else identical, this finds two nodes.
    The test below makes that permanent rather than leaving it as a claim.
    """
    project_id = uuid4()
    adapter, store, snapshot_store = build_adapter(
        tmp_path, project_id, provider=kennedy_provider, judgements=True
    )
    await _record_same(
        store, snapshot_store, project_id, "JFK", "John F. Kennedy", "one president"
    )

    await adapter.ingest(SourceRef(source_id="a", text="JFK commanded PT-109."))
    await adapter.ingest(SourceRef(source_id="b", text="The inauguration was cold."))

    assert len((await adapter.search("JFK")).matches) == 0, "the short spelling was absorbed"
    assert len((await adapter.search("Kennedy")).matches) == 1, "one person, one node"


@pytest.mark.asyncio
async def test_without_a_judgements_repository_the_same_pair_stays_two_nodes(
    tmp_path, build_adapter, kennedy_provider
):
    """The other half, and what makes the test above evidence rather than hope.

    Identical but for the repository. It is also the passthrough guarantee that
    every existing construction site relies on: with no repository the adapter
    builds no finder, `resolve` falls back to its own, and consolidation is
    exactly what it was before judgements existed.
    """
    project_id = uuid4()
    adapter, _, _ = build_adapter(tmp_path, project_id, provider=kennedy_provider)

    await adapter.ingest(SourceRef(source_id="a", text="JFK commanded PT-109."))
    await adapter.ingest(SourceRef(source_id="b", text="The inauguration was cold."))

    assert len((await adapter.search("JFK")).matches) == 1, "still its own node"
    assert len((await adapter.search("Kennedy")).matches) == 1, "and so is the long spelling"
