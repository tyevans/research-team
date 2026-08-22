"""The knowledge graph, in this application's own terms.

Names no redstring type. The adapter behind this port owns that vocabulary,
which is what lets the graph backend change without anything above here
noticing -- and what keeps redstring out of the application layer's import
graph entirely.

The tenant is deliberately not a parameter on any of these calls. A port
instance belongs to one project and supplies it; a caller that could pass a
different tenant is a caller that could write into another project's graph.
"""

import hashlib
import re
from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum
from typing import Literal, Protocol
from uuid import UUID

from research_team.application.artifacts import slugify

#: Tool names, in one place so the autonomy policy and the tools agree.
REMEMBER_TOOL = "remember"
REMEMBER_PAGE_TOOL = "remember_page"
GRAPH_SEARCH_TOOL = "graph_search"
GRAPH_DESCRIBE_TOOL = "graph_describe"
UNMERGE_TOOL = "unmerge"


class KnowledgeError(Exception):
    """Something went wrong reaching or writing the graph."""


#: Longest document accepted in one `remember` or `store_source` call.
#: Roughly a short book.
#:
#: A judgement, not a measurement. Nothing downstream fails at any particular
#: length -- redstring chunks a long document happily, which is exactly the
#: problem: it multiplies model calls rather than bounding them, so the bound
#: has to come from here (`redstring_adapter.ingest`). Raised from 200,000 on
#: 2026-08-17 because a real document came in 4% over it and splitting a
#: document into parts costs cross-part entity resolution, which consolidation
#: only partly recovers. The cost of the raise is that a single oversized
#: ingest can now occupy the extractor two and a half times as long as before.
#:
#: Lives here rather than in `redstring_adapter.py`, where it originated,
#: because `CorpusEditor._store` (`corpus_editing.py`) has to enforce it too:
#: `revise` and `restore` execute `StoreSourceDocument` directly rather than
#: going through `store_source`, so the cap is not free on that path the way
#: indexing and the blank-id refusal are not free either -- and the
#: application layer cannot import the infrastructure module to reach it.
#: Dependencies point inward, so the constant moved inward with the second
#: caller rather than the second caller reaching outward for it.
#:
#: **Changing this means changing `DEFAULT_PERCEPTION_MAX_CHARS` in
#: `infrastructure/config.py` in the same commit.** That constant is the
#: `Budget` handed to `readeverything.represent`, and it is a *copy* of this
#: number rather than an import of it, because `config.py` is the edge that
#: asks nothing of the layers above and importing this module there would
#: invert that (ruling R1). Derived text lands in `corpus_documents` and is
#: extracted like any other document, so a drift between the two makes a
#: transcript truncate at a different length than a document.
#: `test_perception_max_chars_matches_the_document_cap` is what fails if they
#: separate -- this comment is the signal, that test is the gate.
MAX_DOCUMENT_CHARS = 500_000

#: Longest `source_id` this derives from a url.
#:
#: A url is unbounded and a `source_id` is a database key, a read-model row's
#: uuid5 seed (`read_models.py`) and one segment of every per-source route, so
#: something has to bound it. 96 is a judgement, not a measurement: long enough
#: that the host and most of the path survive for a reader, short enough to sit
#: in a URL bar beside a project uuid.
SOURCE_ID_LIMIT = 96

#: The scheme, and the `www.` that carries no information. Stripped before
#: slugging so every id does not begin `https-`, which would be eight characters
#: of the cap spent telling a reader nothing.
_URL_NOISE = re.compile(r"^[a-z][a-z0-9+.-]*://(?:www\.)?", re.IGNORECASE)


def source_id_for_url(url: str) -> str:
    """The `source_id` a page fetched from `url` is stored under.

    **Not the url itself, and that is the whole point of this function.**
    `keep` used to store `source_id=url`, on the reasoning that the url is
    already what the page is and needs no prettier name. It is a good argument
    and it produced a corpus the console could not open: `{source_id}` is one
    path segment, uvicorn percent-decodes the path before Starlette routes it,
    and the `%2F` the browser correctly sent arrives at the router as a real
    separator. Every per-source route -- read, content, extract, perceive --
    answered 404 for every auto-kept page. Measured on 2026-08-16 against the
    live console: 7 of 7 url-keyed documents failed, 36 of 36 slug-keyed ones
    succeeded.

    Readable *and* unique, because either alone is worse. A bare digest keys
    correctly and tells a reader nothing, and this id is what the console shows
    and what `fetch` now hands the model to cite. A bare slug reads well and
    collides -- two urls differing only past the cap slug identically -- so the
    digest is taken over the whole url and appended after truncation.

    Deterministic: `keep` runs on every fetch, and a random component would
    store a fresh document per re-read of the same page. `_store_document`'s
    digest check would not catch it, because that check compares bytes under a
    *given* source_id.

    What this does not do is rename anything already stored. Events are not
    rewritten, so a corpus holding url-keyed documents still holds them and
    those rows stay unreachable through the web layer; re-fetching the page is
    what repairs it, and stores a second document rather than moving the first.
    """
    digest = hashlib.sha256(url.encode("utf-8")).hexdigest()[:8]
    # Truncated before the digest is appended, never after: the digest is the
    # only thing making two similar urls distinguishable, so it is the one part
    # the cap may not eat.
    room = SOURCE_ID_LIMIT - len(digest) - 1
    slug = slugify(_URL_NOISE.sub("", url.strip()))[:room].strip("-")
    # `or` rather than a branch on `slug`: a url that slugs to nothing at all
    # (a bare IP, punctuation) still needs an id, and the digest is one.
    return f"{slug}-{digest}" if slug else digest


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


class SearchMode(StrEnum):
    """Which channels actually ran for one search.

    This layer's own vocabulary rather than redstring's `RetrievalMode`, for
    two reasons and not one: `application/` may not import redstring
    (`tests/test_architecture.py`), and the two do not mean the same thing --
    this counts the substring channel, which redstring has no concept of.
    """

    FUSED = "fused"
    """Substring matching and redstring's blocking-key channel both ran."""

    SUBSTRING = "substring"
    """Substring matching only. No embedding provider, so no fuzzy channel."""

    CARDS = "cards"
    """BM25 over the entity-card corpus. `describe`'s healthy answer."""

    UNAVAILABLE = "unavailable"
    """The channel this call needed is not wired at all.

    Distinct from an empty result, and that distinction is the reason this
    member exists: a build with no card corpus answers every `describe` with
    nothing, which reads exactly like a project that holds no such entity.
    Every defect this feature can have looks like that, so the mode is what
    tells a caller which one it is looking at.
    """


@dataclass(frozen=True)
class SearchOutcome:
    """What a search returned, and which channels produced it.

    **`mode` exists because the degradation it reports is otherwise
    invisible.** The adapter's embedding probe latches `(None, None)` when the
    endpoint is wrong or absent, and entity search quietly becomes a substring
    scan: plausible results, fewer of them, and a warning in a log nobody
    reads. Nothing raises and no count looks wrong.

    That is the shape stark-bench found every one of its real bugs in -- two
    rerank arms ran against a peer answering `502 Bad Gateway`, fell back
    exactly as designed, and wrote plausible scores, while the field that
    would have caught it had been in every report from the beginning and
    nothing read it.

    Deliberately **not** an exception. A dead embedding endpoint should
    degrade entity lookup, not break it -- the same trade the probe already
    makes for consolidation, and the right one. What changes is that a test
    can assert on the degradation and a caller can say so out loud.
    """

    matches: tuple[Match, ...]
    mode: SearchMode


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

    async def describe(self, query: str, *, limit: int = 10) -> SearchOutcome:
        """Entities matching a *description* -- their type, properties or
        neighbours -- rather than their name.

        A separate method from `search` rather than a mode on it, because the
        two answer different questions and fusing them measured worse than
        either: a model shown entities unrelated to its query scored below one
        shown none (stark-bench I.2). A caller that knows the name wants
        `search`; one that knows about the thing wants this.

        `SearchMode.UNAVAILABLE` when no card corpus is wired, which is not the
        same as no match.
        """
        ...

    async def search(self, query: str, *, limit: int = 10) -> SearchOutcome:
        """Entities whose name matches `query`. Entry points, not traversal.

        Returns a `SearchOutcome` rather than a bare list so a caller can tell
        a thin result from a degraded one -- see that class for why the
        distinction is worth a type.
        """
        ...

    async def undo_merge(self, merge_id: UUID) -> MergeRecord:
        """Reverse the merge `merge_id` recorded.

        Raises `KnowledgeError` when no merge in effect has that id -- which
        covers "never happened" and "already undone" as one case.
        """
        ...
