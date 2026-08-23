"""What has been asked for extraction, and what is waiting its turn.

`DispatchQueue` is the shape, and the reasoning in its module docstring
applies here almost line for line: a control on every row, FIFO rather than a
refusal, at most one in flight per project, drained by one background task,
provisional and never durable. Read that first; this records only where the
two differ, and both differences are the same difference -- **extraction
already has a progress channel and dispatch never did.**

**No feed, no frame type, no SSE pump.** `ExtractionActivity` carries
`storing` / `extracting` / `consolidating` / `consolidated` / `failed` to the
browser already, with its own listeners and its own catch-up route, and the
running item here is the one those frames describe. A second channel
publishing "this extraction is running" beside the one already saying
`extracting, chunk 3 of 40` would be two accounts of one thing, and the way
that goes wrong is not a crash -- it is a pane and a row disagreeing, with
nothing in either signature to catch it. So this queue publishes nothing. It
is read through its catch-up route, which the client refreshes when an
extraction frame arrives on the connection it already has.

The gap that leaves is real and is accepted: **a queue that changes with no
extraction frame behind it is not pushed anywhere.** Another tab queueing six
documents does not move this tab's rows until something else refreshes them.
That is a second-tab-only staleness in a local single-user tool, and the fix
-- a frame type, a pump, a `decodeFrame` case and a store -- costs more than
it buys until somebody is actually running two tabs against one project.

**The same document is never queued twice.** `DispatchQueue` deliberately does
not deduplicate, because dispatching a topic twice asks for two pieces of
work. Extracting one document twice asks for the same graph to be written
twice, at model cost, for no difference in the result. It matters most for
"extract all": pressed twice while the first pass is draining, a queue without
this would hold every document twice over.
"""

import asyncio
from collections import deque
from collections.abc import Awaitable, Callable
from contextlib import suppress
from dataclasses import dataclass
from typing import Any
from uuid import UUID

from research_team.application.knowledge import IngestReport


@dataclass
class _Pending:
    """One document waiting to be extracted."""

    source_id: str
    run: Callable[[], Awaitable[IngestReport | None]]


class ExtractionQueue:
    """One project's extractions: the running one, the waiting ones, the last ones."""

    def __init__(self) -> None:
        self._pending: dict[UUID, deque[_Pending]] = {}
        self._running: dict[UUID, str] = {}
        self._finished: dict[UUID, dict[str, dict[str, Any]]] = {}
        self._tasks: dict[UUID, asyncio.Task] = {}
        self._draining: set[UUID] = set()

    # ---------------- what the routes drive ----------------

    def start(
        self,
        project_id: UUID,
        source_id: str,
        run: Callable[[], Awaitable[IngestReport | None]],
    ) -> bool:
        """Enqueue one document. False if it was already queued or running.

        A bool rather than a frame, unlike `DispatchQueue.start`: there is no
        frame to hand back, because the caller's next read is the catch-up
        route and the running item's account comes from `ExtractionActivity`.
        What the route does need to know is whether this press changed
        anything, so "extract all" can answer how many it actually took on.

        `run` is a factory rather than a coroutine already in hand, matching
        `DispatchQueue.start`: an item that sits in a deque for a minute would
        otherwise be a live coroutine nobody has awaited, and one dropped by
        `cancel` would be one nobody ever will.

        `_draining` is maintained synchronously rather than checked through
        `task.done()`, for the reason `DispatchQueue` gives: `done()` is false
        for the whole window between the last item finishing and the drain
        coroutine returning, and a press landing there would queue behind a
        task that was already leaving.
        """
        if self._holds(project_id, source_id):
            return False
        self._pending.setdefault(project_id, deque()).append(_Pending(source_id, run))

        if project_id not in self._draining:
            self._draining.add(project_id)
            self._tasks[project_id] = asyncio.ensure_future(self._drain(project_id))
        return True

    def cancel(self, project_id: UUID) -> int:
        """Stop what is running and drop everything waiting. Returns how many went.

        Per project rather than per document, matching `DispatchQueue.cancel`
        and for the same reason: the UI offers one stop control, not one per
        queued row, so this does not have to honour an action nothing offers.

        A cancelled extraction leaves no `failed` note behind, because the
        `CancelledError` is raised at an `await` inside the ingest rather than
        being reported through it. The row simply stops being queued, which is
        what a person who just pressed stop expects to see.
        """
        waiting = self._pending.pop(project_id, deque())
        # The running *document*, not the drain task. `DispatchQueue` counts
        # the task, which is right there because it pops its item off the deque
        # before awaiting; here the task is scheduled by `start` and may not
        # have claimed anything yet, so counting it would report one more
        # document stopped than the project has -- two documents queued and
        # cancelled before the first turn of the loop would answer 3.
        stopped = len(waiting) + (1 if project_id in self._running else 0)

        task = self._tasks.get(project_id)
        if task is not None and not task.done():
            # Cancelled regardless of whether it had claimed an item: an
            # unclaimed drain task left running would find an empty deque and
            # return, but one that claims its item in the same turn this
            # returns would extract a document the caller just stopped.
            task.cancel()
        return stopped

    # ---------------- what the catch-up route reads ----------------

    def current(self, project_id: UUID) -> str | None:
        """The document being extracted, for a tab that arrived mid-run."""
        return self._running.get(project_id)

    def queued(self, project_id: UUID) -> tuple[str, ...]:
        """Every document waiting, in the order it will run."""
        return tuple(pending.source_id for pending in self._pending.get(project_id, ()))

    def finished(self, project_id: UUID) -> list[dict[str, Any]]:
        """How each document's most recent extraction went.

        Kept rather than cleared on completion, for `ExtractionActivity.last`'s
        reason: nothing durable records that an extraction was *requested*, so
        a failure has no other account of itself. `DocumentExtracted` records
        the successes, which is why a row that succeeded can also be read from
        the corpus projection -- but a failure appends nothing anywhere.
        """
        return list(self._finished.get(project_id, {}).values())

    async def wait(self, project_id: UUID) -> None:
        """Block until this project's queue drains. For tests, not routes."""
        task = self._tasks.get(project_id)
        if task is not None:
            # A cancelled drain is the expected end of `cancel`, not a failure
            # for a waiter to re-raise at its own call site.
            with suppress(asyncio.CancelledError):
                await task

    # ---------------- internals ----------------

    def _holds(self, project_id: UUID, source_id: str) -> bool:
        if self._running.get(project_id) == source_id:
            return True
        return any(
            pending.source_id == source_id for pending in self._pending.get(project_id, ())
        )

    async def _drain(self, project_id: UUID) -> None:
        """Extract this project's documents one at a time until none are waiting.

        **`None` from `run` means "done, with no counts to report", and the
        keys are omitted rather than zeroed.** Perception shares this queue --
        transcribing an hour of audio is the same kind of slow, and a second
        queue would be a second thing to cancel -- but it extracts nothing, and
        `entities: 0` on a finished transcription would read as "extraction
        found nothing" rather than "no extraction happened". The wire schema
        already treats both counts as optional (`extractionOutcomeDto`), so
        this needed no client change.

        A failure is recorded and the loop continues, matching
        `DispatchQueue._drain`: stopping on the first would turn one rate-limit
        refusal in the middle of "extract all" into forty documents silently
        skipped, and the log would say nothing, because a queued extraction
        appends no event of its own.
        """
        try:
            while True:
                waiting = self._pending.get(project_id) or deque()
                if not waiting:
                    return
                pending = waiting.popleft()
                self._running[project_id] = pending.source_id

                try:
                    report = await pending.run()
                except asyncio.CancelledError:
                    raise
                except Exception as error:  # noqa: BLE001 -- reported, not raised, from a task
                    outcome: dict[str, Any] = {
                        "source_id": pending.source_id,
                        "status": "failed",
                    }
                    outcome["detail"] = str(error)
                else:
                    outcome = {"source_id": pending.source_id, "status": "done"}
                    if report is not None:
                        outcome["entities"] = report.entity_count
                        outcome["relationships"] = report.relationship_count
                        # Reported unconditionally rather than only when
                        # non-zero. A key that appears only on a bad run is a
                        # key nobody builds a habit of reading, and the
                        # baseline is the half of this number that matters:
                        # `unresolved` alone says nothing, `unresolved`
                        # against `relationships` says whether the prompt is
                        # landing.
                        outcome["unresolved"] = report.unresolved_relationships
                        outcome["date_nodes"] = report.date_nodes
                        outcome["lifted_dates"] = report.lifted_dates

                self._finished.setdefault(project_id, {})[pending.source_id] = outcome
                self._running.pop(project_id, None)
        finally:
            # Unconditional, so a cancelled drain leaves the project
            # extractable. Without this, every later press would queue behind
            # a `_draining` entry belonging to a task that had gone.
            self._running.pop(project_id, None)
            self._draining.discard(project_id)
