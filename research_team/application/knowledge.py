"""The knowledge graph, in this application's own terms.

Names no redstring type. The adapter behind this port owns that vocabulary,
which is what lets the graph backend change without anything above here
noticing -- and what keeps redstring out of the application layer's import
graph entirely.

The tenant is deliberately not a parameter on any of these calls. A port
instance belongs to one project and supplies it; a caller that could pass a
different tenant is a caller that could write into another project's graph.
"""

from collections.abc import Callable
from dataclasses import dataclass
from typing import Literal, Protocol
from uuid import UUID

#: Tool names, in one place so the autonomy policy and the tools agree.
REMEMBER_TOOL = "remember"
REMEMBER_PAGE_TOOL = "remember_page"
GRAPH_SEARCH_TOOL = "graph_search"
UNMERGE_TOOL = "unmerge"


class KnowledgeError(Exception):
    """Something went wrong reaching or writing the graph."""


#: Longest document accepted in one `remember` or `store_source` call.
#: Roughly a long article.
#:
#: Lives here rather than in `redstring_adapter.py`, where it originated,
#: because `CorpusEditor._store` (`corpus_editing.py`) has to enforce it too:
#: `revise` and `restore` execute `StoreSourceDocument` directly rather than
#: going through `store_source`, so the cap is not free on that path the way
#: indexing and the blank-id refusal are not free either -- and the
#: application layer cannot import the infrastructure module to reach it.
#: Dependencies point inward, so the constant moved inward with the second
#: caller rather than the second caller reaching outward for it.
MAX_DOCUMENT_CHARS = 200_000


@dataclass(frozen=True)
class SourceRef:
    """Content to commit to the graph, supplied by the caller."""

    source_id: str
    """Identifies the document. Must not be blank -- it keys the stream."""
    text: str
    note: str | None = None
    """Why the agent thought this was worth remembering. Provenance only."""
    uri: str | None = None
    """Where the content came from. Unset for text the caller typed or pasted."""
    title: str | None = None
    published_at: str | None = None
    """When the source says it was published, as the source wrote it.

    A string rather than a date because that is what the caller has: `fetch`
    returns whatever the page's metadata claimed, and pages claim dates in
    every format there is. Parsing here would force every caller to guess at
    a format before it could hand over what it already read, and would make
    an unreadable date an error at the boundary -- rejecting the document
    over the one field that matters least. The adapter parses what it can and
    keeps the rest verbatim, so an unparseable date costs precision, not the
    document."""
    fetched_at: str | None = None
    """When this text was read, for content that came off the network.

    Set only by the by-reference path, which is the only caller that knows:
    `remember` is handed text with no way to tell when it was read, and a
    guessed timestamp is worse than the absence it would replace. Text for the
    same reason as `published_at` -- the field it lands in is text.
    """


ExtractionStage = Literal[
    "storing",
    "extracting",
    "extracted",
    "consolidating",
    "consolidated",
    "failed",
    # Perception's two, on this literal rather than on a channel of their own.
    # A transcription is a second slow thing that happens to a source row, and
    # a second progress pane beside the extraction one would be a second place
    # to look for "is anything running" -- see `extraction_queue.py`, which
    # refused a second channel for the same reason. `perceived` is terminal;
    # a perception that fails reports `failed`, like an extraction that does.
    "perceiving",
    "perceived",
]


@dataclass(frozen=True)
class ExtractionNote:
    """Where one `remember` call has got to.

    **Provisional, and never a domain event.** The log is the replay
    substrate: `rebuild_graph` refuses to serve a partial graph and forbids
    model calls on the replay path, so that a session refolded years from now
    does not depend on a live endpoint. Progress is not a fact about the
    domain -- it is a fact about one attempt, at one moment, that a later
    reader has no use for and cannot act on. `DocumentExtracted` and
    `EntitiesMerged` remain the entire durable record.

    Every count defaults to None rather than 0, because the two say different
    things: a `storing` note has established no entity count, and reporting
    one as `0` would claim extraction found nothing.
    """

    source_id: str
    stage: ExtractionStage
    detail: str = ""
    """Free text for the stage: the entity being consolidated, or why it
    failed. Never the document's own content."""
    entities: int | None = None
    relationships: int | None = None
    domain: str | None = None
    domain_confidence: float | None = None
    """`0.0` means the classifier gave up and fell back; `None` means no
    classifier ran. Kept distinct for the reason `IngestReport` keeps them
    distinct -- a fallback is otherwise indistinguishable from a confident
    choice."""
    index: int | None = None
    """Which item of `total` this note is about, 1-based."""
    total: int | None = None
    model_calls: int | None = None
    """Model calls made so far in this ingest. Calls rather than chunks: the
    chunk count is not knowable before extraction runs, and a denominator
    invented here would be a number nobody could check."""


#: Told where an ingest has got to. Synchronous and must not raise -- see
#: `KnowledgePort.ingest`.
ExtractionReporter = Callable[[ExtractionNote], None]


@dataclass(frozen=True)
class MergeRecord:
    """One consolidation, in a form the agent can read and reverse."""

    merge_id: UUID
    canonical_name: str
    absorbed_names: tuple[str, ...]
    reason: str | None


@dataclass(frozen=True)
class IngestReport:
    """What one ingest extracted and consolidated."""

    source_id: str
    entity_count: int
    relationship_count: int
    domain: str | None
    """Which prompt ran. None when no classifier was involved."""
    domain_confidence: float | None
    """How sure the classifier was. `0.0` means it gave up and fell back;
    `None` means no classifier ran. A fallback is otherwise indistinguishable
    from a confident choice, which is this field's whole reason for existing."""
    merges: tuple[MergeRecord, ...] = ()
    consolidation_failures: int = 0
    """Entities whose consolidation raised. The extraction still stands."""


@dataclass(frozen=True)
class Match:
    """One entity found by a search."""

    entity_id: UUID
    name: str
    entity_type: str
    relationship_count: int


class KnowledgePort(Protocol):
    """Committing to the graph, reading it back, and reversing a merge."""

    async def ingest(
        self, source: SourceRef, *, report: ExtractionReporter | None = None
    ) -> IngestReport:
        """Keep `source`'s text, extract it, and consolidate what it found.

        Keeping the text is part of the contract, not an implementation
        detail: everything downstream that cites a source has to be able to
        go back and check that the source says it, and an implementation
        that only built a graph would make every such citation unfalsifiable.
        It happens first, so a failed extraction still leaves the text --
        re-extracting is cheap and re-fetching may be impossible.

        `report`, when given, is told where the ingest has got to. It is
        called synchronously and **an implementation must not let it fail the
        ingest**: a listener that raises must not cost a document that has
        already been fetched and paid for. Optional so every existing caller
        is unaffected.
        """
        ...

    async def index(self, source: SourceRef) -> None:
        """Split `source`'s text into passages a reader can be shown quotes of.

        No model call, and no dependency on `ingest` having run or ever
        running: the corpus this fills is built for every document a caller
        holds, not only the ones worth paying to extract. Safe to call
        whether or not `source` has been indexed before -- a repeat over
        unchanged text writes nothing the second time.

        A no-op, not an error, when the implementation has no chunk store
        configured (`AGENT_CHUNK_STORE=none`): the same "feature is off"
        shape `ProjectGraphs.chunks` uses, rather than a caller having to
        know whether chunking is on before it can call this at all.
        """
        ...

    async def search(self, query: str, *, limit: int = 10) -> list[Match]:
        """Entities whose name matches `query`. Entry points, not traversal."""
        ...

    async def undo_merge(self, merge_id: UUID) -> MergeRecord:
        """Reverse the merge `merge_id` recorded.

        Raises `KnowledgeError` when no merge in effect has that id -- which
        covers "never happened" and "already undone" as one case.
        """
        ...
