"""Dependencies for source, ingestion, media, and perception HTTP routes."""

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from uuid import UUID

from research_team.infrastructure.persistence import CorpusRunner
from research_team.infrastructure.persistence.corpus_reader import ProjectCorpusReader
from research_team.infrastructure.persistence.read_models import OntologyRunner
from research_team.interfaces.web.extraction import ExtractionActivity
from research_team.interfaces.web.extraction_queue import ExtractionQueue
from research_team.platform.shared.blobs import BlobStorePort
from research_team.research.application.corpus_editing import CorpusEditor
from research_team.research.application.document_extraction import (
    DocumentExtractor,
)
from research_team.research.application.perception import (
    MediaPerceiver,
    PerceptionPort,
)

__all__ = ["SourceDeps"]


@dataclass(frozen=True)
class SourceDeps:
    """What the source and ingestion routes need from `create_app`'s closure.

    A record rather than a long parameter list, matching `ExportDeps`,
    `SettingsDeps`, and `CatalogDeps`. Everything here is already built in
    `create_app`; nothing is constructed in this module.
    """

    require_project: Callable[[UUID], Awaitable[None]] | None = None
    corpus: CorpusRunner | None = None
    blob_store: BlobStorePort | None = None
    editor: CorpusEditor | None = None
    extractor: DocumentExtractor | None = None
    extract_queue: ExtractionQueue | None = None
    ontology: OntologyRunner | None = None
    perception: PerceptionPort | None = None
    perceiver: MediaPerceiver | None = None
    extraction: ExtractionActivity | None = None
    reader_of: Callable[[UUID], ProjectCorpusReader] | None = None
