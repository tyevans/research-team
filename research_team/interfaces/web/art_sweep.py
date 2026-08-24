"""Generating art for candidates the library has nothing for.

Modelled directly on `blurb_sweep.py` -- read it first. Same shape: no
aggregate (nothing on the event log describes a piece of art either, see
`ArtStore`'s own docstring), an in-memory progress frame per project, one
sweep at a time, sequential rather than concurrent, and a crashed `_drive`
settles the frame with an `error` key rather than leaving `running: True`
forever.

**What counts as "nothing to do" here is two checks, not one.** A candidate
is skipped only if it already has an assignment (`CandidateArtStore.get`) --
that is genuinely "nothing to do", the same as a blurb sweep's cache hit. A
candidate the library can *match* (`matcher.match`, above threshold) is not
skipped in the same sense: `LibraryArtProvider.for_candidate` would resolve
and assign it the moment anyone actually asks for that candidate's art, so
generating here as well would be wasted model spend for a card that already
has a picture waiting. The sweep checks `matcher.match` up front for exactly
that reason -- to avoid generating for a candidate the library already
covers -- and never writes an assignment itself either way: `for_candidate`
is what performs and records that resolution, on demand, the next time the
catalog is read. This keeps exactly one implementation deciding "does the
library already cover this" (`LibraryArtProvider`/`_best_match`), matching
the port's own note against duplicating that logic in two places.
"""

import asyncio
import logging
from collections.abc import Sequence
from contextlib import suppress
from datetime import UTC, datetime
from typing import Any, Protocol
from uuid import UUID, uuid4

from research_team.application.course_catalog import ArtGeneratorPort, CourseCandidate
from research_team.infrastructure.persistence.read_models import ArtStore, CandidateArtStore

_logger = logging.getLogger(__name__)


class _Matcher(Protocol):
    """The sliver of `LibraryArtProvider` this module reads -- its search,
    not its assignment-writing `for_candidate`. A `Protocol` so a test can
    stand one up without real stores, matching `blurb_sweep._Writer`."""

    async def match(self, candidate: CourseCandidate): ...


class SweepAlreadyActive(Exception):
    """A sweep is already running on this project. See `blurb_sweep`'s
    identical exception for the full reasoning -- there is no run id here
    either, because there is no aggregate to have minted one."""

    def __init__(self, project_id: UUID) -> None:
        super().__init__(f"an art sweep is already active on project {project_id}")
        self.project_id = project_id


_NOT_RUNNING: dict[str, Any] = {"running": False, "done": 0, "total": 0, "failed": 0}


class ArtSweep:
    """One art-generation sweep per project, over in-memory progress only.

    `art_store`/`candidate_art_store` are the durable collaborators; the
    generator and the matcher are supplied per call to `start`, matching
    `BlurbSweep.start`'s reasoning -- a caller refused by the active-run
    check has not been handed a live coroutine to leave unused.
    """

    def __init__(self, art_store: ArtStore, candidate_art_store: CandidateArtStore) -> None:
        self._art = art_store
        self._candidate_art = candidate_art_store
        self._progress: dict[UUID, dict[str, Any]] = {}
        self._tasks: dict[UUID, asyncio.Task] = {}

    def progress(self, project_id: UUID) -> dict[str, Any]:
        frame = self._progress.get(project_id)
        return dict(frame) if frame is not None else dict(_NOT_RUNNING)

    async def start(
        self,
        project_id: UUID,
        candidates: Sequence[CourseCandidate],
        generate: ArtGeneratorPort,
        matcher: _Matcher,
    ) -> dict[str, Any]:
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
            self._drive(project_id, candidates, generate, matcher)
        )
        return dict(self._progress[project_id])

    async def _drive(
        self,
        project_id: UUID,
        candidates: Sequence[CourseCandidate],
        generate: ArtGeneratorPort,
        matcher: _Matcher,
    ) -> None:
        done = 0
        failed = 0
        try:
            for candidate in candidates:
                assigned = await self._candidate_art.get(project_id, candidate.slug)
                if assigned is not None:
                    # Already resolved -- nothing to do, the sweep's exact
                    # equivalent of a blurb sweep's cache hit.
                    done += 1
                    self._progress[project_id] = {
                        "running": True,
                        "done": done,
                        "total": len(candidates),
                        "failed": failed,
                    }
                    continue

                match = await matcher.match(candidate)
                if match is not None:
                    # The library already covers this candidate -- generating
                    # would be wasted spend for a picture that will resolve
                    # the moment anyone actually reads this candidate's art
                    # (see the module docstring). Counted as done, not
                    # failed: this is success, just success this sweep did
                    # not have to pay for.
                    done += 1
                    self._progress[project_id] = {
                        "running": True,
                        "done": done,
                        "total": len(candidates),
                        "failed": failed,
                    }
                    continue

                draft = await generate.generate(candidate.title, candidate.anchors)
                if draft is None:
                    # A refusal: the model had nothing safe to offer. The
                    # seeded placeholder stays in place -- no assignment is
                    # written, so this candidate is picked up again next
                    # sweep, exactly like a blurb sweep's refusal.
                    failed += 1
                else:
                    art_id = uuid4()
                    await self._art.put(
                        art_id=art_id,
                        svg=draft.svg,
                        description=draft.description,
                        # Tags derived cheaply from the candidate rather than
                        # asked of the model -- see DraftArt's docstring for
                        # why the model is not asked for tags at all.
                        tags=[candidate.category],
                        palette=candidate.category,
                        created_at=datetime.now(UTC),
                        source="generated",
                    )
                    await self._candidate_art.put(project_id, candidate.slug, art_id)
                    done += 1

                self._progress[project_id] = {
                    "running": True,
                    "done": done,
                    "total": len(candidates),
                    "failed": failed,
                }
        except Exception as error:
            # See blurb_sweep._drive's identical `except` for why this is
            # caught here rather than left to propagate: nothing in
            # production awaits this task, so an uncaught exception would
            # leave the last frame at `running: True` forever.
            _logger.exception("art sweep for project %s crashed", project_id)
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
