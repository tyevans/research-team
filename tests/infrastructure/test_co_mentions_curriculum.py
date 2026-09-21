"""Curriculum co-mention passage counting and voice aggregation tests.

Extracted from tests/infrastructure/test_co_mentions.py. Covers ChunkCoMentions
passage counting, single-name non-co-mention checks, passage deduplication,
entity filtering, and end-to-end CurriculumService shared passage counting.
"""

from uuid import UUID, uuid4

import pytest
from redstring import InMemoryChunkStore, InMemoryGraphStore

from research_team.application.curriculum import CurriculumService
from research_team.application.knowledge import SourceRef
from research_team.infrastructure.knowledge.co_mention_reader import RecordedCoMentions
from research_team.infrastructure.knowledge.co_mentions import CoMentionIndex
from research_team.infrastructure.knowledge.graph_reader import ProjectGraphReader

DIMENSION = 8

TEXT = "Ada Lovelace worked with Charles Babbage on the Analytical Engine. " * 24


def _stores() -> tuple[InMemoryChunkStore, CoMentionIndex]:
    """A real retrieval corpus and a real co-mention index.

    Two different kinds of thing, deliberately: the corpus holds passages, the
    index holds three fields per passage. `infrastructure/knowledge/co_mentions.py`
    records why the second is not a second corpus.
    """
    return InMemoryChunkStore(dimension=DIMENSION), CoMentionIndex()


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
