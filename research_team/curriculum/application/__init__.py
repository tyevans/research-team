"""Curriculum application package: authoring, catalog, realization, checkpoints, and paths."""

from research_team.curriculum.application.area_projection import (
    CoMentionPort,
    GraphTooLarge,
    SemanticPort,
    project_areas,
    slugify,
)
from research_team.curriculum.application.authoring_checkpoints import (
    CheckpointEvaluation,
    CheckpointFailed,
    evaluate_checkpoint,
)
from research_team.curriculum.application.course_authoring import (
    AuthoredCourse,
    CourseAuthor,
)
from research_team.curriculum.application.course_catalog import (
    ArtGeneratorPort,
    ArtPort,
    BlurbCachePort,
    BlurbTextPort,
    CachedBlurb,
    CachedOutline,
    Catalog,
    CatalogService,
    DraftArt,
    DraftBlurb,
    DraftOutline,
    OutlineCachePort,
    OutlineTextPort,
)
from research_team.curriculum.application.course_realization import (
    CourseDetail,
    CourseService,
    RealizedCourse,
    RealizedCoursePort,
    RealizedCourseView,
)
from research_team.curriculum.application.curriculum import (
    Curriculum,
    CurriculumService,
    graph_fingerprint,
)
from research_team.curriculum.application.frontmatter import (
    extract_title,
    parse_frontmatter,
)
from research_team.curriculum.application.grading import (
    GradingError,
    Verdict,
    grade,
    normalize_answer,
)
from research_team.curriculum.application.learning_paths import (
    full_path,
    path_to,
)

__all__ = [
    "ArtGeneratorPort",
    "ArtPort",
    "AuthoredCourse",
    "BlurbCachePort",
    "BlurbTextPort",
    "CachedBlurb",
    "CachedOutline",
    "Catalog",
    "CatalogService",
    "CheckpointEvaluation",
    "CheckpointFailed",
    "CoMentionPort",
    "CourseAuthor",
    "CourseDetail",
    "CourseService",
    "Curriculum",
    "CurriculumService",
    "DraftArt",
    "DraftBlurb",
    "DraftOutline",
    "GradingError",
    "GraphTooLarge",
    "OutlineCachePort",
    "OutlineTextPort",
    "RealizedCourse",
    "RealizedCoursePort",
    "RealizedCourseView",
    "SemanticPort",
    "Verdict",
    "evaluate_checkpoint",
    "extract_title",
    "full_path",
    "grade",
    "graph_fingerprint",
    "normalize_answer",
    "parse_frontmatter",
    "path_to",
    "project_areas",
    "slugify",
]
