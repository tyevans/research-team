"""Reading the corpus back, in this application's own terms.

The corpus aggregate deliberately holds no text -- keeping documents out of the
fold is what keeps snapshots constant-sized -- so answering "what does s1 say"
is a query, not a state read. This port is what that query looks like from
above: two methods, no storage vocabulary, no projection type.

Narrow on purpose. The read model behind this can grow versions, full-text
search and rebuild machinery without any of it appearing here, because the
only thing the reading tools need is a list of what exists and the bytes of one
document. A port that mirrored the projection would make every change to the
projection a change to the application layer.

`DocumentRecord` comes from the domain rather than being redefined here; see
`CorpusReadPort` for why that is the right way round.

The project is not a parameter on either call, for the same reason it is not a
parameter on `KnowledgePort`: an instance belongs to one project and supplies
it. A caller that could pass a different project id is a caller that could read
another project's sources.
"""

from dataclasses import dataclass
from typing import Protocol

from research_team.domain import DocumentRecord

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

    record: DocumentRecord
    text: str


class CorpusReadPort(Protocol):
    """The project's stored sources, listed and read.

    Both methods speak in `DocumentRecord`, the aggregate's own no-text shape,
    rather than a listing type of this port's own. Naming a domain type is
    ordinary here -- `session_service.py` does it throughout -- and it buys the
    property the rebuild guarantee rests on: the fold, the read model's `list`
    and the tools' listing all say the same thing about a document, because
    they are the same thing. Two types that must agree and are not the same
    type will eventually disagree, and the disagreement would surface as a
    citation whose metadata does not match the corpus it came from.

    `DocumentRecord` carries a field most callers have no use for: `sha256`
    is harmless and occasionally wanted -- it is what proves a quote came
    from the bytes on record. `dropped_reason` is `None` unless a caller asks
    for dropped documents by name, because the default answer is the live
    corpus and nothing else.
    """

    async def list_documents(self, *, include_dropped: bool = False) -> list[DocumentRecord]:
        """Every source in the corpus. Dropped documents are absent by default.

        `include_dropped` is opt-in and defaults to False, so a caller that
        never asks -- the agent's own tools, most of all -- keeps seeing
        exactly the corpus it always has. A caller that does ask gets dropped
        rows back too, because the corpus keeps them on purpose: a drop is a
        judgement someone made, and hiding it from a browser would misreport
        what the project holds.
        """
        ...

    async def read_document(self, source_id: str) -> StoredDocument | None:
        """One source, or `None` when this project has no such `source_id`.

        `None` rather than an exception: a model guessing at a source id is
        the expected case, not a failure, and the caller's answer to it is to
        say what does exist. Reserving the exception for storage failure keeps
        the two apart, which matters because only one of them is a bug.
        """
        ...
