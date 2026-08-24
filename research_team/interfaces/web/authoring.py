"""Where a course-authoring run has got to, while it is getting there -- and
what it wrote, after nobody is watching any more.

Shaped like `seeding.py`, which is shaped like `extraction.py`, which is
shaped like `activity.py` -- but with one difference from all three, and it is
the difference this module is now mostly about: **an authoring run leaves
something behind that outlives the process.** See
`domain/course_authoring_run.py` for the argument; the short form is that each
target is authored in its own session, the course markdown lives in that
session's workspace, and nothing else on the log records which session holds
which area. That pairing used to live in a dict here and was lost permanently
on restart.

So this class is now two things bolted together, and the seam between them is
worth naming because it decides what a reader is told after a restart:

* **The log holds the facts.** Started, one target authored into one session,
  one target failed, settled -- appended through `CourseAuthoringRun`, projected
  into `authoring_runs`, and readable by any process that opens the database.
* **This object holds the progress.** Which target is in hand right now, and
  the live frames the browser repaints from. That is genuinely process state:
  nothing is driving a run whose process is gone, so a durable `current` would
  assert work is in progress when none is.

**One run per project, not one per area**, and that is a product decision
rather than a concurrency convenience. Authoring an area is three model turns;
authoring a path is three per area and can be thirty. Letting a person start
several at once means a browser tab can commit an unbounded amount of a local
model's time with no way to see the total, and the second run's turns would
interleave with the first's on the same project. Refused up front, the way
`ResearchSupervisor.start` refuses a second research run.

**Progress is per area, and that is the difference from `SeedingActivity`.** A
seeding run is one turn and is either running or not; an authoring run over
eight areas is up to twenty-four turns and can sit at "running" for a very
long time. A panel that could only say "running" for twenty minutes is
indistinguishable from one that has hung, so the frame carries which area is
in hand and how many are done.
"""

import asyncio
from collections.abc import Awaitable, Callable, Sequence
from contextlib import suppress
from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

from eventsource.application.aggregates.repository import AggregateRepository

from research_team.application import RunAlreadyActive
from research_team.domain.course_authoring_run import (
    CourseAuthoringRun,
    RecordAuthoredCourse,
    RecordAuthoringFailure,
    SettleCourseAuthoringRun,
    StartCourseAuthoringRun,
)
from research_team.infrastructure.persistence.read_models import (
    AuthoringRunRow,
    AuthoringRunRunner,
)

AUTHORING = "Authoring"
"""The frame type on the live feed, PascalCase like `SEEDING` beside it.

**This used to say the opposite, and the note is left standing because the
mistake is the instructive part.** It read: "Not a domain event and must never
become one. What the log records is the `write_file` calls each turn makes; 'an
authoring run started' is not a fact the log holds, which is exactly why this
module exists." Every clause was true and the conclusion was backwards -- "the
log does not hold it" was the defect, not the reason. See CLAUDE.md on comments
that explain an absence by pointing at another absence.

What is still true, and is all this constant ever needed to say, is that the
*frame* is not the event. The frame carries `current` -- which target is being
written this minute -- and the log deliberately does not, because that is the
one part of a run that does not outlive the process driving it."""

_INTERRUPTED = "interrupted"
"""What a run that was in flight when the process died reports afterwards.

Never appended and never stored: it is derived, by `last` below, from a row
that says `running` next to a process that is driving no such run. Deriving it
rather than stamping it at startup is deliberate -- a startup sweep would have
to decide that *no other process* is driving that run, which this build has no
way to know and would be asserting rather than observing.

It is emphatically not `failed`. A failed run tried and broke; an interrupted
one was still going when the lights went out, and the targets it had already
authored are on the log and reachable. Folding the two together would tell a
reader that work which exists did not happen."""


class AuthoringActivity:
    """One course-authoring run's status per project, over a durable record.

    Both collaborators are required rather than defaulted to None. A no-op
    default here would make "the durable half was never wired up" and "it works"
    indistinguishable from every test and every surface -- which is the failure
    mode CLAUDE.md's Events section describes, and the precise bug this class
    was changed to fix.
    """

    def __init__(
        self,
        runs: AggregateRepository[CourseAuthoringRun],
        records: AuthoringRunRunner,
    ) -> None:
        self._runs = runs
        self._records = records
        self._running: dict[UUID, dict[str, Any]] = {}
        self._tasks: dict[UUID, asyncio.Task] = {}
        #: The one target's coroutine currently being awaited, per project.
        #: Held so `cancel` can stop the model turn in hand rather than only
        #: the ones after it -- see `cancel`.
        self._inflight: dict[UUID, asyncio.Task] = {}
        #: The targets a live run has finished, as the *same list object* the
        #: driving loop appends to. `cancel` counts what it abandoned off this
        #: rather than off the announced frame: a frame is rebuilt at the top of
        #: each iteration, so between a target's turn returning and the next
        #: iteration starting it is one target behind, and a cancel landing in
        #: that window would report one more abandoned than there was.
        self._done: dict[UUID, list[str]] = {}
        self._cancelled: set[UUID] = set()
        self._listeners: set[asyncio.Queue] = set()

    async def start(
        self,
        project_id: UUID,
        targets: Sequence[str],
        run: Callable[[UUID, str], Awaitable[Any]],
        *,
        kind: str,
    ) -> dict[str, Any]:
        """Author every slug in `targets`, in order, in the background.

        `run` is a factory taking the run id and one target slug, for
        `SeedingActivity.start`'s reason: a caller refused by the check below
        has not been handed a live coroutine to leave unawaited.

        Targets are authored **sequentially**, not gathered. Each is three
        model turns against one endpoint, and running eight areas concurrently
        against a local server is how you turn a slow feature into a failed
        one. Sequential also means the per-area progress below is meaningful
        rather than eight things all at 0%.

        **The start is appended before this returns**, not from inside the
        background task. A 202 answered before the run exists on the log leaves
        a window in which a restart loses a run the caller has already been
        told about -- small, and exactly the window this whole change is about
        closing.
        """
        existing = self.active(project_id)
        if existing is not None:
            raise RunAlreadyActive(project_id, UUID(existing["run_id"]))

        run_id = uuid4()
        aggregate = self._runs.create_new(run_id)
        aggregate.execute(
            StartCourseAuthoringRun(
                run_id=run_id,
                project_id=project_id,
                kind=kind,
                targets=tuple(targets),
                started_at=datetime.now(UTC),
            )
        )
        await self._runs.save(aggregate)

        frame = {
            "type": AUTHORING,
            "project_id": str(project_id),
            "run_id": str(run_id),
            "status": "running",
            "kind": kind,
            "targets": list(targets),
            "completed": [],
            "sessions": [],
            "failures": [],
            "current": targets[0] if targets else None,
        }
        completed: list[str] = []
        self._running[project_id] = frame
        self._done[project_id] = completed
        self._cancelled.discard(project_id)
        self._announce(frame)
        self._tasks[project_id] = asyncio.ensure_future(
            self._drive(project_id, run_id, tuple(targets), run, kind, completed)
        )
        return frame

    async def _drive(
        self,
        project_id: UUID,
        run_id: UUID,
        targets: tuple[str, ...],
        run: Callable[[UUID, str], Awaitable[Any]],
        kind: str,
        completed: list[str],
    ) -> None:
        sessions: list[str] = []
        failures: list[dict[str, str]] = []
        stopped = False

        for target in targets:
            if project_id in self._cancelled:
                stopped = True
                break
            self._running[project_id] = {
                **self._running[project_id],
                "current": target,
                "completed": list(completed),
                "sessions": list(sessions),
                "failures": list(failures),
            }
            self._announce(self._running[project_id])

            # The target's work is its own task so `cancel` has something to
            # cancel that is not this loop. Cancelling the loop instead would
            # stop the model turn and also stop the appends below it, leaving
            # the run permanently `running` on the log -- a person pressing
            # stop would produce exactly the state this change exists to
            # remove.
            inflight = asyncio.ensure_future(run(run_id, target))
            self._inflight[project_id] = inflight
            try:
                outcome = await inflight
            except asyncio.CancelledError:
                # The inner task was cancelled, not this one, so this handler
                # runs to completion and the settle below still happens.
                stopped = True
                break
            except Exception as error:  # noqa: BLE001 -- reported from a task, not raised
                # One area's failure does not abandon the rest. A run over
                # eight areas that stops at the third because one model
                # call timed out has thrown away five areas of work that
                # would have succeeded, and the person watching cannot
                # tell a refusal from a crash. Failures are collected and
                # reported per target instead.
                failures.append({"target": target, "detail": str(error)})
                await self._record(run_id, RecordAuthoringFailure(run_id, target, str(error)))
            else:
                completed.append(target)
                sessions.append(str(outcome.session_id))
                await self._record(
                    run_id, RecordAuthoredCourse(run_id, target, outcome.session_id)
                )
            finally:
                self._inflight.pop(project_id, None)

        # "done" even with failures in it, and the failures are listed. A run
        # that authored seven of eight areas did not fail, and calling it
        # failed would hide seven courses that exist.
        status = (
            "cancelled" if stopped else ("failed" if failures and not completed else "done")
        )
        await self._record(run_id, SettleCourseAuthoringRun(run_id, status, datetime.now(UTC)))

        finished = {
            "type": AUTHORING,
            "project_id": str(project_id),
            "run_id": str(run_id),
            "status": status,
            "kind": kind,
            "targets": list(targets),
            "completed": completed,
            "failures": failures,
            # Parallel to `completed` on the wire, and unzipped from pairs on
            # the way out of the table -- see `AuthoringRunRow.authored`. Built
            # here from two lists appended in one loop iteration, which is the
            # same guarantee by a weaker mechanism; the reader that has to cope
            # with them disagreeing is `courseLinks` in the browser.
            "sessions": sessions,
            "current": None,
        }
        self._running.pop(project_id, None)
        self._done.pop(project_id, None)
        self._cancelled.discard(project_id)
        self._announce(finished)

    async def _record(self, run_id: UUID, command: Any) -> None:
        """Append one fact about a run that is already started."""
        aggregate = await self._runs.load(run_id)
        aggregate.execute(command)
        await self._runs.save(aggregate)

    def cancel(self, project_id: UUID) -> int:
        """Stop this project's run. Returns how many targets it abandoned.

        A count rather than a bool, matching `cancel_extraction_queue` and for
        its reason: the caller can say "stopped 6" rather than guessing from a
        status it re-reads a moment later. The count is the targets that will
        now never be written -- including the one in hand, because stopping it
        mid-turn is the point.

        **What it does not do is discard what the run already wrote.** Those
        courses exist, in sessions whose ids are already on the log, and the
        settle below records the run as `cancelled` with them still listed. A
        cancel that reported an empty run would be lying about files a reader
        can open.

        Synchronous, unlike `start`: the append that records the cancellation
        is made by the driving task on its way out, not here. Doing it here
        instead would mean two writers racing to settle one run, and the loser
        would raise `CommandRejectedError` out of a background task.
        """
        frame = self._running.get(project_id)
        task = self._tasks.get(project_id)
        if frame is None or task is None or task.done():
            return 0
        self._cancelled.add(project_id)
        inflight = self._inflight.get(project_id)
        if inflight is not None and not inflight.done():
            inflight.cancel()
        return len(frame["targets"]) - len(self._done.get(project_id, ()))

    def active(self, project_id: UUID) -> dict[str, Any] | None:
        task = self._tasks.get(project_id)
        if task is None or task.done():
            return None
        return self._running.get(project_id)

    def current(self, project_id: UUID) -> dict[str, Any] | None:
        """The live frame, from memory. `None` once the run has settled.

        Deliberately not read from the table. The durable row knows a run is
        running and cannot know which target is in hand, so a `current` served
        from it would be a progress line frozen at the start for twenty
        minutes -- worse than the honest `None` a reconnecting tab gets, which
        sends it to `last` instead.
        """
        return self._running.get(project_id)

    async def last(self, project_id: UUID) -> dict[str, Any] | None:
        """The most recent run this process is not driving, read from the log.

        The newest row that is not the live run, rather than simply the newest:
        while a run is in flight, `current` is already reporting it, and
        answering `last` with the same run would make a panel say "last run
        wrote 0 of 9" underneath its own progress bar.

        A row still marked `running` that this process is not driving is
        reported as `_INTERRUPTED` -- see there. Its completed targets and
        their session ids come back intact, which is the entire point: those
        courses exist and were unreachable before this table did.
        """
        live = self._live_run_id(project_id)
        for row in await self._records.recent_for_project(project_id):
            if row.id == live:
                continue
            return self._frame_of(row)
        return None

    async def authored_session_for(self, project_id: UUID, target: str) -> UUID | None:
        """Which session holds `target`'s course markdown, or `None` if no run
        has ever authored it.

        A delegation to `AuthoringRunStore.authored_session_for` -- see there
        for why it scans 200 runs deep rather than reusing `last`'s window.
        It is here so a route reading one course's files goes through the same
        object it already asks about runs, rather than being handed a second
        collaborator that answers a question this one is already the front for.

        Deliberately not filtered by run status. A target completed by a run
        that was later cancelled or interrupted still wrote real files into a
        real session, and refusing to name that session would be the console's
        version of the refusal `export.py` stopped making.
        """
        return await self._records.authored_session_for(project_id, target)

    def _live_run_id(self, project_id: UUID) -> UUID | None:
        frame = self.active(project_id)
        return None if frame is None else UUID(frame["run_id"])

    def _frame_of(self, row: AuthoringRunRow) -> dict[str, Any]:
        """One stored run, in the shape the wire already speaks.

        `completed` and `sessions` are unzipped from `row.authored` here, so
        the two arrays cannot disagree in length however the row was written.
        `current` is always `None`: a stored run has no target in hand, whether
        it settled or the process driving it died.
        """
        return {
            "type": AUTHORING,
            "project_id": str(row.project_id),
            "run_id": str(row.id),
            "status": _INTERRUPTED if row.status == "running" else row.status,
            "kind": row.kind,
            "targets": list(row.targets),
            "completed": [entry["target"] for entry in row.authored],
            "sessions": [entry["session_id"] for entry in row.authored],
            "failures": [
                {"target": entry["target"], "detail": entry.get("detail", "")}
                for entry in row.failures
            ],
            "current": None,
        }

    async def wait(self, project_id: UUID) -> None:
        """Block until this project's run settles. For tests, not routes."""
        task = self._tasks.get(project_id)
        if task is not None:
            # A cancelled driver is not the expected end of `cancel` -- that
            # cancels the inner turn and lets the loop settle -- but a process
            # shutting down cancels everything, and a waiter re-raising there
            # reports a teardown as a test failure.
            with suppress(asyncio.CancelledError):
                await task

    def listen(self) -> asyncio.Queue:
        queue: asyncio.Queue = asyncio.Queue()
        self._listeners.add(queue)
        return queue

    def stop_listening(self, queue: asyncio.Queue) -> None:
        self._listeners.discard(queue)

    def _announce(self, payload: dict[str, Any]) -> None:
        for queue in self._listeners:
            queue.put_nowait(payload)
