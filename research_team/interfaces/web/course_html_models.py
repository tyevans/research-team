"""Data models for offline course HTML books.

Extracted from `course_html.py`: structured representation of course files,
learning areas, and the fully resolved course book.
"""

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any
from uuid import UUID

from research_team.interfaces.web.course_html_resolvers import Resolution
from research_team.platform.components import Document


@dataclass(frozen=True)
class CourseFile:
    """One authored markdown artifact, parsed.

    `title` is the first `# heading` or the frontmatter's, falling back to the
    filename -- a lesson with neither still needs something in the table of
    contents, and "lesson-03.md" is a worse label than nothing only if you
    have never had to find lesson three.
    """

    path: str
    title: str
    document: Document


@dataclass(frozen=True)
class CourseArea:
    """One learning area: its Understanding by Design unit and its lessons."""

    slug: str
    title: str
    unit: CourseFile | None
    lessons: tuple[CourseFile, ...] = ()


@dataclass(frozen=True)
class CourseBook:
    """Everything the page renders, with every live read already made.

    `resolutions` is keyed by `f"{file path}#{component id}"` rather than by
    component id alone. Ids are unique within a document and nothing enforces
    it across a course, so two lessons that both call a definition block
    `nicene-christianity` are a real and ordinary thing to write -- and would
    otherwise share one resolution, which is a wrong figure rather than a
    missing one.
    """

    name: str
    project_id: UUID
    origin: str
    exported_at: str
    run: Mapping[str, Any]
    #: One plain sentence about how this run settled, and the targets it never
    #: started. Passed in rather than derived here: `export.py` owns the
    #: status vocabulary for both formats, and a page that worked it out
    #: separately could describe the same run differently from the zip.
    status_sentence: str = ""
    never_started: tuple[str, ...] = ()
    overview: CourseFile | None = None
    areas: tuple[CourseArea, ...] = ()
    resolutions: Mapping[str, Resolution] = field(default_factory=dict)
    #: Source id to title, for expanding `[[src:...]]` in prose. Absent ids
    #: are not an error: the reference renders with the id as its own label,
    #: which is what the console does for a source it cannot name either.
    sources: Mapping[str, str] = field(default_factory=dict)


def resolution_key(path: str, component_id: str) -> str:
    """The `CourseBook.resolutions` key. One function so the builder and the
    renderer cannot disagree about it -- a mismatch here renders every
    resolved widget as an absence, which looks exactly like a project with no
    graph."""
    return f"{path}#{component_id}"


__all__ = [
    "CourseArea",
    "CourseBook",
    "CourseFile",
    "resolution_key",
]
