"""Wiring components and lifecycle helpers for the composition root."""

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

__all__ = [
    "_PARTIAL_BUILD_RESOURCES",
    "LazyAsyncResource",
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
]
