"""Assembling an entity card, which is a document written to be retrieved.

A card is never shown to a reader -- `test_entity_card_index.py` covers the
store that keeps it apart from the quotable corpus -- so everything here is
judged by whether BM25 can find the entity from a description of it.
"""

from uuid import uuid4

import pytest
from redstring import InMemoryChunkStore, SlidingWindowChunker, rank_chunks, tokenize

from research_team.application.knowledge import SourceRef
from research_team.infrastructure.knowledge.entity_cards import (
    Neighbour,
    card_text,
    index_cards,
)


def test_a_card_names_its_neighbours_and_their_relationship():
    """The relations block is the whole point of a card.

    stark-bench measured adding neighbour names to an indexed document at +22%
    lexical and +44% hybrid, and the mechanism it found is why the edge *type*
    is here too: queries name related entities verbatim, BM25 matches those
    names directly, and a single dense vector compresses them away. `acquired`
    against `subsidiary_of` is what makes two neighbours distinguishable at the
    same token cost.
    """
    text = card_text(
        name="Acme Corporation",
        entity_type="Organization",
        aliases=["Acme", "Acme Corp."],
        properties={"founded": "1987"},
        neighbours=[
            Neighbour(relationship_type="acquired", name="Blackwell Systems", outgoing=True),
            Neighbour(
                relationship_type="subsidiary_of", name="Vantage Holdings", outgoing=True
            ),
        ],
    )

    assert "Acme Corporation" in text
    assert "Organization" in text
    assert "Acme Corp." in text
    assert "founded" in text and "1987" in text
    assert "acquired" in text and "Blackwell Systems" in text
    assert "subsidiary_of" in text and "Vantage Holdings" in text


def test_a_card_for_an_entity_with_no_neighbours_is_still_a_card():
    """The input that separates a correct assembler from a plausible one.

    A well-connected entity is what anyone would write down, and every
    candidate implementation handles it. An isolated entity is where a template
    that unconditionally emits a `- relations:` header leaves a heading with
    nothing under it -- which costs a real BM25 term on every card in the
    corpus, so it is not merely untidy.

    Most entities in a real graph are leaves, so this is the ordinary case
    rather than the edge one.
    """
    text = card_text(
        name="Lone Entity",
        entity_type="Concept",
        aliases=[],
        properties={},
        neighbours=[],
    )

    assert "Lone Entity" in text
    assert "Concept" in text
    assert "relations" not in text.lower()
    assert "also known as" not in text.lower()


def test_an_incoming_edge_reads_from_the_other_end():
    """Direction is kept, because reversing it changes what the card claims.

    `Blackwell Systems acquired Acme` and `Acme acquired Blackwell Systems` are
    different facts, and a card that flattens both to "acquired Blackwell
    Systems" makes the graph's own direction unrecoverable from the text a
    reader-facing answer is built on.
    """
    text = card_text(
        name="Blackwell Systems",
        entity_type="Organization",
        aliases=[],
        properties={},
        neighbours=[Neighbour("acquired", "Acme Corporation", outgoing=False)],
    )

    assert "Acme Corporation" in text
    assert "acquired by" in text


def test_a_property_whose_value_is_not_a_string_still_reaches_the_text():
    """redstring's `Entity.properties` is `dict[str, Any]`, and extraction puts
    numbers, lists and nested dicts in it -- the domain-schema properties
    (`outcome`, `role`, `creator`, `definition`) land there alongside whatever
    else a model returned. A card that only emitted `str` values would drop
    them silently, which is the failure this whole design is trying not to
    repeat.
    """
    text = card_text(
        name="Some Event",
        entity_type="Event",
        aliases=[],
        properties={"year": 1987, "tags": ["merger", "tech"]},
        neighbours=[],
    )

    assert "1987" in text
    assert "merger" in text


@pytest.mark.asyncio
async def test_an_entity_is_found_by_a_neighbour_name(tmp_path, build_adapter):
    """A query naming only a neighbour finds the entity. The whole of Stage B.

    `Charles Babbage` is nowhere in the string `Ada Lovelace`, so no channel
    `search` has can answer this: the substring pass tests containment in the
    name and the blocking-key pass hashes a prefix and a soundex of it. The
    edge between them is in the graph, and this is what puts it in the index.
    """
    project_id = uuid4()
    adapter, _, _ = build_adapter(tmp_path, project_id)
    await adapter.ingest(
        SourceRef(source_id="notes", text="Ada Lovelace worked with Charles Babbage.")
    )
    cards = InMemoryChunkStore(dimension=8)

    carded = await index_cards(
        graph=adapter._store, cards=cards, tenant_id=project_id, chunker=SlidingWindowChunker()
    )

    assert carded == 2, "every entity gets a card, not only ones with edges"

    terms = tokenize("Charles Babbage")
    ranked = rank_chunks(terms, await cards.lexical_candidates(terms, project_id, 10), 10)
    named = {chunk.chunk.text.splitlines()[0] for chunk in ranked}

    assert any("Ada Lovelace" in first_line for first_line in named), (
        "Ada's card must name Babbage -- that edge is the only thing linking them"
    )


@pytest.mark.asyncio
async def test_a_card_chunk_carries_the_entity_it_describes(tmp_path, build_adapter):
    """`entity_ids` on the chunk, so a hit resolves without parsing a card.

    The alternative is reading the name back off the card's first line, which
    would make retrieval depend on the text format `card_text` happens to emit
    -- and would break on the first entity whose name contains a newline.
    """
    project_id = uuid4()
    adapter, _, _ = build_adapter(tmp_path, project_id)
    await adapter.ingest(
        SourceRef(source_id="notes", text="Ada Lovelace worked with Charles Babbage.")
    )
    cards = InMemoryChunkStore(dimension=8)

    await index_cards(
        graph=adapter._store, cards=cards, tenant_id=project_id, chunker=SlidingWindowChunker()
    )

    terms = tokenize("Charles Babbage")
    ranked = list(
        rank_chunks(terms, await cards.lexical_candidates(terms, project_id, 10), 10)
    )

    assert ranked
    assert all(chunk.chunk.entity_ids for chunk in ranked), (
        "every card chunk names the entity it describes"
    )


@pytest.mark.asyncio
async def test_re_indexing_replaces_a_card_rather_than_adding_one(tmp_path, build_adapter):
    """Cards are rebuilt at every project open, so this runs constantly.

    Source ids are derived from the entity id, which is what makes
    `replace_source` land on the right rows. Get that wrong -- a random id, or
    one derived from the card's text -- and every open doubles the corpus while
    every individual query still looks correct.
    """
    project_id = uuid4()
    adapter, _, _ = build_adapter(tmp_path, project_id)
    await adapter.ingest(
        SourceRef(source_id="notes", text="Ada Lovelace worked with Charles Babbage.")
    )
    cards = InMemoryChunkStore(dimension=8)

    for _ in range(3):
        await index_cards(
            graph=adapter._store,
            cards=cards,
            tenant_id=project_id,
            chunker=SlidingWindowChunker(),
        )

    terms = tokenize("Charles Babbage")
    found = (await cards.lexical_candidates(terms, project_id, 50)).candidates

    ids = {candidate.chunk.id for candidate in found}
    assert len(found) == len(ids), "duplicate chunk rows"
    assert len(found) <= 2, f"three indexings produced {len(found)} chunks"
