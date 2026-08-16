"""Reading the corpus back, in this application's own terms.

The corpus aggregate deliberately holds no text -- keeping documents out of the
fold is what keeps snapshots constant-sized -- so answering "what does s1 say"
is a query, not a state read. This port is what that query looks like from
above: three methods, no storage vocabulary, no projection type.

Narrow on purpose. The read model behind this can grow versions, full-text
search and rebuild machinery without any of it appearing here, because the
only thing the reading tools need is a list of what exists and the bytes of one
source. A port that mirrored the projection would make every change to the
projection a change to the application layer.

`TextRecord`/`MediaRecord`/`SourceRecord` come from the domain rather than
being redefined here; see `CorpusReadPort` for why that is the right way
round.

The project is not a parameter on any call, for the same reason it is not a
parameter on `KnowledgePort`: an instance belongs to one project and supplies
it. A caller that could pass a different project id is a caller that could read
another project's sources.
"""

from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Protocol

from research_team.application.blobs import BlobStat
from research_team.domain import MediaRecord, SourceRecord, TextRecord

#: Tool names, in one place so the prompt and the tools agree. Neither belongs
#: in `GATED_TOOLS` -- see `autonomy.py` on why read tools stay ungated.
LIST_SOURCES_TOOL = "list_sources"
READ_SOURCE_TOOL = "read_source"


class CorpusReadError(Exception):
    """The corpus could not be read. Storage failure, not an absent document."""


@dataclass(frozen=True)
class StoredDocument:
    """One source's text, with the metadata that makes it citable.

    The record travels with the text rather than being fetched separately,
    because everything that renders a document renders its citation too, and
    two calls is two chances for them to disagree.
    """

    record: TextRecord
    text: str
    locator_map: str | None = None
    """Where each stretch of a transcript came from in its medium, as the JSON
    that was stored, or `None` for a fetched document -- which has no map at
    all, not an empty one.

    Here rather than on `TextRecord`, and the split is the point. `TextRecord`
    is the aggregate's own shape and lives in `CorpusState`, which gave up
    document text precisely so snapshots would stay constant-sized; a locator
    map is one entry per segment of a transcript and would put that cost
    straight back. This type already carries the text for the same reason it
    can carry this -- it is a read-side answer, built per query and never
    folded.

    Written by `_on_derived_text` since the perception slice landed and read by
    nothing until now: `CorpusEditor.restore` is its first caller, because
    restoring a dropped transcript means re-issuing `StoreDerivedText` with the
    whole record intact, and a restore that could not read the map back would
    have to either zero it or refuse. `application/locators.py` is what turns
    it into locators; sub-project 4 is what will ask it to.
    """


@dataclass(frozen=True)
class SourceListing:
    """One source's record, plus whether the graph has it.

    Was `DocumentListing`, renamed and widened to `SourceRecord` when media
    arrived: `list_sources` answers for both kinds in one call, and a caller
    that could only see text would be seeing half a corpus while believing it
    saw all of it.

    Composed rather than a widened record, and for the same reason
    `StoredDocument` above is composed: the record is the shape the fold, the
    read model and the tools all share, and everything hung beside it here is
    something the fold cannot say. Extraction happens on redstring's
    `Document` stream; a record carrying `extracted` would be a domain type
    claiming knowledge of another aggregate's log.

    `extracted` is a bool where the row stores a timestamp for a text source,
    and is always `False` for a media one -- nothing extracts media yet, so
    the honest answer for every `MediaRecord` is "no graph", not "unknown".
    What a caller does with this is decide whether to offer extraction, and
    "when" is a question nobody has asked yet -- the column keeps the answer
    for when they do.
    """

    record: SourceRecord
    extracted: bool


class OpenBlob(Protocol):
    """`MediaHandle.open`: call it to start reading, optionally from an offset.

    A Protocol rather than `Callable[[int], AsyncIterator[bytes]]` because the
    offset has to be *optional* -- every caller that wants the whole thing says
    `handle.open()` -- and `Callable` has no way to spell a defaulted argument.
    The alternative, `Callable[..., AsyncIterator[bytes]]`, spells nothing at
    all and would accept a factory taking the wrong argument entirely.
    """

    def __call__(self, start: int = 0) -> AsyncIterator[bytes]: ...


@dataclass(frozen=True)
class MediaHandle:
    """One media source: its record, whether its bytes still exist, and how
    to read them.

    `stat` is `None` for a dangling reference -- a record whose blob is gone
    -- which is not the same state as `read_media` answering `None` outright.
    See `CorpusReadPort.read_media` for why the two must stay distinguishable.

    `open` is a factory (`OpenBlob`), not an already-open stream, so a caller
    that only wants the metadata -- the Documents list, deciding whether to
    offer playback -- does not pay for a file descriptor it will never read.
    Calling it is what actually opens the blob; nothing here has touched the
    filesystem yet.

    It takes the same optional `start` the port does, and passing it through
    rather than letting the web layer discard chunks is what makes a range
    request cost the range rather than the file -- see `BlobStorePort.open`.
    """

    record: MediaRecord
    stat: BlobStat | None
    open: OpenBlob


class CorpusReadPort(Protocol):
    """The project's stored sources, listed and read.

    `list_sources` and `read_media` speak in `SourceRecord`/`MediaRecord`,
    the aggregate's own no-bytes shapes, rather than a listing type of this
    port's own. Naming a domain type is ordinary here -- `session_service.py`
    does it throughout -- and it buys the property the rebuild guarantee rests
    on: the fold, the read model's `list_all` and the tools' listing all say
    the same thing about a source, because they are the same thing. Two types
    that must agree and are not the same type will eventually disagree, and
    the disagreement would surface as a citation whose metadata does not match
    the corpus it came from.

    Every record carries a field most callers have no use for: `sha256`
    is harmless and occasionally wanted -- it is what proves a quote (or a
    download) came from the bytes on record. `dropped_reason` is `None`
    unless a caller asks for dropped sources by name, because the default
    answer is the live corpus and nothing else.

    **`list_documents` was removed, not deprecated.** Keeping it beside
    `list_sources` would have meant every caller silently chose whether to see
    half the corpus or all of it, and a caller that saw half would look
    exactly like one that saw the whole thing -- there is no way to render "I
    only checked the text sources" that a reader would notice was missing. One
    method that answers for both kinds is the only shape that cannot lie about
    that by omission.
    """

    async def list_sources(self, *, include_dropped: bool = False) -> list[SourceListing]:
        """Every source in the corpus, text and media together. Dropped
        sources are absent by default.

        `include_dropped` is opt-in and defaults to False, so a caller that
        never asks -- the agent's own tools, most of all -- keeps seeing
        exactly the corpus it always has. A caller that does ask gets dropped
        rows back too, because the corpus keeps them on purpose: a drop is a
        judgement someone made, and hiding it from a browser would misreport
        what the project holds.
        """
        ...

    async def read_document(
        self, source_id: str, *, include_dropped: bool = False
    ) -> StoredDocument | None:
        """One source's text, or `None` when this project has no such
        `source_id` -- when it has been dropped and `include_dropped` is not
        set, or when it names a media source rather than a text one.

        `None` rather than an exception in every case: a model guessing at a
        source id is the expected case, not a failure, and so is a model
        trying to read a video as if it were a document -- this promises
        text, and a media source has none to give it. Reserving the exception
        for storage failure keeps both apart from the ordinary "no such text"
        answer, which matters because only the exception is a bug.

        `include_dropped` defaults to False for the same reason `list_sources`
        does: the agent's `read_source` tool should keep seeing exactly the live
        corpus it always has. The callers that opt in are the ones whose job is
        to act on an excluded document -- `CorpusEditor.restore` and `revise`,
        which read a dropped document's own text back in order to re-store it,
        and the console's read route, which shows the text of the document
        someone is deciding whether to restore.
        """
        ...

    async def read_media(
        self, source_id: str, *, include_dropped: bool = False
    ) -> MediaHandle | None:
        """One media source, or `None` when this project has no such id.

        Three outcomes rather than two, and the middle one is why this is not
        just `read_document` with different bytes. `None` means nothing was
        ever stored under this id. A handle whose `stat` is `None` means the
        record is here and the bytes are not -- a dangling reference, which the
        web layer reports as 410 Gone. A caller that collapsed those two would
        send an operator looking for an ingest that never happened instead of
        for bytes that went away.

        The handle carries `open` as a factory rather than an open stream, so
        a caller that only wants the metadata -- the Documents list, deciding
        whether to offer playback -- does not pay for a file descriptor it
        will not read.
        """
        ...
