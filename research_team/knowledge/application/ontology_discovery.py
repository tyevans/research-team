"""Discovering the classes a document states, and refusing the ones it does not.

Extraction turns "There are six difficulties available in the game: EASY,
NORMAL, HARD, EXPERT, MASTER, and APPEND" into six unrelated `category`
entities. The class name, the membership, the ordering and the count are all in
that one sentence, and none of the four survives. This recovers them.

Prompt construction, JSON parsing, strict/lenient verification, coordinate
translation, and cross-chunk merging logic are isolated in
`ontology_verification.py`.
"""

from collections.abc import Callable
from dataclasses import dataclass
from typing import Literal, Protocol

from research_team.knowledge.application.ontology_verification import (
    PROMPT_HEADER,
    build_prompt,
    merge_classes,
    parse_ontology,
    verify_classes,
)
from research_team.knowledge.application.ports import CorpusReadPort
from research_team.knowledge.domain.ontology import DiscoveredClass

DiscoveryStage = Literal[
    "reading",
    "chunking",
    "generating",
    "verifying",
    "complete",
    "failed",
]


@dataclass(frozen=True)
class DiscoveryProgress:
    """Where ontology discovery has reached."""

    source_id: str
    stage: DiscoveryStage
    chunk_index: int | None = None
    total_chunks: int | None = None
    classes_found_so_far: int = 0
    detail: str = ""


DiscoveryReporter = Callable[[DiscoveryProgress], None]


@dataclass(frozen=True)
class DiscoveryReport:
    """Detailed summary of an ontology discovery pass over one document."""

    source_id: str
    class_count: int
    classes: tuple[DiscoveredClass, ...]
    chunks_total: int
    chunks_processed: int
    chunks_unreadable: int
    total_rejected_members: int
    strict: bool


MAX_DISCOVERY_CHUNK_CHARS = 40_000
DISCOVERY_CHUNK_OVERLAP_CHARS = 2_000
MAX_DISCOVERY_CHARS = 500_000


@dataclass(frozen=True)
class DocumentChunk:
    """A slice of a document as the model will be shown it, and where it came from.

    `text` is what goes into a prompt. It is `prefix + document[start_char:end_char]`
    -- the prefix being text the document does **not** contain at `start_char`,
    which is how `MarkdownTableChunker` gives a chunk of table rows the header
    that names them. `prefix_start_char` is where that prefix really lives in
    the document, so a span landing inside it can still be cited.
    """

    text: str
    start_char: int
    prefix: str = ""
    prefix_start_char: int = 0


class DocumentChunkPort(Protocol):
    """Cutting a document into pieces one model call can hold."""

    def chunk(self, text: str) -> list[DocumentChunk]: ...


class OntologyTextPort(Protocol):
    """Turning a prompt into text, with the name of whatever did it."""

    @property
    def model_name(self) -> str: ...

    async def generate(self, prompt: str) -> str: ...


class OntologyRecordPort(Protocol):
    """Appending the discovery event, without naming an event store here."""

    async def record(
        self, source_id: str, model_version: str, classes: list[DiscoveredClass]
    ) -> None: ...


class OntologyDiscoveryService:
    """One document's classes: read it, ask, verify, record.

    Bound to one project through the `CorpusReadPort` and the recorder it is
    handed, never through a parameter -- the same implicit binding
    `GraphReadPort` documents at length, and for the same reason: a project id
    a caller can pass is a knob that can be turned to the wrong project.
    """

    def __init__(
        self,
        *,
        corpus: CorpusReadPort,
        model: OntologyTextPort,
        recorder: OntologyRecordPort,
        chunker: DocumentChunkPort,
    ) -> None:
        self._corpus = corpus
        self._model = model
        self._recorder = recorder
        self._chunker = chunker

    async def discover(
        self,
        source_id: str,
        *,
        strict: bool = True,
        on_progress: DiscoveryReporter | None = None,
    ) -> int | None:
        """How many classes were recorded, or `None` when nothing was."""
        report = await self.discover_report(source_id, strict=strict, on_progress=on_progress)
        return report.class_count if report is not None else None

    async def discover_report(
        self,
        source_id: str,
        *,
        strict: bool = True,
        on_progress: DiscoveryReporter | None = None,
    ) -> DiscoveryReport | None:
        """Perform ontology discovery pass over `source_id` returning a full DiscoveryReport,
        or `None` if the document was missing, oversized, or unreadable.
        """
        if on_progress is not None:
            on_progress(DiscoveryProgress(source_id=source_id, stage="reading"))

        document = await self._corpus.read_document(source_id)
        if document is None:
            if on_progress is not None:
                on_progress(
                    DiscoveryProgress(
                        source_id=source_id, stage="failed", detail="document not found"
                    )
                )
            return None
        if len(document.text) > MAX_DISCOVERY_CHARS:
            if on_progress is not None:
                on_progress(
                    DiscoveryProgress(
                        source_id=source_id,
                        stage="failed",
                        detail=(
                            f"document exceeds max chars "
                            f"({len(document.text)} > {MAX_DISCOVERY_CHARS})"
                        ),
                    )
                )
            return None

        if on_progress is not None:
            on_progress(DiscoveryProgress(source_id=source_id, stage="chunking"))

        chunks = self._chunker.chunk(document.text)
        total_chunks = len(chunks)
        per_chunk: list[list[DiscoveredClass]] = []
        unreadable = 0

        for idx, chunk in enumerate(chunks, 1):
            if on_progress is not None:
                on_progress(
                    DiscoveryProgress(
                        source_id=source_id,
                        stage="generating",
                        chunk_index=idx,
                        total_chunks=total_chunks,
                        classes_found_so_far=sum(len(c) for c in per_chunk),
                    )
                )
            proposals = parse_ontology(await self._model.generate(build_prompt(chunk.text)))
            if proposals is None:
                unreadable += 1
                continue

            if on_progress is not None:
                on_progress(
                    DiscoveryProgress(
                        source_id=source_id,
                        stage="verifying",
                        chunk_index=idx,
                        total_chunks=total_chunks,
                        classes_found_so_far=sum(len(c) for c in per_chunk),
                    )
                )

            verified = verify_classes(
                proposals,
                document_text=document.text,
                source_id=source_id,
                chunk=chunk,
                strict=strict,
            )
            per_chunk.append(verified)

        if chunks and unreadable == len(chunks):
            if on_progress is not None:
                on_progress(
                    DiscoveryProgress(
                        source_id=source_id, stage="failed", detail="all chunks unreadable"
                    )
                )
            return None

        classes = merge_classes(per_chunk)
        await self._recorder.record(source_id, self._model.model_name, classes)

        total_rejected = sum(len(c.rejected_members) for c in classes)
        if on_progress is not None:
            on_progress(
                DiscoveryProgress(
                    source_id=source_id,
                    stage="complete",
                    total_chunks=total_chunks,
                    classes_found_so_far=len(classes),
                )
            )

        return DiscoveryReport(
            source_id=source_id,
            class_count=len(classes),
            classes=tuple(classes),
            chunks_total=total_chunks,
            chunks_processed=total_chunks - unreadable,
            chunks_unreadable=unreadable,
            total_rejected_members=total_rejected,
            strict=strict,
        )


__all__ = [
    "DISCOVERY_CHUNK_OVERLAP_CHARS",
    "MAX_DISCOVERY_CHARS",
    "MAX_DISCOVERY_CHUNK_CHARS",
    "PROMPT_HEADER",
    "DiscoveryProgress",
    "DiscoveryReport",
    "DiscoveryReporter",
    "DiscoveryStage",
    "DocumentChunk",
    "DocumentChunkPort",
    "OntologyDiscoveryService",
    "OntologyRecordPort",
    "OntologyTextPort",
    "build_prompt",
    "merge_classes",
    "parse_ontology",
    "verify_classes",
]
