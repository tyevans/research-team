"""Wiring components and lifecycle helpers for the composition root."""

from research_team.wiring.builders import (
    BuiltStores,
    BuiltTools,
    build_curation_tools,
    build_stores,
    build_tools,
)
from research_team.wiring.catalog_wiring import (
    CatalogServices,
    build_catalog_services,
)
from research_team.wiring.helpers import (
    _context_parts,
    _extraction_model,
    _subagents_for,
)
from research_team.wiring.lifecycle import (
    _PARTIAL_BUILD_RESOURCES,
    _close_every_step,
    _partial_build_teardown,
    _run_detached,
    _swallowing,
)
from research_team.wiring.resources import (
    LazyAsyncResource,
    _LazyArtStore,
    _LazyBlurbCache,
    _LazyCandidateArtStore,
    _LazyOutlineCache,
    _LazyProjectSummaries,
)
from research_team.wiring.runners import (
    _CatalogFeatureRunner,
    _CourseRunner,
    _RealizedCourses,
)
from research_team.wiring.service_wiring import (
    ContentPipeline,
    MediaAcquisitionWiring,
    ProjectServiceFactories,
    SessionWiring,
    SupervisorWiring,
    build_ask_service,
    build_content_pipeline,
    build_corpus_editor,
    build_document_extractor,
    build_media_acquisition,
    build_media_perceiver,
    build_project_services,
    build_session_service,
    build_socratic_service,
    build_supervisor_roster,
)

__all__ = [
    "_PARTIAL_BUILD_RESOURCES",
    "BuiltStores",
    "BuiltTools",
    "CatalogServices",
    "ContentPipeline",
    "LazyAsyncResource",
    "MediaAcquisitionWiring",
    "ProjectServiceFactories",
    "SessionWiring",
    "SupervisorWiring",
    "_CatalogFeatureRunner",
    "_CourseRunner",
    "_LazyArtStore",
    "_LazyBlurbCache",
    "_LazyCandidateArtStore",
    "_LazyOutlineCache",
    "_LazyProjectSummaries",
    "_RealizedCourses",
    "_close_every_step",
    "_context_parts",
    "_extraction_model",
    "_partial_build_teardown",
    "_run_detached",
    "_subagents_for",
    "_swallowing",
    "build_ask_service",
    "build_catalog_services",
    "build_content_pipeline",
    "build_corpus_editor",
    "build_curation_tools",
    "build_document_extractor",
    "build_media_acquisition",
    "build_media_perceiver",
    "build_project_services",
    "build_session_service",
    "build_socratic_service",
    "build_stores",
    "build_supervisor_roster",
    "build_tools",
]
