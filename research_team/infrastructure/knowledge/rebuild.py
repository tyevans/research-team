"""Rebuilding a project's graph from the log.

Runs at project open, which is what lets the default install keep the graph in
memory: the store is derived, so losing it costs a fold rather than data.

The two workarounds that used to live here -- R3 (no scoping, so the fold read
the whole log and dropped foreign events in Python) and R4 (a failed replay was
a count, so a partial graph came up silently and undiagnosably) -- are both
closed upstream. redstring 0.3.0 removed its own replay module in favour of
`eventsource.replay`, which takes `tenant_id` (pushed into the adapter's
`WHERE` clause) and `strict`, and whose failures name the offending event.
"""

import logging
from uuid import UUID

from eventsource import ReplayFailedError, replay
from eventsource.application.projections import StoreProjection, handles
from redstring import (
    ChunkProjection,
    ChunkStore,
    EntitiesEmbedded,
    GraphProjection,
    GraphStore,
)
from redstring.ports.vector_store import VectorWriter

from research_team.application.knowledge import KnowledgeError
from research_team.infrastructure.knowledge.entity_embeddings import (
    PROJECT_EMBEDDING_SOURCE,
)

logger = logging.getLogger(__name__)

#: redstring's own per-document embeddings, over `entity.name`. What
#: `CandidateFinder` scores with, and the channel whose numbers consolidation
#: was tuned against.
DOCUMENT_CHANNEL = "document"

#: This project's whole-graph embeddings, over an entity's *card*. What the
#: curriculum clusters on. See `entity_embeddings` for why the two are separate
#: rather than one richer vector serving both.
CARD_CHANNEL = "card"


class EmbeddingsForModel(StoreProjection[VectorWriter]):
    """Folds `EntitiesEmbedded` into a vector store, skipping other models.

    redstring ships `VectorProjection`, which applies every `EntitiesEmbedded`
    it is given. That is right for a library and wrong here, because this
    replay runs with `strict=True` on the path that opens a project: a store
    built for one model's width raises `DimensionMismatchError` on a vector of
    another, `strict` turns the first such event into a refusal, and the
    project stops opening at all.

    That is not hypothetical. A vector store's width is fixed at construction
    from `AGENT_EMBEDDING_DIMENSION`, and the log is permanent -- so changing
    the embedding model, which redstring's own port says means a new store
    rather than a widened one, would otherwise make every project that had
    ever been embedded unopenable, with a message about dimensions and nothing
    about what to do.

    Filtering on the model name rather than catching the error: the two are not
    the same test. Two models can share a width, and their vectors are not
    comparable at equal dimension -- redstring's `ports/vector_store.py` says
    so in as many words. Catching `DimensionMismatchError` would let exactly
    those through, which is the case that produces plausible nonsense instead
    of an error.

    The cost is that switching models silently empties the vector store until
    something re-embeds, so the skip is logged once per event rather than
    passed over in silence.

    **It also picks one of the two embedding channels.** Both are
    `EntitiesEmbedded` and they are told apart by `source_id`: the card pass
    records against the fixed synthetic `PROJECT_EMBEDDING_SOURCE`, and every
    per-document embedding against a real document's id. A store handed the
    wrong channel would be keyed by exactly the same entity ids and hold
    vectors of text nobody asked it to compare -- so it would answer every
    query, plausibly, with the wrong neighbours. That is why the split is
    enforced here rather than left to two callers to keep straight.
    """

    def __init__(self, store: VectorWriter, *, model: str, channel: str) -> None:
        super().__init__(store)
        self._model = model
        self._channel = channel

    @handles(EntitiesEmbedded)
    async def _apply_embeddings(self, _context: object, event: EntitiesEmbedded) -> None:
        # Not logged, unlike the model skip below: every event is offered to
        # both channels, so exactly one of them declines each one and a log
        # line here would be one per embedding event per open.
        if (event.source_id == PROJECT_EMBEDDING_SOURCE) != (self._channel == CARD_CHANNEL):
            return
        if event.embedding_model != self._model:
            logger.info(
                "skipping %d embeddings for model %r; this store holds %r",
                len(event.embeddings),
                event.embedding_model,
                self._model,
            )
            return
        await self._store.upsert_many(event.embeddings)

    async def _truncate_read_models(self) -> None:
        """Not supported; see redstring's `VectorProjection` for the reasoning."""
        raise NotImplementedError(
            "VectorStore has no cross-tenant delete by design; wipe with "
            "delete_by_tenant(tenant_id) for each tenant being rebuilt"
        )


async def rebuild_graph(
    store: GraphStore,
    *,
    feed,
    project_id: UUID,
    chunks: ChunkStore | None = None,
    vectors: VectorWriter | None = None,
    card_vectors: VectorWriter | None = None,
    embedding_model: str | None = None,
) -> int:
    """Fold this project's knowledge events into `store`. Returns events applied.

    Takes no provider, and must not grow one: extraction happens once, when the
    agent asks for it, and is replayed from the log thereafter. A model call on
    this path would mean a session refolded years from now depends on a live
    endpoint.

    `tenant_id` scopes the read rather than the delivery: redstring knows a
    research-team project only as a tenant, and this store is shared, so the
    alternative is reading every session event in the file and discarding it.
    research-team's own events carry no tenant and so are excluded by the same
    filter.

    `chunks` is keyword-only with a `None` default so no existing caller
    breaks. **A log holding `DocumentChunked` cannot fail to open just
    because `chunks` is omitted** -- `eventsource.replay` applies an event no
    projection handles rather than rejecting it (verified against
    `eventsource.application.projections.replay`'s docstring: "An event that
    every projection ignores still counts as applied -- it was delivered and
    nothing rejected it"). The failure mode of omitting `ChunkProjection` is
    therefore silent rather than loud: the corpus comes up empty, BM25
    returns nothing, and the UI says "no mentions found" -- the same sentence
    it truthfully says about an entity that has none. Nothing here can raise
    to catch that; it is why the corresponding test asserts retrieval, not
    that `rebuild_graph` merely returned.

    `vectors` is the same shape and the same warning applies twice over, because
    the embedding half of this fold is *newer than the logs it has to read*.
    Every event written before 2026-08-22 carries no `EntitiesEmbedded` at all
    -- the ingest path computed vectors and threw the event away, which is what
    `entity_embeddings` exists to correct -- so an old project folds to an empty
    vector store however correct this code is. That is a real state, not a bug
    to chase: it means "nothing has been embedded since embeddings became
    durable", and re-embedding is what fills it.

    `embedding_model` must be given with `vectors` and names the model the store
    was built for; see `EmbeddingsForModel` for why the filter is on the name
    and not on the width. Passing `vectors` without it is a programming error
    and raises rather than defaulting to "apply everything", which is the
    setting that makes a project stop opening.
    """
    if (vectors is not None or card_vectors is not None) and embedding_model is None:
        raise ValueError(
            "rebuild_graph needs embedding_model alongside vectors; without it "
            "the fold cannot tell which events this store's width belongs to"
        )
    projections: list[object] = [GraphProjection(store)]
    if embedding_model is not None:
        # Same pass as the graph and the corpus, for the same reason: the log is
        # read once, so a project's vectors can never be a different age than
        # the graph whose entity ids they are keyed by.
        if vectors is not None:
            projections.append(
                EmbeddingsForModel(vectors, model=embedding_model, channel=DOCUMENT_CHANNEL)
            )
        if card_vectors is not None:
            projections.append(
                EmbeddingsForModel(card_vectors, model=embedding_model, channel=CARD_CHANNEL)
            )
    if chunks is not None:
        # Folded in the same pass rather than a second replay: the log is
        # read once and both read models are derived from it, so a corpus can
        # never be a different age than the graph its citations sit alongside.
        projections.append(ChunkProjection(chunks))
    try:
        report = await replay(feed, projections, tenant_id=project_id, strict=True)
    except ReplayFailedError as error:
        # `strict` refuses at the first bad event rather than folding on and
        # reporting a count. The failure names the event, which is the whole
        # difference between a refusal an operator can act on and one they
        # cannot -- so it is repeated here rather than left to the `__cause__`.
        failure = error.failure
        raise KnowledgeError(
            f"knowledge event {failure.event_type} at {failure.position} failed to "
            f"replay for project {project_id} ({failure.error!r}); refusing to serve "
            "a partial graph"
        ) from error
    return report.applied
