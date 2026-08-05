"""The knowledge graph, in this application's own terms.

Names no redstring type. The adapter behind this port owns that vocabulary,
which is what lets the graph backend change without anything above here
noticing -- and what keeps redstring out of the application layer's import
graph entirely.

The tenant is deliberately not a parameter on any of these calls. A port
instance belongs to one project and supplies it; a caller that could pass a
different tenant is a caller that could write into another project's graph.
"""

from dataclasses import dataclass
from typing import Protocol
from uuid import UUID

#: Tool names, in one place so the autonomy policy and the tools agree.
REMEMBER_TOOL = "remember"
GRAPH_SEARCH_TOOL = "graph_search"
UNMERGE_TOOL = "unmerge"


class KnowledgeError(Exception):
    """Something went wrong reaching or writing the graph."""


@dataclass(frozen=True)
class SourceRef:
    """Content to commit to the graph, supplied by the caller."""

    source_id: str
    """Identifies the document. Must not be blank -- it keys the stream."""
    text: str
    note: str | None = None
    """Why the agent thought this was worth remembering. Provenance only."""


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

    async def ingest(self, source: SourceRef) -> IngestReport:
        """Extract `source`, record it, and consolidate what it found."""
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
