"""Vector store probing, coordinate embedding generation, and durable recording."""

import logging
from collections.abc import Sequence
from typing import Any
from uuid import UUID

from eventsource.ports.positions import ExpectedVersion
from eventsource.ports.store import AggregateStore
from redstring import (
    EmbeddingProvider,
    GraphStore,
    VectorStore,
    document_stream,
)

from research_team.infrastructure.knowledge.entity_embeddings import (
    PROJECT_EMBEDDING_SOURCE,
    embed_entities,
    embed_entity_names,
)

logger = logging.getLogger(__name__)


class EmbeddingCoordinator:
    """Coordinates embedding endpoints, vector stores, and dual-channel persistence."""

    def __init__(
        self,
        *,
        embeddings: EmbeddingProvider | None,
        vectors: VectorStore | None,
        card_vectors: VectorStore | None = None,
        event_store: AggregateStore,
        store: GraphStore,
        project_id: UUID,
        usable: bool | None = None,
    ) -> None:
        self.embeddings = embeddings
        self.vectors = vectors
        self.card_vectors = card_vectors
        self.event_store = event_store
        self.store = store
        self.project_id = project_id
        self.usable = usable

    async def pair(self) -> tuple[EmbeddingProvider | None, VectorStore | None]:
        """The embedding provider and store to extract with, if they work.

        **Probed once, lazily, and latched.** `AGENT_VECTOR_STORE` now defaults
        to on, and its endpoint defaults to the same local server that serves
        the chat model -- which need not serve embeddings at all. llama.cpp
        serves one model per process. So the common misconfiguration is not
        exotic, and a default-on feature has to survive it.

        Surviving it means *degrading*, not failing. `build_graph` embeds after
        it has extracted, so an `EmbeddingProviderError` raised there would
        throw away a document that had already been fetched and every model
        call its extraction cost -- to lose an optional third scoring feature.
        `_store_document` makes the same trade in the other direction and for
        the same reason: the cheap failure is the one left possible.

        So the probe is one `embed` of one short string, before the first
        ingest uses it. If it raises, or the width disagrees with what the
        provider declares, this logs at **warning with the exception** and
        returns `(None, None)` for the rest of the process -- consolidation
        falls back to two features, which is exactly what shipped before #88
        and is a working configuration, not a broken one.

        **This is a degradation and it is not silent, but it is also not
        loud enough to stop anything.** That is the deliberate part: a person
        who wanted embeddings and mistyped the model name gets a warning in the
        log and worse consolidation, not a dead application. `AGENT_VECTOR_STORE
        =none` is how to say you meant it and skip the probe.

        Latched rather than retried per ingest: a wrong model name does not
        become right, and retrying would pay a round trip per document to
        re-learn it. The cost of the latch is that an endpoint which comes up
        *after* the process did stays unused until a restart, which is the
        right way round -- the alternative charges every healthy run for a
        failure mode nobody is in.
        """
        if self.embeddings is None or self.vectors is None:
            return None, None
        if self.usable is False:
            return None, None
        if self.usable is None:
            self.usable = await self.probe()
            if not self.usable:
                return None, None
        return self.embeddings, self.vectors

    async def probe(self) -> bool:
        """One embed of one string, to find out whether the endpoint is there.

        Checks the width as well as the call, because the two failures need the
        same handling and only one of them raises. A provider declaring 768
        against a server returning 1024 would otherwise reach
        `VectorProjection` and raise `DimensionMismatchError` -- a *poison
        event*, which is unrecoverable rather than retryable, in the middle of
        an ingest.
        """
        assert self.embeddings is not None and self.vectors is not None
        try:
            vectors = await self.embeddings.embed(["probe"])
        except Exception:
            # Broad on purpose: the transports underneath raise their own
            # types, and every one of them means the same thing here -- no
            # embeddings this run. `exc_info` is what makes it diagnosable.
            logger.warning(
                "the embedding endpoint (%s, model %r) did not answer a probe; "
                "consolidating on name and graph only. Set AGENT_VECTOR_STORE=none "
                "to skip this probe, or fix AGENT_EMBEDDING_MODEL / "
                "AGENT_EMBEDDING_BASE_URL",
                type(self.embeddings).__name__,
                getattr(self.embeddings, "model", "?"),
                exc_info=True,
            )
            return False
        width = len(vectors[0]) if vectors else 0
        if width != self.vectors.dimension:
            logger.warning(
                "the embedding endpoint returned %d components and the vector store "
                "holds %d; consolidating on name and graph only. AGENT_EMBEDDING_MODEL "
                "and AGENT_EMBEDDING_DIMENSION are set together or not at all",
                width,
                self.vectors.dimension,
            )
            return False
        return True

    async def record(self, entities: Sequence[Any], *, source_id: str) -> None:
        """Append this ingest's embeddings to the log, on both channels.

        **Nothing here raises.** Every call site is downstream of an extraction
        that has already been folded into the graph store and appended to the
        log; an embedding endpoint that dies between those two moments must not
        turn a successful ingest into a failed one. What it costs when it does
        fail is that these entities have no vectors until something re-embeds,
        which is exactly the state every project was in before this method
        existed, so it degrades to the old behaviour rather than to a new one.

        **That guarantee is the reason `build_graph` is given no embedding
        pair.** redstring embeds inside `build_graph`, after the extraction has
        been folded into the graph store and appended to the log, and raises on
        a failed or short reply -- so an endpoint that answers the probe and
        dies on the batch discards a document the graph already contains, and
        the caller sees a failed ingest for a document that is in fact there.
        There is no `try/except` this adapter can put around that without also
        swallowing the extraction's own failures. Owning both channels here is
        what makes the paragraph above true rather than aspirational; the test
        is `test_an_ingest_survives_an_embedding_endpoint_that_dies`.

        **Called before `_consolidate`, and the order is load-bearing.**
        `CandidateFinder` scores the third similarity feature against the
        document channel's vectors, so consolidation has to run after they are
        written or it silently falls back to two features -- which is a working
        configuration and therefore not something anything would notice.
        """
        if not entities:
            return

        embeddings, vectors = await self.pair()
        if embeddings is None:
            return

        # The document channel: the bare name, which is what redstring's own
        # `_embed_entities` embedded when it owned this and what consolidation's
        # thresholds were tuned against. Written straight into the store as
        # well as the log, because `_consolidate` below reads that store.
        if vectors is not None:
            try:
                event = await embed_entity_names(
                    entities=entities,
                    provider=embeddings,
                    tenant_id=self.project_id,
                    source_id=source_id,
                )
                if event is not None:
                    await self.event_store.append(
                        document_stream(tenant_id=self.project_id, source_id=source_id),
                        [event],
                        ExpectedVersion.any_(),
                    )
                    await vectors.upsert_many(event.embeddings)
            except Exception:
                logger.exception("could not record document embeddings for %s", source_id)

        # The card channel: this project's own richer vectors, over the same
        # text `entity_cards` gives BM25. Written straight into the per-project
        # store as well as the log, so this ingest's entities are clusterable
        # without waiting for the next project open to fold them back.
        #
        # Cards are assembled here, *before* `_consolidate` and `_recard` -- so
        # a vector can describe an entity that this same ingest then absorbs
        # into another. Harmless rather than merely tolerated: an absorbed
        # entity is skipped by every graph read, so its vector is orphaned and
        # never queried, and the surviving entity's own card is re-embedded by
        # the next pass over it. Moving this after consolidation would fix the
        # staleness and cost the document channel its ordering, since
        # `_consolidate` scores against the vectors written above. See
        # `BACKLOG.md` B130 for the general form of the staleness.
        if self.card_vectors is not None:
            try:
                event = await embed_entities(
                    graph=self.store,
                    provider=embeddings,
                    tenant_id=self.project_id,
                    only={entity.id for entity in entities},
                )
                if event is not None:
                    await self.event_store.append(
                        document_stream(
                            tenant_id=self.project_id,
                            source_id=PROJECT_EMBEDDING_SOURCE,
                        ),
                        [event],
                        ExpectedVersion.any_(),
                    )
                    await self.card_vectors.upsert_many(event.embeddings)
            except Exception:
                logger.exception("could not record card embeddings for %s", source_id)
