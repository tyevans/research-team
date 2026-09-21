"""The curriculum bounded context.

Course modeling, catalogs, learning paths, and learner progress.
"""

from research_team.curriculum.domain.authoring_run import (
    CourseAuthored,
    CourseAuthoringFailed,
    CourseAuthoringRunSettled,
    CourseAuthoringRunStarted,
    RecordAuthoredCourse,
    RecordAuthoringFailure,
    SettleCourseAuthoringRun,
    StartCourseAuthoringRun,
)
from research_team.curriculum.domain.catalog import (
    ArtRef,
    Blurb,
    CatalogSections,
    Category,
    CourseCandidate,
    membership_hash,
    prominence_of,
)
from research_team.curriculum.domain.course import (
    AbandonCourse,
    Course,
    CourseAbandoned,
    CourseFit,
    CourseRealized,
    CourseState,
    RealizeCourse,
    course_stream_id,
    fit_of,
)
from research_team.curriculum.domain.curation import (
    CourseFeatured,
    CourseUnfeatured,
)
from research_team.curriculum.domain.learner import (
    ItemRecord,
    LearnerChecklistRecorded,
    LearnerItemAnswered,
    LearnerItemCompleted,
    LearnerProgress,
    LearnerProgressState,
    RecordAttempt,
    RecordChecklistState,
)
from research_team.curriculum.domain.learning_area import (
    AreaMember,
    AreaProjection,
    LearningArea,
    LearningPath,
    PrerequisiteEdge,
)

__all__ = [
    "AbandonCourse",
    "AreaMember",
    "AreaProjection",
    "ArtRef",
    "Blurb",
    "CatalogSections",
    "Category",
    "Course",
    "CourseAbandoned",
    "CourseAuthored",
    "CourseAuthoringFailed",
    "CourseAuthoringRunSettled",
    "CourseAuthoringRunStarted",
    "CourseCandidate",
    "CourseFeatured",
    "CourseFit",
    "CourseRealized",
    "CourseState",
    "CourseUnfeatured",
    "ItemRecord",
    "LearnerChecklistRecorded",
    "LearnerItemAnswered",
    "LearnerItemCompleted",
    "LearnerProgress",
    "LearnerProgressState",
    "LearningArea",
    "LearningPath",
    "PrerequisiteEdge",
    "RealizeCourse",
    "RecordAttempt",
    "RecordAuthoredCourse",
    "RecordAuthoringFailure",
    "RecordChecklistState",
    "SettleCourseAuthoringRun",
    "StartCourseAuthoringRun",
    "course_stream_id",
    "fit_of",
    "membership_hash",
    "prominence_of",
]
