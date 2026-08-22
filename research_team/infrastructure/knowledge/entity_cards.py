"""A synthetic document per entity, written to be retrieved rather than read.

**What this is for.** Entity lookup matches names: `RedstringKnowledge.search`
tests substrings and asks `redstring.Retriever` for blocking keys over the
name, and both channels are blind to what an entity *is*. A card gives BM25
something to match when the query describes the entity instead of spelling it
-- "the company that acquired Blackwell Systems" names no part of "Acme
Corporation".

**The relations block is the payload, and the evidence is external.** The
stark-bench campaign of 2026-08-19/21 measured two arms differing only in
whether the indexed document named the node's neighbours: dense +0.016,
lexical +0.044 (+22%), hybrid +0.085 (+44%). Nearly all of the gain arrived
through the lexical channel, and the mechanism is why: the benchmark's queries
name related entities verbatim, those names appear in the answer's own
document only in the relations version, BM25 matches them directly, and a
single dense vector compresses them away.

The corollary that shaped this module rather than a graph walk: **edges are
worth more as text in the index than as a traversal at query time.** That
campaign's agentic arm, which traversed at query time, cost ~7.46 model calls
per query and was the worst arm it measured.

Those numbers are for a different corpus and a different embedder. The
direction is what transfers; do not quote the magnitudes as a prediction here.

**A card is never quoted to a reader.** `application/entity_definitions.py`
enforces that every citation is `(source_id, start, end)` into a real
document, because a claim a reader cannot check against the source is the one
failure that module exists to prevent -- and a card is text no source
contains. Nothing here can enforce that; the card index is a separate store
from the quotable corpus, which is what makes a card unreachable from
`UsageReader` rather than merely undocumented.

**No model call.** A card is an assembly of graph state. That is why cards are
derived at project open rather than event-sourced: they hold no information
the graph does not, so persisting them would buy nothing and cost staleness.
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING
from uuid import UUID, uuid5

from redstring import StoredChunk

if TYPE_CHECKING:
    from redstring import Chunker
    from redstring.ports.chunk_store import ChunkWriter
    from redstring.ports.graph_store import GraphStore

#: What separates an edge's type from the neighbour it points at. Two spaces
#: rather than a colon or an arrow: `tokenize` splits on non-word characters,
#: so any punctuation here is dropped before BM25 sees the line and would only
#: mislead a person reading the raw card.
_GAP = "  "


@dataclass(frozen=True)
class Neighbour:
    """One edge, from the point of view of the entity whose card this is.

    `outgoing` is kept rather than normalised away because reversing an edge
    changes what the card asserts: "Acme acquired Blackwell" and "Blackwell
    acquired Acme" are different facts, and a card that flattened both to
    `acquired Blackwell` would make the graph's own direction unrecoverable
    from the text.
    """

    relationship_type: str
    name: str
    outgoing: bool


def card_text(
    *,
    name: str,
    entity_type: str,
    aliases: Sequence[str],
    properties: Mapping[str, object],
    neighbours: Sequence[Neighbour],
) -> str:
    """This entity as a document BM25 can match a description against.

    **Every section is omitted when its input is empty**, and that is
    load-bearing rather than tidy. A `- relations:` heading emitted over an
    empty list puts the term `relations` on every card in the corpus, where it
    matches nothing anyone would search for and dilutes the length
    normalisation that makes short cards rank well in the first place. Most
    entities in a real graph are leaves, so the empty case is the common one.

    Property values are stringified rather than filtered to `str`.
    `Entity.properties` is `dict[str, Any]` and extraction fills it with
    numbers, lists and nested dicts -- a domain schema's declared per-type
    properties all land there. Dropping non-strings would lose them silently,
    which is the exact shape of the defect that cost this project its temporal
    extraction (see `CLAUDE.md`'s Extraction section): a field that is optional
    in the schema and absent in practice looks identical to one the model
    declined to fill.
    """
    lines = [f"{name}{_GAP}({entity_type})"]

    if aliases:
        lines.append(f"also known as: {', '.join(aliases)}")

    lines.extend(f"{key}: {value}" for key, value in properties.items())

    if neighbours:
        lines.append("")
        lines.append("- relations:")
        for edge in neighbours:
            # `X by` for an incoming edge, so the line reads from this
            # entity's side. See `Neighbour.outgoing`.
            verb = edge.relationship_type if edge.outgoing else f"{edge.relationship_type} by"
            lines.append(f"{_GAP}{verb}{_GAP}{edge.name}")

    return "\n".join(lines)


#: The namespace `card_source_id` derives from. Fixed and arbitrary: what
#: matters is only that it is stable across runs, so `replace_source` lands on
#: the rows a previous indexing wrote.
_CARD_NAMESPACE = UUID("6f9b4c1e-0d3a-4f8b-9a21-2c7e5d8b4a60")


def card_source_id(entity_id: UUID) -> str:
    """The synthetic source a card is stored under.

    **Derived, never chosen.** `replace_source` is what keeps re-indexing from
    doubling the corpus, and it can only do that if the same entity resolves to
    the same source every time. A random id, or one derived from the card's
    *text*, would leave the previous card behind on every change -- and every
    individual query would still look correct, because the stale card is a
    truthful description of an older neighbourhood.
    """
    return f"card:{uuid5(_CARD_NAMESPACE, str(entity_id))}"


async def index_cards(
    *,
    graph: "GraphStore",
    cards: "ChunkWriter",
    tenant_id: UUID,
    chunker: "Chunker",
) -> int:
    """Write a card for every canonical entity in `tenant_id`. No model call.

    Returns how many entities were carded.

    **Absorbed entities are skipped**, the same way `RedstringKnowledge.search`
    skips them: a merge is not a delete, so `find_entities` still returns the
    absorbed row, and a card for it would compete in the same index as its
    canonical twin while describing a neighbourhood that has been redirected
    away. `undo_merge` restores the row, and the next indexing restores its
    card with it.

    **One relationship read for the whole tenant**, not one per entity. The
    per-entity shape is the obvious one and costs a round trip per node, which
    is invisible in a test with two entities and is the whole cost of this
    function on a real graph.

    Neighbour names come from a single `get_entities` over every endpoint seen,
    for the same reason. An endpoint with no entity behind it is skipped rather
    than rendered as an id: a card is matched by BM25, and a UUID in the text
    is a term no query will ever contain.
    """
    entities = await graph.find_entities(tenant_id)
    canonical = await graph.resolve_entity_ids([entity.id for entity in entities], tenant_id)
    # `==`, not `is`: an adapter may rebuild the UUID for an id that is not an
    # alias, and `is` would filter out everything and card nothing.
    own = [entity for entity in entities if canonical[entity.id] == entity.id]
    if not own:
        return 0

    ids = [entity.id for entity in own]
    edges = await graph.get_relationships_for(ids, tenant_id)

    endpoints = {edge.source_entity_id for edge in edges} | {
        edge.target_entity_id for edge in edges
    }
    names = {
        entity.id: entity.name
        for entity in await graph.get_entities(list(endpoints), tenant_id)
    }

    neighbours: dict[UUID, list[Neighbour]] = {entity_id: [] for entity_id in ids}
    for edge in edges:
        for near, far, outgoing in (
            (edge.source_entity_id, edge.target_entity_id, True),
            (edge.target_entity_id, edge.source_entity_id, False),
        ):
            if near in neighbours and far in names:
                neighbours[near].append(
                    Neighbour(
                        relationship_type=edge.relationship_type,
                        name=names[far],
                        outgoing=outgoing,
                    )
                )

    for entity in own:
        text = card_text(
            name=entity.name,
            entity_type=entity.entity_type,
            aliases=[],
            properties=entity.properties or {},
            neighbours=neighbours[entity.id],
        )
        source_id = card_source_id(entity.id)
        await cards.replace_source(
            source_id,
            tenant_id,
            [
                StoredChunk(
                    tenant_id=tenant_id,
                    source_id=source_id,
                    text=chunk.text,
                    chunk_index=chunk.chunk_index,
                    start_char=chunk.start_char,
                    end_char=chunk.end_char,
                    # So a hit resolves to its entity without parsing the card
                    # back out of its own text -- which would tie retrieval to
                    # `card_text`'s formatting and break on a name containing a
                    # newline.
                    entity_ids=[entity.id],
                )
                for chunk in chunker.chunk(text).chunks
            ],
        )

    return len(own)
