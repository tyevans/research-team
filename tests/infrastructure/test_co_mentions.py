"""The co-mention channel, end to end, against real stores.

The defect these were written for, measured on 2026-08-22 over a real ingest
of five Wikipedia articles: **36 chunks stored for one document, 0 carrying any
`entity_ids`**, `ChunkCoMentions.passages()` returning 0 passages, and an area
projection byte-identical with and without them (31 areas / 437 placed / 108
dropped, both ways). See `docs/design/co-mention-channel-findings.md`.

The root cause was not a wrong line. `build_graph` was never passed `chunks=`,
so extraction -- the only stage that knows which entities came out of which
passage -- had nowhere to record it; the corpus was filled by `index_documents`
instead, which has no entity knowledge and writes every chunk with an empty
`entity_ids`. Nothing failed, nothing logged, and the console printed
"0 shared passages" for the life of the feature.

**Why no existing test caught it**: `ChunkCoMentions` had none, and the
projection's tests drive literal `frozenset`s. The port and its only adapter
were each verified alone and never against each other, which is the shape
`docs/design/co-mention-repair-spec.md` §F-iii is about. So every test here
drives the real `ingest` through `build_adapter`, and none of them asserts that
a call returned or that a store is non-empty -- `index` fills the retrieval
corpus with unlinked chunks, so non-emptiness passes against the dead build.
"""

from uuid import UUID, uuid4

import pytest
from redstring import FakeLlmProvider, InMemoryChunkStore, InMemoryGraphStore

from research_team.application.curriculum import CurriculumService
from research_team.application.knowledge import SourceRef
from research_team.infrastructure.knowledge.co_mention_reader import RecordedCoMentions
from research_team.infrastructure.knowledge.co_mentions import CoMentionIndex
from research_team.infrastructure.knowledge.graph_reader import ProjectGraphReader
from research_team.infrastructure.knowledge.rebuild import rebuild_graph
from tests.conftest import TWO_PEOPLE

DIMENSION = 8

#: Long enough to split into several passages under the retrieval chunker
#: (1000/500) and into one under the extraction chunker (2000), which is the
#: difference `test_the_retrieval_corpus_keeps_its_own_chunking` measures.
TEXT = "Ada Lovelace worked with Charles Babbage on the Analytical Engine. " * 24

#: A second document's text, sharing no distinctive word with `TEXT` so a
#: `by_substring` provider can tell the two extraction prompts apart. Carryover
#: puts the first document's entity *names* into this one's prompt, so the
#: discriminator has to be a word from the text rather than an entity name.
SECOND_TEXT = "Bletchley Park is where the codebreakers worked. " * 24

ADA_AND_TURING = {
    "entities": [
        {"name": "Ada A. Lovelace", "entity_type": "Person"},
        {"name": "Alan Turing", "entity_type": "Person"},
    ],
    "relationships": [
        {
            "source_name": "Ada A. Lovelace",
            "target_name": "Alan Turing",
            "relationship_type": "INFLUENCED",
        }
    ],
}


def _stores() -> tuple[InMemoryChunkStore, CoMentionIndex]:
    """A real retrieval corpus and a real co-mention index.

    Two different kinds of thing, deliberately: the corpus holds passages, the
    index holds three fields per passage. `infrastructure/knowledge/co_mentions.py`
    records why the second is not a second corpus.
    """
    return InMemoryChunkStore(dimension=DIMENSION), CoMentionIndex()


async def _ids_by_name(adapter, project_id: UUID) -> dict[str, UUID]:
    return {e.name: e.id for e in await adapter._store.find_entities(project_id)}


@pytest.mark.asyncio
async def test_an_ingest_leaves_entity_links_in_the_co_mention_store(build_adapter, tmp_path):
    """One ingest, and a passage that knows which entities it produced.

    **Asserted on the ids, never on the store being non-empty.** `index` runs
    on the same ingest and fills the retrieval corpus with chunks whose
    `entity_ids` is `[]`, so "the corpus has passages in it" is true of the
    build this was written against.

    **Proved red on 2026-08-22** by removing the `_apply_co_mentions` call from
    `RedstringKnowledge.ingest`. That is the pair worth understanding: the links
    reach the *log* from `build_graph` alone, but reaching the index this
    session is holding takes a second write, the way the card vectors do.
    Without it a project's own ingest is invisible to its own curriculum until
    the next restart. Counts under BREAK C in the table at the foot of this
    file.
    """
    project_id = uuid4()
    chunks, co_mentions = _stores()
    adapter, _, _ = build_adapter(tmp_path, project_id, chunks=chunks, co_mentions=co_mentions)

    await adapter.ingest(SourceRef(source_id="notes", text=TEXT))

    entities = await _ids_by_name(adapter, project_id)
    assert len(entities) >= 2, "the fake extraction should give two entities to pair"
    ada = entities["Ada Lovelace"]

    linked = co_mentions.by_entity(ada)
    assert linked, "extraction's entity links must reach the co-mention index"
    assert any(len(ids) >= 2 for _, ids in linked), (
        "a passage that names only the entity it was reached by is not a "
        "co-mention; the links have to carry every entity the chunk produced"
    )


@pytest.mark.asyncio
async def test_the_retrieval_corpus_keeps_its_own_chunking(build_adapter, tmp_path):
    """The corpus quotes and citations are drawn from is still 1000/500.

    *Fails against* the two builds that let extraction's `DocumentChunked` into
    the corpus: passing `chunks=graphs.chunks(...)` to `build_graph`, which
    works live and silently doubles the length of every quoted passage; and
    folding with redstring's own unfiltered `ChunkProjection`, which is correct
    live and wrong on every reopen.

    Pinned on chunk *count* rather than on the signature string: the retrieval
    chunker's window is half the extraction chunker's with five times the
    overlap, so a document of this length splits into strictly more passages
    under it, and the count is a property of the chunking rather than of a
    format this test would then have to track.

    **Proved red on 2026-08-22** by passing `chunks=self._chunks` to
    `build_graph`, which is the smallest-diff design exactly. Counts under
    BREAK D in the table at the foot of this file.
    """
    project_id = uuid4()
    chunks, co_mentions = _stores()
    adapter, _, _ = build_adapter(tmp_path, project_id, chunks=chunks, co_mentions=co_mentions)

    await adapter.ingest(SourceRef(source_id="notes", text=TEXT))

    retrieval = await chunks.get_by_source("notes", project_id)

    assert retrieval, "index must still fill the retrieval corpus"
    assert len(co_mentions) > 0, "extraction must still fill the co-mention index"
    assert len(retrieval) > len(co_mentions), (
        f"the retrieval corpus is chunked at 1000/500 and the extraction at "
        f"the larger extraction size, so the corpus must hold more passages "
        f"than the index; got {len(retrieval)} and {len(co_mentions)}, which "
        f"is what the extraction chunking landing in the corpus looks like"
    )
    assert not any(chunk.entity_ids for chunk in retrieval), (
        "index_documents omits entity links entirely, so a linked chunk in the "
        "retrieval corpus means the extraction chunking landed there"
    )


@pytest.mark.asyncio
async def test_a_reindex_after_extraction_does_not_empty_the_co_mention_store(
    build_adapter, tmp_path
):
    """Re-indexing a document must not wipe the links extraction recorded.

    Both write paths record `DocumentChunked` against one `source_id`. Live,
    nothing can cross them -- `index` writes the corpus and `_apply_co_mentions`
    writes the index -- so this passes trivially unless the assertion is taken
    after a *rebuild*, where one event feed reaches both projections and the
    only thing keeping them apart is the link test.

    *Fails against:* an unfiltered second `ChunkProjection`, and against any
    routing that reads the signature's colon count instead of the links.

    **Proved red on 2026-08-22** by making `carries_entity_links` return `True`
    unconditionally, so `CoMentionProjection` applies the re-index too. See
    BREAK A in the table at the foot of this file: the rebuild test stays green
    under it and is not a substitute for this one, because with no re-index on
    the log extraction's chunking is simply the last one and an unfiltered
    projection lands on the right answer by accident.
    """
    project_id = uuid4()
    chunks, co_mentions = _stores()
    adapter, event_store, _ = build_adapter(
        tmp_path, project_id, chunks=chunks, co_mentions=co_mentions
    )

    await adapter.ingest(SourceRef(source_id="notes", text=TEXT))
    await adapter.index(SourceRef(source_id="notes", text=TEXT + " A postscript."))

    folded = CoMentionIndex()
    await rebuild_graph(
        InMemoryGraphStore(),
        feed=event_store,
        project_id=project_id,
        co_mentions=folded,
    )

    entities = await _ids_by_name(adapter, project_id)
    ada = entities["Ada Lovelace"]
    assert folded.by_entity(ada), (
        "a re-index writes unlinked chunks under the same source id; folding "
        "them into the co-mention index replaces the linked ones with nothing"
    )


@pytest.mark.asyncio
async def test_co_mentions_survive_a_rebuild(build_adapter, tmp_path):
    """A co-mention store folded from the log alone holds the links.

    *Fails against* the single most likely wrong implementation of this
    change: filling the index live and never getting the event onto the log.
    Without `event_store=`, `_persist` is a no-op and the `DocumentChunked` the
    aggregate builds is discarded inside the library -- every live assertion
    passes and the project comes back empty on the next open.

    This is also the test CLAUDE.md's read-model rule asks for: its arrange
    phase never touches the store the assertion reads, so a code path that
    stops recording the event cannot hide behind a fixture that recorded it.

    **Proved red on 2026-08-22** by removing `event_store=self._event_store`
    from the `build_graph` call; counts under BREAK B in the table at the foot
    of this file. The live assertion in
    `test_an_ingest_leaves_entity_links_in_the_co_mention_store` **passed**
    throughout, which is the whole reason this one is written.
    """
    project_id = uuid4()
    chunks, co_mentions = _stores()
    adapter, event_store, _ = build_adapter(
        tmp_path, project_id, chunks=chunks, co_mentions=co_mentions
    )

    await adapter.ingest(SourceRef(source_id="notes", text=TEXT))
    entities = await _ids_by_name(adapter, project_id)
    ada = entities["Ada Lovelace"]

    folded = CoMentionIndex()
    await rebuild_graph(
        InMemoryGraphStore(),
        feed=event_store,
        project_id=project_id,
        co_mentions=folded,
    )

    linked = folded.by_entity(ada)
    assert linked, "the log must be able to reproduce the co-mention index"
    assert any(len(ids) >= 2 for _, ids in linked), (
        "a folded passage whose links did not survive the round trip is an "
        "index that replays as empty of links, which is the retrieval corpus"
    )


@pytest.mark.asyncio
async def test_a_co_mention_survives_consolidation(build_adapter, tmp_path):
    """A passage naming an absorbed entity still names its survivor.

    *Fails against the shipped implementation*, which is also the obvious one:
    a chunk's `entity_ids` are read off `map_extraction`'s return, before
    `merge_extractions` and long before `Consolidator.resolve`, and nothing
    ever rewrites them. Every graph read returns canonical entities only, so a
    raw `& wanted` drops the link twice over -- `get_by_entity(survivor)` never
    finds the passage, and if some other entity fetches it the absorbed id is
    intersected away.

    The fixture is built so the second document's passage is *only* reachable
    through the merge: its two entities are the absorbed spelling of Ada and
    Alan Turing, who appears nowhere else. On a corpus with no merges the
    shipped code and the fixed code agree exactly, which is why this test
    manufactures one rather than hoping consolidation fires.

    **Proved red on 2026-08-22** by reverting `ChunkCoMentions.passages` to the
    raw `& wanted` -- looking the store up under the canonical ids alone,
    with no walk of the alias graph: **1 failed, this one**, 8 passed. The
    second document's passage was not returned at all.
    """
    project_id = uuid4()
    chunks, co_mentions = _stores()
    adapter, _, _ = build_adapter(
        tmp_path,
        project_id,
        chunks=chunks,
        co_mentions=co_mentions,
        # One provider answering differently per document, keyed on a word only
        # the second document's text carries. Not keyed on an entity name:
        # carryover puts the first document's names into the second's prompt,
        # so a name would match both.
        provider=FakeLlmProvider(
            by_substring={"Bletchley": ADA_AND_TURING}, default=TWO_PEOPLE
        ),
    )

    await adapter.ingest(SourceRef(source_id="first", text=TEXT))
    await adapter.ingest(SourceRef(source_id="second", text=SECOND_TEXT))

    entities = await _ids_by_name(adapter, project_id)
    survivor = entities["Ada Lovelace"]
    absorbed = entities["Ada A. Lovelace"]
    turing = entities["Alan Turing"]
    await adapter.merge_entities(
        canonical=survivor, absorbed=[absorbed], reason="one person, two spellings"
    )

    canonical = [survivor, entities["Charles Babbage"], turing]
    reader = RecordedCoMentions(co_mentions, project_id, adapter._store)
    passages = await reader.passages([str(e) for e in canonical])

    assert frozenset({str(survivor), str(turing)}) in passages, (
        "the second document's passage names the absorbed spelling of Ada and "
        "Alan Turing; resolved through the merge it is a co-mention of the "
        "survivor, and unresolved it vanishes entirely"
    )


# ---------------------------------------------------------------------------
# `ChunkCoMentions` alone, against a real store rather than a stub.
#
# The class had no test at all until this file: `tests/application/
# test_curriculum.py` drives a stub `CoMentionPort` and
# `tests/application/test_area_projection.py` drives literal `frozenset`s, so
# the port and its only adapter were each verified alone.
# ---------------------------------------------------------------------------


def _seeded(passages: dict[int, list[UUID]]) -> CoMentionIndex:
    """An index holding one document's passages, by position.

    Seeded through `replace_source` -- the same call the projection makes --
    rather than by reaching into the instance, so a change to how the model
    stores what it is told cannot make these tests pass against a projection
    that no longer works.
    """
    index = CoMentionIndex()
    index.replace_source("doc", passages)
    return index


@pytest.mark.asyncio
async def test_a_passage_naming_one_known_entity_is_not_a_co_mention():
    """A single-name passage contributes nothing, and is not an empty frozenset.

    *Fails against:* dropping the `len(named) >= 2` guard. That variant returns
    a one-member frozenset per passage, which `_co_mention_edges` skips at its
    own `len(members) < 2` check -- so the projection's answer is unchanged and
    nothing downstream can catch it. The count on the projection
    (`co_mention_count`) is the only visible difference, and it is what a
    reader is shown as "N shared passages".

    **Proved red on 2026-08-22** by changing the guard to `len(named) >= 1`.
    See BREAK E in the table at the foot of this file.
    """
    alone, elsewhere = uuid4(), uuid4()
    index = _seeded({0: [alone]})

    reader = RecordedCoMentions(index, uuid4(), InMemoryGraphStore())
    passages = await reader.passages([str(alone), str(elsewhere)])

    assert passages == [], (
        "a passage naming one of the wanted entities licenses no pair, so it "
        "must not be reported as a shared passage"
    )


@pytest.mark.asyncio
async def test_one_passage_reached_through_six_entities_is_counted_once():
    """Reaching a passage once per entity must not weight it by its own length.

    The index answers per entity and has no enumeration -- the shape
    `ChunkStore.get_by_entity` fixed and this model kept, because the caller
    only ever wants the passages of entities the graph read returned. So a
    paragraph naming six entities comes back six times. Counting all six would
    weight it by its entity count: precisely the bias `CO_MENTION_BUDGET`'s
    normalisation exists to remove, reintroduced upstream of the normalisation
    where it cannot be seen.

    *Fails against:* one frozenset per arrival, which is the shape the loop
    falls into without the `seen` dict.

    **A note on the break, because the obvious one proves nothing.** Deleting
    `if key in seen: continue` leaves the behaviour unchanged -- `seen` is a
    dict and the loop overwrites the same key. That line is an early exit, not
    the mechanism. The break that works is keying on the entity the passage was
    reached through; see BREAK F in the table at the foot of this file.
    """
    six = [uuid4() for _ in range(6)]
    index = _seeded({0: six})

    reader = RecordedCoMentions(index, uuid4(), InMemoryGraphStore())
    passages = await reader.passages([str(e) for e in six])

    assert passages == [frozenset(str(e) for e in six)], (
        "six lookups of one paragraph are one passage; six copies of it would "
        "make a long passage six voices instead of one"
    )


@pytest.mark.asyncio
async def test_a_repeated_passage_is_two_voices_and_not_one():
    """Two positions holding the same names are two passages.

    The companion to the test above, and the reason this model is keyed by
    position where the corpus is keyed by content. `StoredChunk.id` hashes
    `(source_id, text)`, so a document that repeats a passage verbatim has one
    chunk id for two positions and `upsert_many` of both leaves the corpus
    holding one -- measured on 2026-08-22. Keying this model the same way would
    inherit that, and a document that says the same thing twice really has said
    it twice.

    *Fails against:* keying the index, or the reader's dedup, on anything
    derived from the passage's content rather than on `(source_id, index)`.

    **Proved red on 2026-08-22** by keying `CoMentionIndex._by_source` on
    `frozenset(ids)` instead of `chunk_index`. See BREAK G.
    """
    pair = [uuid4(), uuid4()]
    index = _seeded({0: pair, 1: pair})

    reader = RecordedCoMentions(index, uuid4(), InMemoryGraphStore())
    passages = await reader.passages([str(e) for e in pair])

    assert len(passages) == 2, (
        "a passage repeated at two positions is two voices; collapsing them "
        "halves the weight the pair earned"
    )


@pytest.mark.asyncio
async def test_entities_outside_the_graph_read_are_dropped_from_the_pair_count():
    """A passage is narrowed to the wanted entities here, not downstream.

    The graph read truncates, so a passage may name entities the projection
    will never see. `_co_mention_edges` divides `CO_MENTION_BUDGET` by the
    passage's pair count, so leaving the unwanted names in inflates the divisor
    and weakens every real pair in proportion to how much of the graph was cut.

    *Fails against:* intersecting downstream in `_co_mention_edges` instead --
    which reads as equivalent, because that function also intersects against
    `known`. It is not: by then the frozenset that was divided by is already
    the wrong size. The class's docstring has always claimed this and nothing
    tested it.

    **Proved red on 2026-08-22**; see BREAK H.
    """
    wanted = [uuid4(), uuid4()]
    stranger = uuid4()
    index = _seeded({0: [*wanted, stranger]})

    reader = RecordedCoMentions(index, uuid4(), InMemoryGraphStore())
    passages = await reader.passages([str(e) for e in wanted])

    assert passages == [frozenset(str(e) for e in wanted)], (
        "the stranger is one the graph read did not return; counting it makes "
        "the passage three pairs instead of one and thirds every real edge"
    )


@pytest.mark.asyncio
async def test_a_curriculum_built_over_a_real_ingest_counts_shared_passages(
    build_adapter, tmp_path
):
    """The port and its adapter, meeting for the first time.

    The spec asked instead for an addition to `tests/application/
    test_area_projection.py` proving the projection changes when passages are
    added. That test already exists as
    `test_co_mention_alone_can_form_an_area`, which forms two areas out of six
    entities and no relationships -- `project_areas` demonstrably reads its
    `passages` argument, and always did. The dead channel was never there.

    It was one level up: `CurriculumService` fetches passages from a
    `CoMentionPort`, and the only adapter of that port was pointed at a corpus
    whose chunks carry no entity links. So this drives the real
    `CurriculumService` over the real `ChunkCoMentions` over a store a real
    `ingest` filled, and asserts the count it reports -- which is the number
    `DerivedFromLine` prints as "*N* shared passages" and which was 0 on every
    projection since the feature shipped.

    The contrast arm is the same service over an **empty** index, which is
    what every project ingested before this change has and what the shipped
    build effectively had: `docs/design/co-mention-channel-findings.md`
    measured 0 passages returned and a projection byte-identical with and
    without them. Two arms rather than one absolute number because the count
    depends on the fixture's chunking, and an assertion on a specific integer
    would be a test of `extraction_chunk_size`.

    The shipped wiring can no longer be written down here: `RecordedCoMentions`
    takes a `CoMentionIndex`, and the retrieval corpus is not one. That is the
    point of the type -- the mistake that produced this defect was handing the
    reader a store whose chunks have no links, and it is now a `TypeError`
    rather than a plausible 200.

    **Proved red on 2026-08-22**; see BREAK C, which takes this test with it.
    """
    project_id = uuid4()
    chunks, co_mentions = _stores()
    adapter, _, _ = build_adapter(tmp_path, project_id, chunks=chunks, co_mentions=co_mentions)
    await adapter.ingest(SourceRef(source_id="notes", text=TEXT))

    reader = ProjectGraphReader(project_id=project_id, store=adapter._store)
    live = await CurriculumService().build(
        project_id, reader, RecordedCoMentions(co_mentions, project_id, adapter._store)
    )
    dead = await CurriculumService().build(
        project_id, reader, RecordedCoMentions(CoMentionIndex(), project_id, adapter._store)
    )

    assert live.projection.co_mention_count > 0, (
        "an ingest of a document naming two entities in one passage is one "
        "shared passage; zero here is the channel not running"
    )
    assert dead.projection.co_mention_count == 0, (
        "an index nothing folded reports zero, which is what every projection "
        "since the feature shipped reported"
    )


# ---------------------------------------------------------------------------
# The breaks these tests were proved red against, on 2026-08-22.
#
# Each was applied to the working tree, the named files run, and the tree
# restored from a saved copy -- not with `git checkout`, which would have
# discarded the rest of the uncommitted change. Counts are over the files
# listed, not over the suite.
#
#   A  `carries_entity_links` returns True unconditionally
#      -> 1 failed, 9 passed. Only the re-index test. The rebuild test stays
#         green: with no re-index on the log, extraction's chunking is simply
#         the last one and an unfiltered fold lands on the right answer.
#
#   B  no `event_store=` on the `build_graph` call
#      -> 14 failed, 61 passed over this file, test_durable_vectors.py and
#         test_redstring_adapter.py. Six here; the adapter failures are the
#         document stream losing its `DocumentChunked` entirely, which the
#         changed-text refusal also depends on.
#
#   C  `ingest` does not call `_apply_co_mentions`
#      -> 4 failed, 6 passed. The live half alone. `test_co_mentions_survive_a
#         _rebuild` stays green, which is the pair worth understanding: the log
#         is correct and the session's own index is empty.
#
#   D  `chunks=self._chunks` passed to `build_graph` (the smallest-diff design)
#      -> 1 failed, 9 passed: `test_the_retrieval_corpus_keeps_its_own_chunking`
#         alone. Every co-mention assertion passes, which is exactly why that
#         test exists.
#
#   E  co-mention guard relaxed to `len(named) >= 1`
#      -> 1 failed, 9 passed.
#
#   F  passage dedup keyed by the entity it was reached through
#      -> 3 failed, 7 passed. Deleting `if key in seen: continue` instead
#         proves nothing -- `seen` is a dict and the loop overwrites.
#
#   G  `CoMentionIndex` keyed by content instead of by position
#      -> 1 failed, 9 passed: the repeated-passage test alone.
#
#   H  passage not narrowed to the wanted entities
#      -> 2 failed, 8 passed. The consolidation test goes with it, because the
#         same expression maps an absorbed id onto its survivor.
#
#   I  no alias walk; the index asked under canonical ids alone
#      -> 1 failed, 9 passed: the consolidation test alone.
#
# Elsewhere, against the same change:
#
#   J  `_record_embeddings` loses its document half
#      -> 2 failed, 5 passed in test_durable_vectors.py.
#   K  the embedding pair passed back to `build_graph`
#      -> 1 failed, 6 passed: the endpoint-death test, which cannot pass under
#         that arrangement.
#   L  changed text falls through to a zero report
#      -> 2 failed, 56 passed in test_redstring_adapter.py.
#   M  refuse whenever `record_extraction` refuses, ignoring the signatures
#      -> 3 failed, 55 passed. Every ordinary re-ingest.
#   N  `close()` forgets the index      -> 1 failed, 19 passed.
#   O  the index built unconditionally  -> 12 failed, 8 passed.
# ---------------------------------------------------------------------------
