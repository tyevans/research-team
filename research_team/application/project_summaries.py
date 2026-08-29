"""What a project *is*, in the five numbers an index has to show.

The landing page listed sessions and files. Neither is a fact about a
project: a session is minted by every `/project use`, every take-over and
every fork, and the file count it showed was the sum of per-session live-file
counts, so a path two sessions touched was counted twice. Six projects drew
six identical rows differing in a name and two numbers that meant nothing.

What a project actually holds is a pipeline, and the order below is the order
the system runs it in rather than a presentation choice:

1. **topics** — questions the project has opened, some still queued.
2. **sources** — documents its investigations have fetched into the corpus.
3. **extracted** — how many of those have been folded into the knowledge graph.
4. **courses** — what the catalog has realized out of the graph.

Each stage consumes the one above it, so a project's numbers read as a
position: 40 sources and 6 extracted is a project mid-ingest, and no
arrangement of "11 sessions, 30 files" can say that.

**`last_activity` is the field that was wrong rather than missing.**
`domain/project/landing.ts` derived it from the newest session *start* and its
own comment warned that a row "must not claim it is" the last activity.
`session_summary_rows.updated_at` moves with every turn the projection folds,
which is the thing a returning reader means. Measured against a copy of the
real database on 2026-08-29: the two disagree by up to 1h24m on a live
project (Intro to Fiction, started 05:08, updated 06:32), so the old page was
not merely imprecise — it was reporting an hour and a half stale.
"""

from dataclasses import dataclass
from typing import Protocol
from uuid import UUID


@dataclass(frozen=True)
class ProjectSummary:
    """One project's position in the pipeline, as the index draws it.

    Every field is a count except `last_activity`, and every count is of rows
    a person would recognise: dropped documents and abandoned courses are
    excluded, because a stage's number answers "how much is here" and a
    retracted thing is not here. The judgements themselves are kept in their
    own tables — this type is the index's reading, not the archive.
    """

    topics: int
    """Questions opened in this project, in any status."""

    topics_open: int
    """Of those, the ones still queued — opened and never investigated.

    Separate from `topics` because it is the only number here that is a
    *backlog* rather than an accumulation: it goes down as work happens, and
    it is the closest thing this page has to "what is waiting for you".
    """

    sources: int
    """Documents in the corpus, excluding dropped ones."""

    extracted: int
    """Of those, the ones folded into the knowledge graph.

    Never greater than `sources`, and the gap is the interesting part: it is
    ingest that has happened without extraction following it, which is a real
    and common state (One Piece, on the database this was measured against,
    had 6 sources and 3 extracted) that the previous index could not express.
    """

    courses: int
    """Realized courses, excluding abandoned ones."""

    sessions: int
    """Sessions belonging to this project. Kept, though it is the number the
    old page over-weighted, because it is still the way into the transcripts
    and a project with none has genuinely never been opened."""

    last_activity: str | None
    """ISO-8601, the newest `updated_at` across this project's sessions, or
    None for a project nothing has ever run in. See the module docstring for
    why this is not the session start the page used to show."""


class ProjectSummaries(Protocol):
    """Every project's summary in one read.

    **One call for the whole list, not one per project**, and that is the
    only interesting thing about this interface. `GET /api/projects` already
    folds one aggregate per row to find the holder, and
    `domain/project/landing.ts` defers a feature explicitly on that cost — so
    a summary reader that added a second per-project round trip would have
    made the page it exists to improve measurably worse. The adapter answers
    all of it in one `GROUP BY` per stage regardless of how many projects
    there are.

    The return is keyed by project id and is **not** required to hold an entry
    for every project: a project with nothing in it produces no rows in any of
    the grouped queries, and inventing a zero-filled entry for it here would
    push the "what does absent mean" question into the adapter, where the
    caller cannot see the answer. `summary_view` in `presenters.py` supplies
    the zeros, once, where the shape of the response is decided.
    """

    async def all(self) -> dict[UUID, ProjectSummary]:
        """Summaries for every project that has anything to summarise."""
        ...
