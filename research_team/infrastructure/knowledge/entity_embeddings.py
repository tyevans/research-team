"""Embedding a project's entities, durably and on what they mean.

Two things were wrong with the embeddings this system produced before this
module existed, and they compound: **they did not survive a restart, and they
encoded only the entity's name.**

## They did not survive a restart

redstring embeds inside `build_graph`, folds the result into a `VectorStore`
through `VectorProjection`, and hands the caller a *count* --
`GraphBuildReport.embedded` -- rather than the `EntitiesEmbedded` event it
built. The event is appended only when `build_graph` is given an
`event_store`, and this system did not give it one: it appended
`built.event` (the `DocumentExtracted`) by hand and let the rest go.

So every vector this project ever computed was written into an in-memory store
and dropped when the process ended. Nothing on the log could replay them.
Measured on 2026-08-22 against a copy of the real database: **zero
`EntitiesEmbedded` rows in a log holding 8 `DocumentExtracted` and 772
`EntitiesMerged`.** Embeddings have been on by default the whole time. Every
one of them was thrown away.

The fix is that this module builds the event and the caller appends it, so
`rebuild_graph` can fold it back at project open exactly as it folds the graph
and the corpus. See `rebuild.py` for the replay half and for why it filters on
the embedding model.

## They encoded only the name

`build_graph` embeds `[entity.name for entity in entities]`. That is fine for
what redstring uses vectors for -- `CandidateFinder` asking whether two
entities are the *same* entity, where the name is most of the evidence -- and
poor for asking what an entity is *about*, which is what clustering a
curriculum out of a graph needs.

**This is not the same as saying a name embedding is a string comparison.** An
earlier version of this project's design documents claimed exactly that, and it
was nonsense: embeddings encode meaning, which is the entire reason they
exist. `glass` and `cup` share no substring and sit close together in any
competent embedding space. The real objection to embedding the bare name is
narrower and survives: a name is *thin*. Two entities can be about the same
subject under names that are unrelated in any space, and one name in isolation
carries none of the type, the properties or the neighbourhood that would say
so.

So this embeds the entity's **card** -- the same text `entity_cards` builds for
BM25 to match, carrying name, type, properties and the named relations -- and
`assemble_cards` is shared rather than reimplemented, so the text a query
matches lexically and the text a vector encodes cannot drift apart.

What that costs: a card is longer than a name, so each embedding call sends
more tokens, and a card is truncated by the model's own input limit rather than
by anything here. It buys a vector that moves with the entity's subject matter
instead of its spelling.

## What it does not do

It does not re-embed at project open. `rebuild_graph`'s docstring is explicit
that a model call on the open path would make a session refolded years from now
depend on a live endpoint, and that rule is worth more than fresher vectors. A
vector therefore encodes the neighbourhood the entity had **when it was
extracted**, which for an early entity is thinner than its card today. The
answer to that is re-embedding on request -- `POST /projects/{id}/embeddings` --
not a model call on a replay path.
"""

import logging
from collections.abc import Sequence
from uuid import UUID

from eventsource.ports.positions import ExpectedVersion
from eventsource.ports.store import AggregateStore
from redstring import (
    EmbeddingProvider,
    EntitiesEmbedded,
    GraphStore,
    RedstringError,
    VectorRecord,
)
from redstring.aggregates.document import Document
from redstring.events.streams import document_stream
from redstring.ports.vector_store import VectorReader, VectorWriter

from research_team.application.knowledge import KnowledgeError
from research_team.infrastructure.knowledge.entity_cards import Card, assemble_cards

logger = logging.getLogger(__name__)

#: The synthetic source id the whole-project embedding pass records against.
#:
#: Embeddings here are keyed by entity and assembled from the *whole* graph, so
#: they do not belong to any one document the way `DocumentExtracted` does --
#: but `EntitiesEmbedded` carries a `source_id` because redstring's aggregate is
#: per document. A fixed synthetic id gives the pass its own stream, which is
#: what makes `Document.record_embeddings`'s repeat-refusal apply to *this*
#: pass rather than to whichever document happened to be ingested last.
#:
#: The consequence to know: because the aggregate refuses a second event for a
#: model it has already seen, a re-embed under an unchanged model is a no-op
#: unless the aggregate is fresh. `embed_entities` builds a fresh one per call
#: -- the shape `build_graph` has -- so re-embedding always re-emits, and the
#: projection absorbs it because `upsert_many` is last-write-wins.
PROJECT_EMBEDDING_SOURCE = "entities:project"

#: How many card texts go in one `embed` call.
#:
#: Cards are far longer than the bare names redstring batched, and an
#: embedding endpoint's request limit is on total tokens rather than on the
#: number of strings -- so the batch that worked for names is the batch that
#: 413s for cards. Sized down accordingly rather than tuned: nothing here has
#: been measured against a real server, and the failure it avoids is a whole
#: pass lost to one oversized request.
EMBED_BATCH = 64


async def embed_entities(
    *,
    graph: GraphStore,
    provider: EmbeddingProvider,
    tenant_id: UUID,
    only: set[UUID] | None = None,
    cards: Sequence[Card] | None = None,
) -> EntitiesEmbedded | None:
    """Embed every canonical entity's card. Returns the event, unappended.

    Unappended for `build_graph`'s reason: the caller owns the event store and
    the stream, and returning the event lets the append and the projection stay
    in the caller's transaction-shaped block rather than being done twice from
    two places.

    `None` when the graph has no canonical entities, which is the ordinary
    outcome for a project nothing has been ingested into yet. It is not an
    error and the caller should not log it.

    `only` narrows the pass to those entity ids; see `assemble_cards`. The
    ingest path passes the entities one document produced, so its cost stays
    proportional to the document rather than to the graph -- a whole-project
    re-embed on every ingest is the shape that makes the tenth document cost
    more than the first nine together. The re-embed route leaves it `None`.

    `cards` is an escape hatch for a caller that has already assembled them.
    Left `None`, this assembles its own.

    **Raises nothing on a short reply.** A provider returning fewer vectors
    than texts is a real failure mode (redstring raises `EmbeddingProviderError`
    on it) and it is *not* treated as one here, because this runs inside a pass
    over batches: one short batch would otherwise discard every batch before
    it. The short batch is dropped with a warning and the rest are kept, which
    leaves some entities unembedded -- visible as a lower count than the graph
    has entities, and repairable by running the pass again.
    """
    assembled = (
        list(cards)
        if cards is not None
        else await assemble_cards(graph=graph, tenant_id=tenant_id, only=only)
    )
    if not assembled:
        return None

    records: list[VectorRecord] = []
    for start in range(0, len(assembled), EMBED_BATCH):
        batch = assembled[start : start + EMBED_BATCH]
        vectors = await provider.embed([card.text for card in batch])
        if len(vectors) != len(batch):
            logger.warning(
                "embedding provider %s returned %d vectors for %d cards; "
                "results are positional, so this batch is dropped rather than "
                "matched to the wrong entities",
                provider.model,
                len(vectors),
                len(batch),
            )
            continue
        records.extend(
            VectorRecord(entity_id=card.entity_id, tenant_id=tenant_id, vector=vector)
            for card, vector in zip(batch, vectors, strict=True)
        )

    if not records:
        return None

    stream = document_stream(tenant_id=tenant_id, source_id=PROJECT_EMBEDDING_SOURCE)
    return Document(stream.aggregate_id).record_embeddings(
        tenant_id=tenant_id,
        source_id=PROJECT_EMBEDDING_SOURCE,
        embedding_model=provider.model,
        embeddings=records,
    )


async def recover_document_embeddings(
    *,
    vectors: "VectorReader",
    entity_ids: Sequence[UUID],
    tenant_id: UUID,
    source_id: str,
    embedding_model: str,
) -> EntitiesEmbedded | None:
    """The `EntitiesEmbedded` `build_graph` built and did not hand back.

    **Read back rather than recomputed.** `build_graph` embeds each entity's
    name, folds the vectors into the `VectorStore` through `VectorProjection`,
    and returns `GraphBuildReport.embedded` -- an integer. The event itself is
    reachable only by giving `build_graph` an `event_store`, which would also
    have it append a `DocumentChunked` carrying the document's full text under
    the *extraction* chunking. That is not free here: this system already
    chunks through `index_documents` under the same source id, `replace_source`
    is last-write-wins, and whichever chunking replayed last would own the
    corpus every citation is checked against. Two chunkings competing for one
    source is a worse problem than the one being solved.

    So the vectors are fetched back out of the store `build_graph` just wrote
    them to, by the ids it just wrote. That is exact rather than approximate --
    the port guarantees `get` returns what was upserted -- and it costs one
    lookup per entity against a store that is in memory on every install this
    ships with.

    The cost worth naming: the vectors are float32 in the store (the port says
    so), so the recovered event carries single-precision values even if the
    provider returned double. Nothing compares a stored vector to a written one
    for equality, and cosine at float32 is what every adapter computes anyway.

    `None` when nothing was embedded -- embeddings off, the endpoint probe
    failed, or the extraction produced no entities. Not an error in any of
    those cases.
    """
    records: list[VectorRecord] = []
    for entity_id in entity_ids:
        stored = await vectors.get(entity_id, tenant_id)
        if stored is not None:
            records.append(stored)

    if not records:
        return None

    stream = document_stream(tenant_id=tenant_id, source_id=source_id)
    return Document(stream.aggregate_id).record_embeddings(
        tenant_id=tenant_id,
        source_id=source_id,
        embedding_model=embedding_model,
        embeddings=records,
    )


async def refresh_project_embeddings(
    *,
    graph: GraphStore,
    provider: EmbeddingProvider,
    event_store: "AggregateStore",
    vectors: "VectorWriter",
    tenant_id: UUID,
) -> int:
    """Re-embed a whole project and record the result. Returns how many.

    The engine behind `POST /projects/{id}/embeddings`. It lives here rather
    than in the composition root so that the append and the stream id stay
    beside the event that needs them -- composition would otherwise have to
    import redstring's `document_stream` and `ExpectedVersion` to do one thing
    this module already knows how to do.

    **The append happens before the upsert**, and the order is the recoverable
    one. An event on the log with no vectors in the store is corrected by the
    next project open, which folds it. Vectors in the store with no event is
    a store holding values the log cannot reproduce, which is precisely the
    state this module exists to end.

    `ExpectedVersion.any_()` for the reason the ingest path uses it: this
    stream is append-only and nothing reads its version to make a decision, so
    an optimistic check would refuse concurrent re-embeds of one project
    without protecting anything. Two concurrent runs produce two events, and
    `upsert_many` is last-write-wins, so the store ends up holding one of the
    two complete answers rather than a mixture.

    0 when there was nothing to embed. Not an error; see `embed_entities`.
    """
    try:
        event = await embed_entities(graph=graph, provider=provider, tenant_id=tenant_id)
    except RedstringError as error:
        # Translated at the layer boundary rather than allowed out as
        # redstring's own type: `tests/test_architecture.py` keeps redstring
        # names inside this package, so a web route catching
        # `EmbeddingProviderError` would have to import one. The distinction the
        # route needs -- upstream is down, as against nothing to do -- survives
        # the translation because this raises and "nothing to do" returns 0.
        raise KnowledgeError(f"could not embed this project's entities: {error}") from error
    if event is None:
        return 0
    await event_store.append(
        document_stream(tenant_id=tenant_id, source_id=PROJECT_EMBEDDING_SOURCE),
        [event],
        ExpectedVersion.any_(),
    )
    await vectors.upsert_many(event.embeddings)
    return len(event.embeddings)
