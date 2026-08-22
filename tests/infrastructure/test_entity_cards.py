"""Assembling an entity card, which is a document written to be retrieved.

A card is never shown to a reader -- `test_entity_card_index.py` covers the
store that keeps it apart from the quotable corpus -- so everything here is
judged by whether BM25 can find the entity from a description of it.
"""

from research_team.infrastructure.knowledge.entity_cards import Neighbour, card_text


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
