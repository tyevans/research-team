"""`UsageReader`: `UsageReadPort` over a live redstring `GraphStore` + `ChunkStore`.

The one collaborator besides `known_names` this needs is the chunk store
itself, called directly rather than through `ChunkRetriever`. That is
deliberate, not an oversight: `ChunkRetriever.__init__` requires an
`EmbeddingProvider` and dimension-checks it against the store, so
constructing one here would mean carrying a fake provider through production
wiring purely to satisfy a collaborator that `RetrievalMode.LEXICAL` never
calls. `tokenize`/`lexical_candidates`/`rank_chunks` below are what that
class's `_lexical` does internally, and every name is exported from
redstring's package root, so nothing here reaches past its public surface.
"""

from typing import TYPE_CHECKING
from uuid import UUID

from redstring import rank_chunks, tokenize

from research_team.application.usages import Usage
from research_team.infrastructure.knowledge.aliases import known_names
from research_team.infrastructure.knowledge.markdown_table_chunker import original_text

if TYPE_CHECKING:
    from redstring.ports.chunk_store import ChunkStore
    from redstring.ports.graph_store import GraphStore


class UsageReader:
    """`UsageReadPort` for one project: `graph` and `chunks` are that
    project's stores, and `tenant_id` is fixed at construction the same way
    `KnowledgePort`/`CorpusReadPort` fix a project -- a caller cannot pass a
    different tenant and read another project's mentions.
    """

    def __init__(self, graph: "GraphStore", chunks: "ChunkStore", tenant_id: UUID) -> None:
        self._graph = graph
        self._chunks = chunks
        self._tenant_id = tenant_id

    async def usages(self, entity_id: UUID, *, limit: int = 20) -> list[Usage]:
        """Passages naming this entity or any name it has been merged under.

        One query per name, not one query over a joined string: BM25 scores
        a passage against the terms it was asked for, so joining "Acme" and
        "Acme Corporation" into a single query would reward a passage for
        containing "Acme" twice rather than treating the two spellings as
        alternatives for the same mention.

        Results are deduplicated by `(source_id, start, end)`, keeping the
        better score -- an entity named "Acme Corporation" with alias "Acme"
        matches the same sentence under both queries, and a usages list
        showing one passage twice reads as a bug to anyone looking at it.

        **The scores this keeps the max of are not strictly comparable.**
        Each is BM25 computed against its own query's term statistics, so
        "the better score" when two names hit the same passage, and the
        final sort across all passages, are both a deliberate approximation
        rather than a single commensurate ranking. It is right about
        ordering far more often than it is wrong, and the alternative -- a
        fused ranking model over multiple queries -- is a great deal of
        machinery for a list of `limit` passages. Reasoned, not measured:
        no A/B against a fused ranker exists for this corpus size.

        **`text` is `original_text(chunk)`, not `chunk.text`.** `Usage`
        promises that `text` is exactly the slice `start`/`end` name, and
        `MarkdownTableChunker` produces chunks whose text begins with a table
        header the document does not contain at `start_char`. Passing
        `chunk.text` through would make the promise false by the header's
        length -- and only on table chunks, so the great majority of usages
        would look right. `GET /api/projects/{id}/sources/{source_id}` serves
        `document[start:end]` for the console's highlighting, so the visible
        symptom is a quotation and a highlight that disagree, on exactly the
        passages a table document is made of. `original_text` is a no-op on
        every chunk with no synthetic prefix, which is all of them from any
        other chunker.

        Not decided here: whether the reader should *show* the header rather
        than merely stop miscounting it. `chunk.metadata["table_header"]`
        carries it for a caller that wants to, and a passage of table rows
        reads poorly without one -- but that is a presentation choice about
        what a citation looks like, and this class's job is to report offsets
        honestly.

        Names that are blank, or tokenize to nothing (`tokenize`/`rank_chunks`
        treat a blank query as an error), are skipped rather than queried --
        an entity whose only recorded name is blank would otherwise turn a
        read into a 500.
        """
        names = await known_names(self._graph, entity_id, self._tenant_id)
        best: dict[tuple[str, int, int], Usage] = {}

        for name in names:
            terms = tokenize(name)
            if not terms:
                continue
            candidates = await self._chunks.lexical_candidates(terms, self._tenant_id, limit)
            for ranked in rank_chunks(terms, candidates, limit):
                chunk = ranked.chunk
                key = (chunk.source_id, chunk.start_char, chunk.end_char)
                existing = best.get(key)
                if existing is not None and existing.score >= ranked.score:
                    continue
                best[key] = Usage(
                    source_id=chunk.source_id,
                    start=chunk.start_char,
                    end=chunk.end_char,
                    text=original_text(chunk),
                    score=ranked.score,
                )

        return sorted(best.values(), key=lambda usage: usage.score, reverse=True)[:limit]
