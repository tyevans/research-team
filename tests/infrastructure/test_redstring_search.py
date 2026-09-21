"""Tests for entity search and describe on `RedstringKnowledge`."""

from uuid import uuid4

import pytest
from redstring import (
    FakeEmbeddingProvider,
    InMemoryChunkStore,
    InMemoryVectorStore,
)

from research_team.knowledge.application import KnowledgeError, SearchMode, SourceRef


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
async def test_search_still_matches_a_misspelling_without_an_embedding_provider(
    tmp_path, build_adapter
):
    """The fuzzy channel no longer depends on an embedding endpoint.

    It used to. `Retriever.__init__` required an `EmbeddingProvider` and a
    `VectorStore` before any mode was chosen, even though
    `RetrievalMode.LEXICAL` reaches neither -- so a build with
    `AGENT_VECTOR_STORE=none`, or one whose probe latched `(None, None)`, lost
    misspelling-tolerant search: a feature with no embedding in it.

    `Retriever.lexical_only` (redstring B163, ADR 0045) removes the
    requirement. This fixture passes no embeddings at all, which is exactly
    the configuration that used to fall back to a substring scan.
    """
    project_id = uuid4()
    adapter, _, _ = build_adapter(tmp_path, project_id)
    await adapter.ingest(
        SourceRef(source_id="notes", text="Ada Lovelace worked with Charles Babbage.")
    )

    outcome = await adapter.search("Adah Lovelace")

    assert [match.name for match in outcome.matches] == ["Ada Lovelace"]
    assert outcome.mode is SearchMode.FUSED


@pytest.mark.asyncio
async def test_search_reports_fused_mode_when_embeddings_work(tmp_path, build_adapter):
    """The healthy case names itself too.

    Thin on its own now that `search` has one mode: it was the guard against
    hardcoding, back when a second mode existed to be confused with. Kept
    because `describe` still has three, and a `search` that started reporting
    one of those would be a real defect with no other test on it.
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
async def test_describe_finds_an_entity_by_its_neighbour(tmp_path, build_adapter):
    """`describe` answers what `search` cannot: a query naming no part of the name.

    `Charles Babbage` is nowhere in the string `Ada Lovelace`, so neither
    channel `search` has can reach it -- the substring pass tests containment
    in the name and the blocking-key pass hashes a prefix and a soundex of it.
    The edge between them lives in the graph, and the card corpus is what puts
    it in an index.

    Both halves are asserted, because only the pair says anything: `describe`
    finding it proves the card corpus works, and `search` missing it is what
    makes this a new capability rather than a second spelling of an old one.
    """
    project_id = uuid4()
    cards = InMemoryChunkStore(dimension=8)
    adapter, _, _ = build_adapter(tmp_path, project_id, cards=cards)
    await adapter.ingest(
        SourceRef(source_id="notes", text="Ada Lovelace worked with Charles Babbage.")
    )

    described = await adapter.describe("who worked with Charles Babbage")
    searched = await adapter.search("who worked with Charles Babbage")

    assert "Ada Lovelace" in [match.name for match in described.matches]
    assert "Ada Lovelace" not in [match.name for match in searched.matches], (
        "if `search` already answered this, `describe` would not be a capability"
    )


@pytest.mark.asyncio
async def test_describe_without_a_card_corpus_says_so_rather_than_answering_empty(
    tmp_path, build_adapter
):
    """A build with cards off reports it, instead of looking like no match.

    The failure this closes is the one every defect in this feature shares: an
    unwired card store answers every query with nothing, which is
    indistinguishable from a project that genuinely holds no such entity. The
    mode is what separates them, exactly as it does for a degraded `search`.
    """
    project_id = uuid4()
    adapter, _, _ = build_adapter(tmp_path, project_id)
    await adapter.ingest(
        SourceRef(source_id="notes", text="Ada Lovelace worked with Charles Babbage.")
    )

    described = await adapter.describe("who worked with Charles Babbage")

    assert described.matches == ()
    assert described.mode is SearchMode.UNAVAILABLE
