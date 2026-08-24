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

**This sweep now also writes outlines, folded in rather than built as a
second sweep beside it.** Outline generation used to happen inside
`CourseService._outline_for`, awaited synchronously behind a candidate's
detail-page request -- no spinner distinguishable from a slow network, no
cancel, two readers of the same slug paying for two generations, and a
refusal-prone cluster paying the model call again on every later view since a
refusal is deliberately never cached. `CourseService._outline_for` is now
cache-read-only; the only place anything writes an outline is here. This
module already walks exactly the candidate list an outline sweep needs,
already has a progress channel, and already does the membership-hash
freshness check that "is this cache entry still good" is -- the same check,
run twice, once per artifact.

**Copy and outline are attempted independently per candidate, and a
candidate counts as `done` only when both are fresh at the end of the
attempt; `failed` if either was refused.** Not "wrote at least one thing" --
a partial success counting as `done` would make the progress line report the
sweep finished while cards are still bare of the piece that failed, which is
exactly what these counts exist to let a reader catch. One artifact's
refusal must not skip the attempt at the other: a cluster the model will not
write copy for may still take an outline, and the reverse, so both writers
are always called (or both cache hits checked) regardless of how the other
one went.

The three-way split most worth reading before touching `_drive`, restated per
artifact:

* **A cache hit whose hash matches** is skipped -- the whole point of
  sweeping, over regenerating every card on every click.
* **A refusal** (`write` returns `None`) counts that artifact as not written
  and moves on -- see the module-level test's docstring; one ungrounded
  cluster must not wall off every card behind it.
* **Anything else raises**, and is caught per candidate: it is tallied as
  `failed`, logged, and the sweep carries on. It is still a defect rather
  than an expected outcome, and the settled frame carries an `error` key --
  present on no other path -- to say so. This used to end the whole run,
  which was defensible over a short list at concurrency 1 and is not over 71
  candidates: a single 502 from the endpoint would have left most cards bare
  with nothing to distinguish it from a sweep that finished. See `_drive`.

**The sweep can run candidates concurrently, bounded by
`config.catalog_sweep_concurrency()`, which defaults to 1** -- read that
docstring before changing the number: concurrency was measured against this
endpoint and buys 1.1%, because the server serialises. The mechanism is kept
for an endpoint that batches. Two consequences worth carrying into
any edit of `_drive`: completion order is not submission order, so the
progress frame is built from counters rather than from a position in the
list; and the two artifacts of *one* candidate stay sequential with respect
to each other, because the outline is written against the title the blurb
just chose.
"""

import asyncio
import logging
from collections.abc import Sequence
from contextlib import suppress
from datetime import UTC, datetime
from typing import Any, Protocol
from uuid import UUID

from research_team.application.course_catalog import (
    BlurbCachePort,
    DraftBlurb,
    DraftOutline,
    OutlineCachePort,
)
from research_team.domain.learning_area import AreaMember
from research_team.infrastructure.config import catalog_sweep_concurrency

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


class _OutlineWriter(Protocol):
    """The sliver of `OutlineTextPort` this module reads -- see `_Writer`."""

    model_name: str

    async def write(
        self, title: str, anchors: Sequence[AreaMember]
    ) -> DraftOutline | None: ...


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
    """One copy-and-outline sweep per project, over in-memory progress only.

    `cache`/`outline_cache` are the durable collaborators; the writers are
    supplied per call to `start`, matching `AuthoringActivity.start`'s `run`
    parameter and for the same reason -- a caller refused by the active-run
    check has not been handed a live coroutine or a writer to leave unused.
    """

    def __init__(
        self,
        cache: BlurbCachePort,
        outline_cache: OutlineCachePort,
        concurrency: int | None = None,
    ) -> None:
        self._cache = cache
        self._outline_cache = outline_cache
        self._progress: dict[UUID, dict[str, Any]] = {}
        self._tasks: dict[UUID, asyncio.Task] = {}
        # Read once at construction rather than per sweep: composition builds
        # one of these per process, and a ceiling that could change between
        # two sweeps in the same process would make a measurement taken
        # against one sweep say nothing about the next. Injectable so a test
        # can pin 1 and assert the sequential shape, or pin 2 and assert the
        # concurrent one, without an environment variable.
        self._concurrency = catalog_sweep_concurrency() if concurrency is None else concurrency

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
        write_outline: _OutlineWriter,
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
            self._drive(project_id, candidates, write, write_outline)
        )
        return dict(self._progress[project_id])

    async def _blurb_ok(
        self, project_id: UUID, candidate: _Candidate, write: _Writer
    ) -> tuple[bool, str]:
        """Whether this candidate's copy is fresh in the cache by the end of
        the attempt -- already there, or just written -- **and the title that
        is now the candidate's**.

        The second half of that pair is not decoration. `_drive` used to hand
        `candidate.title` to the outline writer, and `candidate` is a frozen
        snapshot taken at `start()`: on a project's first sweep a candidate
        with no blurb yet carries `area.display_name()`, the single most
        central entity's name, so every outline in that sweep was written
        against a title like "Xindi" while the card ended up showing the one
        the model had just chosen a line earlier.

        **Measured as cosmetic on 2026-08-23** against the live endpoint: the
        outline is driven by the anchors, and came back correct under a
        deliberately wrong placeholder title. So this returns the title rather
        than re-reading the cache, which would cost a query per candidate to
        recover something the call above already has in hand. A cache hit
        returns `candidate.title` unchanged, and that is already right --
        `CatalogService.build` fills a candidate's title from the cached blurb
        whenever one is there.
        """
        cached = await self._cache.get(project_id, candidate.slug)
        if cached is not None and cached.membership_hash == candidate.membership_hash:
            # Up to date -- the whole reason this is a sweep and not a
            # regenerate-everything button.
            return True, candidate.title

        draft = await write.write(candidate.title, candidate.anchors)
        if draft is None:
            # A refusal: the model would not ground this cluster's copy. The
            # card keeps its title and its art -- see the module docstring --
            # and the sweep moves on rather than stopping.
            return False, candidate.title

        await self._cache.put(
            project_id,
            candidate.slug,
            draft.title,
            draft.text,
            candidate.membership_hash,
            write.model_name,
            datetime.now(UTC),
        )
        return True, draft.title

    async def _outline_ok(
        self,
        project_id: UUID,
        candidate: _Candidate,
        title: str,
        write_outline: _OutlineWriter,
    ) -> bool:
        """`_blurb_ok`'s exact shape, over the outline cache and writer --
        see the module docstring on why copy and outline are attempted
        independently rather than one gating the other.

        `title` is passed in rather than read off `candidate` because the
        blurb attempt may have just replaced it; see `_blurb_ok`'s docstring
        for the snapshot this closes over."""
        cached = await self._outline_cache.get(project_id, candidate.slug)
        if cached is not None and cached.membership_hash == candidate.membership_hash:
            return True

        draft = await write_outline.write(title, candidate.anchors)
        if draft is None:
            return False

        await self._outline_cache.put(
            project_id,
            candidate.slug,
            draft.promise,
            draft.sections,
            candidate.membership_hash,
            write_outline.model_name,
            datetime.now(UTC),
        )
        return True

    async def _drive(
        self,
        project_id: UUID,
        candidates: Sequence[_Candidate],
        write: _Writer,
        write_outline: _OutlineWriter,
    ) -> None:
        total = len(candidates)
        done = 0
        failed = 0
        first_error: str | None = None
        permits = asyncio.Semaphore(self._concurrency)

        def frame(running: bool) -> dict[str, Any]:
            return {"running": running, "done": done, "total": total, "failed": failed}

        async def sweep_one(candidate: _Candidate) -> None:
            nonlocal done, failed, first_error
            async with permits:
                try:
                    # Both attempted regardless of how the other went -- see
                    # the module docstring's paragraph on independence. A
                    # candidate counts as `done` only when everything it
                    # needed came out fresh; if either is missing, it is
                    # `failed`, not partially `done`, because a caller reading
                    # `done == total` uses that to mean "every card is fully
                    # written" and a partial success counted as `done` would
                    # make that reading wrong while the card is still bare of
                    # the piece that failed.
                    #
                    # Sequential *within* a candidate, and that is not an
                    # oversight: the outline is written against the title the
                    # blurb just chose (see `_blurb_ok`), so overlapping the
                    # two would reintroduce the placeholder-title defect this
                    # same change fixes, to buy at most a factor of two on top
                    # of a ceiling that is already the server's limit.
                    blurb_ok, title = await self._blurb_ok(project_id, candidate, write)
                    outline_ok = await self._outline_ok(
                        project_id, candidate, title, write_outline
                    )
                except asyncio.CancelledError:
                    # Re-raised, never counted: a cancelled candidate did not
                    # fail, and swallowing it here would leave `gather` below
                    # believing the sweep ran to completion.
                    raise
                except Exception as error:
                    # **One candidate's defect no longer abandons the rest,
                    # and this is a deliberate change from the sequential
                    # loop**, which let the exception out of the `for` and
                    # settled the whole sweep on the spot. That was defensible
                    # at concurrency 1 over a short list; it is not at 71
                    # candidates and two and a half hours, where a single 502
                    # from the endpoint would silently end the run with most
                    # cards still bare. So a raise is tallied as `failed` --
                    # the candidate genuinely has nothing written -- and the
                    # sweep continues.
                    #
                    # What is preserved is the *signal*: `error` still appears
                    # in the settled frame and nowhere else, so a caller can
                    # still tell "this run hit a defect" from "this run was
                    # clean", and every dict-equality test for a clean run
                    # stays correct without listing a key it never expects.
                    # The first error is the one kept, not the last: it is the
                    # one most likely to explain the ones after it.
                    _logger.exception(
                        "blurb sweep for project %s failed on %r", project_id, candidate.slug
                    )
                    if first_error is None:
                        first_error = str(error)
                    failed += 1
                else:
                    if blurb_ok and outline_ok:
                        done += 1
                    else:
                        failed += 1

                # Written after every candidate, from whichever one finished
                # -- not indexed by position in the list, which is why the
                # counters above are the record and the list order is not.
                # Safe without a lock only because every read-modify-write of
                # `done`/`failed`/this frame happens with no `await` between
                # them, on one event loop thread.
                self._progress[project_id] = frame(True)

        try:
            await asyncio.gather(*(sweep_one(candidate) for candidate in candidates))
        except asyncio.CancelledError:
            # `gather` propagates cancellation into every in-flight child, so
            # by the time this is reached the model calls are already
            # unwinding -- cancelling the sweep task really does stop work in
            # flight, not merely stop new submissions. The frame is settled on
            # the way out for the same reason the `except Exception` below
            # settles it: a poller has no other way to learn the run ended.
            self._progress[project_id] = frame(False)
            raise
        except Exception as error:  # pragma: no cover -- see below
            # Reaching here now means `sweep_one` itself broke rather than a
            # writer -- the per-candidate `except` above catches everything a
            # model call can raise. Kept because the cost of being wrong about
            # that is a frame stuck at `running: True` forever, which a reader
            # watching the button cannot tell from a slow sweep.
            _logger.exception("blurb sweep for project %s crashed", project_id)
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
