"""Which session holds a target's course markdown, and which of its files are
the course.

**Extracted from `export.py` rather than copied out of it**, when the read
route (`read_course_unit` in `app.py`) needed the same four questions the zip
and the HTML book already ask: which target came out of which session, whether
a target wrote the path overview or an area, what prefix its files sit under,
and which of a workspace's files start with it.

The rule this module exists to keep is CLAUDE.md's, restated for a directory
constant: `AREAS_DIR`/`PATHS_DIR` were already on their third copy
(`course_authoring.py` writes them, `export.py` read them, and
`frontend/src/presentation/curriculum/course-paths.ts` mirrors them for links
the console builds itself). A fourth reader resolving them independently would
be a fourth chance for a rename to produce an empty page rather than an error
-- and an empty page is the one failure this whole increment is about, so the
route that fixes it must not reintroduce it.

Nothing here reads a session store or awaits anything. Every function takes an
already-loaded session or an already-fetched run frame, which is what lets the
export routes and the read route share them without sharing `ExportDeps`.
"""

from typing import Any

from research_team.application.course_authoring import AREAS_DIR, PATHS_DIR

__all__ = [
    "AREAS_DIR",
    "PATHS_DIR",
    "UNIT_FILE",
    "AuthoredFile",
    "area_prefix",
    "course_links",
    "files_under",
    "is_path_file",
    "path_file",
    "split_area",
]

UNIT_FILE = "unit.md"
"""The one file in an area's directory that is the unit rather than a lesson.

A fourth copy of a string `course_authoring.py` writes -- but it is written
there inside three prompt sentences addressed to a model, not as a constant,
so there is nothing to import. This is the only *reader's* copy: both the HTML
book and the console's read route go through `split_area` below rather than
comparing filenames themselves, so a rename breaks one grep rather than two
surfaces silently classifying the unit as a lesson.
"""


def path_file(target: str) -> str:
    """Where the path overview for `target` is written, if it is one."""
    return f"{PATHS_DIR}/{target}.md"


def area_prefix(target: str) -> str:
    """The directory every file of `target`'s area course sits under.

    Trailing slash, and it is load-bearing: without it `startswith` on a slug
    like `rome` would also match `rome-law`'s directory, and the reader would
    be handed another area's lessons with nothing to notice them by.
    """
    return f"{AREAS_DIR}/{target}/"


def is_path_file(session: Any, target: str) -> bool:
    """Whether this run's target wrote the path overview rather than an area.

    Asked of the workspace rather than inferred from the slug. A run's targets
    are area slugs plus, last, the path's own slug -- and nothing on the frame
    marks which is which, so the only honest test is whether the file exists.
    """
    return path_file(target) in session.state.files


def course_links(run: dict) -> list[tuple[str, str]]:
    """`completed` zipped with `sessions`, dropping any pair that does not match.

    The same refusal `courseLinks` makes in the console, for the same reason:
    a target paired with the wrong run's session names a real file about
    something else, and nobody would suspect it.
    """
    completed = run.get("completed") or []
    sessions = run.get("sessions") or []
    return [(target, sessions[i]) for i, target in enumerate(completed) if i < len(sessions)]


def files_under(session: Any, prefix: str) -> list[tuple[str, str]]:
    """Every workspace file whose path starts with `prefix`, path-sorted, as
    `(path, content)`.

    Sorted rather than left in insertion order: a workspace dict is written in
    the order the turns happened, and two readers of the same course would see
    its lessons in different orders depending on which turn was retried.
    """
    return [
        (path, entry.get("content", ""))
        for path, entry in sorted(session.state.files.items())
        if path.startswith(prefix)
    ]


#: One workspace file, as `(path, content)`.
AuthoredFile = tuple[str, str]


def split_area(session: Any, target: str) -> tuple[AuthoredFile | None, list[AuthoredFile]]:
    """One area's files as `(unit, lessons)`, each entry `(path, content)`.

    `unit.md` is Stages 1 and 2 and everything else is a lesson, matched on the
    filename because that is what `course_authoring` writes -- there is no
    marker inside the file. A run that wrote only lessons produces `None` for
    the unit rather than a missing area, which is the state a reader can act
    on: the lessons exist and are worth showing even though the framing turn
    did not land.
    """
    prefix = area_prefix(target)
    unit: AuthoredFile | None = None
    lessons: list[AuthoredFile] = []
    for path, content in files_under(session, prefix):
        if path == f"{prefix}{UNIT_FILE}":
            unit = (path, content)
        else:
            lessons.append((path, content))
    return unit, lessons
