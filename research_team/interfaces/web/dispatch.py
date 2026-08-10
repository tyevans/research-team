"""What has been dispatched at this project's topics, and what is waiting.

Shaped like `seeding.py`, which is shaped like `extraction.py`, which is
shaped like `activity.py` -- the same problem each time: content that matters
now, leaves no event behind, and has to survive a reconnect. Two things make
this one different, and both come from where the control lives.

**It queues rather than refusing.** `SeedingActivity.start` and
`ResearchSupervisor.start` both raise `RunAlreadyActive`, which is correct for
a control that appears once on a page. A dispatch control appears on *every
topic row*: with forty topics, "the project is busy" is the answer to nearly
every second press, and a UI whose primary control usually refuses is a UI
people stop pressing. So this is FIFO, at most one in flight per project,
draining in one background task.

The constraint being respected is `Project.decide`'s refusal of a second
`JoinProject`, and that refusal is not a lock protecting a race -- it is the
filesystem model. The project stores a lineage pointer, and two concurrent
holders would mean two divergent tips and no answer to "what are this
project's files". One at a time is therefore not a limitation to be relaxed
later; it is the property the queue exists to preserve.

**The last outcome is kept per topic, not per project.** Each topic row shows
its own last result, so a project's forty topics need forty slots rather than
one that the most recent dispatch overwrites.

**Provisional, and never durable.** Queued / running / done is not a fact the
log records -- the log has `FileWritten` and the topic's own events, and
nothing that says a dispatch was requested. The cost is stated plainly: a
restart loses every pending dispatch, and the catch-up route will answer with
an empty queue. That is the same trade every supervisor here makes, but a
queued dispatch is a *user intention* rather than a running process, and losing
an intention is worse than losing a process. It is accepted rather than fixed
because the fix is a `TopicDispatch` aggregate -- four events in the permanent
vocabulary and a decision about what a `DispatchStarted` with no terminal
event means -- which is not worth buying until someone has actually lost work
to it.
"""

import asyncio
from collections import deque
from collections.abc import Awaitable, Callable
from contextlib import suppress
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

from research_team.application.topic_dispatch import DispatchRun
from research_team.application.workers import DispatchSnapshot

DISPATCH = "Dispatch"
"""The frame type on the live feed, PascalCase like `Seeding` beside it.

A side channel and not a domain event, which is what puts it in this family
rather than with the `Graph` and `Corpus` frames added alongside: those carry
a feed position and replay on `Last-Event-ID`, because they are projections of
events that were genuinely appended. Nothing here is appended anywhere, so
nothing here can be replayed -- hence the catch-up route.

**A frame type published here and not switched on in `decodeFrame` is dropped
silently.** The client's `default:` branch parses anything unrecognised as a
log frame, fails, and returns `null` with no log. The `Extraction` case
carries a comment recording exactly that bug.
"""


@dataclass
class _Pending:
    """One press, before it has run."""

    dispatch_id: UUID
    topic_id: UUID
    action: str
    question: str
    run: Callable[[UUID], Awaitable[DispatchRun]]


class DispatchQueue:
    """One project's dispatches: the running one, the waiting ones, the last ones.

    One object rather than a queue and a separate activity channel, following
    `ExtractionChannel`'s reasoning verbatim: they are two views of one buffer,
    and "a composition root handed mismatched halves would show a roster that
    disagreed with its own pane, and nothing in either signature would have
    caught it". This is a deliberate departure from the design note, which
    proposed `dispatch` and `dispatch_activity` as two `create_app` parameters
    -- the note's own §9 then warns about exactly the failure two parameters
    invite.
    """

    def __init__(self) -> None:
        self._pending: dict[UUID, deque[_Pending]] = {}
        self._running: dict[UUID, dict[str, Any]] = {}
        self._started: dict[UUID, datetime] = {}
        self._finished: dict[UUID, dict[UUID, dict[str, Any]]] = {}
        self._tasks: dict[UUID, asyncio.Task] = {}
        self._draining: set[UUID] = set()
        self._listeners: set[asyncio.Queue] = set()

    # ---------------- what the route drives ----------------

    def start(
        self,
        project_id: UUID,
        topic_id: UUID,
        action: str,
        run: Callable[[UUID], Awaitable[DispatchRun]],
        question: str = "",
    ) -> dict[str, Any]:
        """Enqueue a dispatch, starting the drain if this project has none going.

        Answers `queued` even when the queue is empty and this item is about to
        run. That is honest rather than sloppy: at the moment this returns, the
        drain task has been scheduled and has not run, so nothing has started.
        The `running` frame follows on the next turn of the loop and reaches
        the browser over SSE. Claiming `running` here would be a status the
        server invented for the response and then had to correct.

        `run` is a factory rather than a coroutine already in hand, matching
        `SeedingActivity.start`: an item that sits in a deque for a minute
        would otherwise be a live coroutine nobody has awaited, and one that
        is cancelled while queued would be one nobody ever will.

        `_draining` is a set maintained synchronously rather than a
        `task.done()` check, because `done()` is false for the whole window
        between the drain's last item finishing and the coroutine returning --
        a press landing in that window would be enqueued behind a task that
        was already leaving, and would never run.
        """
        pending = _Pending(uuid4(), topic_id, action, question, run)
        waiting = self._pending.setdefault(project_id, deque())
        waiting.append(pending)

        frame = self._frame(project_id, pending, "queued", position=len(waiting))
        self._announce(frame)

        if project_id not in self._draining:
            self._draining.add(project_id)
            self._tasks[project_id] = asyncio.ensure_future(self._drain(project_id))
        return frame

    def cancel(self, project_id: UUID) -> int:
        """Stop what is running and drop everything waiting. Returns how many went.

        Per project rather than per dispatch, matching `ResearchSupervisor.cancel`.
        A per-dispatch cancel that could pull the third item out of the middle
        of the deque is a nicety and is deliberately not built -- the UI shows
        one stop control on the pane header rather than one per queued row, so
        it does not offer an action this cannot honour.

        The running dispatch's own `finally` is what releases the project: a
        cancelled task raises `CancelledError` inside `TopicDispatcher.dispatch`
        at its `await`, and that method releases in `finally` precisely so a
        dispatch that dies does not die holding the project.
        """
        waiting = self._pending.pop(project_id, deque())
        for pending in waiting:
            self._announce(self._frame(project_id, pending, "cancelled"))
        dropped = len(waiting)

        task = self._tasks.get(project_id)
        if task is not None and not task.done():
            task.cancel()
            dropped += 1
        return dropped

    # ---------------- what the route and the roster read ----------------

    def current(self, project_id: UUID) -> dict[str, Any] | None:
        """The running dispatch's frame, for a tab that arrived mid-run."""
        return self._running.get(project_id)

    def queued(self, project_id: UUID) -> list[dict[str, Any]]:
        """Everything waiting, in order, numbered from 1 as of right now.

        Recomputed on read rather than stored on each frame, so a position is
        never stale: a queued item's number changes every time the one ahead
        of it finishes, and a number captured at press time would tell the
        third presser they are still third long after they were not.
        """
        waiting = self._pending.get(project_id) or deque()
        return [
            self._frame(project_id, pending, "queued", position=index)
            for index, pending in enumerate(waiting, start=1)
        ]

    def last(self, project_id: UUID, topic_id: UUID) -> dict[str, Any] | None:
        """How this topic's most recent dispatch went.

        Kept rather than cleared on completion, for `ExtractionActivity.last`'s
        reason: nothing durable records a dispatch's outcome, so this is the
        only account of it. Per topic because that is where the UI shows it --
        a failure chip belongs on the row whose button produced it.
        """
        return self._finished.get(project_id, {}).get(topic_id)

    def finished(self, project_id: UUID) -> list[dict[str, Any]]:
        """Every topic's last outcome, for the catch-up read."""
        return list(self._finished.get(project_id, {}).values())

    def in_flight(self, project_id: UUID) -> DispatchSnapshot | None:
        """What `WorkerRoster` needs, or None. Satisfies `DispatchesInFlight`."""
        running = self._running.get(project_id)
        if running is None:
            return None
        return DispatchSnapshot(
            topic_id=running["topic_id"],
            action=running["action"],
            question=running.get("question") or "",
            queued=len(self._pending.get(project_id) or ()),
            started_at=self._started.get(project_id),
        )

    def active_projects(self) -> tuple[UUID, ...]:
        """Every project with a dispatch running. Satisfies `DispatchesInFlight`.

        `_running` only, not `_pending`: a queued dispatch is not a worker --
        `in_flight` reports it as `queued` *on* the running one, and a project
        whose queue holds work but whose runner has not started it yet has
        nothing for the roster to show.
        """
        return tuple(self._running)

    async def wait(self, project_id: UUID) -> None:
        """Block until this project's queue drains. For tests, not routes."""
        task = self._tasks.get(project_id)
        if task is not None:
            # A cancelled drain is the expected end of `cancel`, not a failure
            # for a waiter to re-raise at its own call site.
            with suppress(asyncio.CancelledError):
                await task

    # ---------------- the feed ----------------

    def listen(self) -> asyncio.Queue:
        """Subscribe to dispatch frames.

        Unbounded, matching every other side channel here: a dropped frame
        leaves a gap in the row's account with nothing to reconcile it. Not
        seeded with the current state -- a subscriber gets that from the
        catch-up route, which it must call anyway to learn about a queue that
        formed before it connected.
        """
        queue: asyncio.Queue = asyncio.Queue()
        self._listeners.add(queue)
        return queue

    def stop_listening(self, queue: asyncio.Queue) -> None:
        self._listeners.discard(queue)

    # ---------------- internals ----------------

    async def _drain(self, project_id: UUID) -> None:
        """Run this project's dispatches one at a time until none are waiting.

        A failure is recorded and the loop continues. Stopping on the first
        one would turn a single model timeout into a project that ignores
        every later press -- and the log would say nothing about why, because
        a dispatch records no event of its own.
        """
        try:
            while True:
                waiting = self._pending.get(project_id) or deque()
                if not waiting:
                    return
                pending = waiting.popleft()

                self._started[project_id] = datetime.now(UTC)
                running = self._frame(project_id, pending, "running")
                self._running[project_id] = running
                self._announce(running)

                try:
                    outcome = await pending.run(pending.dispatch_id)
                except asyncio.CancelledError:
                    self._announce(self._frame(project_id, pending, "cancelled"))
                    raise
                except Exception as error:  # noqa: BLE001 -- reported, not raised, from a task
                    finished = self._frame(project_id, pending, "failed", detail=str(error))
                else:
                    finished = self._frame(
                        project_id,
                        pending,
                        "done",
                        path=outcome.path,
                        session_id=str(outcome.session_id),
                        question=outcome.question,
                    )

                self._finished.setdefault(project_id, {})[pending.topic_id] = finished
                self._running.pop(project_id, None)
                self._started.pop(project_id, None)
                self._announce(finished)
        finally:
            # Unconditional, so a cancelled drain leaves the project
            # dispatchable. Without this, every later press would be enqueued
            # behind a `_draining` entry belonging to a task that had gone.
            self._running.pop(project_id, None)
            self._started.pop(project_id, None)
            self._draining.discard(project_id)

    def _frame(
        self,
        project_id: UUID,
        pending: _Pending,
        status: str,
        **extra: Any,
    ) -> dict[str, Any]:
        """One frame, in the shape both the feed and the catch-up route send.

        One builder rather than a literal per transition, because the catch-up
        route and the SSE channel must send byte-identical shapes -- a browser
        that reconciled a reconnect against a differently-shaped frame would
        render the same dispatch two ways.
        """
        question = extra.pop("question", None) or pending.question
        return {
            "type": DISPATCH,
            "project_id": str(project_id),
            "topic_id": str(pending.topic_id),
            "dispatch_id": str(pending.dispatch_id),
            "action": pending.action,
            "question": question,
            "status": status,
            **extra,
        }

    def _announce(self, payload: dict[str, Any]) -> None:
        for queue in self._listeners:
            queue.put_nowait(payload)
