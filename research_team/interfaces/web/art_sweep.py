"""Generating art for candidates the library has nothing for.

Modelled directly on `blurb_sweep.py` -- read it first. Same shape: no
aggregate (nothing on the event log describes a piece of art either, see
`ArtStore`'s own docstring), an in-memory progress frame per project, one
sweep at a time, candidates worked under `config.catalog_sweep_concurrency()`
(1 by default -- see that docstring for why concurrency is implemented and
switched off), a per-candidate exception tallied as
`failed` rather than ending the run, and a settled frame carrying an `error`
key rather than leaving `running: True` forever.

**One thing here that the blurb sweep has no equivalent of.**
`ArtStore.decrement_uses` is a read-modify-write over one row, and two
candidates moving off the *same* piece of art at once would interleave their
read and their save and lose one decrement. Sequentially that could not
happen. `_uses_lock` below serialises exactly that call and nothing else --
it is held across a couple of SQLite round trips, never across a model call,
so it costs nothing measurable against a generation that takes a minute.

**What counts as "nothing to do" here is two checks, not one.** A candidate
is skipped only if it already has an assignment (`CandidateArtStore.get`)
*and that assignment was made against the candidate's current
`membership_hash`* -- that is genuinely "nothing to do", the same as a blurb
sweep's cache hit against a hash that still matches. A drifted assignment
(a different hash) is treated exactly like no assignment at all: eligible
for a match, and generated for if none is found. A candidate the library can
*match* (`matcher.match`, above threshold) is not skipped in the same sense:
`LibraryArtProvider.for_candidate` would resolve and assign it the moment
anyone actually asks for that candidate's art, so generating here as well
would be wasted model spend for a card that already has a picture waiting.
The sweep checks `matcher.match` up front for exactly that reason -- to
avoid generating for a candidate the library already covers -- and never
writes an assignment itself either way: `for_candidate` is what performs and
records that resolution, on demand, the next time the catalog is read (see
its docstring for how it now also picks up a drifted assignment). This keeps
exactly one implementation deciding "does the library already cover this"
(`LibraryArtProvider`/`_best_match`), matching the port's own note against
duplicating that logic in two places.

**`force=True` bypasses both checks and generates for every candidate.** The
project-wide "force" route exists because a library match or a stale-only
skip would otherwise make "re-illustrate everything" silently reuse the same
pictures it started with, for the same reason a reroll skips search (see
`ArtReroll` below) -- the whole point of forcing is a visibly different
result, not a re-run of the matching this sweep already does by default.

**`ArtReroll`, below, is this module's second export: a single-candidate
sibling of `ArtSweep`.** It shares `ArtStore`/`CandidateArtStore` and the
crash-settling shape but is keyed by `(project_id, slug)` rather than by
project, because two cards rerolling at once must not share one progress
frame. It never searches the library -- see its own docstring for why.
"""

import asyncio
import logging
from collections.abc import Sequence
from contextlib import suppress
from datetime import UTC, datetime
from typing import Any, Protocol
from uuid import UUID, uuid4

from research_team.application.course_catalog import ArtGeneratorPort, CourseCandidate
from research_team.infrastructure.config import catalog_sweep_concurrency
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

    def __init__(
        self,
        art_store: ArtStore,
        candidate_art_store: CandidateArtStore,
        concurrency: int | None = None,
    ) -> None:
        self._art = art_store
        self._candidate_art = candidate_art_store
        self._progress: dict[UUID, dict[str, Any]] = {}
        self._tasks: dict[UUID, asyncio.Task] = {}
        # See `BlurbSweep.__init__` for why this is read once here and
        # injectable rather than looked up per sweep.
        self._concurrency = catalog_sweep_concurrency() if concurrency is None else concurrency
        # Built lazily in `_drive`: an `asyncio.Lock` constructed here would
        # bind whatever loop happens to be current at composition time, which
        # under uvicorn is not the loop the sweep runs on.
        self._uses_lock: asyncio.Lock | None = None

    def progress(self, project_id: UUID) -> dict[str, Any]:
        frame = self._progress.get(project_id)
        return dict(frame) if frame is not None else dict(_NOT_RUNNING)

    async def start(
        self,
        project_id: UUID,
        candidates: Sequence[CourseCandidate],
        generate: ArtGeneratorPort,
        matcher: _Matcher,
        *,
        force: bool = False,
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
            self._drive(project_id, candidates, generate, matcher, force=force)
        )
        return dict(self._progress[project_id])

    async def _drive(
        self,
        project_id: UUID,
        candidates: Sequence[CourseCandidate],
        generate: ArtGeneratorPort,
        matcher: _Matcher,
        *,
        force: bool = False,
    ) -> None:
        total = len(candidates)
        done = 0
        failed = 0
        first_error: str | None = None
        permits = asyncio.Semaphore(self._concurrency)
        if self._uses_lock is None:
            self._uses_lock = asyncio.Lock()
        uses_lock = self._uses_lock

        def frame(running: bool) -> dict[str, Any]:
            return {"running": running, "done": done, "total": total, "failed": failed}

        async def sweep_one(candidate: CourseCandidate) -> None:
            nonlocal done, failed, first_error
            async with permits:
                try:
                    assigned = await self._candidate_art.get(project_id, candidate.slug)
                    fresh = (
                        assigned is not None
                        and assigned.membership_hash == candidate.membership_hash
                    )
                    if not force and fresh:
                        # Already resolved against the candidate's current
                        # cluster -- nothing to do, the sweep's exact
                        # equivalent of a blurb sweep's cache hit. A drifted
                        # assignment (`assigned` set but `fresh` False) falls
                        # through to be treated as if unassigned, below.
                        done += 1
                    elif not force and (await matcher.match(candidate)) is not None:
                        # The library already covers this candidate --
                        # generating would be wasted spend for a picture that
                        # will resolve the moment anyone actually reads this
                        # candidate's art (see the module docstring). Counted
                        # as done, not failed: this is success, just success
                        # this sweep did not have to pay for.
                        done += 1
                    else:
                        draft = await generate.generate(candidate.title, candidate.anchors)
                        if draft is None:
                            # A refusal: the model had nothing safe to offer.
                            # The existing picture (or the seeded placeholder,
                            # if there was none) stays in place -- no
                            # assignment is written, so this candidate is
                            # picked up again next sweep, exactly like a blurb
                            # sweep's refusal.
                            failed += 1
                        else:
                            art_id = uuid4()
                            await self._art.put(
                                art_id=art_id,
                                svg=draft.svg,
                                description=draft.description,
                                # Tags derived cheaply from the candidate
                                # rather than asked of the model -- see
                                # DraftArt's docstring for why the model is
                                # not asked for tags at all.
                                tags=[candidate.category],
                                palette=candidate.category,
                                created_at=datetime.now(UTC),
                                source="generated",
                            )
                            await self._candidate_art.put(
                                project_id, candidate.slug, art_id, candidate.membership_hash
                            )
                            if assigned is not None:
                                # Moving the candidate off a drifted or
                                # force-overwritten assignment -- the old
                                # picture stays in the library (it may still
                                # suit another candidate) but no longer counts
                                # this one among its uses. Under the lock: see
                                # the module docstring on why this one call is
                                # the only thing here that cannot interleave.
                                async with uses_lock:
                                    await self._art.decrement_uses(assigned.art_id)
                            done += 1
                except asyncio.CancelledError:
                    raise
                except Exception as error:
                    # Tallied and survived rather than ending the run -- see
                    # `blurb_sweep._drive`'s identical `except` for the full
                    # reasoning and for why `error` still means "this run hit
                    # a defect".
                    _logger.exception(
                        "art sweep for project %s failed on %r", project_id, candidate.slug
                    )
                    if first_error is None:
                        first_error = str(error)
                    failed += 1

                self._progress[project_id] = frame(True)

        try:
            await asyncio.gather(*(sweep_one(candidate) for candidate in candidates))
        except asyncio.CancelledError:
            # See `blurb_sweep._drive`: `gather` carries cancellation into
            # every in-flight child, so this really does stop work in flight.
            self._progress[project_id] = frame(False)
            raise
        except Exception as error:  # pragma: no cover -- see blurb_sweep._drive
            _logger.exception("art sweep for project %s crashed", project_id)
            self._progress[project_id] = frame(False) | {"error": str(error)}
            return

        settled = frame(False)
        if first_error is not None:
            settled["error"] = first_error
        self._progress[project_id] = settled

    async def wait(self, project_id: UUID) -> None:
        """Block until this project's sweep settles. For tests, not routes."""
        task = self._tasks.get(project_id)
        if task is not None:
            with suppress(asyncio.CancelledError):
                await task


class RerollAlreadyActive(Exception):
    """A reroll is already running for this candidate. Keyed by
    `(project_id, slug)`, not just `project_id` -- unlike `SweepAlreadyActive`,
    two different candidates in the same project rerolling at once are not a
    conflict, only two requests for the *same* candidate are."""

    def __init__(self, project_id: UUID, slug: str) -> None:
        super().__init__(f"art for {slug!r} in project {project_id} is already rerolling")
        self.project_id = project_id
        self.slug = slug


class ArtReroll:
    """Regenerates one candidate's art on demand, dropping its current
    assignment first -- see the module docstring's "Art is write-once"
    framing for why this exists at all.

    **Never searches the library.** `ArtSweep` checks `matcher.match` before
    generating because a library-covered candidate has nothing to gain from
    a fresh model call. A reroll is the opposite situation: the person
    pressing the button has *already seen* whatever the library or a prior
    generation produced and judged it wrong for this card. Searching first
    would, more often than not, hand back the very picture (or a
    near-duplicate of it) they are trying to get away from, and the reroll
    would look like it did nothing. So this calls `generate` directly and
    unconditionally.

    Tracked with `ArtSweep`'s exact progress-frame shape (`running`/`done`/
    `total`/`failed`) so the frontend can reuse one polling component for
    both, but keyed by `(project_id, slug)` rather than by project -- a
    project-wide frame would make two cards rerolling at the same time
    stomp on each other's progress, which a whole-catalog sweep never has to
    worry about (it already serialises itself to one run per project).
    """

    def __init__(self, art_store: ArtStore, candidate_art_store: CandidateArtStore) -> None:
        self._art = art_store
        self._candidate_art = candidate_art_store
        self._progress: dict[tuple[UUID, str], dict[str, Any]] = {}
        self._tasks: dict[tuple[UUID, str], asyncio.Task] = {}

    def progress(self, project_id: UUID, slug: str) -> dict[str, Any]:
        frame = self._progress.get((project_id, slug))
        return dict(frame) if frame is not None else dict(_NOT_RUNNING)

    async def start(
        self,
        project_id: UUID,
        slug: str,
        candidate: CourseCandidate,
        generate: ArtGeneratorPort,
    ) -> dict[str, Any]:
        """Kick off one candidate's reroll in the background and return the
        initial frame immediately -- 202, matching every other sweep route,
        because a model call is too slow to hold a request open for (see
        the module docstring)."""
        key = (project_id, slug)
        task = self._tasks.get(key)
        if task is not None and not task.done():
            raise RerollAlreadyActive(project_id, slug)

        self._progress[key] = {"running": True, "done": 0, "total": 1, "failed": 0}
        self._tasks[key] = asyncio.ensure_future(
            self._drive(project_id, slug, candidate, generate)
        )
        return dict(self._progress[key])

    async def _drive(
        self,
        project_id: UUID,
        slug: str,
        candidate: CourseCandidate,
        generate: ArtGeneratorPort,
    ) -> None:
        key = (project_id, slug)
        try:
            draft = await generate.generate(candidate.title, candidate.anchors)
        except Exception as error:
            # See `ArtSweep._drive`'s identical `except` for why this is
            # caught here rather than propagated: nothing in production
            # awaits this task, so an uncaught exception would leave the
            # frame a poller reads stuck at `running: True` forever.
            _logger.exception("art reroll for %r in project %s crashed", slug, project_id)
            self._progress[key] = {
                "running": False,
                "done": 0,
                "total": 1,
                "failed": 1,
                "error": str(error),
            }
            return

        if draft is None:
            # A refusal: the candidate's current picture (assigned or
            # placeholder) stays exactly as it was -- there is nothing here
            # to clear an assignment for, unlike the success path below.
            self._progress[key] = {"running": False, "done": 0, "total": 1, "failed": 1}
            return

        previous = await self._candidate_art.get(project_id, slug)
        art_id = uuid4()
        await self._art.put(
            art_id=art_id,
            svg=draft.svg,
            description=draft.description,
            tags=[candidate.category],
            palette=candidate.category,
            created_at=datetime.now(UTC),
            source="generated",
        )
        await self._candidate_art.put(project_id, slug, art_id, candidate.membership_hash)
        if previous is not None:
            # The old picture stays in the library -- it may suit another
            # candidate (see the module docstring) -- only its use count
            # follows this candidate away from it.
            await self._art.decrement_uses(previous.art_id)

        self._progress[key] = {"running": False, "done": 1, "total": 1, "failed": 0}

    async def wait(self, project_id: UUID, slug: str) -> None:
        """Block until this candidate's reroll settles. For tests, not routes."""
        task = self._tasks.get((project_id, slug))
        if task is not None:
            with suppress(asyncio.CancelledError):
                await task
