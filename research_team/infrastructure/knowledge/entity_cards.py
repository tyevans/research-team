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
