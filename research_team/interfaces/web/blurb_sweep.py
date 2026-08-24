"""Writing the catalog copy increment 1 built the cache and the writer for,
and never called.

`AuthoringActivity` (`authoring.py`, read it first) is the model this is
built on: one run at a time per project, an in-memory progress record, a
refused second start. **Unlike it, this needs no aggregate.** A blurb is a
cache entry -- `BlurbCachePort` already is the durable half, keyed by
`(project_id, slug)` -- and nothing on the event log describes one, per
CLAUDE.md's Events section on ports with a single adapter and the domain
module's own note that a candidate is "a pure function of a projection", not
a fact worth appending. So there is no row for a restart to recover and no
`last()` to read one back from: a sweep interrupted by a restart is simply
gone, and the button starts a fresh one. That is the entire reason `progress`
for a project that never swept, or whose sweep has finished, answers the same
"not running" shape rather than `None` or a `KeyError` -- there is nothing
durable underneath it to distinguish those two cases, and a caller rendering
a progress bar should not need to.

The three-way split most worth reading before touching `_drive`:

* **A cache hit whose hash matches** is skipped -- the whole point of
  sweeping, over regenerating every card on every click.
* **A refusal** (`write` returns `None`) is counted as failed and moves on --
  see the module-level test's docstring; one ungrounded cluster must not wall
  off every card behind it.
* **Anything else raises**, and unlike a refusal it is *not* tallied as a
  counted outcome -- it is a defect. But it is still caught inside `_drive`,
  not left to crash the background task: nothing in production awaits that
  task (only the test-only `wait()` does), so an uncaught exception would
  become an unretrieved-exception log line at best while the last frame
  written sits at `running: True` forever. A reader watching the button has
  no way to tell that apart from a sweep that is merely slow. The frame is
  logged and settled instead, with an `error` key present only on this path
  -- see `_drive`.
"""

import asyncio
import logging
from collections.abc import Sequence
from contextlib import suppress
from datetime import UTC, datetime
from typing import Any, Protocol
from uuid import UUID

from research_team.application.course_catalog import BlurbCachePort, DraftBlurb
from research_team.domain.learning_area import AreaMember

_logger = logging.getLogger(__name__)


class _Candidate(Protocol):
    """The sliver of `CourseCandidate` this module reads.

    A `Protocol` rather than importing the dataclass itself: the sweep never
    touches `art`, `category` or `prominence`, and typing against exactly the
    four fields it does read (`slug`, `title`, `anchors`, `membership_hash`)
    is what lets a test build one without an `ArtRef`.
    """

    slug: str
    title: str
    anchors: Sequence[AreaMember]
    membership_hash: str


class _Writer(Protocol):
    """The sliver of `BlurbTextPort` this module reads -- see `_Candidate`."""

    model_name: str

    async def write(self, title: str, anchors: Sequence[AreaMember]) -> DraftBlurb | None: ...


class SweepAlreadyActive(Exception):
    """A sweep is already running on this project.

    Carries only `project_id`, unlike `RunAlreadyActive`'s `project_id` and
    `run_id` pair -- there is no run id, because there is no aggregate to
    have minted one. See the module docstring.
    """

    def __init__(self, project_id: UUID) -> None:
        super().__init__(f"a blurb sweep is already active on project {project_id}")
        self.project_id = project_id


_NOT_RUNNING: dict[str, Any] = {"running": False, "done": 0, "total": 0, "failed": 0}
"""The answer for a project this process has no record of sweeping, and the
answer a finished sweep leaves behind -- see the module docstring for why
those two cases are not distinguished."""


class BlurbSweep:
    """One blurb-writing sweep per project, over in-memory progress only.

    `cache` is the one durable collaborator; the writer is supplied per call
    to `start`, matching `AuthoringActivity.start`'s `run` parameter and for
    the same reason -- a caller refused by the active-run check has not been
    handed a live coroutine or a writer to leave unused.
    """

    def __init__(self, cache: BlurbCachePort) -> None:
        self._cache = cache
        self._progress: dict[UUID, dict[str, Any]] = {}
        self._tasks: dict[UUID, asyncio.Task] = {}

    def progress(self, project_id: UUID) -> dict[str, Any]:
        """The live frame if one exists, or the not-running default.

        Not gated on whether the task is still running: a *finished* sweep's
        last frame (`running: False`, real `done`/`failed` counts) has to
        survive being read after the task completes, or a caller checking
        progress a moment after the sweep settles would see the result
        replaced by zeros. Only a project this process has never swept falls
        back to `_NOT_RUNNING`.
        """
        frame = self._progress.get(project_id)
        return dict(frame) if frame is not None else dict(_NOT_RUNNING)

    async def start(
        self,
        project_id: UUID,
        candidates: Sequence[_Candidate],
        write: _Writer,
    ) -> dict[str, Any]:
        """Sweep every candidate in the background, refusing a second run.

        Returns the initial progress frame immediately -- the sweep itself
        runs as a background task, matching `AuthoringActivity.start`'s
        reasoning: a caller waiting on every candidate's model turn before
        getting a response is indistinguishable from one that hung.
        """
        task = self._tasks.get(project_id)
        if task is not None and not task.done():
            raise SweepAlreadyActive(project_id)

        total = len(candidates)
        self._progress[project_id] = {
            "running": True,
            "done": 0,
            "total": total,
            "failed": 0,
        }
        self._tasks[project_id] = asyncio.ensure_future(
            self._drive(project_id, candidates, write)
        )
        return dict(self._progress[project_id])

    async def _drive(
        self,
        project_id: UUID,
        candidates: Sequence[_Candidate],
        write: _Writer,
    ) -> None:
        done = 0
        failed = 0
        try:
            for candidate in candidates:
                cached = await self._cache.get(project_id, candidate.slug)
                if cached is not None and cached.membership_hash == candidate.membership_hash:
                    # Up to date -- the whole reason this is a sweep and not a
                    # regenerate-everything button.
                    done += 1
                    self._progress[project_id] = {
                        "running": True,
                        "done": done,
                        "total": len(candidates),
                        "failed": failed,
                    }
                    continue

                draft = await write.write(candidate.title, candidate.anchors)
                if draft is None:
                    # A refusal: the model would not ground this cluster's
                    # copy. The card keeps its title and its art -- see the
                    # module docstring -- and the sweep moves on rather than
                    # stopping. Not the same thing as the `except` below: a
                    # refusal is an expected outcome this method counts, not
                    # a defect it reports.
                    failed += 1
                else:
                    await self._cache.put(
                        project_id,
                        candidate.slug,
                        draft.title,
                        draft.text,
                        candidate.membership_hash,
                        write.model_name,
                        datetime.now(UTC),
                    )
                    done += 1

                self._progress[project_id] = {
                    "running": True,
                    "done": done,
                    "total": len(candidates),
                    "failed": failed,
                }
        except Exception as error:
            # Caught here rather than left to propagate out of the task: with
            # nothing in production awaiting it (only the test-only `wait`
            # does), an uncaught exception becomes an unretrieved-exception
            # log line at best, and the frame this loop last wrote sits at
            # `running: True` forever -- a progress bar with no way to tell
            # "the sweep died" from "the sweep is just slow". `error` is only
            # present on this path: a normal finish's frame has no such key,
            # so `progress()["error"]`'s presence is itself the "ended badly"
            # signal, and every dict-equality test for a clean run stays
            # correct without listing a key it never expects.
            _logger.exception("blurb sweep for project %s crashed", project_id)
            self._progress[project_id] = {
                "running": False,
                "done": done,
                "total": len(candidates),
                "failed": failed,
                "error": str(error),
            }
            return

        self._progress[project_id] = {
            "running": False,
            "done": done,
            "total": len(candidates),
            "failed": failed,
        }

    async def wait(self, project_id: UUID) -> None:
        """Block until this project's sweep settles. For tests, not routes."""
        task = self._tasks.get(project_id)
        if task is not None:
            with suppress(asyncio.CancelledError):
                await task
